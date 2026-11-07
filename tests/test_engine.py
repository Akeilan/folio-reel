"""Folio Reel's engine: the project model (R3-01, R3-03, R3-05) and the GES timeline it becomes,
checked by rendering and looking at the frames and the sound (R3-03..R3-06)."""
import copy
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if not os.environ.get("PYTHONPATH"):
    sys.path.insert(0, os.path.join(HERE, "..", "app"))
import mkmedia  # noqa: E402
from folio_reel import engine, model  # noqa: E402

N = [0]
FAILS = []


def check(ok, what, info=None):
    N[0] += 1
    print(("ok   " if ok else "FAIL ") + what + ("" if ok or info is None else "  -- %r" % (info,)))
    sys.stdout.flush()
    if not ok:
        FAILS.append(what)
    return ok


def close(a, b, tol=0.06):
    return abs(a - b) <= tol


def raises(fn):
    try:
        fn()
    except model.EditError:
        return True
    return False


T = tempfile.mkdtemp(prefix="reel_test_")
MEDIA = os.environ.get("REEL_MEDIA") or os.path.join(tempfile.gettempdir(), "reel_media")
M = mkmedia.make(MEDIA)

# ---------------------------------------------------------------- probing media
info = {k: engine.probe(p) for k, p in M.items()}
check(close(info["red"]["duration"], 4.0, 0.1) and info["red"]["has_video"] and info["red"]["has_audio"]
      and (info["red"]["width"], info["red"]["height"]) == (640, 360), "a video: length, picture, sound, size", info["red"])
check(info["music"]["has_audio"] and not info["music"]["has_video"] and close(info["music"]["duration"], 12, 0.2),
      "a sound file")
check(info["photo"]["is_image"] and info["photo"]["width"] == 800 and info["photo"]["duration"] == model.IMAGE_SECONDS,
      "a picture (shown five seconds unless changed)")
check(info["silent"]["has_video"] and not info["silent"]["has_audio"], "a video without sound")
bad = os.path.join(T, "broken.mp4")
open(bad, "wb").write(b"not a video" * 100)
check(raises(lambda: engine.probe(bad)), "a file that isn't media says so")
pb = engine.thumbnail(info["red"], 1.0, 160)
check(pb is not None and pb.get_width() == 160 and pb.get_height() == 90, "a thumbnail of a video",
      pb and (pb.get_width(), pb.get_height()))
px = pb.get_pixels() if pb else b"\0\0\0"
check(pb is not None and px[0] > 180 and px[1] < 60, "of the right frame (red)", tuple(px[:3]))
pb2 = engine.thumbnail(info["photo"], None, 160)
check(pb2 is not None and pb2.get_width() == 160, "and of a picture")

# ---------------------------------------------------------------- the model: R3-01
p = model.Project()
for k in ("red", "blue", "music", "speech", "photo", "silent"):
    p.add_media(info[k])
check(len(p.media) == 6, "Import: the media bin")
p.add_media(info["red"])
check(len(p.media) == 6, "importing the same file twice keeps one")
a = p.add_clip("video", p.media_by_uri(info["red"]["uri"]))
b = p.add_clip("video", p.media_by_uri(info["blue"]["uri"]))
check(close(a["start"], 0) and close(b["start"], a["duration"]), "clips go one after another on the track")
check(raises(lambda: p.add_clip("audio", p.media_by_uri(info["silent"]["uri"]))), "a video without sound can't go on the Audio track")
ph = p.add_clip("video", p.media_by_uri(info["photo"]["uri"]), at=a["duration"], insert=True)
check(close(ph["start"], a["duration"]) and close(b["start"], a["duration"] + 5.0), "insert: later clips make room")
p.delete([ph["id"]], ripple=True)
check(close(b["start"], a["duration"]), "ripple delete closes the gap")
p.undo()
ph = p.clip(ph["id"])
check(ph is not None and close(p.clip(b["id"])["start"], a["duration"] + 5), "Undo brings it back")
p.redo()
check(p.clip(ph["id"]) is None and close(p.clip(b["id"])["start"], 4.0, 0.1), "Redo")
a, b = p.clip(a["id"]), p.clip(b["id"])
second = p.split(a["id"], 1.5)
a = p.clip(a["id"])
check(close(a["duration"], 1.5) and close(second["start"], 1.5) and close(second["inpoint"], 1.5)
      and close(end_of := second["start"] + second["duration"], 4.0, 0.1), "Split at the playhead")
check(raises(lambda: p.split(a["id"], 3.0)), "split away from a clip says so")
p.trim(second["id"], "start", 2.0)
second = p.clip(second["id"])
check(close(second["start"], 2.0) and close(second["inpoint"], 2.0), "trim the start (the in point follows)")
p.trim(second["id"], "start", 0.5)
second = p.clip(second["id"])
check(close(second["start"], 1.5), "a trim stops at the clip before it", second["start"])
p.trim(second["id"], "end", 9.0)
second = p.clip(second["id"])
check(close(second["start"] + second["duration"], 4.0, 0.1), "and at the end of the media / the next clip")
p.trim(b["id"], "end", 6.0)
b = p.clip(b["id"])
check(close(b["start"] + b["duration"], 6.0), "trim the end")
p.undo()
b = p.clip(b["id"])
m = p.move(b["id"], 10.0)
check(close(m["start"], 10.0), "move a clip")
m = p.move(b["id"], 1.0)
check(close(m["start"], 4.0, 0.1) or close(m["start"] + m["duration"], 0.0), "dropped on another clip, it goes to the nearest free place",
      m["start"])
m = p.move(b["id"], 4.15, tolerance=0.2)
check(close(m["start"], 4.0, 0.1), "snapping to clip edges", m["start"])
p.snapping = False
m = p.move(b["id"], 5.3, tolerance=0.5)
check(close(m["start"], 5.3), "snapping off")
p.snapping = True
m = p.move(b["id"], 7.9, tolerance=0.2, playhead=8.0)
check(close(m["start"], 8.0), "snapping to the playhead")
p.move(b["id"], 4.0)
t1 = p.add_clip("titles", "title", at=0, text="My Film")
check(t1["kind"] == "title" and t1["name"] == "My Film" and close(t1["duration"], model.TITLE_SECONDS), "a title card")
check(raises(lambda: p.move(t1["id"], 0, track="video")), "titles stay on the Titles track")
mus = p.add_clip("music", p.media_by_uri(info["music"]["uri"]), at=0)
sp = p.add_clip("audio", p.media_by_uri(info["speech"]["uri"]), at=2.0)
pts = p.duck_points(p.clip(mus["id"]), level=0.3, ramp=0.4)
check(any(close(t, 2.0) and close(v, 0.3) for t, v in pts) and any(close(t, 5.4) and v == 1.0 for t, v in pts),
      "the music bed dips under speech (R3-05)", pts)
p.set(mus["id"], music_bed=True)
g = engine.gain_points(p, p.clip(mus["id"]))
check(min(v for _t, v in g) < 0.35, "and the dip is in the music's gain")

# speed and transitions (R3-03)
q = model.Project()
for k in ("red", "blue", "photo"):
    q.add_media(info[k])
qa = q.add_clip("video", q.media_by_uri(info["red"]["uri"]))
qb = q.add_clip("video", q.media_by_uri(info["blue"]["uri"]))
q.set_speed(qa["id"], 2.0)
qa, qb = q.clip(qa["id"]), q.clip(qb["id"])
check(close(qa["duration"], 2.0, 0.1) and close(qb["start"], qa["duration"]), "2× speed halves the clip; the next one follows")
q.set_transition(qb["id"], "crossfade", 1.0)
qb = q.clip(qb["id"])
check(close(qb["start"], qa["duration"] - 1.0) and qb["transition"]["type"] == "crossfade", "a crossfade overlaps the clips")
q.set_transition(qb["id"], "wipe-right", 0.5)
qb = q.clip(qb["id"])
check(close(qb["start"], qa["duration"] - 0.5), "changing it to a wipe")
q.set_transition(qb["id"], None)
qb = q.clip(qb["id"])
check(close(qb["start"], qa["duration"]) and qb["transition"] is None, "and taking it away")
check(raises(lambda: q.set_transition(qa["id"], "crossfade")), "the first clip has nothing to transition from")

# saving and opening
path = os.path.join(T, "film.reel")
p.save(path)
p2 = model.Project.load(path)
check(len(p2.media) == 6 and sum(len(p2.track(t)) for t in model.TRACKS) == sum(len(p.track(t)) for t in model.TRACKS),
      "a project is saved and opened")
moved = os.path.join(T, "moved")
os.makedirs(os.path.join(moved, "media"))
shutil.copy(M["red"], os.path.join(moved, "media", "Red Clip.mp4"))
pr = model.Project()
pr.add_media(engine.probe(os.path.join(moved, "media", "Red Clip.mp4")))
pr.add_clip("video", pr.media[0])
pr.save(os.path.join(moved, "x.reel"))
shutil.move(moved, moved + "2")
pr2 = model.Project.load(os.path.join(moved + "2", "x.reel"))
check(not pr2.missing_media() and os.path.exists(model.uri_to_path(pr2.media[0]["uri"])),
      "a project moved with its media finds it again")

# ---------------------------------------------------------------- rendering (R3-06) and what's in it
def render(project, name, fmt="mp4", preset="720p"):
    out = os.path.join(T, name)
    prog = []
    e = engine.Exporter(project, out, fmt, preset, on_progress=prog.append)
    ok = e.run_sync(300)
    return out if ok and os.path.exists(out) else None, prog, e


r = model.Project()
for k in ("red", "blue", "photo", "music", "speech"):
    r.add_media(info[k])
ra = r.add_clip("video", r.media_by_uri(info["red"]["uri"]))
rb = r.add_clip("video", r.media_by_uri(info["blue"]["uri"]))
out, prog, e = render(r, "plain.mp4")
dur, size = mkmedia.media_duration(out) if out else (0, None)
check(out and close(dur, 8.0, 0.2) and size == (1280, 720), "Export: MP4 at 720p", (dur, size))
check(prog and prog[-1] == 1.0 and len(prog) >= 2, "with progress")
c1, c2 = mkmedia.frame_color(out, 1.0), mkmedia.frame_color(out, 6.0)
check(c1[0] > 180 and c1[2] < 60 and c2[2] > 180 and c2[0] < 60, "the clips in order (red, then blue)", (c1, c2))
check(mkmedia.loudness(out, 1.0) > 0.05, "with their sound")
out, prog, e = render(r, "plain.webm", "webm", "720p")
dur, size = mkmedia.media_duration(out) if out else (0, None)
check(out and close(dur, 8.0, 0.25) and size == (1280, 720), "WebM", (dur, size))
r.set_size(1080, 1080)
out, prog, e = render(r, "square.mp4", "mp4", "1080p")
check(out and mkmedia.media_duration(out)[1] == (1080, 1080), "a square project keeps its shape", out and mkmedia.media_duration(out))
r.set_size(1920, 1080)
# a long render keeps going while you work, and can be stopped
e = engine.Exporter(r, os.path.join(T, "cancel.mp4"), "mp4", "1080p")
e.start()
import time
from gi.repository import GLib
for _ in range(20):
    GLib.MainContext.default().iteration(False)
    time.sleep(0.01)
e.cancel()
check(e.done and e.error == "cancelled" and not os.path.exists(os.path.join(T, "cancel.mp4")), "Cancel stops it and leaves no half file")

# effects and transitions, looked at in the frames
r.set(ra["id"], color={"saturation": 0.0})
r.set(ra["id"], fade_in=1.0)
r.set_transition(rb["id"], "crossfade", 1.0)
out, prog, e = render(r, "effects.mp4")
f0, f2, fx = mkmedia.frame_color(out, 0.05), mkmedia.frame_color(out, 2.0), mkmedia.frame_color(out, 3.5)
check(max(f2) - min(f2) < 25 and f2[0] > 40, "Colour: a black-and-white red clip is grey", f2)
check(sum(f0) < sum(f2) * 0.4, "Fade in from black", (f0, f2))
check(fx[2] > 50 and fx[0] > 30, "Crossfade: halfway, both pictures", fx)
r.set_transition(rb["id"], "wipe-right", 1.0)
out, prog, e = render(r, "wipe.mp4")
check(out is not None, "a wipe renders")
r.set_transition(rb["id"], "dip-black", 1.0)
out, prog, e = render(r, "dip.mp4")
fd = mkmedia.frame_color(out, 3.99)
check(sum(fd) < 120, "Fade to Black: dark at the cut", fd)
r.set_transition(rb["id"], None)
r.set(ra["id"], fade_in=0.0, color={"saturation": 1.0})
r.set_speed(ra["id"], 2.0)
out, prog, e = render(r, "speed.mp4")
check(close(mkmedia.media_duration(out)[0], 6.0, 0.25), "Speed 2×: the film is shorter", mkmedia.media_duration(out)[0])
r.set_speed(ra["id"], 1.0)
# zoom and crop on a picture
rp = r.add_clip("video", r.media_by_uri(info["photo"]["uri"]))
r.set(rp["id"], zoom=1.5)
r.set(rp["id"], panzoom="in")
out, prog, e = render(r, "photo.mp4")
fp = mkmedia.frame_color(out, rp["start"] + 2.0)
check(fp[1] > 150 and fp[0] < 50, "a picture fills the frame, zoomed and moving (pan and zoom)", fp)
r.delete([rp["id"]])
# titles (R3-04)
tt = r.add_clip("titles", "title", at=0, text="HELLO")
out, prog, e = render(r, "title.mp4")
ft = mkmedia.frame_color(out, 1.0)
check(ft[0] < 120, "a title card covers the picture (black with white text)", ft)
r.set(tt["id"], bg_color="#00000000")
out, prog, e = render(r, "lower.mp4")
fl = mkmedia.frame_color(out, 1.0)
check(fl[0] > 150, "a see-through title shows the clip underneath", fl)
r.delete([tt["id"]])

# ---------------------------------------------------------------- R4-04 preview size and proxies
big = os.path.join(MEDIA, "Big Clip.mp4")
if not os.path.exists(big):
    mkmedia.video(big, "smpte", 3, 440, w=1920, h=1080)
bi = engine.probe(big)
check(engine.proxy_size(bi) == (640, 360), "a small copy keeps the shape", engine.proxy_size(bi))
check(engine.proxy_size({"width": 320, "height": 240}) == (320, 240), "and a small file is left as it is")
engine.forget_proxies()
prog = []
pp = engine.make_proxy(bi, on_progress=prog.append)
check(pp and os.path.exists(pp), "a small copy is made", pp)
if pp:
    pi = engine.probe(pp)
    check((pi["width"], pi["height"]) == (640, 360) and close(pi["duration"], bi["duration"], 0.2),
          "same film, fewer pixels", (pi["width"], pi["height"], round(pi["duration"], 2)))
    check(os.path.getsize(pp) < os.path.getsize(big), "and a smaller file",
          (os.path.getsize(pp), os.path.getsize(big)))
    check(prog and prog[-1] == 1.0, "with progress", len(prog))
    check(engine.make_proxy(bi) == pp, "asking again uses the copy already there")

pr = model.Project()
pr.add_media(bi)
pr.add_clip("video", pr.media_by_uri(bi["uri"]))
tl = engine.make_timeline(pr.width, pr.height, pr.fps)
engine.build(pr, tl, proxies=True)
uris = [c.get_asset().get_id() for layer in tl.get_layers() for c in layer.get_clips() if c.get_asset()]
check(pp and any("proxies" in u for u in uris), "the preview plays the small copy", uris)
tl2 = engine.make_timeline(pr.width, pr.height, pr.fps)
engine.build(pr, tl2, proxies=False)
uris2 = [c.get_asset().get_id() for layer in tl2.get_layers() for c in layer.get_clips() if c.get_asset()]
check(all("proxies" not in u for u in uris2), "an export always uses the original", uris2)

pv2 = engine.Preview(pr)
check(pv2.preview_size() == (pr.width, pr.height), "the preview starts at full size", pv2.preview_size())
pv2.set_quality(2)
check(pv2.preview_size() == (pr.width // 2, pr.height // 2), "half size", pv2.preview_size())
pv2.set_quality(4)
check(pv2.preview_size() == (pr.width // 4, pr.height // 4), "quarter size", pv2.preview_size())
pv2.set_quality(3)
check(pv2.preview_size() == (pr.width // 4, pr.height // 4), "and nothing else is accepted", pv2.preview_size())
pv2.set_quality(1)
check(close(pv2.duration(), pr.duration(), 0.2), "the film is the same length whatever the preview size",
      (pv2.duration(), pr.duration()))
pv2.close()
check(engine.forget_proxies() >= 1, "the small copies can be thrown away")

# ---------------------------------------------------------------- R4-03 subtitles
from folio_reel import subtitles  # noqa: E402

srt = """1
00:00:01,000 --> 00:00:03,500
Hello there

2
00:00:04,000 --> 00:00:06,000
Second line
and more
"""
ents = subtitles.parse(srt)
check(ents == [(1.0, 3.5, "Hello there"), (4.0, 6.0, "Second line\nand more")], "an .srt is read", ents)
check(subtitles.parse(subtitles.write(ents)) == ents, "and written back the same")
check(subtitles.fmt_time(3661.25) == "01:01:01,250", "times are written as SRT does", subtitles.fmt_time(3661.25))
odd = subtitles.parse("00:00:02.500 --> 00:00:04.000\nNo number, stops not commas\n\n\nrubbish\n")
check(odd == [(2.5, 4.0, "No number, stops not commas")], "a file without numbering, with stops, and a bad block", odd)
check(subtitles.parse("") == [] and subtitles.write([]) == "", "nothing in, nothing out")

sp = model.Project()
sp.add_media(info["red"])
sp.add_clip("video", sp.media_by_uri(info["red"]["uri"]))
made = sp.add_subtitles(ents)
caps = [c for c in sp.track("titles") if c["kind"] == "caption"]
check(len(made) == 2 and len(caps) == 2, "they become caption clips on the Titles track", len(caps))
check(close(caps[0]["start"], 1.0) and close(caps[0]["duration"], 2.5) and caps[0]["text"] == "Hello there",
      "at their own times", (caps[0]["start"], caps[0]["duration"]))
check(subtitles.from_clips(sp.track("titles")) == ents, "and come back out as the same subtitles")
sp.undo()
check(not [c for c in sp.track("titles") if c["kind"] == "caption"], "importing them is one undo step")

# ---------------------------------------------------------------- R4-02 chroma key
green_path = os.path.join(MEDIA, "Green Screen.mp4")
if not os.path.exists(green_path):
    mkmedia.video_silent(green_path, "green", 3)
gi_ = engine.probe(green_path)
r.add_media(gi_)
gc = r.add_clip("titles", r.media_by_uri(gi_["uri"]), at=0)
out, prog, e = render(r, "chroma-off.mp4")
fo = mkmedia.frame_color(out, 1.0)
check(fo[1] > 120 and fo[0] < 90, "the green screen covers the picture while keying is off", fo)
r.set(gc["id"], chroma=True)
out, prog, e = render(r, "chroma-on.mp4")
fk = mkmedia.frame_color(out, 1.0)
check(fk[0] > 150 and fk[1] < 90, "keying the green out shows the clip underneath", fk)
check("alpha method=custom" in (engine.chroma_effect(r.clip(gc["id"])) or ""), "the key is an alpha element")
check(engine.chroma_target("blue") == (0, 0, 255) and engine.chroma_target("green") == (0, 255, 0)
      and engine.chroma_target("#204080") == (32, 64, 128), "the colour keyed out")
r.set(gc["id"], chroma_color="blue")
out, prog, e = render(r, "chroma-blue.mp4")
fb = mkmedia.frame_color(out, 1.0)
check(fb[1] > 120 and fb[0] < 90, "keying blue leaves a green screen alone", fb)
r.set(gc["id"], chroma_color="green", chroma_tolerance=1.0)
check("angle=1" in engine.chroma_effect(r.clip(gc["id"])), "tolerance and softness reach the element",
      engine.chroma_effect(r.clip(gc["id"])))
check(engine.chroma_effect({"chroma": False}) is None, "and nothing is added when it is off")
r.delete([gc["id"]])
# audio: volume, fades, the music bed (R3-05)
r.set(ra["id"], volume=0.0)
out, prog, e = render(r, "quiet.mp4")
check(mkmedia.loudness(out, 1.0) < 0.01 and mkmedia.loudness(out, 6.0) > 0.05, "a clip's volume", (mkmedia.loudness(out, 1.0), mkmedia.loudness(out, 6.0)))
r.set(ra["id"], volume=1.0)
r.set(rb["id"], volume=0.0)
mb = r.add_clip("music", r.media_by_uri(info["music"]["uri"]), at=0)
r.set(ra["id"], volume=0.0)
vo = r.add_clip("audio", r.media_by_uri(info["speech"]["uri"]), at=4.5)
out, prog, e = render(r, "bed_off.mp4")
loud_free = mkmedia.loudness(out, 1.0)
r.set(mb["id"], music_bed=True)
r.set(vo["id"], volume=0.0, label="x")
r.set(vo["id"], muted=False)
out, prog, e = render(r, "bed_on.mp4")
# the voice is silent (volume 0) but still counts as speech: the music dips under it
check(mkmedia.loudness(out, 5.5) < mkmedia.loudness(out, 1.0) * 0.6,
      "the music bed dips under the voice-over", (mkmedia.loudness(out, 1.0), mkmedia.loudness(out, 5.5), loud_free))
r.set(mb["id"], fade_out=2.0)
out, prog, e = render(r, "fade.mp4")
end = r.clip(mb["id"])["start"] + r.clip(mb["id"])["duration"]
check(out is not None and mkmedia.loudness(out, min(end, mkmedia.media_duration(out)[0]) - 0.3, 0.25) <
      mkmedia.loudness(out, 1.0), "a fade out at the end of the music")
r.set_keyframes(mb["id"], [(0, 1.0), (2, 1.0), (2.5, 0.1), (3.5, 0.1)])
g = engine.gain_points(r, r.clip(mb["id"]))
check(engine._piecewise(g, 3.0) < 0.2 and engine._piecewise(g, 1.0) > 0.9, "volume points (keyframes)", g)

# the preview
os.environ.setdefault("FOLIO_REEL_VIDEOSINK", "fakesink")
os.environ.setdefault("FOLIO_REEL_AUDIOSINK", "fakesink")
pv = engine.Preview(r)
check(close(pv.duration(), r.duration(), 0.1), "Preview: the timeline's length", (pv.duration(), r.duration()))
pv.seek(5.0)
for _ in range(50):
    GLib.MainContext.default().iteration(False)
    time.sleep(0.01)
check(close(pv.position(), 5.0, 0.05), "seeking (frame-accurate)", pv.position())
snap = pv.snapshot()
spx = snap.get_pixels() if snap else b"\0\0\0"
check(snap is not None and spx[2] > 150 and spx[0] < 80, "the preview shows the frame at the playhead", tuple(spx[:3]))
pv.seek(1.0)
snap = pv.snapshot()
spx = snap.get_pixels() if snap else b"\0\0\0"
check(snap is not None and spx[0] > 150 and spx[2] < 80, "and follows a seek back (the red clip)", tuple(spx[:3]))
pv.seek(5.0)
pv.step(1)
check(close(pv.position(), 5.0 + 1.0 / r.fps, 0.02), "one frame on", pv.position())
pv.play(2.0)
time.sleep(0.6)
for _ in range(20):
    GLib.MainContext.default().iteration(False)
pos = pv.position()
check(pos > 5.4, "fast forward (L L)", pos)
pv.pause()
r.delete([vo["id"]])
pv.refresh()
check(close(pv.duration(), r.duration(), 0.1), "the preview follows edits")
check(pv.level is not None, "the preview has a level meter on its sound (R4-01)")
pv.close()

# ---------------------------------------------------------------- R4-01 waveforms and levels
loud = os.path.join(MEDIA, "loud.wav")
quiet = os.path.join(MEDIA, "quiet.wav")
if not os.path.exists(loud):
    mkmedia.tone(loud, 2.0, 440, 0.9)
if not os.path.exists(quiet):
    mkmedia.tone(quiet, 2.0, 440, 0.1)
wl = engine.waveform(engine.probe(loud))
wq = engine.waveform(engine.probe(quiet))
check(len(wl) == engine.wave_points(2.0) and len(wl) == 50, "a waveform has a peak every 40ms", len(wl))
check(0.8 < max(wl) <= 1.0, "a loud tone peaks near the top", max(wl))
check(0.05 < max(wq) < 0.2, "a quiet one stays low", max(wq))
check(min(wl) > 0.5, "a steady tone is steady all the way through", min(wl))
silent = engine.probe(M["silent"])
check(engine.waveform(silent) == [] or max(engine.waveform(silent)) < 0.01, "a silent film draws nothing")
check(engine.wave_points(3600) == engine.WAVE_MAX, "a very long film is capped", engine.wave_points(3600))

engine.forget_waves()
check(engine.wave_cached(engine.probe(loud)["uri"]) is None, "nothing is cached to begin with")
got = []
engine.waveform_async(engine.probe(loud), lambda w: got.append(w)).join()
check(engine.wave_cached(engine.probe(loud)["uri"]) == wl, "reading it in the background caches it")

check(engine.db_to_bar(0.0) == 1.0 and engine.db_to_bar(-60.0) == 0.0 and engine.db_to_bar(-120.0) == 0.0,
      "0 dB fills the meter, -60 dB empties it")
check(close(engine.db_to_bar(-30.0), 0.5, 0.01), "and -30 dB is half", engine.db_to_bar(-30.0))

# ---------------------------------------------------------------- R4-05 markers
p = model.Project()
p.add_media(engine.probe(M["red"]))
c = p.add_clip("video", p.media[0])
first = p.add_marker(1.5)
second = p.add_marker(0.5, "Intro", "red")
check([(m["t"], m["name"]) for m in p.markers()] == [(0.5, "Intro"), (1.5, "")], "markers come back in time order", p.markers())
check(p.marker(second)["color"] == "red", "with the colour they were given")
check(p.add_marker(1.5, "Chorus") == first, "a marker already there is named, not doubled up")
check(p.marker(first)["name"] == "Chorus" and len(p.markers()) == 2, "and keeps its place", p.markers())
check(p.next_marker(0.0)["t"] == 0.5 and p.next_marker(0.5)["t"] == 1.5, "Next Marker walks forward")
check(p.prev_marker(2.0)["t"] == 1.5 and p.prev_marker(0.5) is None, "Previous Marker walks back")
check(p.marker_at(1.52, 0.1) == p.marker(first) and p.marker_at(1.9, 0.1) is None, "a marker is found near a time")
check(1.5 in p.snap_points() and 0.5 in p.snap_points(), "clips snap to markers", p.snap_points())
p.set_marker(first, name="Verse", color="blue")
check(p.marker(first)["name"] == "Verse" and p.marker(first)["color"] == "blue", "a marker is renamed and recoloured")
p.undo()
check(p.marker(first)["name"] == "Chorus", "and that is one undo step")
mf = os.path.join(T, "markers.reel")
p.save(mf)
back = model.Project.load(mf)
check([(m["t"], m["name"], m["color"]) for m in back.markers()] == [(0.5, "Intro", "red"), (1.5, "Chorus", "yellow")],
      "markers are saved with the project", back.markers())
check(back.remove_markers([second]) == 1 and len(back.markers()) == 1, "a marker is deleted")
back.undo()
check(len(back.markers()) == 2, "and comes back on undo")
check(back.clear_markers() == 2 and back.markers() == [], "Delete All Markers empties the ruler")
old_project = model.Project({"version": 1, "width": 1920, "height": 1080, "fps": 30, "media": [],
                             "tracks": {t: [] for t in model.TRACKS}, "next_id": 1})
check(old_project.markers() == [] and old_project.add_marker(2.0) is not None, "a project from before markers opens fine")
check(c["id"] is not None, "the clip is still there")

# ---------------------------------------------------------------- R4-06 groups of clips
g = model.Project()
for k in ("red", "blue", "music"):
    g.add_media(engine.probe(M[k]))
ga = g.add_clip("video", g.media[0])
gb = g.add_clip("video", g.media[1], at=model.end_of(ga) + 1.0)
gm = g.add_clip("music", g.media[2])
check(raises(lambda: g.group([ga["id"]])), "one clip on its own isn't a group")
gid = g.group([ga["id"], gb["id"]])
check(g.group_of(ga["id"]) == gid and g.group_of(gb["id"]) == gid, "two clips make a group")
check([c["id"] for c in g.group_members(gid)] == [ga["id"], gb["id"]], "the group knows its clips")
check(sorted(g.expand_groups([ga["id"]])) == sorted([ga["id"], gb["id"]]), "picking one picks the group")
check(g.expand_groups([gm["id"]]) == [gm["id"]], "a clip outside a group is left alone")
was = (ga["start"], gb["start"])
g.move_group(gid, 2.0)
check(close(ga["start"], was[0] + 2.0) and close(gb["start"], was[1] + 2.0), "the whole group slides along",
      (ga["start"], gb["start"]))
g.move_group(gid, -100.0)
check(close(ga["start"], 0.0) and close(gb["start"], was[1] - was[0]), "and keeps its spacing at the start",
      (ga["start"], gb["start"]))
blocker = g.add_clip("video", g.media[0], at=model.end_of(gb) + 0.5)
g.ungroup([blocker["id"]]) if blocker.get("group") else None
check(raises(lambda: g.move_group(gid, (blocker["start"] - gb["start"]) + 0.2)),
      "a group won't move on top of another clip")
g.undo()
check(g.group_of(ga["id"]) == gid, "undo keeps the group")
n = g.ungroup([ga["id"]])
check(n == 2 and g.group_of(ga["id"]) is None and g.group_of(gb["id"]) is None, "Ungroup frees them both", n)
check(raises(lambda: g.ungroup([ga["id"]])), "and says so when there is no group")
# a copy of a group pastes as a group of its own
gid2 = g.group([ga["id"], gb["id"]])
items = [{"track": "video", "clip": copy.deepcopy(ga), "offset": 0.0},
         {"track": "video", "clip": copy.deepcopy(gb), "offset": gb["start"] - ga["start"]}]
made = g.paste(items, 60.0)
check(len(made) == 2 and made[0].get("group") and made[0]["group"] == made[1]["group"] and
      made[0]["group"] != gid2, "pasted clips keep their grouping, under a new id",
      (made[0].get("group"), gid2))
gf = os.path.join(T, "groups.reel")
g.save(gf)
check(model.Project.load(gf).group_of(ga["id"]) == gid2, "groups are saved with the project")

shutil.rmtree(T, ignore_errors=True)
print("%d checks, %d failed" % (N[0], len(FAILS)))
print("all passed" if not FAILS else "FAILED")
sys.exit(1 if FAILS else 0)
