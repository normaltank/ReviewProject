# 合成回归检查

在 Windows、PowerShell 7 和 Python 3.12 环境中运行。检查沿用 `tests/` 的公开 CLI、Workspace、补丁/恢复及浏览器往返测试，不读取本地真实材料，不需要模型、密钥或运行中的模型服务。

```powershell
python -m pip install -r requirements.txt playwright==1.47.0
python -m playwright install chromium
$env:REVIEW_BROWSER_BINARY = python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.chromium.executable_path); p.stop()"
pwsh -NoProfile -File scripts/check.ps1 -Python python
```

也可将 `REVIEW_BROWSER_BINARY` 设为已有 Chrome/Chromium 的绝对路径。`-Python` 接受当前环境的解释器命令或路径，不绑定开发机安装目录。入口从任意当前目录定位到仓库，显示实际解释器、浏览器、Playwright 版本及测试数量。

入口先检查 Windows、`pwsh`、`powershell.exe` 和可启动的浏览器，再运行完整 unittest discovery。依赖缺失、测试失败、零测试或任何跳过均以非零退出码结束；跳过会逐项列出原因，不能据此签收界面验收。Windows 符号链接/目录联接测试也须具备所需权限。单独诊断可运行 `python -m unittest discover -s tests -v`，但其默认跳过行为不等于完整检查通过。

[Windows CI](../.github/workflows/check.yml) 安装同一套最小依赖并复用入口；不安装全局 hook，不上传 `work/`、原件、模型或密钥。CI 配置已准备不表示远端运行成功，交付需另查对应提交的实际状态。Actions 用法参考[官方 Python 测试说明](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)和 [setup-python](https://github.com/actions/setup-python)。
