# ReviewProject

ReviewProject 从外审评分与 Comments 提取可追溯的评价观点，建立候选概念、评分对照和条款差异证据，支持出版社改进现有审稿 Framework。当前 0.3.0 提供本地的意见理解与复核流程：规则基线、真实本地模型候选、观点拆分补录、修改历史和候选概念并存。正式条款修订仍需专业判断、独立试评及出版社授权。

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

## 编辑一条观点

1. 在报告中查看原分、意见分区和高亮原句。“评审意见”的作者可见性默认为待核，“作者不可见”分区及派生观点保留该限制。
2. 在单条复核表单选中候选，填写修改人、理由和决定。可以拆成两条、按原文区间补录遗漏观点；高级字段支持跨句证据、理由、否定、条件、替代动作、概念 ID、评分及条款关系。拆分后各条默认待核，需分别检查语义及继承关系。
3. 应用补丁并重新打开报告。每次保存都会校验原句、位置、分区和修订号。相同补丁可安全重试，旧修订发生冲突时重新导出。

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

## 首轮范围与验证

当前支持已核实 DOCX 表型、业务 CSV 和契约 JSON。Word 样式继承造成隐藏或编号歧义、纵向合并、公式和移动修订等内容会保守拒收，不猜分、不把共享格判为空白。规则仍作为低成本对照。本地模型已经实际处理真实评语，也暴露了漏观点、理由自循环、否定误判和输出截断；候选须复核，精确引文不等于语义正确。页面可记录单篇评分关系的明确、推断或未知状态，不自动判评分矛盾。全部报告仅供可信编辑。

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
