"""Test footage for R4-07, made with GdkPixbuf and GStreamer alone (nothing else is needed to
make it, so the test proves the feature rather than the tool that built its input).

  shaky(path)  a hand-held look: a detailed picture with a red marker, jittering frame to frame
  bent(path)   a tripod shot through a wide lens: one straight line bowed by a barrel map
  marker_path(path), bow(path)   what the test measures
"""
import math
import os
import random

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gst  # noqa: E402

Gst.init(None)
SECOND = 1000000000
W, H, FPS = 320, 240, 25
BW, BH = 520, 440          # the bigger picture the shaky window is cropped out of
MARK = (240, 40, 40)       # the red block the test follows


def _run(desc, timeout=180):
    p = Gst.parse_launch(desc)
    p.set_state(Gst.State.PLAYING)
    m = p.get_bus().timed_pop_filtered(timeout * SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    if m is None or m.type == Gst.MessageType.ERROR:
        raise RuntimeError("couldn't make test footage: %s" % (m.parse_error()[0].message if m else "timeout"))


class Img:
    """A plain RGB picture to draw on and save."""
    def __init__(self, w, h, fill=(0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(fill) * (w * h))

    def set(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(rgb)

    def get(self, x, y):
        x = min(self.w - 1, max(0, x))
        y = min(self.h - 1, max(0, y))
        i = (y * self.w + x) * 3
        return self.px[i], self.px[i + 1], self.px[i + 2]

    def block(self, x0, y0, x1, y1, rgb):
        for y in range(max(0, y0), min(self.h, y1)):
            i = (y * self.w + max(0, x0)) * 3
            self.px[i:i + (min(self.w, x1) - max(0, x0)) * 3] = bytes(rgb) * (min(self.w, x1) - max(0, x0))

    def save(self, path):
        pb = GdkPixbuf.Pixbuf.new_from_data(bytes(self.px), GdkPixbuf.Colorspace.RGB, False, 8,
                                            self.w, self.h, self.w * 3, None, None)
        pb.savev(path, "png", [], [])

    def crop(self, x, y, w, h):
        out = Img(w, h)
        for j in range(h):
            si = ((y + j) * self.w + x) * 3
            out.px[j * w * 3:(j + 1) * w * 3] = self.px[si:si + w * 3]
        return out


def _texture(seed=11):
    """Detail that doesn't repeat, so a steadying pass can tell which way the camera moved."""
    rnd = random.Random(seed)
    im = Img(BW, BH, (30, 30, 34))
    for _ in range(90):
        x, y = rnd.randrange(BW), rnd.randrange(BH)
        w, h = rnd.randrange(14, 54), rnd.randrange(14, 54)
        im.block(x, y, x + w, y + h, (rnd.randrange(60, 256), rnd.randrange(60, 256), rnd.randrange(60, 256)))
    for _ in range(600):
        x, y = rnd.randrange(BW), rnd.randrange(BH)
        im.block(x, y, x + 3, y + 3, (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    # a red block in the middle of the scene: it is part of what was filmed, so it moves with the
    # camera, and following it says how steady the picture is
    im.block(BW // 2 - 14, BH // 2 - 14, BW // 2 + 14, BH // 2 + 14, MARK)
    return im


def _encode(folder, path, n, fps=FPS):
    _run('multifilesrc location="%s/f%%03d.png" start-index=0 stop-index=%d caps=image/png,framerate=%d/1 '
         "! pngdec ! videoconvert ! video/x-raw,format=I420 ! x264enc speed-preset=ultrafast quantizer=16 pass=qual "
         '! h264parse ! mp4mux ! filesink location="%s"' % (folder, n - 1, fps, path))


def shaky(path, n=60, amplitude=9, seed=11):
    """A hand-held look: the window on the picture jumps about by up to `amplitude` pixels."""
    folder = path + ".frames"
    os.makedirs(folder, exist_ok=True)
    big = _texture(seed)
    rnd = random.Random(seed + 1)
    cx, cy = (BW - W) // 2, (BH - H) // 2
    for i in range(n):
        jx = int(round(amplitude * math.sin(i * 0.9) + rnd.gauss(0, 3)))
        jy = int(round(amplitude * math.cos(i * 1.1) + rnd.gauss(0, 3)))
        jx = max(-cx, min(cx, jx))
        jy = max(-cy, min(cy, jy))
        big.crop(cx + jx, cy + jy, W, H).save(os.path.join(folder, "f%03d.png" % i))
    _encode(folder, path, n)
    return path


def _barrel(src, k):
    """The same picture as if shot through a lens that bulges (k > 0): straight lines bow out."""
    out = Img(src.w, src.h)
    cx, cy = (src.w - 1) / 2.0, (src.h - 1) / 2.0
    norm = math.hypot(cx, cy)
    for y in range(src.h):
        for x in range(src.w):
            dx, dy = (x - cx) / norm, (y - cy) / norm
            r2 = dx * dx + dy * dy
            f = 1.0 / (1.0 + k * r2)
            out.set(x, y, src.get(int(round(cx + dx * f * norm)), int(round(cy + dy * f * norm))))
    return out


def bent(path, n=50, k=0.35):
    """A tripod shot of a straight line, bowed by a lens. Every frame is the same."""
    folder = path + ".frames"
    os.makedirs(folder, exist_ok=True)
    flat = Img(W, H, (12, 12, 12))
    flat.block(0, 59, W, 63, (250, 250, 250))
    flat.block(0, H - 63, W, H - 59, (250, 250, 250))
    one = _barrel(flat, k)
    first = os.path.join(folder, "f000.png")
    one.save(first)
    for i in range(1, n):
        os.link(first, os.path.join(folder, "f%03d.png" % i)) if not os.path.exists(
            os.path.join(folder, "f%03d.png" % i)) else None
    _encode(folder, path, n)
    return path


def make(d):
    os.makedirs(d, exist_ok=True)
    out = {"shaky": os.path.join(d, "Hand Held.mp4"), "bent": os.path.join(d, "Wide Lens.mp4")}
    if not os.path.exists(out["shaky"]):
        shaky(out["shaky"])
    if not os.path.exists(out["bent"]):
        bent(out["bent"])
    return out


# ---------------------------------------------------------------- measuring
def frames(path, w=80, h=60):
    """Every frame of a film, small, as (bytes, rowstride, w, h)."""
    pipe = Gst.parse_launch(
        "filesrc location=\"%s\" ! decodebin ! videoconvert ! videoscale "
        "! video/x-raw,format=RGB,width=%d,height=%d,pixel-aspect-ratio=1/1 ! appsink name=sink sync=false max-buffers=8"
        % (path, w, h))
    sink = pipe.get_by_name("sink")
    got = []
    pipe.set_state(Gst.State.PLAYING)
    try:
        while True:
            s = sink.emit("pull-sample")
            if s is None:
                break
            buf = s.get_buffer()
            ok, mi = buf.map(Gst.MapFlags.READ)
            if not ok:
                break
            got.append(bytes(mi.data))
            buf.unmap(mi)
    finally:
        pipe.set_state(Gst.State.NULL)
    stride = (w * 3 + 3) // 4 * 4
    return [(g, stride if len(g) >= stride * h else w * 3, w, h) for g in got]


def marker(frame):
    """Where the red block is in this frame, or None."""
    data, stride, w, h = frame
    sx = sy = n = 0
    for y in range(h):
        row = y * stride
        for x in range(w):
            i = row + x * 3
            r, g, b = data[i], data[i + 1], data[i + 2]
            if r > 130 and r > g + 60 and r > b + 60:
                sx += x
                sy += y
                n += 1
    return (sx / n, sy / n) if n >= 4 else None


def shake(path, w=80, h=60):
    """How far the picture jumps between one frame and the next, in pixels of a w×h frame."""
    pts = [marker(f) for f in frames(path, w, h)]
    pts = [p for p in pts if p is not None]
    if len(pts) < 3:
        return None
    steps = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    return sum(steps) / len(steps)


def bow(path, w=320, h=240, at=0.25):
    """How far the straight line in the picture bends, in pixels: 0 is straight."""
    fs = frames(path, w, h)
    if not fs:
        return None
    data, stride, _w, _h = fs[min(len(fs) - 1, int(len(fs) * at))]
    band = range(int(h * 0.12), int(h * 0.42))      # the upper line, wherever it bowed to
    ys = []
    for x in range(int(w * 0.08), int(w * 0.92)):
        tot = wsum = 0.0
        for y in band:
            v = data[y * stride + x * 3]
            if v > 90:
                tot += v
                wsum += v * y
        if tot > 0:
            ys.append(wsum / tot)
    return (max(ys) - min(ys)) if len(ys) > 10 else None
