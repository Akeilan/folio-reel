"""Reel's engine: a project (model.py) turned into a GStreamer Editing Services timeline, for the
preview (R3-02) and for export (R3-06). GES, GStreamer and their plugins come from the distro.

  probe(path)                  what a media file is (length, picture, sound, size)
  thumbnail(info, t, width)    a picture of it (GdkPixbuf)
  build(project, timeline, w, h)   the project's clips on the timeline's layers
  Preview(project)             a GES pipeline with a picture widget (gtksink); seek, play, rate
  Exporter(project, path, fmt, preset)  renders in its own pipeline, so editing goes on
"""
import copy
import os

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GES", "1.0")
gi.require_version("GstPbutils", "1.0")
gi.require_version("GstController", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GES, GLib, Gst, GstController, GstPbutils  # noqa: E402

from . import model  # noqa: E402

SECOND = 1000000000
_ready = False


def init():
    global _ready
    if not _ready:
        Gst.init(None)
        GES.init()
        _ready = True


def ns(secs):
    return int(round(max(0.0, secs) * SECOND))


# ------------------------------------------------------------------ media
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg")


def probe(path):
    """{"uri", "name", "duration", "has_video", "has_audio", "is_image", "width", "height"} or raises."""
    init()
    uri = model.path_to_uri(path) if "://" not in path else path
    name = os.path.basename(model.uri_to_path(uri) or uri)
    if name.lower().endswith(IMAGE_EXT):
        try:
            pb_info = GdkPixbuf.Pixbuf.get_file_info(model.uri_to_path(uri))
            w, h = pb_info[1], pb_info[2]
        except Exception:      # noqa: BLE001
            w, h = 0, 0
        return {"uri": uri, "name": name, "duration": model.IMAGE_SECONDS, "has_video": False, "has_audio": False,
                "is_image": True, "width": w, "height": h}
    disc = GstPbutils.Discoverer.new(15 * SECOND)
    try:
        info = disc.discover_uri(uri)
    except GLib.Error as e:
        raise model.EditError("“%s” couldn't be read: %s" % (name, e.message))
    vids = info.get_video_streams()
    auds = info.get_audio_streams()
    is_image = bool(vids) and vids[0].is_image()
    if not vids and not auds:
        raise model.EditError("“%s” has no picture or sound Reel can use." % name)
    w = vids[0].get_width() if vids else 0
    h = vids[0].get_height() if vids else 0
    dur = info.get_duration() / SECOND if info.get_duration() and not is_image else model.IMAGE_SECONDS
    return {"uri": uri, "name": name, "duration": dur, "has_video": bool(vids) and not is_image,
            "has_audio": bool(auds), "is_image": is_image, "width": w, "height": h}


def thumbnail(info, t=None, width=160):
    """A picture of the media at time t (default: a tenth of the way in)."""
    init()
    path = model.uri_to_path(info["uri"])
    w0, h0 = info.get("width") or 16, info.get("height") or 9
    height = max(2, int(width * h0 / max(1, w0)) // 2 * 2)
    if info.get("is_image") and path:
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, True)
        except GLib.Error:
            return None
    if not info.get("has_video"):
        return None
    t = info["duration"] * 0.1 if t is None else t
    pipe = Gst.parse_launch(
        "uridecodebin uri=%s ! videoconvert ! videoscale ! video/x-raw,format=RGB,width=%d,height=%d,pixel-aspect-ratio=1/1 "
        "! appsink name=sink" % (info["uri"], width, height))
    sink = pipe.get_by_name("sink")
    pb = None
    try:
        pipe.set_state(Gst.State.PAUSED)
        if pipe.get_state(10 * SECOND)[0] != Gst.StateChangeReturn.FAILURE:
            pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, ns(t))
            pipe.get_state(10 * SECOND)
            sample = sink.emit("pull-preroll")
            if sample is not None:
                buf = sample.get_buffer()
                ok, mi = buf.map(Gst.MapFlags.READ)
                if ok:
                    data = GLib.Bytes.new(bytes(mi.data))
                    buf.unmap(mi)
                    stride = (width * 3 + 3) // 4 * 4
                    pb = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, False, 8, width, height, stride)
    finally:
        pipe.set_state(Gst.State.NULL)
    return pb


_assets = {}


def asset(uri):
    a = _assets.get(uri)
    if a is None:
        a = _assets[uri] = GES.UriClipAsset.request_sync(uri)
    return a


# ------------------------------------------------------------------ building a timeline
VTYPES = {"crossfade": ("CROSSFADE", False), "wipe-right": ("BAR_WIPE_LR", False), "wipe-left": ("BAR_WIPE_LR", True),
          "wipe-down": ("BAR_WIPE_TB", False), "wipe-up": ("BAR_WIPE_TB", True), "box": ("BOX_WIPE_TL", False),
          "clock": ("CLOCK_CW12", False), "iris": ("IRIS_RECT", False)}
HALIGN = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
VALIGN = {"top": "TOP", "center": "CENTER", "bottom": "BOTTOM"}


def argb(hexstr):
    """'#aarrggbb' (or '#rrggbb') as the 32-bit ARGB number GES wants."""
    h = hexstr.lstrip("#")
    if len(h) == 6:
        h = "ff" + h
    return int(h, 16) & 0xFFFFFFFF


def make_timeline(width, height, fps):
    init()
    tl = GES.Timeline.new_audio_video()
    for t in tl.get_tracks():
        if t.get_property("track-type") == GES.TrackType.VIDEO:
            t.set_restriction_caps(Gst.Caps.from_string(
                "video/x-raw,width=%d,height=%d,framerate=%d/1" % (width, height, int(fps))))
    return tl


def _children(clip, kind):
    return [e for e in clip.get_children(False) if isinstance(e, kind)]


def _control(element, prop, points, absolute=True):
    """Keyframes [(time ns from the element's in point, value)] on a child property."""
    cs = GstController.InterpolationControlSource()
    cs.set_property("mode", GstController.InterpolationMode.LINEAR)
    for t, v in points:
        cs.set(int(t), float(v))
    element.set_control_source(cs, prop, "direct-absolute" if absolute else "direct")
    return cs


def _piecewise(points, t):
    """Value of a piecewise-linear function [(t, v)] at t (flat outside)."""
    if not points:
        return 1.0
    if t <= points[0][0]:
        return points[0][1]
    for (a, va), (b, vb) in zip(points, points[1:]):
        if a <= t <= b:
            return va if b - a < 1e-9 else va + (vb - va) * (t - a) / (b - a)
    return points[-1][1]


def gain_points(project, c):
    """The clip's loudness through time: its volume × volume points × fades × the music-bed dip.
    [(seconds into the clip, gain)]."""
    d = c["duration"]
    fade = []
    if c.get("fade_in", 0) > 0:
        fade += [(0.0, 0.0), (c["fade_in"], 1.0)]
    if c.get("fade_out", 0) > 0:
        fade += [(d - c["fade_out"], 1.0), (d, 0.0)]
    fade.sort()
    kf = [tuple(p) for p in c.get("keyframes", [])]
    duck = project.duck_points(c) if c.get("music_bed") else []
    times = {0.0, d}
    for pts in (fade, kf, duck):
        times.update(t for t, _v in pts if 0 <= t <= d)
    out = []
    for t in sorted(times):
        g = c.get("volume", 1.0) * _piecewise(fade, t) * (_piecewise(kf, t) if kf else 1.0) * \
            (_piecewise(duck, t) if duck else 1.0)
        out.append((t, g))
    return out


def alpha_points(c, dip_in=0.0, dip_out=0.0):
    d = c["duration"]
    fi = max(c.get("fade_in", 0.0), dip_in)
    fo = max(c.get("fade_out", 0.0), dip_out)
    if fi <= 0 and fo <= 0:
        return None
    pts = []
    if fi > 0:
        pts += [(0.0, 0.0), (fi, 1.0)]
    else:
        pts += [(0.0, 1.0)]
    if fo > 0:
        pts += [(max(fi, d - fo), 1.0), (d, 0.0)]
    else:
        pts += [(d, 1.0)]
    return pts


def _place(project, c, vs, width, height):
    """Zoom, crop and pan-and-zoom (R3-03) through the picture's position and size."""
    z = max(1.0, float(c.get("zoom", 1.0)))
    pz = c.get("panzoom")
    if z == 1.0 and not pz:
        return

    def rect(zoom, fx=0.5, fy=0.5):
        w, h = int(width * zoom), int(height * zoom)
        return (int(-(w - width) * fx), int(-(h - height) * fy), w, h)
    inp = ns(c["inpoint"]) if c["kind"] == "media" else 0
    if pz:
        a, b = {"in": (rect(z), rect(z * 1.3)), "out": (rect(z * 1.3), rect(z)),
                "left": (rect(z * 1.2, 1.0), rect(z * 1.2, 0.0)), "right": (rect(z * 1.2, 0.0), rect(z * 1.2, 1.0))}[pz]
        end = inp + ns(c["duration"] * c.get("speed", 1.0))
        for i, prop in enumerate(("posx", "posy", "width", "height")):
            _control(vs, prop, [(inp, a[i]), (end, b[i])])
    else:
        x, y, w, h = rect(z)
        for prop, v in (("posx", x), ("posy", y), ("width", w), ("height", h)):
            vs.set_child_property(prop, v)


def _effects(project, c, clip, media):
    col = c.get("color") or {}
    if any(abs(col.get(k, d) - d) > 1e-6 for k, d in (("brightness", 0.0), ("contrast", 1.0), ("saturation", 1.0), ("hue", 0.0))):
        clip.add(GES.Effect.new("videobalance brightness=%f contrast=%f saturation=%f hue=%f" % (
            col.get("brightness", 0.0), col.get("contrast", 1.0), col.get("saturation", 1.0), col.get("hue", 0.0))))
    cr = c.get("crop") or {}
    if media and any(cr.get(k, 0) > 0 for k in "lrtb") and media.get("width"):
        mw, mh = media["width"], media["height"]
        clip.add(GES.Effect.new("videocrop left=%d right=%d top=%d bottom=%d" % (
            int(cr.get("l", 0) * mw), int(cr.get("r", 0) * mw), int(cr.get("t", 0) * mh), int(cr.get("b", 0) * mh))))


def build(project, tl, width=None, height=None):
    """Put the project's tracks on the timeline (replacing what was there). Returns {clip id: GES clip}."""
    init()
    width = width or project.width
    height = height or project.height
    for layer in list(tl.get_layers()):
        tl.remove_layer(layer)
    layers = {}
    for name in model.TRACKS:
        layer = tl.append_layer()
        layer.set_auto_transition(name in ("video", "titles"))
        layers[name] = layer
    made = {}
    for name in model.TRACKS:
        clips = project.track(name)
        dips = {}
        for i, c in enumerate(clips):
            tr = c.get("transition")
            if tr and tr["type"] == "dip-black" and i > 0:
                dips.setdefault(c["id"], [0, 0])[0] = tr["duration"] / 2
                dips.setdefault(clips[i - 1]["id"], [0, 0])[1] = tr["duration"] / 2
        for c in clips:
            g = _add(project, layers[name], name, c, width, height, dips.get(c["id"], (0, 0)))
            if g is not None:
                made[c["id"]] = g
        # wipes and the like: the transition GES made where two clips overlap
        trans = [x for x in layers[name].get_clips() if isinstance(x, GES.TransitionClip)]
        for c in clips:
            tr = c.get("transition")
            if not tr or tr["type"] in ("dip-black", "crossfade"):
                continue
            vname, invert = VTYPES.get(tr["type"], ("CROSSFADE", False))
            vtype = getattr(GES.VideoStandardTransitionType, vname, GES.VideoStandardTransitionType.CROSSFADE)
            for t in trans:
                if abs(t.get_start() - ns(c["start"])) < SECOND // 50:
                    t.set_property("vtype", vtype)
                    for el in t.get_children(False):
                        if isinstance(el, GES.VideoTransition):
                            el.set_inverted(invert) if hasattr(el, "set_inverted") else None
    tl.commit()
    return made


def _add(project, layer, track, c, width, height, dip):
    if c["kind"] == "media":
        media = project.media_by_uri(c["media"])
        if media is None or not os.path.exists(model.uri_to_path(c["media"]) or ""):
            return None
        a = asset(c["media"])
        types = GES.TrackType.AUDIO if track in ("audio", "music") else GES.TrackType.UNKNOWN
        sp = float(c.get("speed", 1.0))
        span = c["duration"] * sp
        if not media.get("is_image"):
            span = min(span, max(0.04, media["duration"] - c["inpoint"]))
        clip = layer.add_asset(a, ns(c["start"]), 0 if media.get("is_image") else ns(c["inpoint"]), ns(span), types)
        if clip is None:
            return None
        if abs(sp - 1.0) > 1e-6:
            if media.get("has_video") and track in ("video", "titles"):
                clip.add(GES.Effect.new("videorate rate=%f" % sp))
            if media.get("has_audio"):
                clip.add(GES.Effect.new("pitch tempo=%f" % sp))
            clip.set_duration(ns(c["duration"]))
        if track in ("video", "titles"):
            _effects(project, c, clip, media)
        inp = 0 if media.get("is_image") else ns(c["inpoint"])
        for vs in _children(clip, GES.VideoSource):
            ap = alpha_points(c, dip[0], dip[1])
            if ap:
                _control(vs, "alpha", [(inp + ns(t * sp), v) for t, v in ap], absolute=False)
            _place(project, c, vs, width, height)
        for au in _children(clip, GES.AudioSource):
            if c.get("muted"):
                au.set_child_property("mute", True)
            pts = gain_points(project, c)
            if len(pts) > 1 and any(abs(v - 1.0) > 1e-6 for _t, v in pts):
                _control(au, "volume", [(inp + ns(t * sp), v) for t, v in pts])
        return clip
    # titles, lower thirds, captions: text drawn by GES over what's below (R3-04)
    clip = GES.TitleClip()
    clip.set_start(ns(c["start"]))
    clip.set_duration(ns(c["duration"]))
    layer.add_clip(clip)
    clip.set_child_property("text", c.get("text", ""))
    clip.set_child_property("font-desc", c.get("font", "Sans Bold 48"))
    clip.set_child_property("color", argb(c.get("text_color", "#ffffffff")))
    bg = argb(c.get("bg_color", "#ff000000"))
    clip.set_child_property("foreground-color", bg)
    try:
        clip.set_child_property("pattern", 17)       # videotestsrc solid-color: the background
    except Exception:       # noqa: BLE001
        pass
    clip.set_child_property("halignment", getattr(GES.TextHAlign, HALIGN.get(c.get("halign", "center"), "CENTER")))
    clip.set_child_property("valignment", getattr(GES.TextVAlign, VALIGN.get(c.get("valign", "center"), "CENTER")))
    clip.set_child_property("draw-shadow", c["kind"] != "title")
    for vs in _children(clip, GES.VideoSource):
        ap = alpha_points(c, dip[0], dip[1])
        if ap:
            _control(vs, "alpha", [(ns(t), v) for t, v in ap], absolute=False)
    return clip


# ------------------------------------------------------------------ preview
class Preview:
    """A pipeline that plays the project; widget is the picture (or None without gtksink)."""

    def __init__(self, project, on_event=None):
        init()
        self.project = project
        self.on_event = on_event or (lambda ev, val=None: None)
        self.timeline = make_timeline(project.width, project.height, project.fps)
        self.pipeline = GES.Pipeline()
        self.pipeline.set_timeline(self.timeline)
        self.pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)
        sink_name = os.environ.get("FOLIO_REEL_VIDEOSINK", "gtksink")
        self.sink = Gst.ElementFactory.make(sink_name) or Gst.ElementFactory.make("gtksink")
        self.widget = None
        if self.sink is not None:
            self.pipeline.preview_set_video_sink(self.sink)
            if self.sink.find_property("widget"):
                self.widget = self.sink.get_property("widget")
        a = os.environ.get("FOLIO_REEL_AUDIOSINK")
        if a:
            self.pipeline.preview_set_audio_sink(Gst.ElementFactory.make(a))
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._message)
        self.rate = 1.0
        self.state = "paused"
        self._size = (project.width, project.height)
        self.refresh()
        self.pipeline.set_state(Gst.State.PAUSED)

    def _message(self, bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            self.pause()
            self.on_event("eos")
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            self.on_event("error", err.message)

    def refresh(self):
        """The project changed: rebuild the timeline in place and stay where we were."""
        pos = self.position()
        if (self.project.width, self.project.height) != self._size:
            self._size = (self.project.width, self.project.height)
            for t in self.timeline.get_tracks():
                if t.get_property("track-type") == GES.TrackType.VIDEO:
                    t.set_restriction_caps(Gst.Caps.from_string(
                        "video/x-raw,width=%d,height=%d,framerate=%d/1" % (self.project.width, self.project.height,
                                                                           int(self.project.fps))))
        build(self.project, self.timeline)
        self.timeline.commit_sync()
        if pos:
            self.seek(min(pos, max(0.0, self.duration())))

    def duration(self):
        return self.timeline.get_duration() / SECOND

    def position(self):
        try:
            ok, p = self.pipeline.query_position(Gst.Format.TIME)
        except Exception:       # noqa: BLE001
            return 0.0
        return p / SECOND if ok and p >= 0 else 0.0

    def seek(self, secs, accurate=True):
        secs = max(0.0, min(secs, self.duration()))
        flags = Gst.SeekFlags.FLUSH | (Gst.SeekFlags.ACCURATE if accurate else Gst.SeekFlags.KEY_UNIT)
        if abs(self.rate - 1.0) > 1e-6 and self.state == "playing":
            self.pipeline.seek(self.rate, Gst.Format.TIME, flags, Gst.SeekType.SET, ns(secs), Gst.SeekType.NONE, -1)
        else:
            self.pipeline.seek_simple(Gst.Format.TIME, flags, ns(secs))
        self.on_event("position", secs)

    def step(self, frames):
        self.pause()
        self.seek(self.position() + frames / float(self.project.fps))

    def play(self, rate=1.0):
        self.rate = rate
        if self.position() >= self.duration() - 0.05:
            self.seek(0)
        self.pipeline.set_state(Gst.State.PLAYING)
        if abs(rate - 1.0) > 1e-6:
            self.pipeline.get_state(2 * SECOND)
            self.pipeline.seek(rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                               Gst.SeekType.SET, ns(self.position()), Gst.SeekType.NONE, -1)
        self.state = "playing"
        self.on_event("state", "playing")

    def pause(self):
        self.pipeline.set_state(Gst.State.PAUSED)
        if abs(self.rate - 1.0) > 1e-6:
            self.rate = 1.0
            self.pipeline.get_state(2 * SECOND)
            self.pipeline.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                               Gst.SeekType.SET, ns(self.position()), Gst.SeekType.NONE, -1)
        self.state = "paused"
        self.on_event("state", "paused")

    def toggle(self):
        self.pause() if self.state == "playing" else self.play()

    def snapshot(self, path=None):
        """The picture at the playhead (GdkPixbuf), or saved as PNG."""
        caps = Gst.Caps.from_string("video/x-raw,format=RGB,pixel-aspect-ratio=1/1")
        try:
            sample = self.pipeline.get_thumbnail(caps)
        except Exception:       # noqa: BLE001
            sample = None
        if sample is None:
            return None
        s = sample.get_caps().get_structure(0)
        w, h = s.get_value("width"), s.get_value("height")
        buf = sample.get_buffer()
        ok, mi = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        data = GLib.Bytes.new(bytes(mi.data))
        buf.unmap(mi)
        pb = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, False, 8, w, h, (w * 3 + 3) // 4 * 4)
        if path:
            pb.savev(path, "png", [], [])
        return pb

    def close(self):
        self.pipeline.set_state(Gst.State.NULL)


# ------------------------------------------------------------------ export (R3-06)
FORMATS = {"mp4": "MP4 (H.264 / AAC)", "webm": "WebM (VP9 / Opus)"}


def _pick(*names):
    for n in names:
        if Gst.ElementFactory.find(n):
            return n
    return None


def encoding_profile(fmt, width, height, fps):
    init()
    raw_v = Gst.Caps.from_string("video/x-raw,width=%d,height=%d,framerate=%d/1" % (width, height, int(fps)))
    raw_a = Gst.Caps.from_string("audio/x-raw,channels=2,rate=48000")
    if fmt == "webm":
        cont = GstPbutils.EncodingContainerProfile.new("webm", None, Gst.Caps.from_string("video/webm"), None)
        vcaps = "video/x-vp9" if _pick("vp9enc") else "video/x-vp8"
        acaps = "audio/x-opus" if _pick("opusenc") else "audio/x-vorbis"
    else:
        cont = GstPbutils.EncodingContainerProfile.new("mp4", None, Gst.Caps.from_string("video/quicktime,variant=iso"), None)
        vcaps = "video/x-h264"
        acaps = "audio/mpeg,mpegversion=4"
    vp = GstPbutils.EncodingVideoProfile.new(Gst.Caps.from_string(vcaps), None, raw_v, 0)
    ap = GstPbutils.EncodingAudioProfile.new(Gst.Caps.from_string(acaps), None, raw_a, 0)
    try:
        # quicker encoders: rendering a long film shouldn't take all afternoon
        if vcaps == "video/x-h264" and _pick("x264enc"):
            vp.set_preset_name("x264enc")
            vp.set_element_properties(Gst.Structure.from_string(
                "element-properties-map, map={[x264enc, speed-preset=(string)faster, tune=(string)zerolatency]}")[0])
        elif vcaps == "video/x-vp9":
            vp.set_element_properties(Gst.Structure.from_string(
                "element-properties-map, map={[vp9enc, deadline=(int64)1, cpu-used=(int)8]}")[0])
    except Exception:       # noqa: BLE001 — older GStreamer: default settings
        pass
    cont.add_profile(vp)
    cont.add_profile(ap)
    return cont


def missing_encoders(fmt):
    need = ("x264enc", "mp4mux") if fmt == "mp4" else ("webmmux",)
    out = [n for n in need if not _pick(n)]
    if fmt == "mp4" and not _pick("avenc_aac", "voaacenc", "fdkaacenc", "faac"):
        out.append("an AAC encoder")
    if fmt == "webm" and not _pick("vp9enc", "vp8enc"):
        out.append("a VP9 or VP8 encoder")
    return out


class Exporter:
    """Renders a copy of the project to a file. on_progress(fraction), on_done(path or None, error)."""

    def __init__(self, project, path, fmt="mp4", preset="1080p", on_progress=None, on_done=None):
        init()
        self.path = path
        self.on_progress = on_progress or (lambda f: None)
        self.on_done = on_done or (lambda p, e: None)
        if preset in model.PRESETS:
            w, h = model.PRESETS[preset]
        else:
            w, h = project.width, project.height
        # the project's own shape (portrait, square) is kept at the preset's size
        if project.height > project.width:
            w, h = h, w
        elif project.height == project.width:
            w = h
        self.size = (w, h)
        snap = model.Project(copy.deepcopy(project.data))
        self.timeline = make_timeline(w, h, project.fps)
        build(snap, self.timeline, w, h)
        self.timeline.commit_sync()
        self.duration = self.timeline.get_duration()
        self.pipeline = GES.Pipeline()
        self.pipeline.set_timeline(self.timeline)
        prof = encoding_profile(fmt, w, h, project.fps)
        if os.path.exists(path):
            os.remove(path)
        if not self.pipeline.set_render_settings(model.path_to_uri(path), prof):
            raise model.EditError("This computer can't make %s files." % FORMATS.get(fmt, fmt))
        self.pipeline.set_mode(GES.PipelineFlags.RENDER)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        self._bus_id = bus.connect("message", self._message)
        self._timer = None
        self.done = False
        self.error = None

    def start(self):
        if self.duration <= 0:
            raise model.EditError("There's nothing on the timeline to export.")
        self.pipeline.set_state(Gst.State.PLAYING)
        self._timer = GLib.timeout_add(250, self._tick)

    def _tick(self):
        if self.done:
            return False
        ok, p = self.pipeline.query_position(Gst.Format.TIME)
        if ok and self.duration:
            self.on_progress(max(0.0, min(1.0, p / self.duration)))
        return True

    def _finish(self, error=None):
        if self.done:
            return
        self.done = True
        self.error = error
        self.pipeline.set_state(Gst.State.NULL)
        bus = self.pipeline.get_bus()
        bus.disconnect(self._bus_id)
        bus.remove_signal_watch()
        if error and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.on_progress(1.0 if not error else 0.0)
        self.on_done(None if error else self.path, error)

    def _message(self, bus, msg):
        if msg.type == Gst.MessageType.EOS:
            self._finish()
        elif msg.type == Gst.MessageType.ERROR:
            err, _dbg = msg.parse_error()
            self._finish(err.message)

    def cancel(self):
        self._finish("cancelled")

    def run_sync(self, timeout=600):
        """For tests and the command line: render and wait."""
        self.start()
        ctx = GLib.MainContext.default()
        import time
        end = time.time() + timeout
        while not self.done and time.time() < end:
            ctx.iteration(False)
            time.sleep(0.01)
        if not self.done:
            self.cancel()
        return self.error is None
