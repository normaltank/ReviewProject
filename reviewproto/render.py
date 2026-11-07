"""Static editor report, without remote resources or executable source text."""
import html
import json

from .store import template, source_filename
from .understanding import current_views, effective_views


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
button{font:inherit;padding:.5rem 1rem;cursor:pointer}small{color:#3f5267}code{overflow-wrap:anywhere}
#review-cost select{max-width:100%}#review-cost button{margin-block:.2rem}</style>
<h1>内部审稿证据复核</h1><p><strong>仅供可信编辑。本报告、原件、补丁和派生观点均为本地受控材料；没有作者导出。</strong></p>
<p>规则基线按完整段落产生待复核候选，仅对明确成对字面条件句展示两路结构。语义抽取尚未验证，规则匹配和关键词提示均待人工复核；跨段条件请阅读整个分区。论文未核验，A条款待对照。身份、轮次、量表版本和送审版本关系未知。</p>"""]
    filename = source_filename(state)
    parts.append(f'<p>来源 ID：<code>{esc(state["source"]["source_id"])}</code>；修订：{state["revision"]}。<a href="{filename}" download>打开冻结原件 {filename}</a>（内容哈希绑定，仅供可信编辑）。偏移：Unicode 字符，左闭右开；原文不规范化。</p>')
    parts.append(f'<p>来源性质：{esc(state["source"]["origin"])}；表上自报稿件ID（仅表单自报，未核实配对）：{esc(state["source"]["reported_manuscript_id"])}</p>')
    parts.append('<p>读取范围以当前来源覆盖说明为准。元数据只保存原样自报值，不确认稿件、教师或送审版本配对；本文不能作为整篇论文或完整材料核验。</p>')
    baseline = sum(c['origin'] == 'rule_candidate' for c in state['candidates'])
    model = sum(c['origin'] == 'model_candidate' for c in state['candidates'])
    parts.append(f'<section><h2>复核队列与当前人工观点</h2><p>段落基线 {baseline}；模型候选 {model}；当前人工确认的独立观点 {len(effective_views(state))}。基线与各模型运行并存，不自动合并计数。拒绝、废弃及被替换记录保留历史，不计入当前已确认观点。</p>')
    for view in effective_views(state):
        parts.append(f'<p><a href="#candidate-{esc(view["candidate_id"])}">{esc(view["candidate_id"])}</a> · {esc(view["object"])} · {esc(view["action"])} · 概念 {esc(view.get("concept_ids", []))}</p>')
    parts.append('</section><section><h2>机器候选运行记录</h2>')
    for run in state.get('extraction_runs', []):
        parts.append(f'<details><summary>{esc(run["run_id"])} · {esc(run["model"])} · {esc(run["status"])} · 接收 {len(run["accepted_ids"])} / 拒收 {len(run["rejected"])}</summary><pre>{esc(json.dumps(run, ensure_ascii=False, indent=2))}</pre></details>')
    parts.append('<p>zero_candidates、partial 和 failed 均须复核；不是“已确认没有意见”。模型定位通过也不等于理解正确。</p></section><section><h2>候选概念与 A 条款来源</h2>')
    parts.append('<p>概念用稳定 concept_id 引用；自由属性名仅作旧候选描述。A 来源均为待核候选，不具有正式标准效力；观点可以保持 pending_comparison。</p>')
    for concept in state.get('concepts', []):
        parts.append(f'<details><summary>概念 {esc(concept["concept_id"])} · {esc(concept["name"])} · {esc(concept["status"])}</summary><pre>{esc(json.dumps(concept, ensure_ascii=False, indent=2))}</pre></details>')
    for clause in state.get('clauses', []):
        parts.append(f'<details><summary>A 候选 {esc(clause["clause_id"])} · {esc(clause["source_kind"])} · pending_source_review</summary><pre>{esc(json.dumps(clause, ensure_ascii=False, indent=2))}</pre></details>')
    parts.append('</section>')
    conditional = [c for c in state["candidates"] if c["alternatives"] or (c["candidate_id"] in previous and previous[c["candidate_id"]]["value"]["alternatives"])]
    parts.append('<nav aria-label="复核入口"><p><a href="#editor">进入单条人工复核表单</a></p>')
    if conditional:
        parts.append('<p>含条件分支的待审候选：</p><ul>')
        for candidate in conditional:
            cid = candidate["candidate_id"]
            parts.append(f'<li><a href="#candidate-{esc(cid)}">{esc(candidate["section_id"])} · 查看条件两路及原句 {esc(cid[:8])}</a></li>')
        parts.append('</ul>')
    parts.append('</nav>')
    parts.append('<section id="score-comparison"><h2>教师原始评分</h2><table><tr><th>原标签/量表</th><th>原始字符串</th><th>状态</th><th>位置</th><th>已记录的观点关系</th></tr>')
    active_views = [c for c in current_views(state) if c['status'] not in {'rejected', 'withdrawn', 'superseded'}]
    for score in state["scores"]:
        links = []
        for view in active_views:
            for relation in view['relations']:
                if relation['type'] == 'explains_score' and relation['target'] == score['label']:
                    links.append(f'<a href="#candidate-{esc(view["candidate_id"])}">{esc(view["candidate_id"])}</a> · {esc(relation["provenance"])} · {esc(view["status"])}')
        relationship = '<br>'.join(links) if links else 'unknown（未记录解释关系）'
        parts.append(f'<tr><td>{esc(score["label"])}</td><td><pre>{esc(json.dumps(score["raw_value"], ensure_ascii=False))}</pre></td><td>{esc(score["missing_state"])}</td><td>{esc(score["locator"])}</td><td>{relationship}</td></tr>')
    parts.append('</table><p>原分不会被观点补丁覆盖。关联分别显示明确、推断或未知及观点复核状态；推断不证明实际给分原因。拒绝、废弃和被替换观点不进入本表关联。数值不是机器生成理由的依据，不自动判评分矛盾。</p></section>')
    for section in state["sections"]:
        sid = section["section_id"]
        parts.append(f'<section id="{esc(sid)}"><h2>{esc(section["label"])}</h2><p>{esc(sid)} · {esc(section["visibility"])} · {esc(section["locator"])}</p><h3>冻结原文</h3><pre>{esc(section["text"])}</pre>')
        for candidate in (c for c in state["candidates"] if c["section_id"] == sid):
            cid = candidate["candidate_id"]
            decision = previous.get(cid)
            current = decision["value"] if decision else candidate
            parts.append(f'<article id="candidate-{esc(cid)}"><h3>观点 / 候选 {esc(cid)}</h3><p>初始来源：{esc(candidate["origin"])}；运行：{esc(candidate.get("run_id", "baseline_or_human"))}；当前状态：{esc(current["status"])}；当前来源：{esc(current["origin"])} · <a href="#{esc(sid)}">查看分区全文</a> · <a class="edit-candidate" data-candidate="{esc(cid)}" href="#editor">复核此条</a></p>')
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
            score_links = [r for r in current['relations'] if r['type'] == 'explains_score']
            parts.append(f'<p>原分关系（明确 / 推断 / 未知）：{esc(json.dumps(score_links, ensure_ascii=False)) if score_links else "unknown（没有已记录的解释关系）"}；条款对照：{esc(json.dumps(current.get("clause_links", []), ensure_ascii=False)) if current.get("clause_links") else "pending_comparison"}</p>')
            parts.append('<details><summary>人工历史 / 父子和替换记录</summary><pre>' + esc(json.dumps({'parent_ids': current.get('parent_ids', []), 'replaces': current.get('replaces', []), 'history': [d for d in state['decisions'] if d['candidate_id'] == cid]}, ensure_ascii=False, indent=2)) + '</pre></details>')
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
<div id="review-cost"><h3>复核会话计时（可选）</h3>
<p>先填写上方修改人，再选择自报角色和本次比较组。开始时固定这些声明；比较组仅记录本次观察对象，不筛选或隐藏页面候选。</p>
<p><label>自报角色 <select id="cost-actor-kind"><option value="unknown">未知 / 未声明</option><option value="human_editor">专业编辑（本人自报）</option><option value="agent">代理 / 自动化试用</option></select></label>
<label>比较组 <select id="cost-arm"><option value="rule_baseline">规则基线</option>''')
    for run in state.get('extraction_runs', []):
        parts.append(f'<option value="{esc("run:" + run["run_id"])}">运行 {esc(run["run_id"])}</option>')
    parts.append('''<option value="mixed">混合</option></select></label></p>
<p><button id="cost-start" type="button">开始计时</button> <button id="cost-pause" type="button" disabled>暂停</button> <button id="cost-finish" type="button" disabled>结束会话</button> <button id="cost-download" type="button" disabled>下载计时记录</button></p>
<p id="cost-status" role="status">未开始；打开页面不计工时。</p>
<p><output id="cost-elapsed">活动 0.0 秒；暂停 0.0 秒</output></p>
<p><small>暂停或切换到隐藏标签页会停止活动计时，返回后需手动继续。仅记录开始后至结束前的输入事件数、拆分/补录按钮尝试数和补丁下载按钮尝试数；它们不等于逻辑修正次数或补丁已应用次数。计时记录独立下载，不写入观点补丁，不含原文或评分；角色自报与活动时长不能证明真实专业工时。未下载记录在刷新或重开后丢失，本页不跨页恢复。</small></p></div>
<p><label>复核决定 <select id="status"><option value="needs_review">仍待复核</option><option value="confirmed">人工确认</option><option value="rejected">拒绝候选</option><option value="superseded">已由子观点替换</option><option value="withdrawn">废弃观点</option></select></label>
<label>方向 <select id="direction"><option>unknown</option><option>positive</option><option>negative</option><option>mixed</option><option>neutral</option></select></label></p>
<p><label>对象 <input id="object" size="50"></label></p><p><label>动作 <input id="action" size="70"></label></p>
<p>简单表单一次保存一条候选；条件、替代、多个证据等在高级 JSON 内修改。修改高级 JSON 后请直接下载，切换候选会重新载入其当前字段。</p>
<p><label>在首条证据的第几个 Unicode 字符后拆分 <input id="split-offset" type="number" min="1" value="1"></label> <button id="split" type="button">拆为两条独立观点</button></p>
<p>拆分将生成两个稳定 ID，并以 replaces 记录替换父候选；父记录保留历史。两条新观点默认待核，条件、理由和关联清空，须在高级 JSON 分别核对补充。拆分位置由编辑指定，不代表机器已完成语义切分。</p>
<p><label>补录分区 <select id="add-section"></select></label> <label>起点 <input id="add-start" type="number" value="0" min="0"></label> <label>终点 <input id="add-end" type="number" value="1" min="1"></label> <button id="add-opinion" type="button">补录一条遗漏观点</button></p>
<p>补录同样使用 Unicode 左闭右开偏移。高级 JSON 可添加同区多处 evidence、reasons、conditions、alternatives、concept_ids 和 clause_links；概念定义可通过补丁顶层 concepts 列表保存（稳定 ID、name、definition、positive_examples、negative_examples、boundary、status、sources）。废弃可在 status 填 withdrawn。</p>
<details><summary>高级：结构化字段与精确证据 JSON</summary>
<p>条件、替代、多标签属性及多段证据可在此修改。evidence 中 quote 必须与 Unicode 左闭右开 start/end 精确一致；不能更改分区或扩大权限。attributes 可分别填写样本规模、代表性。conditions 项格式示意：{"text":"条件原意","meaning":"unknown","evidence_indices":[0],"provenance":"explicit"}。alternatives 的 branches 各保留 condition、action、evidence_indices，关系 relation 可为 conditional_branches 或 either_or；示意字段不是本记录事实。</p>
<textarea id="patch" aria-label="人工复核补丁"></textarea></details>
<textarea id="base" hidden aria-hidden="true">''')
    parts.append(esc(json.dumps(base, ensure_ascii=False, indent=2)))
    parts.append('</textarea><textarea id="sections-data" hidden>' + esc(json.dumps(state['sections'], ensure_ascii=False)) + '</textarea>')
    parts.append('''<p><button id="download">下载此条复核补丁</button> <span id="message" role="status"></span></p></section>
<script>
const base=JSON.parse(document.getElementById('base').value);
const sections=JSON.parse(document.getElementById('sections-data').value);
for(const section of sections){const option=document.createElement('option');option.value=section.section_id;option.textContent=section.section_id+' · '+section.label;document.getElementById('add-section').append(option);}
const ids=['status','direction','object','action'];
function selected(){return base.edits.find(e=>e.candidate_id===document.getElementById('candidate').value);}
function load(){const item=selected();if(!item)return;for(const id of ids)document.getElementById(id).value=item.fields[id];sync(true);}
function sync(reset=false){let patch;if(reset){patch={...base,edits:[structuredClone(selected())]};}else{try{patch=JSON.parse(document.getElementById('patch').value);}catch(e){return;}}
patch.actor=document.getElementById('actor').value;patch.reason=document.getElementById('reason').value;
const entry=patch.edits[0]||(patch.creates||[])[0];if(entry)for(const id of ids)entry.fields[id]=document.getElementById(id).value;
document.getElementById('patch').value=JSON.stringify(patch,null,2);}
document.getElementById('candidate').addEventListener('change',load);
for(const link of document.querySelectorAll('.edit-candidate'))link.addEventListener('click',()=>{document.getElementById('candidate').value=link.dataset.candidate;load();});
for(const id of ids)document.getElementById(id).addEventListener('input',()=>sync());
for(const id of ['actor','reason'])document.getElementById(id).addEventListener('input',()=>{try{const p=JSON.parse(document.getElementById('patch').value);p[id]=document.getElementById(id).value;document.getElementById('patch').value=JSON.stringify(p,null,2);}catch(e){}});
load();
function freshId(){return 'human-'+crypto.randomUUID();}
let costSession=null,costPhase='idle',costTick=0;
const costStatus=document.getElementById('cost-status');
function settleCost(){if(!costSession||costPhase==='finished')return;const now=performance.now(),elapsed=Math.max(0,now-costTick);if(costPhase==='active')costSession.active_elapsed_ms+=elapsed;else if(costPhase==='paused')costSession.paused_elapsed_ms+=elapsed;costTick=now;}
function showCost(){settleCost();document.getElementById('cost-elapsed').textContent='活动 '+((costSession?.active_elapsed_ms||0)/1000).toFixed(1)+' 秒；暂停 '+((costSession?.paused_elapsed_ms||0)/1000).toFixed(1)+' 秒';}
function countAttempt(name){if(costSession&&costPhase!=='finished')costSession.attempt_counts[name]++;}
document.getElementById('cost-start').addEventListener('click',()=>{
if(document.hidden)return;
if(costPhase==='idle'){const actor=document.getElementById('actor').value.trim();if(!actor){costStatus.textContent='请先填写上方修改人，再开始计时。';document.getElementById('actor').focus();return;}
const choice=document.getElementById('cost-arm').value;
costSession={artifact_type:'review_cost_observation',schema_version:1,session_id:crypto.randomUUID(),source_id:base.source_id,base_revision:base.base_revision,actor,actor_kind:document.getElementById('cost-actor-kind').value,arm:choice.startsWith('run:')?{kind:'extraction_run',run_id:choice.slice(4)}:{kind:choice,run_id:null},started_at_utc:new Date().toISOString(),finished_at_utc:null,active_elapsed_ms:0,paused_elapsed_ms:0,attempt_counts:{editor_input_events:0,split_button_attempts:0,add_opinion_button_attempts:0,patch_download_button_attempts:0}};
for(const id of ['cost-actor-kind','cost-arm'])document.getElementById(id).disabled=true;
}else if(costPhase==='paused')settleCost();else return;
costTick=performance.now();costPhase='active';document.getElementById('cost-start').disabled=true;document.getElementById('cost-pause').disabled=false;document.getElementById('cost-finish').disabled=false;costStatus.textContent='计时中；修改人与角色、比较组采用开始时声明。';showCost();});
function pauseCost(){if(costPhase!=='active')return;settleCost();costPhase='paused';document.getElementById('cost-start').disabled=false;document.getElementById('cost-start').textContent='继续计时';document.getElementById('cost-pause').disabled=true;costStatus.textContent='已暂停；返回后请手动继续。';showCost();}
document.getElementById('cost-pause').addEventListener('click',pauseCost);
document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseCost();});
document.getElementById('cost-finish').addEventListener('click',()=>{if(!costSession||costPhase==='finished')return;settleCost();costPhase='finished';costSession.finished_at_utc=new Date().toISOString();costSession.active_elapsed_ms=Math.round(costSession.active_elapsed_ms);costSession.paused_elapsed_ms=Math.round(costSession.paused_elapsed_ms);for(const id of ['cost-start','cost-pause','cost-finish'])document.getElementById(id).disabled=true;document.getElementById('cost-download').disabled=false;costStatus.textContent='会话已结束；请下载独立记录。刷新前未下载的记录会丢失。';showCost();});
document.getElementById('cost-download').addEventListener('click',()=>{if(costPhase!=='finished')return;const blob=new Blob([JSON.stringify(costSession,null,2)+'\\n'],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='review-cost-'+costSession.session_id+'.json';a.click();URL.revokeObjectURL(a.href);});
document.getElementById('editor').addEventListener('input',event=>{if(event.target.matches('input,select,textarea')&&!event.target.closest('#review-cost'))countAttempt('editor_input_events');});
for(const [id,name] of [['split','split_button_attempts'],['add-opinion','add_opinion_button_attempts'],['download','patch_download_button_attempts']])document.getElementById(id).addEventListener('click',()=>countAttempt(name));
setInterval(showCost,250);
function cleanFields(){return {status:'needs_review',interpretation:'unknown',object:'unknown',attributes:[],direction:'unknown',speech_function:'unknown',requirement_strength:'unknown',severity:'unknown',action:'unknown',conditions:[],alternatives:[],relations:[],reasons:[],negation:'unknown',concept_ids:[],clause_links:[]};}
function writeCreates(creates){const p={...base,edits:[],creates,actor:document.getElementById('actor').value,reason:document.getElementById('reason').value};document.getElementById('patch').value=JSON.stringify(p,null,2);document.getElementById('message').textContent='已生成新增观点草稿，请展开高级 JSON 逐条复核后下载。';document.getElementById('patch').parentElement.open=true;}
document.getElementById('split').addEventListener('click',()=>{try{const item=selected(),e=item.fields.evidence[0],chars=Array.from(e.quote),n=Number(document.getElementById('split-offset').value);if(!Number.isInteger(n)||n<=0||n>=chars.length)throw Error();const pieces=[[0,n],[n,chars.length]].map(([a,b])=>({candidate_id:freshId(),section_id:e.section_id,parent_ids:[item.candidate_id],replaces:[item.candidate_id],fields:{...cleanFields(),evidence:[{...e,start:e.start+a,end:e.start+b,quote:chars.slice(a,b).join('')}]}}));writeCreates(pieces);}catch(e){document.getElementById('message').textContent='拆分位置必须处于首条证据内部。';}});
document.getElementById('add-opinion').addEventListener('click',()=>{try{const s=sections.find(v=>v.section_id===document.getElementById('add-section').value),a=Number(document.getElementById('add-start').value),b=Number(document.getElementById('add-end').value),chars=Array.from(s.text);if(!Number.isInteger(a)||!Number.isInteger(b)||a<0||b<=a||b>chars.length)throw Error();writeCreates([{candidate_id:freshId(),section_id:s.section_id,parent_ids:[],replaces:[],fields:{...cleanFields(),evidence:[{source_id:s.source_id,section_id:s.section_id,start:a,end:b,quote:chars.slice(a,b).join(''),precision:'exact'}]}}]);}catch(e){document.getElementById('message').textContent='请核对分区与 Unicode 起止偏移。';}});
document.getElementById('download').addEventListener('click',()=>{
const message=document.getElementById('message');try{
const patch=JSON.parse(document.getElementById('patch').value);
if(typeof patch.actor!=='string'||!patch.actor.trim()||typeof patch.reason!=='string'||!patch.reason.trim())throw Error();
const blob=new Blob([JSON.stringify(patch,null,2)+'\\n'],{type:'application/json;charset=utf-8'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='patch.json';a.click();URL.revokeObjectURL(a.href);
message.textContent='已生成待应用补丁；请在本地运行 apply。';}catch(e){message.textContent='请检查 JSON、修改人及理由。';}});</script></html>''')
    return "".join(parts)
