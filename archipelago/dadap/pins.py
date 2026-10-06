"""Exact verified build and runtime pins. Anything else is refused, never guessed."""
BUILD = "Pagoda 5.7.4-33649 (Steam build 25647873)"
EXE_NAME = "PagodaSteam-Win64-Shipping.exe"
EXE_SHA256 = "be96d13e96b9fdd50d6171f294b1f8b7fddfae672bfc934336ad695b3c827366"
UE4SS_ARCHIVE_NAME = "zDEV-UE4SS_v3.0.1-1152-ge3ba1016.zip"
UE4SS_ARCHIVE_URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental/" + UE4SS_ARCHIVE_NAME
UE4SS_ARCHIVE_SHA256 = "7d2dc6163c92714c15cb7df7179d8333581fdf655275fe10ec0b5b7687c77d00"
UE4SS_DLL_SHA256 = "680a026890abb4d0df2211251f8defc1681a584275f1521dcc0fe30af480006f"
PROXY_SHA256 = "cf440b9eb8643bb7c434acfda696aee57fd981d185dca5e57fb8dbb18f8fc1cd"
# Offline, isolated launch: no Steam, no network. Cloud synchronization can never touch swapped saves.
LAUNCH_ARGUMENTS = "-nosteam -httpproxy=127.0.0.1:1"
