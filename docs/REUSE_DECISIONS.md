# 当前组件与复用决定

- **SQLite 分析包**记录来源、保存修订和审计。由已经验证的 `AttentionWorkspace` 提供建包、应用补丁和恢复。网页使用同一保存事务，投影文件可重建。
- **只读来源适配**核验受支持的历史来源原件、普通分区和原分，再交给当前输入契约。`local_io` 负责本地文件和严格 JSON，沿用已有校验。
- **候选分析**使用 DeepSeek 和现有证据绑定及接收流程。测试以模拟响应覆盖请求与保存边界。来源或语义需要复查时，回到具体记录、原话和范围，最终解释可由人纠正。
- **关注图**使用 HTML 和 SVG。轮廓、分区和点由实际材料计算，交互同源联动，静态导出复用当前数据。二维布局能直接满足这批阅读任务，也便于在包内提供本地资源。[技术比较](research/visualization-route-20261117.md)。
- **运行与打包**使用标准库回环服务与浏览器，试用版由 PyInstaller 提供 Windows 运行时。运行、构建及测试依赖各自从实际入口维护。[测试说明](TESTING.md)。

旧实现和隔离实验的原因、用量及结果可从对应工作项和 Git 历史查阅。已知的语义范围和关系问题由 [#38](https://github.com/normaltank/ReviewProject/issues/38) 与 [#44](https://github.com/normaltank/ReviewProject/issues/44) 跟踪。
