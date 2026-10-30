# X2-01 for Folio Reel: under a dark desktop theme (app dark, and app set to light) or the loud
# FolioTestColour theme, the window, Clip Settings, File and the dialogs keep Reel's own colours.
import os
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())
import themecheck  # noqa: E402

LOOKED = []


def look(w, where):
    pump(0.4)
    probs = themecheck.audit(w, where)
    if probs:
        pump(1.5)
        probs = themecheck.audit(w, where)
    for p in probs:
        print("FAIL " + p)
    if probs or os.environ.get("THEME_SHOTS"):
        themecheck.save(w, os.path.join(OUT, "theme_%s%s_%s.png" % (themecheck.mode(), os.environ.get("FOLIO_THEME", ""),
                                                                    where.replace(" ", "_"))))
    FAILS.extend(probs)
    LOOKED.append(where)
    if not probs:
        print("ok   %s (%s)" % (where, themecheck.mode()))


try:
    print("theme", os.environ.get("GTK_THEME"), "mode", themecheck.mode(), "app", os.environ.get("FOLIO_THEME", "desktop"))
    pump(0.5)
    look(win, "empty project")
    win.import_uris([URI[k] for k in ("red", "blue", "music", "speech", "photo")])
    win.add_media_to_timeline([URI["red"]])
    win.add_media_to_timeline([URI["blue"]])
    win.add_media_to_timeline([URI["music"]], track="music", at=0)
    win.seek(1.0)
    win.run("insert-title")
    settle()
    win.timeline.select([clips("video")[1]["id"]])
    win.run("transition:crossfade")
    look(win, "video clip settings")
    win.timeline.select([clips("music")[0]["id"]])
    look(win, "music clip settings")
    win.timeline.select([clips("titles")[0]["id"]])
    look(win, "title settings")
    for page in ("home", "open", "export", "about"):
        win.show_backstage(page)
        look(win, "File " + page)
    win.backstage.close()
    for tab in ("Insert", "Transitions", "Effects", "Audio", "View"):
        win.ribbon.select(win.ribbon.tab_by_name(tab))
        look(win, "ribbon " + tab)
    win.timeline.select([clips("video")[0]["id"]])

    def crop(d):
        look(d[0], "Crop dialog")
    respond("crop_dialog", Gtk.ResponseType.CANCEL, setup=crop)
    win.run("crop")
    win.run("full-screen")
    pump(0.5)
    look(win.full, "full screen")
    win.full.leave()
    check(len(LOOKED) >= 15, "looked at every part", LOOKED)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
