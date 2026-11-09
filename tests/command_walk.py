# Every command on Folio Reel's ribbon and in its menus, with a video clip, a music clip, a title
# and nothing selected; every dialog answered OK, then Cancel. Nothing may raise or say
# "isn't available".
import os
import sys
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

ERRORS = []
_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: (ERRORS.append("".join(traceback.format_exception(t, v, tb))), _hook(t, v, tb))
answer = [Gtk.ResponseType.OK]


def fake_run(d):
    pump(0.01)
    n = getattr(d, "_walk_runs", 0)
    d._walk_runs = n + 1
    return answer[0] if n == 0 else Gtk.ResponseType.CANCEL


Gtk.Dialog.run = fake_run
Gtk.MessageDialog.run = fake_run
Gtk.NativeDialog.run = lambda d: Gtk.ResponseType.CANCEL
Gtk.Menu.popup_at_pointer = lambda *a: None
SKIP = {"close", "new", "open", "save", "save-as", "record-screen", "record-window", "record-camera", "record-voice",
        "full-screen", "play"}


def commands():
    from folio_reel.ribbon_defs import Cmd
    out = []
    for c in win.ribbon.controls:
        a = getattr(c, "action", None)
        if isinstance(a, str):
            out.append(a)
        m = getattr(c, "menu", None)
        if isinstance(m, list):
            for it in m:
                if isinstance(it, tuple) and len(it) >= 2 and isinstance(it[1], Cmd):
                    out.append(it[1].cmd)
    out += ["remove-media", "go-start", "go-end", "frame-back", "frame-forward", "export"]
    seen = []
    for c in out:
        if c not in seen and c.split(":")[0] not in SKIP:
            seen.append(c)
    return seen


try:
    pump(0.5)
    win.run("split-sound:off")      # not what this test is about (R5-05)
    win.import_uris([URI[k] for k in ("red", "blue", "photo", "music", "speech")])
    win.add_media_to_timeline([URI["red"]])
    win.add_media_to_timeline([URI["blue"]])
    win.add_media_to_timeline([URI["photo"]])
    win.add_media_to_timeline([URI["music"]], track="music", at=0)
    win.add_media_to_timeline([URI["speech"]], track="audio", at=1)
    win.seek(1.0)
    win.run("insert-title")
    settle()
    base = win.project.data

    def state(k):
        import copy
        win.project.data = copy.deepcopy(base)
        win.project._changed("all")
        win.seek(1.5)
        tr = {0: "video", 1: "music", 2: "titles"}.get(k)
        if tr:
            lst = clips(tr)
            win.timeline.select([lst[-1 if tr == "video" else 0]["id"]])
        else:
            win.timeline.select([])
        win.mediabin.select_uri(URI["photo"])

    cmds = commands()
    ran = 0
    unavailable = []
    for cmd in cmds:
        for k in range(4):
            answer[0] = Gtk.ResponseType.OK if k % 2 == 0 else Gtk.ResponseType.CANCEL
            state(k)
            win.notice_label.set_text("")
            try:
                win.run(cmd)
            except Exception:
                ERRORS.append(cmd + ": " + traceback.format_exc())
            if "isn't available" in win.notice_label.get_text():
                unavailable.append(cmd)
            if win.backstage_open():
                win.backstage.close()
            if win.keytips.active:
                win.keytips.leave()
            ran += 1
            pump(0.01)
    settle()
    check(ran > 200, "ran %d commands × states" % ran)
    check(not unavailable, "every command is available", sorted(set(unavailable)))
    for e in ERRORS[:5]:
        print(e)
    check(not ERRORS, "nothing raised", len(ERRORS))
    # the File page's own buttons
    for page in ("home", "new", "open", "export", "about"):
        win.show_backstage(page)
        pump(0.1)
    win.backstage.close()
    check(not ERRORS, "File's pages open")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
