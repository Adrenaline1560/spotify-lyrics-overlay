#!/usr/bin/env python3
"""Spotify lyrics overlay for macOS — prev / current / next lyric, album-tinted background."""

from __future__ import annotations

import bisect
import io
import json
import os
import re
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import urllib.request

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.expanduser("~/.spotify_lyrics_overlay.json")
DEFAULTS    = {"alpha": 0.75}

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    except Exception:
        return dict(DEFAULTS)

def save_config(data: dict) -> None:
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[config] save error: {e}")


# ─── Font ─────────────────────────────────────────────────────────────────────

def _pick_font(root: tk.Tk) -> str:
    available = set(tkfont.families(root))
    for name in ("SF Pro Rounded", "Nunito", "Varela Round", "Futura",
                 "Helvetica Neue", "Helvetica"):
        if name in available:
            return name
    return "Helvetica"


# ─── AppleScript ──────────────────────────────────────────────────────────────

_QUERY = """
tell application "Spotify"
    if player state is stopped then return "stopped"
    set t to current track
    try
        set tArt to artwork url of t
    on error
        set tArt to ""
    end try
    return (name of t) & "|" & (artist of t) & "|" & (duration of t) & "|" & (player position) & "|" & (player state as string) & "|" & tArt
end tell
"""

def get_spotify_state() -> dict | None:
    try:
        r = subprocess.run(["osascript", "-e", _QUERY],
                           capture_output=True, text=True, timeout=4)
        out = r.stdout.strip()
        if r.returncode != 0 or not out or out == "stopped":
            return None
        p = out.split("|")
        if len(p) < 5:
            return None
        return {
            "name":        p[0], "artist":   p[1],
            "duration":    int(float(p[2])) // 1000,
            "position":    float(p[3]),   "state":   p[4],
            "artwork_url": p[5].strip() if len(p) > 5 else "",
        }
    except Exception:
        return None



# ─── Album colour ─────────────────────────────────────────────────────────────

DEFAULT_BG  = "#111116"
DEFAULT_DIM = "#44445a"

def fetch_album_colors(url: str) -> tuple[str, str]:
    if not url or not HAS_PIL:
        return DEFAULT_BG, DEFAULT_DIM
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SpotifyLyricsOverlay/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB").resize((60, 60))
        px  = list(img.getdata())
        r = sum(p[0] for p in px) // len(px)
        g = sum(p[1] for p in px) // len(px)
        b = sum(p[2] for p in px) // len(px)

        bg  = (max(12, int(r * 0.20)), max(12, int(g * 0.20)), max(12, int(b * 0.20)))
        dim = (min(170, int(r * 0.50 + 45)), min(170, int(g * 0.50 + 45)), min(170, int(b * 0.50 + 45)))
        return f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}", f"#{dim[0]:02x}{dim[1]:02x}{dim[2]:02x}"
    except Exception as e:

        return DEFAULT_BG, DEFAULT_DIM


# ─── Lyrics ───────────────────────────────────────────────────────────────────

_LRC = re.compile(r"\[(\d{1,2}):(\d{2}\.\d{2,3})\]([^\[]*)")

def parse_lrc(text: str) -> list[tuple[float, str]]:
    out = []
    for line in text.splitlines():
        for m in _LRC.finditer(line):
            out.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return sorted(out, key=lambda x: x[0])

def _req(url):
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "SpotifyLyricsOverlay/1.0"})
        with urllib.request.urlopen(r, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def _extract(data, dur):
    if data.get("syncedLyrics"):
        return parse_lrc(data["syncedLyrics"])
    if data.get("plainLyrics"):
        lines = [l for l in data["plainLyrics"].splitlines() if l.strip()]
        step  = max(1, dur / len(lines)) if lines else 1
        return [(i * step, l) for i, l in enumerate(lines)]
    return []

def fetch_lyrics(artist, track, duration):
    if not artist or not track:
        return []
    p = urllib.parse.urlencode({"artist_name": artist, "track_name": track, "duration": duration})
    d = _req(f"https://lrclib.net/api/get?{p}")
    if isinstance(d, dict):
        r = _extract(d, duration)
        if r: return r
    p = urllib.parse.urlencode({"artist_name": artist, "track_name": track})
    rs = _req(f"https://lrclib.net/api/search?{p}")
    if isinstance(rs, list):
        for item in rs:
            r = _extract(item, duration)
            if r: return r
    return []

def find_line(lyrics, pos):
    if not lyrics: return -1
    return max(bisect.bisect_right([t for t, _ in lyrics], pos) - 1, -1)


# ─── Custom slider widget ────────────────────────────────────────────────────

class Slider(tk.Canvas):
    """Thin Spotify-style horizontal slider: dark track, green fill, white thumb."""

    TRACK_H = 3
    THUMB_R = 7
    PAD     = 10

    def __init__(self, parent, from_=0.0, to=1.0, value=0.75, command=None, bg="#18181f"):
        super().__init__(parent, bg=bg, height=28,
                         highlightthickness=0, bd=0)
        self._from = from_
        self._to   = to
        self._val  = float(value)
        self._cmd  = command
        self._bg   = bg
        self.bind("<Configure>", lambda _: self._draw())
        self.bind("<Button-1>",  self._on_click)
        self.bind("<B1-Motion>", self._on_click)

    def _ratio(self):
        return (self._val - self._from) / (self._to - self._from)

    def _x_from_ratio(self, r):
        w = self.winfo_width()
        return self.PAD + r * (w - 2 * self.PAD)

    def _ratio_from_x(self, x):
        w = self.winfo_width()
        return max(0.0, min(1.0, (x - self.PAD) / (w - 2 * self.PAD)))

    def _draw(self):
        self.delete("all")
        w  = self.winfo_width()
        cy = self.winfo_height() // 2
        x  = self._x_from_ratio(self._ratio())
        # track background
        self.create_rectangle(self.PAD, cy - self.TRACK_H // 2,
                               w - self.PAD, cy + self.TRACK_H // 2,
                               fill="#2e2e3e", outline="")
        # filled portion
        self.create_rectangle(self.PAD, cy - self.TRACK_H // 2,
                               x, cy + self.TRACK_H // 2,
                               fill="#1db954", outline="")
        # thumb
        r = self.THUMB_R
        self.create_oval(x - r, cy - r, x + r, cy + r,
                         fill="#ffffff", outline="")

    def _on_click(self, e):
        self._val = self._from + self._ratio_from_x(e.x) * (self._to - self._from)
        self._draw()
        if self._cmd:
            self._cmd(self._val)

    def get(self) -> float:
        return self._val

    def set(self, val: float):
        self._val = max(self._from, min(self._to, float(val)))
        self._draw()


# ─── UI ───────────────────────────────────────────────────────────────────────

class LyricsOverlayApp:
    W            = 380
    POLL_MS      = 1000
    HIGHLIGHT_MS = 200

    def __init__(self) -> None:
        self.root = tk.Tk()
        self._F   = _pick_font(self.root)


        self._config  = load_config()
        self._running = True
        self._track   = None
        self._lyrics  = []
        self._status  = ""
        self._idx     = -2
        self._state   = None
        self._baseline= (0.0, time.monotonic())
        self._dx = self._dy = 0
        self._bg  = DEFAULT_BG
        self._dim = DEFAULT_DIM
        self._last_progress = (0.0, 1.0)
        self._settings_win  = None
        self._anim_id       = None

        self._setup_window()
        self._build_widgets()
        self._bind_drag()
        self._bar_canvas.bind("<Configure>", lambda e: self._draw_bar())
        threading.Thread(target=self._poll, daemon=True).start()
        self.root.after(200, self.root.lift)
        self.root.after(self.HIGHLIGHT_MS, self._tick)

    # ── Window ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.root.title("Spotify Lyrics Miniplayer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self._config["alpha"])
        self.root.configure(bg=self._bg)
        self.root.minsize(self.W, 250)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x230+{sw - self.W - 20}+{sh - 280}")

    # ── Widgets ───────────────────────────────────────────────────────────────

    def _build_widgets(self):
        F  = self._F
        W  = self.W
        WL = W - 32

        # ── progress bar — pack FIRST with side=bottom so it's always visible ──
        pf = tk.Frame(self.root, bg=self._bg)
        pf.pack(side="bottom", fill="x", padx=14, pady=(0, 10))

        self.pos_lbl = tk.Label(pf, text="0:00", bg=self._bg, fg=self._dim,
                                 font=(F, 10), width=4, anchor="w")
        self.pos_lbl.pack(side="left")

        # dur_lbl must be packed BEFORE the expanding canvas or it gets squeezed out
        self.dur_lbl = tk.Label(pf, text="0:00", bg=self._bg, fg=self._dim,
                                 font=(F, 10), width=4, anchor="e")
        self.dur_lbl.pack(side="right")

        self._bar_canvas = tk.Canvas(pf, bg=self._bg, height=3,
                                      highlightthickness=0, bd=0)
        self._bar_canvas.pack(side="left", fill="x", expand=True, padx=6)

        # ── header: title + artist + gear icon ───────────────────────────
        top = tk.Frame(self.root, bg=self._bg)
        top.pack(side="top", fill="x", padx=14, pady=(12, 0))

        info = tk.Frame(top, bg=self._bg)
        info.pack(side="left", fill="both", expand=True)

        self.title_lbl = tk.Label(info, text="Connecting…", bg=self._bg, fg="#ffffff",
                                   font=(F, 13, "bold"), anchor="w",
                                   wraplength=WL - 26, justify="left")
        self.title_lbl.pack(anchor="w")

        self.artist_lbl = tk.Label(info, text="", bg=self._bg, fg=self._dim,
                                    font=(F, 10), anchor="w")
        self.artist_lbl.pack(anchor="w", pady=(1, 0))

        self._gear_lbl = tk.Label(top, text="⚙", bg=self._bg, fg="#555566",
                                   font=(F, 14), cursor="hand2")
        self._gear_lbl.pack(side="right", anchor="n", pady=(2, 0))
        self._gear_lbl.bind("<Button-1>", self._show_settings)

        # ── lyrics canvas — fills remaining space, scales with window ───
        self._lyrics_canvas = tk.Canvas(
            self.root, bg=self._bg,
            highlightthickness=0, bd=0,
        )
        self._lyrics_canvas.pack(side="top", fill="both", expand=True,
                                  padx=18, pady=(14, 8))
        self._lyrics_canvas.bind("<Button-1>", self._ds)
        self._lyrics_canvas.bind("<B1-Motion>", self._dm)
        self._lyrics_canvas.bind("<Configure>", lambda e: self._rerender())
        self._curr_item = None

        # collect all bg-holding widgets for _apply_colors
        self._bg_widgets = [
            self.root, top, info, pf,
            self.title_lbl, self.artist_lbl,
            self.pos_lbl, self.dur_lbl,
        ]

    # ── Colour update ─────────────────────────────────────────────────────────

    def _apply_colors(self, bg: str, dim: str):
        self._bg, self._dim = bg, dim
        for w in self._bg_widgets:
            try: w.configure(bg=bg)
            except Exception: pass
        self.title_lbl.configure(fg="#ffffff")
        self.artist_lbl.configure(fg=dim)
        self.pos_lbl.configure(fg=dim)
        self.dur_lbl.configure(fg=dim)
        self._gear_lbl.configure(bg=bg)
        self._bar_canvas.configure(bg=bg)
        self._lyrics_canvas.configure(bg=bg)
        self._draw_bar(0, 1)
        self._rerender()

    # ── Drag ─────────────────────────────────────────────────────────────────

    def _bind_drag(self):
        for w in self._bg_widgets + [self._bar_canvas, self._gear_lbl,
                                      self._lyrics_canvas]:
            w.bind("<Button-1>", self._ds)
            w.bind("<B1-Motion>", self._dm)
        self._gear_lbl.bind("<Button-1>", self._show_settings)

    def _ds(self, e): self._dx, self._dy = e.x, e.y
    def _dm(self, e):
        self.root.geometry(f"+{self.root.winfo_x()+e.x-self._dx}+{self.root.winfo_y()+e.y-self._dy}")

    def _show_settings(self, _=None):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return

        F   = self._F
        BG  = "#18181f"
        SEP = "#2e2e40"
        DIM = "#7777aa"

        # Native Toplevel — avoids macOS compositor transparency bug
        # that affects overrideredirect windows sharing a parent.
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.resizable(False, False)
        win.configure(bg=BG)
        win.attributes("-topmost", True)

        # Centre over the overlay
        W_SET, H_SET = 300, 195
        rx = self.root.winfo_x() + (self.W - W_SET) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - H_SET) // 2
        win.geometry(f"{W_SET}x{H_SET}+{rx}+{ry}")

        # Do NOT use transient() with an overrideredirect parent — it breaks z-order on macOS.
        win.grab_set()
        win.lift()
        win.focus_force()
        self._settings_win = win

        prev_alpha = float(self.root.attributes("-alpha"))

        # ── transparency label + live readout ─────────────────────────
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=20, pady=(20, 0))

        tk.Label(row, text="Transparency", bg=BG, fg=DIM,
                 font=(F, 11)).pack(side="left", anchor="w")

        pct_lbl = tk.Label(row, bg=BG, fg="#ffffff",
                            font=(F, 11, "bold"), width=5, anchor="e")
        pct_lbl.pack(side="right")

        def update_pct(v):
            pct_lbl.config(text=f"{int(float(v) * 100)}%")

        update_pct(prev_alpha)

        # ── custom slider ─────────────────────────────────────────────
        slider = Slider(win, from_=0.20, to=1.0, value=prev_alpha,
                        command=update_pct, bg=BG)
        slider.pack(fill="x", padx=20, pady=(10, 0))

        # ── hint ──────────────────────────────────────────────────────
        tk.Label(win, text="Lower = more see-through", bg=BG, fg="#444466",
                 font=(F, 9)).pack(anchor="w", padx=20, pady=(4, 0))

        # ── divider ───────────────────────────────────────────────────
        tk.Frame(win, bg=SEP, height=1).pack(fill="x", padx=20, pady=(16, 0))

        # ── buttons ───────────────────────────────────────────────────
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=20, pady=(12, 18))

        def confirm():
            new_alpha = round(slider.get(), 2)
            self.root.attributes("-alpha", new_alpha)
            self._config["alpha"] = new_alpha
            save_config(self._config)
            win.destroy()

        def cancel():
            win.destroy()

        bkw = dict(relief="flat", cursor="hand2",
                   bd=0, highlightthickness=0,
                   font=(F, 11), padx=20, pady=8)

        tk.Button(btns, text="Confirm", command=confirm,
                  bg="#1f3329", fg="#1db954",
                  activebackground="#243d2f",
                  activeforeground="#1db954", **bkw).pack(side="right")

        tk.Button(btns, text="Cancel", command=cancel,
                  bg=SEP, fg="#7777aa",
                  activebackground="#383852",
                  activeforeground="#aaaacc", **bkw).pack(side="right", padx=(0, 8))

    def _on_close(self, _=None):
        self._running = False
        self.root.destroy()

    # ── UI updates ────────────────────────────────────────────────────────────

    def _draw_bar(self, pos: float = None, dur: float = None):
        if pos is not None:
            self._last_progress = (pos, dur)
        else:
            pos, dur = self._last_progress
        c = self._bar_canvas
        w = c.winfo_width()
        if w < 2 or dur <= 0:
            return
        c.delete("all")
        filled = max(0, min(1, pos / dur)) * w
        c.create_rectangle(0, 0, filled, 3, fill="#ffffff", outline="")
        c.create_rectangle(filled, 0, w, 3, fill=self._dim, outline="")

    def _update_track(self, state: dict | None):
        if state is None:
            self.title_lbl.config(text="Open Spotify to get started")
            self.artist_lbl.config(text="")
            self.pos_lbl.config(text="0:00")
            self.dur_lbl.config(text="0:00")
            self._lyrics = []
            self._status = ""
            self._rerender()
        else:
            self.title_lbl.config(text=state["name"])
            self.artist_lbl.config(text=state["artist"])
            self.dur_lbl.config(text=self._fmt(state["duration"]))

    def _update_lyrics(self, lyrics: list, msg: str | None):
        self._lyrics = lyrics
        self._status = msg or ""
        self._idx    = -2
        self._rerender()

    def _rerender(self):
        """Re-draw the lyrics canvas at the current idx without animation."""
        if not self._running:
            return
        try:
            self._render_lyrics(self._idx)
        except tk.TclError:
            pass

    def _render_lyrics(self, idx: int):
        """Draw as many lyric lines as fit, centred on idx."""
        c   = self._lyrics_canvas
        L   = self._lyrics
        F   = self._F
        w   = c.winfo_width()
        h   = c.winfo_height()
        c.delete("all")
        self._curr_item = None

        if w < 10 or h < 10:
            return

        cx = w // 2

        if not L:
            msg = self._status
            if msg:
                self._curr_item = c.create_text(
                    cx, h // 2, text=msg, fill=self._dim,
                    font=(F, 12), anchor="center",
                    width=w - 24, justify="center")
            return

        curr_text = L[idx][1] if 0 <= idx < len(L) else ""

        # --- measure current line height ---
        probe = c.create_text(cx, 0, text=curr_text or "M",
                               font=(F, 18, "bold"), anchor="n",
                               width=w - 24, justify="center")
        bb = c.bbox(probe)
        curr_h = (bb[3] - bb[1] + 4) if bb else 28
        c.delete(probe)

        GAP = 8   # px between lines

        # how many lines fit above / below the current line
        available = (h - curr_h) // 2
        n = 0
        used = 0
        while True:
            step = 24 if n < 1 else 20
            if used + step + GAP > available:
                break
            used += step + GAP
            n += 1
        n = max(1, n)

        # draw current line centred
        cy = h // 2
        self._curr_item = c.create_text(
            cx, cy, text=curr_text, fill="#ffffff",
            font=(F, 18, "bold"), anchor="center",
            width=w - 24, justify="center")

        # draw lines above
        y_top = cy - curr_h // 2 - GAP
        for k in range(1, n + 1):
            i = idx - k
            if i < 0:
                break
            size = 12 if k == 1 else 11
            item = c.create_text(cx, 0, text=L[i][1],
                                  font=(F, size), anchor="n",
                                  width=w - 24, justify="center")
            bb2 = c.bbox(item)
            ih = (bb2[3] - bb2[1]) if bb2 else size * 2
            y_top -= ih
            if y_top + ih < 0:
                c.delete(item)
                break
            c.coords(item, cx, y_top)
            c.itemconfig(item, anchor="n", fill=self._dim)
            y_top -= GAP

        # draw lines below
        y_bot = cy + curr_h // 2 + GAP
        for k in range(1, n + 1):
            i = idx + k
            if i >= len(L):
                break
            size = 12 if k == 1 else 11
            item = c.create_text(cx, y_bot, text=L[i][1],
                                  font=(F, size), anchor="n",
                                  width=w - 24, justify="center")
            bb2 = c.bbox(item)
            ih = (bb2[3] - bb2[1]) if bb2 else size * 2
            if y_bot > h:
                c.delete(item)
                break
            c.itemconfig(item, fill=self._dim)
            y_bot += ih + GAP

    # ── Crossfade transition ──────────────────────────────────────────────────

    @staticmethod
    def _lerp_hex(c1: str, c2: str, t: float) -> str:
        r1,g1,b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
        r2,g2,b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
        return "#{:02x}{:02x}{:02x}".format(
            int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t))

    def _fade_to(self, new_idx: int):
        """Crossfade current line out → redraw → fade in, ~180ms total."""
        if self._anim_id:
            self.root.after_cancel(self._anim_id)
            self._anim_id = None

        STEPS = 6
        MS    = 30

        def step(i):
            if not self._running:
                return
            try:
                c    = self._lyrics_canvas
                half = STEPS // 2
                if i < half:
                    t = i / half
                    col = self._lerp_hex("#ffffff", self._dim, t)
                    if self._curr_item:
                        c.itemconfig(self._curr_item, fill=col)
                elif i == half:
                    self._render_lyrics(new_idx)
                    if self._curr_item:
                        c.itemconfig(self._curr_item, fill=self._dim)
                else:
                    t = (i - half) / half
                    col = self._lerp_hex(self._dim, "#ffffff", t)
                    if self._curr_item:
                        c.itemconfig(self._curr_item, fill=col)

                if i < STEPS:
                    self._anim_id = self.root.after(MS, lambda: step(i + 1))
                else:
                    if self._curr_item:
                        c.itemconfig(self._curr_item, fill="#ffffff")
                    self._anim_id = None
            except tk.TclError:
                pass

        self._anim_id = self.root.after(0, lambda: step(0))

    # ── Highlight tick ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(secs: float) -> str:
        s = int(secs)
        return f"{s // 60}:{s % 60:02d}"

    def _tick(self):
        if not self._running: return
        try:
            if self._state:
                pos, mono = self._baseline
                playing = self._state.get("state") == "playing"
                estimated = pos + (time.monotonic() - mono) if playing else pos
                dur = self._state.get("duration", 0)
                self.pos_lbl.config(text=self._fmt(estimated))
                self._draw_bar(estimated, dur)
                if self._lyrics:
                    idx = find_line(self._lyrics, estimated)
                    if idx != self._idx:
                        self._idx = idx
                        self._fade_to(idx)
            self.root.after(self.HIGHLIGHT_MS, self._tick)
        except tk.TclError:
            pass

    # ── Poll thread ───────────────────────────────────────────────────────────

    def _poll(self):
        while self._running:
            try:
                state = get_spotify_state()
                self._go(self._update_track, state)
                if state:
                    self._go(self._set_baseline, state["position"], time.monotonic())
                    self._state = state
                    key = (state["name"], state["artist"])
                    if key != self._track:
                        self._track = key
                        self._go(self._update_lyrics, [], "Fetching lyrics…")
    
                        bg, dim = fetch_album_colors(state.get("artwork_url", ""))
                        self._go(self._apply_colors, bg, dim)
                        lyr = fetch_lyrics(state["artist"], state["name"], state["duration"])
    
                        self._go(self._update_lyrics, lyr, None if lyr else "No lyrics found")
                else:
                    self._state = None
                    self._track = None
            except Exception:
                pass
            time.sleep(self.POLL_MS / 1000)

    def _set_baseline(self, pos, mono): self._baseline = (pos, mono)

    def _go(self, fn, *args):
        try: self.root.after(0, lambda: fn(*args))
        except tk.TclError: pass

    def run(self): self.root.mainloop()


def main():
    try:
        LyricsOverlayApp().run()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
