# 关注分析 Interface · attention/1

本页记录T1保存闭环与T2对象/迁入扩展，适用本地可信编辑目录；权限沿用[数据契约](DATA_AND_ANNOTATION.md)。来源、分析包、HTML和草稿均继承原材料权限，不提供作者导出或认证。真实材料不进测试、仓库或模型请求。

## 入口与恢复

```powershell
python -m reviewproto attention-build tests/fixtures/synthetic_attention_input.json --workspace work/attention-demo
python -m reviewproto attention-apply PATH_TO_DOWNLOADED_DRAFT --workspace work/attention-demo
python -m reviewproto attention-recover --workspace work/attention-demo
python -m reviewproto desktop
```

打开 `work/attention-demo/attention.html`，选择原话片段（或在原话中选文字后采用），填写解释、修改者和理由，加入草稿并下载。在本机窗口的“B关注分析”区应用关注草稿补丁、恢复并重开关注页。窗口有独立的建立/打开/应用/恢复入口；旧工作区及batch上下文不被复用。

`AttentionWorkspace(path)` 提供 `build(payload, base=...)` 或 `build(input_path=...)`、`state()`、`apply(patch)` 或 `apply(input_path=...)`、`recover()`、`close()`。新包目录必须为空；已有包从独立 `attention.sqlite3` 打开，旧 `review.sqlite3` 不迁移。SQLite是修订与历史的权威，JSON/HTML是可重建投影。CLI只输出安全状态码、修订及绑定状态，不输出原话/原分。

下载只表示未应用草稿。`apply` 在一个SQLite事务中校验全部编辑，任一错误整批回滚；同一规范JSON指纹重放不增加修订。修改者是自报审计声明。`base_revision` 必须等于当前修订，同分析包身份绑定，旧修订返回 `E_ATTENTION_CONFLICT`。提交后输出失败返回 `E_ATTENTION_OUTPUT_RECOVER`；提交可能已经成功，运行recover并重开核对，不另造补丁重复修改。完全相同补丁可安全重放。

备份须在关闭本机操作后复制整个分析目录，包含SQLite；仅HTML不能恢复。复制到新目录后可recover，绑定仍指向原输入位置；来源不可读时保留快照并标待核，不静默改路径。B来源没有刷新/换源命令；A参照可按下文显式版本事务导入。

## 输入 attention-input/1

可运行的纯合成例见 [fixture](../tests/fixtures/synthetic_attention_input.json)。顶层 `records` 是所选来源，`a_reference` 包含 `version` 和 `items`，每项有独立 `id`、完整 `text` 和 `locator`。不需要framework、旧issue、强度或权重。A按完整条目冻结；T3的分组、版本接续和方面对应编辑见下文。

来源有两个Adapter：

- `kind=transcription`（缺省值）：显式 `visibility=author_visible` 或 `visibility_unknown`（原值保留，不升级权限）、`anchor`、逐字 `text`、`scores`，可给 `locator` 说明转录与原件映射。`internal_only`、缺失或非法visibility拒收；`visibility_unknown`表示普通意见的作者可见性未确认，不提供公开或外发授权。原分项为字符串 `label/raw_value`，不规范化；定位是转录锚点，不能冒称Word坐标。CLI绑定输入文件的真实字节指纹，包内另存规范输入指纹；程序化build以传入结构作为显式冻结输入。
- `kind=workspace`：`workspace` 为相对清单或绝对本地目录，`section_id` 选择普通分区。通过既有只读来源校验Interface读取，不调用会写源application_id的构造器。只复制所选普通分区、定位和记录层原分；不复制原表、私密区或旧候选。`internal_only`、不存在分区及不支持来源拒收。同一来源选多个普通分区合并为一个record，其 `sections` 保存各区坐标。

`record_id` 与 `source_id`、输入绑定指纹分别保存；不含分析run、列表序号或整体分析JSON指纹。同一冻结来源及所选内容重排不改ID，同源多分区共享record；转录锚点是来源身份的一部分，不可随意重命名。Workspace的source_id绑定原件字节；新建独立包若原件字节改变会采用新来源版本身份。转录source_id绑定单条规范内容（含锚点、原话、原分、定位、visibility）；仅改变清单JSON格式/A参照/记录顺序不改变record_id。已有包始终保留旧record_id并待核；改变转录锚点或源版本时不得把重算ID当作保留旧身份的迁移。这里没有跨不同原件自动去重或显式换源映射；这类操作需后续保留身份的Adapter，不能以语义相似推断同记录。R别名不是观点/方面ID。

文件字节变化（包括A和选择）、源Workspace修订/原件变化或来源不可读使 `material_status=needs_revalidation`；旧原话、原分、A及分析保留，新的编辑拒收。静态已打开页不实时轮询；recover/open/apply重新检查绑定。输入选择变化不自动转绑旧观点。

## 当前状态与补丁

`schema=attention/1`，独立随机 `analysis_id`、单调 `revision`、`input_fingerprint`、`rules_version`；records保存稳定ID、来源种类、指纹、锚点、原话/原分和sections；A参照原样冻结。初始 `opinions=[]`，不会把整记录或旧candidate当作已理解观点。

`attention-patch/1` 必须带 `analysis_id/base_revision/actor/reason/edits`。每项编辑含 `opinion_id/facet_id/record_id/evidence/interpretation/status`。新增观点和方面使用新ID；编辑必须沿用原record/facet身份。证据是非空列表，每项严格包含 `source_id/section_id/start/end/quote`；偏移是未经规范化的Unicode码点左闭右开区间，逐字校验quote，重复句必须选定实际位置。浏览器把UTF-16选区转为码点，不要求普通用户填写ID/JSON/偏移。

`status` 为 `working/needs_review/confirmed/withdrawn`，确认只指分析核对。每项观点T1有一个最小方面身份，持久保留 `replaces`、`themes`、`a_links`、`outside`、`expression(function/boilerplate_candidate)` 及 `qualifiers(object/direction/degree/negation/reasons/conditions/actions)`。这些附加字段在T1由系统初始化；T2新增实际编辑方式见下文。全包预留 `themes/relations`，主题/关系/多方面编辑按下文T2扩展，拆合时必须新建身份、保留沿革并使关联待核，禁止按首项自动继承。

历史逐修订保存完整补丁、指纹、时间、修改者和理由；`state()` 返回当前保存视图及历史。输入/补丁使用既有10MB有界JSON读取，保存视图同样有界。备份恢复、失效/错误和草稿状态均不声称完成T2—T6的真实批次/分布/图形验收。

## T2 多方面、主题及关系（attention-objects/2）

保存包继续使用schema=attention/1，state()明确给出model_version=attention-objects/2。旧T1包读取时升级为单方面表示，保留原opinion_id/facet_id；下一次应用保存升级结果。SQLite历史及旧补丁不改写。每个观点的facets是方面的权威列表；仅在恰好一个方面时提供T1顶层facet_id/themes/a_links/outside/expression/qualifiers兼容投影。多方面不提供首方面投影，顶层evidence是各方面证据的串接，不能当作单方面范围。

- 观点：opinion_id/record_id/interpretation/status/facets/replaces/superseded_by。方面可补录并重排；已有方面不能换到另一观点。撤回用状态保留，不删身份。拆合新建观点和方面，replaces指明同记录旧观点；旧观点及其方面变为superseded，superseded_by记录后继。
- 方面：facet_id/kind/interpretation/evidence/status/themes/a_links/outside/expression/qualifiers/legacy_aliases。kind为content（默认）或disposition（流程/总体处置，不混入内容主题排名）。status为working/needs_review/confirmed/withdrawn，另有系统生成的superseded。
- 限定：qualifiers.object/direction/degree/negation/reasons/conditions/actions/examples/alternatives，值为文字或文字列表；不自动抽取、补全或裁判。expression.function是本次作用，boilerplate_candidate独立取true/false/null；候选不意味着删除。
- 主题：theme_id/label/definition/parent_ids/status，可带legacy_aliases；系统提供version（初始缺省1）。改名不换ID；定义或父组变化增加版本并置待核。父组必须存在且无环。方面的themes是成员引用列表，每项严格为theme_id/reason/evidence/status，证据来自该方面所属记录。
- 关系：relation_id/type/endpoints/direction/scope/evidence/reading/ambiguity/status，可带legacy_aliases。端点严格为{facet_id,role}；同一方面可承担不同角色。方向可明确说明无方向/未决，scope说明实际范围，不从成员顺序推理。证据逐项校验且来源属于端点记录。单端点可表示方面内部清单/时点范围。
- A引用预留：方面a_links列表拟由T3使用{a_item_id,version,kind,scope,reason,evidence,status}，kind区分对应/部分/相关/暂未定；outside拟使用{scope,reason,evidence,status}。T3已通过统一事务校验和普通控件支持创建、修改及移除。

attention-patch/2使用同一analysis_id/base_revision/actor/reason，可带edits/themes/relations三个列表，至少一个非空。edits每项是观点完整当前opinion_id/record_id/interpretation/status/facets，可带replaces/legacy_aliases；themes/relations按稳定ID新增或更新。未提交对象保持原样；禁止未知编辑字段。错误端点/来源/证据/循环父组整批拒收。系统字段superseded_by与主题version不通过补丁填写。

拆合不把旧主题、关系或A引用移给新方面；保留旧端点并待核，明确撤回的关联保持撤回。新方面以空关联开始，由用户逐项添加依据。修改已有方面的解释/证据/限定/类型也会使受影响关联待核。后续汇总默认排除superseded/withdrawn观点和方面；待核旧关联供历史回查，不能当作新方面的明确覆盖。

旧attention-patch/1仍可创建单方面观点，或凭明确opinion_id+facet_id更新复合观点中的对应方面。不存在/歧义身份安全拒收，不默认改首项或丢弃其他方面。简单表单仍可下载T1格式；涉及多方面、限定、主题、关系或拆合时下载T2格式。事务、幂等、冲突、recover闭环不变。

普通表单清空已有限定或表达作用、将套话候选复位为未判断、将处置方面复位为内容，也属于富字段实际变化，必须通过T2完整补丁保存；不能因新值为空而退回省略这些字段的T1格式。未修改的其他方面及关联保留，受影响的关联按既有规则待核。

### 合成形状与下游交接

以下使用说明用身份和EV占位（EV实际替换为有效五字段证据）；普通控件自动选择/生成身份，无需用户输入JSON、ID或偏移。

    {
      "schema": "attention-patch/2",
      "analysis_id": "当前分析包身份", "base_revision": 1,
      "actor": "合成编辑", "reason": "保留条件范围",
      "edits": [{
        "opinion_id": "O", "record_id": "R",
        "interpretation": "条件备用动作", "status": "working",
        "facets": [{
          "facet_id": "F", "kind": "content",
          "interpretation": "不能补证时可降低结论",
          "evidence": ["EV"], "status": "working",
          "qualifiers": {"conditions": "若不能补证", "actions": "可降低结论"},
          "expression": {"function": "备用建议", "boilerplate_candidate": false},
          "themes": [{"theme_id": "T", "reason": "涉及结论尺度", "evidence": ["EV"], "status": "working"}],
          "a_links": [], "outside": []
        }]
      }],
      "themes": [{"theme_id": "T", "label": "结论尺度", "definition": "表达与证据的承载范围", "parent_ids": [], "status": "working"}],
      "relations": [{
        "relation_id": "REL", "type": "conditional_fallback",
        "endpoints": [{"facet_id": "F", "role": "条件下的备用动作"}],
        "direction": "条件约束动作", "scope": "只约束降低结论",
        "evidence": ["EV"], "reading": "不补反向保证",
        "ambiguity": "不推排他选择", "status": "working"
      }]
    }

T3接线位置是AttentionWorkspace.apply统一事务及attention_model.apply_objects方面校验。新增A参照版本须明确独立事务，保存新文件绑定与旧参照历史，并保留B记录/方面身份；禁止修改旧输入文件或重建包来偷偷换源。A导入命令及版本事务见下文。T4消费state.records/opinions[].facets/themes/relations与显式状态，不用T1顶层投影、旧coverage或方面数作记录分布。空A参照明确显示尚未导入，不声称A18已冻结。

### 显式工作稿迁入

    python -m reviewproto attention-migrate WORKING_DRAFT_JSON --workspace NEW_EMPTY_DIRECTORY --actor 编辑声明 --reason 迁入理由

桌面“迁入B关注工作稿”可选择原稿、新包父目录及审计声明；Controller提供migrate_attention(source,destination,actor,reason)，Workspace提供migrate_working_draft(input_path,actor=...,reason=...)。仅接受working-attention-index-v1显式Adapter：校验各原话SHA及各方面/关系原始start/end/quote，不使用首个find定位，不采用旧coverage/denominator或confirmed身份。原稿作为只读文件绑定，改变/不可读触发待核。所有对象在建包事务提交前校验，坏稿不留下部分分析状态。

旧记录ID作为转录anchor及旧别名保留；已给材料分组保存在record.locator.paper_id，T4可按这个显式字段筛选材料组，不从R编号/教师/文件名猜组。它表示给定论文材料组关系，不确认精确送审版、轮次或教师身份。普通评审可见性记visibility_unknown；记录expression_function只进入expression_note，不复制为各方面套话判断。每个旧方面先迁为一个工作观点/方面，再以有理由补丁调整。旧主题有持久随机ID；旧关系先保留范围/证据/工作读法，角色/方向明确待核，后续逐条纠正。新包legacy_aliases列出{kind,alias,id,disposition}，kind为record/facet/theme/relation；方面及主题另保留legacy_aliases。旧关系无ID时用旧record别名加:relation:原序号说明首次迁入位置；迁入后按持久relation_id编辑，不用序号重算身份。

迁入不接纳旧A对应、旧计数、教师/稿件身份猜测或私密原表，A参照初始为空并明确未导入。真实迁入及解释核对只留本地受控work目录；公开回归全用合成材料。迁入成功、语义核对、独立审查、集成与用户本人体验分别报告。

## T3 A版本接续与逐方面对应

在现有包导入A参照，无需重建包或修改旧B输入：

```powershell
python -m reviewproto attention-import-a A_INPUT_JSON --workspace EXISTING_ANALYSIS --actor 编辑声明 --reason 接续理由
```

桌面先打开分析包，再点“导入A参照版本”。Controller提供`import_attention_a(source,actor,reason)`，Workspace提供`import_a(input_path,actor=...,reason=...)`，与普通补丁共用`apply`事务、修订、历史及recover。`attention-a-input/1`包含`a_reference`和可选`source:{path,fingerprint}`；source路径相对清单或为绝对本地路径，fingerprint为原文件字节SHA-256。清单本身始终绑定字节指纹；可选source同时绑定原文，两者变化或不可读都保留旧快照并待核。

`a_reference`为`{version,parts:[{id,label}],items:[{id,text,locator,part_id}]}`；旧无分组参照可省parts/part_id，显示未分组，不猜新分组。完整条目包括原文限定、条件、例子和原字样，不按子句扩写新要求。所有ID唯一、part_id指向已知部分。同version下任何条目、文字、定位或分组变化均拒收；显式换版本保存旧参照与旧A绑定到`a_reference_history`，其中`replaced_at_revision`指向接续修订。原B身份及全部旧历史保持不变。内容完全相同的同版本可显式重绑到新文件，保留审计及旧绑定。

A来源失效时`a_material_status=needs_revalidation`，旧A关联和清单外范围均显示待核；B绑定另以`b_material_status`报告。总`material_status`仍表达任一失效并拒收普通编辑。旧A失效允许显式A事务接续；B绑定失效继续阻止A导入。新参照使旧清单外范围待核，不自动转绑旧关联：它们保留原version并待核，撤回状态保持撤回。旧版本引用仅能作为待核/撤回的原关联保留；不能新造旧版或未知条目引用。换版没有自动确认任何B专业判断。

方面`a_links`严格使用`{a_item_id,version,kind,scope,reason,evidence,status}`；kind为explicit/partial/related/undetermined。前三类必须指向当前参照的已知条目；暂未定可指具体条目或null。`outside`严格使用`{scope,reason,evidence,status}`。范围与理由必填，证据使用所属记录的五字段逐字区间，状态为working/needs_review/confirmed/withdrawn。同方面可同时保存多个不同关系及清单外、未定范围。新关联不能仅凭版本字符串接受已变化的含义。

普通表单先选择观点方面及原话片段，在“A对应与清单外内容”选择种类、A条目、范围、理由和状态，点“关联加入草稿”；已有项可纠正或移除。下载后在本机应用并重开才保存。移除最后一条仍生成完整attention-patch/2，保留同观点其他方面及B关联。A完整条目、部分、定位、当前版本及旧版本快照可查；未出现项显示尚无当前采用的对应，不表示B不关注。明确、部分、相关和未定分别显示，不据通用认可点亮全部A。

真实本地A18及111方面工作解释接续保存在受控work目录；不是公开测试材料，也不表示已通过独立语义审查、集成或用户体验。公开合成回归覆盖跨部分、同句在外与对应、数据年代、背景来源偏好、措辞与来源疑虑、通用认可六类结构；浏览器验证宽窄布局、键盘下载、Controller应用及重开，并验证清空最后关联实际持久化。
