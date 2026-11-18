# ReviewProject

一个本地论文评语分析工具。把外审老师（B）的原话、原分及必要语境整理成可核对的关注内容和关系，对照内部专家（A）为当批提供的可选关注清单，查看这些内容在评语记录中的分布。每批可使用不同的 A 和 B，任何解释都可以回查、纠正和保存。

## 开始使用

Windows 10/11 试用版解压整个 ZIP，双击 `ReviewProject.exe`，浏览器会打开本机工作台。先点**建立合成示例**看图和原话，也可点**新建分析**录入自己的评语。详见[使用指南](docs/USER_GUIDE.md)。

从源码运行需要 Windows 与 Python 3.12。安装依赖后双击 `start-review.cmd`，或运行以下命令。

```powershell
python -m pip install -r requirements.txt
python -m reviewproto.workbench_launcher
```

## 维护入口

- [业务规格](docs/specs/b-attention-distribution.md)定义工具用途、A/B 和分布口径。[网页与试用交付规格](docs/specs/web-workbench-trial.md)定义操作及验收。
- [数据与标注](docs/DATA_AND_ANNOTATION.md)约束材料使用。[关注分析契约](docs/ATTENTION_CONTRACT.md)和[汇总算法](docs/ATTENTION_SUMMARY.md)约束保存和计数。
- [当前状态](docs/STATE.md)记录交付与材料位置。[待办](PROJECT_TODO.md)列出试用及在办工作。
- [验证](docs/TESTING.md)说明合成检查，[协作入口](AGENTS.md)说明工程流程。
