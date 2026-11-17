# ReviewProject

一个本地论文评语分析工具。把外审专家B的原话、原分和必要语境放在一起，理解B关注什么、怎样表达、理由与条件怎样关联，再与当批内部专家A的关注方向比较，查看这些内容在评语记录中的分布。解释可以回查、纠正并保存。

A是可选且可变化的内容参照。核对的是我们是否忠实处理材料，不是复审论文或裁定B的专业结论。目标见[业务规格](docs/specs/b-attention-distribution.md)和[复用规格](docs/specs/b-attention-reuse.md)。

## 开始使用

需要 Python 3.12、Tkinter 和基础依赖。在仓库根目录运行：

```powershell
python -m pip install -r requirements.txt
python -m reviewproto desktop
```

也可双击 `start-review.cmd`。

1. **新建或打开分析。** 逐条录入B原话，按需附原分、来源和A关注清单。已有历史普通来源也可选择导入；核对清单后建立独立分析包。
2. **分析评语。** 显式选择已配置的DeepSeek API或本机模型，运行后查看结果。候选初稿、原始响应和处理状态保留，接收不表示语义已经核准。
3. **阅读与修改。** 先读B关注与A对应，需要时展开原话、理由、关系、统计和图形。修改后点击结果页的**保存修改**，成功后显示最新保存修订。

保存由桌面打开的临时本机页面完成；保持桌面运行。直接打开导出的静态HTML时，可以阅读和导出草稿，草稿须经当前CLI应用后才保存。失败或修订冲突会保留页面草稿；刷新或关闭前处理未保存提示。

操作说明：[输入与换批](docs/ATTENTION_INPUT.md)、[分析与候选](docs/ATTENTION_CANDIDATES.md)、[阅读与修改](docs/ATTENTION_READING.md)。备份前关闭写入，复制完整分析目录及绑定来源，不能只备份HTML。

## 数据与工程

当前关注分析是唯一写入产品。历史普通来源由独立只读适配器读取，不依赖旧规则包；旧条款审核、旧批次写入及其专用实验已经退役。旧原件、原分和人工历史保留，已有分析不因代码升级自动重算。改革范围见[改革规格](docs/specs/project-reform.md)。

真实资料、数据库、模型、凭据和备份留在本地可信目录，新克隆只含合成样例。[数据契约](docs/DATA_AND_ANNOTATION.md)规定权限与来源，[分析契约](docs/ATTENTION_CONTRACT.md)规定身份、保存及失效，[汇总口径](docs/ATTENTION_SUMMARY.md)规定分母。原始材料入口见[本地材料定位](docs/LOCAL_MATERIALS.md)。

当前CLI可用 `python -m reviewproto --help` 查看，支持分析包建立、应用、恢复、迁入、换A和候选操作；不再提供旧审核命令。静态草稿可用 `attention-apply` 应用。

完整合成检查使用 `pwsh -NoProfile -File scripts/check.ps1`，环境要求见[测试说明](docs/TESTING.md)。不需要真实材料、模型服务或密钥；浏览器缺失、测试失败或跳过均不能签收。

项目进度见[总清单](PROJECT_TODO.md)，工程续接见[STATE](docs/STATE.md)，协作入口为[AGENTS](AGENTS.md)与[Matt工作流](docs/agents/workflow.md)。GitHub Issues/PR是任务状态台账；本地检查、远端CI和用户验收分别报告。
