# VolleyLens Pages

A standalone, static edition of VolleyLens: published volleyball scouting statistics and YouTube action playlists.
This project is separate from the local DV4-connected edition. It does not modify or require that project.

## What runs where

- **Viewers:** a browser loads static HTML/JavaScript/JSON from GitHub Pages and embeds videos from YouTube.
- **Publisher:** Python 3.12+ converts readable `.dvw` exports into static JSON. Only Python's standard library is needed.
- **Not required for viewers:** Python, a backend server, DV4, DV4 Player, Tailscale, or the publisher's PC being on.

The supplied example is **GDSCascais vs Volley4All**, linked to <https://youtu.be/7yl0EOYuQ64>.
No video files, proprietary decoder, vendor executable or decoding keys are included.

## Use locally

The generated site is in `docs`. To rebuild after changing a scout or match configuration:

```powershell
cd C:\Users\aguas\Documents\VolleyLens-Pages
python publish.py
```

For a local preview only:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory docs
```

Open **http://127.0.0.1:8765/**. Stop the preview with Ctrl+C.
This simple file server is only for local preview, not needed once deployed on GitHub Pages.
Do not double-click `index.html`: JSON loading and YouTube embedding require an HTTP/HTTPS origin.

## Add a match

1. Put a **readable exported** `.dvw` in `scouts`. Encoded files downloaded by DV4 Player are not supported.
2. Add an entry to `matches.json` with a unique lowercase, hyphen-separated id, a scout path and its YouTube video id.
3. Run `python publish.py`, then commit and push the source files and regenerated `docs` folder.

Example:

```json
{
  "id": "my-next-match",
  "scout": "scouts/my-next-match.dvw",
  "videos": [
    { "id": "7yl0EOYuQ64", "offsetSeconds": 0 }
  ]
}
```

The `videos` array follows the scout's video references: its first entry maps to DVW video 1, second entry to DVW video 2, and so on.
Use `"videos": []` for a statistics-only match.
Only generated statistics, necessary roster information and action timing are deployed to Pages; the original scouting files remain in the source repository.
All repository and published information should be treated as public when using a public repository/site.

## Automatic import from DV4

`watch_scouts.py` watches `C:\Data Project\Data Volley 4\Seasons\GDSC26 27\Scout` (it waits if the folder does not exist yet). For every **new** `.dvw` it:

1. Waits until DV4 has not saved the file for 10 minutes (DV4 keeps saving while you scout).
2. Rejects unreadable/encoded files without changing anything.
3. Copies it to `scouts/<id>.dvw` (id from the file name, e.g. `&XXX01 GDSCascais vs Gipa.dvw` → `xxx01-gdscascais-vs-gipa`).
4. Adds a `matches.json` entry with the placeholder YouTube id `TEMP_YOUTUBE_ID`, runs `publish.py`, then commits only `matches.json`, `scouts` and `docs/data` and pushes to GitHub.

A match with `TEMP_YOUTUBE_ID` is published with statistics and a "YouTube video pending" label. Once the video is uploaded, replace `TEMP_YOUTUBE_ID` with the real 11-character id (and offset if needed), run `python publish.py`, then commit and push.
If DV4 saves the source file again later, the scout copy is refreshed and your YouTube id is kept. Files that were already in the folder when the watcher first ran are ignored (use `--import-existing` on the first run to include them).
If you have uncommitted edits in `matches.json`, `scouts` or `docs/data`, the import happens locally only and you commit it yourself. A failed push (offline) is retried every 5 minutes.

Start automatically at Windows logon (no administrator rights needed), or remove it:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_watcher.ps1
powershell -ExecutionPolicy Bypass -File .\install_watcher.ps1 -Uninstall
```

Run manually with `python watch_scouts.py` (options: `--once`, `--no-push`, `--no-git`, `--quiet-minutes 10`, `--source <folder>`). Activity is logged to `.automation\watcher.log`.

## Timestamp alignment

The example starts with **offsetSeconds = 0**. This assumes the YouTube upload has exactly the same timeline as the DVW's original recording. Verify alignment by watching several known actions, including late in the match.

The mapping is:

```text
YouTube action time = original DVW video time + offsetSeconds
clip start = max(0, YouTube action time - 2)
clip end = clip start + 6 (clamped to the video's end)
```

If YouTube has an extra 10 seconds at the beginning, set `offsetSeconds` to `10`.
If 10 seconds were removed from the original recording's beginning, set it to `-10`.
A single offset cannot fix internal cuts, speed changes or a different recording.
Actions mapped before zero, without usable timing or without an associated video are reported rather than guessed.

## Deploy on GitHub Pages

Create a **separate GitHub repository** for this edition; do not overwrite the DV4-connected project.
Upload this folder including `docs` (the site has already been generated for the supplied example).

In the new repository:

1. Open **Settings > Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select your branch (usually `main`) and **`/docs`**, then Save.

GitHub will display the published URL after deployment.
All site assets use relative paths, including JSON requests, so repository URLs such as `https://owner.github.io/repo/` are supported.
No GitHub Actions workflow, API token, Python runtime on Pages or backend configuration is needed.
Rebuild and push `docs` yourself when changing the match catalogue.

## Features and limitations

- Player/team tables, all sets or individual sets, and raw evaluations for all seven skills.
- Click counts to play matching actions in scout order; Previous, Next, Replay and Back to statistics controls.
- Reception/kill percentages link to successful (numerator) actions; attack efficiency links to all attacks.
- Fixed code-based metrics, not proprietary weighted DV4 player ratings.
- About six seconds per clip; YouTube seeking, ads, buffering and browser autoplay restrictions can interrupt the sequence. Tap Play when requested.
- Embedding must be allowed by the video owner. Private, age/region-restricted, removed or embedding-blocked videos may not play. An external YouTube link is provided, but external playback cannot run the embedded action playlist.
- YouTube is contacted only after a playback action; the player uses YouTube's privacy-enhanced embed domain, but playback may still involve cookies and third-party data processing.
- YouTube ads are not bypassed or downloaded. Clips are playback windows, not exported video files.
- The site does not validate that every recorded code matches the visible action; accuracy depends on the original scouting synchronization and recording.

This is an independent project, not affiliated with Data Project or YouTube. Publish only scouting data and recordings you are authorized to share.

## Tests

```powershell
python -m unittest -q
```

Tests use synthetic fixtures and require no DV4 application or third-party Python packages.

For browser playback regression checks, serve the project root (rather than `docs`) with a local HTTP server and open `browser-tests.html`. These checks mock YouTube; they do not contact it. The test runner is outside `docs`, so it is not deployed to Pages.
