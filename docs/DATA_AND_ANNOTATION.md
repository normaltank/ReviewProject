# 数据与标注契约 · 0.3.1

一份 DOCX、CSV 或契约 JSON 对应一个可信编辑工作目录。目录整体继承原件权限。打开 HTML 的人可以读取其中的私密意见，隐藏或折叠界面元素不提供身份隔离。权限控制依赖本地目录访问控制。复核、备份和恢复时按整份受控材料管理。`actor` 是审计声明，不是经过身份认证的账号。

## 从原件到评分和评语

| 记录 | 取值与判读方法 |
| --- | --- |
| 来源 | `source.docx`、`source.csv` 或 `source.json` 保存逐字节副本。SHA-256 同时用作来源 ID，`source.origin` 保存操作人声明的 `original_review`、`synthetic` 或 `unknown`。报告里的转述另属研究资料。 |
| 审稿关系 | 表上自报稿件 ID 保留原值和单元格位置。正式稿件配对、送审版本、教师匿名 ID、轮次、表单版本、独立完成状态分别保留未知。文件名、日期、姓名相似度均不足以完成配对。 |
| 评分 | 四个原标签与 `raw_value` 原样保存，含空格和小数。可解释的 1–5 范围数值另存十进制字符串。空白、明确不适用、无法解析和越界的值分别标记为 `unfilled`、`not_applicable`、`unparseable`、`out_of_range`，解析值为空，原字符串可回看。 |
| 分区 | 普通“评审意见”为 `visibility_unknown`，明确标注作者可见的表头可记 `author_visible`，明确的“作者不可见”区为 `internal_only`。覆盖范围限已核实的表内分区。正文出现混杂权限措辞时保守拒收，交编辑回原件判断。 |
| 声明范围 | 解析器核验表格形态、分项标签及意见区边界。Word 样式链及文档默认样式有隐藏/编号歧义、纵向合并、公式、移动修订或无法表示节点时拒收。共享评分格不作为空分处理。历史工作区再次打开也会用当前规则核验冻结原件，不安全的旧解析需人工重导入。表外内容、其他表型、论文事实及 A 的正式效力另外核实。 |

`source_id + section_id + [start,end) + quote` 唯一定位一段引用。偏移基于冻结分区中的 Unicode 码点，从 0 计数；同格相邻 Word 段落之间放一个换行，保留段内换行、空段和空格。映射指向 `word/document.xml` 的物理表、行、格和段落，横向合并的格子只数一次。校验条件是 `text[start:end] == quote`，遇到重复句按所选区间定位。浏览器显示由 Python 切出的原句，手工修改高级偏移时使用码点计数。

## 从候选到已复核观点

首次模型提取只接收单个意见区的文本窗口，不传评分字段、表单身份元数据、其他分区或 A 条款。原文中的录用建议、数字或身份仍是原文的一部分，不能据此承诺内容已脱敏。规则每个非空段落产生一个 `rule_candidate / pending_review`；模型追加 `model_candidate / pending_review`，保留运行 ID 和原始响应。二者都用于安排复核，不直接充当独立业务观点或统计分母。

- 原句可附多个不连续证据片段，全部来自同一来源、同一权限分区。`reasons`、`conditions` 与 `alternatives` 分别指向 `evidence_indices`；理由可跨句。`negation` 保留否定短语或 unknown。窄规则仅识别明确成对措辞；模型不保证保留条件，需查看完整上下文。
- 对象、属性、方向、话语功能、要求强度、严重性与动作分别填写。样本数量与样本代表性可分别标注。正面判断与修改建议可以并存。“建议”不能自动升级为强制或严重缺陷。
- `explicit` 表示审稿人明说，`inferred` 表示分析者推断，`unknown` 表示证据不足。连接评分时注明原分项和证据，缺乏理由时保留未知。`paper_verification=not_checked` 单独表示尚未核验论文。A 标准对齐为 `pending_comparison`。
- 编辑可确认、拒绝或保留待核。补丁只允许改观点字段。每个决定追加记录修改人、时间、理由、来源 ID、修订号和补丁指纹。历史机器候选与历次人工决定并存，最新人工决定用于当前展示。

拆分或补录使用补丁顶层 `creates`。每条包含 `candidate_id`、`section_id`、`fields`，可带 `parent_ids` 与 `replaces`。新 ID 使用 8–100 位 ASCII 字母、数字、下划线或连字符，工作区内唯一；新观点只能从 `needs_review` 或显式 `confirmed` 开始。被替换父项追加 `superseded` 决定，原记录不会删除。单条修正仍用 `edits`。确认、拒绝、待核、替换、废弃分别记录；只有当前 `confirmed` 的独立观点进入已确认视图。

模型重跑使用新的 `run_id`，通过 `ingest-candidates` 追加；旧观点 ID、人工修改及概念绑定不变。相同运行和内容重试幂等，同 ID 不同内容拒绝。抽取状态有 `complete / partial / failed / zero_candidates`；任何错误或候选拒收都会进入运行记录，接收成功不表示语义通过。严格校验冻结文本切片，禁止以模糊匹配掩盖改引号、空白或重复引文歧义。

## 结构化输入

`--format csv` 当前只支持已核的 6×6 业务表单：第 0 行是三组元数据，第 1 行标题，第 2–3 行四项评分，第 4–5 行普通/私密意见。它是 **一份审稿表，不是多条 CSV 记录**。位置保存为零基 `row/cell`；原分字符串、空格和意见区字节来源均保留。

通用导出可先转换为下列 JSON，`raw_value` 必须是字符串。`scores` 可为空；量表按当前 1–5 分契约解释，其他量表须另行适配，不借标签猜测。`metadata` 可选，仅用于保留来源声明；不参与身份配对或模型抽取。

```json
{
  "schema_version": 1,
  "scores": [{"label": "创新性与科学性（1-5分）", "raw_value": "4"}],
  "sections": [{"section_id": "comments", "label": "评审意见", "text": "合成示例：论点清楚。建议调整章节顺序。", "visibility": "visibility_unknown"}]
}
```

JSON 的证据位置除字符偏移外保留 JSON pointer。作者不可见标签必须 `internal_only`；只有明确的作者可见表头才允许 `author_visible`。混杂权限措辞继续拒收。

## 概念、分数与 A 来源

补丁顶层 `concepts` 的每条记录为 `concept_id/name/definition/positive_examples/negative_examples/boundary/status/sources`。状态为 `pending_confirmation / confirmed / deprecated`，修改追加 `concept_history`。同名异 ID 拒绝，观点通过 `concept_ids` 引用已存在概念。模型自由标签只是提名；定义、边界和反例需要单独整理，不按词频自动合并规模与代表性，也不将相反判断合并。概念确认不等于正式条款批准。

`relations` 中 `explains_score` 指向原始评分标签，并带 `explicit/inferred/unknown` 与证据下标。同主题只能支持候选关联，不能自动认定实际给分因果，更不能据高分和局部建议直接判矛盾。缺少交叉评分与稿件版本时不估计审稿人严宽、质量或跨稿结论。

`ingest-clauses` 输入为 `{"schema_version":1,"clauses":[...]}`，每条只有 `clause_id/text/source_kind/sources`。`source_kind` 区分 `direct_source_quote / machine_synthesis / machine_transcript`。来源需 `source_id/sha256` 及页码、时间戳或 locator；逐字引文还需 `quote` 与 `text` 相等。导入器验证声明结构，实际来源文件的字节与引文须由整理者核对；不得据此声称自动验真。所有条款强制 `candidate/pending_source_review/authority=unconfirmed/framework_version=unknown`。

观点的 `clause_links` 记录 `clause_id/relation/provenance/evidence_indices`；关系可为 covered、partial、condition_difference、potential_conflict 或 pending_comparison。目标仍是候选来源时不能据该关联发布正式要求。

## 合成条件示例

演示表中有一句“若能取得逐周记录，可补一张对照表；否则请说明资料的覆盖范围。”这两路可以引用同一句中的不同片段。第一路以能取得记录为条件，动作是“可补一张对照表”。第二路以不能取得记录为条件，动作是“说明资料的覆盖范围”。它们在 `alternatives` 内属于同一组 `conditional_branches`，每支都写自己的 `evidence_indices`。这份合成输入也演示了较宽泛句式需要人工填写的情形。新的手工字段与机器候选分别保留。

## 保存与恢复

`review.sqlite3` 保存状态、运行记录、成功补丁和机器导入 payload。事务按 `base_revision` 检测冲突。重复补丁复用原决定；使用新文件名导出后续草稿。`imports/` 保存可重放导入，`model-artifacts/<run_id>/` 保存实际响应、定位结果与失败。直接编辑 `state.json` 或 HTML 会在重建时消失。

`state.json`、`report.html`、`runs/` 和 `patches/` 是本地可读产物，均继承组内权限。运行记录列出实际版本、状态、命令、参数、来源或输入指纹、输出哈希及调用数。命令行输出安全错误代号，原文仅在受控原件、复核材料及其备份中查看。可按 README 的 `recover` 命令重新生成展示文件。

## 可选外部试验与成本观察

`deepseek_trial.py` 仅处理明确授权计划中的一个普通意见分区，固定官方 `deepseek-flash`。计划绑定原始来源 ID、冻结分区 hash、待发文本 hash、等长遮蔽区间、模型、端点、总费用与调用上限；批准记录绑定整个计划 bytes hash。请求前重新检查来源和授权，禁止 internal_only、评分、身份字段、原稿、A 材料及额外工具。遮蔽范围外文本必须逐字不变，模型引文跨遮蔽区间拒收。普通区的 visibility_unknown 不等于可公开；本轮外发效力来自明确用户授权。

每计划一个 `deepseek-budget.sqlite3`，事务先预留按最高公布单价计算的保守费用。响应 token 用量、估算与实际账单分别记录；pending 或未知用量阻断后续请求，失败不自动重试。更换模型或扩大文本范围需重新绑定批准，不能因持有密钥而推定允许任意材料外发。密钥通过当前 Windows 用户 DPAPI 加密保存，调用时只注入子进程环境。

复核计时导出独立 `review_cost_observation` JSON 旁车，不进入候选或 apply schema。记录 source_id、base_revision、会话 ID、修改人及自报角色、选定方法、UTC 起止、活动/暂停毫秒及操作尝试计数，不含原文或原分。显式开始后计时，暂停/隐藏停止活动时间；选择方法只作任务声明，不会过滤队列。自报身份不是认证，页面计时不证明持续注意、专业资质或修改已应用。真实人工数据为零时必须报告未测，不将合成浏览器或代理耗时改称节省人工。

## 进入 Framework 修订的条件

后续对齐应使用经确认的 A 条款版本、原句、来源页码或时间戳，并记录覆盖、部分覆盖、条件差异或待核。候选提案需要修改前后文字、支持与反例、独立稿件与审稿人分母、作者和编辑负担、独立试评及回退条件。出版社授权人员负责正式发布。从候选观点到制度变更之间的这些判断分别留证。
