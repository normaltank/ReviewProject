# B关注分析：现有成果与代码基线

核对日期：2026-11-13。业务依据为[当前规格](../specs/b-attention-distribution.md)，实施安排沿用[正式计划](b-attention-distribution-construction.md)。本页从本地基线报告提取公开维护所需结论；原证据身份及位置见[本地材料说明](../LOCAL_MATERIALS.md)。后续状态归[STATE](../STATE.md)，计划和积压快照不表示main已交付。

## 来源版本及当前整理

原现场核对来自可信主工作区 `codex/opinion-review-flow`，HEAD为 `ffa9dac2ee3dbe731993d8ea359821938380f366`，结论包含该HEAD之外的既有未提交实现。原源码指纹覆盖53个应用、实验、脚本与测试文件，另有必要文档及样稿，仍保存在本地规划证据目录，不能把旧HEAD当完整底座。

本轮[#6](https://github.com/normaltank/ReviewProject/issues/6)按来源整理47个历史提交及69项工作区积压；文档批次[#9](https://github.com/normaltank/ReviewProject/issues/9)从 `b5d405d0ee449d94e1b070f3d5f548a986ceaa1f` 创建，隔离集成分支为 `codex/attention-integration`。这是来源和起始点，不是最终集成/审查结论；各批交接必须同步最新集成头并重验，最终提交与main状态归对应Issue/PR。仓库维护去标识化的[逐项处置清单](../history/backlog-2026-11-13.md)，完整盘点与原报告证据仍留本地。

运行批次已由[PR #10](https://github.com/normaltank/ReviewProject/pull/10)合入main `77a69f2fd9fc2845543efdd2fa7772f2de60ebef`，接收树与受审 `6bed3d29` 一致；本地261项完整检查及两组远端CI成功。文档与完整积压的最终状态继续以#9/#6为准。

## 已有成果怎样使用

- [既有反馈和工作稿](../LOCAL_MATERIALS.md#working-analysis)已吸收表达措辞与作用分开、主题与意见分开、关系范围、多重A对应、原分语境和记录并集。已有14记录、56原分、13暂定主题、93方面、8关系可作迁入起点，数量与分类可纠正，不继续等待新意见。
- 六个A样例用于多重、部分、清单外及范围差别的回归对照，不表示A18全量对应完成；中文相关研究覆盖继续留在外。
- [17条试行规则](../specs/opinion-coding-rules.md)、六案例及20个合成反例用于切分、条件、例示及关系范围核对，允许保留信息等价的替代组织。
- 既有机械核验和定向复核只证明记录范围内的一致性与解释修复，不扩大为专业金标；[复用决策](../REUSE_DECISIONS.md)保留现有Python、SQLite、HTML、Tk及补丁底座，抽取和检索不是本批前置。

## 可以复用的底座

1. **冻结原件、原分与证据**：`reviewproto/core.py` 的解析与候选校验及 `intake.py` 的结构化输入，保留raw_value、解析状态和Unicode区间，引用须与冻结文本切片一致。
2. **纠正与历史**：`store.py` 的 `Workspace.apply()`、事务、发布及恢复，`understanding.py` 的当前视图；支持creates、edits、替换历史、冲突、幂等、原子拒收和提交后输出失败恢复。
3. **普通编辑及定位**：`editor.js` 的选区、补录、拆分和语义字段，`review_links.py` 的身份/修订定位，`render.py` 的全文、证据和历史。下载后仍须本机应用并恢复/重开。
4. **只读跨来源快照经验**：`batch.py` 的 `source_state()` / `select_source()` 冻结普通分区、来源修订、所选观点和原分，同来源及绑定副本按一次处理；复用这些机械约束，不复用旧条款决定语义。

## 需要适配或新增的缺口

1. **中性入口**：旧batch构建和渲染要求framework，manifest、issue及apply围绕规则和个案/标准决定；当前尚无 `attention-build / attention-apply / attention-recover` 新入口。
2. **稳定身份**：当前概念注册表限单source，candidate关系限同分区；clause_links缺方面范围、理由、A版本及清单外结构。`conditional_actions`不是带角色的多对象关系组，重跑ID不能自动继承人工关联。
3. **B解释明细**：尚缺跨记录主题定义/成员依据、稳定方面及普通编辑闭环，旧speech_function没有分开套话候选与本次表达作用。
4. **A18内容参照**：缺完整原话版本、逐方面多重/部分/相关对应、清单外与暂未定范围/理由及普通控件；旧clause/framework不能直接替代。
5. **分布与可选图形**：尚缺记录并集、分母、状态分列、A五部分去重及对应矩阵/局部图；检索内部数值matrix不是用户分析视图。
6. **往返一致性**：尚无新分析明细、统计、图形共用已保存修订的产品路径。静态已打开页面不实时感知其他页面变化。

## 工作稿迁入约束

本地 `working-attention-index-v1` 不是现有候选或batch输入协议。旧Rxx-Fnn按列表位置生成，插入/重排会变ID；旧定位使用首个anchor匹配，不能证明重复片段位置唯一；旧local_relations的成员列表不能代替独立关系ID、端点角色和方向。

迁入须持久保存旧别名到新身份的映射，核对重复引文位置及关系作用域，歧义保留待核。不能按顺序猜配、塞入旧schema或直接标confirmed。新确认仅表示分析记录已核对，不表示认可B专业结论。

## 验证证据及未验证范围

原计划核对曾运行CLI帮助及 `test_core_understanding.py` 的10项：9通过，1因当时未配置必需浏览器环境变量跳过；这不是全套或浏览器验收。工作稿曾机械复算14记录、56原分、93方面、8关系、101处引文切片和13主题集合一致，未逐一重核全部Word转录、重复定位及解释。

本轮T0/[#8](https://github.com/normaltank/ReviewProject/issues/8)在隔离基线另实跑 `python -m unittest discover -s tests -v`：261项、267.755秒、0失败、0跳过，显式配置Chrome环境，证据仍本地，由T0关联实际版本。新增统一入口为 `scripts/check.ps1`，Windows CI为 `.github/workflows/check.yml`，环境和运行方式见[测试说明](../TESTING.md)。修正版 `6bed3d29` 的完整入口再次通过261项、0跳过；两组远端CI成功及实际main交付见本页上方PR #10和[STATE](../STATE.md)。

本票只核对文档内容、状态、格式、链接、隐私白名单及差异；应用全套由T0承担。旧238项历史结果不替代本轮261项，也不能把261项底座回归当成新业务V01—V12、受控真实批次、双轴最终审查或用户本人体验。#6的最终交付以各批集成、审查、PR及main证据为准，状态只在对应工作项维护。
