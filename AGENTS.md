# ReviewProject

处理需求、规格、任务拆分、实现或代码审查时，先读 `docs/agents/workflow.md`，按当前任务选择对应工程技能。

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
