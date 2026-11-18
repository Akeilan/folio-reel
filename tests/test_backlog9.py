"""Backlog 9: what a full test of Reel 0.14.0 found, each item checked the way it was found —
by editing a project, rendering it, and measuring the film that comes out.

The test film has a different colour and a different tone in each of its eight seconds, so the
picture and the sound of any render say where they are. It is ordinary 4:2:0 H.264 with AAC sound,
which is what phones and cameras make and what Reel's other test media is not."""
import array
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if not os.environ.get("PYTHONPATH"):
    sys.path.insert(0, os.path.join(HERE, "..", "app"))
T = tempfile.mkdtemp(prefix="reel_b9_")
os.environ["XDG_CACHE_HOME"] = os.path.join(T, "cache")
os.environ["XDG_STATE_HOME"] = os.path.join(T, "state")
from folio_reel import engine, model, recovery, subtitles  # noqa: E402

N = [0]
FAILS = []


def check(ok, what, info=None):
    N[0] += 1
    print(("ok   " if ok else "FAIL ") + what + ("" if ok or info is None else "  -- %r" % (info,)))
    sys.stdout.flush()
    if not ok:
        FAILS.append(what)
    return ok


def raises(fn):
    try:
        fn()
    except model.EditError:
        return True
    return False


# ---------------------------------------------------------------- the test media
MD = os.environ.get("REEL_B9_MEDIA") or os.path.join(tempfile.gettempdir(), "reel_b9_media")
os.makedirs(MD, exist_ok=True)
FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
COLS = ["red", "green", "blue", "yellow", "magenta", "cyan", "white", "gray"]
RGB = {"red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0), "magenta": (255, 0, 255),
       "cyan": (0, 255, 255), "white": (255, 255, 255), "gray": (128, 128, 128), "black": (0, 0, 0)}


def ff(*args):
    subprocess.run(FF + list(args), check=True)


def P(name):
    return os.path.join(MD, name)


def make_media():
    if os.path.exists(P("done")):
        return
    ins, fc = [], ""
    for n, c in enumerate(COLS):
        ins += ["-f", "lavfi", "-t", "1", "-i", "color=c=%s:s=640x360:r=25" % c,
                "-f", "lavfi", "-t", "1", "-i", "sine=frequency=%d:sample_rate=48000" % (300 + 100 * n)]
        fc += "[%d:v][%d:a]" % (2 * n, 2 * n + 1)
    ff(*ins, "-filter_complex", fc + "concat=n=8:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
       "-preset", "veryfast", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", P("steps.mp4"))
    ff("-i", P("steps.mp4"), "-c:v", "mpeg2video", "-c:a", "mp2", P("steps.mpg"))
    ff("-i", P("steps.mp4"), "-vf", "scale=720:576,setsar=64/45", "-c:v", "libx264", "-preset", "veryfast",
       "-c:a", "copy", P("wide-pixels.mp4"))
    ff("-f", "lavfi", "-t", "1", "-i", "testsrc=s=800x600", "-frames:v", "1", P("pic.png"))
    for ext in ("jpg", "bmp", "tiff"):
        ff("-i", P("pic.png"), P("pic." + ext))
    ff("-f", "lavfi", "-t", "2", "-i", "testsrc=s=200x150:r=10", P("anim.gif"))
    ff("-f", "lavfi", "-t", "1", "-i", "color=c=red:s=400x800", "-frames:v", "1", P("tall.png"))
    ff("-f", "lavfi", "-t", "4", "-i", "sine=frequency=880:sample_rate=48000", P("voice.wav"))
    open(P("done"), "w").write("ok")


make_media()


def proj(w=1920, h=1080, fps=30):
    return model.Project(model.new_project(w, h, fps))


def media(p, name):
    return p.add_media(engine.probe(P(name)))


def export(p, name, preset="720p", prepare=True):
    out = os.path.join(T, name)
    if prepare:
        engine.prepare(p)
    ex = engine.Exporter(p, out, "webm" if name.endswith(".webm") else "mp4", preset)
    ok = ex.run_sync(300)
    return out, ok, ex


def frame(path, t, w=32, h=18):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ss", "%.3f" % t, "-frames:v", "1", "-vf",
                        "scale=%d:%d:flags=area" % (w, h), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True).stdout
    return r if len(r) >= w * h * 3 else None


def at(path, t, fx=0.5, fy=0.5):
    """The colour at a point of the frame shown at t."""
    f = frame(path, t)
    if f is None:
        return None
    i = (min(17, int(fy * 18)) * 32 + min(31, int(fx * 32))) * 3
    return tuple(f[i:i + 3])


def named(c):
    return "none" if c is None else min(RGB, key=lambda k: sum((a - b) ** 2 for a, b in zip(RGB[k], c)))


def colours(path, times):
    return [named(at(path, t)) for t in times]


def size_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    try:
        w, h = r.split(",")[:2]
        return (int(w), int(h))
    except ValueError:
        return None


def sound(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                       capture_output=True).stdout
    a = array.array("h")
    a.frombytes(r[:len(r) // 2 * 2])
    return a


def level(a, t0, t1):
    seg = a[int(t0 * 48000):int(t1 * 48000)]
    return (sum(v * v for v in seg) / max(1, len(seg))) ** 0.5 / 32768.0


def gaps(a, upto, w=240, floor=0.03):
    """Starts (s) of the stretches of near silence in a sound that should have none."""
    out, last = [], -1.0
    for k in range(0, len(a) - w, w):
        t = k / 48000.0
        if not (0.1 < t < upto):
            continue
        seg = a[k:k + w]
        if (sum(v * v for v in seg) / w) ** 0.5 / 32768.0 < floor:
            if t - last > 0.011:
                out.append(round(t, 3))
            last = t
    return out


def line(p, tracks=("video", "audio")):
    return " | ".join("%s: %s" % (t[0], " ".join("%.2f-%.2f" % (c["start"], model.end_of(c)) for c in p.track(t)))
                      for t in tracks)


def three(split=True):
    p = proj()
    m = media(p, "steps.mp4")
    for _ in range(3):
        (p.add_media_split("video", m) if split else p.add_clip("video", m))
    return p


# ================================================================ the editing model
# ---------------------------------------------------------------- R9-04: speed moves later clips once
p = three()
p.set_speed(p.track("video")[0]["id"], 2.0)
check(line(p) == "v: 0.00-4.00 4.00-12.00 12.00-20.00 | a: 0.00-4.00 4.00-12.00 12.00-20.00",
      "R9-04: 2× on the first of three clips with split sound: the rest follow once", line(p))
p = three()
p.set_speed(p.track("video")[0]["id"], 0.5)
check(line(p) == "v: 0.00-16.00 16.00-24.00 24.00-32.00 | a: 0.00-16.00 16.00-24.00 24.00-32.00",
      "R9-04: and 0.5× leaves no gap", line(p))
check(not p.out_of_step(), "R9-04: every picture still has its sound under it")

# ---------------------------------------------------------------- R9-05: ripple delete keeps pairs together
p = proj()
m = media(p, "steps.mp4")
ph = media(p, "pic.png")
p.add_media_split("video", m)
photo = p.add_clip("video", ph)
p.add_media_split("video", m)
p.delete([photo["id"]], ripple=True)
check(line(p) == "v: 0.00-8.00 8.00-16.00 | a: 0.00-8.00 8.00-16.00" and not p.out_of_step(),
      "R9-05: ripple-deleting a photo brings the later picture and its sound along together", line(p))
p = proj()
m = media(p, "steps.mp4")
v = media(p, "voice.wav")
p.add_media_split("video", m)                       # 0-8, with its sound
vo = p.add_clip("audio", v, at=8.0)                 # a voice-over, 8-12
p.add_clip("video", media(p, "pic.png"), at=8.0)    # a photo over it, 8-13
p.add_media_split("video", m, at=13.0)              # 13-21, with its sound
p.delete([vo["id"]], ripple=True)
check(not p.out_of_step() and line(p) == "v: 0.00-8.00 8.00-13.00 13.00-21.00 | a: 0.00-8.00 13.00-21.00",
      "R9-05: a gap that a later picture's place won't let close stays open, rather than landing clips on each other",
      line(p))

# ---------------------------------------------------------------- R9-13: edits beside a transition
p = three(False)
ids = [c["id"] for c in p.track("video")]
p.set_transition(ids[1], "crossfade", 1.0)
p.delete([ids[1]], ripple=True)
check(line(p, ("video",)) == "v: 0.00-8.00 8.00-16.00", "R9-13: ripple delete of a clip with a crossfade leaves no overlap",
      line(p, ("video",)))
p = three(False)
ids = [c["id"] for c in p.track("video")]
p.set_transition(ids[1], "crossfade", 1.0)
p.set_speed(ids[0], 2.0)
check(line(p, ("video",)) == "v: 0.00-4.00 3.00-11.00 11.00-19.00" and p.clip(ids[1])["transition"]["duration"] == 1.0,
      "R9-13: a speed change carries the crossfaded clip after it", line(p, ("video",)))
check(raises(lambda: p.split_at(3.5)), "R9-13: a split inside a transition is refused, with the reason")
p = three(False)
ids = [c["id"] for c in p.track("video")]
p.set_transition(ids[1], "crossfade", 2.0)
p.trim(ids[0], "end", 1.0)
check(p.clip(ids[1])["transition"] is None, "R9-13: trimming the clips apart takes their transition off")
p = three(False)
ids = [c["id"] for c in p.track("video")]
p.set_transition(ids[2], "wipe-left", 1.0)
p.move(ids[1], 40.0)
check(p.clip(ids[2])["transition"] is None, "R9-13: so does moving the clip before it away")

# ---------------------------------------------------------------- split halves, R9-14 paste
p = three()
new = p.split_at(2.0)
vs, au = p.track("video"), p.track("audio")
check(vs[0]["group"] == au[0]["group"] and vs[1]["group"] == au[1]["group"] and vs[0]["group"] != vs[1]["group"],
      "the two sides of a cut are pairs of their own, and can be moved apart")
check([(c["id"], (p.sound_partner(c["id"]) or {}).get("id")) for c in vs[:2]] == [(vs[0]["id"], au[0]["id"]), (vs[1]["id"], au[1]["id"])],
      "each side's picture knows its own sound")
p = three()
v0 = p.track("video")[0]
s0 = p.sound_partner(v0["id"])
items = [{"track": "video", "clip": copy.deepcopy(v0), "offset": 0.0, "media": None},
         {"track": "audio", "clip": copy.deepcopy(s0), "offset": 0.0, "media": None}]
made = p.paste(items, 30.0)
pic = [c for c in made if c.get("sound_elsewhere")][0]
check(p.sound_partner(pic["id"])["id"] != s0["id"] and p.sound_partner(pic["id"])["start"] == pic["start"]
      and not p.out_of_step(), "R9-14: a pasted picture's sound is the pasted sound, not the original's")
made = p.paste(items, 4.0)          # the Video track is busy at 4 s, the Audio track too
pic = [c for c in made if c.get("sound_elsewhere")][0]
check(not p.out_of_step(), "R9-14: a pasted pair lands together even where the tracks are busy")

# ---------------------------------------------------------------- R9-26: several clips move together
p = three()
vs = p.track("video")
p.move_many([vs[0]["id"], vs[1]["id"]], 40.0)
check(line(p) == "v: 16.00-24.00 40.00-48.00 48.00-56.00 | a: 16.00-24.00 40.00-48.00 48.00-56.00",
      "R9-26: two selected clips move together, with their sound, keeping their spacing", line(p))
check(raises(lambda: p.move_many([p.track("video")[1]["id"], p.track("video")[2]["id"]], -30.0)),
      "R9-26: and not at all when one of them would land on another clip")

# ---------------------------------------------------------------- R9-27, R9-32: trims
p = three(False)
c = p.track("video")[0]
check(raises(lambda: p.trim_to_playhead(c["id"], 20.0, "start")) and c["duration"] == 8.0,
      "R9-27: Trim Start with the playhead off the clip is refused; the clip keeps its length")
check(raises(lambda: p.trim_to_playhead(c["id"], 30.0, "end")), "R9-27: Trim End too")
p.trim_to_playhead(c["id"], 2.0, "start")
check(abs(c["start"] - 2.0) < 1e-6 and abs(c["duration"] - 6.0) < 1e-6, "R9-27: with the playhead on the clip it trims")
p = proj()
m = media(p, "steps.mp4")
c = p.add_clip("video", m, at=1.0)
p.split_at(1.05)
tiny = p.track("video")[0]
p.trim(tiny["id"], "start", 5.0)
check(tiny["start"] >= 0 and model.end_of(tiny) <= p.track("video")[1]["start"] + 1e-6 and tiny["duration"] > 0,
      "R9-32: a clip under a tenth of a second can be trimmed without leaving the timeline or its neighbour",
      (tiny["start"], tiny["duration"]))

# ---------------------------------------------------------------- R9-28: the music bed
p = proj()
m = media(p, "steps.mp4")
p.add_media_split("video", m)
mu = p.add_clip("music", media(p, "voice.wav"), at=0)
p.set(mu["id"], music_bed=True)
check(all(g == 1.0 for _t, g in p.duck_points(mu)), "R9-28: the music doesn't dip under a clip's own sound",
      p.duck_points(mu))
vo = p.add_clip("audio", media(p, "voice.wav"), at=8.5)
mu2 = p.add_clip("music", media(p, "voice.wav"), at=8.0)
p.set(mu2["id"], music_bed=True)
check(any(g < 0.5 for _t, g in p.duck_points(mu2)), "R9-28: it still dips under a voice-over")

# ---------------------------------------------------------------- R9-29, R9-31: undo
p = three()
n = len(p.undo_stack)
with p.batch("Volume"):
    for c in list(p.all_clips()):
        p.set(c["id"], volume=0.5)
check(len(p.undo_stack) == n + 1 and p.undo() == "Volume" and all(c["volume"] == 1.0 for c in p.all_clips()),
      "R9-29: a change to six clips is one step for Undo")
f = os.path.join(T, "saved.reel")
p.save(f)
p.set(p.track("video")[0]["id"], volume=0.3)
dirty = p.dirty
p.undo()
check(dirty and not p.dirty, "R9-31: undoing back to the saved project leaves nothing to save")
p.redo()
check(p.dirty, "R9-31: redoing the change does")

# ---------------------------------------------------------------- R9-15: files that aren't projects
cases = {"empty": "", "words": "hello", "a list": "[]", "an empty object": "{}", "tracks as a list": '{"tracks": []}',
         "binary": "\x00\x01\x02"}
bad = []
for k, txt in cases.items():
    fp = os.path.join(T, "x.reel")
    open(fp, "w").write(txt)
    try:
        model.Project.load(fp)
        bad.append(k + ": loaded")
    except model.EditError:
        pass
    except Exception as e:      # noqa: BLE001
        bad.append("%s: %s" % (k, type(e).__name__))
check(not bad, "R9-15: a file that isn't a project is refused in plain words, whatever is in it", bad)
fp = os.path.join(T, "thin.reel")
open(fp, "w").write(json.dumps({"tracks": {"video": [{"id": 1, "kind": "media", "media": "file:///x.mp4"},
                                                      {"kind": "title", "start": 2, "duration": 3},
                                                      "junk"]}, "fps": None}))
q = model.Project.load(fp)
check(len(q.track("titles")) == 0 and [c["kind"] for c in q.track("video")] == ["title"] and q.fps == 30
      and q.data["next_id"] > q.track("video")[0]["id"], "R9-15: a thin project loads with what can be used",
      q.data["tracks"])
q.add_clip("titles", "caption")
check(q.duration() == 5.0, "R9-15: and can be worked on")
check(model.parse_time("inf") is None and model.parse_time("1e999") is None and model.parse_time("1:30") == 90.0,
      "a typed time is a number of seconds, never infinity")

# ---------------------------------------------------------------- R9-02: missing media, and finding it again
d = os.path.join(T, "proj")
os.makedirs(d)
shutil.copy(P("steps.mp4"), os.path.join(d, "clip.mp4"))
p = proj()
m = p.add_media(engine.probe(os.path.join(d, "clip.mp4")))
p.add_media_split("video", m)
pf = os.path.join(d, "film.reel")
p.save(pf)
os.rename(os.path.join(d, "clip.mp4"), os.path.join(T, "renamed.mp4"))
q = model.Project.load(pf)
check(len(q.missing_media()) == 1 and len(q.missing_clips()) == 2, "R9-02: a project with a file gone loads, and knows what is missing")
old = q.media[0]["uri"]
q.relink_media(old, engine.probe(os.path.join(T, "renamed.mp4")))
check(not q.missing_media() and not q.missing_clips() and all(c["media"] != old for c in q.all_clips()),
      "R9-02: Find File points the media and its clips at the file's new place")
shutil.copy(P("steps.mp4"), os.path.join(d, "clip.mp4"))
os.makedirs(os.path.join(T, "moved"))
shutil.move(os.path.join(d, "film.reel"), os.path.join(T, "moved", "film.reel"))
shutil.move(os.path.join(d, "clip.mp4"), os.path.join(T, "moved", "clip.mp4"))
check(not model.Project.load(os.path.join(T, "moved", "film.reel")).missing_media(),
      "R9-02: a file beside the project is found by its name")

# ---------------------------------------------------------------- random editing: nothing breaks, Undo is exact
infos = {n: engine.probe(P(n)) for n in ("steps.mp4", "voice.wav", "pic.png")}


def broken(p):
    out = []
    for t in model.TRACKS:
        cs = p.track(t)
        for a, b in zip(cs, cs[1:]):
            over = model.end_of(a) - b["start"]
            tr = b.get("transition") or {}
            want = tr.get("duration", 0) if tr.get("type") not in (None, "dip-black") else 0
            if t in ("video", "titles") and over > want + 1e-4:
                out.append("overlap")
            if tr and tr.get("type") != "dip-black" and over < want - 0.06:
                out.append("transition without its overlap")
        for i, c in enumerate(cs):
            if c["start"] < -1e-9 or c["duration"] <= 0:
                out.append("off the timeline")
            if c.get("transition") and i == 0:
                out.append("transition on the first clip")
            m = p.media_by_uri(c["media"]) if c["kind"] == "media" else None
            if m and not m.get("is_image") and c["inpoint"] + c["duration"] * c.get("speed", 1.0) > float(m["duration"]) + 0.05:
                out.append("past the end of its media")
    if p.out_of_step():
        out.append("picture and sound apart")
    return out


seen = {}
undo_bad = 0
for seed in range(1, 121):
    r = random.Random(seed)
    p = proj()
    ms = {n: p.add_media(i) for n, i in infos.items()}
    p.undo_stack.clear()
    start = json.dumps(p.data, sort_keys=True)
    for step in range(50):
        clips = list(p.all_clips())
        op = r.choice(["add", "pair", "pair", "title", "split", "trim", "trim", "move", "move", "delete", "ripple",
                       "speed", "trans", "trans", "paste", "many"])
        try:
            if op == "add":
                n = r.choice(list(ms))
                p.add_clip("video" if n != "voice.wav" else r.choice(["audio", "music"]), ms[n], at=r.choice([None, r.uniform(0, 30)]))
            elif op == "pair":
                p.add_media_split("video", ms["steps.mp4"], at=r.choice([None, r.uniform(0, 30)]))
            elif op == "title":
                p.add_clip("titles", r.choice(["title", "caption"]), at=r.uniform(0, 30))
            elif not clips:
                continue
            elif op == "split":
                p.split_at(r.uniform(0, p.duration()))
            elif op == "trim":
                c = r.choice(clips)
                p.trim(c["id"], r.choice(["start", "end"]), r.uniform(c["start"] - 2, model.end_of(c) + 2))
            elif op == "move":
                c = r.choice(clips)
                p.move(c["id"], r.uniform(0, 40), tolerance=r.choice([0, 0.2]))
            elif op == "many":
                p.move_many([c["id"] for c in r.sample(clips, min(len(clips), 3))], r.uniform(-10, 10))
            elif op in ("delete", "ripple"):
                p.delete(p.expand_groups([r.choice(clips)["id"]]), ripple=op == "ripple")
            elif op == "speed":
                c = r.choice([x for x in clips if x["kind"] == "media"] or [None])
                if c:
                    p.set_speed(c["id"], r.choice([0.5, 2.0, 1.0, 4.0]))
            elif op == "trans":
                p.set_transition(r.choice(clips)["id"], r.choice(["crossfade", "dip-black", "wipe-left", "none"]),
                                 r.choice([0.5, 1.0, 3.0]))
            elif op == "paste":
                sel = [p.clip(i) for i in p.expand_groups([r.choice(clips)["id"]])]
                base = min(c["start"] for c in sel)
                p.paste([{"track": p.find(c["id"])[0], "clip": copy.deepcopy(c), "offset": c["start"] - base,
                          "media": None} for c in sel], r.uniform(0, 40))
        except model.EditError:
            continue
        b = broken(p)
        if b:
            seen.setdefault("%s after %s" % (b[0], op), (seed, step))
            break
    end = json.dumps(p.data, sort_keys=True)
    while p.can_undo():
        p.undo()
    back = json.dumps(p.data, sort_keys=True) == start
    while p.can_redo():
        p.redo()
    if not back or json.dumps(p.data, sort_keys=True) != end:
        undo_bad += 1
check(not seen, "120 random editing sessions: clips never overlap, leave the timeline or part from their sound", seen)
check(undo_bad == 0, "and Undo all the way back, then Redo all the way forward, gives the same project each time", undo_bad)

# ================================================================ the films that come out
# ---------------------------------------------------------------- R9-01, R9-23: an export never destroys a file
src = os.path.join(T, "holiday.mp4")
shutil.copy(P("steps.mp4"), src)
p = proj()
p.add_media_split("video", p.add_media(engine.probe(src)))
size = os.path.getsize(src)
check(raises(lambda: engine.Exporter(p, src, "mp4", "720p")) and os.path.getsize(src) == size,
      "R9-01: exporting onto a file the project uses is refused, and the file is untouched")
good = os.path.join(T, "film.mp4")
open(good, "wb").write(b"the film from last time")
ex = engine.Exporter(p, good, "mp4", "1080p")
ex.start()
ex.cancel()
check(open(good, "rb").read() == b"the film from last time" and not os.path.exists(ex.tmp),
      "R9-23: a cancelled export leaves the film that was there, and nothing half-written")
out, ok, ex = export(p, "plain.mp4")
check(ok and colours(out, [n + 0.5 for n in range(8)]) == COLS, "an ordinary film renders, second by second",
      colours(out, [n + 0.5 for n in range(8)]))

# ---------------------------------------------------------------- R9-08: WebM from ordinary video
out, ok, ex = export(p, "plain.webm")
check(ok and size_of(out) == (1280, 720) and colours(out, [0.5, 3.5, 7.5]) == ["red", "yellow", "gray"],
      "R9-08: WebM from ordinary 4:2:0 video (failed on 22.04)", (ok, ex.error))

# ---------------------------------------------------------------- R9-16: the project's shape
check([engine.export_size(proj(w, h), q) for (w, h), q in (((1920, 1080), "720p"), ((1440, 1080), "720p"), ((1440, 1080), "1080p"),
                                                         ((1080, 1920), "1080p"), ((1080, 1080), "4k"))]
      == [(1280, 720), (960, 720), (1440, 1080), (1080, 1920), (2160, 2160)],
      "R9-16: every project shape keeps its shape at every export size")
p43 = proj(1440, 1080)
p43.add_clip("video", media(p43, "pic.png"))
out, ok, ex = export(p43, "43.mp4")
check(ok and size_of(out) == (960, 720), "R9-16: a 4:3 project exports 4:3", size_of(out))

# ---------------------------------------------------------------- R9-10: what an export holds in memory
caps = [pr.get_restriction().to_string() for pr in engine.encoding_profile("mp4", 1280, 720, 30).get_profiles()
        if pr.get_restriction() is not None and "video" in pr.get_restriction().to_string()]
check(caps and "I420" in caps[0], "R9-10: the encoder is handed plain 4:2:0 (about half the memory)", caps)
p = proj()
p.add_clip("video", media(p, "steps.mp4"))
p.add_clip("titles", "caption", text="Over the film")
out, ok, ex = export(p, "over.mp4")
check(ok and colours(out, [0.5, 5.5]) == ["red", "cyan"], "R9-10: and a caption over a film still renders (refused on 24.04 when the mixer was asked instead)",
      (ok, ex.error))

# ---------------------------------------------------------------- R9-03, R9-19, R9-34, R9-36: pictures
for name in ("pic.bmp", "pic.tiff", "anim.gif", "pic.jpg"):
    p = proj()
    p.add_clip("video", media(p, name))
    try:
        out, ok, ex = export(p, "still_%s.mp4" % name.split(".")[1])
        mid, bar = at(out, 2.0, 0.5, 0.35), at(out, 2.0, 0.02, 0.5)
        check(ok and not ex.bad and mid is not None and max(mid) > 150 and max(bar) < 8,
              "%s: %s exports as a still picture, bars black" % ({"pic.bmp": "R9-03", "pic.tiff": "R9-03",
                                                                   "anim.gif": "R9-19", "pic.jpg": "R9-34"}[name], name),
              (ok, ex.error, mid, bar))
    except Exception as e:      # noqa: BLE001
        check(False, "%s exports" % name, repr(e)[:200])
p = proj()
m = media(p, "steps.mp4")
p.add_clip("video", m)
junk = os.path.join(T, "junk.mp4")
shutil.copy(P("steps.mp4"), junk)
jm = p.add_media(engine.probe(junk))
p.add_clip("video", jm)
open(junk, "wb").write(b"no longer a film" * 50)
try:
    out, ok, ex = export(p, "onebad.mp4")
    check(ok and ex.bad and colours(out, [0.5]) == ["red"], "R9-03: a clip whose file can't be read is left out and named; the rest of the film is made",
          (ok, ex.bad))
except Exception as e:      # noqa: BLE001
    check(False, "R9-03: one unreadable clip doesn't stop the film", repr(e)[:200])

# ---------------------------------------------------------------- R9-17, R9-20: the picture keeps its shape
p = proj()
p.add_clip("video", media(p, "wide-pixels.mp4"))
out, ok, ex = export(p, "widepx.mp4")
edge = [named(at(out, 1.5, fx, 0.5)) for fx in (0.03, 0.5, 0.97)]
check(ok and edge == ["green", "green", "green"], "R9-17: footage with non-square pixels fills the frame, centred", edge)
p = proj()
c = p.add_clip("video", media(p, "steps.mp4"))
p.set(c["id"], crop={"l": 0.4, "r": 0.4, "t": 0.0, "b": 0.0})
out, ok, ex = export(p, "strip.mp4")
row = [named(at(out, 1.5, fx, 0.5)) for fx in (0.1, 0.35, 0.5, 0.65, 0.9)]
check(ok and row == ["black", "black", "green", "black", "black"], "R9-20: a clip cropped to a strip stays a strip", row)
p = proj()
c = p.add_clip("video", media(p, "tall.png"))
p.set(c["id"], zoom=1.5)
out, ok, ex = export(p, "tallzoom.mp4")
row = [named(at(out, 1.5, fx, 0.5)) for fx in (0.15, 0.5, 0.85)]
check(ok and row == ["black", "red", "black"], "R9-20: a zoomed picture keeps its shape", row)
p = proj()
c = p.add_clip("video", media(p, "pic.png"))
whole = frame(export(p, "nocrop.mp4")[0], 1.0)
p.set(c["id"], crop={"l": 0.3, "r": 0.0, "t": 0.0, "b": 0.0})
cut = frame(export(p, "crop.mp4")[0], 1.0)
check(whole is not None and cut is not None and whole != cut, "R9-36: a crop changes the picture")

# ---------------------------------------------------------------- R9-18: an MPEG file starts at its start
p = proj()
m = media(p, "steps.mpg")
p.add_clip("video", m)
out, ok, ex = export(p, "mpg.mp4")
got = colours(out, [0.25, 1.25, 2.25, 6.25, 7.4])
check(ok and got == ["red", "green", "blue", "white", "gray"] and m.get("offset", 0) > 0.1,
      "R9-18: an .mpg plays from its first picture, to its last", (got, m.get("offset")))

# ---------------------------------------------------------------- R9-06, R9-21: words
p = proj()
p.add_clip("titles", "title", text="Fish & Chips <b>")
out, ok, ex = export(p, "amp.mp4")
f = frame(out, 1.0, 64, 36) or b""
lit = sum(1 for i in range(0, len(f), 3) if f[i] > 120)
check(ok and lit > 40, "R9-06: a title with & and < in it shows its words", lit)
p = proj()
c = p.add_clip("video", media(p, "steps.mp4"))
cap = p.add_clip("titles", "caption", text="A caption")
p.set(cap["id"], bg_color="#e0ff0000")
out, ok, ex = export(p, "box.mp4")
f = frame(out, 1.5, 64, 36) or b""
box = sum(1 for i in range(0, len(f), 3) if f[i] > 150 and f[i] - f[i + 1] > 60 and f[i] - f[i + 2] > 60)
check(ok and box > 15, "R9-21: a caption has a box of its background colour behind the words", box)

# ---------------------------------------------------------------- R9-11, R9-12: sound
for split in (True, False):
    p = proj()
    m = media(p, "steps.mp4")
    (p.add_media_split("video", m) if split else p.add_clip("video", m))
    t = 0.5
    while t < 7.9:
        p.split_at(t)
        t += 0.5
    out, ok, ex = export(p, "cuts_%s.mp4" % split)
    g = gaps(sound(out), 7.9)
    check(ok and not g, "R9-11: fifteen cuts in AAC footage leave no silence (%s)"
          % ("sound on the Audio track" if split else "sound kept with the picture"), g[:8])
p = three()
p.set_transition(p.track("video")[1]["id"], "crossfade", 1.0)
out, ok, ex = export(p, "xf.mp4")
a = sound(out)
normal, over = level(a, 5.2, 5.8), level(a, 7.2, 7.8)
check(ok and normal > 0.03 and over < normal * 1.15, "R9-12: under a crossfade the two sounds cross over instead of doubling up",
      (round(normal, 3), round(over, 3)))

# ---------------------------------------------------------------- R9-09: a speed change is rendered before the film is
shutil.rmtree(engine.fix_dir(), ignore_errors=True)
p = proj()
pic, snd = p.add_media_split("video", media(p, "steps.mp4"))
p.set_speed(pic["id"], 2.0)
todo = engine.to_prepare(p)
check(len(todo) == 2 and {j[0] for j in todo} == {"fix"}, "R9-09: a speed change not yet rendered is listed before an export",
      [(j[0], j[1]["name"]) for j in todo])
out, ok, ex = export(p, "fast.mp4")
got = colours(out, [k * 0.5 + 0.2 for k in range(8)])
check(ok and got == COLS and not engine.to_prepare(p), "R9-09: and the film then runs the whole clip at 2×", got)

# ---------------------------------------------------------------- R9-25: subtitles
raw = ("1\r\n00:00:01,000 --> 00:00:02,500\r\nCaf\xe9 na\xefve\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\n<i>Italic</i> "
       "and <font color=\"#ff0000\">red</font>{\\an8}\r\n\r\n3\r\n00:00:06 --> 00:00:07\r\nno milliseconds\r\n\r\n"
       "4\r\nnot a time\r\nlost\r\n").encode("cp1252")
skipped = []
subs = subtitles.parse(subtitles.decode(raw), skipped)
check([s[2] for s in subs] == ["Café naïve", "Italic and red", "no milliseconds"] and subs[2][:2] == (6.0, 7.0)
      and len(skipped) == 1, "R9-25: a Windows-encoded .srt reads right, tags come off, a time without milliseconds counts, "
      "and what can't be read is counted", (subs, skipped))
check(subtitles.decode("Café".encode("utf-8")) == "Café", "R9-25: UTF-8 stays UTF-8")

# ---------------------------------------------------------------- the recovery copy
recovery.write("abc", "Holiday", None, p.to_json())
check(recovery.pending() == [], "a recovery copy belonging to a Reel that is running isn't offered")
fp = os.path.join(recovery.folder(), "abc.json")
d = json.load(open(fp))
d["pid"] = 2 ** 22 + 12345          # no such process
json.dump(d, open(fp, "w"))
pend = recovery.pending()
check(len(pend) == 1 and pend[0]["name"] == "Holiday" and model.check_project(pend[0]["project"])["tracks"]["video"],
      "one left by a Reel that stopped is offered, with the project in it")
recovery.clear("abc")
check(recovery.pending() == [], "and is gone once dealt with")

# ---------------------------------------------------------------- R9-33: the command line
APP = os.environ.get("REEL_CMD")
CMD = [APP] if APP else [sys.executable, "-m", "folio_reel"]
ENV = dict(os.environ)
if not APP:
    ENV["PYTHONPATH"] = os.path.join(HERE, "..", "app")
gone = os.path.join(T, "gone.mp4")
shutil.copy(P("steps.mp4"), gone)
p = proj()
p.add_clip("video", p.add_media(engine.probe(gone)))
p.add_clip("video", media(p, "pic.png"))
pf = os.path.join(T, "cli.reel")
p.save(pf)
os.remove(gone)
r = subprocess.run(CMD + ["--render", pf, os.path.join(T, "cli.mp4")], capture_output=True, text=True, env=ENV)
check(r.returncode == 4 and "missing" in r.stderr and not os.path.exists(os.path.join(T, "cli.mp4")),
      "R9-33: --render of a project with a file missing says so and makes nothing", (r.returncode, r.stderr[-200:]))
check("PyGIWarning" not in r.stderr, "R9-33: with no warning line from Python")
r = subprocess.run(CMD + ["--render", pf, os.path.join(T, "cli.mp4"), "--skip-missing", "--preset", "720p"],
                   capture_output=True, text=True, env=ENV)
check(r.returncode == 0 and os.path.exists(os.path.join(T, "cli.mp4")), "R9-33: --skip-missing leaves those clips out",
      (r.returncode, r.stderr[-200:]))
r = subprocess.run(CMD + ["--help"], capture_output=True, text=True, env=ENV)
check(r.returncode == 0 and "--render" in r.stdout and "--version" in r.stdout, "R9-33: --help lists --render and --version")

shutil.rmtree(T, ignore_errors=True)
print("%d checks, %d failed" % (N[0], len(FAILS)))
print("all passed" if not FAILS else "FAILED")
sys.exit(1 if FAILS else 0)
