"""
Reads icon.ico and rebuilds it with ALL standard Windows sizes.
Run automatically by BUILD_EXE.bat before compiling.
"""
import struct
import sys
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    print("[icon] Pillow not installed, skipping icon fix.")
    sys.exit(0)

SIZES = [16, 24, 32, 40, 48, 64, 96, 128, 256]

ico_path = Path(__file__).parent / "icon.ico"

if not ico_path.exists():
    print("[icon] No icon.ico found, skipping.")
    sys.exit(0)

try:
    src = Image.open(ico_path).convert("RGBA")

    frames = []
    for s in SIZES:
        resized = src.resize((s, s), Image.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="PNG")
        frames.append((s, buf.getvalue()))

    n = len(frames)
    header = struct.pack("<HHH", 0, 1, n)

    dir_offset = 6 + n * 16
    entries = b""
    images  = b""
    offset  = dir_offset

    for (s, png_bytes) in frames:
        size_byte = 0 if s == 256 else s
        entry = struct.pack(
            "<BBBBHHII",
            size_byte,
            size_byte,
            0,
            0,
            1,
            32,
            len(png_bytes),
            offset
        )
        entries += entry
        images  += png_bytes
        offset  += len(png_bytes)

    ico_path.write_bytes(header + entries + images)
    print("[icon] icon.ico rebuilt with sizes: " + str(SIZES))

except Exception as e:
    print("[icon] Warning: " + str(e))
    sys.exit(0)
