"""Offline trusted-editor projection; every input is escaped."""
from html import escape
import json
from pathlib import Path

from .review_links import editor_link, unreferenced_ranges, text_range, render_overlap_panel


def render(state):
    esc = lambda value: escape(str(value), quote=True)
    def rule_context(rule):
        strength = {'unknown': '未知', 'recommended': '建议', 'mandatory': '强制措辞（正式效力未确认）', 'optional': '可选'}
        provenance = {'unknown': '未知', 'explicit': '明说', 'inferred': '推断'}
        rows = []
        for key, label in [('applicable_when', '适用条件'), ('exceptions', '例外'),
                           ('strength', '要求强度'), ('strength_provenance', '强度来源'),
                           ('unknowns', '规则未知项'), ('checks', '检查项')]:
            value = rule[key]
            if isinstance(value, list):
                visible = '<ul>' + ''.join(f'<li>{esc(item)}</li>' for item in value) + '</ul>' if value else '未列出（不据此推定不存在）'
            else:
                labels = strength if key == 'strength' else provenance
                visible = esc(labels.get(value, value) + '（' + value + '）')
            rows.append(f'<dt>{label}</dt><dd>{visible}</dd>')
        return '<dl class="rule-context">' + ''.join(rows) + '</dl>'

    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>多来源条款审核</title>',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{max-width:1100px;margin:auto;padding:24px;font:16px/1.6 system-ui;color:#202c36;background:#f5f6f8}article,section,fieldset{background:white;border:1px solid #b8c2cc;border-radius:8px;padding:20px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f6;padding:12px}label{display:block;margin:10px 0}select,input,textarea,button{font:inherit;max-width:100%;padding:8px}textarea{width:90%}button{cursor:pointer}a{color:#074b8b}:target{outline:3px solid #b78612}strong{color:#8a3b13}</style>',
             '<h1>多来源条款审核</h1><p>本机可信编辑材料，沿用来源权限。不是作者端导出。区分人工预填、规则相关词/条件线索与本地模型探索；不发布正式标准。</p><p>来源按原件指纹去重，不推定独立教师或稿件数。个案选择指向审稿记录，稿件身份关系仍待核。</p>']
    parts.append('<style>*{box-sizing:border-box}body{overflow-wrap:anywhere}select{width:100%}fieldset{min-width:0}button{margin:4px} @media(max-width:600px){body{padding:12px}article,section,fieldset{padding:12px}}</style>')
    material_status = state.get('material_status', 'current')
    material_label = {'current': '与当前来源版本一致', 'needs_refresh': '来源已变化，需刷新并复核'}.get(material_status, '版本状态待检查')
    parts.append(f'<p id="material-status">材料状态：{esc(material_label)}</p><details><summary>版本与刷新说明</summary><p>版本状态代码：{esc(material_status)}。版本一致不表示判断已核实。静态页面无法实时监测原工作区。纠正后先在原来源应用观点补丁，再在桌面“刷新包”；拆分或补录后用“重选观点并刷新包”。旧决定需复核，旧建议需重新分析。</p></details>')
    parts.append('''<section id="review-cost"><h2>体验计时（可选）</h2>
<p>仅记录本页活动；原文纠正和桌面操作另记，不是总审核成本。隐藏后暂停，返回须手动继续。</p>
<label>执行者类型（自报）<select id="cost-actor-kind"><option value="agent">代理演练</option><option value="user">用户本人体验</option></select></label>
<label>比较方法（任务声明）<select id="cost-method"><option value="mixed_review">综合审核</option><option value="baseline">规则对照</option><option value="local">本地模型候选</option></select></label>
<button id="cost-start" type="button">开始计时</button><button id="cost-pause" type="button" disabled>暂停</button><button id="cost-finish" type="button" disabled>结束会话</button><button id="cost-download" type="button" disabled>下载独立计时记录</button>
<p id="cost-status" role="status">未开始；打开页面不计工时。</p><output id="cost-elapsed">活动 0.0 秒；暂停 0.0 秒</output>
<details><summary>独立计时记录说明</summary><p>结束后下载独立JSON；刷新或关闭前未下载的记录会丢失。只保存包版本绑定、执行者类型、方法、用时和操作尝试数，不保存身份、原文或完整状态。类型是自报，不认证专业资质；尝试和下载不等于应用成功，代理耗时不代表人工收益。选择方法不切换分析。</p></details></section>''')
    parts.append('<h2>分析运行与覆盖范围</h2><p>零候选、失败和部分完成分别保留；模型失败不自动回退规则。全部候选均可查看，审核顺序不代表批准。</p><details><summary>分析校验说明</summary><p>合法JSON与引用校验通过，仅说明格式及出处绑定通过，不等于业务判断已核实。</p></details>')
    parts.append('<section id="retrieval-results"><h2>选定观点证据查找</h2><p>相关性只安排查阅顺序；不判断同立场、矛盾、概念或论文事实。空结果不表示论文没有对应证据。静态页只展示本机已生成的结果。</p>')
    retrieval_labels = {'current': '与本次材料一致', 'needs_revalidation': '旧结果待重新查找', 'invalid': '记录不可用'}
    retrieval_methods = {'bge': '本机中文语义(BGE)', 'lexical': '词面查找'}
    for run in state.get('retrieval_runs', []):
        historical = run['validity'] != 'invalid' and 'ranking_version' not in run['config']
        if historical:
            parts.append('<details class="historical-retrieval"><summary>历史证据片段结果（保留原排名）</summary>')
        parts.append(f'<article class="retrieval-run"><p>{esc(retrieval_labels[run["validity"]])}</p>')
        parts.append(f'<details><summary>运行记录</summary><p>{esc(run["run_id"])}</p></details>')
        if run['validity'] == 'invalid':
            parts.append('<p>旁车损坏或不安全，未载入结果。</p></article>')
            continue
        parts.append(f'<p>查询：{esc(run["query"])} · 方法：{esc(retrieval_methods[run["config"]["method"]])}</p>')
        candidate_count = len({(h['source_id'], h['candidate_id']) for h in run['hits']})
        source_count = len({h['source_id'] for h in run['hits']})
        unit = '历史证据片段' if historical else '独立观点（各取最高相关证据）'
        parts.append(f'<p>排名单位：{unit}；命中 {len(run["hits"])} 条，不同观点 {candidate_count} 个，来源 {source_count} 份。</p>')
        parts.append('<p>材料一致只说明来源绑定一致；候选仍需人工核对，不表示判断已获确认。</p>')
        if run['config']['method'] == 'bge':
            parts.append('<p>BGE表示最多512 tokens，长引文编码可能截断；下方原引文保留完整内容，相关性不表示已理解全文。</p>')
        if run['validity'] != 'current':
            parts.append('<p>历史输入已失效；请刷新审核包并用新运行ID重新查询。</p>')
        elif not run['hits']:
            parts.append('<p>本次选定观点中没有候选结果。</p>')
        for hit in run['hits']:
            anchor = 'evidence-' + hit['source_id'] + '-' + hit['candidate_id'] + '-' + str(hit['evidence_index'])
            source = next(s for s in state['sources'] if s['source']['source_id'] == hit['source_id'])
            correction = editor_link(source, candidate_id=hit['candidate_id'])
            parts.append(f'<p>#{hit["rank"]} · 候选相关性 {hit["score"]:.3f} · <a href="#{esc(anchor)}">定位命中原文</a> · <a class="direct-correction" href="{esc(correction)}">直接纠正此观点</a> · 证据 {hit["evidence_index"]} [{hit["start"]}, {hit["end"]})</p><pre>{esc(hit["quote"])}</pre>')
        parts.append('</article>')
        if historical:
            parts.append('</details>')
    parts.append('</section>')
    for run in state.get('analysis_runs', []):
        parts.append(f'<article class="analysis-run"><p>{esc(run["run_id"])} · {esc(run.get("method", run["provenance"]))} · {esc(run.get("status", "legacy_unspecified"))} · {esc(run.get("validity", "unknown"))}</p><p>本地模型请求 {esc(run.get("model_requests", "unknown"))} · 错误 {esc(run.get("errors", []))}</p><p>输入指纹 {esc(run.get("input_sha256", run["input_package_sha256"]))}</p><p>{esc(run.get("limitations", []))}</p></article>')
    rare = [i for i in state['issues'] if i.get('ranking', {}).get('rare_important_hint')]
    parts.append('<section id="rare-important"><h2>低频但可能重要的线索</h2><p>模型推断待核，不代表核心结论已判错。</p>')
    for issue in rare:
        parts.append(f'<a href="#issue-{esc(issue["issue_id"])}">{esc(issue["title"])}</a> ')
    if not rare:
        parts.append('<p>本次未提名单列线索；不表示没有重要问题。</p>')
    parts.append('</section>')
    for source in state['sources']:
        parts.append(f'<section><h2>来源 {esc(source["source"]["source_id"])}</h2>')
        parts.append(render_overlap_panel(source))
        summaries = next((r['runs'] for r in state.get('source_run_status', []) if r['source_id'] == source['source']['source_id']), source.get('extraction_status', []))
        parts.append(f'<p>抽取运行状态：{esc(summaries or "unknown（规则基线或未记录）")}；pending/partial均不表示语义验证通过。</p>')
        for score in source['scores']:
            parts.append(f'<p>原分 {esc(score["label"])}：<pre>{esc(score["raw_value"])}</pre></p>')
        for section in source['sections']:
            parts.append(f'<h3>{esc(section["label"])} · {esc(section["visibility"])}</h3><pre>{esc(section["text"])}</pre>')
            gaps = unreferenced_ranges(source, section, include_whitespace=True)
            meaningful, punctuation = [g for g in gaps if text_range(g)], [g for g in gaps if not text_range(g)]
            parts.append(f'<details class="unreferenced"><summary>未被本次所选观点引用的原文 · 含文字 {len(meaningful)} 段，标点/空白/符号 {len(punctuation)} 段</summary><p>仅比较原文区间；这些片段尚不能称为已证实漏提或新观点。请查看上下文，确有需要时显式补录，仍待复核。标点、空白与符号单列，原坐标保留，不把折叠视为覆盖完成。</p>')
            for gap in meaningful + punctuation:
                if punctuation and gap is punctuation[0]:
                    parts.append('<details class="unreferenced-noise"><summary>标点/空白/符号片段（保留位置）</summary>')
                link = editor_link(source, section_id=section['section_id'], start=gap['start'], end=gap['end'])
                parts.append(f'<p>{esc(section["section_id"])} [{gap["start"]}, {gap["end"]}) · <a class="direct-add" href="{esc(link)}">定位此处并选择补录</a></p><pre>{esc(gap["quote"])}</pre>')
            if punctuation:
                parts.append('</details>')
            if not gaps:
                parts.append('<p>没有可展示的未引用片段；不表示观点语义已完整提取。</p>')
            parts.append('</details>')
        for entry in source['candidates']:
            candidate = entry['value']
            anchor = source['source']['source_id'] + '-' + candidate['candidate_id']
            parts.append(f'<article id="candidate-{esc(anchor)}"><h3>观点 {esc(candidate["candidate_id"])} · {esc(candidate["status"])}</h3>')
            parts.append(f'<p>绑定修订 {source["revision"]} · 观点指纹 {esc(entry["candidate_sha256"])}</p>')
            parts.append(f'<p><a class="direct-correction" href="{esc(editor_link(source, candidate_id=candidate["candidate_id"]))}">直接纠正此观点</a></p>')
            for action in candidate.get('conditional_actions', []):
                parts.append(f'<p class="conditional-action">单条件对应动作：{esc(action["condition"])} → {esc(action["action"])}；含义 {esc(action["meaning"])}，依据 {esc(action["provenance"])}。关联及作用域仍待核对。</p>')
            for key, label in [('object', '对象'), ('direction', '方向'), ('action', '动作'), ('requirement_strength', '要求强度'), ('reasons', '理由'), ('conditions', '条件'), ('alternatives', '替代分支'), ('negation', '否定'), ('relations', '关联（含原分性质）')]:
                parts.append(f'<p>{label}：{esc(candidate.get(key, "unknown"))}</p>')
            for index, evidence in enumerate(candidate['evidence']):
                evidence_anchor = 'evidence-' + anchor + '-' + str(index)
                parts.append(f'<p id="{esc(evidence_anchor)}">原文 [{evidence["start"]}, {evidence["end"]})</p><pre>{esc(evidence["quote"])}</pre>')
            parts.append('</article>')
        link = (Path(source['workspace']) / 'report.html').as_uri()
        parts.append(f'<a href="{esc(link)}">在原工作区纠正观点</a><p>下载观点补丁后，在桌面下拉选择本来源并“打开所选原来源”，再用上方“选择下载补丁并应用”。随后刷新审核包并重开；本页不会自动保存。</p></section>')
    parts.append('<h2>规则候选 · authority=unconfirmed</h2><p>原规则引文只支持 before；after 是编辑建议，未经专业确认。</p>')
    for rule in state['framework']['book']['rules']:
        parts.append(f'<article id="rule-{esc(rule["rule_id"])}"><h3>{esc(rule["title"])}</h3><pre>{esc(rule["requirement"])}</pre>')
        parts.append(rule_context(rule))
        for evidence in rule['evidence']:
            parts.append(f'<p>{esc(evidence["source_id"])} · {esc(evidence["locator"])}</p><pre>{esc(evidence["quote"])}</pre>')
        parts.append('</article>')
    parts.append(f'<p>所用规则版本：{esc(state["framework"]["book"]["version"])} · {esc(state["framework"]["sha256"])}</p>')
    for issue in state['issues']:
        origin = '人工预填' if issue['origin'] == 'manual' else '分析候选（待审核）'
        parts.append(f'<article class="review-issue" id="issue-{esc(issue["issue_id"])}"><h2>{esc(issue["title"])}</h2><p>{origin} · {esc(issue.get("provenance", "manual"))} · {esc(issue.get("validity", "unknown"))} · {esc(issue["rationale"])}</p><section class="rule-before"><h3>原规则（before）</h3><pre>{esc(issue["before"]["requirement"])}</pre>{rule_context(issue["before"])}</section><pre>候选改动（after）: {esc(issue["after"])}</pre>')
        if 'alternatives' not in issue:
            effective = dict(issue['before'], **issue['after'])
            parts.append('<section class="rule-after"><h3>候选方案的条件与强度</h3><p>未单列修改的字段沿用原规则；明确改动按 after 展示，尚待审核。</p>' + rule_context(effective) + '</section>')
        if 'concept' in issue:
            concept = issue['concept']
            parts.append(f'<p>候选概念 {esc(concept["concept_id"])} · {esc(concept["status"])}</p><p>定义：{esc(concept["definition"])}</p><p>边界：{esc(concept["boundary"])}</p><p>正例：{esc(concept["example"])}；边界反例：{esc(concept["boundary_counterexample"] or "本次未有，不编造")}</p>')
            parts.append(f'<p>规则对照（inferred）：{esc(issue["comparison"])}</p><p class="ranking">排序理由：{esc(issue["ranking"]["reasons"])}</p><p>原分关联（生成后连接）：{esc(issue["score_links"])}</p>')
            for alternative in issue['alternatives']:
                parts.append(f'<section class="alternative"><h3>{esc(alternative["label"])}</h3><p>editorial_proposal · authority=unconfirmed</p><pre>{esc(alternative["after"]["requirement"])}</pre><p>理由：{esc(alternative["rationale"])}</p><p>可能益处：{esc(alternative["benefits"])}；代价/负担：{esc(alternative["costs"])}</p><p>未知：{esc(alternative["unknowns"])}</p>')
                note = ('本版扩展方案仅修改要求文字；条件、例外、强度、未知项及检查项沿用原规则。'
                        if set(alternative['after']) == {'requirement'} else
                        '历史方案含其他改动字段，保留决定须重新核验；未修改字段沿用原规则。')
                parts.append('<p>' + note + '</p>' + rule_context(dict(issue['before'], **alternative['after'])))
                if alternative['alternative_id'] == 'retain':
                    # Old producers copied discussion evidence into retain.
                    # Keep those records visible without endorsing their roles.
                    parts.append('<p>保留对照记录；原规则见 before。B支持/反对关系未判；以下历史字段不表示已核实的方案依据。</p>')
                    labels = [('support', '历史关联引用（原support字段，关系未判）'),
                              ('counter', '历史关联引用（原counter字段，关系未判）')]
                else:
                    labels = [('support', '方案支持'), ('counter', '方案反例')]
                for kind, label in labels:
                    parts.append(f'<p>{label}：')
                    for ref in alternative[kind]:
                        anchor = ref['source_id'] + '-' + ref['candidate_id']
                        parts.append(f'<a href="#candidate-{esc(anchor)}">{esc(ref["candidate_id"])}</a> ')
                    if not alternative[kind]:
                        parts.append('本次未有')
                    parts.append('</p>')
                parts.append('</section>')
        parts.append(f'<a href="#rule-{esc(issue["rule_id"])}">查看原规则与出处</a>')
        for kind, label in [('support', '支持材料'), ('counter', '反对材料')]:
            parts.append(f'<h3>{label}</h3>')
            for ref in issue[kind]:
                anchor = ref['source_id'] + '-' + ref['candidate_id']
                parts.append(f'<a href="#candidate-{esc(anchor)}">{esc(ref["candidate_id"])}</a> ')
        parts.append(f'<p>未知：{esc(issue["unknowns"])}</p></article>')
    pending_ids = state.get('refresh_pending_issue_ids', [])
    if pending_ids:
        parts.append('<section id="refresh-pending"><h2>重选后待重新分析的问题（只读历史）</h2><p>旧证据不转绑新子项。以下问题已保存在包历史；请通过既有 batch-discover 重新分析选定材料。尚未自动重新分析。</p>')
        for issue_id in pending_ids:
            old = next((i for package in reversed(state['package_history']) for i in package['issues'] if i['issue_id'] == issue_id), None)
            if old:
                parts.append(f'<article><h3>{esc(old["title"])}</h3><p>{esc(issue_id)} · needs_revalidation</p><pre>{esc(old["after"])}</pre></article>')
        parts.append('</section>')
    options = ''.join(f'<option value="{esc(i["issue_id"])}">{esc(i["title"])}</option>' for i in state['issues'] if i.get('validity') != 'needs_revalidation')
    parts.append('<fieldset><legend>记录审核决定</legend><p>个案处理与通用条款讨论分别保存；选择修改也不发布正式标准。</p>'
                 f'<label>问题<select id="issue">{options}</select></label>'
                 '<label>决定类型<select id="decision-type"><option value="case_decision">个案处理决定</option><option value="framework_proposal_review">Framework候选提案审核</option></select></label>'
                 '<label>本次个案的审稿记录<select id="case-source"></select></label>'
                 '<label>处理<select id="action"><option value="keep">保留</option><option value="change">修改</option><option value="need_material">补材料</option><option value="defer">暂缓</option></select></label>'
                 '<label>修改方案（有候选方案时必选）<select id="alternative"></select></label>'
                 '<label>本项理由<textarea id="decision-reason"></textarea></label><button id="queue" type="button">加入决定队列</button>'
                 '<ul id="draft-list"></ul><label>操作者（声明）<input id="actor"></label><label>本次审核说明<textarea id="reason"></textarea></label>'
                 '<button id="download" type="button">下载决定补丁</button><p id="save-status" role="status">草稿尚未应用。本页关闭会丢失未下载草稿。</p>'
                 '<p>下载不等于保存成功。在桌面“应用下载决定”，再“恢复审核包并重开”查看已应用历史。个案仅指所选来源记录；通用条款始终是草案讨论，未发布。</p></fieldset>')
    parts.append('<h2>已应用决定及历史</h2>')
    for decision in state['decisions']:
        parts.append(f'<article class="saved-decision"><p>{esc(decision["issue_id"])} · {esc(decision["decision_type"])} · {esc(decision["action"])} · <strong>{esc(decision["validity"])}</strong></p><p>个案来源：{esc(decision.get("case_source_id") or "不适用（通用条款讨论）")} · 修订 {decision["revision"]}</p><p>{esc(decision["reason"])}</p><p>{esc(decision["actor"])} · {esc(decision["at"])} · {esc(decision["decision_id"])}</p></article>')
        if 'alternative_id' in decision:
            # Keep the frozen choice inside the decision card on reopen.
            parts[-1] = parts[-1].replace('</article>', f'<p>所选方案：{esc(decision["alternative_id"] or "未选定（补材料/暂缓）")}</p><pre>{esc(decision.get("selected_after"))}</pre><p>方案指纹 {esc(decision.get("alternative_sha256"))}</p></article>')
    envelope = dict(schema_version=1, batch_id=state['batch_id'], base_revision=state['revision'], package_sha256=state['package_sha256'])
    cases = {i['issue_id']: list(dict.fromkeys(r['source_id'] for kind in ('support', 'counter') for r in i[kind])) for i in state['issues']}
    alternatives = {i['issue_id']: [dict(alternative_id=a['alternative_id'], label=a['label']) for a in i.get('alternatives', [])] for i in state['issues']}
    data = json.dumps(dict(envelope=envelope, issue_cases=cases, alternatives=alternatives), ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    parts.append('<script id="batch-data" type="application/json">' + data + '</script><script>' + Path(__file__).with_name('batch_editor.js').read_text(encoding='utf-8') + '</script><script>' + Path(__file__).with_name('batch_cost.js').read_text(encoding='utf-8') + '</script>')
    return '\n'.join(parts) + '</html>'
