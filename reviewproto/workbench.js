'use strict';
const $=id=>document.getElementById(id),token=JSON.parse($('workbench-session').textContent).token;
let current=null,jobs=[],browsePath='',draft={records:[],parts:[],items:[]};
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const notice=(text,error=false)=>{$('notice').textContent=text;$('notice').className=error?'error':'';};
async function api(route,data={}){const r=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Attention-Token':token},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
const errors={E_DEEPSEEK_CREDENTIAL_MISSING:'尚未配置DeepSeek，请展开分析设置保存自己的密钥；也可先人工阅读。',E_WORKBENCH_BUSY:'分析任务仍在运行。请等待任务完成后再关闭或重新分析。',E_ATTENTION_EMPTY:'没有可建立的B原话，或所选目录不是已有分析。',E_ATTENTION_NOT_DEDICATED:'目录已有内容。请填写新的空目录，已有内容已保护。',E_ATTENTION_REVALIDATION:'来源、A或保存修订已变化。请刷新核对并重新生成，旧候选仍保留。'};
function action(id,fn){$(id).onclick=async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){notice(errors[e.message]||'操作未完成（'+e.message+'）。输入草稿仍在，请核对后重试。',true);}finally{b.disabled=false;}};}
function show(name){for(const id of ['home','input','project'])$(id).hidden=id!==name;}
function field(parent,label,value='',tag='input'){const l=node('label',label),e=node(tag);e.value=value;l.append(e);parent.append(l);return e;}
function button(parent,label,fn){const b=node('button',label);b.type='button';b.onclick=fn;parent.append(b);return b;}
function removeButton(parent,label,fn){return button(parent,label,()=>{fn();renderDraft();});}
function renderDraft(){
 $('records').replaceChildren();draft.records.forEach((r,i)=>{const box=node('div');box.className='record';box.append(node('h3',r.kind==='workspace'?'已选择普通来源分区':'B评语 '+(i+1)));
 if(r.kind==='workspace')box.append(node('p',r.workspace+' / '+r.section_id));else{
 const row=node('div');row.className='row';box.append(row);field(row,'原话定位 / 名称',r.anchor).oninput=e=>r.anchor=e.target.value;field(row,'材料分组（可选）',r.paper_id).oninput=e=>r.paper_id=e.target.value;
 field(box,'完整原话',r.text,'textarea').oninput=e=>r.text=e.target.value;
 const more=node('details'),summary=node('summary','原分、来源与可见性');more.append(summary);box.append(more);
 field(more,'来源说明',r.locator).oninput=e=>r.locator=e.target.value;
 const visible=field(more,'可见性','','select');for(const [value,label] of [['author_visible','普通可见'],['visibility_unknown','可见性未知']]){const o=node('option',label);o.value=value;visible.append(o);}visible.value=r.visibility||'author_visible';visible.onchange=()=>r.visibility=visible.value;
 r.scores.forEach((s,j)=>{const row=node('div');row.className='score-row';more.append(row);field(row,'原分标签',s.label).oninput=e=>s.label=e.target.value;field(row,'原值（原样保留）',s.raw_value).oninput=e=>s.raw_value=e.target.value;removeButton(row,'移除此原分',()=>r.scores.splice(j,1));});
 button(more,'加入原分',()=>{r.scores.push({label:'',raw_value:''});renderDraft();});}
 removeButton(box,'移除此B',()=>draft.records.splice(i,1));$('records').append(box);});
 $('parts').replaceChildren();draft.parts.forEach((p,i)=>{const box=node('div');box.className='part';field(box,'A部分名称',p.label).oninput=e=>p.label=e.target.value;removeButton(box,'移除此部分',()=>{draft.parts.splice(i,1);draft.items.forEach(x=>{if(x.part_id===p.id)x.part_id='';});});$('parts').append(box);});
 $('items').replaceChildren();draft.items.forEach((item,i)=>{const box=node('div');box.className='a-item';box.append(node('h3','A条目 '+(i+1)));field(box,'完整条文与限定',item.text,'textarea').oninput=e=>item.text=e.target.value;field(box,'原文定位',item.locator).oninput=e=>item.locator=e.target.value;
 if(draft.parts.length){const select=field(box,'所属部分','','select');const empty=node('option','选择部分');empty.value='';select.append(empty);for(const p of draft.parts){const o=node('option',p.label);o.value=p.id;select.append(o);}select.value=item.part_id||'';select.onchange=()=>item.part_id=select.value;}
 removeButton(box,'移除此A条目',()=>draft.items.splice(i,1));$('items').append(box);});
}
function reference(){return {version:$('a-version').value,parts:draft.parts,items:draft.items.map(x=>{const r={...x};if(!draft.parts.length)delete r.part_id;return r;})};}
function inputPayload(){return {path:$('destination').value,records:draft.records,a_reference:draft.items.length?reference():undefined};}
async function home(){const h=await api('home');jobs=h.jobs; $('recent').replaceChildren();for(const path of h.recent)button($('recent'),path,()=>load(path).catch(e=>notice(e.message,true)));
 if(h.draft){draft={records:h.draft.records||[],parts:h.draft.a_reference?.parts||[],items:h.draft.a_reference?.items||[]};$('destination').value=h.draft.path||'';$('a-version').value=h.draft.a_reference?.version||'A-v1';renderDraft();}
 if(!$('destination').value)$('destination').value=h.data_dir+'/analysis-'+Date.now();notice('工作台已就绪。材料与结果保留在本机。');}
async function load(path){await display(await api('open',{path}));}
async function display(p){current=p;sessionStorage.setItem('active-analysis',p.id);$('show-current').hidden=false;show('project');$('project-title').textContent='当前分析 · '+p.state.records.length+'条B';$('project-meta').textContent='保存修订 '+p.state.revision+' · '+(p.state.a_reference.items.length?'A版本 '+p.state.a_reference.version:'尚未提供A参照');$('project-path').textContent=p.path;$('result').href=p.url;$('scope').replaceChildren();for(const r of p.state.records){const l=node('label');l.className='scope-record';const c=node('input');c.type='checkbox';c.checked=true;c.value=r.record_id;c.setAttribute('aria-label','分析 '+(r.paper_id||r.anchor||'B原话'));l.append(c);const body=node('div');body.append(node('strong',r.paper_id||r.anchor||'B原话'));body.append(node('pre',r.sections.map(s=>s.text).join('\n')));l.append(body);$('scope').append(l);}notice('分析已打开。可直接阅读，或选择原话后开始分析。');await runs();drawJobs();}
async function runs(){const p=current,h=await api('runs',{id:p.id});$('runs').replaceChildren();for(const run of h.runs){const box=node('div');box.className='job';box.append(node('p',run));candidateActions(box,p.id,run);$('runs').append(box);}}
function candidateActions(box,id,run){const a=node('a','核对待保存结果');a.href='/preview?id='+id+'&run='+run;box.append(a);button(box,'显式接收此候选',async()=>{try{const p=await api('accept',{id,run});if(current?.id===id)await display(p);notice('候选已保存到其原分析包。');}catch(e){notice(errors[e.message]||'候选未保存（'+e.message+'）。请核对预览和当前修订。',true);}});}
function drawJobs(){$('jobs').replaceChildren();for(const j of jobs){const box=node('div');box.className='job';box.append(node('p',j.path));box.append(node('strong',j.status==='running'?'正在分析 · '+j.phase:j.phase+' · '+({complete:'已完成',partial:'部分完成',failed:'失败',zero_candidates:'无可接收候选'}[j.status]||j.status)));box.append(node('p','固定修订 '+j.revision+'；已处理记录 '+(j.completed_records||0)+'；请求 '+(j.requests||0)));if(j.error)box.append(node('p',j.error));if(j.status!=='running')candidateActions(box,j.project,j.run);$('jobs').append(box);}}
action('show-current',async()=>{if(current)await display(await api('state',{id:current.id}));});
action('show-home',async()=>{show('home');await home();});action('show-input',async()=>{show('input');renderDraft();});action('new',async()=>{show('input');if(!draft.records.length)draft.records.push({anchor:'B1',text:'',locator:'网页录入',scores:[]});renderDraft();});action('add-b',async()=>{draft.records.push({anchor:'B'+(draft.records.length+1),text:'',locator:'网页录入',scores:[]});renderDraft();});
action('add-part',async()=>{draft.parts.push({id:'part-'+crypto.randomUUID(),label:''});renderDraft();});action('add-a',async()=>{draft.items.push({id:'item-'+crypto.randomUUID(),text:'',locator:'',part_id:draft.parts[0]?.id});renderDraft();});
action('save-draft',async()=>{await api('draft',inputPayload());notice('输入草稿已保存在本机。尚未建立分析。');});action('create',async()=>{await api('draft',inputPayload());await display(await api('create',inputPayload()));});action('open',()=>load($('open-path').value));
action('sample',async()=>{await display(await api('sample'));notice('已打开人工编写的纯合成示例。示例非模型结果、非专业金标，可直接读图并练习纠正保存。');});
action('save-key',async()=>{try{await api('credential',{key:$('api-key').value});notice('密钥已保存到本机凭据层。');}finally{$('api-key').value='';}});
action('generate',async()=>{const records=Array.from($('scope').querySelectorAll('input:checked')).map(e=>e.value);if(!records.length){notice('请至少选择一条B原话。',true);return;}const job=await api('generate',{id:current.id,records});jobs.push(job);drawJobs();notice('分析已启动。切换项目不会改变此任务的保存目标。');});
action('all-records',async()=>{$('scope').querySelectorAll('input').forEach(c=>c.checked=true);});action('no-records',async()=>{$('scope').querySelectorAll('input').forEach(c=>c.checked=false);});action('load-runs',runs);action('refresh',async()=>display(await api('state',{id:current.id})));action('import-a',async()=>display(await api('import-a',{id:current.id,a_reference:reference()})));
async function browse(path){const b=await api('browse',{path});browsePath=b.path;$('browse-path').textContent=b.path;$('browser').hidden=false;$('directories').replaceChildren();for(const p of b.directories)button($('directories'),p,()=>browse(p).catch(e=>notice(e.message,true)));$('parent').onclick=()=>browse(b.parent);}
action('browse',()=>browse($('open-path').value));action('choose-path',async()=>{$('open-path').value=browsePath;$('browser').hidden=true;});
action('source-load',async()=>{const path=$('source-path').value,h=await api('source',{path});$('source-sections').replaceChildren();for(const s of h.sections)button($('source-sections'),'加入 '+s.section_id,()=>{draft.records.push({kind:'workspace',workspace:path,section_id:s.section_id});renderDraft();notice('已加入普通来源分区，建立分析前会再次核验。');});});
action('stop',async()=>{await api('draft',inputPayload());await api('stop');notice('工作台已关闭。已保存分析与输入草稿保留，可关闭此页。');document.querySelectorAll('button').forEach(b=>b.disabled=true);});
setInterval(async()=>{for(let i=0;i<jobs.length;i++)if(jobs[i].status==='running'){try{jobs[i]=await api('job',{job:jobs[i].id});drawJobs();}catch{}}},1200);
home().then(async()=>{const id=sessionStorage.getItem('active-analysis');if(id){try{await display(await api('state',{id}));}catch{sessionStorage.removeItem('active-analysis');}}}).catch(e=>notice('无法读取工作台：'+e.message,true));
