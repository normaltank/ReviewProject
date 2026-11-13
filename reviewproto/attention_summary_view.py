"""Embeddable, escaped, script-free saved summary. Main page integration is separate."""
from hashlib import sha256
from html import escape

_LABELS = {'explicit': '明确对应', 'partial': '部分对应', 'related': '相关',
           'undetermined': '暂未定', 'needs_review': '待核对', 'working': '工作解释',
           'confirmed': '已核对分析', 'content': '内容关注', 'disposition': '流程或总体处置'}


def render_summary(summary):
    """Return a complete HTML section; consume only summarize()'s saved result."""
    def text(value):
        if isinstance(value, list):
            value = '；'.join(str(v) for v in value)
        return escape(str(value if value is not None else '未说明'), quote=True)

    def label(value):
        return text(_LABELS.get(value, value))

    def anchor(rid):
        return 'attention-summary-record-' + sha256(rid.encode('utf-8')).hexdigest()[:20]

    def metric(value):
        links = '、'.join(f'<a href="#{anchor(rid)}">{text(rid)}</a>' for rid in value['record_ids']) or '无命中记录'
        return f'<span class="as-number">{value["count"]}/{value["denominator"]}</span> <span>{links}</span>'

    def evidence(entries):
        return ''.join('<blockquote>' + text(e.get('quote', '')) + '<br><small>出处：' +
                       text(e.get('section_id')) + ' · ' + text(e.get('start')) + '–' +
                       text(e.get('end')) + '</small></blockquote>' for e in entries)

    def rows(title, values, names=None):
        names = names or {}
        return '<h3>' + text(title) + '</h3><ul>' + ''.join(
            '<li><strong>' + text(names.get(key, _LABELS.get(key, key))) + '</strong> ' + metric(value) + '</li>'
            for key, value in values.items()) + '</ul>'

    output = ['''<section class="attention-summary" aria-label="已保存关注分布">
<style>
.attention-summary{font:16px/1.6 system-ui,sans-serif;color:#17212e;background:#f7f9fb;padding:1rem;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere}
.attention-summary h2{font-size:1.5rem;margin:0 0 .75rem}.attention-summary h3{font-size:1.15rem;margin:1.8rem 0 .5rem}
.attention-summary p,.attention-summary ul{margin:.5rem 0 1rem}.attention-summary ul{padding-left:1.4rem}.attention-summary li{margin:.5rem 0}
.attention-summary a{color:#254e70;text-underline-offset:.2em}.attention-summary a:hover{color:#17212e}.attention-summary :focus-visible{outline:2px solid #315879;outline-offset:3px}
.attention-summary ::selection{background:#cbdff0;color:#17212e}.attention-summary .as-number{font-variant-numeric:tabular-nums;white-space:nowrap}
.attention-summary details{border-top:1px solid #c8d0da;padding:.75rem 0}.attention-summary summary{cursor:pointer;min-height:2rem}
.attention-summary blockquote{margin:.5rem 0;padding:.5rem;background:#eef1f5;white-space:pre-wrap}.attention-summary small{color:#3f5267}
.attention-summary .as-source{white-space:pre-wrap}.attention-summary :target{outline:2px solid #315879;outline-offset:3px}
@media(max-width:600px){.attention-summary{padding:.6rem}.attention-summary ul{padding-left:1.1rem}}
</style><h2>本批关注分布</h2>''']
    output.append(f'<p>已保存修订 {text(summary["revision"])} · 分母 {summary["denominator"]["count"]} 条评语记录</p>')
    output.append('<p>表达、套话候选、方向与状态筛选只改变命中；记录与材料筛选改变分母。零命中仍列为 0/N；分母为零时不计算比例。</p>')
    output.append('<p>各项可重叠，父主题及A部分按记录取并集。工作解释可见；部分、相关、暂未定及待核均不合称明确覆盖。处置和条件关系单列。</p>')
    output.append('<p>数字描述本批表达，不代表群体重要性、论文质量或A权重；未提及不表示不关注。下载或未应用草稿不会改变本视图。</p>')
    output.append('<p><small>分析规则：' + text(summary['rules_version']) + ' · 计数规则：' + text(summary['summary_rules_version']) +
                  ' · A版本：' + text(summary['a_version']) + ' · 材料状态：' + text(summary['material_status']) + '</small></p>')
    if summary['filters']:
        filter_names = {'record_ids':'评语记录', 'paper_ids':'材料组', 'directions':'判断方向', 'statuses':'核对状态', 'functions':'表达作用', 'boilerplate_candidate':'套话候选'}
        output.append('<p>当前筛选：' + '；'.join(text(filter_names[k]) + '：' + text(v) for k,v in summary['filters'].items()) + '</p>')
    output.append(rows('主题与父组', summary['themes'], {k:v['label'] for k,v in summary['theme_definitions'].items()}))
    for key, title, definitions, id_key, name_key in [
            ('a_parts', 'A五部分（并集）', summary['a_reference'].get('parts', []), 'id', 'label'),
            ('a_items', 'A条目', summary['a_reference'].get('items', []), 'id', 'text')]:
        output.append('<h3>' + title + '</h3>')
        if not definitions:
            output.append('<p>尚未导入分组或条目；不推测旧参照分组。</p>')
        for definition in definitions:
            output.append('<details><summary>' + text(definition[id_key]) + ' · ' + text(definition[name_key]) + '</summary><ul>')
            output.extend('<li>' + label(kind) + ' ' + metric(value) + '</li>' for kind,value in summary[key][definition[id_key]].items())
            output.append('</ul></details>')
    output.append(rows('未能确定条目的A关联', summary['a_unassigned']))
    output.append(rows('当前清单外（按核对状态）', summary['outside']))
    output.append(rows('判断方向', summary['directions']))
    output.append(rows('内容方面核对状态', summary['statuses']))
    output.append('<h3>辅助观点与方面数</h3><ul>')
    for kind in ('content', 'disposition'):
        group = summary[kind]
        output.append('<li>' + label(kind) + '：' + str(group['opinions']['count']) + ' 个观点，' + str(group['facets']['count']) + ' 个方面；记录 ' + metric(group['records']) + '</li>')
    output.append('</ul>' + rows('条件、理由及其他关系（记录集合）', summary['relations']))
    for relation in summary['relation_details']:
        output.append('<details><summary>关系：' + text(relation['type']) + '</summary><p>范围：' + text(relation.get('scope')) +
                      ' · 状态：' + label(relation.get('status')) + '</p><p>' + text(relation.get('reading')) + '</p>' + evidence(relation.get('evidence', [])) + '</details>')
    output.append('<h3>记录明细与原话回查</h3>')
    for rid, detail in summary['details'].items():
        record = detail['record']
        output.append('<details id="' + anchor(rid) + '"><summary>' + text(rid) + ' · ' + str(len(detail['facets'])) + ' 个命中方面</summary>')
        output.append('<p>材料组：' + text(record.get('locator', {}).get('paper_id')) + '</p>')
        sections = record.get('sections') or [dict(text=record.get('text', ''), section_id=record.get('anchor', ''))]
        for section in sections:
            output.append('<p>普通分区：' + text(section.get('section_id')) + '</p><blockquote class="as-source">' + text(section.get('text')) + '</blockquote>')
        output.append('<p>原分：' + '；'.join(text(s.get('label')) + '：' + text(s.get('raw_value')) for s in record.get('scores', [])) + '</p>')
        if not detail['facets']:
            output.append('<p>没有命中方面；该记录仍在本次分母中。</p>')
        for entry in detail['facets']:
            facet = entry['facet']
            output.append('<h4>' + text(facet.get('interpretation')) + '</h4><p>' + label(facet.get('kind', 'content')) + ' · ' + label(facet.get('status')) + '</p>')
            output.append(evidence(facet.get('evidence', [])))
            expr = facet.get('expression') or {}
            boiler = {True:'是候选', False:'非候选', None:'未判断'}.get(expr.get('boilerplate_candidate'))
            output.append('<p>表达作用：' + text(expr.get('function')) + ' · 套话候选：' + text(boiler) + '</p>')
            qualifiers = {'object':'对象','direction':'方向','degree':'程度','negation':'否定','reasons':'理由','conditions':'条件','actions':'动作','examples':'例示','alternatives':'备选'}
            output.append('<ul>' + ''.join('<li>' + name + '：' + text(facet.get('qualifiers', {}).get(k)) + '</li>' for k,name in qualifiers.items() if facet.get('qualifiers', {}).get(k)) + '</ul>')
            for link in facet.get('a_links', []):
                output.append('<p>A关联：' + text(link.get('a_item_id')) + ' · ' + label(link.get('kind')) + ' · ' + label(link.get('status')) + ' · 版本：' + text(link.get('version')) + '</p><p>范围：' + text(link.get('scope')) + '；依据：' + text(link.get('reason')) + '</p>')
            for entry in facet.get('outside', []):
                output.append('<p>清单外范围：' + text(entry.get('scope')) + '；依据：' + text(entry.get('reason')) + ' · ' + label(entry.get('status')) + '</p>')
        output.append('</details>')
    output.append('</section>')
    return ''.join(output)
