# 合成回归检查

在Windows、PowerShell 7和Python 3.12环境中运行。检查覆盖当前CLI、`AttentionWorkspace`事务、历史来源只读、补丁/恢复及实际浏览器往返，不读取真实材料，不需要模型、密钥或运行中的模型服务。

```powershell
python -m pip install -r requirements.txt playwright==1.47.0
pwsh -NoProfile -File scripts/check.ps1 -Python python
```

未设置`REVIEW_BROWSER_BINARY`时，入口查找本机已有Chrome或Edge；不会自动下载浏览器。也可显式指定可启动浏览器的绝对路径。显式指定无效路径会报错，不静默换用其他安装。如本机没有浏览器，可自行准备，或安装Playwright Chromium后指定其路径：

```powershell
python -m playwright install chromium
$env:REVIEW_BROWSER_BINARY = python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.chromium.executable_path); p.stop()"
pwsh -NoProfile -File scripts/check.ps1 -Python python
```

`-Python`接受解释器命令或路径，不绑定开发机目录。入口从任意当前目录定位仓库，显示实际解释器、浏览器、Playwright版本和测试数量。先检查Windows、`pwsh`、`powershell.exe`及可启动浏览器，再运行完整unittest discovery。

依赖缺失、测试失败、零测试或任何跳过均以非零退出码结束；不能据跳过签收界面验收。Windows链接/目录联接测试须有相应权限。直接诊断可运行`python -m unittest discover -s tests -v`，但其默认跳过行为不等于规范检查通过。

[Windows CI](../.github/workflows/check.yml)安装同一套最小依赖并复用入口，不上传原件、`work/`、模型或密钥。CI配置存在不表示远端运行成功，须核对交付提交的实际状态。真实语义质量和用户体验另行验收，工程测试通过不替代这些结论。
