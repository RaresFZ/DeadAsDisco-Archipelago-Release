# Dead as Disco - Archipelago

Play **Dead as Disco** as an [Archipelago](https://archipelago.gg) randomizer, alone or with friends in a multiworld.

- The **skill tree is a shop**: buying a node sends a *check* (it can hold an item for anyone). You get your own skills when
  Archipelago sends them to you.
- **Idol powers** work the same way: beating an Idol sends a check; the power comes from the multiworld.
- The five **missions are locked** behind Mission Access items (you start with one).
- Challenges, memorabilia you pick up, quests, star ratings, achievements and shop purchases can all be checks.
- Filler comes as **Fan Packs** (fans to spend in the skill tree). Optional **traps** and **DeathLink**.

This guide takes you from nothing to playing. You do **not** need Python or any programming tools: just download the
latest zip from the **Releases** page of this repository (the source code is for contributors, see the end of this file).

---

## 1. What you need

| | |
|---|---|
| A PC | Windows 10 or 11 |
| The game | **Dead as Disco** on Steam, fully updated (the app supports Steam builds **25772865** and **25647873** and tells you if yours differs; don't use a beta branch) |
| The mod package | `DeadAsDiscoAP-<version>-windows.zip` (from the project's *Releases* page or from whoever invited you) |
| A multiworld | Someone has to host it (see step 4; it can be you) |
| About 1 GB free | On the drive where Windows keeps your user files |

## 2. Install (30 seconds)

1. Right-click the zip, choose **Extract All...**, and extract it somewhere you will find it again (for example your Desktop).
2. Open the new folder `DeadAsDiscoAP`. It contains:
   - `DeadAsDiscoAP.exe`: the app you will run
   - `Dead as Disco.yaml`: your player settings template (step 3)
   - `dead_as_disco.apworld`: the Archipelago world file (only the person who generates the multiworld needs it)
   - `README.md`, `FINAL_AUDIT.md`: this guide and the exact list of what is supported
3. Keep the folder together. There is nothing else to install; the app sets itself up the first time you press Play.

Windows may show a blue **"Windows protected your PC"** box when you first run the app. Click **More info**, then **Run anyway**.
(The app is not code-signed.)

## 3. Make your settings file (your YAML)

Every player gives the multiworld host a small text file saying what they want.

1. Open `Dead as Disco.yaml` with Notepad (right-click > Open with > Notepad).
2. Change the line `name:` to your player name (this is your **slot name**; keep it, you will type it into the app).
3. Read the comments: every option is explained and grouped (Goal and Missions, Shuffled Rewards, What Counts as a Check, Filler
   and Traps, DeathLink). The defaults are a good first multiworld. Things people usually change:
   - `goal`: what finishes the game (all five missions by default).
   - `starting_mission`: which of the five missions you can play from the start.
   - `include_songs`: turn on the 36 extra Infinite Disco songs (adds a lot of checks).
   - `death_link`: share deaths with other DeathLink players.
4. Save the file and send it to the person hosting.

Tip: you can also keep several files with different names, one per multiworld.

## 4. Hosting a multiworld (only the host does this)

1. Install **Archipelago 0.6.8** from <https://github.com/ArchipelagoMW/Archipelago/releases> (the Windows installer).
2. Double-click `dead_as_disco.apworld`. The Archipelago Launcher installs it. (Or copy the file into Archipelago's `custom_worlds` folder.)
3. Put every player's YAML (including games other than Dead as Disco) into Archipelago's `Players` folder.
4. In the Archipelago Launcher click **Generate**. The result appears in its `output` folder as a `.zip`.
5. Host it: either click **Host** in the Launcher (play over your own network/port-forwarding) or upload the zip at
   <https://archipelago.gg/uploads> and click *Create new room*.
6. Give each player the **server address** (for example `archipelago.gg:12345`), their **slot name** and the **password** if you set one.

> Worlds made with an older version of this project are not compatible: regenerate after updating.

## 5. Before you play (once)

1. **Steam Cloud off for this game:** in Steam, Library > right-click Dead as Disco > **Properties** > **General** > untick
   *Keep games saves in the Steam Cloud*. (Turn it back on when you finish; this only protects your saves during the swap described below.)
2. **Close Steam completely:** right-click the Steam icon in the system tray (bottom right, next to the clock) > **Exit**.
   Also close Dead as Disco if it is open. The app waits until both are closed.

## 6. Play

1. Double-click **DeadAsDiscoAP.exe**.
2. Type the **Server** (`host:port`), your **Slot name**, and the **Password** (leave it empty if there is none).
3. Tick the box saying Steam Cloud is off, then click **PLAY**.
4. **First time on a multiworld only:** the game opens for the **tutorial** (the app creates a fresh profile for this multiworld).
   Finish *only the tutorial*, stay in the hub (do **not** start a mission), quit the game to the desktop, and close Steam again.
   The Archipelago game then starts by itself.
5. Press **Continue** and wait about 30 seconds in the hub while the app connects. The app window shows the Archipelago console:
   received items, other players' messages and your own checks. You can type chat or commands (`!hint <item>`, `!help`) in the box at the bottom.
6. Play normally. When you are done, quit the game and close Steam. The window tells you your normal saves are back.

**Next time:** just open the app and click **PLAY** (it remembers the server and slot). It continues exactly where you left off.

### What is different in the game

- Only your starting mission is playable at first; the others unlock when their **Access** item arrives.
- Buying a skill node sends a check and gives you no skill. Skills arrive from the multiworld and are equipped for you.
  A power you have not received cannot be equipped or used.
- Beating an Idol sends its check; its power comes from the multiworld.
- Collectibles count the moment you **pick them up** (in the hub or in a level), not only when you buy them.
- **Fan Packs** (125 / 250 / 500 / 1,000 / 2,000 fans by default) are the usual filler.
  *Fan Packs are still being validated, so the app runs them in a protected test mode.*
- What each shop node contains is listed in `%LOCALAPPDATA%\DeadAsDiscoAP\profiles\<your profile>\node-contents.txt`.
- **Traps:** *Half Heart* (lose a little health, never lethal) and *Silence* (you can run, but cannot attack, dodge or use abilities for a few seconds).
- **DeathLink:** an incoming death drains your health in small hits, then the normal death screen appears; your own death is sent out once.

## 7. Your saves are safe

You never touch any save file. Each time you press PLAY the app moves your real saves aside, plays on a separate Archipelago
profile, and moves your saves back with a hash check; a full backup is also kept in `%LOCALAPPDATA%\DeadAsDiscoAP\backups`.
Nothing stays installed in the game folder between sessions. If the PC crashes or the app is killed mid-session, open the app and click
**Recover saves** (always safe).

## 8. If something goes wrong

| Problem | What to do |
|---|---|
| "Exit Steam completely" / waiting for Steam | Right-click the Steam tray icon > Exit; check Task Manager for `steam.exe` |
| The app says the game build is different | Let Steam update the game and leave beta branches. If Steam just updated it, you may need a newer release of this app |
| "The game bridge stopped itself" in the console | Quit the game and click Play again (your saves are safe). If it repeats, send the file named in that message (`%LOCALAPPDATA%\DeadAsDiscoAP\sessions\<id>\runtime\ap-refusal.txt`) |
| Crash, power cut, or you closed the app mid-game | Open the app > **Recover saves** |
| Not sure everything is fine | Click **Check install** and fix any line that is not OK |
| The game will not connect | Check server address and slot name spelling, and that the host's server is running |
| "CERTIFICATE_VERIFY_FAILED" / "certificate has expired" | Update to release 0.5.10 or newer. If it still happens, check that the PC's date, time and time zone are correct (Windows Settings > Time & language > *Sync now*) |
| You want everything removed | Delete `%LOCALAPPDATA%\DeadAsDiscoAP` (profiles and backups included) and the extracted folder |

Logs: `%LOCALAPPDATA%\DeadAsDiscoAP\last-run.log` and each session's `...\sessions\<id>\core\UE4SS.log`.
(Paste `%LOCALAPPDATA%` in the Explorer address bar to open the folder.)

## 9. Limits

The exact numbers and every exclusion are in `FINAL_AUDIT.md`. In short: 50 song-related records are not checks (their song
data cannot be tied to a visible/unlockable song), 11 records are free at New Game and cannot be checks, there is no stamina trap
(the game has no stamina resource), and cosmetic and dance rewards are not shuffled (only their purchases are checks).
The app needs a supported game build (it refuses any other) and Steam Cloud off. Fan Packs and the first-time tutorial restart are the least-tested parts.

---

## Contributing

Pull requests and bug reports are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and the [development guide](docs/DEVELOPMENT.md)
(setup is one command: `python tools/setup-dev.py`). The exact list of what is and is not a check is in
[docs/FINAL_AUDIT.md](docs/FINAL_AUDIT.md); how checks and items are defined is in [docs/CATALOG.md](docs/CATALOG.md).

## License

[MIT](LICENSE): use, change and share it freely. This is an unofficial fan project, not affiliated with the makers of Dead as Disco,
and it contains no game files. Bundled and required third-party software is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
