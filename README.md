# 矩形翻译（RectTranslate）

一个 Windows 桌面翻译工具：在屏幕上保留一块可变大小的矩形，持续翻译框内的内容；也可以在任何应用里选中文字，按全局热键直接翻译。

界面为中文。

## 功能

- **常驻矩形**：任意位置与大小，拖四角/四边胶囊即可调整；内容变化时自动重译，也可以点控制条上的「翻译」手动翻一次。
- **划词翻译**：选中文字后按全局热键（默认 `Ctrl+Shift+Q`），直接翻译选中内容，不经过 OCR。
- **双翻译通道**：免 key 的公共接口，或 DeepSeek 大模型，随时切换。
- **术语标注**：大模型通道下，译文中的专业术语、网络热梗、典故/论文概念会用蓝字标出，点击打开搜索引擎（默认 Bing）。
- **独立浮窗**：半透明、白/黑两套配色，可拖动、缩放，并记住位置。
- **托盘常驻**：关闭控制条只是收进托盘；重复启动快捷方式会把已有选框唤到前面。
- **外观可调**：选框颜色（橙/蓝/黑/白）、粗细（4/6/8px）、长度（短/中/长）。

## 系统要求

- Windows 10 2004+ 或 Windows 11
- Python 3.12+（开发与验证环境为 3.14）
- 已安装对应的 Windows OCR 语言包（设置 → 时间和语言 → 语言）

## 安装与启动

```powershell
git clone <this-repository-url>
cd <repository-folder>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe 01-run.py
```

首次运行会自动生成 `config.local.json`，默认使用**免费通道**，不需要 API key。

需要桌面快捷方式时：

```powershell
powershell -NoProfile -File tools\05-install-shortcut.ps1
```

## 常用操作

| 操作 | 做法 |
| --- | --- |
| 翻译当前矩形 | 点控制条上的「翻译」；或双击选框；或右键「翻译一次」 |
| 移动选框 | 拖四角回旋镖的拐弯处 |
| 缩放选框 | 拖回旋镖臂端（对角）或四边中点胶囊（单边） |
| 划词翻译 | 选中文字 → `Ctrl+Shift+Q` |
| 移动译文浮窗 | 拖浮窗顶部中间的胶囊 |
| 收进托盘 | 点控制条最右的 ×，或按 `Esc` |
| 完全退出 | 托盘图标右键 →「退出」 |
| 改热键/外观 | 控制条齿轮 → 设置 |

## 切换到大模型

设置 → 翻译通道 →「大模型」，填入以 `sk-` 开头的 DeepSeek API key。key 只保存在本机 `config.local.json`，不会上传。没有 key 时请保持「免费接口」。

## 隐私

- 矩形截图在**本机**用 Windows OCR 识别；识别出的文字会发送给你选择的翻译服务（免费通道为 Google 公共端点，大模型为 DeepSeek）。
- 划词会模拟一次 `Ctrl+C` 读取选中文本，完成后**原样还原剪贴板**（包括图片、文件与 HTML）。
- 程序不含遥测，不上传配置；API key 以明文保存在本机配置文件中。

## 已知限制

- 仅支持 Windows；OCR 依赖系统语言包。
- 小字号、深色底、密集文字识别质量有限；DRM 保护内容可能抓到黑屏。
- 免费通道使用非官方公共端点，可能限流或失效。
- 高 DPI 与多显示器只做了基础适配，尚未充分验证。
- 术语标注由模型判断，可能误标或漏标；点击是跳转搜索，不是权威释义。

## 项目结构

```text
.
├─ 01-run.py            入口
├─ recttrans/           主程序（选框、抓图、OCR、翻译、浮窗、托盘、设置）
├─ tests/               回归与自检脚本
├─ tools/               快捷方式与图标工具
├─ requirements.txt     依赖
└─ config.example.json  配置示例（首次运行会自动生成 config.local.json）
```

## 开发与测试

```powershell
.\.venv\Scripts\python.exe tests\run_all.py
```

`run_all.py` 只跑不依赖网络/真实 OCR 的回归项；`tests\14-settings-check.py`（联网）、`tests\15-text-selection.ps1`（手动划词）需要单独执行。CI 配置见 `.github/workflows/tests.yml`。

## License

MIT，见 [LICENSE](LICENSE)。第三方组件与参考说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## English

RectTranslate is a Windows desktop translation tool. Keep a resizable on-screen rectangle and get live translations of its contents, or select text in any app and press a global hotkey. OCR runs locally through Windows OCR; recognized text is sent to Google's public endpoint or DeepSeek for translation. Requires Windows 10 2004+/11 and Python 3.12+. MIT licensed. The UI is currently Chinese.
