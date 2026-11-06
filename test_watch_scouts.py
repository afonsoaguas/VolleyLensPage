import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import publish
from test_publish import sample_scout
from watch_scouts import Watcher, slug


class WatcherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repo"
        self.source = self.base / "Scout"
        (self.root / "scouts").mkdir(parents=True)
        self.source.mkdir()
        (self.root / "scouts" / "first.dvw").write_bytes(sample_scout().encode("utf-8"))
        self.matches = {"matches": [{"id": "first", "scout": "scouts/first.dvw",
                                     "videos": [{"id": "7yl0EOYuQ64", "offsetSeconds": 0}]}]}
        (self.root / "matches.json").write_text(json.dumps(self.matches), encoding="utf-8")

    def watcher(self, **options):
        return Watcher(self.root, self.source, quiet_seconds=60, use_git=False, **options)

    def drop(self, name, text, age=120):
        path = self.source / name
        path.write_bytes(text.encode("utf-8"))
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def config(self):
        return json.loads((self.root / "matches.json").read_text(encoding="utf-8"))

    def test_new_scout_added_with_pending_youtube_id_and_published(self):
        watcher = self.watcher()
        self.drop("&XXX01 GDSCascais vs Gipa.dvw", sample_scout() + "\n")
        watcher.scan()
        entry = self.config()["matches"][-1]
        self.assertEqual(entry, {"id": "xxx01-gdscascais-vs-gipa", "scout": "scouts/xxx01-gdscascais-vs-gipa.dvw",
                                 "videos": [{"id": "TEMP_YOUTUBE_ID", "offsetSeconds": 0}]})
        self.assertTrue((self.root / entry["scout"]).is_file())
        library = json.loads((self.root / "docs" / "data" / "library.json").read_text(encoding="utf-8"))
        published = library["matches"][-1]
        self.assertEqual((published["videos"], published["videoPending"]), ([], True))
        self.assertNotIn("videoPending", library["matches"][0])
        watcher.scan()
        self.assertEqual(len(self.config()["matches"]), 2)

    def test_files_present_on_first_run_are_not_published_unless_requested(self):
        self.drop("old.dvw", sample_scout() + "\n")
        self.watcher().scan()
        self.assertEqual(len(self.config()["matches"]), 1)
        (self.root / ".automation" / "state.json").unlink()
        self.watcher(import_existing=True).scan()
        self.assertEqual(self.config()["matches"][-1]["id"], "old")

    def test_waits_until_dv4_stops_saving(self):
        watcher = self.watcher()
        path = self.drop("live.dvw", sample_scout() + "\n", age=0)
        watcher.scan()
        self.assertEqual(len(self.config()["matches"]), 1)
        watcher.scan(now=path.stat().st_mtime + 61)
        self.assertEqual(self.config()["matches"][-1]["id"], "live")

    def test_invalid_scout_does_not_change_catalogue_then_valid_version_is_added(self):
        watcher = self.watcher()
        original = (self.root / "matches.json").read_bytes()
        path = self.drop("bad.dvw", "encodedPlayerFile==")
        with self.assertLogs("volleylens.watcher", "ERROR"):
            watcher.scan()
        self.assertEqual((self.root / "matches.json").read_bytes(), original)
        self.assertFalse((self.root / "scouts" / "bad.dvw").exists())
        self.drop(path.name, sample_scout() + "\n")
        watcher.scan()
        self.assertEqual(self.config()["matches"][-1]["id"], "bad")

    def test_changed_scout_updates_file_and_keeps_youtube_id(self):
        watcher = self.watcher()
        self.drop("game.dvw", sample_scout() + "\n")
        watcher.scan()
        config = self.config()
        config["matches"][-1]["videos"] = [{"id": "abcdefghijk", "offsetSeconds": 3}]
        (self.root / "matches.json").write_text(json.dumps(config), encoding="utf-8")
        self.drop("game.dvw", sample_scout() + "\n\n")
        watcher.scan()
        self.assertEqual(self.config()["matches"][-1]["videos"][0]["id"], "abcdefghijk")
        self.assertEqual((self.root / "scouts" / "game.dvw").read_text(encoding="utf-8"), sample_scout() + "\n\n")
        self.assertEqual(len(self.config()["matches"]), 2)

    def test_duplicates_and_name_collisions(self):
        watcher = self.watcher()
        self.drop("copy.dvw", sample_scout())  # Same bytes as the already published "first".
        self.drop("First.dvw", sample_scout() + "\n")
        watcher.scan()
        self.assertEqual([entry["id"] for entry in self.config()["matches"]], ["first", "first-2"])
        self.assertEqual(slug("&Ação 03 Benfica vs Sporting"), "acao-03-benfica-vs-sporting")

    def test_mixed_pending_and_real_videos_rejected(self):
        with self.assertRaises(ValueError):
            publish.video_config([{"id": "TEMP_YOUTUBE_ID"}, {"id": "7yl0EOYuQ64"}])
        self.assertEqual(publish.video_config([{"id": "TEMP_YOUTUBE_ID"}]), [])

    def test_commits_and_pushes_only_catalogue_paths(self):
        def git(*args, cwd=self.root):
            return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout
        remote = self.base / "remote.git"
        git("init", "--bare", "-b", "main", str(remote), cwd=self.base)
        git("init", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.com")
        (self.root / "notes.txt").write_text("keep", encoding="utf-8")
        git("add", "matches.json", "scouts")
        git("commit", "-m", "start")
        git("remote", "add", "origin", str(remote))
        git("push", "-u", "origin", "main")
        watcher = Watcher(self.root, self.source, quiet_seconds=60)
        self.drop("pushed.dvw", sample_scout() + "\n")
        watcher.scan()
        self.assertIn("Add match pushed", git("log", "-1", "--format=%s", "origin/main"))
        self.assertIn("?? notes.txt", git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
