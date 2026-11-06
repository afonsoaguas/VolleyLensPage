"""Fixed, code-based statistics; no proprietary player rating or custom weights."""

import re
import math
from collections import Counter

class ScoutError(ValueError):
    """Readable scouting data could not be interpreted."""


GRADES = "=/-!+#"
SKILLS = {"S": "Serve", "R": "Reception", "A": "Attack", "B": "Block",
          "D": "Dig", "E": "Set", "F": "Freeball"}
ACTION = re.compile(r"^([*a])(\d{2}|\$\$)([SRABDEF])([A-Z])([=/!+#-])")


def display_text(value):
    if value.startswith("\x0f2"):
        try:
            raw = bytes.fromhex(value[2:])
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                value = raw.decode("cp1252")
        except (ValueError, UnicodeDecodeError) as error:
            raise ScoutError("An encoded name in the scout is malformed.") from error
    return "".join(character for character in value if character.isprintable()).strip()


def parse_scout(text):
    sections = {}
    name = None
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            name = line
            sections[name] = []
        elif name and line:
            sections[name].append(line)
    if not all(key in sections for key in ("[3DATAVOLLEYSCOUT]", "[3TEAMS]", "[3SCOUT]")):
        raise ScoutError("Scout is missing its header, teams or action section.")
    team_lines = sections["[3TEAMS]"]
    if len(team_lines) != 2:
        raise ScoutError("Scout does not contain two team definitions.")
    teams = []
    for side, index, section in (("*", 0, "[3PLAYERS-H]"), ("a", 1, "[3PLAYERS-V]")):
        fields = team_lines[index].split(";")
        if len(fields) < 3:
            raise ScoutError("A scout team definition is incomplete.")
        team_name = display_text(fields[6] if len(fields) > 6 and fields[6] else fields[1])
        players = {}
        for line in sections.get(section, []):
            values = line.split(";")
            if len(values) < 11 or not values[1].isdigit():
                raise ScoutError("A player roster entry is incomplete.")
            number = int(values[1])
            if number in players:
                raise ScoutError("A roster contains duplicate jersey numbers.")
            surname = display_text(values[17] if len(values) > 17 and values[17] else values[9])
            first = display_text(values[18] if len(values) > 18 and values[18] else values[10])
            players[number] = {"number": number, "name": f"{first} {surname}".strip() or display_text(values[8]),
                               "libero": len(values) > 12 and values[12] == "L"}
        teams.append({"side": side, "name": team_name, "players": players})
    set_scores = []
    for index, line in enumerate(sections.get("[3SET]", []), 1):
        values = line.split(";")
        score = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", values[4]) if len(values) > 4 else None
        if score:
            set_scores.append({"number": index, "home": int(score[1]), "away": int(score[2])})
    actions = []
    skipped = 0
    auxiliary = 0
    unassigned = 0
    for line in sections["[3SCOUT]"]:
        values = line.split(";")
        code = values[0]
        if re.match(r"^[*a](?:\d{2}|\$\$)&", code):
            auxiliary += 1
            continue
        match = ACTION.match(code)
        if not match:
            if re.match(r"^[*a](?:\d{2}|\$\$)", code):
                skipped += 1
            continue
        if len(values) <= 8 or not re.fullmatch(r"[1-5]", values[8]):
            skipped += 1
            continue
        side, number, skill, _, grade = match.groups()
        player_number = None if number == "$$" else int(number)
        if player_number is None:
            unassigned += 1
        video_index = None
        video_seconds = None
        if len(values) > 12 and re.fullmatch(r"[1-9]\d*", values[11]):
            video_index = int(values[11]) - 1
            try:
                seconds = float(values[12])
                if math.isfinite(seconds) and seconds >= 0:
                    video_seconds = seconds
            except ValueError:
                pass  # Missing timing is reported below, without dropping the skill.
        actions.append({"side": side, "player": player_number, "skill": skill, "grade": grade,
                        "set": int(values[8]), "videoIndex": video_index, "videoSeconds": video_seconds})
    if not actions:
        if any(line.startswith(">VIDEO;") for line in sections["[3SCOUT]"]):
            raise ScoutError("This entry contains video clips but no evaluated scouting actions. Video playback is still available; player statistics cannot be calculated from video alone.")
        raise ScoutError("No supported evaluated actions were found in this scout; statistics cannot be calculated.")
    return {"teams": teams, "actions": actions, "scores": set_scores,
            "skipped": skipped, "auxiliary": auxiliary, "unassigned": unassigned}


def metrics(counts):
    def count(skill, grade):
        return counts[(skill, grade)]

    def total(skill):
        return sum(count(skill, grade) for grade in GRADES)

    def percent(numerator, denominator):
        return round(numerator * 100 / denominator, 1) if denominator else None

    kills, attack_errors, blocked = count("A", "#"), count("A", "="), count("A", "/")
    return {
        "points": count("S", "#") + kills + count("B", "#"),
        "serve": total("S"), "aces": count("S", "#"), "serveErrors": count("S", "="),
        "receptions": total("R"), "receptionErrors": count("R", "="),
        "positiveReception": percent(count("R", "+") + count("R", "#"), total("R")),
        "perfectReception": percent(count("R", "#"), total("R")),
        "attacks": total("A"), "kills": kills, "attackErrors": attack_errors, "blocked": blocked,
        "killPercent": percent(kills, total("A")),
        "attackEfficiency": percent(kills - attack_errors - blocked, total("A")),
        "blockPoints": count("B", "#"),
        "skills": {skill: {"total": total(skill), "grades": {grade: count(skill, grade) for grade in GRADES}}
                   for skill in SKILLS},
    }


def summarize(scout, selected_set=None):
    actions = [action for action in scout["actions"] if selected_set is None or action["set"] == selected_set]
    teams = []
    for team in scout["teams"]:
        team_actions = [action for action in actions if action["side"] == team["side"]]
        counts = Counter((action["skill"], action["grade"]) for action in team_actions)
        players = dict(team["players"])
        for action in team_actions:
            number = action["player"]
            if number not in players:
                players[number] = {"number": number, "name": "Unassigned" if number is None else "Not in roster", "libero": False}
        rows = []
        for number in sorted(players, key=lambda value: (value is None, value if value is not None else 0)):
            player_counts = Counter((action["skill"], action["grade"]) for action in team_actions if action["player"] == number)
            rows.append({**players[number], **metrics(player_counts)})
        teams.append({"name": team["name"], "side": team["side"], "totals": metrics(counts), "players": rows})
    return {"teams": teams, "actionCount": len(actions)}


def statistics(text):
    scout = parse_scout(text)
    sets = sorted({action["set"] for action in scout["actions"]} | {score["number"] for score in scout["scores"]})
    warnings = []
    if scout["skipped"]:
        warnings.append(f"{scout['skipped']} unsupported or malformed action records were excluded. These totals may be incomplete.")
    if scout["unassigned"]:
        warnings.append(f"{scout['unassigned']} evaluated actions have no jersey number; they are included in an Unassigned row.")
    untimed = sum(action["videoIndex"] is None or action["videoSeconds"] is None for action in scout["actions"])
    if untimed:
        warnings.append(f"{untimed} evaluated actions lack usable video references or timestamps. They remain in the statistics but cannot be played as clips.")
    for team in scout["teams"]:
        unknown = {action["player"] for action in scout["actions"] if action["side"] == team["side"]
                   and action["player"] is not None and action["player"] not in team["players"]}
        if unknown:
            warnings.append(f"{team['name']}: actions reference jerseys not in the roster: {', '.join(map(str, sorted(unknown)))}.")
    return {
        "all": summarize(scout), "sets": [{"number": number, **summarize(scout, number)} for number in sets],
        "scores": scout["scores"], "warnings": warnings,
        "auxiliaryRecords": scout["auxiliary"],
        "actions": scout["actions"],
        "retrievedAt": None,
    }
