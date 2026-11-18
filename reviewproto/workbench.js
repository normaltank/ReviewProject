'use strict';
const $=id=>document.getElementById(id),token=JSON.parse($('workbench-session').textContent).token;
let current=null,jobs=[],browsePath='',draft={records:[],parts:[],items:[]},aChange=null;
const scopes=new Map();
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const notice=(text,error=false)=>{$('notice').textContent=text;$('notice').className=error?'error':'';};
async function api(route,data={}){const r=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Attention-Token':token},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
const errors={E_DEEPSEEK_TRIAL_CONFIG:'本机试用配置文件无效，请重新解压完整试用包，或在分析设置中保存自己的密钥。',E_DEEPSEEK_CREDENTIAL_MISSING:'尚未配置DeepSeek，请展开分析设置保存自己的密钥；也可先人工阅读。',E_WORKBENCH_BUSY:'分析任务仍在运行。请等待任务完成后再关闭或重新分析。',E_ATTENTION_EMPTY:'没有可建立的B原话，或所选目录不是已有分析。',E_ATTENTION_NOT_DEDICATED:'目录已有内容。请填写新的空目录，已有内容已保护。',E_ATTENTION_REVALIDATION:'来源、A或保存修订已变化。请重新选择普通分区，或刷新后重新生成候选。',E_ATTENTION_OUTPUT_RECOVER:'数据库可能已保存。请在“维护当前分析”中点“恢复已保存视图”。',E_WORKBENCH_STOPPING:'工作台正在关闭。',E_ATTENTION_TARGET:'分析包或修订已变化，请重新核对。'};
function action(id,fn){$(id).onclick=async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){notice(errors[e.message]||'操作未完成（'+e.message+'）。输入草稿仍在，请核对后重试。',true);}finally{b.disabled=false;}};}
function show(name){for(const id of ['home','input','project'])$(id).hidden=id!==name;}
function field(parent,label,value='',tag='input'){const l=node('label',label),e=node(tag);e.value=value;l.append(e);parent.append(l);return e;}
function button(parent,label,fn){const b=node('button',label);b.type='button';b.onclick=fn;parent.append(b);return b;}
function removeButton(parent,label,fn){return button(parent,label,()=>{fn();renderDraft();});}
function renderDraft(){
 $('records').replaceChildren();draft.records.forEach((r,i)=>{const box=node('div');box.className='record';box.append(node('h3',r.kind==='workspace'?'已选择普通来源分区':'B评语 '+(i+1)));
 if(r.kind==='workspace'){
  box.append(node('p',r.label||r.section_id));
  box.append(node('pre',r.text||'请重新读取并选择普通分区。'));
  field(box,'材料分组（可选）',r.paper_id||'').oninput=e=>r.paper_id=e.target.value;
  const source=node('details');source.append(node('summary','来源位置'),node('p',r.workspace+' / '+r.section_id));box.append(source);
 }else{
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
function inputPayload(){return {path:$('destination').value,records:draft.records,a_reference:reference()};}
function configurationStatus(c){$('configuration-status').textContent=c.error?(errors[c.error]||'本机分析配置无法读取，请检查分析设置。'):c.configured?(c.source==='trial'?'试用配置已就绪。选择原话后可直接开始分析。':'个人分析配置已就绪。选择原话后可开始分析。'):'尚未配置分析服务，可在分析设置中保存密钥，也可先人工阅读。';}
async function home(restore=false){
 const h=await api('home');jobs=h.jobs;configurationStatus(h.configuration);
 $('recent').replaceChildren();
 for(const path of h.recent)button($('recent'),path,()=>load(path).catch(e=>notice(e.message,true)));
 if(restore&&h.draft){
  draft={records:h.draft.records||[],parts:h.draft.a_reference?.parts||[],items:h.draft.a_reference?.items||[]};
  $('destination').value=h.draft.path||'';$('a-version').value=h.draft.a_reference?.version??'A-v1';renderDraft();
 }
 if(!$('destination').value)$('destination').value=h.data_dir+'/analysis-'+Date.now();
 $('show-input').disabled=false;$('new').disabled=false;notice('');
}
async function load(path){await display(await api('open',{path}));}
function cancelA(){aChange=null;$('a-confirmation').hidden=true;}
async function display(p){
 current=p;cancelA();
 sessionStorage.setItem('active-analysis',p.id);$('show-current').hidden=false;show('project');
 $('project-title').textContent='当前分析 · '+p.state.records.length+'条B';
 $('project-meta').textContent='保存修订 '+p.state.revision+' · '+(p.state.a_reference.items.length?'A版本 '+p.state.a_reference.version:'尚未提供A参照');
 $('project-path').textContent=p.path;$('result').href=p.url;
 $('scope').replaceChildren();
 for(const r of p.state.records){
  const l=node('label');l.className='scope-record';
  const c=node('input');c.type='checkbox';c.checked=scopes.get(p.id)?.includes(r.record_id)??true;c.value=r.record_id;
  c.setAttribute('aria-label','分析 '+(r.paper_id||r.anchor||'B原话'));c.onchange=rememberScope;l.append(c);
  const body=node('div');body.append(node('strong',r.paper_id||r.anchor||'B原话'),node('pre',r.sections.map(s=>s.text).join('\n')));
  l.append(body);$('scope').append(l);
 }
 notice('');await runs();drawJobs();
}
const selectedRecords=()=>Array.from($('scope').querySelectorAll('input:checked')).map(e=>e.value);
function rememberScope(){scopes.set(current.id,selectedRecords());}
const candidateLabels={complete:'待核对，尚未保存',partial:'部分完成 · 待核对，尚未保存',failed:'分析失败',accepted:'已接收',
 stale:'候选已失效',zero_candidates:'无可接收候选',interrupted:'运行已中断',running:'正在分析',unavailable:'运行记录不可读'};
async function runs(){
 const p=current,h=await api('runs',{id:p.id});if(current?.id!==p.id)return;
 $('runs').replaceChildren();
 for(const run of h.runs){
  const box=node('div');box.className='job';box.id='candidate-'+run.run;
  candidateActions(box,p.id,run);$('runs').append(box);
 }
}
function candidateActions(box,id,info){
 const status=candidateLabels[info.state]||candidateLabels.unavailable;
 box.append(node('p',status+(info.accepted_revision!=null?' · 保存修订 '+info.accepted_revision:'')));
 if(!info.preview)return;
 const a=node('a',['complete','partial'].includes(info.state)?'核对待保存结果':'查看运行记录');
 a.href='/preview?'+new URLSearchParams({id,run:info.run});box.append(a);
 if(['complete','partial'].includes(info.state))button(box,'显式接收此候选',async e=>{
  e.currentTarget.disabled=true;
  try{
   const p=await api('accept',{id,run:info.run});
   if(current?.id===id)await display(p);
   await refreshJobs();notice('候选已保存到对应的分析包。');
  }catch(e){
   notice(errors[e.message]||'候选未保存（'+e.message+'）。',true);
   if(current?.id===id)await runs();
  }
 });
}
function drawJobs(){
 $('jobs').replaceChildren();
 const active=jobs.filter(j=>j.project===current?.id);
 $('jobs-title').hidden=!active.length;
 for(const j of active){
  const box=node('div');box.className='job';
  if(j.status==='running')box.append(node('p',j.phase));
  else candidateActions(box,j.project,j.candidate?.preview?j.candidate:{state:j.status});
  box.append(node('p','固定修订 '+j.revision+' · 已处理记录 '+(j.completed_records||0)+' · 请求 '+(j.requests||0)));
  if(j.error)box.append(node('p',errors[j.error]||j.error));
  $('jobs').append(box);
 }
}
async function refreshJobs(onlyRunning=false){
 const targets=jobs.filter(j=>!onlyRunning||j.status==='running');
 if(!targets.length)return;
 const results=await Promise.allSettled(targets.map(j=>api('job',{job:j.id})));
 results.forEach(result=>{
  if(result.status==='fulfilled'){
   const job=result.value,i=jobs.findIndex(j=>j.id===job.id);
   if(i!==-1)jobs[i]=job;
  }
 });
 drawJobs();
}
action('show-current',async()=>{if(current)await display(await api('state',{id:current.id}));});
action('show-home',async()=>{show('home');await home();});action('show-input',async()=>{show('input');renderDraft();});action('new',async()=>{show('input');if(!draft.records.length)draft.records.push({anchor:'B1',text:'',locator:'网页录入',scores:[]});renderDraft();});action('add-b',async()=>{draft.records.push({anchor:'B'+(draft.records.length+1),text:'',locator:'网页录入',scores:[]});renderDraft();});
action('add-part',async()=>{draft.parts.push({id:'part-'+crypto.randomUUID(),label:''});renderDraft();});action('add-a',async()=>{draft.items.push({id:'item-'+crypto.randomUUID(),text:'',locator:'',part_id:draft.parts[0]?.id});renderDraft();});
action('save-draft',async()=>{await api('draft',inputPayload());notice('输入草稿已保存在本机。尚未建立分析。');});action('create',async()=>{await api('draft',inputPayload());await display(await api('create',inputPayload()));});action('open',()=>load($('open-path').value));
action('sample',async()=>{await display(await api('sample'));notice('已打开人工编写的纯合成示例。示例非模型结果、非专业金标，可直接读图并练习纠正保存。');});
action('save-key',async()=>{try{await api('credential',{key:$('api-key').value});configurationStatus({configured:true,source:'personal'});notice('密钥已保存到本机凭据层。');}finally{$('api-key').value='';}});
action('generate',async()=>{const records=selectedRecords();if(!records.length){notice('请至少选择一条B原话。',true);return;}const job=await api('generate',{id:current.id,records});jobs.push(job);drawJobs();notice('');});
for(const [id,checked] of [['all-records',true],['no-records',false]])action(id,async()=>{
 $('scope').querySelectorAll('input').forEach(c=>c.checked=checked);rememberScope();
});
action('load-runs',runs);
$('candidate-history').ontoggle=()=>{if($('candidate-history').open&&current)runs().catch(e=>notice(errors[e.message]||e.message,true));};
action('refresh',async()=>{await display(await api('state',{id:current.id}));await refreshJobs();});
action('recover',async()=>{await display(await api('recover',{id:current.id}));notice('已按当前保存修订恢复结果文件。');});
action('import-a',async()=>{
 const next=structuredClone(reference());
 if(!next.version.trim()||!next.items.length){notice('请在“录入材料”填写新的A版本和至少一个条目。',true);return;}
 aChange={id:current.id,analysis_id:current.state.analysis_id,a_reference:next};
 $('a-target').textContent='目标分析 · '+current.path;
 $('a-change').textContent='A参照 '+(current.state.a_reference.items.length?current.state.a_reference.version:'未导入')+' → '+next.version;
 $('a-confirm-items').replaceChildren(...next.items.map(item=>node('li',item.text)));
 $('a-confirmation').hidden=false;$('confirm-a').focus();
});
action('cancel-a',async()=>{cancelA();$('import-a').focus();});
action('confirm-a',async()=>{
 if(!aChange||aChange.id!==current.id)return;
 await display(await api('import-a',aChange));await refreshJobs();notice('已更换当前分析的A参照。');
});
async function browse(path){const b=await api('browse',{path});browsePath=b.path;$('browse-path').textContent=b.path;$('browser').hidden=false;$('directories').replaceChildren();for(const p of b.directories)button($('directories'),p,()=>browse(p).catch(e=>notice(e.message,true)));$('parent').onclick=()=>browse(b.parent);}
action('browse',()=>browse($('open-path').value));action('choose-path',async()=>{$('open-path').value=browsePath;$('browser').hidden=true;});
action('source-load',async()=>{
 const h=await api('source',{path:$('source-path').value});$('source-sections').replaceChildren();
 for(const s of h.sections){
  const option=node('div');option.className='source-option';option.append(node('p',s.label||s.section_id),node('pre',s.text));
  button(option,'加入 '+(s.label||s.section_id),()=>{
   draft.records.push({kind:'workspace',workspace:h.path,section_id:s.section_id,text:s.text,label:s.label,source_selection:s.source_selection});
   renderDraft();notice('已加入普通来源分区。');
  });
  $('source-sections').append(option);
 }
});
action('stop',async()=>{await api('draft',inputPayload());await api('stop');notice('工作台已关闭。已保存分析与输入草稿保留，可关闭此页。');document.querySelectorAll('button').forEach(b=>b.disabled=true);});
setInterval(()=>refreshJobs(true),1200);
const query=new URLSearchParams(location.search);
home(true).then(async()=>{
 const id=query.get('project')||sessionStorage.getItem('active-analysis');
 if(!id)return;
 try{
  await display(await api('state',{id}));
  if(query.has('run')){
   $('candidate-history').open=true;
   document.getElementById('candidate-'+query.get('run'))?.scrollIntoView({block:'nearest'});
  }
 }catch(e){sessionStorage.removeItem('active-analysis');notice(errors[e.message]||e.message,true);}
}).catch(e=>notice('无法读取工作台：'+e.message,true));
