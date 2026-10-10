"""Plain-words explanations for the errors a player can meet, and what to do about them.

The technical message is always kept as it is (journal, copy-details text, launcher-log.txt); this only adds a short explanation next
to it. Each entry has a stable code so a screenshot is enough to know which case it was.
"""
import re

CONTACT = ("Still stuck? Ping @the_twelvez in the Dead As Disco channel of the Archipelago Discord server. Send a screenshot of this "
           "window and describe what you did just before. I may ask you for a few more files.")

# (code, pattern, title, what it means, [what to try])
CATALOG = (
    ("E-NOT-RESTORED", r"NOT restored yet",
     "Your saves are safe but not put back yet", "The game or Steam was still open when the session ended.",
     ["Close the game and Steam completely.", "Press Recover saves."]),
    ("E-STILL-OPEN", r"Close Dead as Disco completely|Exit Steam completely|Timed out waiting for the game and Steam",
     "The game or Steam is still open", "Your saves are swapped while the game is closed, and Steam must be closed too so its cloud cannot interfere.",
     ["Quit Dead as Disco completely, then quit Steam (right-click its tray icon, Exit).", "Press Play again."]),
    ("E-FILES", r"Missing capabilities certificate|archive pin mismatch|pin mismatch|Pinned proxy source changed|not bundled|Archive lacks",
     "The app files look incomplete or changed", "Part of the app is missing or was altered, often by an antivirus or an interrupted extraction.",
     ["Delete the app folder and extract the zip again, all the way.", "Keep DeadAsDiscoAP.exe inside its folder with the other files.",
      "Add the folder to your antivirus exclusions."]),
    ("E-SERVER-NO-ANSWER", r"No answer from the Archipelago server|Connection to .* failed|WinError 1(0061|0060|225)|timed out|getaddrinfo|"
     r"Name or service not known|actively refused|connection refused by the server",
     "The server did not answer",
     "The app could not reach the Archipelago room, or the room said no.",
     ["Ask whoever hosts for the current address and port: the port changes every time the room restarts.",
      "Check that the room is still open and that your internet works.",
      "Pause any VPN or strict firewall, then press Play again."]),
    ("E-PASSWORD", r"requires a password|InvalidPassword|Server requires",
     "This room needs a password", "The host protected the room with a password and none (or a wrong one) was typed.",
     ["Type the password in the Password field (ask the host).", "Press Play again."]),
    ("E-SLOT", r"InvalidSlot",
     "Slot name not found", "The room does not have a player with that exact name.",
     ["Copy the slot name from the room page, capital letters count.", "Press Play again."]),
    ("E-VERSION", r"InvalidGame|IncompatibleVersion|InvalidItemsHandling",
     "This room does not match the app", "The room is not a Dead as Disco room, or it was made with another Archipelago version.",
     ["Ask the host which release the room was generated with, and use the same app version.", "Make sure you typed the right room address."]),
    ("E-WORLD-VERSION", r"different Dead as Disco world version",
     "This multiworld was made with another version of the Dead as Disco world",
     "The room and this app do not speak the same version of the randomizer.",
     ["Ask the host to regenerate the multiworld with the dead_as_disco.apworld from the same release zip as your app.",
      "Or get the app version that matches the room."]),
    ("E-OPTIONS", r"has not validated",
     "The room uses options this app does not support yet", "The multiworld enabled something that is still being tested.",
     ["Ask the host to regenerate with the options named in the message turned off."]),
    ("E-TUTORIAL", r"tutorial of this multiworld was not saved",
     "The tutorial was not saved completely", "The game closed before it finished writing its two save files. Nothing was changed and your real saves are untouched.",
     ["Press Play again.", "Finish ONLY the tutorial and stay in the hub.",
      "Quit from the game's menu (not Alt+F4 or Task Manager), then close Steam."]),
    ("E-UNFINISHED", r"unfinished session exists",
     "A previous session did not finish", "The last session ended before your saves were put back. They are safe in the backup.",
     ["Close the game and Steam, then press Recover saves.", "Then press Play."]),
    ("E-BUILD", r"Unsupported game build",
     "Your game version is not supported yet", "Dead as Disco was updated to a version this app has not been checked against.",
     ["Look for a newer release of the app, or ask me and I will add it."]),
    ("E-SAVE-FORMAT", r"Unsupported save header|SaveError",
     "The app could not read a save file", "The game was updated and writes its saves in a way this app version does not know, or a save was cut short.",
     ["Update the app to the newest release.", "If it is the first run, press Play again and play the tutorial to the end."]),
    ("E-MOD-START", r"UE4SS reported a fatal error|game mod did not start|did not start in time",
     "The game mod did not start", "The game opened but the Archipelago mod never answered.",
     ["Press Play again.", "Add the app folder and %LOCALAPPDATA%\\DeadAsDiscoAP to your antivirus exclusions, then try again.",
      "Close overlays and other mod tools that attach to the game."]),
    ("E-NETWORK-GUARD", r"external network connections",
     "The game went online when it should stay offline", "For safety the app refuses to continue if the game talks to the internet during startup.",
     ["Close Steam, overlays and any download running in the background.", "Press Play again."]),
    ("E-CERT", r"CERTIFICATE_VERIFY_FAILED|certificate (has )?expired|certificate verify",
     "The secure connection check failed", "Your PC does not trust the server's certificate. This is usually a wrong date or time, or antivirus HTTPS scanning.",
     ["Check that your PC's date and time are correct (sync them in Windows settings).",
      "Turn off HTTPS or web scanning in your antivirus for a moment, then press Play again."]),
    ("E-DISK", r"volume|disk space|Missing directory",
     "A folder or drive problem", "The app needs free space and its working folder on the same drive as the game saves.",
     ["Free some disk space (a few GB).", "Run Check install and read the red lines."]),
    ("E-BRIDGE", r"game bridge stopped itself",
     "The in-game mod stopped itself", "The mod found something unsafe or too slow and stopped to protect your game. Your saves are safe.",
     ["Quit the game from its menu and close Steam.", "Press Play again.", "If it keeps happening, send me the file named in the message."]),
    ("E-PROFILE", r"bound to a different Archipelago|already has game progress",
     "This profile belongs to another game", "Each multiworld gets its own profile. This one already has other progress.",
     ["Use the exact slot and room you started with.", "For a new multiworld the app creates a fresh profile by itself."]),
    ("E-SAVES-LINK", r"reparse point",
     "Your saves folder is a special link", "The app does not touch saves that are redirected (for example by a sync tool).",
     ["Stop syncing the Dead as Disco saves folder with such a tool, then try again."]),
)
_COMPILED = [(code, re.compile(pattern, re.IGNORECASE), title, what, steps) for code, pattern, title, what, steps in CATALOG]
UNKNOWN = ("E-UNKNOWN", "Something unexpected stopped the launcher",
           "Your real saves are safe: the app never plays on them.", ["Press Check install and read the red lines.", "Press Recover saves, then Play again."])


def explain(message):
    """{code, title, what, steps} for a technical message (the unknown case when nothing matches)."""
    for code, pattern, title, what, steps in _COMPILED:
        if pattern.search(message):
            return {"code": code, "title": title, "what": what, "steps": list(steps), "known": True}
    code, title, what, steps = UNKNOWN
    return {"code": code, "title": title, "what": what, "steps": list(steps), "known": False}
