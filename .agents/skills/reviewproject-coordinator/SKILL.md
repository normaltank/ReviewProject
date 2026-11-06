---
name: reviewproject-coordinator
description: 统筹 ReviewProject 仓库的开发、维护、规格与任务拆分、审查交付，自动安排当前任务的临时子代理。用于本项目工程工作；无关答疑与语言写作不适用。
---

# ReviewProject coordinator

主代理作为唯一用户对接统筹。读取仓库 [AGENTS.md](../../../AGENTS.md)、[工作流](../../../docs/agents/workflow.md) 和 [多代理协作](../../../docs/agents/multi-agent.md)，按当前任务分流并执行相应阶段。

沿用已有确认；重大未决业务问题集中呈交具体方案，常规技术选择及已授权步骤自动推进。按角色和交接字段实际派工，以成果及验证证据验收，达到验收点后汇报并停止。

本技能直接执行项目阶段方法，不自动触发全局 explicit-only 的 `to-spec`、`to-tickets`、`triage`、`implement`、`implement-spec`、`ask-matt` 等技能。用户显式调用原技能时读取其正文并保留其确认节点。
