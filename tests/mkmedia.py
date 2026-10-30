"""Test media made with GStreamer: coloured videos with tones, sound-only files and a picture.

  make(dir) -> {"red": path, "blue": path, "music": path, "speech": path, "photo": path, "silent": path}
  frame_color(path, t) -> (r, g, b) average of the frame at t
  loudness(path, t, span) -> RMS (0..1) of the sound around t
"""
import os

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gst  # noqa: E402

Gst.init(None)
SECOND = 1000000000


def _run(desc, timeout=120):
    p = Gst.parse_launch(desc)
    p.set_state(Gst.State.PLAYING)
    m = p.get_bus().timed_pop_filtered(timeout * SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    if m is None or m.type == Gst.MessageType.ERROR:
        raise RuntimeError("couldn't make test media: %s" % (m.parse_error()[0].message if m else "timeout"))


def video(path, pattern, secs, freq, w=640, h=360, fps=25):
    n = int(secs * fps)
    _run("videotestsrc pattern=%s num-buffers=%d ! video/x-raw,width=%d,height=%d,framerate=%d/1 ! x264enc speed-preset=ultrafast "
         "! h264parse ! mux. audiotestsrc freq=%d volume=0.5 num-buffers=%d samplesperbuffer=1024 ! audio/x-raw,rate=48000,channels=2 "
         "! avenc_aac ! aacparse ! mux. mp4mux name=mux ! filesink location=\"%s\""
         % (pattern, n, w, h, fps, freq, int(secs * 48000 / 1024), path))


def video_silent(path, pattern, secs, w=640, h=360, fps=25):
    _run("videotestsrc pattern=%s num-buffers=%d ! video/x-raw,width=%d,height=%d,framerate=%d/1 ! x264enc speed-preset=ultrafast "
         "! h264parse ! mp4mux ! filesink location=\"%s\"" % (pattern, int(secs * fps), w, h, fps, path))


def tone(path, secs, freq, volume=0.5):
    enc = "vorbisenc ! oggmux" if path.endswith(".ogg") else "wavenc"
    _run("audiotestsrc freq=%d volume=%f num-buffers=%d samplesperbuffer=1024 ! audio/x-raw,rate=48000,channels=2 ! audioconvert "
         "! %s ! filesink location=\"%s\"" % (freq, volume, int(secs * 48000 / 1024), enc, path))


def picture(path, rgb, w=800, h=600):
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
    pb.fill((rgb[0] << 24) | (rgb[1] << 16) | (rgb[2] << 8) | 0xFF)
    pb.savev(path, "png", [], [])


def make(d):
    os.makedirs(d, exist_ok=True)
    out = {"red": os.path.join(d, "Red Clip.mp4"), "blue": os.path.join(d, "Blue Clip.mp4"),
           "music": os.path.join(d, "Music Bed.ogg"), "speech": os.path.join(d, "Voice.wav"),
           "photo": os.path.join(d, "Green Photo.png"), "silent": os.path.join(d, "White Silent.mp4")}
    if not os.path.exists(out["red"]):
        video(out["red"], "red", 4, 440)
    if not os.path.exists(out["blue"]):
        video(out["blue"], "blue", 4, 660)
    if not os.path.exists(out["silent"]):
        video_silent(out["silent"], "white", 3)
    if not os.path.exists(out["music"]):
        tone(out["music"], 12, 330, 0.4)
    if not os.path.exists(out["speech"]):
        tone(out["speech"], 3, 880, 0.6)
    if not os.path.exists(out["photo"]):
        picture(out["photo"], (0, 200, 0))
    return out


def frame_color(path, t, w=64, h=36):
    """Average colour of the frame shown at t seconds. Decodes from the start (a seek in some
    decoders lands on the wrong frame, and the test files are short)."""
    p = Gst.parse_launch("filesrc location=\"%s\" ! decodebin ! videoconvert ! videoscale "
                         "! video/x-raw,format=RGB,width=%d,height=%d ! appsink name=s sync=false" % (path, w, h))
    s = p.get_by_name("s")
    p.set_state(Gst.State.PLAYING)
    want, best = int(t * SECOND), None
    while True:
        sample = s.emit("try-pull-sample", 10 * SECOND)
        if sample is None:
            break
        buf = sample.get_buffer()
        if buf.pts > want and best is not None:
            break
        ok, mi = buf.map(Gst.MapFlags.READ)
        best = bytes(mi.data)
        buf.unmap(mi)
    p.set_state(Gst.State.NULL)
    if best is None:
        return None
    stride = (w * 3 + 3) // 4 * 4
    tot = [0, 0, 0]
    for y in range(h):
        row = best[y * stride:y * stride + w * 3]
        for k in range(3):
            tot[k] += sum(row[k::3])
    return tuple(v // (w * h) for v in tot)


def loudness(path, t, span=0.4):
    """RMS level (0..1) of the sound from t to t+span."""
    import array
    import math
    uri = Gst.filename_to_uri(path)
    p = Gst.parse_launch("uridecodebin name=d uri=\"%s\" audioconvert name=c ! audioresample "
                         "! audio/x-raw,format=S16LE,channels=1,rate=16000 ! appsink name=s sync=false" % uri)
    s = p.get_by_name("s")
    conv = p.get_by_name("c")

    def pad_added(_d, pad):    # only the sound is wanted; video pads stay unlinked
        caps = pad.get_current_caps() or pad.query_caps(None)
        if caps.to_string().startswith("audio/") and not conv.get_static_pad("sink").is_linked():
            pad.link(conv.get_static_pad("sink"))
    p.get_by_name("d").connect("pad-added", pad_added)
    p.set_state(Gst.State.PAUSED)
    p.get_state(10 * SECOND)
    p.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, Gst.SeekType.SET, int(t * SECOND),
           Gst.SeekType.SET, int((t + span) * SECOND))
    p.set_state(Gst.State.PLAYING)
    samples = array.array("h")
    while True:
        smp = s.emit("try-pull-sample", 5 * SECOND)
        if smp is None:
            break
        buf = smp.get_buffer()
        ok, mi = buf.map(Gst.MapFlags.READ)
        samples.frombytes(bytes(mi.data)[: len(mi.data) // 2 * 2])
        buf.unmap(mi)
    p.set_state(Gst.State.NULL)
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768.0


def media_duration(path):
    gi.require_version("GstPbutils", "1.0")
    from gi.repository import GstPbutils
    d = GstPbutils.Discoverer.new(10 * SECOND).discover_uri(Gst.filename_to_uri(path))
    vids = d.get_video_streams()
    return d.get_duration() / SECOND, (vids[0].get_width(), vids[0].get_height()) if vids else None


_ = GLib
