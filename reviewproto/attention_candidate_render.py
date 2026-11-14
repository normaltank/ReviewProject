"""Display-only candidate evidence and positions over the frozen saved revision."""
import copy
import html
import json

from .attention_model import apply_objects
from .attention_positions import project_positions
from .attention_render import render
from .attention_summary import summarize


def render_candidate_preview(run):
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
    acceptance = ('已在修订 ' + str(run['accepted_revision']) + ' 接收；这里展示生成时的待核原候选，不代表当前人工纠正结果。请恢复并重开普通关注页查看当前保存结果。'
                  if run.get('accepted_revision') is not None else '尚未接收，全部待核。生成与预览不改变正式分析。回到本机候选窗口显式接收后，再打开关注页纠正并保存。')
    out = ['<section id="candidate-preview"><h1>B内容与A位置候选 · 预览</h1>',
           '<p>' + acceptance + '</p>',
           '<p>下方“已保存”区域来自生成时冻结的修订 ' + str(saved['revision']) +
           '，不是实时保存状态。候选位置另列，不进入保存统计。</p>']
    out.append('<p><a href="#candidate-position-overlay">查看候选建议位置图与钻取</a> · <a href="#candidate-details">查看候选明细</a></p>')
    status = {'complete': '处理完成', 'partial': '部分处理', 'failed': '处理失败',
              'zero_candidates': '零候选', 'running': '未完成'}
    out.append('<p>运行 ' + esc(run['run_id']) + ' · ' + status.get(run['status'], '未完成') +
               ' · ' + ('工程回放（非实际推理）' if run['mode'] == 'replay' else '实际本机推理') +
               ' · ' + ('绑定有效' if run.get('validity') == 'current' else '输入或修订已变，须重新生成') + '</p>')
    out.append('<p>处理状态不表示语义正确或人工确认。跨记录主题仍须人工整理。</p>')
    out.append('<h2>处理范围与未完成项</h2><ul>')
    for item in run.get('coverage', []):
        out.append('<li>' + esc(item['record_id']) + ' · 全部分区：' +
                   esc(' / '.join(item['section_ids'])) + ' · ' +
                   ('部分处理' if item['status'] == 'partial' else '已处理（仍须核对遗漏）') + '</li>')
    for item in run.get('unprocessed', []):
        explanation = {'B stage failed or capacity exceeded': '整条记录处理未完成或超出容量',
                       'A mapping missing or rejected': 'A对照缺失或被拒收'}.get(item.get('reason'), item.get('reason', '未完成'))
        out.append('<li>未完成：' + esc(item.get('record_id', item.get('facet_id', ''))) +
                   ' · ' + esc(item.get('section_id', 'A对照')) + ' · ' + esc(explanation) +
                   ' · 请回查范围并重新生成或人工补录。</li>')
    out.append('</ul><p>处理错误 ' + str(len(run.get('errors', []))) + ' 项；拒收 ' +
               str(len(run.get('rejected', []))) + ' 项。完整运行记录保存在本包候选历史中。</p>')
    failures = {
        'E_ATTENTION_CAPACITY': '整条记录或A参照超出本次容量，未截断原文。请调整所选范围或人工补录。',
        'E_ATTENTION_QUOTE': '引文与原话不一致，该项已拒收。请重新生成或在普通关注页人工补录。',
        'E_ATTENTION_QUOTE_AMBIGUOUS': '重复引文没有足够位置消歧，该项已拒收。请回查重复片段后人工补录。',
        'E_ATTENTION_RANGE': '引文位置无效，该项已拒收。请回查完整原话后重新生成或人工补录。',
        'E_ATTENTION_MACHINE_STATUS': '候选试图自行确认，已拒收。模型候选必须待核。',
        'E_ATTENTION_A_REWRITE': 'A对照试图改写B内容，已拒收；有效B草稿仍保留。',
        'E_ATTENTION_B_STAGE': 'B阶段混入A位置判断，已拒收。请重新生成并核对分析范围。',
        'E_ATTENTION_RESPONSE_TRUNCATED': '模型输出未完整结束，该次响应未接收。请核对模型设置后重新生成。',
        'E_ATTENTION_HTTP': '本机模型请求未完成。请检查模型是否运行，再重新生成。',
        'E_ATTENTION_PROVIDER': '模型未返回可用结果。请检查本机服务后重新生成。',
    }
    out.append('<ul>')
    for item in run.get('errors', []) + run.get('rejected', []):
        out.append('<li>' + ('拒收候选：' if item in run.get('rejected', []) else '处理未完成：') +
                   failures.get(item.get('code'), '响应缺少有效证据、范围或结构，未接收该项。请回查原话后重新生成或人工补录。') + '</li>')
    out.append('</ul>')
    qualifiers = dict(object='对象', direction='判断方向', degree='程度', negation='否定',
                      reasons='理由', conditions='条件', actions='动作', examples='例示', alternatives='备选')
    out.append('<h2 id="candidate-details">候选明细与逐字证据</h2>')
    for op in projected['opinions']:
        for f in op['facets']:
            if f['facet_id'] not in candidate_ids:
                continue
            out.append('<details id="candidate-facet-' + esc(f['facet_id']) + '"><summary>' +
                       esc(f['interpretation']) + ' · 待核</summary><p>记录 ' + esc(op['record_id']) +
                       ' · 观点：' + esc(op['interpretation']) + '</p>')
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
            for p in placements:
                if p['facet_id'] == f['facet_id']:
                    region = next(r for r in positions['regions'] if r['id'] == p['region_id'])
                    out.append('<p>建议位置（待核）：' + esc(region['label']) + ' · 范围：' + esc(p['scope']) +
                               ' · 理由：' + esc(p['reason']) + '</p>')
            for m in f['themes']:
                theme = next(t for t in projected['themes'] if t['theme_id'] == m['theme_id'])
                out.append('<p>主题：' + esc(theme['label']) + ' · 定义：' + esc(theme['definition']) +
                           ' · 成员依据：' + esc(m['reason']) + ' · 待核</p>')
            out.append('</details>')
    if not candidate_ids:
        out.append('<p>没有可接收候选。请查看未完成范围，调整所选记录或人工补录。</p>')
    out.append('<h2>候选关系（待核）</h2>')
    for r in patch.get('relations', []):
        out.append('<details><summary>' + esc(r['type']) + '</summary>')
        for e in r['endpoints']:
            out.append('<p>' + esc(e['role']) + ' · <a href="#candidate-facet-' + esc(e['facet_id']) + '">查看方面证据</a></p>')
        for key, label in [('direction', '方向'), ('scope', '范围'), ('reading', '读法'), ('ambiguity', '歧义')]:
            out.append('<p>' + label + '：' + esc(r[key]) + '</p>')
        for e in r['evidence']:
            out.append('<blockquote>' + esc(e['quote']) + '</blockquote>')
        out.append('</details>')
    out.append('<h2>本次所选原话与原分</h2>')
    for r in saved['records']:
        if r['record_id'] not in run['record_ids']:
            continue
        out.append('<details id="candidate-source-' + esc(r['record_id']) + '"><summary>' + esc(r['anchor']) + '</summary>')
        for s in r['sections']:
            out.append('<h3>' + esc(s['section_id']) + '</h3><pre style="white-space:pre-wrap">' + esc(s['text']) + '</pre>')
        for score in r.get('scores', []):
            out.append('<p>' + esc(score['label']) + '：' + esc(score['raw_value']) + '</p>')
        out.append('</details>')
    out.append('</section>')
    data = json.dumps(overlay, ensure_ascii=True).replace('<', '\\u003c')
    script = '''<script>document.addEventListener('click',e=>{const a=e.target.closest('a');if(!a?.hash?.startsWith('#candidate-'))return;const t=document.getElementById(decodeURIComponent(a.hash.slice(1)));if(t){for(let p=t;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;t.tabIndex=-1;t.focus();}});AttentionPositions.setOverlay(''' + data + ');</script>'
    page = render(saved)
    # Keep the existing saved-state editor and navigation intact. Candidate
    # objects only exist in the independent details and overlay above.
    return page.replace('</style>', '</style><body>' + ''.join(out), 1).replace('</html>', script + '</html>')
