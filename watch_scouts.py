"""Watch the DV4 scout folder and publish new readable .dvw files to this GitHub Pages repository."""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
from logging.handlers import RotatingFileHandler
from pathlib import Path

import publish
from scout_stats import ScoutError, statistics


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path(r"C:\Data Project\Data Volley 4\Seasons\GDSC26 27\Scout")
MANAGED_PATHS = ["matches.json", "scouts", "docs/data"]
log = logging.getLogger("volleylens.watcher")


def slug(name):
    text = unicodedata.normalize("NFKD", name.lstrip("&")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "match"


def write_atomic(path, data):
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


class Watcher:
    def __init__(self, root=ROOT, source=DEFAULT_SOURCE, quiet_seconds=600, use_git=True, push=True, import_existing=False):
        self.root = Path(root).resolve()
        self.source = Path(source)
        self.quiet_seconds = quiet_seconds
        self.use_git = use_git
        self.push = push
        self.state_path = self.root / ".automation" / "state.json"
        self.state_path.parent.mkdir(exist_ok=True)
        self.last_push_attempt = 0.0
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = {"version": 1, "files": {}}
            if not import_existing and self.source.is_dir():
                # Only files added after the watcher is first installed count as new.
                for path in self.scout_files():
                    self.state["files"][path.name.casefold()] = {"sha256": self.digest(path.read_bytes()), "id": None,
                                                                 "baseline": True}
                log.info("First run: %d existing scout file(s) marked as already seen.", len(self.state["files"]))
            self.save_state()

    def save_state(self):
        write_atomic(self.state_path, (json.dumps(self.state, indent=2) + "\n").encode("utf-8"))

    @staticmethod
    def digest(blob):
        return hashlib.sha256(blob).hexdigest()

    def scout_files(self):
        return sorted(path for path in self.source.iterdir()
                      if path.is_file() and path.suffix.lower() == ".dvw" and not path.name.startswith("~"))

    def git(self, *args, check=True):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=300,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check and result.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
        return result

    def scan(self, now=None):
        now = time.time() if now is None else now
        if not self.source.is_dir():
            return
        for path in self.scout_files():
            try:
                self.consider(path, now)
            except (OSError, ValueError, ScoutError, RuntimeError, subprocess.TimeoutExpired) as error:
                log.error("%s: %s", path.name, error)
        self.push_pending(now)

    def consider(self, path, now):
        info = path.stat()
        if now - info.st_mtime < self.quiet_seconds:
            return  # DV4 may still be scouting/saving this match.
        key = path.name.casefold()
        record = self.state["files"].get(key)
        blob = path.read_bytes()
        after = path.stat()
        if len(blob) != after.st_size or after.st_mtime_ns != info.st_mtime_ns:
            return  # Changed while reading; try on the next scan.
        sha = self.digest(blob)
        if record and record["sha256"] == sha:
            return
        if record and record.get("failedSha256") == sha:
            return  # Already reported; wait for DV4 to save a different version.
        try:
            text = publish.decode_scout(blob, path.name)
            statistics(text)
            if record and record.get("id"):
                self.update(path, record, blob, sha)
            elif record and record.get("baseline"):
                record["sha256"] = sha  # Pre-existing file changed; it was never published, so keep ignoring it.
                self.save_state()
            else:
                self.add(path, key, blob, sha)
        except (ValueError, ScoutError) as error:
            self.state["files"].setdefault(key, {"sha256": None, "id": None})["failedSha256"] = sha
            self.save_state()
            raise error

    def matches(self):
        return json.loads((self.root / "matches.json").read_text(encoding="utf-8"))

    def managed_dirty(self):
        return bool(self.git("status", "--porcelain", "--", *MANAGED_PATHS).stdout.strip())

    def prepare_git(self):
        if not self.use_git:
            return False
        if self.managed_dirty():
            log.warning("matches.json, scouts or docs/data has uncommitted edits; importing locally without committing.")
            return False
        pulled = self.git("pull", "--rebase", "--autostash", check=False)
        if pulled.returncode:
            log.warning("git pull failed (offline?); the commit will be pushed later: %s", pulled.stderr.strip())
        return True

    def existing_match_for(self, sha, config):
        for entry in config["matches"]:
            scout = self.root / str(entry.get("scout", ""))
            if scout.is_file() and self.digest(scout.read_bytes()) == sha:
                return entry["id"]
        return None

    def add(self, path, key, blob, sha):
        commit = self.prepare_git()
        original = (self.root / "matches.json").read_bytes()
        config = self.matches()
        duplicate = self.existing_match_for(sha, config)
        if duplicate:
            log.info("%s is identical to published match %s; not adding it again.", path.name, duplicate)
            self.state["files"][key] = {"sha256": sha, "id": duplicate}
            self.save_state()
            return
        base = slug(path.stem)
        identifier, number = base, 2
        ids = {entry.get("id") for entry in config["matches"]}
        while identifier in ids or (self.root / "scouts" / f"{identifier}.dvw").exists():
            identifier, number = f"{base}-{number}", number + 1
        target = self.root / "scouts" / f"{identifier}.dvw"
        target.parent.mkdir(exist_ok=True)
        config["matches"].append({"id": identifier, "scout": f"scouts/{identifier}.dvw",
                                  "videos": [{"id": publish.PENDING_VIDEO_ID, "offsetSeconds": 0}]})
        try:
            write_atomic(target, blob)
            write_atomic(self.root / "matches.json", (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            publish.build(self.root)
        except Exception:
            target.unlink(missing_ok=True)
            write_atomic(self.root / "matches.json", original)
            raise
        self.state["files"][key] = {"sha256": sha, "id": identifier}
        self.save_state()
        log.info("Added %s as match %s with YouTube id %s.", path.name, identifier, publish.PENDING_VIDEO_ID)
        if commit:
            self.commit(f"Add match {identifier}")

    def update(self, path, record, blob, sha):
        commit = self.prepare_git()
        entry = next((item for item in self.matches()["matches"] if item.get("id") == record["id"]), None)
        if entry is None:
            log.warning("%s changed, but match %s was removed from matches.json; ignoring it.", path.name, record["id"])
            record["sha256"] = sha
            self.save_state()
            return
        target = (self.root / entry["scout"]).resolve()
        if not target.is_relative_to(self.root / "scouts"):
            raise ValueError(f"{record['id']}: scout path is outside the scouts folder.")
        original = target.read_bytes() if target.exists() else None
        try:
            write_atomic(target, blob)
            publish.build(self.root)
        except Exception:
            if original is None:
                target.unlink(missing_ok=True)
            else:
                write_atomic(target, original)
            raise
        record["sha256"] = sha
        record.pop("failedSha256", None)
        self.save_state()
        log.info("Updated scout for match %s (YouTube id in matches.json kept).", record["id"])
        if commit:
            self.commit(f"Update match {record['id']}")

    def commit(self, message):
        self.git("add", "--", *MANAGED_PATHS)
        if not self.git("diff", "--cached", "--quiet", check=False).returncode:
            return
        self.git("commit", "-m", message, "--", *MANAGED_PATHS)
        log.info("Committed: %s", message)
        self.push_pending(time.time(), force=True)

    def push_pending(self, now, force=False):
        if not (self.use_git and self.push) or (not force and now - self.last_push_attempt < 300):
            return
        ahead = self.git("rev-list", "--count", "@{u}..HEAD", check=False)
        if ahead.returncode or ahead.stdout.strip() in ("", "0"):
            return
        self.last_push_attempt = now
        result = self.git("push", check=False)
        if result.returncode:
            log.warning("git push failed; retrying in 5 minutes: %s", result.stderr.strip())
        else:
            log.info("Pushed to GitHub; Pages will update in a minute or two.")


def single_instance(root):
    import msvcrt
    handle = open(root / ".automation" / "watcher.lock", "a+")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="DV4 Scout folder to watch.")
    parser.add_argument("--quiet-minutes", type=float, default=10,
                        help="Wait until the file has not changed for this long (DV4 saves during scouting).")
    parser.add_argument("--interval", type=float, default=15, help="Seconds between folder checks.")
    parser.add_argument("--no-git", action="store_true", help="Only update the local folder; do not commit or push.")
    parser.add_argument("--no-push", action="store_true", help="Commit locally but do not push.")
    parser.add_argument("--import-existing", action="store_true",
                        help="On the very first run, also publish .dvw files already in the folder.")
    parser.add_argument("--once", action="store_true", help="Check once and exit instead of watching.")
    options = parser.parse_args()

    (ROOT / ".automation").mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(ROOT / ".automation" / "watcher.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    lock = single_instance(ROOT)
    if lock is None:
        log.info("Another watcher is already running; exiting.")
        return
    watcher = Watcher(ROOT, options.source, options.quiet_minutes * 60, not options.no_git, not options.no_push,
                      options.import_existing)
    log.info("Watching %s (waiting %.0f min after the last DV4 save).", options.source, options.quiet_minutes)
    while True:
        try:
            watcher.scan()
        except Exception:
            log.exception("Unexpected watcher error")
        if options.once:
            break
        time.sleep(options.interval)


if __name__ == "__main__":
    main()
