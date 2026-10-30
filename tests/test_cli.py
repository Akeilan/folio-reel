"""Rendering without a window (R3-08): raw frames from Folio Show, and a saved project."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkmedia  # noqa: E402

APP = os.environ.get("REEL_CMD")          # the installed /usr/bin/folio-reel, or python3 -m folio_reel
CMD = [APP] if APP else [sys.executable, "-m", "folio_reel"]
ENV = dict(os.environ)
if not APP:
    ENV["PYTHONPATH"] = os.path.join(HERE, "..", "app")
FAILS = []
N = [0]


def check(ok, what, info=None):
    N[0] += 1
    print(("ok   " if ok else "FAIL ") + what + ("" if ok or info is None else "  -- %r" % (info,)))
    if not ok:
        FAILS.append(what)


T = tempfile.mkdtemp(prefix="reel_cli_")
w, h, fps = 320, 180, 25
frames = b""
for i in range(50):                   # 2 s: red, then green (BGRA)
    px = bytes((0, 0, 255, 255)) if i < 25 else bytes((0, 255, 0, 255))
    frames += px * (w * h)
for ext in ("mp4", "webm"):
    out = os.path.join(T, "show." + ext)
    p = subprocess.run(CMD + ["--render", "--raw", "%dx%d" % (w, h), str(fps), out], input=frames, env=ENV,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    check(p.returncode == 0 and os.path.exists(out), "Show's frames become a %s" % ext.upper(), p.stderr[-300:])
    if os.path.exists(out):
        d, size = mkmedia.media_duration(out)
        check(abs(d - 2.0) < 0.15 and size == (w, h), "  2 s at %dx%d" % (w, h), (d, size))
        a, b = mkmedia.frame_color(out, 0.5), mkmedia.frame_color(out, 1.5)
        check(a[0] > 180 and a[1] < 70 and b[1] > 180 and b[0] < 70, "  the frames in order", (a, b))
p = subprocess.run(CMD + ["--render", "--raw", "bad", "25", os.path.join(T, "x.mp4")], input=b"", env=ENV,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
check(p.returncode == 2 and b"usage" in p.stderr, "a bad size says how to use it")

# a saved project
M = mkmedia.make(os.path.join(tempfile.gettempdir(), "reel_media"))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
from folio_reel import engine, model  # noqa: E402
pr = model.Project()
for k in ("red", "blue"):
    pr.add_media(engine.probe(M[k]))
pr.add_clip("video", pr.media[0])
pr.add_clip("video", pr.media[1])
proj = os.path.join(T, "p.reel")
pr.save(proj)
out = os.path.join(T, "p.mp4")
p = subprocess.run(CMD + ["--render", proj, out, "--preset", "720p"], env=ENV, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, timeout=300)
check(p.returncode == 0 and os.path.exists(out), "a project renders from the command line", p.stderr[-300:])
if os.path.exists(out):
    d, size = mkmedia.media_duration(out)
    check(abs(d - 8.0) < 0.3 and size == (1280, 720), "  8 s at 720p", (d, size))
    check(b"100%" in p.stderr, "  with progress")
p = subprocess.run(CMD + ["--version"], env=ENV, stdout=subprocess.PIPE, timeout=30)
check(p.stdout.startswith(b"Folio Reel "), "--version", p.stdout)
print("%d checks, %d failed" % (N[0], len(FAILS)))
print("all passed" if not FAILS else "FAILED")
sys.exit(1 if FAILS else 0)
