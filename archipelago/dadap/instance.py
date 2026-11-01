"""Only one launcher at a time.

Two launchers could both swap the same saves: the second one's Recover would move the first one's parked saves back while its game
starts. The lock is a Windows named mutex, so it disappears with the process, even after a crash.
"""
import sys

NAME = "Local\\DeadAsDiscoAP-Launcher"
ERROR_ALREADY_EXISTS = 183
_held = {}


def acquire(name=NAME):
    """True when this process holds the lock (asking again from the same process is fine); False when another process holds it."""
    if name in _held:
        return True
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True  # the lock could not be asked for: never keep a player out because of that
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
    except Exception:  # noqa: BLE001 - same reason
        return True
    _held[name] = handle
    return True


def tell_already_open():
    """Say it in a message box: the packaged launcher has no console."""
    text = ("The Dead as Disco - Archipelago launcher is already open (look in the taskbar).\n\n"
            "Close it first, or use that window. Two launchers at once could mix up your saves.")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Dead as Disco - Archipelago", 0x40)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)
