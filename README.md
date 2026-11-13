# ReviewProject

理解已有B评语关注什么、怎样表达及彼此的联系与差异，再与A已提供的关注方向对照，说明本批清单内外及分布；支持明细、可选可视化、原文回查和纠正保存。核对的是本项目对数据的处理，不审查B或论文的专业正确性。当前目标与验收见[业务规格](docs/specs/b-attention-distribution.md)，实际能力及继续位置见[STATE](docs/STATE.md)。

A工作参照 `a-focus-20261112-01` 为5部分18项关注方向，保留原话限定，不是强制评分标准；中文相关研究覆盖留在当前清单外，不再问A。原话、原分及分析确认的含义见[数据契约](docs/DATA_AND_ANNOTATION.md)与[术语表](GLOSSARY.md)。本地原件、工作稿及旧报告见[材料定位说明](docs/LOCAL_MATERIALS.md)，新克隆不包含这些受限材料。

交付衔接由 [Issue #6](https://github.com/normaltank/ReviewProject/issues/6) 记录：运行批次[#8](https://github.com/normaltank/ReviewProject/issues/8)已通过[PR #10](https://github.com/normaltank/ReviewProject/pull/10)合入main，文档与隐私边界由[#9](https://github.com/normaltank/ReviewProject/issues/9)承接。确认#6全部处置完成后，直接继续B关注本职，不重做已验证底座。[正式施工计划](docs/plans/b-attention-distribution-construction.md)保留T0—T6行为、依赖与验收，[基线核对](docs/plans/b-attention-distribution-baseline.md)区分已有底座与真实缺口。新无framework关注分析、分布、可选视图及统一保存闭环尚待实施；独立工作稿和未合并快照不表示main已交付。

## 使用既有底座

需要Python 3.12、Tkinter及基础依赖。在仓库根目录运行：

```powershell
python -m pip install -r requirements.txt
python -m reviewproto desktop
# 或双击 start-review.cmd
```

窗口以本机可信编辑方式打开原件及静态HTML，没有可写HTTP服务。单来源导入和纠正可直接使用；旧batch仍要求framework规则包，属于[旧工程路径](docs/history/legacy-engineering.md)，不是新业务前置。

1. 导入时选择来源声明、docx/csv/json类型和材料；使用专用工作目录保存冻结来源、数据库及派生产物。
2. 打开已有工作区并恢复报告，核对原话和原分。可从原文选区补录、拆分或纠正观点，保留否定、条件、理由及替代动作的证据；不明确的语义保持待核。
3. 在普通表单填写修改者声明及理由，下载草稿补丁；回到本机窗口应用补丁，再恢复/重开核对。下载不等于数据库已经保存，未导出的页面草稿刷新后会丢失。
4. 备份与恢复按整份可信工作区处理，不能仅复制HTML。报告、导出、检索及日志沿用来源权限，普通意见不自动可对作者或公众开放。

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
