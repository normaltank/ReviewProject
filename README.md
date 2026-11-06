# ReviewProject

审稿评价框架研究项目。工程工作以 GitHub Issues 记录需求、规格和任务，采用 Matt Pocock skills 的阶段工作流。

- 工作流：[`docs/agents/workflow.md`](docs/agents/workflow.md)
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
