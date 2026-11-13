# ReviewProject

处理本项目开发、维护、规格、任务拆分或审查交付时，先读 [Matt工作流](docs/agents/workflow.md)，直接读取并使用已安装的通用Matt技能，沿用OpenSource和DataBase的接入方式。主代理负责统筹，不另设项目专属技能。

## 唯一统筹入口

主代理默认担任用户唯一对接的统筹。用户已明确授权：在当前任务范围内自动委派临时子代理，无需用户逐次点技能、创建聊天或重复授权。统筹负责分流、集中澄清业务决定、派工、汇总、证据验收，以及获授权的对外发布和远端变更。

子代理向统筹交接；需要用户决定或发现范围变化时回报统筹，由统筹统一处理。派工与角色边界见 [多代理协作](docs/agents/multi-agent.md)。自动委派授权以当前任务为界，不扩大为发布、推送、合并、部署或数据使用授权。

## Subagent defaults

需要调用子代理时，默认显式设置 `model="gpt-6.1-sol"`、`reasoning_effort="high"`。用户为具体任务指定的参数优先。

当前协作接口覆盖模型参数时使用 `fork_turns="none"`，并在子任务说明中提供必要的目标、上下文、文件位置和验收要求。

## Agent skills

### Issue tracker

需求、规格和任务使用 `normaltank/ReviewProject` 的 GitHub Issues。读取或发布工作项前，见 `docs/agents/issue-tracker.md`。

### Triage labels

使用五个默认状态标签；分类及状态含义见 `docs/agents/triage-labels.md`。

### Domain docs

采用 single-context：根目录 `GLOSSARY.md` 和 `docs/adr/`。探索项目或提出设计变更前，按 `docs/agents/domain.md` 读取相关文档。
