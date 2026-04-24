#!/usr/bin/env python3
"""Spotify lyrics overlay for macOS — no OAuth required."""

import bisect
import json
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request

# ─── AppleScript bridge ───────────────────────────────────────────────────────

_SPOTIFY_QUERY = """
tell application "Spotify"
    if player state is stopped then return "stopped"
    set t to current track
    set tName to name of t
    set tArtist to artist of t
    set tAlbum to album of t
    set tDur to duration of t
    set tPos to player position
    set tState to player state as string
    return tName & "|" & tArtist & "|" & tAlbum & "|" & tDur & "|" & tPos & "|" & tState
end tell
"""


def get_spotify_state() -> dict | None:
    try:
        r = subprocess.run(
            ["osascript", "-e", _SPOTIFY_QUERY],
            capture_output=True, text=True, timeout=4,
        )
        out = r.stdout.strip()
        if r.returncode != 0 or not out or out == "stopped":
            return None
        parts = out.split("|")
        if len(parts) < 6:
            return None
        return {
            "name": parts[0],
            "artist": parts[1],
            "album": parts[2],
            "duration": int(float(parts[3])) // 1000,  # ms → seconds
            "position": float(parts[4]),
            "state": parts[5],  # "playing" | "paused"
        }
    except Exception:
        return None


def _run_spotify_cmd(cmd: str) -> None:
    subprocess.run(["osascript", "-e", f'tell application "Spotify" to {cmd}'],
                   capture_output=True, timeout=3)


def spotify_previous() -> None:
    _run_spotify_cmd("previous track")


def spotify_playpause() -> None:
    _run_spotify_cmd("playpause")


def spotify_next() -> None:
    _run_spotify_cmd("next track")


# ─── Lyrics fetcher ───────────────────────────────────────────────────────────

_LRC_RE = re.compile(r"\[(\d{1,2}):(\d{2}\.\d{2,3})\]([^\[]*)")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    results = []
    for line in text.splitlines():
        for m in _LRC_RE.finditer(line):
            ts = int(m.group(1)) * 60 + float(m.group(2))
            results.append((ts, m.group(3).strip()))
    results.sort(key=lambda x: x[0])
    return results


def fetch_lyrics(artist: str, track: str, duration: int) -> list[tuple[float, str]]:
    if not artist or not track:
        return []
    params = urllib.parse.urlencode({
        "artist_name": artist,
        "track_name": track,
        "duration": duration,
    })
    url = f"https://lrclib.net/api/get?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SpotifyLyricsOverlay/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        if data.get("syncedLyrics"):
            return parse_lrc(data["syncedLyrics"])
        if data.get("plainLyrics"):
            lines = [l for l in data["plainLyrics"].splitlines() if l.strip()]
            if not lines:
                return []
            step = max(1, duration / len(lines))
            return [(i * step, line) for i, line in enumerate(lines)]
    except Exception:
        pass
    return []


# ─── Sync engine ─────────────────────────────────────────────────────────────

def find_current_line(lyrics: list[tuple[float, str]], position: float) -> int:
    if not lyrics:
        return -1
    timestamps = [ts for ts, _ in lyrics]
    idx = bisect.bisect_right(timestamps, position) - 1
    return max(idx, -1)


# ─── UI ───────────────────────────────────────────────────────────────────────

class LyricsOverlayApp:
    WIDTH = 340
    HEIGHT = 430
    BG = "#1a1a2e"
    FG_TITLE = "#ffffff"
    FG_ARTIST = "#b3b3b3"
    FG_CURRENT = "#1db954"
    FG_NORMAL = "#555577"
    BTN_BG = "#1db954"
    BTN_FG = "#ffffff"
    BTN_ACTIVE = "#1ed760"
    POLL_MS = 1000
    HIGHLIGHT_MS = 250

    def __init__(self) -> None:
        self.root = tk.Tk()
        self._running = True
        self._current_track: tuple[str, str] | None = None
        self._lyrics: list[tuple[float, str]] = []
        self._lyrics_message: str = "Open Spotify to get started"
        self._current_line_idx = -2  # force initial draw
        self._last_state: dict | None = None
        self._pos_baseline: tuple[float, float] = (0.0, time.monotonic())
        self._drag_x = 0
        self._drag_y = 0

        self._setup_window()
        self._build_widgets()
        self._bind_drag()
        self._start_polling_thread()
        self.root.after(200, self.root.lift)
        self.root.after(self.HIGHLIGHT_MS, self._highlight_tick)

    def _setup_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.configure(bg=self.BG)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - self.WIDTH - 20
        y = sh - self.HEIGHT - 60
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _build_widgets(self) -> None:
        # Top bar (close button + title)
        top = tk.Frame(self.root, bg=self.BG)
        top.pack(fill="x", padx=8, pady=(6, 0))

        close_btn = tk.Button(
            top, text="✕", command=self._on_close,
            bg=self.BG, fg="#555577", relief="flat",
            font=("Helvetica", 11), cursor="hand2",
            activebackground=self.BG, activeforeground="#ffffff",
            bd=0, padx=4,
        )
        close_btn.pack(side="right")

        self.title_lbl = tk.Label(
            top, text="Connecting...", bg=self.BG, fg=self.FG_TITLE,
            font=("Helvetica", 13, "bold"), anchor="w",
            wraplength=self.WIDTH - 50, justify="left",
        )
        self.title_lbl.pack(side="left", fill="x", expand=True)

        self.artist_lbl = tk.Label(
            self.root, text="", bg=self.BG, fg=self.FG_ARTIST,
            font=("Helvetica", 11), anchor="w",
        )
        self.artist_lbl.pack(fill="x", padx=12, pady=(0, 4))

        # Controls
        ctrl = tk.Frame(self.root, bg=self.BG)
        ctrl.pack(pady=(0, 6))

        btn_cfg = dict(
            bg=self.BTN_BG, fg=self.BTN_FG, relief="flat",
            font=("Helvetica", 16), width=3, cursor="hand2",
            activebackground=self.BTN_ACTIVE, activeforeground=self.BTN_FG,
            bd=0,
        )
        tk.Button(ctrl, text="⏮", command=self._on_prev, **btn_cfg).pack(side="left", padx=3)
        self.playpause_btn = tk.Button(ctrl, text="⏸", command=self._on_playpause, **btn_cfg)
        self.playpause_btn.pack(side="left", padx=3)
        tk.Button(ctrl, text="⏭", command=self._on_next, **btn_cfg).pack(side="left", padx=3)

        # Lyrics area
        lyrics_frame = tk.Frame(self.root, bg=self.BG)
        lyrics_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scrollbar = tk.Scrollbar(lyrics_frame, bg=self.BG, troughcolor=self.BG,
                                  relief="flat", width=4)
        scrollbar.pack(side="right", fill="y")

        self.lyrics_text = tk.Text(
            lyrics_frame,
            bg=self.BG, fg=self.FG_NORMAL,
            font=("Helvetica", 12),
            relief="flat", wrap="word",
            state="disabled",
            selectbackground=self.BG,
            cursor="arrow",
            spacing1=3, spacing3=3,
            yscrollcommand=scrollbar.set,
        )
        self.lyrics_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.lyrics_text.yview)

        self.lyrics_text.tag_configure("current", foreground=self.FG_CURRENT,
                                        font=("Helvetica", 13, "bold"))
        self.lyrics_text.tag_configure("normal", foreground=self.FG_NORMAL,
                                        font=("Helvetica", 12))
        self.lyrics_text.tag_configure("message", foreground="#555577",
                                        font=("Helvetica", 12), justify="center")

        # bind drag targets
        self._drag_targets = [top, self.title_lbl, self.artist_lbl, self.root]

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _bind_drag(self) -> None:
        for widget in self._drag_targets:
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_motion)
        # Lyrics text: override to enable drag without selecting text
        self.lyrics_text.bind("<Button-1>", self._text_drag_start)
        self.lyrics_text.bind("<B1-Motion>", self._text_drag_motion)

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag_motion(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _text_drag_start(self, event: tk.Event) -> str:
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()
        return "break"

    def _text_drag_motion(self, event: tk.Event) -> str:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")
        return "break"

    # ── Control callbacks ─────────────────────────────────────────────────────

    def _on_prev(self) -> None:
        threading.Thread(target=spotify_previous, daemon=True).start()

    def _on_playpause(self) -> None:
        threading.Thread(target=spotify_playpause, daemon=True).start()

    def _on_next(self) -> None:
        threading.Thread(target=spotify_next, daemon=True).start()

    def _on_close(self) -> None:
        self._running = False
        self.root.destroy()

    # ── UI updates (main thread only) ────────────────────────────────────────

    def _update_track_ui(self, state: dict | None) -> None:
        if state is None:
            self.title_lbl.config(text="Open Spotify to get started")
            self.artist_lbl.config(text="")
            self.playpause_btn.config(text="▶")
        else:
            self.title_lbl.config(text=state["name"])
            self.artist_lbl.config(text=state["artist"])
            icon = "⏸" if state["state"] == "playing" else "▶"
            self.playpause_btn.config(text=icon)

    def _update_lyrics_ui(self, lyrics: list[tuple[float, str]], message: str | None) -> None:
        self._lyrics = lyrics
        self._lyrics_message = message or ""
        self._current_line_idx = -2  # force redraw
        self._redraw_lyrics(-1)

    def _redraw_lyrics(self, active_idx: int) -> None:
        tw = self.lyrics_text
        tw.config(state="normal")
        tw.delete("1.0", "end")

        if self._lyrics_message and not self._lyrics:
            tw.insert("end", f"\n\n{self._lyrics_message}", "message")
        else:
            for i, (_, line) in enumerate(self._lyrics):
                tag = "current" if i == active_idx else "normal"
                tw.insert("end", (line or "") + "\n", tag)
        tw.config(state="disabled")

    # ── Highlight timer (main thread) ────────────────────────────────────────

    def _highlight_tick(self) -> None:
        if not self._running:
            return
        try:
            if self._lyrics and self._last_state and self._last_state["state"] == "playing":
                stored_pos, mono = self._pos_baseline
                estimated = stored_pos + (time.monotonic() - mono)
                idx = find_current_line(self._lyrics, estimated)
                if idx != self._current_line_idx:
                    self._current_line_idx = idx
                    self._redraw_lyrics(idx)
                    # scroll so current line is ~1/3 from top
                    if idx >= 0:
                        look_ahead = min(idx + 5, len(self._lyrics))
                        try:
                            self.lyrics_text.see(f"{look_ahead}.0")
                            self.lyrics_text.see(f"{max(1, idx - 1)}.0")
                        except tk.TclError:
                            pass
            self.root.after(self.HIGHLIGHT_MS, self._highlight_tick)
        except tk.TclError:
            pass

    # ── Polling thread ────────────────────────────────────────────────────────

    def _start_polling_thread(self) -> None:
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def _poll_loop(self) -> None:
        while self._running:
            try:
                state = get_spotify_state()
                self._schedule(self._update_track_ui, state)

                if state:
                    # update position baseline on main thread
                    pos, mono = state["position"], time.monotonic()
                    self._schedule(self._set_baseline, pos, mono)
                    self._last_state = state

                    track_key = (state["name"], state["artist"])
                    if track_key != self._current_track:
                        self._current_track = track_key
                        self._schedule(self._update_lyrics_ui, [], "Fetching lyrics...")
                        lyrics = fetch_lyrics(state["artist"], state["name"], state["duration"])
                        msg = None if lyrics else "No lyrics found for this track"
                        self._schedule(self._update_lyrics_ui, lyrics, msg)
                else:
                    self._last_state = None
                    self._current_track = None
            except Exception:
                pass
            time.sleep(self.POLL_MS / 1000)

    def _set_baseline(self, pos: float, mono: float) -> None:
        self._pos_baseline = (pos, mono)

    def _schedule(self, fn, *args) -> None:
        try:
            self.root.after(0, lambda: fn(*args))
        except tk.TclError:
            pass

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    try:
        LyricsOverlayApp().run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
