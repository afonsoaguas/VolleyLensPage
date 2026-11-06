import json
import tempfile
import unittest
from pathlib import Path

from publish import build, read_scout, video_config
from scout_stats import statistics


def action(code, selected_set=1, video="1", seconds="206"):
    return ";".join([code] + [""] * 7 + [str(selected_set), "2", "6", video, seconds])


def sample_scout():
    return "\n".join([
        "[3DATAVOLLEYSCOUT]", "[3MATCH]", "10/18/2026;;;Test;",
        "[3TEAMS]", "H;Home;1;", "V;Away;0;",
        "[3SET]", "True;;;;25-23;30;", "True;;;;23-25;29;", "True;;;;;;",
        "[3PLAYERS-H]", "0;17;99;;;;;;Nick;Example;Player;;L;",
        "0;9;88;;;;;;Unused;Unused;Player;;;",
        "[3PLAYERS-V]", "1;7;77;;;;;;Away;Example;Away;;;",
        "[3SCOUT]",
        action("*17SH#"), action("*17SH="), action("*17AH#"), action("*17AH="),
        action("*17AH/"), action("*17RH#"), action("*17RH+"), action("*17RH="),
        action("*17BH#"), action("*17EH+"), action("*17DH/"), action("*17FH#", 2),
        action("a07AH#", 2, seconds="312.5"), action("a07AH+", 2, seconds="0"),
        action("*$$&H#"), action("*p01:00"), action("*z2>LUp"),
    ])


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scouts").mkdir()
        (self.root / "scouts" / "match.dvw").write_text(sample_scout(), encoding="utf-8")
        self.entry = {"id": "test-match", "scout": "scouts/match.dvw",
                      "videos": [{"id": "7yl0EOYuQ64", "offsetSeconds": -12}]}
        self.configure([self.entry])

    def configure(self, entries):
        (self.root / "matches.json").write_text(json.dumps({"matches": entries}), encoding="utf-8")

    def test_build_standalone_statistics_and_metadata(self):
        library = build(self.root)
        match = library[0]
        self.assertEqual((match["home"], match["away"], match["date"], match["competition"], match["score"]),
                         ("Home", "Away", "10/18/2026", "Test", "1 - 1"))
        self.assertEqual(match["videos"][0]["offsetSeconds"], -12)
        data = json.loads((self.root / "docs" / match["data"]).read_text(encoding="utf-8"))
        self.assertEqual(data["all"]["actionCount"], 14)
        self.assertEqual(len(data["actions"]), 14)
        self.assertEqual((data["actions"][0]["videoIndex"], data["actions"][0]["videoSeconds"]), (0, 206))
        self.assertEqual(data["all"]["teams"][0]["players"][0]["number"], 9)
        player = data["all"]["teams"][0]["players"][1]
        self.assertEqual((player["number"], player["points"], player["attackEfficiency"]), (17, 3, -33.3))
        unused = data["all"]["teams"][0]["players"][0]
        self.assertIsNone(unused["killPercent"])
        self.assertEqual(sum(entry["actionCount"] for entry in data["sets"]), 14)
        self.assertNotIn("retrievedAt", data)
        self.assertNotIn("scouts/", json.dumps(data))
        self.assertNotIn("C:\\", json.dumps(data))
        self.assertEqual(json.loads((self.root / "docs" / "data" / "library.json").read_text())["version"], 1)

    def test_failed_build_preserves_previously_published_files(self):
        build(self.root)
        path = self.root / "docs" / "data" / "library.json"
        previous = path.read_bytes()
        self.configure([self.entry, {**self.entry, "id": "missing", "scout": "scouts/not-found.dvw"}])
        with self.assertRaises(OSError):
            build(self.root)
        self.assertEqual(path.read_bytes(), previous)

    def test_duplicate_invalid_ids_and_path_escape_rejected(self):
        for entries in [[self.entry, self.entry], [{**self.entry, "id": "../escape"}],
                        [{**self.entry, "scout": "../outside.dvw"}], [{**self.entry, "scout": "matches.json"}], []]:
            with self.subTest(entries=entries):
                self.configure(entries)
                with self.assertRaises(ValueError):
                    build(self.root)

    def test_video_config_rejects_bad_ids_and_offsets(self):
        for value in [None, [{}], [{"id": "https://youtu.be/7yl0EOYuQ64"}],
                      [{"id": "7yl0EOYuQ64", "offsetSeconds": float("inf")}],
                      [{"id": "7yl0EOYuQ64", "offsetSeconds": True}],
                      [{"id": "7yl0EOYuQ64", "offsetSeconds": "5"}]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                video_config(value)
        self.assertEqual(video_config([]), [])

    def test_plain_exports_only_no_player_or_crypto_needed(self):
        path = self.root / "scouts" / "match.dvw"
        for encoding in ("utf-8-sig", "cp1252"):
            path.write_bytes(sample_scout().encode(encoding))
            self.assertEqual(read_scout(path), sample_scout())
        path.write_bytes(b"encodedPlayerFile==")
        with self.assertRaisesRegex(ValueError, "readable DV4 export"):
            read_scout(path)

    def test_missing_timing_and_unassigned_actions_remain_in_stats(self):
        data = statistics(sample_scout() + "\n" + action("*$$AH#", seconds="nan"))
        self.assertEqual(data["all"]["actionCount"], 15)
        self.assertEqual(data["all"]["teams"][0]["totals"]["kills"], 2)
        self.assertIsNone(data["actions"][-1]["videoSeconds"])
        self.assertIsNone(data["actions"][-1]["player"])
        self.assertTrue(any("lack usable video" in warning for warning in data["warnings"]))

    def test_grade_counts_players_and_sets_reconcile(self):
        data = statistics(sample_scout())
        for index, team in enumerate(data["all"]["teams"]):
            for key in ("points", "serve", "aces", "attacks", "kills", "blockPoints", "receptions"):
                self.assertEqual(sum(player[key] for player in team["players"]), team["totals"][key])
                self.assertEqual(sum(entry["teams"][index]["totals"][key] for entry in data["sets"]), team["totals"][key])


if __name__ == "__main__":
    unittest.main()
