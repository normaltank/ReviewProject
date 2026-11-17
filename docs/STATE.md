# 交接状态 · 2026-11-17

用户授权主动重构并删除过时实现，当前工程范围见[改革规格](specs/project-reform.md)，执行与交付以[父#47](https://github.com/normaltank/ReviewProject/issues/47)及其子项为准。本页是续接导航，不替代任务台账。

<a id="当前目标与a参照"></a>
<a id="已确认的业务边界"></a>
## 当前目标

理解每批B评语的关注、表达功能、理由条件、关系和分布，并对照当批可选A；可读、可查、可纠正、可保存。核对本项目是否忠实处理材料，不裁定B或论文专业正确性，不把A改成强制标准。以[业务规格](specs/b-attention-distribution.md)和[复用规格](specs/b-attention-reuse.md)为准。

当前真实实例的A是5部分18项，B是14条普通评语和56项原分；这不是产品固定数量。原件和分析包的身份及本地定位见[材料入口](LOCAL_MATERIALS.md)，受限文件不在新克隆中。原D盘旧分支和未提交材料保留，不得把旧代码当作本轮运行版本，也不得替其他会话覆盖其工作区。

<a id="已交付及证据"></a>
<a id="方法检查与规则校准"></a>
## 当前结构

- 关注分析使用`attention.sqlite3`作为唯一当前分析写入及历史。普通操作为新建/打开、分析、阅读、修改、保存。
- `local_io`提供被实际复用的本地文件与严格JSON能力；`legacy_source`只读历史普通来源，核验原件、分区和原分，不依赖旧规则包或旧审核写入器。
- 桌面结果页通过固定绑定单包的临时回环会话调用已有apply事务。静态HTML无会话凭据，只能阅读和导出草稿；新编辑统一使用`attention-patch/2`，旧补丁兼容集中适配。
- 旧单来源审核、framework/batch写入、旧编辑资源及专用实验退役。历史原件、原分、人工记录和现有分析包保留，不自动重算或重绑。

行为契约见[数据与标注](DATA_AND_ANNOTATION.md)、[关注分析](ATTENTION_CONTRACT.md)、[汇总口径](ATTENTION_SUMMARY.md)。操作见[输入](ATTENTION_INPUT.md)、[候选分析](ATTENTION_CANDIDATES.md)、[阅读修改](ATTENTION_READING.md)。

<a id="下一步"></a>
<a id="续接点与远端记录"></a>
## 验收与继续位置

体验重做已沿[父#53](https://github.com/normaltank/ReviewProject/issues/53)继续，规格见[体验规格](specs/attention-experience.md)和[汇总需求](specs/attention-summary-visualization.md)。#54/#55的首版网页与本机功能已集成到任务分支，草稿[PR56](https://github.com/normaltank/ReviewProject/pull/56)堆叠在PR52之上；未合并main。首版网页视觉未过，用户最新反馈也明确否定其字号、布局和本机控件呈现，允许重做单评语页。原focus-v1批准和74%报告均保留历史身份，不能冒充新版已验收。

功能基线`ca6a775`已完成`scripts/check.ps1`：236项通过，失败0、错误0、跳过0；独立Standards/Spec的三项发现及处置方面状态边界均关闭，包含实际合成浏览器保存重开。这不证明视觉质量，也不表示该本地提交已经推送或main已更新。新汇总及阅读效果图仍为待反馈提案，未替换程序；后续实现和交付继续记录在#53及PR56。

桌面“评语分析”快捷方式仍指旧日常工作树`review-attention-integration`，不是当前任务树。用户提供的黑色录入截图则匹配本轮合成验证窗口，属于首版实现自身的问题。新视觉确认并实现前，不把旧入口切到另一个未验收界面；后续界面验证须使用隔离桌面或明确受控的测试会话，避免在用户工作桌面弹窗。

[#38](https://github.com/normaltank/ReviewProject/issues/38)语义范围和[#44](https://github.com/normaltank/ReviewProject/issues/44)关系保全仍按原工作项处理。此次改革不新增付费模型请求，不用工程通过冒称语义问题已解决。方法采用决定见[工具记录](research/attention-tools.md#method-first-20261117)，已有局部试验不重复施工。

受控主分析包的旧工作解释及待核状态不自动升级确认。此前候选推理、真实副本往返、并发修复及各轮首评的证据留在原工作项、本地HANDOFF和Git历史，不重标为本轮新验证。冻结导读是历史实例，不是新批次自动报告。

<a id="历史资料与文档维护"></a>
## 历史边界

[旧工程概要](history/legacy-engineering.md)只解释已退役路径；旧规格、审计、`.planning/`及`work/`中的“当前/下一步”保留当轮身份。当前任务只沿用本次目标、相关确认及实际版本证据。原件、数据库、模型、密钥、截图和备份留本地可信目录，发布任务记录不取得材料外发权限。
