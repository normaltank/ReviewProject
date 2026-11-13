# 关注分析 Interface · attention/1

本页记录T1实际实现，适用本地可信编辑目录；权限沿用[数据契约](DATA_AND_ANNOTATION.md)。来源、分析包、HTML和草稿均继承原材料权限，不提供作者导出或认证。真实材料不进测试、仓库或模型请求。

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

备份须在关闭本机操作后复制整个分析目录，包含SQLite；仅HTML不能恢复。复制到新目录后可recover，绑定仍指向原输入位置；来源不可读时保留快照并标待核，不静默改路径。当前没有刷新/换源命令。

## 输入 attention-input/1

可运行的纯合成例见 [fixture](../tests/fixtures/synthetic_attention_input.json)。顶层 `records` 是所选来源，`a_reference` 包含 `version` 和 `items`，每项有独立 `id`、完整 `text` 和 `locator`。不需要framework、旧issue、强度或权重。T1只冻结并显示A，完整A18迁入及对应编辑属于T3。

来源有两个Adapter：

- `kind=transcription`（缺省值）：显式 `visibility=author_visible`、`anchor`、逐字 `text`、`scores`，可给 `locator` 说明转录与原件映射。原分项为字符串 `label/raw_value`，不规范化；定位是转录锚点，不能冒称Word坐标。CLI绑定输入文件的真实字节指纹，包内另存规范输入指纹；程序化build以传入结构作为显式冻结输入。
- `kind=workspace`：`workspace` 为相对清单或绝对本地目录，`section_id` 选择普通分区。通过既有只读来源校验Interface读取，不调用会写源application_id的构造器。只复制所选普通分区、定位和记录层原分；不复制原表、私密区或旧候选。`internal_only`、不存在分区及不支持来源拒收。同一来源选多个普通分区合并为一个record，其 `sections` 保存各区坐标。

`record_id` 与 `source_id`、输入绑定指纹分别保存；不含分析run、列表序号或整体分析JSON指纹。同一冻结来源及所选内容重排不改ID，同源多分区共享record；转录锚点是来源身份的一部分，不可随意重命名。这里没有跨不同原件自动去重或显式换源映射；这类操作需后续保留身份的Adapter，不能以语义相似推断同记录。R别名不是观点/方面ID。

文件字节变化（包括A和选择）、源Workspace修订/原件变化或来源不可读使 `material_status=needs_revalidation`；旧原话、原分、A及分析保留，新的编辑拒收。静态已打开页不实时轮询；recover/open/apply重新检查绑定。输入选择变化不自动转绑旧观点。

## 当前状态与补丁

`schema=attention/1`，独立随机 `analysis_id`、单调 `revision`、`input_fingerprint`、`rules_version`；records保存稳定ID、来源种类、指纹、锚点、原话/原分和sections；A参照原样冻结。初始 `opinions=[]`，不会把整记录或旧candidate当作已理解观点。

`attention-patch/1` 必须带 `analysis_id/base_revision/actor/reason/edits`。每项编辑含 `opinion_id/facet_id/record_id/evidence/interpretation/status`。新增观点和方面使用新ID；编辑必须沿用原record/facet身份。证据是非空列表，每项严格包含 `source_id/section_id/start/end/quote`；偏移是未经规范化的Unicode码点左闭右开区间，逐字校验quote，重复句必须选定实际位置。浏览器把UTF-16选区转为码点，不要求普通用户填写ID/JSON/偏移。

`status` 为 `working/needs_review/confirmed/withdrawn`，确认只指分析核对。每项观点T1有一个最小方面身份，持久保留 `replaces`、`themes`、`a_links`、`outside`、`expression(function/boilerplate_candidate)` 及 `qualifiers(object/direction/degree/negation/reasons/conditions/actions)`。这些附加字段在T1由系统初始化，不接受补丁假装完成后续功能。全包预留 `themes/relations`，后续主题/关系/多方面编辑由T2扩展，拆合时必须新建身份、保留沿革并使关联待核，禁止按首项自动继承。

历史逐修订保存完整补丁、指纹、时间、修改者和理由；`state()` 返回当前保存视图及历史。输入/补丁使用既有10MB有界JSON读取，保存视图同样有界。备份恢复、失效/错误和草稿状态均不声称完成T2—T6的真实批次/分布/图形验收。
