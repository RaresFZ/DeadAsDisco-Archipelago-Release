# Third-party notices

This project is an unofficial fan project. It is not affiliated with or endorsed by the makers or publishers of Dead as Disco, and it
contains no game files or assets: only identifiers (names, tags, asset paths) needed to talk to the game. You need your own copy of
the game.

The release package bundles or depends on:

| Component | Use | License |
|---|---|---|
| [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) (experimental build 3.0.1-1152-ge3ba1016, bundled unmodified, SHA-256 pinned in `archipelago/dadap/pins.py`) | Loads the Lua mod into the game | MIT |
| [Archipelago](https://github.com/ArchipelagoMW/Archipelago) (the world targets 0.6.8; used for generation and tests, not bundled) | Randomizer framework and protocol | MIT |
| [websockets](https://github.com/python-websockets/websockets) | Client network connection | BSD-3-Clause |
| [PyInstaller](https://pyinstaller.org) (build tool; the bootloader is bundled in `DeadAsDiscoAP.exe`) | Packages the app | GPL-2.0 with the bootloader exception that permits distributing the packaged app under any license |
| [Python](https://www.python.org) runtime (inside the packaged app) | Runs the app | PSF License |
| [lupa](https://github.com/scoder/lupa) (development only) | Runs the Lua fixtures | MIT |
| Fonts Press Start 2P (CodeMan38), Silkscreen (Jason Kottke), JetBrains Mono (JetBrains), in data/archipelago/dadap/assets/fonts/ | Text of the app window, loaded privately by the app | SIL Open Font License 1.1 |
| Fonts Oswald (Vernon Adams, Kalapi Gajjar, Cyreal) and Roboto Condensed (Christian Robertson), in `data/archipelago/dadap/webui/fonts/` | Text of the launcher window | SIL Open Font License 1.1 |
| [pywebview](https://github.com/r0x0r/pywebview) with [pythonnet](https://github.com/pythonnet/pythonnet), [clr_loader](https://github.com/pythonnet/clr-loader), [bottle](https://github.com/bottlepy/bottle) and proxy_tools | The launcher's own window around Microsoft WebView2 (the WebView2 runtime itself is installed with Edge / Windows and is not bundled) | BSD-3-Clause / MIT |

Each upstream project's license text applies to its own files.
