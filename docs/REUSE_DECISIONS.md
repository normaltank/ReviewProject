# 首轮复用决策 · 2026-11-06

| 环节 | 实际核验与决定 |
| --- | --- |
| 原生 DOCX | **薄封装适配**。工作机已有 python-docx 1.2.0，MIT。已通过原生合并单元格、分数原字符串、空段和段落定位的合成测试及三份真实表回放。用其读取 Word 原生段落和格内文本，物理单元格取序避免横向合并重复计数。只给已经核实的表型补验证与权限约束。运行时直接依赖固定于 `requirements.txt`。[API](https://python-docx.readthedocs.io/en/latest/api/table.html) · [版本与许可](https://pypi.org/project/python-docx/1.2.0/) |
| 持久化与复核 | **直接复用** Python 标准库 SQLite 事务、JSON 和浏览器本地 HTML。薄封装负责精确证据、修订冲突和补丁往返。工作机未安装 Label Studio。本轮仅核对其预标注导入文档，未部署或向其提供材料；当独立多标注者协作成为实际需要时，另验隔离、结果回填和维护成本。[Label Studio 预标注](https://labelstud.io/guide/predictions.html) |
| LangExtract | **暂缓进入运行链路**。隔离试装并实跑 1.7.1，Apache-2.0。定位和本地展示可复用，业务输入需要额外的来源、字面匹配、权限和人工版本约束。未发现直接可用且经验证的本地中文指令模型，外部模型也未经授权。本轮抽取使用段落与窄规则基线。[官方仓库](https://github.com/google/langextract) · [实测版本](https://pypi.org/project/langextract/1.7.1/) |
| 维度与条款 | **仅借鉴方法**。沿用 R1 中观点与依据配对、多轴标注、版本绑定的设计。概念归纳、评分校准和 AutoRubric 需等待经核观点、正式 A 条款和独立样本，本轮未部署。 |

## LangExtract 与简单切分的实测

脚本只内置十个新造中文样例，固定供给器返回预先写好的 JSON。分别运行默认与 Unicode 分词器，并用原段、简单分句和逐字查找作对照。运行时禁止 socket 连接，观测到 0 次连接尝试、0 次模型请求。原始输出保存在本地 `work/langextract-probe/results.json`。这项实验检验了工具如何定位给定答案，模型的语义能力仍待验证。

| 样例 ID | 观察到的输出 | 主程序采用的处理 |
| --- | --- | --- |
| `chinese_substring` | 默认分词未对齐中文子串。Unicode 分词定位到 `[4,8)`。 | 所有观点保存分区与 Unicode 区间。 |
| `repeat_two / repeat_one` | 两条重复夹具按序得到 `[0,5)`、`[6,11)`；只有一条答案时工具给出首处，原文实际有两处。 | 从已知段落生成位置，人工校正按指定区间核对。 |
| `newline` | 关闭模糊和部分匹配后，含空格的引文对含换行的原文仍返回 `match_exact` 和 `[0,8)`，字面校验为假。 | 强制检查冻结文本的逐字切片。 |
| `invented` 与坏 JSON | 不存在的引文返回空位置；默认设置对坏 JSON 留下 0 条结果，严格解析抛出 `ResolverParsingError`。 | 未来接入时保留解析失败与无位置状态，区分“未提出观点”和“提取失败”。 |
| `conditional / negation / non_contiguous / paragraphs / emoji` | 原句可定位；两个 emoji 后的原句区间为 `[2,9)`。单条工具对象只带一个区间，多段关系需单独表达。 | 原段作为上下文，证据可以有多段。窄规则产生的两支仍待编辑确认；其余语义保留未知。 |

另外用该包的 `visualize` 在合成输入上生成过本地 HTML；未在该展示组件中验证人工修改往返或权限隔离。软件包安装在独立 Python 3.12.10 环境，本次共解析 58 个发行包，含 pip 的临时环境约 211 MB。LangExtract wheel 的 SHA-256 为 `0b075b90c3f6ecd0504ab117e2c809a301c27aa408c3a85f70cfe5ff1fb32bd8`。这些是代码依赖的安装情况，模型和数据的授权需分别核实。

## 复跑与重评

从仓库根目录在单独环境复跑可选实验。依赖安装需要公开包源，运行脚本只处理内置合成样本。日常使用原型只需根目录的 `requirements.txt`。

```powershell
python -m venv .tools/langextract-probe
& .\.tools\langextract-probe\Scripts\python.exe -m pip install -r experiments/langextract-requirements.txt
& .\.tools\langextract-probe\Scripts\python.exe experiments/probe_langextract.py
```

获得可用且获准的模型后，另建按稿件分组、未用于改规则的独立样本。测量完整观点召回、精确定位、条件保真、强度误判，以及每条通过验收观点的人工修正时间和成本。本轮仅验证技术往返，编辑实际耗时、提取准确率及业务收益尚无测量值。
