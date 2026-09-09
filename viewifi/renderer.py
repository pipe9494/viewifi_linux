"""Pure-stdlib PNG renderer for the RSSI detection snapshot.

Draws the signal waveform around the alarm moment with the detection
threshold band, in the Viewifi dark palette. No Pillow/matplotlib needed —
this writes a PNG directly with zlib, so it runs on a bare Raspberry Pi.
"""

import struct
import zlib

W, H = 800, 400

# palette (RGB) — mirrors the Android app theme
BG = (10, 14, 20)
GRID = (40, 50, 65)
TEXT = (154, 163, 181)
LINE = (0, 229, 255)
THRESH = (255, 145, 0)
ALERT = (255, 23, 68)
GREEN = (0, 230, 118)


def render_waveform(samples, baseline, sigma, sensitivity, level, title=""):
    """Renders the RSSI window as PNG bytes."""
    img = bytearray(BG * (W * H))

    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H:
            i = (y * W + x) * 3
            img[i:i + 3] = bytes(c)

    def hline(y, x0, x1, c):
        for x in range(x0, x1 + 1):
            put(x, y, c)

    def line(x0, y0, x1, y1, c):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):  # 2px thick
                put(x0 + ox, y0 + oy, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    if not samples:
        samples = [baseline] * 2

    lo = min(min(samples), baseline - 8)
    hi = max(max(samples), baseline + 8)
    rng = max(hi - lo, 6)

    def sy(rssi):
        return int(H - 40 - (rssi - lo) / rng * (H - 80))

    # grid
    for gy in range(0, H, 40):
        for x in range(0, W, 2):
            put(x, gy, GRID)

    # threshold band: baseline ± sigma*sensitivity
    t = sigma * sensitivity
    y_hi = sy(baseline + t)
    y_lo = sy(baseline - t)
    for y in range(y_hi, y_lo + 1):
        for x in range(0, W, 3):
            put(x, y, (30, 34, 45))
    hline(y_hi, 0, W - 1, THRESH)
    hline(y_lo, 0, W - 1, THRESH)

    # baseline
    yb = sy(baseline)
    hline(yb, 0, W - 1, GREEN)

    # waveform
    n = len(samples)
    step = max(1, n // W)
    xs = samples[::step]
    col = ALERT if level in ("HIGH", "MEDIUM") else LINE
    px, py = 0, sy(xs[0])
    for i in range(1, len(xs)):
        x = int(i * W / len(xs))
        y = sy(xs[i])
        line(px, py, x, y, col)
        px, py = x, y

    return _png(W, H, bytes(img))


def _png(w, h, rgb):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw.extend(rgb[y * w * 3:(y + 1) * w * 3])
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
