# 当前工具与方法选择

最新侧边研究的接续结论见[2026-11-17 成果收拢](#side-results-20261117)；下文 11-15 的固定实测保留当轮范围。

核查日：2026-11-15。目标是变化A/B下理解B关注、对照非评分A、看分布、回原文并纠正保存。费用约束按用户最新确认：保留已授权DS Flash，不新增收费API或软件订阅。

## 当前名单

- **运行底座：** 继续使用现有Python、SQLite、JSON补丁、本机窗口与静态HTML/原生JS；保留原文定位、修订、来源失效、恢复和可选可视化。
- **模型服务：** 仅DeepSeek `deepseek-flash`，按官方当日映射为用户指定的4.1 Flash 1017；不Pro、不微调。DS按用量收费，结构化输出仍须本地校验和人工核对，不将模型自己填写的置信度当校准概率。
- **本轮结论：** 保留现有`focused`候选流程。记录级合并请求试验未满足采用条件，`record-batched`原型不进入main、运行依赖或普通入口；[固定实验代码](https://github.com/normaltank/ReviewProject/commit/612716e37b327c7b92e115a66460392443a76270)保留用于复现，不能当作待合入功能。
- **方法参考：** LLooM的概念定义、正反例与原文下钻，LLMCode的人工示例与编码一致性核对；原包都不列为当前安装或运行依赖。
- **条件观察：** GLiNER2.5只在有限分类确有瓶颈时再测本机方案；QualCoder保留为人工工作台对照。NuExtract3文档抽取、旧LangExtract组件当前均不为新关注流程扩装或切换模型。
- **退出实施：** Gemini Decisions、MAXQDA及开源框架默认的额外OpenAI/Azure等付费后端。原论文、界面和历史研究可继续参考，不恢复接入身份。

## 两年前的工具还能用吗

方法年份、软件维护和本项目适配分开判断。2024论文仍能提供合适的分析方法；当前软件能否直接使用，要看固定源码、发行、依赖及实际行为。

### LLooM：可借方法，当前原包需要显著适配

作者库最后实际代码变更为[2de1a86，2025-06-04](https://github.com/michelle123lam/lloom/commit/2de1a86153ee9524f886d82feb6c0b5baffe81ec)；同日HEAD[8252533](https://github.com/michelle123lam/lloom/commit/8252533ab6018bea89c1e33e31c0f8fb6a07a707)只改文档。[PyPI](https://pypi.org/project/text-lloom/)的0.8.2.1也发于2025-06；不能把2024的GitHub Release当成最新Python发行日期。截至本次核查未见之后的新代码，研究软件有维护断档风险。

固定源码默认用GPT-4o/mini及OpenAI embeddings；替换聊天模型后仍需替换嵌入服务。[自定义接口](https://github.com/michelle123lam/lloom/blob/8252533ab6018bea89c1e33e31c0f8fb6a07a707/docs/about/custom-models.md)存在，但不等于已支持指定Flash。原包装器有模型名表、分词/截断假设，工作台导入会下载NLTK资源；不能只换key/address便认定兼容。[edit接口](https://github.com/michelle123lam/lloom/blob/8252533ab6018bea89c1e33e31c0f8fb6a07a707/text_lloom/src/text_lloom/workbench.py#L845-L861)尚未实现，不能用原论文的人在环设计证明当前包已有完整纠正保存闭环。

BSD-3-Clause许可允许按条件复用。当前已核查固定源码、wheel与依赖，没有整包安装或widget运行/DS质量结果；不将静态检查称为可用性通过。若以后试原包，使用隔离环境并显式替换全部收费提供方。

### LLMCode：适合借流程，整包迁移当前不划算

[HEAD 1fbea4b](https://github.com/PerttuHamalainen/LLMCode/commit/1fbea4b190cb6742a86ad58b3be0a1f418469330)为2025-01-21的UI变更；[Python库最近更新](https://github.com/PerttuHamalainen/LLMCode/commit/e402776b899227ff27785d6732a914e5f9ce1ca2)为2024-11-18。库为MIT，未找到作者确认的PyPI发行；不是把GitHub源码当当前可直接安装包。

固定[模型分支](https://github.com/PerttuHamalainen/LLMCode/blob/1fbea4b190cb6742a86ad58b3be0a1f418469330/llmcode/llms.py#L242-L258)对OpenAI名称/分词/context表有绑定，`deepseek-flash`不进入正确chat分支。React界面的[凭据方式](https://github.com/PerttuHamalainen/LLMCode/blob/1fbea4b190cb6742a86ad58b3be0a1f418469330/coding_ui/src/llmcode/LLM.js#L5-L10)及20条标注门槛不适合直接迁入当前本机流程。[JS指标清洗](https://github.com/PerttuHamalainen/LLMCode/blob/1fbea4b190cb6742a86ad58b3be0a1f418469330/coding_ui/src/llmcode/Metrics.js#L17-L34)会去除中文字符；这是UI指标问题，不扩推为Python指标或输入原文都会被删除。

未安装整包、未测试其当前云接口或中文质量；保留示例编码、引文检查和轻量报告思路。复用方法无需先接受其整套依赖和默认模型。

## 记录级试验：未采用

[Issue34](https://github.com/normaltank/ReviewProject/issues/34)记录本轮固定范围、取舍及实际交付。原型只改变候选编排，沿用原逐字/范围核对、所有候选待核、正式数据只读生成、接收事务和纠正恢复。B阶段独立于A；A阶段完整比较已校验B范围与当批全部A，无A不生成清单外。研究对照代码不属于当前产品入口。

三批全新合成输入为2A/3B、3A/3B、无A/1B，共7条逻辑B；含多分区、条件备选、归属、多A、Unicode组合字符/emoji及未导入A。输入、验收参考和方案代码在模型推理前冻结；基线为`29d3974`，原型为`612716e`，模型均为同一指定Flash及相同思考/输出设置。参考不发送模型，没有根据本批输出调提示或重标首评。

- 基线109次请求，原型14次（含格式修复）；全部123次HTTP200且usage已知。
- 生成与预览渲染合计分别681.359秒和660.422秒；不含输入准备或人的核对，不是重复随机实验或用户工时收益。
- 按核查日非高峰计价和实际缓存/输出用量，分别估算0.0717美元和0.0749美元；不是账户账单。请求更少没有带来本批费用优势。
- 隐藏方法名/成本的独立代理首评：基线6通过、1部分、0失败；原型4通过、2部分、1失败，分母各7。原型一条B无有效候选，另一条B保留内容但A去向未完成。两法都把一处访谈说明力关注扩大为呈现类A的partial对应；保留默认不等于宣称默认在未来输入均正确。

原型工程检查455项、零失败/错误/跳过；固定Spec/Standards复核无未解决项。审查中曾发现完整矩阵在容量检查前撑破审计限制，返修后超限明确partial、保留有效B并列未完成A。工程有效没有弥补本批语义质量和费用结果，故不采用。main仅收拢文档决定，不增加实验参数、模块或测试。

合并调用仍需输出完整比较矩阵，规模不会因请求变少而消失。实验保留失败、一次格式修复与未知/未完成边界，不以裁A/B或自动回退换低调用数。本轮原费用估算上限1美元未变；首组旧流程45调用后，仅内部请求数边界由80修订为140以完成原定全部样例，实际123次，无超限拒发或追加模型提供方。

跨记录主题仍须人工整理；此试验没有实现全自动概念归并。LLooM式概念定义与回查是后续可比较方法，不因本轮名单收拢而宣称已完成。

<a id="side-results-20261117"></a>
## 侧边成果收拢 · 2026-11-17

来源为“比较当前工作与 RAG”五轮对话及其[本地交接和证据](../LOCAL_MATERIALS.md#side-research-20261117)。本轮只收拢既有研究，没有新增工具优势结论。

- **已有验证：** DocETL、LOTUS、Haystack 的公开接口已用隔离安装与预写回放跑通；真实 DS 试点随后暴露拒收和语义扩大，不能把接口成功当内容正确。
- **可接收小补丁：** 模型内容 JSON 检出重复字段，沿当前最多一次格式修复保留原失败。侧边公开生成红绿回归和只读应用检查可复用；接入本项目仍需最终完整检查及独立审查。当前不依赖 DocETL。
- **归并方法候选：** 直接 DS 只生成标签和成员 ID，成员解释及原话来自冻结 B，减少自由改写。新的 3 条记录、5 个预写方面上两法均为 4 组；直接 DS 此例估价较低，但提示/输出不同，同一代理核对，未验证完整 B 抽取或 A 对照，也未接入产品保存。
- **检索方向：** [RAG](https://arxiv.org/abs/2005.11401)保留按需找原文、语境和正反例的用途；[GraphRAG](https://arxiv.org/abs/2404.16130)保留整批主题归纳的待测问题。检索遗漏不等于关注不存在或位于 A 清单外，检索子集不作为整批统计分母。
- **其他相关候选：** [BERTopic](https://maartengr.github.io/BERTopic/)用于主题探索，[Argdown](https://argdown.org/)借鉴关系表达，[Promptfoo](https://www.promptfoo.dev/docs/intro/)借鉴反例回归；[DocWrangler](https://arxiv.org/abs/2504.14764)保留人工检查中间过程的方法参考。已有主源初筛，不冒称这些路线已在本项目生产适配或效果胜出。

当前采用决定：继续既有 DS Flash 路径，先接收小修复；不重复安装/回放已验证接口，不引入新收费后端。跨记录归并需普通操作、版本失效、未处理范围和保存恢复的完整接入与新材料验收，仍属条件分支。[当前总计划](../plans/attention-followthrough-20261117.md)规定顺序，不用本侧预写 B 的归并结果替代 #38 或新 A/B 完整验证。
