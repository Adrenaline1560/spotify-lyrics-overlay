# Spotify Lyrics Overlay

A minimal macOS desktop overlay that shows the currently playing Spotify track with time-synced, scrolling lyrics. No OAuth, no API keys — works out of the box.

![overlay screenshot placeholder](https://via.placeholder.com/340x430/1a1a2e/1db954?text=Lyrics+Overlay)

## Features

- Always-on-top semi-transparent floating window
- Song title and artist display
- ⏮ ▶/⏸ ⏭ playback controls
- Time-synced lyrics that scroll and highlight in green as the song plays
- Draggable — click anywhere and drag to reposition on screen
- Zero dependencies — Python 3 stdlib only

## Requirements

- macOS 10.14+
- Python 3.10+ (ships with macOS or install via [Homebrew](https://brew.sh): `brew install python`)
- [Spotify desktop app](https://www.spotify.com/download/mac/) (not the web player)
- Internet connection (for lyrics lookup)

## Run

```bash
python3 lyrics_overlay.py
```

On first run, macOS will ask for "Automation" permission so the app can talk to Spotify — click **OK**.

## How it works

| Component | Technology |
|---|---|
| Reads Spotify track info | AppleScript via `osascript` (built-in to macOS) |
| Controls playback | AppleScript `playpause` / `next track` / `previous track` |
| Fetches lyrics | [lrclib.net](https://lrclib.net) REST API (free, no account) |
| UI | Python `tkinter` (stdlib) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Open Spotify to get started" | Launch the Spotify desktop app first |
| "No lyrics found" | Track may not be in lrclib's database |
| Lyrics slightly out of sync | Normal — position is polled every second |
| Window hides behind full-screen app | Drag it back into view; known macOS/tkinter limitation |

## Privacy

- No data is sent to Spotify
- Track name and artist are sent to [lrclib.net](https://lrclib.net) solely to look up lyrics
