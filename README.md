# ReviewProject

审稿评价框架研究项目。工程工作以 GitHub Issues 记录需求、规格和任务，采用 Matt Pocock skills 的阶段工作流。

在本项目中直接用自然语言向主代理描述目标即可；主代理是唯一对接统筹，在任务范围内自动分派临时子代理并汇总验收。重大业务决定由统筹集中确认，已有确认沿用。

- 工作流：[`docs/agents/workflow.md`](docs/agents/workflow.md)
- 多代理交接与验收：[`docs/agents/multi-agent.md`](docs/agents/multi-agent.md)
- 自动统筹技能：[`.agents/skills/reviewproject-coordinator/SKILL.md`](.agents/skills/reviewproject-coordinator/SKILL.md)
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

仓库提供可发现的自动技能及六个角色配置；主代理本身担任统筹。原生发现是否已生效需在支持该配置的 Codex 新会话或重启后核实。当前接口缺少角色类型参数时，统筹读取角色指令后通过临时子代理工具派工，显式传入模型与思考强度。配置不是自运行引擎，也不创建常驻聊天或后台服务。

本次建设交付工作流文档、角色和技能配置；格式检查或小型委派验收只证明各自覆盖的配置与调用行为。真实多工单业务的实施、集成和整体验收须在后续获授权任务中留证，不能据此宣称已端到端验证。项目自动技能承载阶段方法；全局 explicit-only 技能仍由用户显式调用。

配置字段参考 [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)；项目协作方式参考 [NewPlan](https://github.com/normaltank/NewPlan/blob/main/docs/agents/workflow.md) 和 [DataBase](https://github.com/normaltank/DataBase/blob/main/docs/agents/workflow.md)，本项目业务约定以仓库文件为准。
