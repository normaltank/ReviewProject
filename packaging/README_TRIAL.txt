ReviewProject 本地试用版（Windows 10/11，64 位）

将整个 ZIP 解压到可写的本地目录，双击 ReviewProject.exe。
程序会启动仅本机可访问的网页工作台，并用系统默认浏览器打开。
请保留 _internal 和 licenses 目录；无需另装 Python 或 PowerShell。

先点“建立合成示例”体验原话、已保存分析图和人工纠正。所有示例均为
虚构材料，只说明软件操作，不代表专业金标。也可新建自己的分析，录入
任意数量的普通 B 评语、原分及可选 A 参照。请在保存后核对实际修订。

没有 API 配置也能录入、读取已有分析和人工纠正。自动分析需使用者自己
已授权的 DeepSeek 凭据，并明确开始任务；此包不含开发者密钥或离线大
模型。凭据由 Windows 当前用户加密层保存在本机，不随分析包或导出分享。

默认工作数据在 %LOCALAPPDATA%\ReviewProject\workbench。分析包是整个
目录，不只是 HTML；使用外部来源时，备份还须保留原来源及有效绑定。
请通过网页“关闭工作台”结束服务，再备份完整分析目录。浏览器标签关闭
后服务可能仍运行，需回到工作台执行关闭。

受控验证入口（通常无需使用）：
ReviewProject.exe --no-browser --port 0 --data-dir <独立本地目录> --ready-file <JSON路径>

运行环境及第三方许可证见 licenses/THIRD_PARTY_NOTICES.txt。
BUILD_INFO.json 记录构建版本，CONTENTS.sha256 是随包文件校验清单。
试用包只包含程序、运行库和明确合成示例，不含真实原件、分析数据库、
开发工作树、模型、凭据缓存或开发日志。项目本身未另行授予开源许可。
