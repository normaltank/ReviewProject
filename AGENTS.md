# ReviewProject

处理本项目开发、维护、规格、任务拆分或审查交付时，先读 [工作流](docs/agents/workflow.md)，使用项目级 `reviewproject-coordinator` 技能承接对应阶段。

接手业务原型时，按本地 `CODEX_PROJECT_PLAN.md` 和[交接状态](docs/STATE.md)核对阶段与材料。变更导入、权限、观点或补丁时读[数据与标注契约](docs/DATA_AND_ANNOTATION.md)，并运行 `python -m unittest discover -s tests -v`。评估新组件时先读[复用实测](docs/REUSE_DECISIONS.md)。真实原件与派生产物限本地可信编辑工作区，仓库测试使用合成输入。

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
