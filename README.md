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

## Quickstart — double-click to run (recommended)

```bash
git clone https://github.com/Adrenaline1560/spotify-lyrics-overlay.git
cd spotify-lyrics-overlay
```

Then double-click **`run.command`** in Finder.

On first launch it automatically sets up a virtual environment and installs dependencies. Subsequent launches start instantly.

> macOS will ask for **Automation** permission on first run so the app can talk to Spotify — click **OK**.
>
> If macOS blocks the script: right-click `run.command` → **Open** → **Open**.

## Alternative — run from Terminal

```bash
git clone https://github.com/Adrenaline1560/spotify-lyrics-overlay.git
cd spotify-lyrics-overlay
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3.12 lyrics_overlay.py
```

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
