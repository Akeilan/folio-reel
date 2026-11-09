# Recording into the project (R3-07): voice-over, the screen, one window, the camera.
# The microphone and camera are stand-ins (FOLIO_REEL_AUDIOSRC, FOLIO_REEL_FAKE_CAMERA).
import os
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())


def record(cmd, secs=1.5, pick=False):
    if pick:
        respond("pick_dialog", Gtk.ResponseType.OK)
    rec = win.run(cmd)
    if rec is None:
        return None
    wait(lambda: rec.started is not None, 10)
    pump(secs)
    win.record_bar.stop()
    wait(lambda: win.recorder is None, 20)
    pump(0.3)
    return rec


try:
    pump(0.5)
    win.run("split-sound:off")      # not what this test is about (R5-05)
    win.import_uris([URI["red"]])
    win.add_media_to_timeline([URI["red"]])
    win.seek(1.0)
    win._do_seek()
    rec = record("record-voice")
    a = clips("audio")
    check(rec is not None and os.path.exists(rec.path) and rec.path.endswith(".wav"), "Voice-over: a sound file is made",
          rec and rec.path)
    check(len(a) == 1 and abs(a[0]["start"] - 1.0) < 0.01, "on the Audio track at the playhead", a)
    check(a and a[0]["duration"] > 1.0, "as long as the recording", a and a[0]["duration"])
    check(os.path.dirname(rec.path).endswith("Folio Reel"), "kept in Videos/Folio Reel", rec.path)
    check(mkmedia.loudness(rec.path, 0.5) > 0.05, "with sound in it")
    rec = record("record-screen")
    v = clips("video")
    check(rec is not None and len(v) == 2 and v[1]["name"].startswith("Screen Recording"), "Record Screen: a clip on the Video track",
          [c["name"] for c in v])
    m = win.project.media_by_uri(v[1]["media"]) if len(v) > 1 else None
    check(m and m["has_video"] and m["width"] >= 1000 and m["duration"] > 1.0, "the whole screen, for as long as it ran", m)
    from folio_reel import record as rmod
    wins = rmod.x11_windows()
    check(any("Folio Reel" in t for _x, t in wins), "the windows on the screen are listed", wins)
    rec = record("record-window", pick=True)
    v = clips("video")
    check(rec is not None and v[-1]["name"].startswith("Window Recording"), "Record Window", [c["name"] for c in v])
    m = win.project.media_by_uri(v[-1]["media"])
    check(m and m["width"] < 1600, "just the window", m and (m["width"], m["height"]))
    os.environ["FOLIO_REEL_FAKE_CAMERA"] = "1"
    rec = record("record-camera", pick=len(rmod.cameras()) > 1)
    v = clips("video")
    check(rec is not None and v[-1]["name"].startswith("Camera Recording"), "Record Camera", [c["name"] for c in v])
    m = win.project.media_by_uri(v[-1]["media"])
    check(m and m["has_video"] and m["has_audio"], "picture and sound", m)
    # Cancel throws the recording away
    n = len(clips("audio"))
    r = win.run("record-voice")
    wait(lambda: r.started is not None, 10)
    pump(0.5)
    win.record_bar.cancel()
    pump(0.3)
    check(len(clips("audio")) == n and not os.path.exists(r.path), "Cancel keeps nothing")
    del os.environ["FOLIO_REEL_FAKE_CAMERA"]
    shot("10_recorded")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
