"""Display-only candidate evidence and positions over the frozen saved revision."""
import copy
import html
import json

from .attention_model import apply_objects
from .attention_positions import project_positions
from .attention_render import render
from .attention_summary import summarize
from .attention_candidates import request_audit


def render_candidate_preview(run, *, workbench_url=None, result_url=None):
    saved = copy.deepcopy(run['snapshot'])
    projected = copy.deepcopy(saved)
    patch = run['patch']
    if any(patch.get(k) for k in ('edits', 'themes', 'relations')):
        apply_objects(projected, copy.deepcopy(patch))
    candidate_ids = {f['facet_id'] for o in patch['edits'] for f in o['facets']}
    positions = project_positions(summarize(projected))
    placements = [dict(p, detail_id='candidate-facet-' + p['facet_id'])
                  for p in positions['placements'] if p['facet_id'] in candidate_ids]
    overlay = dict(analysis_id=saved['analysis_id'], base_revision=saved['revision'],
                   a_version=saved['a_reference']['version'], label=run['run_id'], placements=placements,
                   validity=run.get('validity'), accepted_revision=run.get('accepted_revision'))
    esc = lambda value: html.escape(str(value), quote=True)
    if run.get('accepted_revision') is not None:
        acceptance = '已在修订 ' + str(run['accepted_revision']) + ' 保存，仍需核对。此页保留生成时的候选。'
    elif run.get('validity') != 'current':
        acceptance = '候选已失效。此页保留生成时的记录。'
    elif run['status'] in {'complete', 'partial'} and patch['edits']:
        operation = '返回工作台点“显式接收此候选”' if workbench_url else '回分析窗口点“保存分析”'
        acceptance = '结果尚未保存。核对后可' + operation + '。'
    else:
        acceptance = '本次运行没有可接收的候选。'
    result_url = result_url or '../../attention.html'
    result_label = '查看当前已保存结果' if workbench_url else '查看当前已保存结果（编辑请从桌面打开）'
    status = {'complete': '处理完成', 'partial': '部分处理', 'failed': '处理失败',
              'zero_candidates': '未生成候选', 'running': '未完成'}
    records = {r['record_id']: r for r in saved['records']}
    record_label = lambda rid: records.get(rid, {}).get('anchor') or rid
    partial_count = sum(item['status'] == 'partial' for item in run.get('coverage', []))
    progress = ('' if run['status'] == 'partial' and partial_count else status.get(run['status'], '未完成') + ' · ') + str(len(run['record_ids'])) + ' 条记录 · ' + str(len(candidate_ids)) + ' 条解释'
    if partial_count:
        progress += ' · 部分处理 ' + str(partial_count) + ' 条'
    if run.get('unprocessed'):
        progress += ' · 未完成范围 ' + str(len(run['unprocessed'])) + ' 项'
    out = ['<section id="candidate-preview"><h1>评语分析结果</h1>',
           '<p>' + acceptance + '</p><p id="page-draft" role="status"></p>',
           ('<p><a href="' + esc(workbench_url) + '">返回工作台核对候选</a></p>') if workbench_url else '',
           '<p class="candidate-meta">' + progress + '</p>',
           '<nav aria-label="候选导航"><a href="#candidate-visualization">查看分布图</a><a href="#candidate-sources">查看原话与原分</a><a href="#candidate-audit">查看处理明细</a></nav>']
    if run['mode'] == 'replay':
        out.append('<p class="candidate-meta">工程回放（非实际推理）</p>')
    if run.get('validity') != 'current' and (not workbench_url or run.get('accepted_revision') is None):
        recovery = '可在工作台重新生成。' if workbench_url else '须重新生成。以下仅供回查。'
        out.append('<p class="reading-warning">输入或修订已变。' + recovery + '</p>')
    reading = out
    out = []
    audit=request_audit(run)
    if run['mode'] != 'replay':
        out.append('<p>' + ('DeepSeek API联网推理' if run['mode']=='remote_api' else '实际本机推理') + '</p>')
    out.append('<p>已记录的提供方尝试数：'+(str(audit['count']) if audit['count'] is not None else '未知')+'。尝试数不代表服务器已收到请求、完成响应或计费成功。</p>')
    if audit['unfinished']:
        reading.append('<p class="reading-warning">请求结果与用量未知：运行可能仍在执行或已经中断；不会自动继续或重试。请展开处理范围与运行明细核对。</p>')
        out.append('<p>运行尚未结束，可能仍在执行或已经中断。已开始而未保存响应的尝试：'+(str(audit['pending_response']) if audit['pending_response'] is not None else '未知')+'；结果与用量未知，不代表服务器已收到或已计费。不会自动继续或重试，请核对原运行记录。</p>')
        if audit['count'] is None:
            out.append('<p>旧运行缺少完整尝试标记，次数未知，不能按0处理。</p>')
    out.append('<h2>处理范围与未完成项</h2><ul>')
    for item in run.get('coverage', []):
        out.append('<li>' + esc(record_label(item['record_id'])) + ' · 全部分区：' +
                   esc(' / '.join(item['section_ids'])) + ' · ' +
                   ('部分处理' if item['status'] == 'partial' else '已处理（仍须核对遗漏）') + '</li>')
    for item in run.get('unprocessed', []):
        explanation = {'B stage failed or capacity exceeded': '整条记录处理未完成或超出容量',
                       'A mapping missing or rejected': 'A对照缺失或被拒收',
                       'B output rejected; no accepted candidates formed for this source': '此来源输出被拒收，未形成可接收候选；不表示模型未读取原文'}.get(item.get('reason'), item.get('reason', '未完成'))
        out.append('<li>未完成：' + esc(record_label(item.get('record_id', item.get('facet_id', '')))) +
                   ' · ' + esc(item.get('section_id', 'A对照')) + ' · ' + esc(explanation) +
                   ' · 请回查范围并重新生成或人工补录。</li>')
    out.append('</ul><p>处理错误 ' + str(len(run.get('errors', []))) + ' 项；拒收 ' +
               str(len(run.get('rejected', []))) + ' 项。完整运行记录保存在本包候选历史中。</p>')
    repair_count=sum(c.get('purpose')=='format_repair' for c in run.get('calls',[]))
    if repair_count:
        attempts=audit['format_repair_count']
        out.append('<p>发生格式修复 '+str(repair_count)+' 次（实际请求 '+(str(attempts) if attempts is not None else '未知')+' 次）；首次失败、原始草稿与各次用量均保留。修复不等于语义通过，运行保持部分或失败状态。</p>')
    failures = {
        'E_ATTENTION_JSON_FORMAT': '模型草稿不是有效JSON，原始输出保留；符合条件时最多一次格式修复。请查看修复记录及未形成候选的来源。',
        'E_ATTENTION_SCHEMA_FORMAT': '模型JSON不符合原字段结构，原始输出和校验详情保留；符合条件时最多一次格式修复，逐字与语义核对仍独立执行。',
        'E_DEEPSEEK_CREDENTIAL_MISSING': 'DeepSeek API密钥缺失。请在模型设置输入并保存，或设置DEEPSEEK_API_KEY后重新生成。',
        'E_DEEPSEEK_CREDENTIAL_STORE': 'API凭据无法解密。请用当前Windows用户重新保存，或显式设置环境变量。',
        'E_ATTENTION_API_TRANSPORT': 'DeepSeek API连接未完成。请检查网络后显式重新生成；不会自动重试或回退本机。',
        'E_ATTENTION_CAPACITY': '整条记录或A参照超出本次容量，未截断原文。请调整所选范围或人工补录。',
        'E_ATTENTION_CAPACITY_CHECK': '本机容量预检未完成，尚未发出该次模型推理。请核对本机服务后重新生成；原文未截断。',
        'E_ATTENTION_CAPACITY_PROFILE': '输出长度小于已验证配置所需的768，尚未发出该次推理。请提高最大输出长度后重新生成。',
        'E_ATTENTION_RELATION_CONNECTION': '关系类型缺少原文明示的连接依据；未接收该关系，原提议保留在运行审计供人工核对。',
        'E_ATTENTION_RELATION_ROLE': '关系端点角色不能对应原文的实际作用；未接收该关系，原提议保留供人工核对。',
        'E_ATTENTION_RELATION_RANGE': '关系端点或作用范围未绑定到相应连接证据；未接收该关系，原提议保留供人工核对。',
        'E_ATTENTION_RELATION_TEXT': '关系解释用了来源或方面ID占位；未接收该关系，原提议保留供人工核对。',
        'E_ATTENTION_QUALIFIER_ROLE': '限定片段缺少所填作用的明确依据；未采用该字段，原话及原提议保留供核对。',
        'E_ATTENTION_QUOTE': '引文与原话不一致，该项已拒收。请重新生成或在普通关注页人工补录。',
        'E_ATTENTION_QUOTE_AMBIGUOUS': '重复引文没有足够位置消歧，该项已拒收。请回查重复片段后人工补录。',
        'E_ATTENTION_RANGE': '引文位置无效，该项已拒收。请回查完整原话后重新生成或人工补录。',
        'E_ATTENTION_MACHINE_STATUS': '候选试图自行确认，已拒收。模型候选必须待核。',
        'E_ATTENTION_A_REWRITE': 'A对照试图改写B内容，已拒收；有效B草稿仍保留。',
        'E_ATTENTION_B_STAGE': 'B阶段混入A位置判断，已拒收。请重新生成并核对分析范围。',
        'E_ATTENTION_RESPONSE_TRUNCATED': '模型输出未完整结束，该次响应未接收。请核对模型设置后重新生成。',
        'E_ATTENTION_HTTP': '模型请求未完成。请核对提供方、网络或本机服务；本次没有HTTP重试。',
        'E_ATTENTION_PROVIDER': '模型未返回可用结果。请核对提供方及原始运行记录后显式重新生成。',
    }
    out.append('<ul>')
    for item in run.get('errors', []) + run.get('rejected', []):
        field_label={'examples':'例示','negation':'否定'}.get(item.get('field'))
        out.append('<li>' + ('拒收候选：' if item in run.get('rejected', []) else '处理未完成：') +
                   (field_label+'字段：' if field_label else '') +
                   failures.get(item.get('code'), '响应缺少有效证据、范围或结构，未接收该项。请回查原话后重新生成或人工补录。') + '</li>')
    out.append('</ul>')
    # Raw calls and extensible diagnostics can contain private reasoning. They
    # stay in the local audit, never in ordinary HTML (even inside a disclosure).
    out.append('<p>运行 ' + esc(run['run_id']) +
               '：完整请求、原始响应、用量及原始错误/拒收记录仅保存在本地候选历史的 run.json，供操作员回查；不嵌入普通页面。</p>')
    audit_html = ''.join(out)
    out = reading
    qualifiers = dict(object='对象', direction='判断方向', degree='程度', negation='否定',
                      reasons='理由', conditions='条件', actions='动作', examples='例示', alternatives='备选')
    out.append('<h2 id="candidate-details">B关注什么，与A如何对应</h2>')
    for op in projected['opinions']:
        for f in op['facets']:
            if f['facet_id'] not in candidate_ids:
                continue
            links = [p for p in placements if p['facet_id'] == f['facet_id']]
            regions = {r['id']: r for r in positions['regions']}
            kind_names = {'explicit': '明确对应', 'partial': '部分对应', 'related': '内容相关', 'undetermined': '暂未定'}
            descriptions = []
            for p in links:
                region = regions[p['region_id']]
                if region['id'] == 'pending':
                    continue
                title = region['label']
                title = title[:52] + '…' if len(title) > 52 else title
                phrase = (kind_names.get(p.get('proposed_kind'), '') + '：' if region['kind'] == 'item' else '') + title
                if phrase not in descriptions:
                    descriptions.append(phrase)
            correspondence = ('；'.join(descriptions) or '尚未确定A对应') if saved['a_reference']['items'] else '尚未导入A'
            full = f['interpretation']
            prefix = full.split('：')[0]
            title = prefix if prefix != full and 10 <= len(prefix) <= 72 else full[:100] + '…' if len(full) > 100 else full
            out.append('<details id="candidate-facet-' + esc(f['facet_id']) + '"><summary>' +
                       esc(title) + '<span class="candidate-meta">与A：' + esc(correspondence) + '</span></summary>')
            if title != full:
                out.append('<p>完整解释：' + esc(full) + '</p>')
            out.append('<p class="candidate-meta">原话来自：' + esc(record_label(op['record_id'])) + '</p>')
            out.append('<p>表达作用：' + esc(f['expression']['function'] or '未说明') + ' · 套话候选：' +
                       {True: '是', False: '否', None: '未判断'}[f['expression']['boilerplate_candidate']] + '</p>')
            for key, label in qualifiers.items():
                if f['qualifiers'].get(key):
                    value = f['qualifiers'][key]
                    out.append('<p>' + label + '：' + esc(' / '.join(value) if isinstance(value, list) else value) + '</p>')
            for e in f['evidence']:
                out.append('<blockquote>' + esc(e['quote']) + '</blockquote><p>' + esc(e['section_id']) +
                           ' · 字符 ' + str(e['start']) + '–' + str(e['end']) +
                           ' · <a href="#candidate-source-' + esc(op['record_id']) + '">查看本条完整原话与原分</a></p>')
            out.append('<details><summary>与A对照的范围和理由</summary>')
            for p in placements:
                if p['facet_id'] == f['facet_id']:
                    region = next(r for r in positions['regions'] if r['id'] == p['region_id'])
                    out.append('<p>建议位置（待核）：' + esc(region['label']) + ' · 范围：' + esc(p['scope']) +
                               ' · 理由：' + esc(p['reason']) + '</p>')
            out.append('</details>')
            for m in f['themes']:
                theme = next(t for t in projected['themes'] if t['theme_id'] == m['theme_id'])
                out.append('<p>主题：' + esc(theme['label']) + ' · 定义：' + esc(theme['definition']) +
                           ' · 成员依据：' + esc(m['reason']) + ' · 待核</p>')
            out.append('</details>')
    if not candidate_ids:
        out.append('<p>没有可接收候选。请查看未完成范围，调整所选记录或人工补录。</p>')
    if patch.get('relations'):
        out.append('<h2>候选关系（待核）</h2>')
    for r in patch.get('relations', []):
        out.append('<details><summary>' + esc(r.get('reading') or r.get('scope') or '查看联系') + '</summary>')
        for e in r['endpoints']:
            out.append('<p>' + esc(e['role']) + ' · <a href="#candidate-facet-' + esc(e['facet_id']) + '">查看方面证据</a></p>')
        for key, label in [('direction', '方向'), ('scope', '范围'), ('reading', '读法'), ('ambiguity', '歧义')]:
            out.append('<p>' + label + '：' + esc(r[key]) + '</p>')
        for e in r['evidence']:
            out.append('<blockquote>' + esc(e['quote']) + '</blockquote>')
        out.append('</details>')
    out.append('<details id="candidate-visualization"><summary>查看候选分布图</summary></details>')
    out.append('<details id="candidate-audit"><summary>处理范围与运行明细 · 错误 ' + str(len(run.get('errors', []))) + ' 项 / 拒收 ' + str(len(run.get('rejected', []))) + ' 项</summary>' + audit_html + '</details>')
    out.append('<details id="candidate-sources"><summary>本次所选原话与原分</summary>')
    for r in saved['records']:
        if r['record_id'] not in run['record_ids']:
            continue
        out.append('<details id="candidate-source-' + esc(r['record_id']) + '"><summary>' + esc(r['anchor']) + '</summary>')
        for s in r['sections']:
            out.append('<h3>' + esc(s['section_id']) + '</h3><pre style="white-space:pre-wrap">' + esc(s['text']) + '</pre>')
        for score in r.get('scores', []):
            out.append('<p>' + esc(score['label']) + '：' + esc(score['raw_value']) + '</p>')
        out.append('</details>')
    out.append('</details></section>')
    data = json.dumps(overlay, ensure_ascii=True).replace('<', '\\u003c')
    script = '<script>AttentionPositions.setOverlay(' + data + ');document.getElementById("candidate-visualization").before(document.getElementById("view-filters"));</script>'
    page = render(saved)
    # Keep the existing reading/position views, without an editable snapshot.
    start = page.index('<details id="attention-editor">')
    end = page.index('<script id="attention-data"', start)
    page = page[:start] + page[end:]
    from pathlib import Path
    editor = Path(__file__).with_name('attention_editor.js').read_text(encoding='utf-8')
    page = page.replace('<script>' + editor + '</script>', '')
    page = page.replace("node('button','查看原话并修改',", "if(document.getElementById('attention-editor'))node('button','查看原话并修改',")
    page = page.replace('<p id="page-draft" role="status"></p>', '')
    page = page.replace('<a href="#attention-editor">材料</a>', '')
    page = page.replace('</style><body>', '</style><body>' + ''.join(out) +
                        '<p><a href="' + esc(result_url) + '">' + result_label + '</a></p>' +
                        '<details id="candidate-saved"><summary>生成时的只读保存结果 · 修订 ' + str(saved['revision']) +
                        '</summary>', 1)
    page = page.replace('<script id="attention-data"', '</details><script id="attention-data"', 1)
    return page.replace('</body>', script + '</body>')
