# 交接状态 2026-11-14

<a id="当前目标与a参照"></a>
<a id="已确认的业务边界"></a>
## 当前目标

处理已有B评语、原分及按需论文语境，理解B关注、表达功能、联系差异、清单内外和本批分布；提供明细、可选图形、原文回查和纠正保存。行为及验收以[当前规格](specs/b-attention-distribution.md)为准。核对本项目处理是否忠实，分析确认不表示认可B专业结论；论文仅帮助理解对象与语境。

A工作版本 `a-focus-20261112-01` 为5部分18项关注方向，保留原话限定，不是强制评分标准。中文相关研究覆盖按当前清单外处理，不再问A。本批为4篇论文语境、14条普通评语记录和56项原分；教师、轮次及精确送审关系仍未全部确认。材料身份与入口见[本地材料定位](LOCAL_MATERIALS.md#batch-inputs)。

<a id="已交付及证据"></a>
<a id="方法检查与规则校准"></a>
## 当前实现与真实包

T1—T6及最终审查返修已由独立merger串行验收并集成到 `codex/b-attention-distribution`，运行代码固定于 `4c2da43c3da7cf09f4fc5301b6e654c051a01f3a`。关注流程使用独立attention.sqlite3，不要求framework、旧issue或模型请求；旧单来源与batch保持兼容。可用入口、补丁及版本/失效规则见[关注分析契约](ATTENTION_CONTRACT.md)，集合、分母和筛选见[汇总接口](ATTENTION_SUMMARY.md)。

- 本机窗口和CLI可建立/迁入/打开分析包、导入A版本、应用草稿、恢复重开。下载仍是未应用草稿。
- 普通页面可补录/拆合多方面观点，纠正限定/表达作用/套话候选、主题及成员依据、带角色和范围的关系、多个A对应及清单外内容；身份和历史保留，受影响关联待核。
- 已保存区显示原话原分明细、记录/材料/表达筛选及可关闭矩阵/局部原生SVG图，共用同一修订和记录集合。记录/材料改变N，表达筛选保留N；A部分按并集，明确/部分/相关/未定/待核分别显示。

[受控主包](LOCAL_MATERIALS.md#attention-delivery)保留原analysis_id及历史，当前修订7：14记录、56原分、97有效观点、111有效方面、13主题、9关系，A18完整导入并逐方面给出工作去向。13主题/93方面/8关系是[旧工作稿](LOCAL_MATERIALS.md#working-analysis)的迁入起点，原稿保留。本包的工作解释及待核状态不批量升级为confirmed。

T6在受控目录逐记录核对原话原分、A18、全部方面去向及9关系的限定/角色/范围，保留有据歧义；主包无新增语义修改。四类真实普通浏览器纠正在明确标识的NOT-MAIN副本完成7→11修订，用来验证切分、主题、条件范围和A对应往返，不作为主分析新发现。明细、集合、矩阵和局部图同修订/筛选/分母/记录集合；下载未apply保持旧保存结果。冲突、坏补丁原子拒收、幂等、输出失败recover、整包关闭后备份恢复及独立输入B/A失效有可复现证据，入口为上述本地HANDOFF。工程检查、独立审查及交付须对应实际最终版本。

原件指纹与先前普通区XML/原分证据一致；R09/R14五处可见编号沿用旧Word探针，本轮未重验原生Word渲染。4论文只核文件关系，不复审B专业正确性。用户本人尚未体验，代理演练不等于用户验收、专业金标或节省工时证明。

<a id="下一步"></a>
<a id="续接点与远端记录"></a>
## 当前继续位置

当前父任务为[Issue #12](https://github.com/normaltank/ReviewProject/issues/12)，施工沿[正式计划](plans/b-attention-distribution-construction.md)的M1—M3/T0—T6/V01—V12；交付归[PR #19](https://github.com/normaltank/ReviewProject/pull/19)。T6贯通、集中返修和两轴审查已完成：Spec无未解决项；Standards的A原文列表待核误显明确问题已修复并独立复核通过。原Standards角色入口失效后，由fresh default代理按同一角色约定接续复核，实际覆盖及限制留在PR证据。新功能是否已合入main以PR实际状态为准，任务随实际交付关闭。后续从主包修订7继续使用，不重复施工或把NOT-MAIN演练回灌主包。

本地运行须使用包含上述集成成果的代码工作树；原可信D盘工作区保留旧分支及未提交历史材料，其旧runtime不能当作新工具。私有打开脚本明确指向保留的集成工作树，见本地HANDOFF；仓库克隆只包含合成样例。

积压#6已由[PR #10](https://github.com/normaltank/ReviewProject/pull/10)（运行，77a69f2）和[PR #11](https://github.com/normaltank/ReviewProject/pull/11)（文档，48e8356）交付并关闭，T0不重做。最终运行代码4c2da43的完整本地检查为297项、297.922秒、0失败/错误/跳过，对应push与pull_request两组CI均成功；本页仅状态导航，后续文档提交的检查与最终交付以Issue/PR为准。最新本地HANDOFF记录投影刷新、关闭备份、原始资料指纹及实际运行位置。

<a id="历史资料与文档维护"></a>
## 历史与工程边界

[旧工程概要](history/legacy-engineering.md)用于维护兼容性；Framework修订、F0/Fd/Fg、评分优化和标准发布属于另行任务。[基线核对](plans/b-attention-distribution-baseline.md)保留2026-11-13施工前差距；47项历史提交及69项积压的去向见[处置清单](history/backlog-2026-11-13.md)。两份既有外部意见已吸收，[六案例与试行规则](specs/opinion-coding-rules.md)继续作校准，不再新AI征询。

GitHub Issues/PR是任务状态台账，本页承担续接导航。原件、数据库、真实报告、草稿、截图、备份和恢复副本均留本地可信工作区；权限沿用[数据契约](DATA_AND_ANNOTATION.md)。历史资料中的“当前/下一步”保留当轮身份。
