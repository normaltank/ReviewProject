# ReviewProject

可重复接收不同A、B输入的本地关注分析工具：理解每批B评语关注什么、怎样表达及彼此的联系与差异，再与当次A关注方向对照，查看分布、明细、可选图形、原文回查和纠正保存。核对的是本项目对数据的处理，不审查B或论文的专业正确性。目标与验收见[业务规格](docs/specs/b-attention-distribution.md)和[复用规格](docs/specs/b-attention-reuse.md)，实际版本见[STATE](docs/STATE.md)。

当前真实验收实例的A工作参照 `a-focus-20261112-01` 为5部分18项，后续A、B的数量、内容和原分均可变化；也可先不导入A。A关注保留原话限定，不是强制评分标准；中文相关研究覆盖的既有清单外决定限该A版本。原话、原分及分析确认的含义见[数据契约](docs/DATA_AND_ANNOTATION.md)与[术语表](GLOSSARY.md)。本地原件、工作稿及旧报告见[材料定位说明](docs/LOCAL_MATERIALS.md)，新克隆不包含这些受限材料。

历史底座由 PR #10/#11、关注流程由 [PR #19](https://github.com/normaltank/ReviewProject/pull/19)交付main，#6及#12—#18已关闭。[父#21](https://github.com/normaltank/ReviewProject/issues/21)与[PR #25](https://github.com/normaltank/ReviewProject/pull/25)继续普通输入、保存态概览和跨批验收，顺序与完成条件见[复用施工计划](docs/plans/b-attention-reuse-construction.md)。[前轮计划](docs/plans/b-attention-distribution-construction.md)和[基线核对](docs/plans/b-attention-distribution-baseline.md)保留历史身份；实时交付状态以工作项为准。

## 打开本机工具

需要Python 3.12、Tkinter及基础依赖。在仓库根目录运行：

```powershell
python -m pip install -r requirements.txt
python -m reviewproto desktop
# 或双击 start-review.cmd
```

窗口以本机可信编辑方式打开原件及静态HTML，没有可写HTTP服务。单来源导入和纠正可直接使用；旧batch仍要求framework规则包，属于[旧工程路径](docs/history/legacy-engineering.md)，不是新业务前置。

1. 在“B关注分析”选择“准备A/B输入并建立独立分析”，逐条录入B或选择已导入工作区的普通分区，按需录入A，核对清单后建包。已有包直接打开。具体步骤见[输入与换批](docs/ATTENTION_INPUT.md)。
2. 打开关注页查看当前保存修订的概览和原话原分；新包尚无观点，先用普通控件整理。按需要筛选记录、材料或表达，回查明细或开启矩阵/局部图。
3. 用普通控件纠正观点/方面、主题、关系范围或A对应，填写修改者声明及理由，加入草稿并下载；回本机窗口应用，再恢复/重开核对。下载不等于保存，页面未导出的草稿刷新后会丢失。
4. 关闭本机写入后备份整份分析目录及所绑定来源；恢复到新空目录再打开核对，不能仅复制HTML。报告、草稿、日志与备份沿用来源权限。

旧单来源导入/纠正和framework batch见[旧工程路径](docs/history/legacy-engineering.md)；新关注分析不要求先走这些步骤。

已有命令和参数可通过 `python -m reviewproto --help` 查看。抽取/检索属于可选辅助，采用范围见[复用决策](docs/REUSE_DECISIONS.md)。模型、检索依赖及本地模型文件须另外准备；窗口不自动下载安装或回退云模型。外部调用须绑定本次材料、计划、批准和预算，历史额度或持有密钥不授权新费用。当前无需新AI征询。

## 验证

仓库检查入口为 `scripts/check.ps1`，环境、浏览器要求和运行方式见[测试说明](docs/TESTING.md)。完整应用回归的直接入口为：

```powershell
python -m unittest discover -s tests -v
```

工程回归使用合成材料；真实原件及语义核对留在本地。必需浏览器场景因缺环境跳过时，不能签收界面验收。本地检查、远端CI、真实产品验收和用户本人体验分别报告。文档维护检查内容、格式、链接及 `git diff --check`，不为文字增加镜像应用测试。

## 工程协作

自然语言向主代理说明目标即可，由主代理统一对接、在任务范围内委派并汇总验收。入口为[AGENTS](AGENTS.md)，按[通用Matt工作流](docs/agents/workflow.md)使用已安装技能，不另建项目专属技能。角色与隔离交接见[多代理约定](docs/agents/multi-agent.md)及[原生角色配置](.codex/agents/)；角色配置存在不表示已执行。

[GitHub Issues](https://github.com/normaltank/ReviewProject/issues)和PR记录需求、依赖、验证及交付。操作及关闭约定见[Issue tracker](docs/agents/issue-tracker.md)，分类见[状态标签](docs/agents/triage-labels.md)，业务术语与设计决定见[领域约定](docs/agents/domain.md)。已确认计划和阶段成果按任务白名单提交；分支已推送、PR待审、main已合并和已部署分别记录。

本机若 `gh` 不在PATH，可运行：

```powershell
& ./scripts/gh.ps1 repo view --json 'nameWithOwner,url'
& ./scripts/gh.ps1 issue list --state open
```

原始课程、评语、论文、审计、完整旧报告及 `work/` 产物继续留本地；`.gitignore` 不能替代暂存白名单检查。历史资料保留原任务身份，不能依据旧“当前/下一步”自动追加任务或外发授权。

## B关注分析

普通输入入口无需手写JSON，支持变化的A、B和原分，详见[输入与换批](docs/ATTENTION_INPUT.md)。已有结构化清单也可用 `python -m reviewproto attention-build tests/fixtures/synthetic_attention_input.json --workspace work/attention-demo` 建包，打开包内 `attention.html`。选择证据并填写解释后下载草稿，用 `attention-apply 草稿路径 --workspace work/attention-demo` 实际保存，`attention-recover --workspace work/attention-demo` 恢复并重开；桌面也有对应应用和恢复入口。

原话原分保持冻结；下载不等于已保存。合成样例与两种来源Adapter、修订/恢复/权限详见[关注分析契约](docs/ATTENTION_CONTRACT.md)。多方面、补录/拆合、主题成员、限定/表达作用、带角色关系及逐方面多重A对应/清单外范围均有普通控件。显式工作稿可用attention-migrate或桌面“迁入B关注工作稿”建立新包；旧身份、沿革和待核关联保留。已保存区提供原话原分明细、记录/材料/表达筛选及可关闭的矩阵与局部关系图，统一使用[记录集合口径](docs/ATTENTION_SUMMARY.md)。受控真实批次从已有包打开，迁入命令不用于覆盖现有分析。

现有包可从桌面“录入A参照并显式换版”准备新A；已有清单也可使用“导入A参照版本”或 `attention-import-a`。导入保留B身份和历史，旧对应待核。B换批或更正则从输入清单建立独立新包，旧包保留，旧观点不自动迁移。格式及待核规则见[关注分析契约](docs/ATTENTION_CONTRACT.md#t3-a版本接续与逐方面对应)。关联普通控件可添加、纠正和移除；下载后实际apply再重开核对，最后一条清空同样保存。
