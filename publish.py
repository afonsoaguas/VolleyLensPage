"""Build static JSON from readable DVW exports; Python is a publishing tool only."""

import argparse
import json
import math
import re
from pathlib import Path

from scout_stats import ScoutError, display_text, statistics


ROOT = Path(__file__).resolve().parent
MAX_SCOUT = 5 * 1024 * 1024
PENDING_VIDEO_ID = "TEMP_YOUTUBE_ID"


def read_scout(path):
    return decode_scout(path.read_bytes(), path.name)


def decode_scout(blob, name):
    if not blob or len(blob) > MAX_SCOUT:
        raise ValueError(f"{name}: scout must be nonempty and no larger than 5 MB.")
    if not blob.startswith((b"[3DATAVOLLEYSCOUT]", b"\xef\xbb\xbf[3DATAVOLLEYSCOUT]")):
        raise ValueError(f"{name}: use a readable DV4 export, not an encoded Player download.")
    try:
        return blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        return blob.decode("cp1252")


def video_config(value):
    if not isinstance(value, list):
        raise ValueError("Each match needs a videos array (it may be empty).")
    videos = []
    pending = [isinstance(entry, dict) and entry.get("id") == PENDING_VIDEO_ID for entry in value]
    if any(pending):
        # Video indexes come from the scout, so a partly-pending list would shift clips to the wrong video.
        if not all(pending):
            raise ValueError(f"Replace every {PENDING_VIDEO_ID} in a match before publishing its other videos.")
        return []
    for entry in value:
        if not isinstance(entry, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(entry.get("id", ""))):
            raise ValueError("Each video needs an 11-character YouTube id, not a full URL.")
        offset = entry.get("offsetSeconds", 0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise ValueError("offsetSeconds must be a finite number.")
        videos.append({"id": entry["id"], "offsetSeconds": offset})
    return videos


def metadata(text):
    section = None
    fields = []
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[3MATCH]" and line:
            fields = line.split(";")
            break
    date = fields[0] if fields else ""
    competition = display_text(fields[12] if len(fields) > 12 and fields[12] else fields[3]) if len(fields) > 3 else ""
    return date, competition


def build(root=ROOT):
    root = Path(root).resolve()
    config = json.loads((root / "matches.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("matches"), list) or not config["matches"]:
        raise ValueError("matches.json must contain a nonempty matches array.")
    library = []
    outputs = {}
    seen = set()
    for entry in config["matches"]:
        if not isinstance(entry, dict):
            raise ValueError("Each match must be an object.")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier):
            raise ValueError("Match ids must use lowercase letters, digits and single separating hyphens.")
        if identifier in seen:
            raise ValueError(f"Duplicate match id: {identifier}")
        seen.add(identifier)
        source = entry.get("scout")
        if not isinstance(source, str):
            raise ValueError(f"{identifier}: scout must name a readable DVW file.")
        path = (root / source).resolve()
        if not path.is_relative_to(root / "scouts") or path.suffix.lower() != ".dvw":
            raise ValueError(f"{identifier}: scout must be a .dvw file inside the scouts folder.")
        text = read_scout(path)
        data = statistics(text)
        data.pop("retrievedAt", None)
        videos = video_config(entry.get("videos"))
        video_pending = any(isinstance(video, dict) and video.get("id") == PENDING_VIDEO_ID for video in entry["videos"])
        date, competition = metadata(text)
        scores = data["scores"]
        home, away = data["all"]["teams"]
        item = {
            "id": identifier, "home": home["name"], "away": away["name"],
            "date": date, "competition": competition,
            "score": f"{sum(s['home'] > s['away'] for s in scores)} - {sum(s['away'] > s['home'] for s in scores)}" if scores else "",
            "videos": videos, "data": f"data/{identifier}.json",
        }
        if video_pending:
            item["videoPending"] = True
        data["match"] = item
        library.append(item)
        outputs[f"{identifier}.json"] = data
    # Validate the entire catalogue before replacing any previously published data.
    destination = root / "docs" / "data"
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in {**outputs, "library.json": {"version": 1, "matches": library}}.items():
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return library


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        result = build()
    except (OSError, ValueError, ScoutError) as error:
        parser.exit(1, f"Publishing failed: {error}\n")
    print(f"Published {len(result)} match(es) to docs\\data. Upload docs to GitHub Pages; no backend is required.")
