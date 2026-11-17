# 项目进度

目标是一个可以重复接收变化A/B的本地工具：理解B关注、表达、关系及分布，对照当批可选A，允许原文回查、纠正和保存。当前业务目标不包含论文复审、评分预测或标准修订。

**本轮：工程与操作改革。** 只保留当前关注分析写入主线，拆开历史来源只读接入，结果页直接保存，退役旧审核及专用实验。规格见[改革规格](docs/specs/project-reform.md)，实际验收与交付见[父任务#47](https://github.com/normaltank/ReviewProject/issues/47)。

已有普通输入、候选生成、原话原分回查、逐方面纠正、主题/关系/A对应、记录分布与可选图形。已有分析及人工历史保留，不因代码升级自动重算。操作见[README](README.md)。

仍需区分两类后续工作：

- 已知语义缺口：[#38](https://github.com/normaltank/ReviewProject/issues/38)的范围理解、[#44](https://github.com/normaltank/ReviewProject/issues/44)的关系保全。此次结构改革不冒称解决模型解释质量。
- 用户实际使用：检查新操作是否清楚、当前解释是否忠实。代理浏览器演练不等于用户验收或专业金标。

其他研究与隔离试验见[工具决定](docs/research/attention-tools.md)，按当前业务缺口采用方法，不重新启动逐包框架横评。历史完成记录见GitHub已关闭工作项及Git历史，旧计划中的“下一步”不自动进入本轮待办。

GitHub Issues/PR是任务状态唯一台账。本地实现、已推送分支、PR、main和部署分别报告，工程续接见[STATE](docs/STATE.md)。
