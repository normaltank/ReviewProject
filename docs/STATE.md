# 交接状态 2026-11-13

<a id="当前目标与a参照"></a>
<a id="已确认的业务边界"></a>
## 当前目标

处理已有B评语、原分及按需论文语境，理解B关注、表达功能、联系差异、清单内外和分布，再与A已给关注方向对照；支持明细、可选可视化、原文回查和纠正保存。行为及验收以[当前规格](specs/b-attention-distribution.md)为准。

核对的是本项目转录、切分、归纳、关联和解释是否忠实，分析确认不表示认可B的专业结论。论文仅按需帮助理解对象与语境。A工作版本 `a-focus-20261112-01` 为5部分18项关注方向，不是强制评分标准；中文相关研究覆盖按当前清单外处理，不再问A。

## 本批材料及已有解释

本批包含4篇论文、14条普通评语记录、56项原分；身份、轮次及精确送审关系未全部确认，记录分析照常进行。原文入口和资料身份见[本地材料定位](LOCAL_MATERIALS.md#batch-inputs)。

已有两份外部意见均已吸收，不再进行新AI征询。[14记录工作稿与六个A样例](LOCAL_MATERIALS.md#working-analysis)是一版可纠正的解释；13主题、93方面和8关系不是固定终值，不代表A18全量对应或完整产品验收。[六案例和试行规则](specs/opinion-coding-rules.md)可继续使用，旧QA快照不自动成为待问清单。

<a id="已交付及证据"></a>
<a id="方法检查与规则校准"></a>
## 已有能力和未完成部分

积压工程快照包含原话/原分导入、观点补录/拆分/纠正、条件与替代保留、出处定位、受控补丁保存重开，以及可选候选抽取和本机证据查找。兼容接口见[数据契约](DATA_AND_ANNOTATION.md)，采用边界见[复用决策](REUSE_DECISIONS.md)。运行批次已由[PR #10](https://github.com/normaltank/ReviewProject/pull/10)交付到main，提交 `77a69f2fd9fc2845543efdd2fa7772f2de60ebef`；这不表示新B关注产品或各历史业务效果已完成。

当前旧batch仍要求framework规则包，页面围绕条款问题和决定。新B主题、方面、A18对应、记录分布、可选视图及同修订保存闭环仍待T1—T6实施；单来源纠正能力不等于新通用产品。差距及现有证据见[基线核对](plans/b-attention-distribution-baseline.md)。

<a id="下一步"></a>
## 当前继续位置

积压#6已由PR #10（运行，77a69f2）和PR #11（文档，48e8356）交付并关闭，T0不重做。当前施工集成分支为 `codex/b-attention-distribution`，T1从固定基线48e83566实施；远端状态由统筹在Issue/PR更新。

T1任务分支实现了无framework的独立关注分析建包、普通表单创建/纠正一项解释、下载草稿、本机apply及recover/reopen。CLI与桌面入口及数据形状见[关注分析契约](ATTENTION_CONTRACT.md)。T1最小保存闭环已由独立merger验收并集成至77264bb；不表示T2—T6或真实14记录/A18迁入已经完成。旧源Workspace通过只读Adapter选择普通区，不复制私密原表。

T2任务分支扩展多方面、补录/拆合沿革、主题成员与有范围关系的普通控件，以及工作稿显式Adapter；14记录工作稿本地迁入与纠正证据留在受控work目录。契约以attention-objects/2明确身份/待核规则，旧T1补丁凭明确方面ID兼容。验证以实际交接版本为准，独立验收与集成由统筹处理，不声称main已交付；A18导入对应、分布及图形仍由T3—T6完成。

T0修正版 `6bed3d29` 的本地完整入口为261项、269.713秒、0失败/错误/跳过；两组[远端PR检查](https://github.com/normaltank/ReviewProject/actions/runs/43445505747)与[push检查](https://github.com/normaltank/ReviewProject/actions/runs/43445494942)均成功。此前两项Windows路径别名失败保留，修复仅涉及测试路径身份比较。main接收树与该受审版本一致。本票文档检查不替代T1—T6新业务验收。

后续沿用[正式施工计划](plans/b-attention-distribution-construction.md)的M1—M3、T0—T6依赖和V01—V12验收；T0的基线与检查入口验收通过后才释放T1。该计划的业务路径不因基线整理另立一套路线，统筹继续承担后续交付。

<a id="续接点与远端记录"></a>
<a id="历史资料与文档维护"></a>
## 历史与工程边界

[旧工程概要](history/legacy-engineering.md)仅用于维护兼容性；Framework修订、F0/Fd/Fg、评分优化和标准发布不自动回到当前任务。[本地材料定位](LOCAL_MATERIALS.md#historical-documents)保留完整原文及旧分支身份，不将私有报告复制入公开导航。

47项历史提交与69项工作区积压的逐项去向见[处置清单](history/backlog-2026-11-13.md)。

GitHub Issues/PR是任务状态台账，本页承担续接导航。未完成语义核对、用户本人体验、专业效果或人工收益均明确保留未知；工程测试、代理演练与用户验收分别记录。原件、派生产物、数据库及模型沿用本地授权和[数据契约](DATA_AND_ANNOTATION.md)权限。
