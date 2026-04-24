# Spotify Lyrics Miniplayer

A minimal macOS desktop overlay that shows time-synced lyrics for the currently playing Spotify track. The background colour is derived from the album art. No OAuth, no API keys — works out of the box.

## Features

- Always-on-top semi-transparent floating window
- Song title and artist display
- Time-synced lyrics that scroll with the song — shows as many lines as fit the window
- Album-art-tinted background colour
- Progress bar with elapsed / total time
- ⚙ Settings panel to adjust transparency (saved between sessions)
- Draggable — click anywhere and drag to reposition

## Requirements

- macOS 10.14+
- Python 3.12 ([Homebrew](https://brew.sh): `brew install python@3.12`)
- [Spotify desktop app](https://www.spotify.com/download/mac/) (not the web player)
- Internet connection (for lyrics lookup)

## Option A — Run as a native macOS app (recommended)

Build a double-clickable `.app` bundle:

```bash
git clone https://github.com/Adrenaline1560/spotify-lyrics-overlay.git
cd spotify-lyrics-overlay
pip3.12 install -r requirements.txt py2app
python3.12 setup.py py2app
```

The app is created at `dist/Spotify Lyrics.app`. Drag it to your **Applications** folder and double-click to launch.

> On first launch, macOS will ask for **Automation** permission so the app can talk to Spotify — click **OK**.

## Option B — Run directly with Python

```bash
git clone https://github.com/Adrenaline1560/spotify-lyrics-overlay.git
cd spotify-lyrics-overlay
pip3.12 install -r requirements.txt
python3.12 lyrics_overlay.py
```

On first run, macOS will ask for **Automation** permission — click **OK**.

## How it works

| Component | Technology |
|---|---|
| Reads Spotify track info | AppleScript via `osascript` (built-in to macOS) |
| Fetches lyrics | [lrclib.net](https://lrclib.net) REST API (free, no account) |
| Album colour | Pillow — averages album art pixels |
| UI | Python `tkinter` (stdlib) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Open Spotify to get started" | Launch the Spotify desktop app first |
| "No lyrics found" | Track may not be in lrclib's database |
| Lyrics slightly out of sync | Normal — position is polled every second |
| Window hides behind a full-screen app | Drag it back into view; known macOS/tkinter limitation |

## Privacy

- No data is sent to Spotify
- Track name and artist are sent to [lrclib.net](https://lrclib.net) solely to look up lyrics
