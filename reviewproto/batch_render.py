"""Offline trusted-editor projection; every input is escaped."""
from html import escape
import json
from pathlib import Path


def render(state):
    esc = lambda value: escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>多来源条款审核</title>',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{max-width:1100px;margin:auto;padding:24px;font:16px/1.6 system-ui;color:#202c36;background:#f5f6f8}article,section,fieldset{background:white;border:1px solid #b8c2cc;border-radius:8px;padding:20px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f6;padding:12px}label{display:block;margin:10px 0}select,input,textarea,button{font:inherit;max-width:100%;padding:8px}textarea{width:90%}button{cursor:pointer}a{color:#074b8b}:target{outline:3px solid #b78612}strong{color:#8a3b13}</style>',
             '<h1>多来源条款审核</h1><p>本机可信编辑材料，沿用来源权限。不是作者端导出。人工预填问题，非自动发现；不发布正式标准。</p><p>来源按原件指纹去重，不推定独立教师或稿件数。个案选择指向审稿记录，稿件身份关系仍待核。</p>']
    parts.append(f'<p id="material-status">材料状态：{esc(state.get("material_status", "current"))}</p><p>静态页面无法实时监测原工作区。纠正后请运行 batch-recover 检查旧包，再用新修订清单 batch-build 刷新；历史决定仍须重新核对。</p>')
    for source in state['sources']:
        parts.append(f'<section><h2>来源 {esc(source["source"]["source_id"])}</h2>')
        for score in source['scores']:
            parts.append(f'<p>原分 {esc(score["label"])}：<pre>{esc(score["raw_value"])}</pre></p>')
        for section in source['sections']:
            parts.append(f'<h3>{esc(section["label"])} · {esc(section["visibility"])}</h3><pre>{esc(section["text"])}</pre>')
        for entry in source['candidates']:
            candidate = entry['value']
            anchor = source['source']['source_id'] + '-' + candidate['candidate_id']
            parts.append(f'<article id="candidate-{esc(anchor)}"><h3>观点 {esc(candidate["candidate_id"])} · {esc(candidate["status"])}</h3>')
            parts.append(f'<p>绑定修订 {source["revision"]} · 观点指纹 {esc(entry["candidate_sha256"])}</p>')
            for key, label in [('object', '对象'), ('direction', '方向'), ('action', '动作'), ('requirement_strength', '要求强度'), ('reasons', '理由'), ('conditions', '条件'), ('alternatives', '替代分支'), ('negation', '否定'), ('relations', '关联（含原分性质）')]:
                parts.append(f'<p>{label}：{esc(candidate.get(key, "unknown"))}</p>')
            for evidence in candidate['evidence']:
                parts.append(f'<p>原文 [{evidence["start"]}, {evidence["end"]})</p><pre>{esc(evidence["quote"])}</pre>')
            parts.append('</article>')
        link = (Path(source['workspace']) / 'report.html').as_uri()
        parts.append(f'<a href="{esc(link)}">在原工作区纠正观点</a><p>下载观点补丁后，须在原工作区 apply，再用新修订清单刷新本包；当前页面不会自动保存。</p></section>')
    parts.append('<h2>规则候选 · authority=unconfirmed</h2><p>原规则引文只支持 before；after 是编辑建议，未经专业确认。</p>')
    for rule in state['framework']['book']['rules']:
        parts.append(f'<article id="rule-{esc(rule["rule_id"])}"><h3>{esc(rule["title"])}</h3><pre>{esc(rule["requirement"])}</pre>')
        for evidence in rule['evidence']:
            parts.append(f'<p>{esc(evidence["source_id"])} · {esc(evidence["locator"])}</p><pre>{esc(evidence["quote"])}</pre>')
        parts.append('</article>')
    parts.append(f'<p>所用规则版本：{esc(state["framework"]["book"]["version"])} · {esc(state["framework"]["sha256"])}</p>')
    for issue in state['issues']:
        origin = '人工预填' if issue['origin'] == 'manual' else '分析候选（待审核）'
        parts.append(f'<article><h2>{esc(issue["title"])}</h2><p>{origin} · {esc(issue["rationale"])}</p><pre>before: {esc(issue["before"]["requirement"])}</pre><pre>after: {esc(issue["after"])}</pre>')
        parts.append(f'<a href="#rule-{esc(issue["rule_id"])}">查看原规则与出处</a>')
        for kind, label in [('support', '支持材料'), ('counter', '反对材料')]:
            parts.append(f'<h3>{label}</h3>')
            for ref in issue[kind]:
                anchor = ref['source_id'] + '-' + ref['candidate_id']
                parts.append(f'<a href="#candidate-{esc(anchor)}">{esc(ref["candidate_id"])}</a> ')
        parts.append(f'<p>未知：{esc(issue["unknowns"])}</p></article>')
    options = ''.join(f'<option value="{esc(i["issue_id"])}">{esc(i["title"])}</option>' for i in state['issues'])
    parts.append('<fieldset><legend>记录审核决定</legend><p>个案处理与通用条款讨论分别保存；选择修改也不发布正式标准。</p>'
                 f'<label>问题<select id="issue">{options}</select></label>'
                 '<label>决定类型<select id="decision-type"><option value="case_decision">个案处理决定</option><option value="framework_proposal_review">Framework候选提案审核</option></select></label>'
                 '<label>本次个案的审稿记录<select id="case-source"></select></label>'
                 '<label>处理<select id="action"><option value="keep">保留</option><option value="change">修改</option><option value="need_material">补材料</option><option value="defer">暂缓</option></select></label>'
                 '<label>本项理由<textarea id="decision-reason"></textarea></label><button id="queue" type="button">加入决定队列</button>'
                 '<ul id="draft-list"></ul><label>操作者（声明）<input id="actor"></label><label>本次审核说明<textarea id="reason"></textarea></label>'
                 '<button id="download" type="button">下载决定补丁</button><p id="save-status" role="status">草稿尚未应用。本页关闭会丢失未下载草稿。</p>'
                 '<p>下载不等于保存成功。用本机 batch-apply 应用补丁，再 batch-recover 并重开此页查看已应用历史。</p></fieldset>')
    parts.append('<h2>已应用决定及历史</h2>')
    for decision in state['decisions']:
        parts.append(f'<article class="saved-decision"><p>{esc(decision["issue_id"])} · {esc(decision["decision_type"])} · {esc(decision["action"])} · <strong>{esc(decision["validity"])}</strong></p><p>个案来源：{esc(decision.get("case_source_id") or "不适用（通用条款讨论）")} · 修订 {decision["revision"]}</p><p>{esc(decision["reason"])}</p><p>{esc(decision["actor"])} · {esc(decision["at"])} · {esc(decision["decision_id"])}</p></article>')
    envelope = dict(schema_version=1, batch_id=state['batch_id'], base_revision=state['revision'], package_sha256=state['package_sha256'])
    cases = {i['issue_id']: list(dict.fromkeys(r['source_id'] for kind in ('support', 'counter') for r in i[kind])) for i in state['issues']}
    data = json.dumps(dict(envelope=envelope, issue_cases=cases), ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    parts.append('<script id="batch-data" type="application/json">' + data + '</script><script>' + Path(__file__).with_name('batch_editor.js').read_text(encoding='utf-8') + '</script>')
    return '\n'.join(parts) + '</html>'
