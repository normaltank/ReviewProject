"""Local, exploratory batch proposals. No model authority and no cloud fallback."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import time
import urllib.request
import urllib.error

from .core import ReviewError, require, digest
from .framework import framework_digest, identifier, text, texts
from .store import atomic, encoded
from .batch import bounded, checked_local, read_json

INSTRUCTION = '''你是本机审稿条款候选提案助手，不裁决学术正确性、商业取舍或正式标准。
输入仅为选定普通区观点与一个A候选规则。不提供原分和身份元数据。所有观点仍待专业复核。
只列有引用依据的候选问题；同主题相反判断必须分开，不因高分与批评并存推断矛盾。
support/counter引用必须使用输入source_id、candidate_id及一条完整逐字quote，不改引号或空白。
一个问题的多个方案可比较保留、改写、增加条件，但无依据不凑方案。A引文只支持原规则。
概念沿用输入rule_id，definition/boundary为待核定义，不批准新词典。
明确条件、反例、利弊、编辑负担与未知。没有反例就空counter并说明本次范围。
relation只针对当前候选规则包，uncovered不代表A全部标准没有要求。
所有新建议是editorial_proposal，比较是inferred，不得升级为明确事实。
possible_core_impact仅为建议单列复核的线索，不能认定核心结论错误。
没有问题返回issues=[]。只输出指定JSON，不输出身份、分数或新引文。'''


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


STRING = {'type': 'string'}
STRINGS = {'type': 'array', 'items': STRING}
REF = obj(dict(source_id=STRING, candidate_id=STRING, quote=STRING))
REFS = {'type': 'array', 'items': REF}
OPTION = obj(dict(label=STRING, requirement=STRING, support=REFS, counter=REFS,
                  rationale=STRING, benefits=STRINGS, costs=STRINGS, unknowns=STRINGS))
MODEL_ISSUE = obj(dict(title=STRING, rule_id=STRING, definition=STRING, boundary=STRING,
    support=REFS, counter=REFS, rationale=STRING, unknowns=STRINGS,
    relation={'type': 'string', 'enum': ['partial', 'condition_difference', 'potential_conflict', 'uncovered', 'pending_comparison']},
    possible_core_impact={'type': 'boolean'}, alternatives={'type': 'array', 'items': OPTION}))
SCHEMA = obj(dict(issues={'type': 'array', 'items': MODEL_ISSUE}))


def input_binding(state):
    return framework_digest({k: state[k] for k in ('sources', 'framework')})


def reference_keys(refs):
    return {(r['source_id'], r['candidate_id']) for r in refs}


def refs_valid(refs, allowed):
    require(isinstance(refs, list), 'E_BATCH_EVIDENCE')
    keys = []
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {'source_id', 'candidate_id'}, 'E_BATCH_EVIDENCE')
        key = (ref['source_id'], ref['candidate_id'])
        require(key in allowed and key not in keys, 'E_BATCH_EVIDENCE')
        keys.append(key)
    return set(keys)


def validate_issue(issue, sources, rule):
    allowed = {(s['source']['source_id'], c['value']['candidate_id']) for s in sources for c in s['candidates']}
    scope = reference_keys(issue['support'] + issue['counter'])
    concept = issue['concept']
    require(isinstance(concept, dict) and set(concept) == {'concept_id', 'definition', 'boundary', 'status', 'example', 'boundary_counterexample'}, 'E_BATCH_CONCEPT')
    require(concept['concept_id'] == rule['rule_id'] and concept['status'] == 'candidate', 'E_BATCH_CONCEPT')
    text(concept['definition']); text(concept['boundary'])
    for field in ('example', 'boundary_counterexample'):
        require(concept[field] is None or refs_valid([concept[field]], scope), 'E_BATCH_CONCEPT')
    require(isinstance(issue['alternatives'], list) and 1 <= len(issue['alternatives']) <= 6, 'E_BATCH_ALTERNATIVES')
    seen = set()
    for alternative in issue['alternatives']:
        require(isinstance(alternative, dict) and set(alternative) == {'alternative_id', 'label', 'after', 'support', 'counter', 'rationale', 'benefits', 'costs', 'unknowns', 'provenance'}, 'E_BATCH_ALTERNATIVE')
        identifier(alternative['alternative_id'])
        require(alternative['alternative_id'] not in seen and alternative['provenance'] == 'editorial_proposal', 'E_BATCH_ALTERNATIVE')
        seen.add(alternative['alternative_id'])
        for key in ('label', 'rationale'):
            text(alternative[key])
        for key in ('benefits', 'costs', 'unknowns'):
            texts(alternative[key])
        require(isinstance(alternative['after'], dict) and set(alternative['after']) == {'requirement'}, 'E_BATCH_AFTER')
        text(alternative['after']['requirement'])
        positive = refs_valid(alternative['support'], scope)
        negative = refs_valid(alternative['counter'], scope)
        require(positive and not positive & negative, 'E_BATCH_ALTERNATIVE')
    require(issue['alternatives'][0]['after']['requirement'] == rule['requirement'], 'E_BATCH_BEFORE')
    rank = issue['ranking']
    require(isinstance(rank, dict) and set(rank) == {'reasons', 'distinct_source_records', 'rare_important_hint'}, 'E_BATCH_RANKING')
    texts(rank['reasons'])
    require(type(rank['distinct_source_records']) is int and rank['distinct_source_records'] == len({r[0] for r in scope}) and
            type(rank['rare_important_hint']) is bool, 'E_BATCH_RANKING')
    require(isinstance(issue['comparison'], dict) and set(issue['comparison']) == {'relation', 'provenance', 'scope'} and
        issue['comparison']['relation'] in MODEL_ISSUE['properties']['relation']['enum'] and
        issue['comparison']['provenance'] == 'inferred' and issue['comparison']['scope'] == 'selected_candidate_package_only', 'E_BATCH_COMPARISON')
    # Recompute the allowed score linkage from the source opinion; sharing a
    # form or a topic never constitutes an explanation of a numerical score.
    require(issue['score_links'] == score_links(sources, scope), 'E_BATCH_SCORE_LINK')
    require(scope <= allowed, 'E_BATCH_EVIDENCE')


def score_links(sources, scope):
    links = []
    for source in sources:
        for wrapped in source['candidates']:
            candidate = wrapped['value']
            key = (source['source']['source_id'], candidate['candidate_id'])
            if key not in scope:
                continue
            explicit = [r for r in candidate.get('relations', []) if r.get('type') == 'explains_score' and r.get('provenance') == 'explicit' and r.get('evidence_indices')]
            links.append(dict(source_id=key[0], candidate_id=key[1], provenance='explicit' if explicit else 'unknown',
                relations=copy.deepcopy(explicit), note='原分在生成后展示；同表共现不是给分原因；未估计教师严宽或群体权重。'))
    return links


def validate_analysis(analysis, issues, state):
    fields = {'method', 'status', 'input_sha256', 'config', 'config_sha256', 'prompt_sha256', 'schema_sha256', 'adapter_sha256', 'model_requests', 'errors', 'calls', 'limitations'}
    require(isinstance(analysis, dict) and set(analysis) == fields, 'E_BATCH_ANALYSIS_METADATA')
    require(analysis['method'] in {'baseline', 'local'} and analysis['status'] in {'complete', 'partial', 'failed', 'zero_candidates'}, 'E_BATCH_ANALYSIS_METADATA')
    require(analysis['input_sha256'] == input_binding(state), 'E_BATCH_ANALYSIS_INPUT')
    for field in ('input_sha256', 'config_sha256', 'prompt_sha256', 'schema_sha256', 'adapter_sha256'):
        require(isinstance(analysis[field], str) and re.fullmatch('[0-9a-f]{64}', analysis[field]), 'E_BATCH_ANALYSIS_METADATA')
    require(analysis['config_sha256'] == framework_digest(analysis['config']), 'E_BATCH_ANALYSIS_METADATA')
    require(type(analysis['model_requests']) is int and analysis['model_requests'] >= 0, 'E_BATCH_ANALYSIS_METADATA')
    texts(analysis['errors']); texts(analysis['limitations'])
    require(isinstance(analysis['calls'], list) and len(analysis['calls']) <= 20, 'E_BATCH_ANALYSIS_METADATA')
    require((analysis['status'] == 'complete' and issues and not analysis['errors']) or
            (analysis['status'] == 'zero_candidates' and not issues and not analysis['errors']) or
            (analysis['status'] == 'partial' and issues and analysis['errors']) or
            (analysis['status'] == 'failed' and not issues and analysis['errors']), 'E_BATCH_ANALYSIS_STATUS')


def make_issue(rule, support, counter, *, run_id, number, definition, boundary, rationale, unknowns,
               relation='pending_comparison', alternatives=None, important=False, sources):
    scope = reference_keys(support + counter)
    count = len({x[0] for x in scope})
    candidate_status = [c['value']['status'] for s in sources for c in s['candidates'] if (s['source']['source_id'], c['value']['candidate_id']) in scope]
    run_status = [r['status'] for s in sources for r in s.get('extraction_status', [])]
    warnings = ['出处校验不等于理解正确或论文判断已核实。', '未取得教师/稿件交叉结构；仅统计distinct source记录数。',
                '未提供作者回复或论文事实核验；学术与编辑负担取舍交人工。',
                '原观点状态：' + ', '.join(sorted(set(candidate_status))) + '；抽取运行状态：' + ', '.join(sorted(set(run_status)) or ['unknown']),
                '没有反例仅说明本次选定范围未列出；不代表没有反例。']
    baseline = dict(alternative_id='retain', label='保留原规则对照', after=dict(requirement=rule['requirement']), support=copy.deepcopy(support or counter), counter=[],
        rationale='保留当前候选规则作为人工对照；B引用仅用于本次讨论，A出处只支持before。', benefits=['保持现行要求的可预期性'], costs=['原条件是否足够清楚仍需核查'], unknowns=['未验证规则后果或正式效力'], provenance='editorial_proposal')
    options = [baseline] + (alternatives or [])
    return dict(issue_id=f'{run_id}-{number}', title=rule['title'] + '：' + rationale[:60], rule_id=rule['rule_id'], support=support, counter=counter,
        rationale=rationale, after=copy.deepcopy(options[1]['after']) if len(options) > 1 else {}, unknowns=list(dict.fromkeys(unknowns + warnings)),
        concept=dict(concept_id=rule['rule_id'], definition=definition, boundary=boundary, status='candidate',
                     example=copy.deepcopy((support or counter)[0]), boundary_counterexample=None),
        alternatives=options, ranking=dict(distinct_source_records=count, rare_important_hint=important and count == 1,
            reasons=[f'{count}个不同来源记录（不推定教师/稿件数）', '引用可定位，但观点及条件尚待专业核实',
                     '低频核心影响线索，单列供人工检查' if important and count == 1 else '按材料记录数和稳定ID展示，频率不构成标准权重']),
        comparison=dict(relation=relation, provenance='inferred', scope='selected_candidate_package_only'), score_links=score_links(sources, scope))


def baseline_issues(state, rules, run_id, candidate_ids=None):
    issues = []
    for rule in rules:
        # Literal bigrams are deliberately only retrieval cues, not a semantic
        # classifier. Each selected opinion remains a separate candidate issue.
        vocabulary = set(re.findall(r'[\u4e00-\u9fff]{2}|[a-zA-Z]{3,}', rule['title'] + rule['requirement']))
        for source in state['sources']:
            for wrapped in source['candidates']:
                candidate = wrapped['value']
                if candidate_ids and candidate['candidate_id'] not in candidate_ids:
                    continue
                quote = '\n'.join(e['quote'] for e in candidate['evidence'])
                matched = sorted(word for word in vocabulary if word in quote)
                if not matched:
                    continue
                ref = dict(source_id=source['source']['source_id'], candidate_id=candidate['candidate_id'])
                issues.append(make_issue(rule, [ref], [], run_id=run_id, number=len(issues) + 1,
                    definition='候选概念沿用规则：' + rule['title'], boundary='仅为相关词/条件线索；不确认覆盖、矛盾或条件含义。',
                    rationale='相关词/条件线索：' + '、'.join(matched), unknowns=['基线未生成语义改写；没有足够材料时仅保留原规则对照。'], sources=state['sources']))
    return issues


def discover(workspace, *, method, run_id, rule_ids=None, endpoint='http://127.0.0.1:8766/v1',
             model='reviewproject-qwen3-4b-q4km', max_output_tokens=4096, context_chars=10000, candidate_ids=None):
    identifier(run_id)
    require(len(run_id) <= 80, 'E_BATCH_RUN_ID')
    require(method in {'baseline', 'local'} and 256 <= max_output_tokens <= 8192 and 500 <= context_chars <= 20000, 'E_BATCH_DISCOVERY_CONFIG')
    state = workspace.state()
    require(state['material_status'] == 'current', 'E_BATCH_STALE')
    rules = [r for r in state['framework']['book']['rules'] if not rule_ids or r['rule_id'] in rule_ids]
    require(rules and len(rules) <= 20 and (not rule_ids or len(set(rule_ids)) == len(rule_ids) and set(rule_ids) == {r['rule_id'] for r in rules}), 'E_BATCH_RULE_SELECTION')
    allowed_candidates = {c['value']['candidate_id'] for s in state['sources'] for c in s['candidates']}
    require(not candidate_ids or len(set(candidate_ids)) == len(candidate_ids) and set(candidate_ids) <= allowed_candidates, 'E_BATCH_CANDIDATE_SELECTION')
    config = dict(method=method, rule_ids=[r['rule_id'] for r in rules], endpoint=endpoint if method == 'local' else None,
                  model=model if method == 'local' else None, max_output_tokens=max_output_tokens, context_chars=context_chars,
                  score_blind=True, identity_metadata_excluded=True, temperature=0, external_model_requests=0,
                  source_run_status=copy.deepcopy(state.get('source_run_status', [])), candidate_ids=sorted(candidate_ids) if candidate_ids else None)
    if method == 'local':
        from experiments.extract_local import local_endpoint
        try:
            local_endpoint(endpoint)
        except ValueError:
            raise ReviewError('E_LOCAL_ENDPOINT_REQUIRED') from None
    fingerprint = input_binding(state)
    previous = next((r for r in state.get('analysis_runs', []) if r['run_id'] == run_id), None)
    if previous:
        require(previous.get('input_sha256') == fingerprint and previous.get('config') == config, 'E_BATCH_RUN_CONFLICT')
        workspace.recover()
        return previous
    root = checked_local(workspace.path / 'analysis-artifacts')
    root.mkdir(exist_ok=True)
    folder = checked_local(root / run_id)
    if folder.exists():
        # A completed producer payload can be replayed after publication failed.
        payload = read_json(folder / 'analysis.json') if (folder / 'analysis.json').is_file() else None
        require(payload is not None and payload['analysis']['input_sha256'] == fingerprint and payload['analysis']['config'] == config, 'E_BATCH_DISCOVERY_EXISTS')
        workspace.append_analysis(payload)
        return workspace.state()['analysis_runs'][-1]
    folder.mkdir()
    analysis = dict(method=method, status='failed', input_sha256=fingerprint, config=config,
        config_sha256=framework_digest(config), prompt_sha256=digest(INSTRUCTION.encode('utf-8')), schema_sha256=framework_digest(SCHEMA),
        adapter_sha256=digest(Path(__file__).read_bytes()), model_requests=0, errors=[], calls=[],
        limitations=['Exploratory only; JSON and literal evidence checks do not establish semantic correctness.',
                     'Original scores and identity metadata excluded from proposal generation; ordinary text itself is not anonymized.',
                     'No teacher/paper denominator, academic verdict, commercial trade-off or automatic publication.'])
    atomic(folder / 'protocol.json', encoded(dict(instruction=INSTRUCTION, schema=SCHEMA, config=config)))
    analysis_state = copy.deepcopy(state)
    summaries = {r['source_id']: r['runs'] for r in state.get('source_run_status', [])}
    for source in analysis_state['sources']:
        source['extraction_status'] = summaries.get(source['source']['source_id'], [])
    if method == 'baseline':
        issues = baseline_issues(analysis_state, rules, run_id, candidate_ids)
    else:
        issues = local_issues(workspace, analysis_state, rules, run_id, folder, analysis)
    issues.sort(key=lambda i: (-i['ranking']['distinct_source_records'], i['issue_id']))
    analysis['status'] = ('partial' if issues else 'failed') if analysis['errors'] else ('complete' if issues else 'zero_candidates')
    payload = bounded(dict(schema_version=1, batch_id=state['batch_id'], base_revision=state['revision'],
        package_sha256=state['package_sha256'], run_id=run_id, provenance='literal_rule_cues' if method == 'baseline' else 'local_qwen_structured_editorial_proposal',
        issues=issues, analysis=analysis))
    atomic(folder / 'analysis.json', encoded(payload))
    workspace.append_analysis(payload)
    return workspace.state()['analysis_runs'][-1]


def local_issues(workspace, state, rules, run_id, folder, analysis):
    from experiments.extract_local import NoRedirect, local_endpoint
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    rows, aliases = [], {}
    for sn, source in enumerate(state['sources'], 1):
        for cn, wrapped in enumerate(source['candidates'], 1):
            candidate = wrapped['value']
            if analysis['config']['candidate_ids'] and candidate['candidate_id'] not in analysis['config']['candidate_ids']:
                continue
            sid, cid = f'source-{sn}', f'candidate-{cn}'
            aliases[(sid, cid)] = (source['source']['source_id'], candidate)
            # Exclude metadata, scores, model raw payloads and score relations.
            rows.append(dict(source_id=sid, candidate_id=cid, status=candidate['status'],
                quotes=[e['quote'] for e in candidate['evidence']],
                opinion={k: copy.deepcopy(candidate.get(k, 'unknown')) for k in ('object', 'direction', 'conditions', 'reasons', 'action', 'negation', 'alternatives', 'requirement_strength')}))
    issues = []
    for number, rule in enumerate(rules, 1):
        prompt = json.dumps(dict(rule={k: rule[k] for k in ('rule_id', 'title', 'requirement', 'applicable_when', 'exceptions')}, opinions=rows), ensure_ascii=False)
        call = dict(rule_id=rule['rule_id'], prompt_sha256=digest(prompt.encode('utf-8')), response_sha256=None, status='pending', errors=[])
        analysis['calls'].append(call)
        # Conservative byte-as-token bound for the existing 16K context. Never
        # truncate a quote or silently drop an opinion to fit the model.
        if len(prompt) > analysis['config']['context_chars'] or len((INSTRUCTION + prompt + json.dumps(SCHEMA)).encode('utf-8')) + analysis['config']['max_output_tokens'] > 16000:
            call.update(status='skipped', errors=['E_MODEL_CONTEXT_LIMIT'])
            analysis['errors'].append('E_MODEL_CONTEXT_LIMIT')
            atomic(folder / f'call-{number:03}.json', encoded(call))
            continue
        require(input_binding(workspace.state()) == analysis['input_sha256'] and workspace.state()['material_status'] == 'current', 'E_BATCH_STALE')
        request_payload = dict(model=analysis['config']['model'], temperature=0, max_tokens=analysis['config']['max_output_tokens'],
            messages=[dict(role='system', content=INSTRUCTION), dict(role='user', content=prompt)],
            chat_template_kwargs=dict(enable_thinking=False), response_format=dict(type='json_schema', json_schema=dict(name='framework_review', strict=True, schema=SCHEMA)))
        call['request_sha256'] = framework_digest(request_payload)
        atomic(folder / f'request-{number:03}.json', encoded(request_payload))
        atomic(folder / f'call-{number:03}.json', encoded(call))
        analysis['model_requests'] += 1
        started = time.monotonic()
        try:
            request = urllib.request.Request(local_endpoint(analysis['config']['endpoint']), data=encoded(request_payload), headers={'Content-Type': 'application/json'}, method='POST')
            with opener.open(request, timeout=180) as response:
                raw = response.read(1_000_001)
            require(len(raw) <= 1_000_000, 'E_MODEL_RESPONSE_LIMIT')
            call['response_sha256'] = digest(raw)
            atomic(folder / f'response-{number:03}.json', raw)
            from .framework import load_json
            answer = load_json(raw)
            choice = answer['choices'][0]
            require(choice.get('finish_reason') == 'stop', 'E_MODEL_TRUNCATED')
            result = load_json(choice['message']['content'])
            require(isinstance(result, dict) and set(result) == {'issues'} and isinstance(result['issues'], list) and len(result['issues']) <= 20, 'E_MODEL_SCHEMA')
            for proposed in result['issues']:
                try:
                    issue = convert_issue(proposed, rule, aliases, state, run_id, len(issues) + 1)
                    validate_issue(issue, state['sources'], rule)
                    issues.append(issue)
                except (ReviewError, KeyError, TypeError, ValueError) as error:
                    call['errors'].append(str(error) if isinstance(error, ReviewError) else 'E_MODEL_PROPOSAL_REJECTED')
            call['status'] = 'partial' if call['errors'] else 'responded'
        except Exception as error:
            code = str(error) if isinstance(error, ReviewError) else 'E_LOCAL_PROPOSAL_REQUEST'
            if isinstance(error, urllib.error.HTTPError):
                call['http_status'] = error.code
                try:
                    raw = error.read(1_000_001)
                    if len(raw) <= 1_000_000:
                        call['response_sha256'] = digest(raw)
                        atomic(folder / f'response-{number:03}.json', raw)
                    else:
                        code = 'E_MODEL_RESPONSE_LIMIT'
                finally:
                    error.close()
            call.update(status='failed')
            call['errors'].append(code)
        finally:
            call['seconds'] = round(time.monotonic() - started, 3)
            analysis['errors'].extend(call['errors'])
            atomic(folder / f'call-{number:03}.json', encoded(call))
    return issues


def convert_issue(proposed, rule, aliases, state, run_id, number):
    require(isinstance(proposed, dict) and set(proposed) == set(MODEL_ISSUE['properties']) and proposed['rule_id'] == rule['rule_id'], 'E_MODEL_SCHEMA')
    for field in ('title', 'definition', 'boundary', 'rationale'):
        text(proposed[field])
    texts(proposed['unknowns'])
    require(type(proposed['possible_core_impact']) is bool and proposed['relation'] in MODEL_ISSUE['properties']['relation']['enum'], 'E_MODEL_SCHEMA')

    def cited(entries):
        require(isinstance(entries, list), 'E_MODEL_REFERENCE')
        refs = []
        for ref in entries:
            require(isinstance(ref, dict) and set(ref) == {'source_id', 'candidate_id', 'quote'}, 'E_MODEL_REFERENCE')
            require((ref['source_id'], ref['candidate_id']) in aliases, 'E_MODEL_REFERENCE')
            sid, candidate = aliases[(ref['source_id'], ref['candidate_id'])]
            require(ref['quote'] in [e['quote'] for e in candidate['evidence']], 'E_MODEL_QUOTE')
            actual = dict(source_id=sid, candidate_id=candidate['candidate_id'])
            require(actual not in refs, 'E_MODEL_REFERENCE')
            refs.append(actual)
        return refs

    support, counter = cited(proposed['support']), cited(proposed['counter'])
    require(support and not reference_keys(support) & reference_keys(counter), 'E_MODEL_REFERENCE')
    require(isinstance(proposed['alternatives'], list) and len(proposed['alternatives']) <= 5, 'E_MODEL_SCHEMA')
    options = []
    for n, alternative in enumerate(proposed['alternatives'], 1):
        require(isinstance(alternative, dict) and set(alternative) == set(OPTION['properties']), 'E_MODEL_SCHEMA')
        for field in ('label', 'requirement', 'rationale'):
            text(alternative[field])
        for field in ('benefits', 'costs', 'unknowns'):
            texts(alternative[field])
        require(alternative['requirement'] != rule['requirement'], 'E_MODEL_NO_CHANGE')
        options.append(dict(alternative_id=f'option-{n}', label=alternative['label'], after=dict(requirement=alternative['requirement']),
            support=cited(alternative['support']), counter=cited(alternative['counter']), rationale=alternative['rationale'],
            benefits=alternative['benefits'], costs=alternative['costs'], unknowns=alternative['unknowns'], provenance='editorial_proposal'))
    issue = make_issue(rule, support, counter, run_id=run_id, number=number, definition=proposed['definition'], boundary=proposed['boundary'],
        rationale=proposed['rationale'], unknowns=proposed['unknowns'], relation=proposed['relation'], alternatives=options,
        important=proposed['possible_core_impact'], sources=state['sources'])
    issue['title'] = proposed['title']
    return issue
