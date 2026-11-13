"""Readable local framework evidence and revision discussions."""
import html
from urllib.parse import quote

from .framework import refresh_reviews


def esc(value):
    return html.escape(str(value), quote=True)


def listed(values):
    if not values:
        return '<p>未列出，须复核是否未知或不适用。</p>'
    return '<ul>' + ''.join('<li>' + esc(v) + '</li>' for v in values) + '</ul>'


def render_frameworks(state):
    refresh_reviews(state)
    if not state.get('frameworks'):
        return ''
    parts = ['<section id="frameworks"><h2>A 课程候选规则与 B 对照</h2><p>框架均为候选，正式效力、现行版本与适用范围待确认；来源字节及引文校验通过不代表专业听校或标准批准。没有自动判断或正式发布。</p>']
    for entry in state['frameworks']:
        book, fingerprint = entry['book'], entry['sha256']
        sources = {s['source_id']: s for s in book['sources']}
        parts.append(f'<article id="framework-{fingerprint}"><h3>{esc(book["title"])} · {esc(book["version"])}</h3><p>candidate · authority=unconfirmed · source_status=pending；正式版本 unknown。内容指纹 <code>{fingerprint}</code></p><h4>覆盖说明</h4>' + listed(book['coverage_notes']))
        for rule in book['rules']:
            anchor = fingerprint + '-' + rule['rule_id']
            derivation = '编辑操作化推断，须专业复核' if rule['derivation'] == 'editorial_operationalization' else '来源转述，仍非逐字原话'
            parts.append(f'<article id="rule-{esc(anchor)}"><h4>{esc(rule["rule_id"])} · {esc(rule["title"])} · {esc(rule["dimension_id"])}</h4><p><strong>要求：</strong>{esc(rule["requirement"])}</p><p>规则类型 {esc(rule["rule_type"])}；强度 {esc(rule["strength"])}；强度依据 {esc(rule["strength_provenance"])}；{derivation}。</p>')
            for key, label in [('applicable_when', '适用范围与条件'), ('exceptions', '例外'), ('unknowns', '未知与待核'), ('checks', '复核检查')]:
                parts.append('<h5>' + label + '</h5>' + listed(rule[key]))
            parts.append('<h5>冻结来源与逐字引文</h5>')
            for evidence in rule['evidence']:
                source = sources[evidence['source_id']]
                locator = evidence['locator']
                if source['kind'] == 'pptx_native':
                    location = f'PPT 第 {locator["page"]} 页，第 {locator["paragraph"]} 段（从 0 计）'
                    reliability = '原生文本定位；未核图像、讲解及正式效力'
                else:
                    location = '转写位置 ' + locator['pointer']
                    if 'time_range' in locator:
                        location += f'；{locator["time_range"][0]}–{locator["time_range"][1]} 秒'
                    if 'ppt_page' in locator:
                        location += f'；关联 PPT 第 {locator["ppt_page"]} 页'
                    reliability = 'machine_unchecked：机器转写，未人工回听'
                href = quote('frameworks/' + fingerprint + '/' + source['file'], safe='/')
                parts.append(f'<p><a href="{esc(href)}">{esc(source["source_id"])}</a> · {esc(location)} · [{evidence["start"]}, {evidence["end"]}) · {reliability}</p><blockquote><pre>{esc(evidence["quote"])}</pre></blockquote>')
            parts.append('</article>')
        parts.append('</article>')
    parts.append('<h3>B 对照记录与修订讨论草案</h3><p>通过 framework-template 导出待填写记录，再由 apply-framework-review 应用。只记录人工声明；评分原值保持冻结。B 候选补录、编辑或撤销后，历史对照与提案显示 needs_revalidation（需重新验证）。</p>')
    relations = {'covered': '覆盖', 'partial': '部分覆盖', 'condition_difference': '条件差异', 'potential_conflict': '潜在冲突（待专业核实）', 'uncovered': '未覆盖（待核）', 'pending_comparison': '待对照'}
    for review in state.get('framework_reviews', []):
        parts.append(f'<article><h4>对照修订 {review["revision"]} · {esc(review["actor"])}</h4><p>{esc(review["reason"])} · {esc(review["at"])}</p>')
        for row in review['alignments']:
            parts.append(f'<p><a href="#candidate-{esc(row["candidate_id"])}">B 观点 {esc(row["candidate_id"])}</a> → <a href="#rule-{esc(review["framework_sha256"] + "-" + row["rule_id"])}">{esc(row["rule_id"])}</a>：{esc(relations[row["relation"]])}；{esc(row["provenance"])}；<strong>{esc(row["validity"])}</strong></p><p>对照理由：{esc(row["rationale"])}</p>')
            for index in row['evidence_indices']:
                evidence = row['candidate_snapshot']['evidence'][index]
                parts.append(f'<pre>记录当时 B 引文 [{evidence["start"]}, {evidence["end"]})：{esc(evidence["quote"])}</pre>')
        for proposal in review['proposals']:
            kind = '来源解释调整' if proposal['kind'] == 'source_interpretation' else '出版社要求变更建议'
            parts.append(f'<article id="proposal-{esc(proposal["proposal_id"])}"><h4>{esc(proposal["proposal_id"])} · {kind}</h4><p>draft · needs_professional_review · baseline_confirmation_required；<strong>{esc(proposal["validity"])}</strong>。未修改正式标准。</p><p>条款 {esc(proposal["rule_id"])} · 框架版本与正式效力待确认。</p><p>理由：{esc(proposal["rationale"])}</p>')
            parts.append('<p>修改后内容是编辑提案（after_provenance=editorial_proposal），不是课程原话或已确认的来源转述。草案增补未获原文确认；原引文仅为修改前基线依据（evidence_scope=baseline_only）。两类建议均须另行核实与专业复核。</p><table><tr><th>字段</th><th>冻结修改前</th><th>建议修改后</th></tr>')
            for key, label in [('requirement', '要求'), ('applicable_when', '适用条件'), ('exceptions', '例外'), ('strength', '强度'), ('strength_provenance', '强度依据'), ('checks', '检查')]:
                before, after = proposal['before'][key], proposal['after'][key]
                before = listed(before) if isinstance(before, list) else esc(before)
                after = listed(after) if isinstance(after, list) else esc(after)
                parts.append(f'<tr><th>{label}</th><td>{before}</td><td>{after}</td></tr>')
            parts.append('</table>')
            for key, label in [('support_candidate_ids', '支持材料'), ('counter_candidate_ids', '反例材料')]:
                parts.append('<h5>' + label + '</h5>')
                for cid in proposal[key]:
                    snapshot = proposal['candidate_snapshots'][cid]
                    parts.append(f'<p><a href="#candidate-{esc(cid)}">{esc(cid)}</a> · {esc(snapshot["visibility"])}</p>')
                    for evidence in snapshot['evidence']:
                        parts.append('<pre>' + esc(evidence['quote']) + '</pre>')
                if not proposal[key]:
                    parts.append('<p>未提供，不能视为不存在。</p>')
            parts.append(f'<h5>独立验证计划</h5><p>{esc(proposal["validation_plan"])}</p><h5>回退条件</h5><p>{esc(proposal["rollback_condition"])}</p><h5>未知与待核</h5>' + listed(proposal['unknowns']) + '</article>')
        parts.append('</article>')
    parts.append('</section>')
    return ''.join(parts)
