import unittest

from archipelago.dadap import binding

MISSION = "Progression.Scope.Mission"
SONG = "Progression.Scope.InfiniteDiscoSong"
PLAYTHROUGH = "Progression.Scope.Playthrough"


def decoded(name, value):
    return {"name": name, "status": "decoded", "value": value}


def variable(tag, state="4", counter=False):
    leaf = {"structType": "ProgressionValueSnapshot",
            "fields": [decoded("CurrentState", int(state)), decoded("ViewedState", int(state))]}
    return {"key": [decoded("TagName", tag)], "value": leaf}


def scope(name, context, *variables):
    return {"scope": name, "context": context, "variables": list(variables)}


class SelectAnchorsTests(unittest.TestCase):
    def test_a_scope_whose_contexts_agree_keeps_the_alphabetically_first_stable_variable(self):
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.B"), variable("Progression.A"), variable("Progression.Check")),
                  scope(MISSION, "Hemlock", variable("Progression.Q"), variable("Progression.P")),
                  scope(MISSION, "Arora", variable("Progression.P"), variable("Progression.Q"))]
        selected, contexts, objects = binding.select_anchors(scopes, "Progression.Check")
        self.assertEqual(selected[MISSION], ["Progression.P"])
        self.assertEqual(sorted(contexts), ["Progression.Scope.Mission|Arora", "Progression.Scope.Mission|Hemlock",
                                            "Progression.Scope.Playthrough|None"])

    def test_a_long_played_save_with_an_extra_variable_in_one_context_no_longer_fails(self):
        # Reported after 4-5 hours of play: "BindingError('Selection differs across contexts')" before the game even started. One mission
        # context gained a variable that sorts before the rest, so the contexts no longer had the same first variable.
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.A"), variable("Progression.Check")),
                  scope(MISSION, "Hemlock", variable("Progression.Early"), variable("Progression.P"), variable("Progression.Q")),
                  scope(MISSION, "Arora", variable("Progression.P"), variable("Progression.Q"))]
        selected, contexts, _ = binding.select_anchors(scopes, "Progression.Check")
        self.assertEqual(selected[MISSION], ["Progression.P"])   # the first variable EVERY context has: the mod reads it in all of them
        for key in ("Progression.Scope.Mission|Hemlock", "Progression.Scope.Mission|Arora"):
            self.assertEqual(list(contexts[key]), ["Progression.P"])

    def test_counters_never_anchor_and_a_context_with_nothing_stable_is_still_refused(self):
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.A"), variable("Progression.Check")),
                  scope(MISSION, "Hemlock", variable("Progression.Counter.Kills"), variable("Progression.P"))]
        self.assertEqual(binding.select_anchors(scopes, "Progression.Check")[0][MISSION], ["Progression.P"])
        with self.assertRaisesRegex(binding.BindingError, "No stable anchor in scope " + MISSION):
            binding.select_anchors(scopes + [scope(MISSION, "Arora", variable("Progression.Counter.Kills"))], "Progression.Check")

    def test_contexts_that_share_no_stable_variable_are_refused_with_a_clear_reason(self):
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.A"), variable("Progression.Check")),
                  scope(MISSION, "Hemlock", variable("Progression.P")), scope(MISSION, "Arora", variable("Progression.Q"))]
        with self.assertRaisesRegex(binding.BindingError, "No anchor shared by every context of scope " + MISSION):
            binding.select_anchors(scopes, "Progression.Check")

    def test_song_contexts_with_different_variables_bind_only_what_they_all_have(self):
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.A"), variable("Progression.Check")),
                  scope(SONG, "One", variable("Progression.Song.Best"), variable("Progression.Song.Stars")),
                  scope(SONG, "Two", variable("Progression.Song.Best"))]
        selected, contexts, _ = binding.select_anchors(scopes, "Progression.Check")
        self.assertEqual(selected[SONG], ["Progression.Song.Best"])
        self.assertEqual(list(contexts["Progression.Scope.InfiniteDiscoSong|Two"]), ["Progression.Song.Best"])

    def test_the_check_variable_is_always_added_to_the_playthrough_scope(self):
        scopes = [scope(PLAYTHROUGH, "None", variable("Progression.A"), variable("Progression.Check"))]
        self.assertEqual(binding.select_anchors(scopes, "Progression.Check")[0][PLAYTHROUGH], ["Progression.A", "Progression.Check"])


if __name__ == "__main__":
    unittest.main()
