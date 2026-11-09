# A clip's sound as its own clip on the Audio track (R5-05), and dragging media out of the bin
# (R5-06). Run with run_ui.sh ui_sound.py.
import os
import tempfile
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

import mkclap
from folio_reel import engine, model
from folio_reel.model import end_of

try:
    T = tempfile.mkdtemp(prefix="reel_snd_")
    pump(0.5)
    p = win.project
    check(win.split_sound(), "a clip's sound goes on its own track to begin with")

    # ---------------------------------------------------------------- the pair
    win.add_uris([URI["red"]], track="video", at=0.0)
    settle()
    pic = clips("video")[0]
    snd = clips("audio")[0] if clips("audio") else None
    check(len(clips("video")) == 1 and snd is not None,
          "a film with sound lands as a picture clip and a sound clip",
          (len(clips("video")), len(clips("audio"))))
    check(abs(snd["start"] - pic["start"]) < 1e-9 and abs(snd["duration"] - pic["duration"]) < 1e-9,
          "at the same time, for the same length", (snd["start"], snd["duration"]))
    check(pic.get("sound_elsewhere") and not snd.get("sound_elsewhere"),
          "the picture clip knows its sound is elsewhere")
    check(p.group_of(pic["id"]) and p.group_of(pic["id"]) == p.group_of(snd["id"]),
          "the two are one group", (p.group_of(pic["id"]), p.group_of(snd["id"])))
    check(p.sound_partner(pic["id"])["id"] == snd["id"], "the picture can say which clip its sound is")
    check(p.out_of_step() == [], "and the check says they line up", p.out_of_step())

    # ---------------------------------------------------------------- they stay together
    win.timeline.select([pic["id"]])
    win.edit(lambda pr: pr.move(pic["id"], 2.0))
    settle()
    pic, snd = clips("video")[0], clips("audio")[0]
    check(abs(pic["start"] - 2.0) < 1e-6 and abs(snd["start"] - 2.0) < 1e-6,
          "moving the picture takes the sound with it", (pic["start"], snd["start"]))
    check(p.out_of_step() == [], "still in step after a move")

    win.edit(lambda pr: pr.trim(pic["id"], "end", pic["start"] + 2.0))
    settle()
    pic, snd = clips("video")[0], clips("audio")[0]
    check(abs(pic["duration"] - 2.0) < 1e-6 and abs(snd["duration"] - 2.0) < 1e-6,
          "trimming the picture's end trims the sound too", (pic["duration"], snd["duration"]))
    win.edit(lambda pr: pr.trim(pic["id"], "start", pic["start"] + 0.5))
    settle()
    pic, snd = clips("video")[0], clips("audio")[0]
    check(abs(snd["start"] - pic["start"]) < 1e-6 and abs(snd["duration"] - pic["duration"]) < 1e-6,
          "and so does trimming its start", (pic["start"], pic["duration"], snd["start"], snd["duration"]))
    check(abs(snd["inpoint"] - pic["inpoint"]) < 1e-6, "both skip the same way into the media",
          (pic["inpoint"], snd["inpoint"]))
    check(p.out_of_step() == [], "still in step after trimming")

    # a sound clip pushed out of step is reported
    win.edit(lambda pr: pr.ungroup([pic["id"]]))
    win.edit(lambda pr: pr.move(snd["id"], snd["start"] + 0.4))
    settle()
    off = p.out_of_step()
    check(len(off) == 1, "nudging the sound on its own is noticed, group or no group", off)
    check(win.check_sound_in_step() is False and "no longer line up" in win.notice_label.get_text(),
          "and said plainly", win.notice_label.get_text())
    check(win.sound_warnings() and "no longer line up" in win.sound_warnings()[0],
          "and it is said again before a render", win.sound_warnings())
    win.run("undo")
    win.run("undo")
    settle()
    check(p.out_of_step() == [], "undo puts it back in step", p.out_of_step())

    # ---------------------------------------------------------------- ripples carry the pair
    w1b = win.run("new")
    pump(0.6)
    for _ in range(3):
        w1b.add_uris([URI["red"]], track="video")
        settle()
    vids = w1b.project.track("video")
    snds = w1b.project.track("audio")
    check(len(vids) == 3 and len(snds) == 3, "three clips, three sounds",
          (len(vids), len(snds)))
    check(w1b.project.out_of_step() == [], "all in step")
    w1b.timeline.select([vids[1]["id"]])
    w1b.run("transition:crossfade")
    settle()
    check(w1b.project.track("video")[1].get("transition"), "a crossfade on the second clip",
          w1b.project.track("video")[1].get("transition"))
    check(w1b.project.out_of_step() == [],
          "a transition pulls the clips after it earlier and takes their sound along",
          [(c["name"], c["start"], s2["start"]) for c, s2 in w1b.project.out_of_step()])
    w1b.run("undo")
    settle()
    w1b.timeline.select([w1b.project.track("video")[0]["id"]])
    w1b.run("ripple-delete")
    settle()
    check(len(w1b.project.track("video")) == 2 and len(w1b.project.track("audio")) == 2,
          "a ripple delete takes the sound with the picture",
          (len(w1b.project.track("video")), len(w1b.project.track("audio"))))
    check(w1b.project.out_of_step() == [], "and closes the same gap on both tracks",
          [(c["start"], s2["start"]) for c, s2 in w1b.project.out_of_step()])
    first = w1b.project.track("video")[0]
    check(abs(first["start"]) < 1e-6, "the clips after it moved up", first["start"])
    # splitting a pair leaves each half with the right sound under it
    w1b.seek(first["start"] + first["duration"] / 2)
    w1b.timeline.select([first["id"]])
    w1b.run("split")
    settle()
    check(len(w1b.project.track("video")) == 3 and len(w1b.project.track("audio")) == 3,
          "splitting a pair splits both halves",
          (len(w1b.project.track("video")), len(w1b.project.track("audio"))))
    check(w1b.project.out_of_step() == [], "and each half keeps the sound under it",
          [(c["start"], c["duration"], s2["start"], s2["duration"]) for c, s2 in w1b.project.out_of_step()])

    # ---------------------------------------------------------------- what does not get split
    win.add_uris([URI["photo"]], track="video")
    settle()
    n_audio = len(clips("audio"))
    check(len(clips("video")) == 2 and n_audio == 1, "a still picture has no sound to split off",
          (len(clips("video")), n_audio))
    win.add_uris([URI["silent"]], track="video")
    settle()
    check(len(clips("audio")) == 1, "nor does a film with no sound in it", len(clips("audio")))
    win.add_uris([URI["music"]], track="music")
    settle()
    check(len(clips("music")) == 1 and len(clips("audio")) == 1, "sound put on a sound track stays put",
          (len(clips("music")), len(clips("audio"))))

    # with the sound tracks busy at that time, the clip keeps its own sound
    w2 = win.run("new")
    pump(0.6)
    w2.add_uris([URI["music"]], track="music", at=0.0)
    w2.add_uris([URI["speech"]], track="audio", at=0.0)
    settle()
    w2.add_uris([URI["red"]], track="video", at=0.0)
    settle()
    vid = w2.project.track("video")[0]
    check(not vid.get("sound_elsewhere"), "a clip keeps its sound when the sound tracks are busy")
    check("kept its own sound" in w2.notice_label.get_text(), "and says why",
          w2.notice_label.get_text())

    # ---------------------------------------------------------------- the setting
    w3 = win.run("new")
    pump(0.6)
    check(w3.run("split-sound:off") is False and not w3.split_sound(), "the split can be turned off")
    w3.add_uris([URI["red"]], track="video", at=0.0)
    settle()
    check(len(w3.project.track("video")) == 1 and not w3.project.track("audio"),
          "and then a clip keeps its own sound",
          (len(w3.project.track("video")), len(w3.project.track("audio"))))
    check(w3.run("split-sound:on") is True and w3.split_sound(), "and turned back on")

    # ---------------------------------------------------------------- the film that comes out
    w4 = win.run("new")
    pump(0.6)
    clap = os.path.join(T, "clap.mp4")
    mkclap.clapper(clap)
    base, _f, _b = mkclap.offsets(clap)
    check(len(base) >= 3, "a clapperboard to measure with: flash and beep together", base)
    w4.add_uris([_model.path_to_uri(clap)], track="video", at=0.0)
    settle()
    check(len(w4.project.track("video")) == 1 and len(w4.project.track("audio")) == 1,
          "the clapperboard splits in two")
    out = os.path.join(T, "split.mp4")
    ex = w4.start_export(out, "mp4", "720p")
    ok = wait(lambda: ex is not None and ex.done, 600)
    check(ok and ex.error is None and os.path.exists(out), "it exports", ex.error if ex else None)
    if os.path.exists(out):
        got, ff, bb = mkclap.offsets(out)
        check(len(got) >= 3, "the flashes and beeps are all still there", (len(ff), len(bb)))
        spread = max(got) - min(got) if got else 9
        check(spread < 0.02, "the sound keeps step with the picture all the way through", got)
        drift = max(abs(g - base[0]) for g in got) if got else 9
        check(drift < 0.045, "and within a frame of where it started", (base[0], got))

    # ---------------------------------------------------------------- a speed change (R5-05)
    check("pitch" in engine.speed_filter(0.5), "a speed change stretches the sound", engine.speed_filter(0.5))
    w6 = win.run("new")
    pump(0.6)
    w6.add_uris([_model.path_to_uri(clap)], track="video", at=0.0)
    settle()
    vp = w6.project.track("video")[0]
    w6.edit(lambda pr: pr.set_speed(vp["id"], 0.5))
    settle()
    vp, vs = w6.project.track("video")[0], w6.project.track("audio")[0]
    check(abs(vp["speed"] - 0.5) < 1e-9 and abs(vs["speed"] - 0.5) < 1e-9,
          "slowing the picture slows its sound with it", (vp["speed"], vs["speed"]))
    check(abs(vs["duration"] - vp["duration"]) < 1e-6 and w6.project.out_of_step() == [],
          "and the two still line up", (vp["duration"], vs["duration"]))
    slow = os.path.join(T, "slow.mp4")
    ex = w6.start_export(slow, "mp4", "720p")
    ok = wait(lambda: ex is not None and ex.done, 900)
    check(ok and ex.error is None and os.path.exists(slow), "slow motion exports",
          ex.error if ex else None)
    if os.path.exists(slow):
        got, ff, bb = mkclap.offsets(slow)
        spread = (max(got) - min(got)) if len(got) > 1 else 9
        check(len(got) >= 3, "the flashes and beeps survive the slow motion", (len(ff), len(bb)))
        # the stretch wanders: measured at 25ms across a clip at half speed. Doing it exactly means
        # rendering the speed change to a copy first (R5-07); this holds the line where it is.
        check(spread < 0.045, "the sound holds step through slow motion to within half a frame",
              (got, round(spread, 4)))

    # ---------------------------------------------------------------- dragging out of the bin
    w5 = win.run("new")
    pump(0.6)
    w5.import_uris([URI["red"], URI["blue"]])
    settle()
    view = w5.mediabin.view
    check(len(view.get_model()) == 2, "two in the bin", len(view.get_model()))
    view.unselect_all()
    check(w5.mediabin.selected_uris() == [], "nothing selected to begin with")
    # pressing a thumbnail picks it, which is what the drag then carries
    path = Gtk.TreePath.new_from_indices([1])
    area = view.get_cell_rect(path, None)[1]
    w5.mediabin._press(view, Ev(type=Gdk.EventType.BUTTON_PRESS, button=1,
                                x=float(area.x + area.width / 2), y=float(area.y + area.height / 2),
                                state=Gdk.ModifierType(0)))
    picked = w5.mediabin.selected_uris()
    check(len(picked) == 1, "pressing a thumbnail picks that one", picked)

    class Data:
        def __init__(self):
            self.uris = None

        def set_uris(self, u):
            self.uris = u

    d = Data()
    w5.mediabin._drag_get(view, None, d, 0, 0)
    check(d.uris == picked, "and the drag carries it", d.uris)
    # the timeline takes the drop at the time and track it landed on
    t = w5.timeline
    y, h = t.track_rect("video")
    class Dropped:
        def get_uris(self):
            return d.uris
    t._dropped(t.area, None, t.x_of(3.0), y + h / 2, Dropped(), 0, 0)
    settle()
    dropped = w5.project.track("video")
    check(len(dropped) == 1, "dropping it puts a clip on the timeline", len(dropped))
    check(abs(dropped[0]["start"] - 3.0) < 0.1, "at the time it was dropped", dropped[0]["start"])
    check(len(w5.project.track("audio")) == 1, "and its sound comes along on the Audio track",
          len(w5.project.track("audio")))
except Exception:
    traceback.print_exc()
    check(False, "the test ran to the end")
finish()
