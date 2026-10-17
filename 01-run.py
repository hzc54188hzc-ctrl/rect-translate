"""常驻矩形翻译工具入口。"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from recttrans.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
