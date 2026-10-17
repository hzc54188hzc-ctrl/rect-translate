"""生成 app.ico（纯标准库，不经过 Qt —— 本机 QImage 写 PNG 会崩）。

图案：橙色圆角方块 + 两条深色横线（对应选框与译文）。
用法：.venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZE = 64
ACCENT = (0xFF, 0xA8, 0x00, 255)
DARK = (0x11, 0x11, 0x11, 255)
TRANSPARENT = (0, 0, 0, 0)


def _in_rounded_rect(x: int, y: int, left: float, top: float, right: float, bottom: float, radius: float) -> bool:
    if not (left <= x + 0.5 < right and top <= y + 0.5 < bottom):
        return False
    cx = min(max(x + 0.5, left + radius), right - radius)
    cy = min(max(y + 0.5, top + radius), bottom - radius)
    return (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= radius ** 2


def _rows() -> list[bytes]:
    rows: list[bytes] = []
    for y in range(SIZE):
        row = bytearray()
        for x in range(SIZE):
            color = TRANSPARENT
            if _in_rounded_rect(x, y, 4, 8, 60, 56, 12):
                color = ACCENT
                if 16 <= y < 22 and 14 <= x < 50:
                    color = DARK
                elif 32 <= y < 38 and 14 <= x < 38:
                    color = DARK
            row += bytes((color[2], color[1], color[0], color[3]))  # BGRA
        rows.append(bytes(row))
    return rows


def main() -> int:
    rows = _rows()
    xor = b"".join(reversed(rows))
    mask_stride = ((SIZE + 31) // 32) * 4
    and_mask = b"\x00" * (mask_stride * SIZE)
    header = struct.pack(
        "<IiiHHIIiiII", 40, SIZE, SIZE * 2, 1, 32, 0, len(xor), 0, 0, 0, 0
    )
    image = header + xor + and_mask
    icon_dir = struct.pack("<HHH", 0, 1, 1) + struct.pack(
        "<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32, len(image), 6 + 16
    )
    out = Path(__file__).resolve().parent.parent / "app.ico"
    out.write_bytes(icon_dir + image)
    print(f"已生成 {out}（{out.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
