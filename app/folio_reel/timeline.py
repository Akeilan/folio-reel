"""The timeline (R3-01): a ruler and four tracks drawn on one area. Click to move the playhead,
drag clips to move them (to another track too), drag their edges to trim, with snapping to clip
edges and the playhead. Ctrl+wheel zooms; the wheel scrolls."""
import math

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import model
from .model import EPS, TRACKS, TRACK_NAMES, end_of

HEAD = 96            # track names on the left
RULER = 26
MARKER_W = 9      # the marker flag on the ruler (R4-05)
MARKER_H = 11
HEIGHTS = {"titles": 40, "video": 64, "audio": 46, "music": 46}
EDGE = 6             # px at a clip's ends that trim instead of move
GRAB = 5             # px either side of the playhead that grab it, over anything underneath
EDGE_SCROLL = 56     # px at the ends of the view where a drag carries the view along (R5-01)
SCROLL_RATE = 460    # px a second the view travels while a drag sits right at the edge
SNAP_PX = 8
COLORS = {"titles": (0.48, 0.36, 0.66), "video": (0.22, 0.36, 0.60), "audio": (0.24, 0.55, 0.36),
          "music": (0.18, 0.52, 0.54)}


class Timeline(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.get_style_context().add_class("reel-timeline")
        self.pps = 40.0                  # pixels per second
        self.selected = []               # clip ids
        self.drag = None
        self._scroll_id = None           # the view travelling under a held drag (R5-01)
        self._scrolling = False
        self.ghost = None                # (track, start, duration) while dragging
        self.snap_line = None
        self.thumbs = {}
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("button-press-event", self._press)
        self.area.connect("button-release-event", self._release)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("scroll-event", self._scroll)
        self.area.set_size_request(-1, RULER + sum(HEIGHTS.values()) + 4)
        self.adj = Gtk.Adjustment(value=0, lower=0, upper=100, step_increment=20, page_increment=200, page_size=100)
        self.adj.connect("value-changed", lambda *_: self.area.queue_draw())
        self.scroll = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.adj)
        self.pack_start(self.area, True, True, 0)
        self.pack_start(self.scroll, False, False, 0)
        self.area.connect("size-allocate", lambda *_: self.update_range())
        # files and media dropped on the timeline
        self.area.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.area.drag_dest_add_uri_targets()
        self.area.connect("drag-data-received", self._dropped)

    # ------------------------------------------------------------ geometry
    @property
    def project(self):
        return self.win.project

    def x_of(self, t):
        return HEAD + t * self.pps - self.adj.get_value()

    def t_of(self, x):
        return max(0.0, (x - HEAD + self.adj.get_value()) / self.pps)

    def track_rect(self, name):
        y = RULER
        for t in TRACKS:
            if t == name:
                return y, HEIGHTS[t]
            y += HEIGHTS[t]
        return y, 0

    def track_at(self, y):
        yy = RULER
        for t in TRACKS:
            if yy <= y < yy + HEIGHTS[t]:
                return t
            yy += HEIGHTS[t]
        return None

    def clip_at(self, x, y):
        tr = self.track_at(y)
        if tr is None or x < HEAD:
            return None, None
        t = self.t_of(x)
        for c in reversed(self.project.track(tr)):
            if c["start"] <= t <= end_of(c):
                return tr, c
        return tr, None

    def refresh(self):
        """Draw the timeline again (after markers change, say)."""
        self.update_range()
        self.area.queue_draw()

    def update_range(self):
        w = self.area.get_allocated_width() - HEAD
        total = max(self.project.duration() + 10, 30) * self.pps
        self.adj.configure(min(self.adj.get_value(), max(0, total - w)), 0, total, 20, max(50, w * 0.8), max(1, w))

    def set_zoom(self, pps, anchor_t=None):
        pps = max(2.0, min(600.0, pps))
        anchor_t = self.win.playhead if anchor_t is None else anchor_t
        ax = self.x_of(anchor_t)
        self.pps = pps
        self.update_range()
        self.adj.set_value(max(0, anchor_t * pps - (ax - HEAD)))
        self.area.queue_draw()

    def zoom_fit(self):
        w = max(100, self.area.get_allocated_width() - HEAD - 20)
        self.pps = max(2.0, min(600.0, w / max(5.0, self.project.duration())))
        self.update_range()
        self.adj.set_value(0)
        self.area.queue_draw()

    def show_time(self, t):
        """Scroll so time t is in view (the playhead while playing). While a drag is going on the
        view belongs to the drag: jumping it here would yank the timeline out from under the
        pointer, and the playhead would leap away instead of following it (R5-01)."""
        if self.drag is not None:
            return
        x = t * self.pps
        v, w = self.adj.get_value(), self.adj.get_page_size()
        if x < v or x > v + w - 30:
            self.adj.set_value(max(0, x - w * 0.2))

    def centre_on(self, t):
        """Scroll so time t sits in the middle of the view: where the playhead should land after a
        jump to a time somewhere else in a long film (R5-01)."""
        w = self.adj.get_page_size()
        self.adj.set_value(max(0.0, min(max(0.0, self.adj.get_upper() - w), t * self.pps - w / 2)))
        self.area.queue_draw()

    def snap_tolerance(self):
        return SNAP_PX / self.pps

    # ------------------------------------------------------------ selection
    def select(self, ids):
        # a clip in a group brings the rest of its group with it (R4-06)
        self.selected = self.project.expand_groups(list(ids))
        self.area.queue_draw()
        self.win.selection_changed()

    def selected_clips(self):
        return [c for c in (self.project.clip(i) for i in self.selected) if c is not None]

    # ------------------------------------------------------------ drawing
    def _thumb(self, c):
        """A small picture of a video clip's first frame (made once, in the background)."""
        key = (c.get("media"), round(c.get("inpoint", 0), 1))
        if key in self.thumbs:
            return self.thumbs[key]
        self.thumbs[key] = None
        m = self.project.media_by_uri(c["media"])
        if m is None or not (m.get("has_video") or m.get("is_image")):
            return None

        def make():
            from . import engine
            try:
                pb = engine.thumbnail(m, None if m.get("is_image") else c.get("inpoint", 0) + 0.05, 96)
            except Exception:       # noqa: BLE001
                pb = None
            self.thumbs[key] = pb
            self.area.queue_draw()
            return False
        GLib.idle_add(make)
        return None

    def _wave(self, c):
        """The sound peaks of a clip's media (read once, in the background) — R4-01."""
        from . import engine
        m = self.project.media_by_uri(c.get("media"))
        if m is None or not m.get("has_audio"):
            return None
        w = engine.wave_cached(m["uri"])
        if w is not None:
            return w
        engine.waveform_async(m, lambda _peaks: self.area.queue_draw())
        return None

    def _draw_wave(self, cr, c, x0, x1, y, h):
        """The waveform across the clip, from the part of the media the clip shows."""
        from . import engine
        peaks = self._wave(c)
        if not peaks:
            return
        W = self.area.get_allocated_width()
        left, right = max(x0, HEAD), min(x1, W)
        if right - left < 2:
            return
        speed = c.get("speed", 1.0) or 1.0
        inp = c.get("inpoint", 0.0)
        mid = y + h / 2.0
        half = (h - 12) / 2.0
        cr.set_source_rgba(1, 1, 1, 0.45)
        step = 1.0 / self.pps * speed * engine.WAVE_RATE      # peaks a pixel
        for px in range(int(left), int(right)):
            a = (inp + (px - x0) / self.pps * speed) * engine.WAVE_RATE
            i0 = int(a)
            i1 = max(i0 + 1, int(a + step))
            if i0 >= len(peaks):
                break
            v = max(peaks[i0:i1] or [0.0])
            if v <= 0:
                continue
            cr.rectangle(px, mid - v * half, 1, max(1.0, v * half * 2))
        cr.fill()

    def _text(self, cr, x, y, text, size=8.5, bold=False, rgb=(1, 1, 1), width=None):
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string("Sans %s%s" % ("Bold " if bold else "", size))
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        if width:
            lay.set_width(int(width * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        cr.set_source_rgb(*rgb)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    def _draw(self, area, cr):
        from . import appearance
        dark = appearance.is_dark()
        W, H = area.get_allocated_width(), area.get_allocated_height()
        bg = (0.12, 0.12, 0.12) if dark else (0.90, 0.90, 0.90)
        lane = (0.17, 0.17, 0.17) if dark else (0.95, 0.95, 0.95)
        ink = (0.94, 0.94, 0.94) if dark else (0.15, 0.15, 0.15)
        line = (0.25, 0.25, 0.25) if dark else (0.80, 0.80, 0.80)
        cr.set_source_rgb(*bg)
        cr.paint()
        # ruler
        cr.set_source_rgb(*lane)
        cr.rectangle(0, 0, W, RULER)
        cr.fill()
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800) if s * self.pps >= 70)
        t0 = math.floor(self.t_of(HEAD) / step) * step
        t = t0
        cr.set_line_width(1)
        while self.x_of(t) < W:
            x = int(self.x_of(t)) + 0.5
            if x >= HEAD:
                cr.set_source_rgb(*line)
                cr.move_to(x, RULER - 8)
                cr.line_to(x, RULER)
                cr.stroke()
                self._text(cr, x + 3, 4, model.fmt_time(t), 8, rgb=ink)
            t += step
        # markers on the ruler (R4-05): a small flag with its name
        for m in self.project.markers():
            mx = self.x_of(m["t"])
            if mx < HEAD - 1 or mx > W:
                continue
            r, g, b = model.MARKER_RGB.get(m.get("color", "yellow"), model.MARKER_RGB["yellow"])
            cr.set_source_rgb(r, g, b)
            cr.move_to(mx, RULER - 1)
            cr.line_to(mx, RULER - MARKER_H)
            cr.line_to(mx + MARKER_W, RULER - MARKER_H)
            cr.line_to(mx + MARKER_W - 3, RULER - MARKER_H / 2 - 1)
            cr.line_to(mx + MARKER_W, RULER - 1)
            cr.close_path()
            cr.fill()
            if m.get("name"):
                self._text(cr, mx + MARKER_W + 3, RULER - MARKER_H, m["name"], 8.5,
                           rgb=ink, width=max(30, W - mx - MARKER_W - 6))
        # tracks
        y = RULER
        for name in TRACKS:
            h = HEIGHTS[name]
            cr.set_source_rgb(*lane)
            cr.rectangle(HEAD, y + 1, W - HEAD, h - 2)
            cr.fill()
            for c in self.project.track(name):
                self._draw_clip(cr, name, c, y, h, dark)
            y += h
        # drag ghost
        if self.ghost:
            gt, gs, gd = self.ghost
            gy, gh = self.track_rect(gt)
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.rectangle(self.x_of(gs), gy + 3, gd * self.pps, gh - 6)
            cr.fill_preserve()
            cr.set_source_rgb(1, 1, 1)
            cr.set_dash([4, 3])
            cr.stroke()
            cr.set_dash([])
        if self.snap_line is not None:
            cr.set_source_rgb(1.0, 0.85, 0.1)
            x = int(self.x_of(self.snap_line)) + 0.5
            cr.move_to(x, RULER)
            cr.line_to(x, H)
            cr.stroke()
        # track names
        y = RULER
        cr.set_source_rgb(*lane)
        cr.rectangle(0, 0, HEAD, H)
        cr.fill()
        for name in TRACKS:
            h = HEIGHTS[name]
            r, g, b = COLORS[name]
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, y + 1, 4, h - 2)
            cr.fill()
            self._text(cr, 10, y + h / 2 - 8, TRACK_NAMES[name], 9, True, rgb=ink)
            cr.set_source_rgb(*line)
            cr.move_to(0, y + h - 0.5)
            cr.line_to(W, y + h - 0.5)
            cr.stroke()
            y += h
        cr.move_to(HEAD - 0.5, 0)
        cr.line_to(HEAD - 0.5, H)
        cr.stroke()
        # a bracket over each group of clips, so it reads as one thing (R4-06)
        groups = {}
        for c in self.project.all_clips():
            if c.get("group"):
                groups.setdefault(c["group"], []).append(c)
        for members in groups.values():
            gx0 = self.x_of(min(m["start"] for m in members))
            gx1 = self.x_of(max(end_of(m) for m in members))
            if gx1 < HEAD or gx0 > W:
                continue
            gy = RULER + 2.5
            cr.set_source_rgba(0.55, 0.70, 0.95, 0.95)
            cr.set_line_width(2)
            cr.move_to(max(gx0, HEAD), gy + 4)
            cr.line_to(max(gx0, HEAD), gy)
            cr.line_to(min(gx1, W), gy)
            cr.line_to(min(gx1, W), gy + 4)
            cr.stroke()

        # a marker's line down the tracks, over the lanes but under the playhead (R4-05)
        cr.set_line_width(1)
        for m in self.project.markers():
            mx = self.x_of(m["t"])
            if mx < HEAD or mx > W:
                continue
            r, g, b = model.MARKER_RGB.get(m.get("color", "yellow"), model.MARKER_RGB["yellow"])
            cr.set_source_rgba(r, g, b, 0.45)
            cr.move_to(int(mx) + 0.5, RULER)
            cr.line_to(int(mx) + 0.5, H)
            cr.stroke()
        # playhead
        x = self.x_of(self.win.playhead)
        if x >= HEAD:
            cr.set_source_rgb(0.85, 0.12, 0.12)
            cr.set_line_width(2)
            cr.move_to(x, 0)
            cr.line_to(x, H)
            cr.stroke()
            # a grab tab at the top, wide enough to aim at (R5-01)
            cr.move_to(x - 7, 0)
            cr.line_to(x + 7, 0)
            cr.line_to(x + 7, 7)
            cr.line_to(x, 13)
            cr.line_to(x - 7, 7)
            cr.close_path()
            cr.fill()

    def _draw_clip(self, cr, track, c, y, h, dark):
        x0, x1 = self.x_of(c["start"]), self.x_of(end_of(c))
        W = self.area.get_allocated_width()
        if x1 < HEAD or x0 > W:
            return
        r, g, b = COLORS[track]
        missing = c["kind"] == "media" and self.project.media_by_uri(c["media"]) is None
        if missing:
            r, g, b = 0.6, 0.2, 0.2
        cr.save()
        cr.rectangle(HEAD, y, W - HEAD, h)
        cr.clip()
        cr.set_source_rgb(r, g, b)
        cr.rectangle(x0 + 0.5, y + 3, max(1, x1 - x0 - 1), h - 6)
        cr.fill()
        if track == "video" and h > 40:
            pb = self._thumb(c)
            if pb is not None and x1 - x0 > 30:
                th = h - 10
                tw = pb.get_width() * th / pb.get_height()
                cr.save()
                cr.rectangle(x0 + 2, y + 5, min(tw, x1 - x0 - 4), th)
                cr.clip()
                cr.translate(x0 + 2, y + 5)
                cr.scale(th / pb.get_height(), th / pb.get_height())
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
                cr.paint()
                cr.restore()
                tx = x0 + 6 + tw
            else:
                tx = x0 + 5
        else:
            tx = x0 + 5
        if c["kind"] == "media" and not missing and (track in ("audio", "music") or h > 40):
            self._draw_wave(cr, c, x0, x1, y + (h / 2 if track == "video" else 0), h / 2 if track == "video" else h)
        label = c["name"]
        if c.get("speed", 1.0) != 1.0:
            label += "  %g×" % c["speed"]
        if c.get("muted"):
            label += "  (muted)"
        if c.get("music_bed"):
            label += "  ♪ bed"
        self._text(cr, max(tx, HEAD + 3), y + 6, label, 8, True, width=max(10, x1 - max(tx, HEAD + 3) - 4))
        # fades
        cr.set_source_rgba(0, 0, 0, 0.35)
        if c.get("fade_in", 0) > 0:
            cr.move_to(x0, y + 3)
            cr.line_to(x0 + c["fade_in"] * self.pps, y + 3)
            cr.line_to(x0, y + h - 3)
            cr.close_path()
            cr.fill()
        if c.get("fade_out", 0) > 0:
            cr.move_to(x1, y + 3)
            cr.line_to(x1 - c["fade_out"] * self.pps, y + 3)
            cr.line_to(x1, y + h - 3)
            cr.close_path()
            cr.fill()
        # the volume line on sound clips
        if track in ("audio", "music") or (track == "video" and c.get("volume", 1.0) != 1.0):
            from . import engine
            pts = engine.gain_points(self.project, c)
            cr.set_source_rgba(1, 1, 0.6, 0.9)
            cr.set_line_width(1.2)
            top, bot = y + 5, y + h - 5
            for i, (t, v) in enumerate(pts):
                px = x0 + t * self.pps
                py = bot - (bot - top) * min(1.0, v)
                cr.line_to(px, py) if i else cr.move_to(px, py)
            cr.stroke()
        # transition into this clip
        tr = c.get("transition")
        if tr:
            tw = tr["duration"] * self.pps
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.rectangle(x0, y + 3, tw, h - 6)
            cr.fill()
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.set_line_width(1)
            cr.move_to(x0, y + 3)
            cr.line_to(x0 + tw, y + h - 3)
            cr.move_to(x0, y + h - 3)
            cr.line_to(x0 + tw, y + 3)
            cr.stroke()
        if c["id"] in self.selected:
            cr.set_source_rgb(1.0, 0.85, 0.1)
            cr.set_line_width(2.5)
            cr.rectangle(x0 + 1.5, y + 4, max(1, x1 - x0 - 3), h - 8)
            cr.stroke()
        cr.restore()

    # ------------------------------------------------------------ mouse
    def marker_at_x(self, x, y):
        """The marker whose flag is under a point on the ruler (R4-05)."""
        if y >= RULER or y < RULER - MARKER_H - 2:
            return None
        for m in self.project.markers():
            mx = self.x_of(m["t"])
            if mx - 3 <= x <= mx + MARKER_W + 2:
                return m
        return None

    def on_playhead(self, x, y):
        """True where a press lands on the playhead itself: the red bar is draggable all the way
        down the tracks, over clips as well as between them (R5-01)."""
        return y >= RULER and abs(x - self.x_of(self.win.playhead)) <= GRAB

    def _on_clip_edge(self, c, x):
        """True where x is close enough to one of clip c's ends to trim it."""
        if c is None:
            return False
        return abs(x - self.x_of(c["start"])) <= EDGE or abs(x - self.x_of(end_of(c))) <= EDGE

    def _press(self, area, ev):
        area.grab_focus()
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            if ev.type == Gdk.EventType._2BUTTON_PRESS:
                # a marker's flag: name it, pick its colour or delete it
                if self.marker_at_x(ev.x, ev.y) is not None:
                    self.win.run("marker-rename")
                    return True
                tr, c = self.clip_at(ev.x, ev.y)
                if c is not None:
                    self.win.run("clip-properties")
            return True
        if ev.y < RULER and ev.x >= HEAD:
            m = self.marker_at_x(ev.x, ev.y)
            if m is not None:
                self.win.pause()
                self.win.seek(m["t"])
                if m.get("name"):
                    self.win.notice(m["name"])
                if ev.button == 3:
                    self.win.run("marker-rename")
                return True
            self.drag = {"kind": "scrub"}
            self.win.seek(self.t_of(ev.x))
            return True
        tr, c = self.clip_at(ev.x, ev.y)
        if ev.button == 1 and self.on_playhead(ev.x, ev.y) and not self._on_clip_edge(c, ev.x):
            # the bar wins over the body of a clip, but a clip's own end wins over the bar: after a
            # split the two sit on top of each other, and trimming there must still be possible
            self.drag = {"kind": "scrub"}
            self.win.seek(self.t_of(ev.x))
            return True
        if ev.button == 3:
            if c is not None and c["id"] not in self.selected:
                self.select([c["id"]])
            self.win.context_menu(ev)
            return True
        if c is None:
            if not (ev.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)):
                self.select([])
            if ev.x >= HEAD:
                self.drag = {"kind": "scrub"}
                self.win.seek(self.t_of(ev.x))
            return True
        if ev.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):
            ids = list(self.selected)
            if c["id"] in ids:
                ids.remove(c["id"])
            else:
                ids.append(c["id"])
            self.select(ids)
            return True
        if c["id"] not in self.selected:
            self.select([c["id"]])
        x0, x1 = self.x_of(c["start"]), self.x_of(end_of(c))
        gid = self.project.group_of(c["id"])
        if ev.x - x0 <= EDGE:
            kind = "trim-start"
        elif x1 - ev.x <= EDGE:
            kind = "trim-end"
        else:
            kind = "move"
        if gid and kind != "move":
            # a group trims at its own ends only; an edge inside it moves the group instead
            members = self.project.group_members(gid)
            outer_start = min(m["start"] for m in members)
            outer_end = max(end_of(m) for m in members)
            if (kind == "trim-start" and abs(c["start"] - outer_start) > EPS) or \
               (kind == "trim-end" and abs(end_of(c) - outer_end) > EPS):
                kind = "move"
        self.drag = {"kind": kind, "id": c["id"], "track": tr, "x": ev.x, "y": ev.y,
                     "t0": self.t_of(ev.x), "start": c["start"], "dur": c["duration"], "moved": False}
        return True

    def _motion(self, area, ev):
        d = self.drag
        if d is None:
            tr, c = self.clip_at(ev.x, ev.y)
            cur = None
            if self.on_playhead(ev.x, ev.y) or (ev.y < RULER and ev.x >= HEAD):
                cur = "col-resize"
            elif c is not None:
                x0, x1 = self.x_of(c["start"]), self.x_of(end_of(c))
                if ev.x - x0 <= EDGE or x1 - ev.x <= EDGE:
                    cur = "col-resize"
            win = area.get_window()
            if win is not None:
                win.set_cursor(Gdk.Cursor.new_from_name(area.get_display(), cur) if cur else None)
            return False
        d["x_now"], d["y_now"] = ev.x, ev.y
        self._start_auto_scroll()
        return self._drag_to(ev.x, ev.y)

    # -------------------------------------------------- carrying the view along with a drag (R5-01)
    def _edge_step(self, x):
        """How far the view should travel this tick for a drag held at x: nothing in the middle,
        more the further past the edge of the view the pointer is."""
        w = self.area.get_allocated_width()
        if x > w - EDGE_SCROLL:
            f = min(1.0, (x - (w - EDGE_SCROLL)) / EDGE_SCROLL)
        elif x < HEAD + EDGE_SCROLL:
            f = -min(1.0, ((HEAD + EDGE_SCROLL) - x) / EDGE_SCROLL)
        else:
            return 0.0
        # gentle where the band begins, quick at the very edge: fine aim near the end of the view,
        # and a long film still passes by quickly when the pointer is pressed right up against it
        return f * abs(f)

    def _start_auto_scroll(self):
        if self._scroll_id is None and self.drag is not None and self._edge_step(self.drag.get("x_now", 0)) != 0.0:
            self.drag["scrolled_at"] = GLib.get_monotonic_time()
            self._scroll_id = GLib.timeout_add(20, self._auto_scroll)

    def auto_scroll_tick(self):
        """One tick of the view travelling under a held drag. True while there is further to go."""
        if self._scrolling:          # a tick already in hand: never stack them up
            return True
        d = self.drag
        if d is None:
            return False
        x = d.get("x_now")
        if x is None:
            return False
        fraction = self._edge_step(x)
        if fraction == 0.0:
            return False
        now = GLib.get_monotonic_time()
        elapsed = min(0.2, max(0.0, (now - d.get("scrolled_at", now)) / 1e6))
        d["scrolled_at"] = now
        step = fraction * SCROLL_RATE * elapsed
        if step == 0.0:
            return True
        v = self.adj.get_value()
        nv = max(0.0, min(max(0.0, self.adj.get_upper() - self.adj.get_page_size()), v + step))
        if abs(nv - v) < 1e-9:
            return False
        self._scrolling = True
        try:
            self.adj.set_value(nv)
            self._drag_to(x, d.get("y_now", RULER + 1))
        finally:
            self._scrolling = False
        return True

    def _stop_auto_scroll(self):
        if self._scroll_id is not None:
            try:
                GLib.source_remove(self._scroll_id)
            except (ValueError, TypeError):      # it finished of its own accord
                pass
            self._scroll_id = None

    def _auto_scroll(self):
        going = self.auto_scroll_tick()
        if not going:
            self._scroll_id = None
        return going

    def _drag_to(self, x, y):
        """Carry the drag to a point on the timeline. The pointer's own position does the work, so
        this is the same whether the pointer moved or the view did (R5-01)."""
        d = self.drag
        if d is None:
            return False
        if d["kind"] == "scrub":
            self.win.seek(self.t_of(x), accurate=False)
            return True
        if abs(x - d["x"]) < 3 and abs(y - d["y"]) < 3 and not d["moved"]:
            return True
        d["moved"] = True
        dt = self.t_of(x) - d["t0"]
        tol = self.snap_tolerance()
        p = self.project
        extra = [self.win.playhead]
        self.snap_line = None
        if d["kind"] == "move":
            track = self.track_at(y) or d["track"]
            start = max(0.0, d["start"] + dt)
            if p.snapping:
                s1 = p.snap(start, tol, exclude=(d["id"],), extra=extra)
                s2 = p.snap(start + d["dur"], tol, exclude=(d["id"],), extra=extra) - d["dur"]
                moved = [s for s in (s1, s2) if abs(s - start) > 1e-9]
                if moved:
                    start = min(moved, key=lambda s: abs(s - start))
                    self.snap_line = start if start == s1 else start + d["dur"]
            self.ghost = (track, start, d["dur"])
            d["to"] = (track, start)
        else:
            edge_t = (d["start"] + dt) if d["kind"] == "trim-start" else (d["start"] + d["dur"] + dt)
            if p.snapping:
                s = p.snap(edge_t, tol, exclude=(d["id"],), extra=extra)
                if s != edge_t:
                    self.snap_line = s
                edge_t = s
            if d["kind"] == "trim-start":
                self.ghost = (d["track"], min(edge_t, d["start"] + d["dur"] - 0.1),
                              max(0.1, d["start"] + d["dur"] - edge_t))
            else:
                self.ghost = (d["track"], d["start"], max(0.1, edge_t - d["start"]))
            d["to"] = edge_t
        self.area.queue_draw()
        return True

    def _release(self, area, ev):
        d, self.drag = self.drag, None
        self._stop_auto_scroll()
        if d is not None and d["kind"] == "scrub":
            self.win.seek(self.win.playhead)        # the exact frame, now the dragging has stopped
        self.ghost = None
        self.snap_line = None
        if d and d.get("moved") and "to" in d:
            try:
                if d["kind"] == "move":
                    track, start = d["to"]
                    gid = self.project.group_of(d["id"])
                    if gid:
                        self.project.move_group(gid, start - d["start"])
                    else:
                        self.project.move(d["id"], start, track=track)
                elif d["kind"] == "trim-start":
                    self.project.trim(d["id"], "start", d["to"])
                else:
                    self.project.trim(d["id"], "end", d["to"])
            except model.EditError as e:
                self.win.notice(str(e))
        self.area.queue_draw()
        return True

    def _scroll(self, area, ev):
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
            dx = {Gdk.ScrollDirection.LEFT: -1, Gdk.ScrollDirection.RIGHT: 1}.get(ev.direction, 0)
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            self.set_zoom(self.pps * (0.8 if dy > 0 else 1.25), self.t_of(ev.x))
        else:
            self.adj.set_value(max(0, min(self.adj.get_upper() - self.adj.get_page_size(),
                                          self.adj.get_value() + (dx + dy) * 60)))
        return True

    def _dropped(self, area, ctx, x, y, data, info, time):
        uris = data.get_uris() or []
        track = self.track_at(y)
        self.win.add_uris(uris, track=track, at=self.t_of(x) if x >= HEAD else None)
