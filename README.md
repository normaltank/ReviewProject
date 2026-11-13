# ReviewProject

审稿评价框架研究项目。工程工作以 GitHub Issues 记录需求、规格和任务，采用 Matt Pocock skills 的阶段工作流。

在本项目中直接用自然语言向主代理描述目标即可；主代理是唯一对接统筹，在任务范围内自动分派临时子代理并汇总验收。重大业务决定由统筹集中确认，已有确认沿用。

- 工作流：[`docs/agents/workflow.md`](docs/agents/workflow.md)
- 多代理交接与验收：[`docs/agents/multi-agent.md`](docs/agents/multi-agent.md)
- 通用Matt技能：按工作流读取已安装的`ask-matt`及所选阶段技能，不另设项目专属技能。
- 原生角色：[`.codex/agents/`](.codex/agents/)；默认设置：[`.codex/config.toml`](.codex/config.toml)
- 需求与任务：<https://github.com/normaltank/ReviewProject/issues>
- 工作项操作：[`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)
- 状态标签：[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md)
- 术语与设计决策：[`docs/agents/domain.md`](docs/agents/domain.md)

`Afeedback/`、`Bfeedback/`、`EssayCourse/` 为本地资料目录；原始课程、外审反馈和处理成果保留在本地。当前仓库发布工程配置，后续按明确任务加入代码。

本机若 `gh` 不在 PATH，可从项目目录执行：

```powershell
& ./scripts/gh.ps1 repo view --json 'nameWithOwner,url'
& ./scripts/gh.ps1 issue list --state open
```

其他环境安装官方 [GitHub CLI](https://cli.github.com/) 并登录即可。`docs/agents/*.md` 可直接调整；切换任务跟踪平台或重新初始化时再运行 setup 技能。

仓库保留六个角色配置与既有模型默认值，主代理担任统筹，按通用Matt技能实际派工。配置与角色边界见多代理约定；角色配置存在不表示已经执行。

GitHub Issues和PR承接需求、依赖及执行状态；已确认的阶段成果按任务范围提交和同步。分支已推送、PR待审、main已合并分别报告。流程配置、分析样稿和真实业务交付分别验收，历史未交付内容不能因本次流程修正被标为完成。

配置字段参考 [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)；项目协作方式参考 [NewPlan](https://github.com/normaltank/NewPlan/blob/main/docs/agents/workflow.md) 和 [DataBase](https://github.com/normaltank/DataBase/blob/main/docs/agents/workflow.md)，本项目业务约定以仓库文件为准。
