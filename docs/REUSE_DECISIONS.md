# 复用决策 · 2026-11-08

0.3.0 将先前隔离探针推进到真实本地模型调用。下面先给当前选择，后面的十例固定答案探针保留为历史定位证据；它们不是模型准确率实验。更完整的方法研究见 [TECHNICAL_LITERATURE_REVIEW.md](TECHNICAL_LITERATURE_REVIEW.md)，本轮没有重新开展大综述或安装多个候选平台。

| 环节 | 实际核验与决定 |
| --- | --- |
| 输入 | **保留 python-docx 薄适配，优先结构化输入**。1.2.0，MIT；CSV 用标准库 csv，JSON 用明确契约。已核 CSV 是 6×6 单份表单，不再把 5 行当 5 条记录。Word 样式继承及纵向合并歧义拒收，特殊表型继续人工检查。无需建设通用 Word 解析器。[python-docx API](https://python-docx.readthedocs.io/en/latest/api/table.html) · [版本与许可](https://pypi.org/project/python-docx/1.2.0/) |
| 持久化与复核 | **直接复用** Python 标准库 SQLite 事务、JSON 和浏览器本地 HTML。薄封装负责精确证据、修订冲突和补丁往返。工作机未安装 Label Studio。本轮仅核对其预标注导入文档，未部署或向其提供材料；当独立多标注者协作成为实际需要时，另验隔离、结果回填和维护成本。[Label Studio 预标注](https://labelstud.io/guide/predictions.html) |
| LangExtract | **采用抽取与对齐接口，增加严格证据适配**。1.7.1，Apache-2.0；使用显式本地 BaseLanguageModel、UnicodeTokenizer、禁模糊匹配、严格解析。候选必须通过冻结原文切片检查；工具未对齐但原文唯一逐字匹配时另行标记回指，重复或引文改写继续拒绝。真实调用已运行，不把定位通过当理解正确。[官方仓库](https://github.com/google/langextract) · [实测版本](https://pypi.org/project/langextract/1.7.1/) |
| 本地模型 | **一个主方案**：官方 Qwen3-4B Q4_K_M + llama.cpp b12110 Vulkan。无需 Torch，不调用付费或外部模型；只监听本机。选它是当前显存与可运行性取舍，不是语义最优结论。已实际暴露能力限制，保留段落/窄规则作为唯一简单对照。 |
| 概念与条款 | **出版社专属薄逻辑**：稳定概念 ID、定义/例子/反例/边界/待确认状态、人工历史、候选 A 来源与关联；不做自动维度批准或自动标准发布。尚无证据支持引入向量库、知识图谱、BERTopic 或自动 Rubric 优化器。先以当前人工复核成本和条件保真问题决定是否增加组件。 |

## 本地模型与复现边界

权重来自官方 [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/bc640142c66e1fdd12af0bd68f40445458f3869b)，Apache-2.0，文件 `Qwen3-4B-Q4_K_M.gguf`，2,497,280,256 字节，SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`。运行包为官方 [llama.cpp b12110](https://github.com/ggml-org/llama.cpp/releases/tag/b12110) Windows Vulkan，代码 MIT，commit `cd959bae9`；37,661,146 字节 ZIP 的 SHA-256 为 `9732a5e48887ca54d0bfe4af4324dc85fd56cd8cda19b52df3542fa6ebe6874f`。官方元数据、许可副本及下载核验在本地 `work/development-20261107/runtime/`。

依赖安装到 `.tools/semantic-env`，锁定列表为 `requirements-model.txt` 及其引用。核心 CLI 不导入 LangExtract。真实调用由 `experiments/extract_local.py` 执行；只允许字面 `http://127.0.0.1:<port>/v1`，禁环境代理、重定向及云回退。运行脚本 `scripts/start-local-model.ps1`、`stop-local-model.ps1` 检查端口、权重指纹、服务身份和 PID 创建时间，不接管外来实例。服务需手动启停，没有安装开机服务。

曾按 pinned README 使用直接 `response_format.schema`，实际被静默忽略。查官方实现后改为 `response_format.json_schema.schema` 并真实验证；失败请求与响应仍在 runtime。JSON 约束只保证结构。16K 上下文已用 8,911 prompt tokens 的合成容量探针验证接收，但这不证明长评语生成与理解质量。

真实探索的开发样本不是独立留出集。CSV v1 接收 19 个模型候选，38 个最终引文逐字相等，其中原工具 20 项无 interval，靠唯一字面回指。开发诊断发现遗漏直接评价、8 项理由复述主张、建议误作否定、概念边界模板化。v2 改提示后为 18 个候选，自循环理由反而 11 项，关键遗漏和否定错误仍在；不能以“提示已修改”宣称修复。

已知条件开发例的模型 v1 接收 13 个候选，5 个引文错误导致部分失败；其中有 3 条理由与 1 条观点因改引号/空白未被接收。成对条件原句虽然保留，模型未结构化两支；规则基线在此例保留两支，故应继续保留它。1743 字符长评语 v2 在 8192 输出 tokens 时截断，零候选明确记 failed。原始输出和后续复跑均保留在对应工作区 `model-artifacts/`，不通过清洗结果掩盖失败。

v3 对同一主方案作一次协议简化：单一 opinion 类型内用引用列表连接理由、条件、分支和否定，避免小模型跨类型关联；窗口降为 600 字，超长单段拒绝截断。四份真实分区顺序调用 8 次，无截断；条件例、CSV、文字评分长例、短例分别接收 13、8、40、1 个候选，前两种协议粒度不同，这些数字不能当召回提升。条件例恢复了 1 组 2 支，但还有 11 个处理错误和明确动作遗漏；长例有 46 个处理错误，导入状态 partial。CSV 虽然全文被 8 个大引用覆盖，仍合并多个独立观点；4 条理由中 3 条是语义复述，不能因与主张跨度不同就视为因果解释。v3 没有自动形成可靠观点集合。

最后的保守适配不将某一条件分支的动作/强度投到整组，整组保留 unknown 和待核标记；原预测仍在 response/grounding。代码指纹在请求前捕获。四份真实 v3 输出保留当时配置、不改写；最后这两项适配修补另用合成回归及当前入口真实本地合成推理验证，不冒充原真实样本已重跑。原协议与四次复跑的明细见 `work/development-20261107/v3-adapter-summary.json`；主数据库导入及开发修正另见交接状态。

当前可验证的进展是本地模型真实执行、逐字证据校验、机器与人工记录分离，以及失败可回看。尚未测量独立准确率、专业复核耗时或 Framework 效果。下一步最小实验是同一批冻结原文、同一复核任务下比较主方案与基线的遗漏、条件/强度错误、每条合格观点的编辑用时；只有在独立开发外材料中降低人工总成本且不损害条件保真，才提高模型使用范围。否则保留模型为辅助提名，继续人工复核，不替换有效基线。

交付前独立审查还修复了三项适配问题：请求前复用核心冻结来源校验；合法空返回与失败区分；仅完整内容相同的候选去重，保留同句不同动作、强度或条件。三项均经原审查者独立探针关闭，记录见 STATE。全套 62 个合成测试和当前入口真实本地合成 smoke 通过；它们验证工程边界，不改变上述真实语义限制。

## 2026-11-06 LangExtract 与简单切分的固定答案实测

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

独立效果评测仍需按稿件分组、未参与改规则的样本和专业标注。测量完整观点召回、精确定位、条件保真、强度误判，以及每条合格观点的编辑修正时间。不能将开发例、固定答案探针或当前 agent 诊断改称独立测试集。
