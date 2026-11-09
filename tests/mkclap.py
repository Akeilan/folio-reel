"""A clapperboard for measuring whether picture and sound line up (R5-04).

  clapper(path)      a film that flashes white and beeps at the same instants
  flashes(path)      the times, in seconds, where its picture flashes
  beeps(path)        the times, in seconds, where its sound starts
  offsets(path)      beep time minus flash time for each pair: 0 means in sync

Made with GdkPixbuf, Python's wave module and GStreamer alone, so the measurement does not lean on
whatever made the film.
"""
import os
import struct
import wave

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gst  # noqa: E402

Gst.init(None)
SECOND = 1000000000
W, H = 320, 240
RATE = 48000
BEEP_MS = 40            # how long each beep lasts
BEEP_HZ = 1000


def _run(desc, timeout=180):
    p = Gst.parse_launch(desc)
    p.set_state(Gst.State.PLAYING)
    m = p.get_bus().timed_pop_filtered(timeout * SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    if m is None or m.type == Gst.MessageType.ERROR:
        raise RuntimeError("couldn't make a clapperboard: %s" % (m.parse_error()[0].message if m else "timeout"))


def _frame(path, white):
    v = 255 if white else 0
    px = bytes((v, v, v)) * (W * H)
    pb = GdkPixbuf.Pixbuf.new_from_data(px, GdkPixbuf.Colorspace.RGB, False, 8, W, H, W * 3, None, None)
    pb.savev(path, "png", [], [])


def _wav(path, secs, at, fps):
    """Silence with a short beep starting at each of `at` (frame numbers)."""
    n = int(secs * RATE)
    buf = bytearray(n * 2)
    import math
    for f in at:
        start = int(round(f / fps * RATE))
        for i in range(int(RATE * BEEP_MS / 1000)):
            if start + i >= n:
                break
            s = int(22000 * math.sin(2 * math.pi * BEEP_HZ * i / RATE))
            struct.pack_into("<h", buf, (start + i) * 2, s)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(buf))


def clapper(path, n=75, fps=25, at=(10, 35, 60)):
    """A film of `n` frames at `fps` that flashes white on each frame in `at` and beeps at the very
    same instant. The flash lasts one frame; the beep lasts %d ms.""" % BEEP_MS
    folder = path + ".frames"
    os.makedirs(folder, exist_ok=True)
    for i in range(n):
        _frame(os.path.join(folder, "f%03d.png" % i), i in at)
    wav = path + ".wav"
    _wav(wav, n / fps, at, fps)
    _run('multifilesrc location="%s/f%%03d.png" start-index=0 stop-index=%d caps=image/png,framerate=%d/1 '
         "! pngdec ! videoconvert ! video/x-raw,format=I420 ! x264enc speed-preset=ultrafast quantizer=14 pass=qual "
         '! h264parse ! mux. filesrc location="%s" ! wavparse ! audioconvert ! audioresample '
         "! audio/x-raw,rate=48000,channels=2 ! avenc_aac ! aacparse ! mux. "
         'mp4mux name=mux ! filesink location="%s"' % (folder, n - 1, fps, wav, path))
    return path


def _brightness(uri, w=32, h=18):
    """[(t, mean 0..255)] for every frame."""
    p = Gst.parse_launch("uridecodebin uri=%s ! videoconvert ! videoscale "
                         "! video/x-raw,format=GRAY8,width=%d,height=%d ! appsink name=s sync=false" % (uri, w, h))
    s = p.get_by_name("s")
    p.set_state(Gst.State.PLAYING)
    stride = (w + 3) // 4 * 4
    out = []
    while True:
        sample = s.emit("try-pull-sample", 10 * SECOND)
        if sample is None:
            break
        buf = sample.get_buffer()
        ok, mi = buf.map(Gst.MapFlags.READ)
        if ok:
            d = bytes(mi.data)
            out.append((buf.pts / SECOND, sum(sum(d[y * stride:y * stride + w]) for y in range(h)) / (w * h)))
            buf.unmap(mi)
    p.set_state(Gst.State.NULL)
    return out


def _samples(uri):
    """(rate, [abs sample]) of the sound, one channel, as read back from the file."""
    p = Gst.parse_launch("uridecodebin uri=%s ! audioconvert ! audioresample "
                         "! audio/x-raw,format=S16LE,channels=1,rate=%d ! appsink name=s sync=false" % (uri, RATE))
    s = p.get_by_name("s")
    p.set_state(Gst.State.PLAYING)
    out = bytearray()
    while True:
        sample = s.emit("try-pull-sample", 10 * SECOND)
        if sample is None:
            break
        buf = sample.get_buffer()
        ok, mi = buf.map(Gst.MapFlags.READ)
        if ok:
            out += bytes(mi.data)
            buf.unmap(mi)
    p.set_state(Gst.State.NULL)
    n = len(out) // 2
    vals = struct.unpack_from("<%dh" % n, out, 0) if n else ()
    return RATE, [abs(v) for v in vals]


def _uri(path):
    return Gst.filename_to_uri(path) if "://" not in path else path


def flashes(path, floor=80.0):
    """The times where the picture goes bright, one per flash."""
    out, lit = [], False
    for t, v in _brightness(_uri(path)):
        if v >= floor and not lit:
            out.append(t)
            lit = True
        elif v < floor:
            lit = False
    return out


def beeps(path, floor=4000, gap=0.2):
    """The times where the sound starts, one per beep."""
    rate, vals = _samples(_uri(path))
    out = []
    i = 0
    while i < len(vals):
        if vals[i] >= floor:
            t = i / rate
            if not out or t - out[-1] > gap:
                out.append(t)
            i += int(rate * gap)
        else:
            i += 1
    return out


def offsets(path):
    """[beep - flash] for each pair, in seconds. Positive means the sound is late."""
    f, b = flashes(path), beeps(path)
    return [round(bb - ff, 4) for ff, bb in zip(f, b)], f, b
