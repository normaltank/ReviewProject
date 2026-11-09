# ReviewProject

ReviewProject 从外审评分与 Comments 提取可追溯的评价观点，组织多来源证据、原分与候选规则，供可信编辑查证、纠正并保存条款审核决定。首轮三票已本地集成验收；用户本人体验、专业理解可靠性及正式条款效果分别验证。

从[本轮试跑与试用索引](work/framework-review-20261109/README.md)进入，或直接打开[本地模型条款审核包](work/framework-review-20261109/model-batch/report.html)。报告含真实受限材料，只供本机可信编辑。当前模型提案没有生成新的改法，保留原规则仅作对照；真实错误与未知项见索引及[交接状态](docs/STATE.md)。无需重新推理即可查看已有结果。

## 从本机窗口开始

在已配置的本机双击根目录 `start-review.cmd`，或在项目根目录运行：

```powershell
python -m reviewproto desktop
```

入口使用 Python 标准库 Tkinter，不启动可写 HTTP 服务。其他机器仍需 Python 3.12、Tkinter 及 `requirements.txt`；可选模型另行准备，窗口不会下载安装或回退到云模型。

### 审核本轮小批条款包

公开规格为 [Issue #1](https://github.com/normaltank/ReviewProject/issues/1)，实施顺序为 [T1 #2](https://github.com/normaltank/ReviewProject/issues/2) → [T2 #3](https://github.com/normaltank/ReviewProject/issues/3) → [T3 #4](https://github.com/normaltank/ReviewProject/issues/4)。三票代码及三项独立审查发现已本地集成验收；代码尚未推送或创建PR，准确版本、验证与Issue状态见 [STATE](docs/STATE.md)。

1. 点“选择审核包”，选本轮 `model-batch` 等含 `batch.sqlite3` 的目录，再点“打开审核页”。查看原话、原分、规则出处，以及原规则的适用条件、例外、要求强度与来源、未知项和检查项。未列出不代表不存在；规则候选仍未获正式授权。
2. 需要纠正观点时，从包内链接进入原观点表单；在桌面包来源下拉选择相应记录，点“打开所选原来源”，再用上方“选择下载补丁并应用”保存原来源修正。
3. 同ID纠正后点“刷新包”；拆分或补录后用“重选观点并刷新包”，按来源、状态、原话和父项/替换关系明确勾选，再重开审核页。只列原授权普通分区、原运行及手工观点，明确重选后切为 `selected` 探索视图，待核不会变成已确认。旧决定需复核；旧建议不自动转绑新子项，引用消失的问题只读保留在历史，通过既有 `batch-discover` 重新分析后再作新决定。
4. 比较仍有效的问题及具体方案，分别选择个案决定或Framework候选提案审核。个案下拉指向审稿记录，不推定稿件身份；修改须选具体方案。填写理由、加入队列，点“下载决定补丁”。保留原规则对照的B支持/反对关系未判，不能据此当成已核实依据。
5. 回到桌面点“应用下载决定”，再“恢复审核包并重开”核对。只有通过应用校验才保存，下载次数不代表成功；候选提案处理仍是草案讨论，未发布正式标准。
6. 体验计时默认“代理演练”；本人首次体验时明确切换“用户本人体验”，再开始、暂停、继续或结束。页面隐藏会暂停；离开本页纠正观点的工时需另记。结束后下载独立计时JSON，只有包绑定、方法、执行者类型、用时与尝试数，不含身份、原文或完整状态。角色是自报，代理演练不代表专业人工收益。

准备包和本地发现仍使用既有CLI。同ID刷新可运行 `python -m reviewproto batch-refresh --workspace work/batch-review`；观点集合改变时使用桌面普通重选确认，无需手写JSON或文本偏移。页面为静态快照，源变化后应恢复、刷新再重开；不能安全刷新时显示待处理。

### 导入和编辑单来源

1. 首次导入前选择来源声明和 `docx / csv / json` 类型，再选材料及父目录，入口自动创建专用新子目录。来源/类型选择只配置下一次新导入；已有工作区以顶部显示的保存来源为准。
2. 选择“打开已有工作区”，指向含 `review.sqlite3` 的专用目录；入口核验冻结来源并重建当前报告，不改变已保存业务修订。再点“打开报告”。
3. 在报告中拖选原文，补录独立观点、追加跨句证据，或将单段观点拆分。普通表单可填写否定、理由、条件及替代动作；每项引用证据并区分明确、推断和未知，条件的具体含义不明时保留 unknown。
4. 选中候选即加入本页草稿队列；下载包含队列中的全部草稿。将无意加入的项“移出草稿队列”后再下载，这不会删除已保存记录。填写修改人及理由，下载补丁；回到窗口“选择下载补丁并应用”，然后重新打开报告核对保存修订。仅下载并未保存到数据库，未下载草稿关闭或刷新会丢失。
5. 需要模型时显式启动本项目已安装模型，选择一个普通分区，抽取并导入；默认仍为联合 v3，结果可能 partial/failed，接收不代表语义正确。操作完成后点“停止本窗口启动的模型”，再关闭窗口。关闭空闲窗口不会自动停止模型；误关后由操作员用项目停止脚本核对自有实例。

### 既往开发案例

[R018修订案例](work/revision-case-20261108/case.html)及[来源、失败与核验索引](work/revision-case-20261108/README.md)、[五项原稿回核草稿](work/r018-manuscript-check/evidence.html)及[核验索引](work/r018-manuscript-check/README.md)保留为历史开发回放，不是本轮默认入口。按用户已确认口径，先视本地匹配稿为老师所评论文推进工程；这不是送审版本确证。作者已经写有不足或未来计划不自动抵消老师要求，仍需核对老师所指对象、条件和必要证据。

此前[可信编辑演练](work/mvp-20261108/README.md)、[条件/否定修正](work/mvp-20261108/real-workspaces/staged-01/report.html#candidate-agent-staged-01-target)及[主张—理由修正](work/mvp-20261108/real-workspaces/staged-03/report.html#candidate-agent-staged-03-target)同样属于已知真实副本上的代理开发演练，仍待专业复核。全部页面沿用来源权限，不能向作者或外部直接分享；尚未测得专业人工成本或独立准确率。

## 跑一份合成审稿表

在项目根目录使用 Python 3.12。可在虚拟环境中安装一项直接依赖。当前工作机的系统 Python 已有该版本。

```powershell
python -m pip install -r requirements.txt
python experiments/make_demo.py work/demo-input.docx
python -m reviewproto run work/demo-input.docx --workspace work/demo --origin synthetic
Invoke-Item .\work\demo\report.html
```

每份表使用专用空目录或该表已有的工作目录。真实样本用 `--origin original_review`。冻结原件、数据库、HTML、模型响应和补丁都只供可信编辑使用；放在 `work/` 内，由操作系统限制访问。

业务 CSV 可直接输入：追加 `--format csv`，无需转 Word。当前 CSV 适配已核实的 6 行×6 列单份表单；通用系统导出可转换为[明确的 JSON 契约](docs/DATA_AND_ANNOTATION.md)，使用 `--format json`。无法安全识别的格式会拒收，留待人工核对。

## 使用本机已准备的真实模型

本机已在 `.tools/semantic-env` 安装可选依赖，准备了官方 Qwen3-4B GGUF 和 llama.cpp Vulkan。抽取只向 `127.0.0.1` 发请求，禁用代理与重定向，没有云模型回退。首次抽取只传所选意见分区的文本，不传数值评分或表单身份字段。评语本身仍可能包含身份信息，全部产物留在可信编辑工作区。

```powershell
& .\scripts\start-local-model.ps1
# 服务就绪后处理已导入的工作区；run-id 每次用新值。
& .\.tools\semantic-env\Scripts\python.exe experiments/extract_local.py --workspace work/demo --run-id local-01
python -m reviewproto ingest-candidates work/demo/model-artifacts/local-01/candidates.json --workspace work/demo
Invoke-Item .\work\demo\report.html
& .\scripts\stop-local-model.ps1
```

其他机器先在隔离环境安装 `requirements-model.txt`；权重、运行包、指纹与授权见[复用记录](docs/REUSE_DECISIONS.md)。启动脚本只复用已安装且指纹匹配的文件，不自动下载。可不启动模型，直接用规则候选开展人工复核。模型截断、引文不符和超长单段会留下失败记录；导入失败产物用于显示诊断，不代表抽取成功。

抽取默认仍用 `--protocol v3`。显式 `--protocol v4` 可试验区分 `either_or` 与 `conditional_branches`；未说明的选择条件保留 unknown，不把两路改成都必须完成。四份新真实材料的同模型对照未证实 v4 恢复关键分支，所以没有将它设为默认；共享的 Flash 入口也仍用 v3。[本轮试验与失败索引](work/conditional-20261108/README.md)保留真实响应、诊断和修正，不必重跑模型即可查看。

当前可直接复核[双路条件观点](work/conditional-20261108/workspaces/conditional-01/report.html#candidate-agent-conditional-01-target)、[条件未说明的二择一](work/conditional-20261108/workspaces/conditional-02/report.html#candidate-agent-conditional-02-target)和[短评拆分结果](work/conditional-20261108/workspaces/conditional-04/report.html#candidate-agent-conditional-04-coverage)。补录由 AI 代理沿原文完成、全部 needs_review，专业编辑可用既有表单和计时入口继续核对。它们是可信编辑材料，不能向作者或外部服务直接转发。

可选 `experiments/extract_staged.py` 先召回原句，再用原文线索和召回跨度安排局部 v4 复核；线索和召回均单独保存，只有第二步真实模型输出进入候选。四份新材料及两份已知回归的试验尚未证明整体更好，当前默认入口仍是上面的联合 v3。查看[本轮结果及失败索引](work/staged-20261108/README.md)、[新条件观点](work/staged-20261108/workspaces/staged-01/report.html#candidate-agent-staged-01-target)或[主张—理由复核页](work/staged-20261108/workspaces/staged-03/report.html#candidate-agent-staged-03-target)，无需重复推理。

需要自行试用时，先按前文启动本机模型，选择已导入工作区的普通区 ID 和全新 run-id：

```powershell
& .\.tools\semantic-env\Scripts\python.exe experiments/extract_staged.py --workspace work/demo --section section-1 --run-id staged-demo-01 --context-chars 1000 --stage2-max-output-tokens 8192
python -m reviewproto ingest-candidates work/demo/model-artifacts/staged-demo-01/candidates.json --workspace work/demo
```

它默认每记录至多12请求、4次局部复核。第一阶段窗口固定600码点，第二阶段完整上下文可用 `--context-chars 600|1000` 单独指定，未指定时仍为600；上面的1000是显式实验。完整闭包超过所选上限、预算未处理及失败留在 `queue.json / coverage.json`。扩容不剪碎原文，也可能挤出其他上下文的复核预算；处理覆盖与候选结果分开，空候选伴错误明确失败。队列处理完成只表示模型看过，不能解释为观点已被理解。试用完按前文停止模型。

1000模式已在[六份已知材料回归](work/context-20261108/README.md)实际运行；三个先前未送达的目标已完整送达，条件、否定和替代关系仍需人工纠正。原有修正保持；新候选会令A历史对照保守标为需重新核验。可直接打开[续接复核页](work/context-20261108/workspaces/staged-01/report.html#candidate-agent-staged-01-target)，无需重跑模型。此次不是新独立测试集，也未证明整体语义改善。

## 获授权的 Flash 对照

可选 `experiments/deepseek_trial.py` 固定使用官方当前别名 `deepseek-flash`，不使用 Pro。普通工作区仍可完全本地运行。外部试验必须有逐项文本/来源哈希绑定的计划及明确用户授权；只有密钥不足以授权材料外发。作者不可见区禁止进入此入口，数值评分、身份元数据、原稿及 A 材料不传给模型。每批共享调用次数和费用账本，先预留保守费用，未知用量会停止后续调用；token 费用估算不冒充账户实际扣费。

```powershell
# 仅首次配置：交互输入隐藏，加密保存到本机当前Windows用户的DPAPI文件。
& .\scripts\set-deepseek-key.ps1
# 本轮已获授权的计划可先检查；此命令不解密密钥、不调用API。
& .\scripts\run-deepseek-trial.ps1 -Plan work/trial-20261108/outbound-plan.json -Approval work/trial-20261108/approval.json -Item trial-06-short -CheckOnly
```

实际运行时去掉 `-CheckOnly`，用新的 `-RunId`，再按本地模型同样的 `ingest-candidates` 导入结果。本轮已有结果直接打开 STATE 中的链接，无需付费重跑。批准须绑定原预算账本的绝对路径与身份；复制计划不能重置次数或费用。密钥仅在本次进程树环境传递，退出后恢复原环境；不写入仓库、请求日志或命令行。

本机 DSH 已通过 `python experiments/dsh_bridge.py --mock` 验证隔离 profile 的调用往返，默认执行为不启动进程的 dry-run。此入口只允许内置合成数据和本机 mock，禁用模型工具、额外会话上传及外连；真实审稿抽取本轮采用上面的直接 API。DSH mock 不代表真实模型效果。

## 编辑一条观点

1. 在报告中查看原分、意见分区和高亮原句。“评审意见”的作者可见性默认为待核，“作者不可见”分区及派生观点保留该限制。
2. 在单条复核表单选中候选，填写修改人、理由和决定。拖选原文可拆分、补录或追加证据；普通表单支持跨句理由、否定、条件、替代动作及各自证据引用。拆分后各条默认待核，分别检查语义及继承关系。概念 ID、评分及条款关系保留高级 JSON/操作员入口，不自动确认。
3. 从草稿队列下载补丁，经本机窗口或下列 CLI 应用，再重新打开报告。每次保存校验原句、位置、分区和修订号。相同补丁可安全重试，旧修订冲突时重新导出。被其他字段引用的证据不能直接移除；移除未引用证据后索引自动重排。

```powershell
python -m reviewproto apply work/demo/edit-01.json --workspace work/demo
python -m reviewproto run work/demo-input.docx --workspace work/demo --origin synthetic
Invoke-Item .\work\demo\report.html
```

浏览器无法将补丁另存到受控位置时，可在工作目录内直接生成补丁，再用文本编辑器填写。将下面的 `ID` 换成报告中的候选 ID，使用新的文件名即可保留草稿。

```powershell
python -m reviewproto review --workspace work/demo --candidate ID --output work/demo/edit-02.json
python -m reviewproto apply work/demo/edit-02.json --workspace work/demo
```

概念通过补丁顶层 `concepts` 保存稳定 ID、定义、例子、反例、边界与待确认状态；观点用 `concept_ids` 引用。A 来源使用 `ingest-clauses` 导入，只能成为待核候选，不具有正式标准效力。具体格式见[数据契约](docs/DATA_AND_ANNOTATION.md)。

模型每次运行追加候选和原始输出，不能覆盖人工决定。相同运行重放幂等；同一运行 ID 改内容会拒收。基线、不同模型运行和当前已确认观点分别显示，不相加充当业务意见总数。若生成报告中断，运行 `python -m reviewproto recover --workspace work/demo` 重建可读文件。更换送审版本另建工作目录。

页面新增复核成本记录：填写修改人、选择自报角色与对照方法后显式开始计时，可暂停、继续、结束并下载独立旁车 JSON。隐藏标签会暂停，返回后手动继续；未下载的记录刷新会丢失。计时不会改变补丁，输入/点击次数仅为尝试计数，不表示修改已应用。只有真实编辑完成任务后才能据此记录人工时间，自动化演练或代理计时均不能代替专业人工成本。

## 查看 A 规则并讨论修订

本机已经将首讲课程整理为 24 条候选规则，涵盖已有 13 个维度的局部内容；每条包含适用范围、例外、未知项、检查提示与逐字来源。PPT 原生文字和未听校机器转写分别标记。它们没有正式标准效力、评分锚点或统一合格线。

直接打开[综述类型与证据责任讨论页](work/framework-20261108/b-workspaces-final/trial-02-long/report.html#proposal-P-A01-METHOD-TYPE-01)或[局限与替代动作讨论页](work/framework-20261108/b-workspaces-final/trial-03-praise_and_revision/report.html#proposal-P-A01-LIMITATION-SCOPE-01)。两页含真实评语，仅供本机可信编辑；[本轮索引](work/framework-20261108/README.md)记录来源、开发回放和限制。

将本地规则包接入另一份已导入的审稿工作区：

```powershell
python -m reviewproto ingest-framework work/framework-20261108/a-package/book.json --workspace work/demo
# 将 CANDIDATE_ID 替换为页面中需要对照的观点 ID。
python -m reviewproto framework-template --workspace work/demo --candidate CANDIDATE_ID --rule A01-R018 --output work/demo/framework-edit-01.json
# 填写 actor、reason、rationale 及关系；也可按数据契约填写 proposals。
python -m reviewproto apply-framework-review work/demo/framework-edit-01.json --workspace work/demo
Invoke-Item .\work\demo\report.html
```

该入口全程本地，不调用模型。包导入会核验来源文件字节、引文及位置，并冻结规则版本与来源；来源缺失可从数据库恢复，已改动文件会拒绝覆盖。草案保存修改前后、支持与反例、验证计划和回退条件，不改原分或正式标准。草案增补单独标为编辑提案，原引文只证明修改前来源。任何观点新增、修正或撤销后，既有对照与草案会标 `needs_revalidation`。当前通过 JSON 草稿修改，页面用于查看与回溯，尚无规则图形编辑器。`current` 只表示仍对应当前观点快照，不代表专业认可。

## 首轮范围与验证

当前支持已核实 DOCX 表型、业务 CSV 和契约 JSON。Word 样式继承造成隐藏或编号歧义、纵向合并、公式和移动修订等内容会保守拒收，不猜分、不把共享格判为空白。规则仍作为低成本对照。本地模型已经实际处理真实评语，也暴露了漏观点、理由自循环、否定误判和输出截断；候选须复核，精确引文不等于语义正确。页面可记录单篇评分关系的明确、推断或未知状态，不自动判评分矛盾。全部报告仅供可信编辑。

试用MVP面向本机可信编辑。入口与高频复核操作已可运行，两份已知真实材料完成普通表单修正、保存及旧来源/模型产物重放；这些是开发演练，不是独立业务测试。复杂 A 修改仍由操作员经 CLI/JSON 预导入，尚无规则图形编辑器、多用户认证或安全作者端。下一步让专业编辑完成小批真实任务并计时，按阻断问题返修；模型实验不代替这项验收。工程可运行、专业理解可靠性和 Framework 改善效果分别核验。

- [交接状态、真实样本入口与限制](docs/STATE.md)
- [原文定位、评分、权限和复核字段](docs/DATA_AND_ANNOTATION.md)
- [组件实测、对照和复跑方法](docs/REUSE_DECISIONS.md)

```powershell
python -m unittest discover -s tests -v
python experiments/audit_inputs.py Bfeedback
```

第二条命令只统计本地文件和模板线索。浏览器往返测试还需要本机 Playwright 及 Chromium，可将 `REVIEW_BROWSER_BINARY` 设为浏览器可执行文件的完整路径后运行同一测试命令。

## 工程工作流

在本项目中直接用自然语言向主代理描述目标即可；主代理是唯一对接统筹，在任务范围内自动分派临时子代理并汇总验收。重大业务决定由统筹集中确认，已有确认沿用。

- 工作流：[`docs/agents/workflow.md`](docs/agents/workflow.md)
- 多代理交接与验收：[`docs/agents/multi-agent.md`](docs/agents/multi-agent.md)
- 自动统筹技能：[`.agents/skills/reviewproject-coordinator/SKILL.md`](.agents/skills/reviewproject-coordinator/SKILL.md)
- 原生角色：[`.codex/agents/`](.codex/agents/)；默认设置：[`.codex/config.toml`](.codex/config.toml)
- 需求与任务：<https://github.com/normaltank/ReviewProject/issues>
- 工作项操作：[`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)
- 状态标签：[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md)
- 术语与设计决策：[`docs/agents/domain.md`](docs/agents/domain.md)

`Afeedback/`、`Bfeedback/`、`EssayCourse/` 及 `work/` 为本地资料与工作目录。用户提供的计划书和 Word 研究报告含材料索引，保存在原位置并由 Git 忽略。

本机若 `gh` 不在 PATH，可从项目目录执行：

```powershell
& ./scripts/gh.ps1 repo view --json 'nameWithOwner,url'
& ./scripts/gh.ps1 issue list --state open
```

其他环境安装官方 [GitHub CLI](https://cli.github.com/) 并登录即可。`docs/agents/*.md` 可直接调整；切换任务跟踪平台或重新初始化时再运行 setup 技能。

仓库提供可发现的自动技能及六个角色配置；主代理本身担任统筹。原生发现是否已生效需在支持该配置的 Codex 新会话或重启后核实。当前接口缺少角色类型参数时，统筹读取角色指令后通过临时子代理工具派工，显式传入模型与思考强度。配置不是自运行引擎，也不创建常驻聊天或后台服务。

首轮业务原型按一条可独立验收的链路交付，实际运行与审查记录见交接状态。项目自动技能承载阶段方法；全局 explicit-only 技能仍由用户显式调用。

配置字段参考 [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)；项目协作方式参考 [NewPlan](https://github.com/normaltank/NewPlan/blob/main/docs/agents/workflow.md) 和 [DataBase](https://github.com/normaltank/DataBase/blob/main/docs/agents/workflow.md)，本项目业务约定以仓库文件为准。
