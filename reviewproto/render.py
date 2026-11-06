"""Static editor report, without remote resources or executable source text."""
import html
import json

from .store import template


def esc(value):
    return html.escape(str(value), quote=True)


def render(state):
    previous = {d["candidate_id"]: d for d in state["decisions"]}
    parts = ["""<!doctype html><html lang="zh"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; form-action 'none'; base-uri 'none'">
<title>内部审稿证据复核</title><style>
body{font:16px/1.7 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17212e;background:#f4f6f8}
section,article{background:white;border:1px solid #c8d0da;border-radius:8px;padding:1rem;margin:1rem 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef1f5;padding:.7rem}textarea{width:100%;min-height:360px;box-sizing:border-box}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #b8c2cd;padding:.4rem;text-align:left}mark{background:#ffed9b}
button{font:inherit;padding:.5rem 1rem;cursor:pointer}small{color:#3f5267}code{overflow-wrap:anywhere}</style>
<h1>内部审稿证据复核</h1><p><strong>仅供可信编辑。本报告、原件、补丁和派生观点均为本地受控材料；没有作者导出。</strong></p>
<p>规则基线按完整段落产生待复核候选，仅对明确成对字面条件句展示两路结构。语义抽取尚未验证，规则匹配和关键词提示均待人工复核；跨段条件请阅读整个分区。论文未核验，A条款待对照。身份、轮次、量表版本和送审版本关系未知。</p>"""]
    parts.append(f'<p>来源 ID：<code>{esc(state["source"]["source_id"])}</code>；修订：{state["revision"]}。<a href="source.docx" download>打开冻结原件 source.docx</a>（内容哈希绑定，仅供可信编辑）。偏移：Unicode 字符，左闭右开；原文不规范化。</p>')
    parts.append(f'<p>来源性质：{esc(state["source"]["origin"])}；表上自报稿件ID（仅表单自报，未核实配对）：{esc(state["source"]["reported_manuscript_id"])}</p>')
    parts.append('<p>读取范围仅限四项评分和两个评论单元格。表头身份字段及表外段落未作内容分析，请按 source.docx 人工检查；本文不能作为整篇论文或完整材料核验。</p>')
    conditional = [c for c in state["candidates"] if c["alternatives"] or (c["candidate_id"] in previous and previous[c["candidate_id"]]["value"]["alternatives"])]
    parts.append('<nav aria-label="复核入口"><p><a href="#editor">进入单条人工复核表单</a></p>')
    if conditional:
        parts.append('<p>含条件分支的待审候选：</p><ul>')
        for candidate in conditional:
            cid = candidate["candidate_id"]
            parts.append(f'<li><a href="#candidate-{esc(cid)}">{esc(candidate["section_id"])} · 查看条件两路及原句 {esc(cid[:8])}</a></li>')
        parts.append('</ul>')
    parts.append('</nav>')
    parts.append('<section><h2>教师原始评分</h2><table><tr><th>原标签/量表</th><th>原始字符串</th><th>状态</th><th>位置</th></tr>')
    for score in state["scores"]:
        parts.append(f'<tr><td>{esc(score["label"])}</td><td><pre>{esc(json.dumps(score["raw_value"], ensure_ascii=False))}</pre></td><td>{esc(score["missing_state"])}；原因关系 unknown</td><td>{esc(score["locator"])}</td></tr>')
    parts.append('</table><p>原分不会被人工观点补丁覆盖；数值不是机器生成的理由依据。</p></section>')
    for section in state["sections"]:
        sid = section["section_id"]
        parts.append(f'<section id="{esc(sid)}"><h2>{esc(section["label"])}</h2><p>{esc(sid)} · {esc(section["visibility"])} · {esc(section["locator"])}</p><h3>冻结原文</h3><pre>{esc(section["text"])}</pre>')
        for candidate in (c for c in state["candidates"] if c["section_id"] == sid):
            cid = candidate["candidate_id"]
            decision = previous.get(cid)
            current = decision["value"] if decision else candidate
            parts.append(f'<article id="candidate-{esc(cid)}"><h3>候选 {esc(cid)}</h3><p>机器待复核；当前状态：{esc(current["status"])}；来源：{esc(current["origin"])} · <a href="#{esc(sid)}">查看分区全文</a> · <a class="edit-candidate" data-candidate="{esc(cid)}" href="#editor">复核此条</a></p>')
            for group in current["alternatives"]:
                parts.append(f'<h4>可审校分支 · {esc(group["relation"])} · {esc(group["provenance"])}</h4><ul>')
                for branch in group["branches"]:
                    meaning = next((condition["meaning"] for condition in current["conditions"] if condition["text"] == branch["condition"]), "unknown")
                    parts.append(f'<li>{esc(branch["condition"])}（具体条件含义：{esc(meaning)}） → {esc(branch["action"])}</li>')
                parts.append('</ul><p>以上保留条件及原动作；规则匹配仍待复核，不代表所有论文必须执行。</p>')
            parts.append('<h4>当前证据位置</h4>')
            for evidence in current["evidence"]:
                start, end = evidence["start"], evidence["end"]
                left, right = max(0, start - 45), min(len(section["text"]), end + 45)
                parts.append(f'<p>{esc(sid)} [{start}, {end}) · 精确证据及最多45字符相邻上下文</p><pre>{"…" if left else ""}{esc(section["text"][left:start])}<mark>{esc(section["text"][start:end])}</mark>{esc(section["text"][end:right])}{"…" if right < len(section["text"]) else ""}</pre>')
            parts.append(f'<details><summary>机器候选（保留原始版本）</summary><pre>{esc(json.dumps(candidate, ensure_ascii=False, indent=2))}</pre></details>')
            summary = {k: current[k] for k in ("status", "object", "attributes", "action", "direction", "requirement_strength", "interpretation")}
            labels = {"status": "复核状态", "object": "评价对象", "attributes": "属性（多标签）", "action": "动作", "direction": "评价方向", "requirement_strength": "要求强度", "interpretation": "明确/推断/未知", "conditions": "条件及含义", "alternatives": "替代或条件分支", "relations": "依据关系"}
            parts.append('<table><tr><th>当前字段</th><th>值</th></tr>' + ''.join(f'<tr><td>{esc(labels[k])}</td><td>{esc(json.dumps(v, ensure_ascii=False))}</td></tr>' for k, v in summary.items()) + '</table>')
            parts.append(f'<details><summary>当前完整结构（高级）</summary><pre>{esc(json.dumps(current, ensure_ascii=False, indent=2))}</pre></details>')
            if decision:
                parts.append(f'<p>人工决定：{esc(decision["actor"])} · {esc(decision["at"])} · 理由：{esc(decision["reason"])}</p>')
            parts.append('</article>')
        parts.append('</section>')
    parts.append('''<section id="editor"><h2>保存人工复核</h2>
<ol><li>先核对候选原句及冻结原件；在下方单条表单选择候选，填写修改人和理由。</li>
<li>选择“人工确认”“拒绝候选”或“仍待复核”，按需修改对象、动作和方向。未确定的语义轴保持 unknown。</li>
<li>点击“下载此条复核补丁”，将补丁保存到本工作区，运行 <code>python -m reviewproto apply work/本工作区/patch.json --workspace work/本工作区</code>；成功后重新打开 report.html。
也可运行 <code>python -m reviewproto review --workspace work/本工作区</code>，用文本编辑器修改工作区 patch.json，再 apply。</li>
<li>保存会校验证据、结构、权限和修订号。旧补丁冲突时重新导出后修改；完全相同的补丁重复应用幂等。重跑保留人工决定，历史在 state.json；产物中断可运行 recover 重建。</li></ol>
<p>此静态页面不会直接写入工作区，也不会发送网络请求。下载只是生成待应用补丁。</p>
''')
    base = template(state)
    parts.append('<label>选择一条候选 <select id="candidate">')
    for candidate in state["candidates"]:
        label = f'{candidate["section_id"]} · {candidate["candidate_id"]} · {candidate["evidence"][0]["quote"][:55]}'
        parts.append(f'<option value="{esc(candidate["candidate_id"])}">{esc(label)}</option>')
    parts.append('''</select></label><p><label>修改人 <input id="actor" autocomplete="off"></label> <label>理由 <input id="reason" size="50" autocomplete="off"></label></p>
<p><label>复核决定 <select id="status"><option value="needs_review">仍待复核</option><option value="confirmed">人工确认</option><option value="rejected">拒绝候选</option></select></label>
<label>方向 <select id="direction"><option>unknown</option><option>positive</option><option>negative</option><option>mixed</option><option>neutral</option></select></label></p>
<p><label>对象 <input id="object" size="50"></label></p><p><label>动作 <input id="action" size="70"></label></p>
<p>简单表单一次保存一条候选；条件、替代、多个证据等在高级 JSON 内修改。修改高级 JSON 后请直接下载，切换候选会重新载入其当前字段。</p>
<details><summary>高级：结构化字段与精确证据 JSON</summary>
<p>条件、替代、多标签属性及多段证据可在此修改。evidence 中 quote 必须与 Unicode 左闭右开 start/end 精确一致；不能更改分区或扩大权限。attributes 可分别填写样本规模、代表性。conditions 项格式示意：{"text":"条件原意","meaning":"unknown","evidence_indices":[0],"provenance":"explicit"}。alternatives 的 branches 各保留 condition、action、evidence_indices，关系 relation 可为 conditional_branches 或 either_or；示意字段不是本记录事实。</p>
<textarea id="patch" aria-label="人工复核补丁"></textarea></details>
<textarea id="base" hidden aria-hidden="true">''')
    parts.append(esc(json.dumps(base, ensure_ascii=False, indent=2)))
    parts.append('''</textarea><p><button id="download">下载此条复核补丁</button> <span id="message" role="status"></span></p></section>
<script>
const base=JSON.parse(document.getElementById('base').value);
const ids=['status','direction','object','action'];
function selected(){return base.edits.find(e=>e.candidate_id===document.getElementById('candidate').value);}
function load(){const item=selected();if(!item)return;for(const id of ids)document.getElementById(id).value=item.fields[id];sync(true);}
function sync(reset=false){let patch;if(reset){patch={...base,edits:[structuredClone(selected())]};}else{try{patch=JSON.parse(document.getElementById('patch').value);}catch(e){return;}}
patch.actor=document.getElementById('actor').value;patch.reason=document.getElementById('reason').value;
for(const id of ids)patch.edits[0].fields[id]=document.getElementById(id).value;
document.getElementById('patch').value=JSON.stringify(patch,null,2);}
document.getElementById('candidate').addEventListener('change',load);
for(const link of document.querySelectorAll('.edit-candidate'))link.addEventListener('click',()=>{document.getElementById('candidate').value=link.dataset.candidate;load();});
for(const id of [...ids,'actor','reason'])document.getElementById(id).addEventListener('input',()=>sync());
load();
document.getElementById('download').addEventListener('click',()=>{
const message=document.getElementById('message');try{
const patch=JSON.parse(document.getElementById('patch').value);
if(typeof patch.actor!=='string'||!patch.actor.trim()||typeof patch.reason!=='string'||!patch.reason.trim())throw Error();
const blob=new Blob([JSON.stringify(patch,null,2)+'\\n'],{type:'application/json;charset=utf-8'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='patch.json';a.click();URL.revokeObjectURL(a.href);
message.textContent='已生成待应用补丁；请在本地运行 apply。';}catch(e){message.textContent='请检查 JSON、修改人及理由。';}});</script></html>''')
    return "".join(parts)
