# 交接状态 2026-11-15

<a id="当前目标与a参照"></a>
<a id="已确认的业务边界"></a>
## 当前目标

建设可重复接受不同A、B输入的关注分析工具，理解每次材料中B关注、表达功能、联系差异、清单内外和本批分布；提供明细、可选图形、原文回查和纠正保存。行为及验收以[当前规格](specs/b-attention-distribution.md)及[复用规格](specs/b-attention-reuse.md)为准。当前数据和导读是一次验收实例。核对本项目处理是否忠实，分析确认不表示认可B专业结论；论文仅帮助理解对象与语境。

A工作版本 `a-focus-20261112-01` 为5部分18项关注方向，保留原话限定，不是强制评分标准。中文相关研究覆盖按当前清单外处理，不再问A。本批为4篇论文语境、14条普通评语记录和56项原分；教师、轮次及精确送审关系仍未全部确认。材料身份与入口见[本地材料定位](LOCAL_MATERIALS.md#batch-inputs)。

<a id="已交付及证据"></a>
<a id="方法检查与规则校准"></a>
## 当前实现与真实包

T1—T6及最终审查返修已由独立merger串行验收并经PR19交付，前轮运行基线为 `4c2da43c3da7cf09f4fc5301b6e654c051a01f3a`。本轮普通输入与保存态概览沿[PR25](https://github.com/normaltank/ReviewProject/pull/25)交付。关注流程使用独立attention.sqlite3，不要求framework、旧issue或模型请求；旧单来源与batch保持兼容。输入步骤见[输入与换批](ATTENTION_INPUT.md)，补丁及版本/失效规则见[关注分析契约](ATTENTION_CONTRACT.md)，集合、分母和筛选见[汇总接口](ATTENTION_SUMMARY.md)。

- 本机窗口可逐条录入B原话/任意原分、选择普通工作区分区、录入可选A部分/完整条目并核对清单，独立建包；可从普通入口显式换A。CLI清单、旧工作稿迁入及打开/应用/恢复保持。下载仍是未应用草稿。
- 普通页面可补录/拆合多方面观点，纠正限定/表达作用/套话候选、主题及成员依据、带角色和范围的关系、多个A对应及清单外内容；身份和历史保留，受影响关联待核。
- 已保存区显示原话原分明细、记录/材料/表达筛选及可关闭矩阵/局部原生SVG图，共用同一修订和记录集合。记录/材料改变N，表达筛选保留N；A部分按并集，明确/部分/相关/未定/待核分别显示。
- 当前关注概览由同一保存态生成，动态显示本批规模、A结构、记录集合、空态和绑定状态，链接原话；不复制冻结导读的发现与案例。材料组使用显式声明并兼容旧定位字段。

[受控主包](LOCAL_MATERIALS.md#attention-delivery)保留原analysis_id及历史，当前修订7：14记录、56原分、97有效观点、111有效方面、13主题、9关系，A18完整导入并逐方面给出工作去向。13主题/93方面/8关系是[旧工作稿](LOCAL_MATERIALS.md#working-analysis)的迁入起点，原稿保留。本包的工作解释及待核状态不批量升级为confirmed。

T6在受控目录逐记录核对原话原分、A18、全部方面去向及9关系的限定/角色/范围，保留有据歧义；主包无新增语义修改。四类真实普通浏览器纠正在明确标识的NOT-MAIN副本完成7→11修订，用来验证切分、主题、条件范围和A对应往返，不作为主分析新发现。明细、集合、矩阵和局部图同修订/筛选/分母/记录集合；下载未apply保持旧保存结果。冲突、坏补丁原子拒收、幂等、输出失败recover、整包关闭后备份恢复及独立输入B/A失效有可复现证据，入口为上述本地HANDOFF。工程检查、独立审查及交付须对应实际最终版本。

原件指纹与先前普通区XML/原分证据一致；R09/R14五处可见编号沿用旧Word探针，本轮未重验原生Word渲染。4论文只核文件关系，不复审B专业正确性。用户本人尚未体验，代理演练不等于用户验收、专业金标或节省工时证明。

<a id="下一步"></a>
<a id="续接点与远端记录"></a>
## 当前继续位置

本轮工程集成头`bfacebce93c7d3af190e14f25862adca1dbab364`，独立merger已接收C1/C2/C3，候选核心25项、普通UI8项、位置3项、视图4项相关检查通过。实际合成本机推理已运行，18项A容量路径可用；新7条独立语义核对为1通过、1部分、5不满足，发现A理由错配、处置分类和情态问题，C4保持开放，待双轴审查后统一返修。工程集成不等于本轮验收或main交付；当前稳定运行树仍为PR25。

当前在main `d78cb256e5ccf5d3111b87771f583df3f3638692`（PR25）之后，按用户的问题重构及“继续施工”实施[内容与位置候选规格](specs/b-attention-candidates.md)和[施工计划](plans/b-attention-candidates-construction.md)。父任务[Issue #26](https://github.com/normaltank/ReviewProject/issues/26)：先B内容分析、再独立A对照，补可回查的直观位置与普通界面候选路径；沿[C1 #27](https://github.com/normaltank/ReviewProject/issues/27)/[C2 #28](https://github.com/normaltank/ReviewProject/issues/28)并行、[C3 #29](https://github.com/normaltank/ReviewProject/issues/29)贯通、[C4 #30](https://github.com/normaltank/ReviewProject/issues/30)新输入实际验证推进。当前稳定版本仍需人工填写语义对象，不把已有输入/编辑能力称为自动理解。新施工状态与实际验证跟随本轮Issue/PR，完成前不修改真实主包。

前轮[Issue #12](https://github.com/normaltank/ReviewProject/issues/12)及T1—T6已由[PR #19](https://github.com/normaltank/ReviewProject/pull/19)合入main `5b31b393294144b90786128c1d1b7bcb0ea037c8`，相关任务已关闭。T6贯通、集中返修和两轴审查完成：Spec无未解决项；Standards的A原文列表待核误显明确问题已修复并独立复核通过。原Standards角色入口失效后，由fresh default代理按同一角色约定接续复核，实际覆盖及限制留在PR证据。main CI成功。不重复施工或把NOT-MAIN演练回灌主包。

前轮父任务[Issue #21](https://github.com/normaltank/ReviewProject/issues/21)，对应[可复用工具施工计划](plans/b-attention-reuse-construction.md)及[PR25](https://github.com/normaltank/ReviewProject/pull/25)已交付关闭：普通输入建包/A录入（#22）、同保存修订的通用概览（#23）已由独立merger集成；两组变化A/B的普通Tk→网页表单→下载/应用/重开（#24）已贯通。无A2B与不同结构A/3B验证Unicode/原分、主题/关系/A对应、换A历史与纠正、材料组分母、另建变化B及旧包文件保护、来源失效/失联恢复。仅用合成材料，不等同用户本人体验或专业语义金标。PR25终版完整检查316项、零失败/错误/跳过，两轴审查和main CI通过。

下一批从普通输入清单开始，已有真实包继续打开；不重做旧迁入或为新批写专用报告脚本。B变化先走独立新包并保留旧分析，原包内B替换/旧标注迁移未实现。冻结样例导读[Issue #20](https://github.com/normaltank/ReviewProject/issues/20)已按其范围交付关闭，仍不代表整体工具验收。

本地运行须使用包含上述集成成果的代码工作树；原可信D盘工作区保留旧分支及未提交历史材料，其旧runtime不能当作新工具。私有打开脚本明确指向保留的集成工作树，见本地HANDOFF；仓库克隆只包含合成样例。

积压#6已由[PR #10](https://github.com/normaltank/ReviewProject/pull/10)（运行，77a69f2）和[PR #11](https://github.com/normaltank/ReviewProject/pull/11)（文档，48e8356）交付并关闭，T0不重做。最终运行代码4c2da43的完整本地检查为297项、297.922秒、0失败/错误/跳过，对应push与pull_request两组CI均成功；本页仅状态导航，后续文档提交的检查与最终交付以Issue/PR为准。最新本地HANDOFF记录投影刷新、关闭备份、原始资料指纹及实际运行位置。

<a id="历史资料与文档维护"></a>
## 历史与工程边界

[旧工程概要](history/legacy-engineering.md)用于维护兼容性；Framework修订、F0/Fd/Fg、评分优化和标准发布属于另行任务。[基线核对](plans/b-attention-distribution-baseline.md)保留2026-11-13施工前差距；47项历史提交及69项积压的去向见[处置清单](history/backlog-2026-11-13.md)。两份既有外部意见已吸收，[六案例与试行规则](specs/opinion-coding-rules.md)继续作校准，不再新AI征询。

GitHub Issues/PR是任务状态台账，本页承担续接导航。原件、数据库、真实报告、草稿、截图、备份和恢复副本均留本地可信工作区；权限沿用[数据契约](DATA_AND_ANNOTATION.md)。历史资料中的“当前/下一步”保留当轮身份。
