from setuptools import setup

APP = ['lyrics_overlay.py']
OPTIONS = {
    'argv_emulation': False,
    'packages': ['PIL'],
    'plist': {
        'CFBundleName': 'Spotify Lyrics',
        'CFBundleDisplayName': 'Spotify Lyrics',
        'CFBundleIdentifier': 'com.spotify-lyrics-miniplayer',
        'CFBundleVersion': '1.0.0',
        'LSUIElement': True,  # hide from Dock (background app)
        'NSAppleEventsUsageDescription': 'Required to read track info from Spotify.',
    },
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
