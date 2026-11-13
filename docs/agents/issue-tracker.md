# Issue tracker: GitHub

需求、规格和任务记录在 <https://github.com/normaltank/ReviewProject/issues>。使用 GitHub CLI 操作。

## 文档、任务与版本

GitHub Issues是待办、依赖和执行状态的唯一台账。项目内规格是维护稿，父Issue保留同版本发布快照并链接固定提交；修订先更新维护稿、检查并提交，再同步发布快照，保留原讨论和历史入口。本地STATE、计划或交接只承担导航与当次证据，不替代任务台账。

已确认的规格和阶段成果及时进入对应任务分支；用户要求GitHub交付时，范围检查后推送并创建或更新PR。原始材料、忽略目录和其他代理的未提交成果不因一次文档维护被整体发布。

优先使用可用的GitHub工具；连接失败或能力不足时使用已认证的GitHub CLI。首次写入前确认仓库，以下CLI入口继续适用。

## 命令入口与仓库确认

在仓库内运行 `gh`。本机若未把 `gh` 加入 PATH，可用等价入口：

```powershell
& ./scripts/gh.ps1 repo view --json 'nameWithOwner,url'
& ./scripts/gh.ps1 issue list --state open
```

辅助脚本优先使用已安装的 GitHub CLI，其次使用本地 `.tools/github-cli/bin/gh.exe`。若 CLI 尚未登录，脚本可复用 Git Credential Manager 中已有的 GitHub 登录，仅在当前进程传入凭据，结束后恢复环境；不会写入令牌文件。没有可用登录时停止，并提示执行 `gh auth login`。

每次会话首次创建工作项前，执行 `gh repo view --json 'nameWithOwner'`，确认结果为 `normaltank/ReviewProject`。以下命令中的 `gh` 均可替换为 `& ./scripts/gh.ps1`。

## 常用操作

- 创建：`gh issue create --title '...' --body-file <正文文件>`。多行正文先保存到文件，保留实际换行。
- 读取：`gh issue view <number> --json 'number,title,body,labels,comments'`。
- 列表：`gh issue list --state open --json 'number,title,body,labels,comments'`，按需要增加标签或状态过滤。
- 评论：`gh issue comment <number> --body-file <正文文件>`。
- 标签：`gh issue edit <number> --add-label '<label>'` 或 `--remove-label '<label>'`。
- 关闭：先评论说明，再执行 `gh issue close <number>`；已关闭工作项也需单独评论，不能假定关闭命令会补写评论。

工作项只发布到本项目，不发布到技能来源仓库。

## 父子工作项与阻塞关系

优先使用 GitHub 原生关系；GitHub CLI 2.94 及以后支持：

- 创建子项：`gh issue create --parent <parent> --title '...' --body-file <正文文件>`。
- 关联已有子项：`gh issue edit <parent> --add-sub-issue <child>`。
- 添加阻塞：`gh issue edit <child> --add-blocked-by <blocker>`，或创建时使用 `--blocked-by`。
- 开放阻塞数：`gh api repos/normaltank/ReviewProject/issues/<number> --jq '.issue_dependencies_summary.blocked_by'`。

旧版 CLI 可通过 GitHub API 添加关系：子项接口为 `issues/<parent>/sub_issues`，字段为 `sub_issue_id`；阻塞接口为 `issues/<child>/dependencies/blocked_by`，字段为 `issue_id`。这些字段使用工作项的数字数据库 ID，可由 `gh api repos/normaltank/ReviewProject/issues/<number> --jq '.id'` 取得，不是 `#number` 或 `node_id`。

原生关系不可用时，在子项正文开头写 `Part of #<parent>` 和 `Blocked by: #<blocker>`，并在父项任务列表保留关联。工程依赖以成果已集成且相应验收通过为满足条件，Issue关闭单独记录；下游不等待最终PR合并才开始。原生阻塞状态尚未同步时，先核对集成与验收证据，再在已有授权内更新关系。

## 技能约定

- “publish to the issue tracker”：在本项目创建 GitHub Issue。
- “fetch the relevant ticket”：读取工作项完整正文、评论和标签。
- `/wayfinder` 的 map 使用 `wayfinder:map` 标签，子项使用 `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling` 或 `wayfinder:task`。这些标签在实际启用该工作流时创建。
- `/wayfinder` 从地图顺序中选取无开放阻塞、无负责人且尚未关闭的子项；认领时分配给当前开发者；解决后评论、关闭子项，并把结论和链接回填地图。

## Pull requests as a triage surface

**PRs as a request surface: no.**

这表示不把PR当作新需求收件箱；施工和文档仍通过PR交付与审查。

## 交付与关闭

规格与拆分任务按同一PR追溯。首次有效集成后建立草稿PR，最终提交的必要检查及独立审查通过后转为可审查；最终合并沿用已有授权。已集成并验证可解除下游依赖，PR未交付时不提前关闭对应任务。

关闭前记录实际版本、验证、审查及交付链接；只关闭实际已交付的范围。单次文档修正不强建父子票；已有Issue则同步。本地积压、远端任务分支、main和部署的状态分别报告，未验证的旧成果保持待处理身份。
