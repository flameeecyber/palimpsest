#!/usr/bin/env python3
"""Generate placeholder 'photos' with no third-party libraries.

Pure stdlib PNG writer: a sky gradient, a horizon, a sun, and noise. At
thumbnail size it reads as a photograph, which is enough for a reproducible
demo image. For the real thing, pass --photos with your own directory.
"""

from __future__ import annotations

import math
import random
import struct
import subprocess
import sys
import zlib
from pathlib import Path

W, H = 640, 480


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def png(path: Path, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def scene(path: Path, seed: int) -> None:
    rng = random.Random(seed)
    hue = rng.random()
    sky_top = (
        int(40 + 80 * hue),
        int(60 + 70 * hue),
        int(110 + 90 * (1 - hue)),
    )
    sky_bottom = (
        int(190 + 50 * hue),
        int(140 + 40 * hue),
        int(90 + 60 * hue),
    )
    sun_x = rng.randint(90, W - 90)
    sun_y = rng.randint(80, 200)
    sun_r = rng.randint(26, 48)
    horizon = rng.randint(300, 360)

    rows: list[bytes] = []
    for y in range(H):
        row = bytearray()
        t = y / H
        if y < horizon:
            local = y / max(1, horizon)
            base = tuple(int(sky_top[i] * (1 - local) + sky_bottom[i] * local) for i in range(3))
        else:
            ground = y / H
            base = (
                int(40 + 30 * (1 - ground)),
                int(34 + 24 * (1 - ground)),
                int(28 + 18 * (1 - ground)),
            )
        for x in range(W):
            r, g, b = base
            dx, dy = x - sun_x, y - sun_y
            dist = math.hypot(dx, dy)
            if dist < sun_r:
                glow = 1 - dist / sun_r
                r = min(255, int(r + 120 * glow))
                g = min(255, int(g + 95 * glow))
                b = min(255, int(b + 55 * glow))
            elif dist < sun_r * 2.6:
                glow = (1 - dist / (sun_r * 2.6)) ** 2
                r = min(255, int(r + 60 * glow))
                g = min(255, int(g + 45 * glow))
            if y >= horizon:
                grain = rng.randint(-9, 9)
                r = max(0, min(255, r + grain))
                g = max(0, min(255, g + grain))
                b = max(0, min(255, b + grain))
            row += bytes((r, g, b))
        rows.append(bytes(row))
    png(path, rows)


def stamp(path: Path, index: int) -> None:
    """Write capture metadata so the demo has something to reason about.

    A recovered file with no EXIF is nearly unreadable: we know it is a photo,
    not when it was taken or where. Real photos carry this; placeholders need
    help.
    """
    try:
        subprocess.run(
            [
                "exiftool", "-overwrite_original", "-q",
                f"-DateTimeOriginal=2019:06:{14 + index:02d} 18:{22 + index % 30:02d}:01",
                f"-CreateDate=2019:06:{14 + index:02d} 18:{22 + index % 30:02d}:01",
                "-Make=Apple",
                "-Model=iPhone 8",
                f"-GPSLatitude={51.5074 + index * 0.001:.6f}",
                f"-GPSLongitude={0.1278 + index * 0.001:.6f}",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample/photos")
    out.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        path = out / f"IMG_{2019 + i % 3}_{i:04d}.png"
        scene(path, seed=i)
        stamp(path, i)
    print(f"wrote 10 placeholder photos to {out}")


if __name__ == "__main__":
    main()
