# 矩形翻译（RectTranslate）

[English](README.en.md) | 中文

一个 Windows 桌面翻译工具：在屏幕上保留一块可变大小的矩形，持续翻译框内的内容；也可以在任何应用里选中文字，按全局热键直接翻译；还可以采集系统声音，为英文视频和直播生成实时中文字幕。

界面为中文。

![矩形翻译：框住 arXiv 论文《Attention Is All You Need》，右侧浮窗给出译文，Transformer、注意力机制、BLEU 等术语以蓝字标出](docs/screenshot-01.png)

*框住网页任意区域即可持续翻译；译文中的高辨识度术语会以蓝字标出，点击可跳转搜索。*

<!-- 第二张（设置面板）就绪后取消注释，把截图放到 docs/screenshot-02.png：
![设置：翻译通道、划词热键、选框外观](docs/screenshot-02.png)
-->

## 功能

- **常驻矩形**：任意位置与大小，拖四角/四边胶囊即可调整；内容变化时自动重译，也可以点控制条上的「翻译」手动翻一次。
- **OCR 增强**：识别前 2 倍放大；自动模式同时用中英两套引擎并择优，右键可强制中文/英文。
- **划词翻译**：选中文字后按全局热键（默认 `Ctrl+Shift+Q`），直接翻译选中内容，不经过 OCR。
- **双翻译通道**：免 key 的公共接口，或 DeepSeek 大模型，随时切换。
- **术语标注**：大模型通道下，译文中的专业术语、网络热梗、典故/论文概念会用蓝字标出，点击打开搜索引擎（默认 Bing）。
- **独立浮窗**：半透明、白/黑两套配色，可拖动、缩放，并记住位置。
- **翻译历史**：手动与划词翻译保留最近 50 条，托盘「历史记录…」可回看、复制、清空。
- **长译文滚动**：浮窗封顶 75% 屏高，超出部分可滚动查看。
- **托盘常驻**：关闭控制条只是收进托盘；重复启动快捷方式会把已有选框唤到前面。
- **外观可调**：选框颜色（橙/蓝/黑/白）、粗细（4/6/8px）、长度（短/中/长）。
- **系统声音同传**：采集扬声器环回音频，在本机用 tiny.en 识别，中文译文实时滚动；支持 1–3 句上下文、2–4 行显示、向上滚回看历史；音频只在内存处理，不落盘。

## 系统要求

- Windows 10 2004+ 或 Windows 11
- Python 3.12+（开发与验证环境为 3.14）
- 已安装对应的 Windows OCR 语言包（设置 → 时间和语言 → 语言）
- 同传需要额外下载约 75MB 的 tiny.en 语音模型（见下）
- 同传建议 4 核以上 CPU；低端 CPU 可能无法实时

## 安装与启动

```powershell
git clone https://github.com/hzc54188hzc-ctrl/rect-translate.git
cd rect-translate
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe 01-run.py
```

首次运行会自动生成 `config.local.json`，默认使用**免费通道**，不需要 API key。

使用同传前，先下载语音模型：

```powershell
powershell -NoProfile -File tools\download-model.ps1
```

下载完成后，点功能浮窗上的「同传」即可开始。

## 免安装版（Windows x64）

不想装 Python 的话，从 [Releases](https://github.com/hzc54188hzc-ctrl/rect-translate/releases) 下载 `RectTranslate-win64.zip`，解压后双击 `RectTranslate.exe`。首次运行同样会自动生成 `config.local.json`。

免安装包不内置语音模型。首次开启同传时，程序会提示下载；也可以手动运行包内 `tools\download-model.ps1`。

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
| 开启/关闭同传 | 点功能浮窗上的「同传」 |
| 回看字幕 | 在字幕浮窗上向上滚；停手 3 秒自动回到底部 |

## 切换到大模型

设置 → 翻译通道 →「大模型」，填入以 `sk-` 开头的 DeepSeek API key。key 只保存在本机 `config.local.json`，不会上传。没有 key 时请保持「免费接口」。

## 隐私

- 矩形截图在**本机**用 Windows OCR 识别；识别出的文字会发送给你选择的翻译服务（免费通道为 Google 公共端点，大模型为 DeepSeek）。
- 划词会模拟一次 `Ctrl+C` 读取选中文本，完成后**原样还原剪贴板**（包括图片、文件与 HTML）。
- 程序不含遥测，不上传配置；API key 以明文保存在本机配置文件中。
- 翻译历史保存在本机 `history.json`（仅手动/划词，最多 50 条），可随时在历史窗口清空。
- 同传只采集系统输出声音（WASAPI 环回），音频在内存中处理，不写文件；语音识别在本机完成，只有识别出的文字会发送给你选择的翻译服务。

## 已知限制

- 仅支持 Windows；OCR 依赖系统语言包。
- 小字号、深色底、密集文字识别质量有限；DRM 保护内容可能抓到黑屏。
- 免费通道使用非官方公共端点，可能限流或失效。
- 抓图已按窗口物理像素适配 125%/150% 缩放；多显示器仍建议实测。
- 术语标注由模型判断，可能误标或漏标；点击是跳转搜索，不是权威释义。
- 同传对重叠对话、背景音、生僻词可能听错或漏句；网络慢时当前行会滞后，向上滚可看历史。
- 同传目前只支持英文识别、中文翻译。

## 项目结构

```text
.
├─ 01-run.py            入口
├─ recttrans/           主程序（选框、抓图、OCR、翻译、浮窗、托盘、设置）
├─ tests/               回归与自检脚本
├─ tools/               快捷方式与图标工具
├─ models/              本地语音模型（下载后生成，不提交）
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
