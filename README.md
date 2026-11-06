# ReviewProject

ReviewProject 用外审分项评分与 Comments 建立出版社改进审稿条款所需的证据。首轮交付本地编辑复核工具：保留外审原件和原分，逐段定位意见，记录条件与替代动作，允许编辑修正后重跑。后续可用已核验观点对照 A 的现行条款，结合反例和独立试评提出修订，由出版社授权人员决定发布。

## 跑一份合成审稿表

在项目根目录使用 Python 3.12。可在虚拟环境中安装一项直接依赖。当前工作机的系统 Python 已有该版本。

```powershell
python -m pip install -r requirements.txt
python experiments/make_demo.py work/demo-input.docx
python -m reviewproto run work/demo-input.docx --workspace work/demo --origin synthetic
Invoke-Item .\work\demo\report.html
```

每份表使用新建的专用空目录或该表已有的工作目录。处理获准的真实样本时，将输入换成实际 DOCX 路径，使用 `--origin original_review`。冻结原件、数据库、HTML 和补丁都只供可信编辑使用。建议放在 `work/` 内，并由操作系统限制人员访问。工具会在专用工作目录写入仅对该目录生效的 Git 忽略规则。

## 编辑一条观点

1. 在报告中查看原分、意见分区和高亮原句。“评审意见”的作者可见性默认为待核，“作者不可见”分区及派生观点保留该限制。
2. 在单条复核表单选中候选，核对前后文，填入修改人、理由和决定。可修改对象、动作和判断方向，高级字段可改条件、互选分支及引文。生成补丁时将文件另存到该工作目录，例如 `work/demo/edit-01.json`。
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

若生成报告时中断，运行 `python -m reviewproto recover --workspace work/demo` 重建可读文件。保留冻结原件和 SQLite 数据库。换送审版本或抽取器版本时另建工作目录，并保留原目录供审计。

## 首轮范围与验证

当前支持已核实的单表四评分、双意见分区 DOCX。遇到 Word 原生公式、移动修订或无法映射的内容时会拒收并记录原因。重新使用历史工作目录时，先成功运行 `run` 或 `recover`，再打开报告。提取以完整段落建立待复核候选，再为少数明确的成对条件句标出两路证据。跨段指代、一般语义判断、评分理由及论文事实仍需编辑核对。所有报告均为内部版。

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
