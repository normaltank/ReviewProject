"""Explicit offline producer: frozen grounding to new candidates, never import."""
from collections import Counter
from pathlib import Path
import re
from types import SimpleNamespace

from .batch import checked_local, source_state
from .core import digest, require, EDIT_FIELDS, validate_candidate, ReviewError
from .framework import load_json
from .store import encoded, read_input
from .review_links import unreferenced_ranges
from .understanding import candidate_value

LIMIT = 10_000_000


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value), 'E_REPLAY_RUN_ID')


def scope(value, sections):
    require(isinstance(value, dict) and {'section_id', 'window_start', 'window_end'} <= set(value), 'E_REPLAY_WINDOW')
    sid, start, end = (value[k] for k in ('section_id', 'window_start', 'window_end'))
    require(isinstance(sid, str) and sid in sections and type(start) is int and type(end) is int
            and 0 <= start < end <= len(sections[sid]['text']), 'E_REPLAY_WINDOW')
    return sid, start, end


def read_artifact(folder, name):
    raw = read_input(checked_local(folder / name), LIMIT, 'E_REPLAY_LIMIT')
    return load_json(raw), digest(raw)


def semantic_key(candidate):
    if not isinstance(candidate, dict):
        return None
    return encoded({k: v for k, v in candidate.items() if k not in {'external_id', 'review_flags'}})


def replay(workspace, from_run, run_id):
    from experiments import extract_local as adapter
    identifier(from_run); identifier(run_id)
    require(from_run != run_id, 'E_REPLAY_RUN_EXISTS')
    workspace = checked_local(workspace)
    state = source_state(workspace)
    require(not any(r['run_id'] == run_id for r in state.get('extraction_runs', [])), 'E_REPLAY_RUN_EXISTS')
    previous = next((r for r in state.get('extraction_runs', []) if r['run_id'] == from_run), None)
    require(previous is not None, 'E_REPLAY_RUN')
    parent = checked_local(workspace / 'model-artifacts')
    folder = checked_local(parent / from_run)
    target = checked_local(parent / run_id)
    require(not target.exists(), 'E_REPLAY_RUN_EXISTS')
    original, payload_file_hash = read_artifact(folder, 'candidates.json')
    require(isinstance(original, dict) and original == previous.get('payload') and
            digest(encoded(original)) == previous['payload_sha256'], 'E_REPLAY_PAYLOAD_HASH')
    require(original['source_id'] == state['source']['source_id'] and original['run_id'] == from_run, 'E_REPLAY_SOURCE')
    allowed = {}
    sections = {s['section_id']: s for s in state['sections']}
    for item in original['sections']:
        require(isinstance(item, dict) and set(item) == {'section_id', 'text_sha256'}, 'E_REPLAY_SECTION')
        sid = item['section_id']
        require(isinstance(sid, str) and sid in sections and sid not in allowed, 'E_REPLAY_SECTION')
        section = sections[sid]
        require(section['visibility'] in {'author_visible', 'visibility_unknown'}, 'E_REPLAY_PRIVATE')
        require(item['text_sha256'] == digest(section['text'].encode('utf-8')), 'E_REPLAY_SECTION_HASH')
        allowed[sid] = section
    require(allowed, 'E_REPLAY_SECTION')
    grounding, grounding_hash = read_artifact(folder, 'grounding.json')
    windows, windows_hash = read_artifact(folder, 'windows.json')
    require(isinstance(grounding, list) and isinstance(windows, list) and len(grounding) <= 1000 and len(windows) <= 1000,
            'E_REPLAY_SHAPE')
    config = original['config']
    historical_hashes = []
    for name, actual in (('grounding', grounding_hash), ('windows', windows_hash)):
        if name + '_sha256' in config:
            require(config[name + '_sha256'] == actual, 'E_REPLAY_ARTIFACT_HASH')
            historical_hashes.append(name)
    size = config.get('window_chars')
    require(type(size) is int and 300 <= size <= 6000, 'E_REPLAY_WINDOW_CONFIG')
    expected = {(sid, offset, offset + len(text)) for sid, section in allowed.items()
                for offset, text, _ in adapter.windows(section, size) if text.strip()}
    require(len(expected) <= 1000, 'E_REPLAY_LIMIT')
    outcomes = {}
    for item in windows:
        key = scope(item, allowed)
        require(set(item) <= {'section_id', 'window_start', 'window_end', 'status', 'window_kind', 'candidates', 'errors', 'error_type', 'error_detail'}, 'E_REPLAY_WINDOW')
        require(key in expected and key not in outcomes and item.get('status') in {'converted', 'failed', 'skipped'}, 'E_REPLAY_WINDOW')
        require(isinstance(item.get('errors', []), list) and all(isinstance(e, str) for e in item.get('errors', [])), 'E_REPLAY_WINDOW')
        outcomes[key] = item
    documents = {}
    for item in grounding:
        require(isinstance(item, dict), 'E_REPLAY_GROUNDING')
        require(set(item) in ({'scope', 'extractions'}, {'section_id', 'window_start', 'window_end', 'extractions'}), 'E_REPLAY_GROUNDING')
        if 'scope' in item:
            require(isinstance(item['scope'], dict) and set(item['scope']) == {'section_id', 'window_start', 'window_end'}, 'E_REPLAY_GROUNDING')
        key = scope(item.get('scope', item), allowed)
        require(key in expected and key not in documents and isinstance(item['extractions'], list)
                and len(item['extractions']) <= 10000, 'E_REPLAY_GROUNDING')
        extractions = []
        for raw in item['extractions']:
            require(isinstance(raw, dict) and set(raw) == {'class', 'text', 'attributes', 'interval'} and
                isinstance(raw['class'], str) and isinstance(raw['text'], str) and
                (raw['attributes'] is None or isinstance(raw['attributes'], dict)), 'E_REPLAY_GROUNDING')
            interval = raw['interval']
            require(interval is None or (isinstance(interval, list) and len(interval) == 2 and
                all(type(n) is int for n in interval) and 0 <= interval[0] < interval[1] <= key[2] - key[1]), 'E_REPLAY_INTERVAL')
            extractions.append(SimpleNamespace(extraction_class=raw['class'], extraction_text=raw['text'],
                attributes=raw['attributes'], char_interval=None if interval is None else SimpleNamespace(start_pos=interval[0], end_pos=interval[1])))
        documents[key] = SimpleNamespace(extractions=extractions)
    candidates, new_errors, diagnostics = [], [], []
    resolved = 0
    parent_keys = {semantic_key(c) for c in original['candidates']}
    for number, key in enumerate(sorted(expected)):
        outcome = outcomes.get(key)
        if outcome is None:
            new_errors.append('E_REPLAY_WINDOW_MISSING')
            continue
        if outcome['status'] != 'converted':
            new_errors.extend(outcome.get('errors') or ['E_REPLAY_UPSTREAM_WINDOW'])
            continue
        if key not in documents:
            new_errors.extend(outcome.get('errors', []))
            new_errors.append('E_REPLAY_GROUNDING_MISSING')
            continue
        sid, start, end = key
        section = allowed[sid]
        text = section['text'][start:end]
        legacy, _, old_errors = adapter.convert(documents[key], section, text, start, f'replay-{number}-')
        converted, _, errors = adapter.convert(documents[key], section, text, start, f'replay-{number}-', policy=adapter.OFFLINE_SINGLE_PAIR)
        # Remove only a demonstrated pairing failure from an original accepted
        # producer candidate. Unrelated producer/import errors remain visible.
        eligible = sum(bool(new.get('conditional_actions')) and semantic_key(old) in parent_keys
                       for old, new in zip(legacy, converted))
        count = min(eligible, Counter(outcome.get('errors', []))['E_MODEL_BRANCH_PAIRING'],
                    max(0, Counter(old_errors)['E_MODEL_BRANCH_PAIRING'] - Counter(errors)['E_MODEL_BRANCH_PAIRING']))
        resolved += count
        diagnostics.append(dict(section_id=sid, window_start=start, window_end=end, resolved_pairing_errors=count, errors=errors))
        upstream = Counter(outcome.get('errors', []))
        upstream['E_MODEL_BRANCH_PAIRING'] -= count
        new_errors.extend((Counter(errors) | +upstream).elements())
        for candidate in converted:
            flags = candidate['review_flags']
            if original['model'] == 'deepseek-flash':
                flags = [f for f in flags if f != 'local_model_candidate'] + ['external_model_candidate']
            candidate['review_flags'] = list(dict.fromkeys(flags + ['offline_grounding_replay', 'model_semantics_unverified']))
            candidates.append(candidate)
    inherited = list(original.get('errors', []))
    removed = 0
    for _ in range(resolved):
        if 'E_MODEL_BRANCH_PAIRING' in inherited:
            inherited.remove('E_MODEL_BRANCH_PAIRING'); removed += 1
    # A multiset maximum preserves independent error counts without counting
    # unchanged conversion errors twice merely because they were re-evaluated.
    merged = Counter(inherited) | Counter(new_errors)
    errors = list(merged.elements())
    for rejected in previous.get('rejected', []):
        errors.extend(['E_REPLAY_UPSTREAM_REJECTED', rejected.get('error_code', 'E_EXTRACTION_CANDIDATE')])
    if previous['status'] == 'partial' and not errors and not removed:
        errors.append('E_REPLAY_UPSTREAM_PARTIAL_UNRESOLVED')
    if original.get('status') == 'failed' or previous['status'] == 'failed':
        errors.append('E_REPLAY_UPSTREAM_FAILED')
    unique = {}
    for candidate in candidates:
        unique.setdefault(semantic_key(candidate), candidate)
    rejected = []
    for index, candidate in enumerate(unique.values()):
        try:
            preview = candidate_value(state, candidate['section_id'], f'replay-preview-{index}',
                {k: v for k, v in candidate.items() if k in EDIT_FIELDS}, 'model_candidate')
            preview['status'] = 'pending_review'
            validate_candidate(preview, state, allow_pending=True)
        except ReviewError as error:
            errors.append(str(error))
            rejected.append(dict(index=index, error=str(error)))
    status = 'failed' if 'E_REPLAY_UPSTREAM_FAILED' in errors or (errors and not unique) else 'complete'
    result = dict(schema_version=1, source_id=original['source_id'], run_id=run_id,
        extractor='offline-grounding-replay-v1', model=original['model'], status=status, errors=errors,
        sections=original['sections'], candidates=list(unique.values()), config=dict(
            from_run=from_run, original_payload_sha256=previous['payload_sha256'], original_payload_file_sha256=payload_file_hash,
            original_grounding_sha256=grounding_hash, original_windows_sha256=windows_hash,
            historical_artifact_hashes_verified=historical_hashes,
            artifact_provenance='current_local_files_not_retroactive_model_output_proof',
            original_extractor=original['extractor'], original_model=original['model'],
            original_protocol=config.get('protocol', 'v3'), conversion_policy=adapter.OFFLINE_SINGLE_PAIR,
            adapter_sha256=digest(Path(adapter.__file__).read_bytes()), producer_sha256=digest(Path(__file__).read_bytes()),
            model_requests=0, external_model_requests=0, score_blind=True, input_scope='existing_ordinary_grounding_only'))
    report = dict(schema_version=1, run_id=run_id, from_run=from_run, windows=diagnostics,
        missing_windows=len(expected - set(outcomes)), original_status=previous['status'],
        resolved_pairing_errors=removed, preserved_errors=errors, auto_imported=False, model_requests=0)
    report['core_validation_rejections'] = rejected
    coverage_source = dict(candidates=[dict(value=c) for c in unique.values()])
    report['coverage'] = [dict(section_id=sid, label='未被本次重放候选引用的原文，不等于已证实漏提',
        unreferenced=unreferenced_ranges(coverage_source, section, include_whitespace=True)) for sid, section in allowed.items()]
    require(len(encoded(result)) <= LIMIT and len(encoded(report)) <= LIMIT, 'E_REPLAY_LIMIT')
    current = source_state(workspace)
    require(current['source'] == state['source'] and any(r['run_id'] == from_run and r['payload_sha256'] == previous['payload_sha256']
            for r in current.get('extraction_runs', [])), 'E_REPLAY_SOURCE_CHANGED')
    for name, fingerprint in (('candidates.json', payload_file_hash), ('grounding.json', grounding_hash), ('windows.json', windows_hash)):
        require(digest(read_input(checked_local(folder / name), LIMIT, 'E_REPLAY_LIMIT')) == fingerprint, 'E_REPLAY_ARTIFACT_CHANGED')
    checked_local(target)
    # Exclusive creation; no overwrite, no Workspace write-side initializer.
    target.mkdir()
    for name, value in (('candidates.json', result), ('diagnostics.json', report)):
        with (target / name).open('xb') as stream:
            stream.write(encoded(value))
    return result
