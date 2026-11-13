# 旧工程维护入口

本页为去标识化概要，供维护现有代码、接口和回归使用，不替代[当前业务规格](../specs/b-attention-distribution.md)或[正式计划](../plans/b-attention-distribution-construction.md)。完整旧规格与真实报告保持在原可信主工作区、原工作分支 `codex/opinion-review-flow`，不因本次导航取得公开权限。版本交付状态见[STATE](../STATE.md)。

## 旧条款审核路径

本地 `docs/specs/first-framework-review.md` 和 `first-framework-review-tasks.md` 记录旧首轮规格及任务图，历史远端入口为[父项#1](https://github.com/normaltank/ReviewProject/issues/1)及子项#2—#4。旧路径聚合普通观点和规则包、发现候选问题、保存个案决定或候选标准处理，再通过本机入口恢复。它不是新B关注分析的默认路径，原任务图T1—T3与新计划同名票分别理解。

维护时保留来源与规则版本绑定、失效提示、原分与观点历史，以及个案/通用决定分开和正式标准另行批准的边界。旧模型提案只有保留原规则的对照不代表生成真实新改法；旧代理演练不代表用户本人试用或标准效果验证。

## 后续辅助工具与复核改进

- 本地 `docs/specs/selected-tool-integration.md`：既有 `batch-retrieve` 与 `extract-approved` 的工程接入。检索旁车不改业务修订，来源变化后失效；Flash预检/计划绑定、单账本预算、未知用量阻断和无自动重试等边界继续维护，历史批准不扩为新调用许可。
- 本地 `docs/specs/real-batch-review-friction.md`：按独立观点聚合top-k，保留旧证据片段排名身份；来源/修订/候选或Unicode区间链接只定位明确目标，过期拒收；未引用原文是区间补集，不是已证实漏项。
- 本地 `docs/specs/offline-review-repair.md`：单条件动作与多支替代分开，显式离线重放保留旧响应和运行；引文重合仅提示复核，不自动合并同主题、相反或不同对象观点。

现行兼容字段与补丁边界见[数据契约](../DATA_AND_ANNOTATION.md)，采用决定见[复用决策](../REUSE_DECISIONS.md)。旧规格原文、历史交接、24项审计及完整技术研究的定位见[本地材料导航](../LOCAL_MATERIALS.md#historical-documents)；本页没有复制真实引文或重写原材料。
