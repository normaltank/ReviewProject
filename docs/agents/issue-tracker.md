# Issue tracker: GitHub

需求、规格和任务记录在 <https://github.com/normaltank/ReviewProject/issues>。使用 GitHub CLI 操作。

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

原生关系不可用时，在子项正文开头写 `Part of #<parent>` 和 `Blocked by: #<blocker>`，并在父项任务列表保留关联。工程依赖按[集成与验收证据](multi-agent.md#验收证据)判断：前置成果已集成且验收通过后才释放下游；Issue 是否关闭单独记录。若原生阻塞状态尚未同步，先核对验收证据并在获授权时更新关系。

## 技能约定

- “publish to the issue tracker”：在本项目创建 GitHub Issue。
- “fetch the relevant ticket”：读取工作项完整正文、评论和标签。
- `/wayfinder` 的 map 使用 `wayfinder:map` 标签，子项使用 `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling` 或 `wayfinder:task`。这些标签在实际启用该工作流时创建。
- `/wayfinder` 从地图顺序中选取无开放阻塞、无负责人且尚未关闭的子项；认领时分配给当前开发者；解决后评论、关闭子项，并把结论和链接回填地图。

## Pull requests as a triage surface

**PRs as a request surface: no.**
