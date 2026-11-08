"""Folio Reel's ribbon: Home, Insert, Transitions, Effects, Audio and View, with KeyTips and
ScreenTips from the suite's shared ribbon code."""
from . import screentips
from .model import EXPORT_PRESETS, TRANSITIONS
from .ribbon import CheckControl, Group, MenuButton, RibbonButton, SplitButton, Tab


class Cmd:
    """A menu callback that remembers its command (the command walk test reads it)."""
    def __init__(self, win, cmd):
        self.win = win
        self.cmd = cmd

    def __call__(self, *_):
        self.win.run(self.cmd)


def _tip(label, tip):
    """'Split (S): cut the clip in two' -> ScreenTip title 'Split (S)' with that description."""
    tip = tip or label or ""
    title, sep, desc = tip.partition(": ")
    if not sep:
        title, desc = tip, ""
    base = title.split(" (")[0]
    if not desc and base not in screentips.TIPS:
        desc = REEL_TIPS.get(base, "")
    if desc:
        screentips.TIPS[base] = desc[0].upper() + desc[1:] + ("" if desc.endswith(".") else ".")
    return title


REEL_TIPS = {
    "Paste": "Put the copied clips in at the playhead.", "Cut": "Take the selected clips out to paste somewhere else.",
    "Copy": "Copy the selected clips to paste somewhere else.", "Delete": "Delete the selected clips, leaving a gap.",
    "Select All": "Select every clip on the timeline.", "Previous Frame": "Step back one frame.",
    "Next Frame": "Step on one frame.", "Full Screen": "Show the preview on the whole screen.",
    "None": "Take the transition away.", "Duration": "How long the transition takes.",
    "Black and White": "Take the colour out of the picture.", "Brighter": "Make the picture brighter.",
    "Darker": "Make the picture darker.", "More Contrast": "Make darks darker and lights lighter.",
    "Less Contrast": "Soften the difference between darks and lights.", "Reset Colour": "Put the colours back as filmed.",
    "Fade In": "Start from black (or silence).", "Fade Out": "End in black (or silence).",
    "Volume": "How loud the selected clips are.", "Mute": "Silence the clip's sound.",
    "Clear Volume Points": "Take away the clip's volume points.", "Zoom In": "Show the timeline in more detail.",
    "Zoom Out": "Show more of the timeline.", "Zoom to Fit": "Show the whole project on the timeline.",
    "Snapping": "Clips snap to clip edges and the playhead.", "Shape of the video": "Widescreen, portrait, square or 4:3.",
    "Frame Rate": "Frames a second of the exported video.", "Shape": "Widescreen, portrait, square or 4:3.",
    "Title": "A title card at the playhead.", "Import Media": "Put video, sound and pictures in the media bin.",
    "Marker": "Mark this moment on the timeline, to find it again and to snap clips to.",
}


class Builder:
    def __init__(self, win):
        self.win = win
        self.r = win.ribbon

    def menu(self, items):
        out = []
        for it in items:
            if it is None or (isinstance(it, tuple) and it[0] == "#"):
                out.append(it)
                continue
            label, cmd = it[0], it[1]
            icon = it[2] if len(it) > 2 else None
            out.append((label, Cmd(self.win, cmd), icon) if icon else (label, Cmd(self.win, cmd)))
        return out

    def big(self, label, icon, cmd, keytip, menu=None, tip=None):
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self.menu(menu), size="large", keytip=keytip, tooltip=_tip(label, tip))
            return SplitButton(self.r, label, icon, cmd, self.menu(menu), size="large", keytip=keytip, tooltip=_tip(label, tip))
        return RibbonButton(self.r, label, icon, cmd, size="large", keytip=keytip, tooltip=_tip(label, tip))

    def small(self, label, icon, cmd, keytip, menu=None, tip=None, state=None):
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self.menu(menu), size="small", keytip=keytip, tooltip=_tip(label, tip))
            return SplitButton(self.r, label, icon, cmd, self.menu(menu), size="small", keytip=keytip,
                               tooltip=_tip(label, tip), state=state)
        return RibbonButton(self.r, label, icon, cmd, size="small", keytip=keytip, tooltip=_tip(label, tip), state=state)

    def group(self, tab, caption, columns, launcher=None, launcher_keytip=None):
        g = Group(caption, columns, launcher=launcher, ribbon=self.r, launcher_keytip=launcher_keytip)
        tab.add(g)
        return g


SPEEDS = [("0.25×", "speed:0.25"), ("0.5×", "speed:0.5"), ("0.75×", "speed:0.75"), ("Normal (1×)", "speed:1"),
          ("1.5×", "speed:1.5"), ("2×", "speed:2"), ("4×", "speed:4")]
VOLUMES = [("Mute (0%)", "volume:0"), ("25%", "volume:0.25"), ("50%", "volume:0.5"), ("75%", "volume:0.75"),
           ("100%", "volume:1"), ("150%", "volume:1.5"), ("200%", "volume:2")]
DURATIONS = [("0.25 s", "transition-duration:0.25"), ("0.5 s", "transition-duration:0.5"),
             ("1 s", "transition-duration:1"), ("1.5 s", "transition-duration:1.5"), ("2 s", "transition-duration:2")]
FADES = [("None", "%s:0"), ("0.5 s", "%s:0.5"), ("1 s", "%s:1"), ("2 s", "%s:2"), ("3 s", "%s:3")]
STRAIGHTEN = [("Straight (none)", "lens:0"), ("Bulge: a little", "lens:30"), ("Bulge: more", "lens:60"),
              ("Bulge: most", "lens:100"), ("Pinch: a little", "lens:-30"), ("Pinch: more", "lens:-60"),
              ("Pinch: most", "lens:-100")]


def build_ribbon(win):
    B = Builder(win)
    r = win.ribbon

    # ================================================================ Home
    t = r.building(Tab("Home", "H"))
    B.group(t, "Clipboard", [
        B.big("Paste", "paste", "paste", "V", tip="Paste (Ctrl+V): the copied clips go in at the playhead"),
        [B.small("Cut", "cut", "cut", "X", tip="Cut (Ctrl+X)"), B.small("Copy", "copy", "copy", "C", tip="Copy (Ctrl+C)")],
    ])
    B.group(t, "Media", [
        B.big("Import Media", "reel-import", "import-media", "I",
              tip="Import Media (Ctrl+I): put video, sound and pictures in the media bin"),
        [B.small("Add to Timeline", "reel-add", "add-to-timeline", "AT",
                 tip="Add to Timeline: the media chosen in the bin goes in at the playhead")],
    ])
    B.group(t, "Editing", [
        B.big("Split", "reel-split", "split", "S", tip="Split (S): cut the clip in two at the playhead"),
        [B.small("Trim Start", "reel-trim-start", "trim-start", "TS", tip="Trim Start: the clip now starts at the playhead"),
         B.small("Trim End", "reel-trim-end", "trim-end", "TE", tip="Trim End: the clip now ends at the playhead"),
         B.small("Delete", "delete", "delete", "D", tip="Delete (Delete)")],
        [B.small("Group", "reel-group", "group", "G",
                 tip="Group (Ctrl+G): the selected clips move and trim as one"),
         B.small("Ungroup", "reel-ungroup", "ungroup", "UG", tip="Ungroup (Ctrl+Shift+G)")],
        [B.small("Ripple Delete", "reel-ripple", "ripple-delete", "RD",
                 tip="Ripple Delete (Shift+Delete): delete and close the gap"),
         B.small("Select All", "selectall", "select-all", "SA", tip="Select All (Ctrl+A)"),
         B.small("Clip Settings", "reel-properties", "clip-properties", "P", tip="Clip Settings: show the clip's settings")],
    ])
    B.group(t, "Playback", [
        B.big("Play", "reel-play", "play", "PL", tip="Play / Pause (Space). J, K and L play back, stop and play forward"),
        [B.small("Previous Frame", "reel-prev-frame", "frame-back", "FB", tip="Previous Frame (Left)"),
         B.small("Next Frame", "reel-next-frame", "frame-forward", "FF", tip="Next Frame (Right)"),
         B.small("Full Screen", "fullscreen", "full-screen", "FS", tip="Full-Screen Preview (F11)")],
    ])
    B.group(t, "Markers", [
        B.big("Marker", "reel-marker", "marker-add", "M", menu=[
            ("Add Marker (M)", "marker-add"),
            ("Name This Marker (Shift+M)", "marker-rename"),
            None,
            ("Previous Marker (,)", "marker-prev"),
            ("Next Marker (.)", "marker-next"),
            None,
            ("Delete This Marker", "marker-delete"),
            ("Delete All Markers", "marker-clear"),
        ], tip="Marker (M): mark this moment on the timeline. Clips snap to markers"),
    ])
    B.group(t, "Share", [
        B.big("Export Video", "reel-export", "export", "E",
              menu=[(name, "export:%s/%s" % (fmt, size)) for name, fmt, size in EXPORT_PRESETS] +
                   [None, ("More Export Settings…", "export")],
              tip="Export Video (Ctrl+E): make an MP4 or WebM file. The arrow picks a preset; "
                  "several exports wait their turn"),
    ])
    r.add_tab(t)

    # ================================================================ Insert
    t = r.building(Tab("Insert", "N"))
    B.group(t, "Media", [
        B.big("Import Media", "reel-import", "import-media", "I", tip="Import Media (Ctrl+I)"),
    ])
    B.group(t, "Record", [
        B.big("Record Screen", "reel-screen", "record-screen", "RS", tip="Record Screen: record the whole screen into the project"),
        [B.small("Record Window", "reel-window", "record-window", "RW", tip="Record Window: record one window"),
         B.small("Record Camera", "reel-camera", "record-camera", "RC", tip="Record Camera: record from a webcam"),
         B.small("Voice-over", "reel-mic", "record-voice", "RV",
                 tip="Record Voice-over: record from the microphone onto the Audio track at the playhead")],
    ])
    B.group(t, "Text", [
        B.big("Title", "reel-title", "insert-title", "T", tip="Title: a title card at the playhead"),
        [B.small("Lower Third", "reel-lowerthird", "insert-lower-third", "L", tip="Lower Third: a name and role over the picture"),
         B.small("Caption", "reel-caption", "insert-caption", "CA", tip="Caption: words across the bottom of the picture")],
    ])
    B.group(t, "Proxies", [
        [B.small("Make Small Copies", "reel-import", "make-proxies", "MP",
                 tip="Make small copies of the videos for a smoother preview; exports use the originals"),
         B.small("Use Small Copies", "reel-play", "use-proxies", "UP", tip="Play the small copies in the preview"),
         B.small("Remove Small Copies", "reel-reset", "remove-proxies", "RP", tip="Throw the small copies away")],
    ])
    B.group(t, "Preview", [
        [B.small("Full Size", "reel-play", "preview-quality:1", "QF", tip="Play the preview at full size"),
         B.small("Half Size", "reel-play", "preview-quality:2", "QH", tip="Play the preview at half size: smoother on a slow machine"),
         B.small("Quarter Size", "reel-play", "preview-quality:4", "QQ", tip="Play the preview at quarter size")],
    ])
    B.group(t, "Subtitles", [
        [B.small("Import Subtitles", "reel-caption", "import-subtitles", "IS",
                 tip="Import Subtitles: an .srt file becomes captions on the Titles track"),
         B.small("Export Subtitles", "reel-caption", "export-subtitles", "ES",
                 tip="Export Subtitles: the captions written out as an .srt beside the film")],
    ])
    r.add_tab(t)

    # ================================================================ Transitions
    t = r.building(Tab("Transitions", "K"))
    gallery = [B.big("None", "reel-none", "transition:none", "0", tip="No transition")]
    for i, (key, name) in enumerate(TRANSITIONS):
        gallery.append(B.big(name, "reel-" + key, "transition:" + key, str(i + 1),
                             tip="%s: into the selected clip from the one before it" % name))
    B.group(t, "Transition to This Clip", gallery)
    B.group(t, "Timing", [
        [B.small("Duration", "timefield", None, "D", menu=DURATIONS, tip="Duration of the transition")],
    ])
    r.add_tab(t)

    # ================================================================ Effects
    t = r.building(Tab("Effects", "X"))
    B.group(t, "Colour", [
        [B.small("Black and White", "reel-bw", "color:bw", "BW", tip="Black and White"),
         B.small("Brighter", "reel-brighter", "color:brighter", "BR", tip="Brighter"),
         B.small("Darker", "reel-darker", "color:darker", "DK", tip="Darker")],
        [B.small("More Contrast", "reel-contrast", "color:contrast+", "C+", tip="More Contrast"),
         B.small("Less Contrast", "grafcontrast", "color:contrast-", "C-", tip="Less Contrast"),
         B.small("Reset Colour", "reel-reset", "color:reset", "CR", tip="Reset Colour")],
    ])
    B.group(t, "Speed", [
        B.big("Speed", "reel-speed", None, "SP", menu=SPEEDS, tip="Speed: slow motion or fast forward"),
    ])
    B.group(t, "Picture", [
        B.big("Pan and Zoom", "reel-panzoom", None, "PZ",
              menu=[("None", "panzoom:none"), ("Zoom In", "panzoom:in"), ("Zoom Out", "panzoom:out"),
                    ("Pan Left to Right", "panzoom:right"), ("Pan Right to Left", "panzoom:left")],
              tip="Pan and Zoom: slow movement across a picture"),
        [B.small("Zoom", "reel-zoom", None, "Z",
                 menu=[("100%", "zoom:1"), ("110%", "zoom:1.1"), ("125%", "zoom:1.25"), ("150%", "zoom:1.5"), ("200%", "zoom:2")],
                 tip="Zoom: fill more of the frame"),
         B.small("Crop", "crop", "crop", "CP", tip="Crop: cut away the edges of the picture"),
         B.small("Reset Picture", "reel-reset", "picture:reset", "RP", tip="Reset Picture: no zoom, crop or movement")],
    ])
    B.group(t, "Fade", [
        [B.small("Fade In", "reel-fadein", None, "FI", menu=[(l, c % "fade-in") for l, c in FADES], tip="Fade In from black"),
         B.small("Fade Out", "reel-fadeout", None, "FO", menu=[(l, c % "fade-out") for l, c in FADES], tip="Fade Out to black")],
    ])
    B.group(t, "Steady", [
        B.big("Steady", "reel-aspect", "steady", "SD",
              tip="Steady: take the shake out of the selected clip"),
        [B.small("Straighten", "reel-panzoom", None, "SR", menu=STRAIGHTEN,
                 tip="Straighten: take the bulge or the pinch out of the lens"),
         B.small("Render Correction", "reel-export", "steady-apply", "SA",
                 tip="Render Correction: make the corrected copy the selected clip asks for"),
         B.small("Remove Corrections", "reel-reset", "remove-fixes", "SX",
                 tip="Remove Corrections: throw the corrected copies away")],
    ])
    r.add_tab(t)

    # ================================================================ Audio
    t = r.building(Tab("Audio", "A"))
    B.group(t, "Level", [
        B.big("Volume", "reel-volume", None, "V", menu=VOLUMES, tip="Volume of the selected clips"),
        [B.small("Mute", "reel-mute", "mute", "M", tip="Mute the clip's sound", state="muted"),
         B.small("Fade In", "reel-fadein", None, "FI", menu=[(l, c % "fade-in") for l, c in FADES], tip="Sound fades in"),
         B.small("Fade Out", "reel-fadeout", None, "FO", menu=[(l, c % "fade-out") for l, c in FADES], tip="Sound fades out")],
    ])
    B.group(t, "Volume Points", [
        [B.small("Add Point", "reel-keyframe", "keyframe-add", "KA",
                 tip="Add Volume Point: hold the clip's current level at the playhead; drag levels in Clip Settings"),
         B.small("Dip Here", "reel-duck", "keyframe-dip", "KD", tip="Dip Here: lower the sound around the playhead"),
         B.small("Clear Points", "reel-reset", "keyframe-clear", "KC", tip="Clear Volume Points")],
    ])
    B.group(t, "Music", [
        B.big("Music Bed", "reel-music", "music-bed", "B",
              tip="Music Bed: the music dips under speech and voice-over on the Audio track"),
    ])
    B.group(t, "Record", [
        B.big("Voice-over", "reel-mic", "record-voice", "R", tip="Record Voice-over at the playhead"),
    ])
    r.add_tab(t)

    # ================================================================ View
    t = r.building(Tab("View", "W"))
    B.group(t, "Zoom", [
        [B.small("Zoom In", "zoomin", "zoom-in", "ZI", tip="Zoom In on the timeline (Ctrl+=)"),
         B.small("Zoom Out", "zoomout", "zoom-out", "ZO", tip="Zoom Out (Ctrl+-)"),
         B.small("Zoom to Fit", "zoomoptimal", "zoom-fit", "ZF", tip="Zoom to Fit the whole project (Ctrl+0)")],
    ])
    snap = CheckControl(r, "Snapping", "snapping", active=True, state="snapping", keytip="SN",
                        tooltip=_tip("Snapping", "Snapping: clips snap to clip edges and the playhead"))
    win.snap_check = snap
    B.group(t, "Timeline", [[snap]])
    B.group(t, "Project", [
        B.big("Shape", "reel-aspect", None, "SH",
              menu=[("Widescreen 16:9", "aspect:16:9"), ("Portrait 9:16", "aspect:9:16"), ("Square 1:1", "aspect:1:1"),
                    ("Standard 4:3", "aspect:4:3")], tip="Shape of the video"),
        B.big("Frame Rate", "reel-fps", None, "FR",
              menu=[("24 frames a second", "fps:24"), ("25 frames a second", "fps:25"), ("30 frames a second", "fps:30"),
                    ("60 frames a second", "fps:60")], tip="Frame Rate"),
    ])
    B.group(t, "Preview", [
        B.big("Full Screen", "fullscreen", "full-screen", "F", tip="Full-Screen Preview (F11; Esc returns)"),
    ])
    r.add_tab(t)
    r.select(r.tabs[0])
