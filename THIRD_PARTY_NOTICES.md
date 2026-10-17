# Third-Party Notices

This project depends on the following third-party software and services.

## PySide6 / Qt 6

- License: LGPL-3.0 (with Qt commercial licensing options)
- Usage: GUI toolkit, dynamically linked.
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/

If you distribute a bundled executable, keep Qt dynamically linked and allow users to replace the Qt libraries, as required by the LGPL.

## winrt-* packages

- Packages: `winrt-runtime`, `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections`, `winrt-Windows.Globalization`, `winrt-Windows.Graphics.Imaging`, `winrt-Windows.Media.Ocr`, `winrt-Windows.Security.Cryptography`, `winrt-Windows.Storage`, `winrt-Windows.Storage.Streams`
- License: MIT
- Usage: access to the built-in Windows OCR engine.

## Translation services

- **Google public translate endpoint** (`clients5.google.com`): an unofficial public endpoint, not affiliated with or supported by Google. It may rate-limit or stop working at any time.
- **DeepSeek API**: usage is subject to DeepSeek's own terms and pricing.

## UI reference

The visual style was tuned with reference to the mobile apps **ViiTor 实时翻译** and **Bubble Translate**. Only color values and size parameters were referenced; no source code, assets, or resources from those applications are included in this repository.
