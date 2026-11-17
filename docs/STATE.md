# 交接状态 2026-11-17

面向使用者的进度和待办先看[项目总清单](../PROJECT_TODO.md)；本页保留工程续接与证据细节。

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

2026-11-17 已收拢侧边“比较当前工作与 RAG”的研究与隔离补丁，执行顺序见[当前总施工计划](plans/attention-followthrough-20261117.md)，可读进度见[总清单](../PROJECT_TODO.md)。先独立接收模型内容重复字段的小修复，再推进 #38 的语义范围问题和新 A/B 完整路径验收。DocETL/LOTUS/Haystack 已有隔离接口验证不重复做；归并预览尚未接入产品，当前不增加生产依赖。具体证据与候选身份见[工具状态](research/attention-tools.md#side-results-20261117)和[本地入口](LOCAL_MATERIALS.md#side-research-20261117)。

收拢及小修复由[#40](https://github.com/normaltank/ReviewProject/issues/40)/[PR42](https://github.com/normaltank/ReviewProject/pull/42)交付：451 项本地完整检查零失败/错误/跳过，两轴审查无未解决发现，本轮无新增模型调用。最终远端与运行入口状态见工作项。旧 #1 已按目标变更退出；#38、独立连接词 #41 尚未修复。#39 在主线检查再次复发后追加测试同步维护，其验收与交付见该工作项；不以格式保全、工程维护或归并实验代替内容验收。

本轮延续focused路径，[Issue36](https://github.com/normaltank/ReviewProject/issues/36)与[PR37](https://github.com/normaltank/ReviewProject/pull/37)补齐原A对照请求遗漏的已有部分名称，具体边界见[A语境规格](specs/b-attention-a-context.md)。名称只辅助理解，不新增要求或排除跨部分的实际交集；未分组与无A保持。`1130139`完整检查444项零失败/错误/跳过，固定两轴审查无发现。新冻结5B三组A输入的独立盲首评两版均3通过、2部分；基线40次API，修订臂回放同一B后仅22次实际A调用，合计62次、用量已知，按本次时段估算约0.0326美元而非账单。没有证明语义提升；共同的确定排除/必要条件附加解释问题见[后续核对](https://github.com/normaltank/ReviewProject/issues/38)，不改写首评或混入本轮输入修复。最终文档、CI、main与本地入口状态以工作项为准。

CI曾在旧跨进程测试等待子进程预校验处超时，同产品/测试版本后续CI也通过；这些终态均保留。验收集中返修仅将解释器/导入就绪等待与原10秒预校验窗口分开，增加子进程退出诊断并保持全部唯一收据/历史断言；同一子进程导入前延迟12秒的受控红测已转绿。该测试修改不改变已验证的生产B/A路径，不追加模型调用；最终完整工程检查及CI仍须对应最终版本。

新诊断随后捕获同时打开包时重复替换正确`.gitignore`导致Windows共享冲突，以及初始化失败后SQLite连接未释放。构造器现保留正确保护文件，错误/缺失仍修复，并在连接后的初始化失败时关闭数据库再抛出；数据库身份检查顺序与保护内容不变。真实合成读锁红绿及43项定向通过，新增3项打开/资源测试；候选、提示、API及其他运行文件与实际推理`1130139`保持，只有本地包初始化改变。447项最终完整检查及对应CI仍以工作项实际终态为准。

最新费用与工具决定见[当前名单](research/attention-tools.md)：只保留已授权DS Flash费用，Gemini Decisions/MAXQDA退出实施，LLooM/LLMCode保留方法参考。[Issue34](https://github.com/normaltank/ReviewProject/issues/34)的记录级DS对照已形成不采用结论：少请求未带来费用/质量优势，原型留在隔离分支，不进入main运行路径。main仅收拢名单和依据，具体交付/CI终态见工作项。现有默认仍有待核边界，不能称任意新输入的正确率保证。结果阅读层由[PR33](https://github.com/normaltank/ReviewProject/pull/33)交付，操作见[阅读说明](ATTENTION_READING.md)。

本轮[父任务#26](https://github.com/normaltank/ReviewProject/issues/26)与[PR31](https://github.com/normaltank/ReviewProject/pull/31)补齐可变A/B的实际候选路径；规格及依赖见[内容与位置规格](specs/b-attention-candidates.md)和[施工计划](plans/b-attention-candidates-construction.md)。C1—C3及集中返修经独立merger串行集成，候选代码头为`247d26bcb466b3060ca35b1f5974d89ed411fbff`。先分析全部所选普通B分区，再独立对照当批A；无A可先分析，不强填清单外。普通操作见[候选生成与核对](ATTENTION_CANDIDATES.md)。

用户于2026-11-15要求直接接入API，指定4.1 Flash 1017、不用Pro。普通窗口默认官方DeepSeek API及`deepseek-flash`，凭据保存在仓库外当前Windows用户DPAPI或显式环境变量；不本地微调、不自动下载或回退。别名对应当日官方映射，不能冒称永久锁定权重版本。本轮实际外发仅合成材料，真实主包修订7及原始指纹保持，原D盘分支和69项未提交成果保留。

新输入05在`76dd114`干净版本冻结后才推理：7条B、8个普通段落，A分别3/2/0项，64次实际Flash调用，独立首评7通过、0部分、0失败，108处Unicode逐字坐标一致。一次A结构错误经允许的单次格式修复后继续，原失败、原草稿和全部用量保留，运行仍可标部分；处理状态不等于语义核实。核对的是本项目处理，不是专业复审；代理演练不等于用户体验、专业金标或未来任意输入的正确率。

实际普通Tk输入→Flash生成→Chrome位置/原文回查→接收→纠正→下载→应用/恢复重开已贯通1→2→3；生成前后正式文件字节不变，重复接收保留人工纠正及限定。桌面1440与窄屏420、原生920/760窗口有实际截图及零JS错误/横向溢出检查；独立视觉Finish结论为`disposition: ship`，仅覆盖所审界面。跨记录主题归并及所有候选仍需人工核对，不能自动升级为confirmed。

独立Standards在`76dd114`发现同run并发接收覆盖成功收据；返修后以不可覆盖原子发布保存唯一接收补丁，并核对真实双进程、失败恢复、过期和人工成果保留。除accept外17个既有函数AST及其余42个生产文件字节与实际推理版本相同；这是路径等价凭证，不是新增API调用。另在未接收合成副本用最终接收代码走普通Tk/Chrome首次接收、纠正、应用及重开0→1→2，未重新推理或改写首评分数。

历史失败保留：本机4B两轮新输入未通过；9B组合在已知池为2通过、4部分、1失败，新旧适配不同，不能把差异全归于权重。Flash新03及新04首评均5通过、1部分、1失败；后续复跑和有限控制属于已知开发，不重标独立通过。额外A前提核查因误删合法局部交集未采用，当前在原A对照入口明确对象、属性、语境及partial/related边界。故障前请求意图先持久化，用量未知不写0；候选审计本地写入限次恢复与HTTP重试分开。

`76dd114`的规范完整检查429项、零失败/错误/跳过（含真实Chrome）。接收返修后的完整检查、固定版本Spec/Standards复核、最终CI、获授权的main交付及运行树SHA，分别以[PR31](https://github.com/normaltank/ReviewProject/pull/31)和本地HANDOFF的实际终态为准，不把此前检查或工程集成冒充最终交付。后续从普通输入清单开始；现有真实包保持原分析，不因工具换版自动重算或外发。

前轮[Issue #12](https://github.com/normaltank/ReviewProject/issues/12)及T1—T6已由[PR #19](https://github.com/normaltank/ReviewProject/pull/19)合入main `5b31b393294144b90786128c1d1b7bcb0ea037c8`，相关任务已关闭。T6贯通、集中返修和两轴审查完成：Spec无未解决项；Standards的A原文列表待核误显明确问题已修复并独立复核通过。原Standards角色入口失效后，由fresh default代理按同一角色约定接续复核，实际覆盖及限制留在PR证据。main CI成功。不重复施工或把NOT-MAIN演练回灌主包。

前轮父任务[Issue #21](https://github.com/normaltank/ReviewProject/issues/21)，对应[可复用工具施工计划](plans/b-attention-reuse-construction.md)及[PR25](https://github.com/normaltank/ReviewProject/pull/25)已交付关闭：普通输入建包/A录入（#22）、同保存修订的通用概览（#23）已由独立merger集成；两组变化A/B的普通Tk→网页表单→下载/应用/重开（#24）已贯通。无A2B与不同结构A/3B验证Unicode/原分、主题/关系/A对应、换A历史与纠正、材料组分母、另建变化B及旧包文件保护、来源失效/失联恢复。仅用合成材料，不等同用户本人体验或专业语义金标。PR25终版完整检查316项、零失败/错误/跳过，两轴审查和main CI通过。

下一批从普通输入清单开始，已有真实包继续打开；不重做旧迁入或为新批写专用报告脚本。B变化先走独立新包并保留旧分析，原包内B替换/旧标注迁移未实现。冻结样例导读[Issue #20](https://github.com/normaltank/ReviewProject/issues/20)已按其范围交付关闭，仍不代表整体工具验收。

本地运行须使用包含上述集成成果的代码工作树；原可信D盘工作区保留旧分支及未提交历史材料，其旧runtime不能当作新工具。私有打开脚本明确指向保留的集成工作树，见本地HANDOFF；仓库克隆只包含合成样例。

积压#6已由[PR #10](https://github.com/normaltank/ReviewProject/pull/10)（运行，77a69f2）和[PR #11](https://github.com/normaltank/ReviewProject/pull/11)（文档，48e8356）交付并关闭，T0不重做。最终运行代码4c2da43的完整本地检查为297项、297.922秒、0失败/错误/跳过，对应push与pull_request两组CI均成功；本页仅状态导航，后续文档提交的检查与最终交付以Issue/PR为准。最新本地HANDOFF记录投影刷新、关闭备份、原始资料指纹及实际运行位置。

<a id="历史资料与文档维护"></a>
## 历史与工程边界

[旧工程概要](history/legacy-engineering.md)用于维护兼容性；Framework修订、F0/Fd/Fg、评分优化和标准发布属于另行任务。[基线核对](plans/b-attention-distribution-baseline.md)保留2026-11-13施工前差距；47项历史提交及69项积压的去向见[处置清单](history/backlog-2026-11-13.md)。两份既有外部意见已吸收，[六案例与试行规则](specs/opinion-coding-rules.md)继续作校准，不再新AI征询。

GitHub Issues/PR是任务状态台账，本页承担续接导航。原件、数据库、真实报告、草稿、截图、备份和恢复副本均留本地可信工作区；权限沿用[数据契约](DATA_AND_ANNOTATION.md)。历史资料中的“当前/下一步”保留当轮身份。
