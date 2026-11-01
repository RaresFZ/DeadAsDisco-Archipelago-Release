import os
import subprocess
import sys
import unittest
from pathlib import Path

from archipelago.dadap import instance

ROOT = Path(__file__).resolve().parents[2]


def other_process_gets(name):
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from archipelago.dadap import instance; print(instance.acquire({name!r}))"
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()


@unittest.skipUnless(sys.platform == "win32", "the lock is a Windows mutex")
class SingleLauncherTests(unittest.TestCase):
    def test_a_second_process_is_refused_while_the_first_holds_the_lock(self):
        name = f"Local\\DeadAsDiscoAP-Test-{os.getpid()}"
        self.assertEqual(other_process_gets(name), "True")        # nobody holds it yet (and that process ends again)
        self.assertTrue(instance.acquire(name))
        self.assertTrue(instance.acquire(name))                   # asking again from the same process is fine
        self.assertEqual(other_process_gets(name), "False")
        self.assertEqual(other_process_gets(name + "-other"), "True")  # another lock name is unaffected

    def test_the_lock_is_released_when_its_process_ends(self):
        name = f"Local\\DeadAsDiscoAP-Test-Exit-{os.getpid()}"
        self.assertEqual(other_process_gets(name), "True")
        self.assertEqual(other_process_gets(name), "True")        # the first holder is gone, so the second one gets it


if __name__ == "__main__":
    unittest.main()
