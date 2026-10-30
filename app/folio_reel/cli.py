"""Rendering without a window (R3-08: Folio Show's Create a Video goes through here).

  folio-reel --render PROJECT.reel OUT.mp4 [--preset 720p|1080p|4k]
      the project, as Export does it
  folio-reel --render --raw WIDTHxHEIGHT FPS OUT.mp4|OUT.webm
      raw BGRA frames on standard input (what Folio Show draws), encoded by Reel's engine
"""
import os
import sys

from gi.repository import GLib, Gst

from . import engine, model


def _say(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def render(args):
    engine.init()
    fmt = "webm" if any(a.lower().endswith(".webm") for a in args) else "mp4"
    preset = None
    if "--preset" in args:
        i = args.index("--preset")
        preset = args[i + 1]
        del args[i:i + 2]
    if "--raw" in args:
        i = args.index("--raw")
        try:
            size, fps, out = args[i + 1], args[i + 2], args[i + 3]
            w, h = (int(v) for v in size.lower().split("x"))
            fps = int(float(fps))
        except (IndexError, ValueError):
            _say("usage: folio-reel --render --raw WIDTHxHEIGHT FPS OUT.mp4")
            return 2
        return render_raw(w, h, fps, out, fmt)
    if len(args) < 2:
        _say("usage: folio-reel --render PROJECT.reel OUT.mp4 [--preset 1080p]")
        return 2
    src, out = args[0], args[1]
    try:
        project = model.Project.load(src)
    except (OSError, ValueError, model.EditError) as e:
        _say("Can't open %s: %s" % (src, e))
        return 1
    missing = engine.missing_encoders(fmt)
    if missing:
        _say("Can't make %s files: missing %s" % (fmt, ", ".join(missing)))
        return 1
    last = [-1]

    def progress(f):
        pct = int(f * 100)
        if pct != last[0]:
            last[0] = pct
            _say("%d%%" % pct)
    ex = engine.Exporter(project, out, fmt, preset or "1080p", on_progress=progress)
    ok = ex.run_sync(24 * 3600)
    if not ok:
        _say("Export failed: %s" % (ex.error or "unknown error"))
        return 1
    return 0


def render_raw(w, h, fps, out, fmt="mp4"):
    """Frames on stdin (BGRA, w*h*4 bytes each) to a video file."""
    if fmt == "webm":
        venc = "vp9enc deadline=1 cpu-used=8 row-mt=true" if Gst.ElementFactory.find("vp9enc") else "vp8enc deadline=1"
        mux = "webmmux"
    else:
        venc = "x264enc speed-preset=faster ! video/x-h264,profile=high ! h264parse"
        mux = "mp4mux faststart=true"
    loc = out.replace("\\", "\\\\").replace('"', '\\"')
    desc = ("fdsrc fd=0 blocksize=%d ! rawvideoparse width=%d height=%d format=bgra framerate=%d/1 "
            "! videoconvert ! video/x-raw,format=I420 ! %s ! %s ! filesink location=\"%s\""
            % (w * h * 4, w, h, fps, venc, mux, loc))
    try:
        p = Gst.parse_launch(desc)
    except GLib.Error as e:
        _say("Can't render: %s" % e.message)
        return 1
    p.set_state(Gst.State.PLAYING)
    msg = p.get_bus().timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    if msg is None or msg.type == Gst.MessageType.ERROR:
        _say("Render failed: %s" % (msg.parse_error()[0].message if msg else "no end"))
        try:
            os.remove(out)
        except OSError:
            pass
        return 1
    return 0
