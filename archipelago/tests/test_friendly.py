import re
import unittest

from archipelago.dadap import friendly


class FriendlyErrorTests(unittest.TestCase):
    CASES = {
        "No answer from the Archipelago server": "E-SERVER-NO-ANSWER",
        "Connection to wss://archipelago.gg:60206 failed: [WinError 1225] Le syst\u00e8me distant a refus\u00e9": "E-SERVER-NO-ANSWER",
        "Connection refused: InvalidSlot": "E-SLOT",
        "Connection refused: InvalidPassword": "E-PASSWORD",
        "Server requires a password": "E-PASSWORD",
        "The multiworld was generated with a different Dead as Disco world version.": "E-WORLD-VERSION",
        "This build has not validated: fan-packs. Generate with those options disabled.": "E-OPTIONS",
        "The tutorial of this multiworld was not saved completely (the game has not written both of its save files).": "E-TUTORIAL",
        "Close Dead as Disco completely before changing saves.": "E-STILL-OPEN",
        "Timed out waiting for the game and Steam to close": "E-STILL-OPEN",
        "An unfinished session exists. Run recover before starting another.": "E-UNFINISHED",
        "NOT restored yet (Exit Steam completely). Close the game and Steam, then run: recover": "E-NOT-RESTORED",
        "Unsupported game build; supported: 25772865.": "E-BUILD",
        "SaveError('Unsupported save header')": "E-SAVE-FORMAT",
        "The game mod did not start in time": "E-MOD-START",
        "UE4SS reported a fatal error during startup": "E-MOD-START",
        "The game kept external network connections open (1.2.3.4); refusing to enable the AP bridge.": "E-NETWORK-GUARD",
        "CERTIFICATE_VERIFY_FAILED ... certificate has expired": "E-CERT",
        "Missing capabilities certificate; this build cannot grant items": "E-FILES",
        "Proxy DLL pin mismatch": "E-FILES",
        "The game bridge stopped itself (callback-time-budget). Checks and items are paused.": "E-BRIDGE",
        "This profile is bound to a different Archipelago slot/seed. Use a new profile for a new game.": "E-PROFILE",
        "something nobody has seen before": "E-UNKNOWN",
    }

    def test_every_known_message_gets_its_own_plain_explanation(self):
        for message, code in self.CASES.items():
            self.assertEqual(friendly.explain(message)["code"], code, message)

    def test_every_entry_is_complete_and_in_plain_words(self):
        codes = [entry[0] for entry in friendly.CATALOG]
        self.assertEqual(len(codes), len(set(codes)))
        for code, pattern, title, what, steps in friendly.CATALOG:
            re.compile(pattern)
            self.assertTrue(title and what and 1 <= len(steps) <= 4, code)
            self.assertNotRegex(" ".join([title, what, *steps]), r"Traceback|Exception|ReconciliationError|SafetyError", code)

    def test_the_contact_line_names_discord_and_asks_for_a_screenshot(self):
        for word in ("@the_twelvez", "Dead As Disco", "Archipelago", "screenshot"):
            self.assertIn(word, friendly.CONTACT)


if __name__ == "__main__":
    unittest.main()
