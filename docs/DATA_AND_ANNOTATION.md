# 数据与标注契约 · 0.4.3

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

本地抽取 CLI 默认 `--protocol v3`，共享公开配置及 Flash 入口保持该默认。`--protocol v4` 是显式试验选项：新增 `branch_relation=none / unknown / either_or / conditional_branches`。none/unknown 不升级成分组；纯 either_or 只接收两个不同、位于同一观点引用内的逐字动作、空 branch_conditions，以及两动作间的显式“或/或者/要么”连接。存储时两支 condition 均为 unknown；不得补造“无法实验”等选择条件。有明确条件时仍逐项引用条件与动作。缺字段的旧 grounding 按 v3 回放，不据关键词猜 either_or。

v4 的连接词检查仅为必要表面约束，不能确认两段真是可选动作；对象列举、引述或相容建议仍可能被模型误报，保留 `branch_relation_semantics_requires_review`。有分支提名时整组 action/requirement_strength 保留 unknown，不能用单一路径的模态覆盖全组。运行配置记录实际选定协议、指令/schema 指纹及输出 token 上限；协议选择不改变模型权重、候选概念或正式条款。

可选分步入口 `extract_staged.py` 仅接受既有工作区、显式普通分区和新运行ID。第一步的逐字 span/kind、原文字面cue及其上下文队列都是旁车，语义状态固定未知，绝不充作已理解观点。第二步仅接收同一区域的连续原文和公开合成例子，不接收第一步kind或语义结论、评分、身份字段、私密区或A条款；实际候选复用v4逐字转换及待核状态。该入口同时改变了上下文安排和调用次数，不是纯关系分类器或分阶段方法的单变量消融。

同区重叠cue上下文先按坐标闭包合并，相交召回继承完整范围。第一阶段窗口固定600码点；第二阶段用 `--context-chars 600|1000` 指定完整上下文上限，默认600。超过所选上限保留 `boundary_pending`，不得用碎片绕过。原span、ID、来源和原句仍可回看；纯召回不按主题互相合并。cue字面表是有限提示，不保证发现所有语言条件或理解其含义。默认总请求12、局部复核4，队列排序不因扩容改变；新可处理的早期上下文可能挤出后续预算，未处理项保留原因，不能算已完成业务复核。config和coverage分别记录实际window_chars/context_chars，旧未记录context_chars的历史产物按当时window_chars=600解释，不改写旧文件。

每请求前重验源文件、所选文本及权限，采用相同本地端点/禁代理/禁重定向约束，先落盘attempted再发送。中断时 pending 只证明客户端已记尝试，不证明服务已接收或完成。`recall.json / queue.json / grounding.json / coverage.json / response-*.json` 的实际指纹放入config；队列processed只表示送模型处理，绝不是语义正确。coverage可为partial，同时零候选伴错误的候选payload为failed且退出2；合法无错空为complete并导入zero_candidates，有错非空由核心派生partial。旁车进展不会将失败升级为充分支持。旧默认入口、概念审批及正式规则权限不变。

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

## 有原文证据的候选规则包

`ingest-framework BOOK` 在现有单份 B 工作区中导入本地规则包。包顶层严格为 `schema_version=1 / framework_id / version / title / coverage_notes / sources / rules`。来源文件相对路径仅允许 `sources/<文件名>`；拒绝绝对路径、目录穿越、链接、重复 JSON 字段、超限来源与 ZIP 解压膨胀。当前复用 `python-docx` 已有的 lxml 和标准库 ZIP/JSON/SQLite，不新增文档服务或外部请求。

- `sources` 每项为 `source_id/kind/file/sha256/verification`。`pptx_native` 固定 `native_text`，`transcript_json` 固定 `machine_unchecked`。导入检查真实文件 SHA，数据库保存来源 bytes，`frameworks/<内容指纹>/sources/` 再保存冻结副本。原始包的美化 JSON 文件 SHA 可不同于 canonical 内容指纹；后者由 `framework_digest()` 计算并绑定对照。
- `rules` 每项为 `rule_id/dimension_id/title/requirement/rule_type/strength/strength_provenance/applicable_when/exceptions/unknowns/checks/derivation/evidence`。类型区分 `evaluation_question / recommendation / requirement_candidate`；强度为 `unknown / recommended / mandatory / optional`，依据为 `explicit / inferred / unknown`。`derivation` 区分来源转述 `source_paraphrase` 和整理者操作化 `editorial_operationalization`。mandatory 可记录来源自身措辞，绝不等于出版社正式效力。
- 每处证据为 `source_id/locator/start/end/quote`，逐字校验 Unicode 切片。PPT `locator={page,paragraph}` 使用 `ppt/slides/slideN.xml` 的页号与零基 `a:p` 段号；段内文字拼接 `a:t`，`a:br` 为换行，不验证图像或备注。转写 `locator={pointer}` 可加 `segment_id/time_range/ppt_page`，均与实际 JSON 记录核验。语音识别错误仍须回听，字节或切片通过不能消除它。
- 导入统一强制 `status=candidate / authority=unconfirmed / source_status=pending / formal_version=unknown`。同 framework_id、version、内容重复幂等；同版本不同内容拒绝，新内容必须另起版本。`recover` 只能补回缺失的冻结文件，不能静默覆盖被改动的规则或来源。

book 与 framework-review payload 的输入 bytes 和 canonical 编码各受 10,000,000 bytes 上限约束；文件入口与内存入口同样执行 canonical 预检。紧凑输入变为带缩进的规范 JSON 后可能增大，须在冻结文件或修改业务状态前拒收，保证后续读取、恢复与重放不会因自身输出超限锁死工作区。失败仍可留下运行错误记录，不添加规则、来源或对照。

旧 `ingest-clauses` 仍兼容旧记录，其声明型来源校验不等于新包的真实来源文件校验；两者不会自动转换或冒称同一正式版本。

## B 对照与修订讨论草案

`framework-template` 可指定一个 `--candidate` 和 `--rule`，产生一条 `pending_comparison/unknown` 草稿，不生成全体观点与条款的笛卡尔积。`apply-framework-review` 的 payload 严格包含 `schema_version/source_id/base_revision/actor/reason/framework_sha256/alignments/proposals`，至少一条对照或提案；需填写真实声明，不能直接应用空模板。

每条 `alignments` 为 `candidate_id/rule_id/relation/provenance/evidence_indices/rationale`；relation 为 `covered / partial / condition_difference / potential_conflict / uncovered / pending_comparison`。uncovered 仅说当前候选包未覆盖，不能推出完整 A 标准没有此项，更不能凭主题相同确认覆盖或冲突。

每条 `proposals` 为 `proposal_id/rule_id/kind/after/rationale/support_candidate_ids/counter_candidate_ids/validation_plan/rollback_condition/unknowns`。`kind` 区分 `source_interpretation`（解释或操作化）和 `publisher_requirement_change`（业务要求变更建议）。`after` 只能修改 `requirement/applicable_when/exceptions/strength/strength_provenance/checks`，至少有一处真实变化；完整 before 由系统从绑定规则冻结，调用者不能伪造。输出 after 固定 `derivation=editorial_operationalization`，提案标 `after_provenance=editorial_proposal / evidence_scope=baseline_only`；原来源引文仅支持修改前规则，不能为草案新增文字冒认课程出处。支持与反例不能重复，合计至少一项，全部来自同一来源、同一分区和权限区。当前不支持跨稿合并提案证据；专业观点可以相反，不作同主题去重。

系统冻结所用观点、最新决定 ID 与候选视图指纹；提案统一 `draft / needs_professional_review / baseline_confirmation_required / authority=unconfirmed`。观点变更后整份工作区历史对照与提案保守标 `needs_revalidation`，即使改的是无关观点也先复核；新对照记录追加而不改旧证据，提案 ID 不重用。`current` 只说明观点快照未变。规则版本通过 SHA 显式绑定，导入新版本不会自动替换旧提案依据。概念调整、模型调参、课程解释和出版社要求变更分别留证，均无自动正式发布路径。

## 合成条件示例

演示表中有一句“若能取得逐周记录，可补一张对照表；否则请说明资料的覆盖范围。”这两路可以引用同一句中的不同片段。第一路以能取得记录为条件，动作是“可补一张对照表”。第二路以不能取得记录为条件，动作是“说明资料的覆盖范围”。它们在 `alternatives` 内属于同一组 `conditional_branches`，每支都写自己的 `evidence_indices`。这份合成输入也演示了较宽泛句式需要人工填写的情形。新的手工字段与机器候选分别保留。

## 保存与恢复

`review.sqlite3` 保存状态、运行记录、成功补丁和机器导入 payload。事务按 `base_revision` 检测冲突。重复补丁复用原决定；使用新文件名导出后续草稿。`imports/` 保存可重放导入，`model-artifacts/<run_id>/` 保存实际响应、定位结果与失败。直接编辑 `state.json` 或 HTML 会在重建时消失。

`state.json`、`report.html`、`runs/` 和 `patches/` 是本地可读产物，均继承组内权限。运行记录列出实际版本、状态、命令、参数、来源或输入指纹、输出哈希及调用数。命令行输出安全错误代号，原文仅在受控原件、复核材料及其备份中查看。可按 README 的 `recover` 命令重新生成展示文件。

## 可选外部试验与成本观察

`deepseek_trial.py` 仅处理明确授权计划中的一个普通意见分区，固定官方 `deepseek-flash`。计划绑定原始来源 ID、冻结分区 hash、待发文本 hash、等长遮蔽区间、模型、端点、总费用与调用上限；批准记录绑定整个计划 bytes hash。请求前重新检查来源和授权，禁止 internal_only、评分、身份字段、原稿、A 材料及额外工具。遮蔽范围外文本必须逐字不变，模型引文跨遮蔽区间拒收。普通区的 visibility_unknown 不等于可公开；本轮外发效力来自明确用户授权。

每计划一个 `deepseek-budget.sqlite3`，批准必须绑定规范绝对 `ledger_path` 及 `ledger_identity=SHA256(plan_sha256 + 换行 + ledger_path)`；复制/移动计划或批准仍须引用原账本，缺失绑定拒绝。identity 是一致性检查，批准记录依赖可信本地操作，不是签名认证。事务先预留按最高公布单价计算的保守费用。响应 token 用量、估算与实际账单分别记录；pending 或未知用量阻断后续请求，失败不自动重试。更换模型或扩大文本范围需重新绑定批准，不能因持有密钥而推定允许任意材料外发。密钥通过当前 Windows 用户 DPAPI 加密保存，调用时在本次进程树环境中传递，退出后恢复原环境。

复核计时导出独立 `review_cost_observation` JSON 旁车，不进入候选或 apply schema。记录 source_id、base_revision、会话 ID、修改人及自报角色、选定方法、UTC 起止、活动/暂停毫秒及操作尝试计数，不含原文或原分。显式开始后计时，暂停/隐藏停止活动时间；选择方法只作任务声明，不会过滤队列。自报身份不是认证，页面计时不证明持续注意、专业资质或修改已应用。真实人工数据为零时必须报告未测，不将合成浏览器或代理耗时改称节省人工。

## 进入 Framework 修订的条件

当前允许用待核课程包做探索性对照和草案，但必须显式保留现行基线待确认；课程解释不能冒充对正式 A 要求的已确认修改。进入正式决策前仍需确认 A 有效版本与适用范围，核验稿件事实、独立稿件与审稿人分母、作者和编辑负担，并完成独立试评及回退设计。出版社授权人员负责正式发布。从候选观点到制度变更之间的这些判断分别留证。
