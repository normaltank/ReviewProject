"""Offline evidence search; immutable sidecars never change business revisions."""
from __future__ import annotations

import math
import hashlib
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import re

from .batch import checked_local, read_json
from .core import ReviewError, digest, require
from .framework import framework_digest
from .framework import load_json
from .store import encoded, read_input

MODEL = 'BAAI/bge-small-zh-v1.5'
MAX_RUNS = 100
LIMIT = 2_000_000
RANKING = dict(ranking_version=2, ranking_unit='source_candidate', aggregation='max_evidence_score')


def ranked_hits(corpus, scores, top_k):
    """Stable max-evidence ranking of exact source/candidate identities."""
    winners, seen = [], set()
    for index in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
        item = corpus[index]
        identity = (item['source_id'], item['candidate_id'])
        if identity in seen:
            continue
        seen.add(identity)
        winners.append(dict(item, rank=len(winners) + 1, score=float(scores[index])))
        if len(winners) == top_k:
            break
    return winners


def finite_score(value):
    """JSON integers may exceed float range; malformed sidecars stay isolated."""
    if type(value) not in {float, int}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def versions(packages):
    result = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = 'unavailable'
    return result


def entries(state):
    result = []
    for source in state['sources']:
        sections = {s['section_id']: s for s in source['sections']}
        for item in source['candidates']:
            candidate = item['value']
            section = sections[candidate['section_id']]
            require(section['visibility'] in {'author_visible', 'visibility_unknown'}, 'E_RETRIEVAL_PRIVATE')
            for index, evidence in enumerate(candidate['evidence']):
                require(section['text'][evidence['start']:evidence['end']] == evidence['quote'], 'E_RETRIEVAL_QUOTE')
                result.append(dict(source_id=source['source']['source_id'], candidate_id=candidate['candidate_id'],
                    candidate_sha256=item['candidate_sha256'], section_id=section['section_id'],
                    section_sha256=digest(section['text'].encode('utf-8')), source_revision=source['revision'],
                    visibility=section['visibility'], evidence_index=index,
                    **{k: evidence[k] for k in ('start', 'end', 'quote')}))
    require(len(result) <= 10000 and len(encoded(result)) <= LIMIT, 'E_RETRIEVAL_LIMIT')
    return result


def binding(state):
    return framework_digest(dict(batch_id=state['batch_id'], sources=state['sources']))


def model_config(model_path):
    require(model_path is not None, 'E_RETRIEVAL_MODEL_REQUIRED')
    path = checked_local(model_path)
    require(path.is_dir(), 'E_RETRIEVAL_MODEL_REQUIRED')
    config_path = checked_local(path / 'tokenizer_config.json')
    require(config_path.is_file(), 'E_RETRIEVAL_MODEL_REQUIRED')
    tokenizer_config = load_json(read_input(config_path, 64000, 'E_RETRIEVAL_LIMIT'))
    lengths = [tokenizer_config[k] for k in ('model_max_length', 'max_length') if k in tokenizer_config]
    require(lengths and all(type(n) is int and n > 0 for n in lengths) and min(lengths) == 512,
            'E_RETRIEVAL_MODEL_CONFIG')
    files = []
    for item in sorted(path.rglob('*')):
        checked_local(item)
        if item.is_file():
            require(len(files) < 1000, 'E_RETRIEVAL_LIMIT')
            with item.open('rb') as stream:
                fingerprint = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append(dict(file=item.relative_to(path).as_posix(), sha256=fingerprint))
    require(files and any(f['file'].endswith('.onnx') for f in files), 'E_RETRIEVAL_MODEL_REQUIRED')
    return dict(model=MODEL, model_files=files, local_files_only=True,
                representation='query_embed/passage_embed', metric='cosine',
                engine_versions=versions(('fastembed', 'onnxruntime', 'numpy', 'tokenizers')),
                providers=['CPUExecutionProvider'], threads=None,
                tokenizer_max_length=512, truncation=True, batch_size=256, parallel=None)


def bge_scores(query, quotes, model_path, encoder=None):
    try:
        import numpy as np
        if encoder is None:
            from fastembed import TextEmbedding
            encoder = TextEmbedding(model_name=MODEL, specific_model_path=str(checked_local(model_path)),
                                    local_files_only=True, providers=['CPUExecutionProvider'])
        passage = np.asarray(list(encoder.passage_embed(quotes)), dtype=float)
        vector = np.asarray(list(encoder.query_embed(query)), dtype=float)
        require(passage.ndim == 2 and vector.shape == (1, passage.shape[1])
                and np.isfinite(passage).all() and np.isfinite(vector).all(), 'E_RETRIEVAL_ENCODING')
        norms = np.linalg.norm(passage, axis=1) * np.linalg.norm(vector[0])
        require((norms > 0).all(), 'E_RETRIEVAL_ENCODING')
        return (passage @ vector[0] / norms).tolist()
    except ReviewError:
        raise
    except ImportError:
        raise ReviewError('E_RETRIEVAL_DEPENDENCY') from None
    except Exception:
        raise ReviewError('E_RETRIEVAL_ENCODING') from None


def lexical_scores(query, quotes):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        matrix = TfidfVectorizer(analyzer='char', ngram_range=(1, 2)).fit_transform([query, *quotes])
        return (matrix[1:] @ matrix[0].T).toarray().ravel().tolist()
    except ImportError:
        raise ReviewError('E_RETRIEVAL_DEPENDENCY') from None
    except Exception:
        raise ReviewError('E_RETRIEVAL_ENCODING') from None


def sidecar_root(workspace):
    return checked_local(workspace.path / 'retrieval-runs')


def restored(workspace, state):
    root = sidecar_root(workspace)
    if not root.exists():
        return []
    require(root.is_dir(), 'E_RETRIEVAL_SIDECAR')
    paths = sorted(root.iterdir())
    require(len(paths) <= MAX_RUNS, 'E_RETRIEVAL_LIMIT')
    runs = []
    for path in paths:
        try:
            require(path.suffix == '.json' and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', path.stem), 'E_RETRIEVAL_SIDECAR')
            require(path.stat().st_size <= LIMIT, 'E_RETRIEVAL_LIMIT')
            run = read_json(path)
            require(run['run_id'] == path.stem and run['schema_version'] == 1, 'E_RETRIEVAL_SIDECAR')
            checksum = run.pop('sha256')
            require(framework_digest(run) == checksum, 'E_RETRIEVAL_SIDECAR')
            require(set(run) == {'schema_version', 'run_id', 'query', 'config', 'input_sha256', 'top_k', 'request_sha256', 'hits'}, 'E_RETRIEVAL_SIDECAR')
            require(isinstance(run['query'], str) and run['query'].strip() and len(run['query']) <= 4000
                    and isinstance(run['config'], dict) and run['config'].get('method') in {'bge', 'lexical'}
                    and type(run['top_k']) is int and 1 <= run['top_k'] <= 100, 'E_RETRIEVAL_SIDECAR')
            require(run['request_sha256'] == framework_digest({k: run[k] for k in ('query', 'config', 'input_sha256', 'top_k')}), 'E_RETRIEVAL_SIDECAR')
            ranking_fields = set(run['config']) & set(RANKING)
            require(not ranking_fields or (ranking_fields == set(RANKING) and
                all(run['config'][k] == v for k, v in RANKING.items()) and
                type(run['config']['ranking_version']) is int), 'E_RETRIEVAL_SIDECAR')
            require(isinstance(run['hits'], list) and len(run['hits']) <= run['top_k'] <= 100, 'E_RETRIEVAL_SIDECAR')
            current = state['material_status'] == 'current' and run['input_sha256'] == binding(state)
            for rank, hit in enumerate(run['hits'], 1):
                require(isinstance(hit, dict) and hit['rank'] == rank and finite_score(hit['score']), 'E_RETRIEVAL_SIDECAR')
            if ranking_fields:
                identities = [(hit['source_id'], hit['candidate_id']) for hit in run['hits']]
                require(len(set(identities)) == len(identities), 'E_RETRIEVAL_SIDECAR')
            if current:
                allowed = entries(state)
                for rank, hit in enumerate(run['hits'], 1):
                    require({k: v for k, v in hit.items() if k not in {'rank', 'score'}} in allowed, 'E_RETRIEVAL_SIDECAR')
            run.update(sha256=checksum, validity='current' if current else 'needs_revalidation')
            # Invalidated text cannot appear as a current hit or link to new material.
            if not current:
                run['hits'] = []
            runs.append(run)
        except (ReviewError, OSError, KeyError, TypeError, ValueError, OverflowError):
            runs.append(dict(run_id='invalid-sidecar', validity='invalid', hits=[]))
    return runs


def retrieve(workspace, *, query_path, run_id, method, top_k=10, model_path=None, encoder=None, score_provider=None):
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id), 'E_RETRIEVAL_RUN_ID')
    require(method in {'bge', 'lexical'} and type(top_k) is int and 1 <= top_k <= 100, 'E_RETRIEVAL_CONFIG')
    try:
        query = read_input(checked_local(query_path), 16000, 'E_RETRIEVAL_QUERY').decode('utf-8')
    except (UnicodeError, OSError):
        raise ReviewError('E_RETRIEVAL_QUERY') from None
    require(query.strip() and len(query) <= 4000, 'E_RETRIEVAL_QUERY')
    state = workspace.state()
    require(state['material_status'] == 'current', 'E_BATCH_SOURCE_CHANGED')
    corpus = entries(state)
    representation = dict(method=method, **(model_config(model_path) if method == 'bge' else dict(
        representation='sklearn-char-tfidf-1-2', metric='cosine', engine_versions=versions(('scikit-learn', 'numpy', 'scipy')),
        analyzer='char', ngram_range=[1, 2], lowercase=True, norm='l2', use_idf=True,
        smooth_idf=True, sublinear_tf=False, fit_scope='query_and_selected_evidence')))
    config = dict(representation, **RANKING)
    request = dict(query=query, config=config, input_sha256=binding(state), top_k=top_k)
    request_hash = framework_digest(request)
    root = sidecar_root(workspace)
    target = checked_local(root / (run_id + '.json'))
    if target.exists():
        previous = next((r for r in restored(workspace, state) if r['run_id'] == run_id), None)
        require(previous is not None and previous['validity'] == 'current', 'E_RETRIEVAL_SIDECAR')
        require(previous['request_sha256'] == request_hash, 'E_RETRIEVAL_RUN_CONFLICT')
        recovered = workspace.recover()
        return next(r for r in recovered['retrieval_runs'] if r['run_id'] == run_id)
    require(not root.exists() or len(list(root.iterdir())) < MAX_RUNS, 'E_RETRIEVAL_LIMIT')
    scores = (score_provider(query, [c['quote'] for c in corpus]) if score_provider is not None else
              bge_scores(query, [c['quote'] for c in corpus], model_path, encoder) if method == 'bge'
              else lexical_scores(query, [c['quote'] for c in corpus])) if corpus else []
    require(len(scores) == len(corpus) and all(finite_score(s) for s in scores), 'E_RETRIEVAL_ENCODING')
    if method == 'bge':
        require(representation == dict(method=method, **model_config(model_path)), 'E_RETRIEVAL_MODEL_CHANGED')
    hits = ranked_hits(corpus, scores, top_k)
    require(workspace.state()['material_status'] == 'current' and binding(workspace.state()) == request['input_sha256'], 'E_BATCH_SOURCE_CHANGED')
    run = dict(schema_version=1, run_id=run_id, **request, request_sha256=request_hash, hits=hits)
    run['sha256'] = framework_digest(run)
    data = encoded(run)
    require(len(data) <= LIMIT, 'E_RETRIEVAL_LIMIT')
    root.mkdir(exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    recovered = workspace.recover()
    return next(r for r in recovered['retrieval_runs'] if r['run_id'] == run_id)
