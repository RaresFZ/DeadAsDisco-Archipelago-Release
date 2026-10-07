"""Exact verified build and runtime pins. Anything else is refused, never guessed."""
# Current build. 25772865 changed combat/boss assets and re-cooked levels: the archived configuration, localization, string tables and every
# item/location definition are byte-identical to 25647873 (archipelago/data/evidence/build-25772865-static-diff.json).
BUILD = "Pagoda 5.7.4-33836 (Steam build 25772865)"
EXE_NAME = "PagodaSteam-Win64-Shipping.exe"
EXE_SHA256 = "81157164f458d8afea1addc04298c7d829c10ddcdacbe65228d5e571f4e2fc51"
# The previous build, on which every release up to 0.5.7 was verified live. Still accepted for players who have not updated.
PREVIOUS_BUILDS = {"be96d13e96b9fdd50d6171f294b1f8b7fddfae672bfc934336ad695b3c827366": "Pagoda 5.7.4-33649 (Steam build 25647873)"}


def supported_exe_hashes():
    return {EXE_SHA256, *PREVIOUS_BUILDS}


def supported_builds_text():
    return " or ".join([BUILD, *PREVIOUS_BUILDS.values()])
UE4SS_ARCHIVE_NAME = "zDEV-UE4SS_v3.0.1-1152-ge3ba1016.zip"
UE4SS_ARCHIVE_URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental/" + UE4SS_ARCHIVE_NAME
UE4SS_ARCHIVE_SHA256 = "7d2dc6163c92714c15cb7df7179d8333581fdf655275fe10ec0b5b7687c77d00"
UE4SS_DLL_SHA256 = "680a026890abb4d0df2211251f8defc1681a584275f1521dcc0fe30af480006f"
PROXY_SHA256 = "cf440b9eb8643bb7c434acfda696aee57fd981d185dca5e57fb8dbb18f8fc1cd"
# Offline, isolated launch: no Steam, no network. Cloud synchronization can never touch swapped saves.
LAUNCH_ARGUMENTS = "-nosteam -httpproxy=127.0.0.1:1"
