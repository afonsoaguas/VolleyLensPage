"use strict";
const $ = id => document.getElementById(id);
let catalogue = [];
let currentPlayback = null;
let generation = 0;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function status(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}

async function readJSON(path) {
  const response = await fetch(new URL(path, document.baseURI));
  if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status}). Publish the match data and reload.`);
  try { return await response.json(); }
  catch { throw new Error(`${path} is not valid JSON. Run publish.py again before deploying.`); }
}

function renderLibrary() {
  const query = $("search").value.trim().toLocaleLowerCase();
  const items = catalogue.filter(item => [item.home, item.away, item.date, item.competition].join(" ").toLocaleLowerCase().includes(query));
  $("result-count").textContent = `${items.length} of ${catalogue.length} matches`;
  $("cards").replaceChildren();
  for (const item of items) {
    const card = node("article", undefined, "card");
    card.append(node("div", item.competition || "Match", "eyebrow"), node("p", item.date || "Date not supplied", "muted"));
    const teams = node("div", undefined, "teams");
    teams.append(node("h3", item.home), node("div", item.score || "-", "score"), node("h3", item.away));
    const badges = node("div", undefined, "badges");
    badges.append(node("span", "Published scouting", "badge"), node("span", `${item.videos.length} YouTube video(s)`, "badge"));
    const open = node("button", "Statistics & video");
    open.type = "button";
    open.addEventListener("click", () => { void openMatch(item); });
    card.append(teams, badges, open);
    $("cards").append(card);
  }
  if (!items.length) $("cards").append(node("p", "No matches found.", "empty"));
}

async function openMatch(item) {
  const request = ++generation;
  currentPlayback?.dispose();
  currentPlayback = null;
  $("match-content").replaceChildren();
  $("library").hidden = true;
  $("match").hidden = false;
  $("match-title").textContent = `${item.home} vs ${item.away}`;
  $("match-info").textContent = [item.date, item.competition, item.score].filter(Boolean).join(" / ");
  status("Loading published statistics...");
  try {
    const data = await readJSON(item.data);
    if (request !== generation) return;
    if (data.match?.id !== item.id || !Array.isArray(data.actions) || !Array.isArray(data.all?.teams) || !Array.isArray(data.sets)) {
      throw new Error("Published match data is incompatible. Run publish.py and redeploy.");
    }
    currentPlayback = youtubePlayback(item);
    $("match-content").append(currentPlayback.element, statisticsPanel(data, currentPlayback));
    status("Statistics loaded. Click a statistic to watch its actions on YouTube.");
    $("match-title").scrollIntoView({ block: "start" });
  } catch (error) {
    if (request === generation) status(error.message, true);
  }
}

const STAT_COLUMNS = [
  ["points", "Points", "Aces + attack kills + block points"],
  ["serve", "Srv", "Serve attempts"], ["aces", "Ace", "Serves graded #"], ["serveErrors", "SE", "Serves graded ="],
  ["receptions", "Rec", "Reception attempts"], ["receptionErrors", "RE", "Receptions graded ="],
  ["positiveReception", "Rec+%", "(Reception + and #) / all receptions", true],
  ["perfectReception", "Rec#%", "Reception # / all receptions", true],
  ["attacks", "Att", "Attack attempts"], ["kills", "Kill", "Attacks graded #"],
  ["attackErrors", "AE", "Attacks graded ="], ["blocked", "Blk", "Attacks graded /"],
  ["killPercent", "Kill%", "Attack kills / attack attempts", true],
  ["attackEfficiency", "Eff%", "(Kills - attack errors - blocked attacks) / attack attempts", true],
  ["blockPoints", "BP", "Blocks graded #"],
];

function statisticsPanel(data, playback) {
  const section = node("section", undefined, "statistics");
  const heading = node("h3", "Match statistics");
  heading.tabIndex = -1;
  section.append(heading, node("p", "Click a statistic to watch matching actions. Counts follow the selected team, player and set. Reception/kill percentages link to successful actions; efficiency links to all attacks.", "muted"));
  const controls = node("div", undefined, "stats-controls");
  const setLabel = node("label", "Set");
  const set = node("select");
  set.id = "stats-set";
  setLabel.htmlFor = set.id;
  const teamLabel = node("label", "Team");
  const teamSelect = node("select");
  teamSelect.id = "stats-team";
  teamLabel.htmlFor = teamSelect.id;
  const option = (select, value, text) => {
    const element = node("option", text);
    element.value = value;
    select.append(element);
  };
  option(set, "all", "All sets");
  for (const entry of data.sets) {
    const score = data.scores.find(score => score.number === entry.number);
    option(set, String(entry.number), `Set ${entry.number}${score ? ` (${score.home} - ${score.away})` : ""}`);
  }
  option(teamSelect, "both", "Both teams");
  for (const team of data.all.teams) option(teamSelect, team.side, team.name);
  setLabel.append(set);
  teamLabel.append(teamSelect);
  controls.append(setLabel, teamLabel);
  const output = node("div", undefined, "stats-output");
  const cell = (text, rules, team, player, label, key) => {
    const element = node("td");
    const actions = statisticActions(data.actions, team.side, player?.number, set.value, rules);
    if (!data.match.videos.length || !actions.length) { element.textContent = text; return element; }
    const person = player ? `${player.number === null ? "Unassigned" : "#" + player.number} ${player.name}` : "Team total";
    const title = `${team.name} / ${person} / ${label} / ${set.value === "all" ? "All sets" : "Set " + set.value}`;
    const link = node("button", text, "stat-link");
    link.type = "button";
    link.dataset.stat = key;
    link.dataset.player = player ? String(player.number) : "team";
    link.dataset.side = team.side;
    link.title = `${actions.length} matching actions`;
    link.setAttribute("aria-label", `${title}: ${text}. Watch ${actions.length} actions`);
    link.addEventListener("click", () => playback.showActions(actions, title, link));
    element.append(link);
    return element;
  };
  const draw = () => {
    playback.reset();
    output.replaceChildren();
    const current = set.value === "all" ? data.all : data.sets.find(entry => entry.number === Number(set.value));
    output.append(node("p", `${current.actionCount} evaluated skill actions from the published scout.`, "muted"));
    for (const warning of data.warnings) output.append(node("p", warning, "stats-warning"));
    for (const team of current.teams.filter(team => teamSelect.value === "both" || team.side === teamSelect.value)) {
      const wrapper = node("div", undefined, "stats-table-wrap");
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", `${team.name} statistics; scroll horizontally for more columns`);
      const table = node("table", undefined, "stats-table");
      table.append(node("caption", `${team.name} / ${set.value === "all" ? "All sets" : "Set " + set.value}`));
      const head = node("thead");
      const headings = node("tr");
      for (const [label, description] of [["#", "Jersey"], ["Player", "Player"], ...STAT_COLUMNS.map(column => [column[1], column[2]])]) {
        const th = node("th", label);
        th.scope = "col";
        th.title = description;
        headings.append(th);
      }
      head.append(headings);
      table.append(head);
      const row = (player, total = false) => {
        const tr = node("tr", undefined, total ? "team-total" : "");
        tr.append(node("td", total ? "" : player.number === null ? "-" : String(player.number)));
        const name = node("th", total ? "Team total" : `${player.name}${player.libero ? " (L)" : ""}`);
        name.scope = "row";
        tr.append(name);
        for (const [key, label, , percent] of STAT_COLUMNS) {
          const value = player[key];
          tr.append(cell(value === null ? "-" : percent ? `${value.toFixed(1)}%` : String(value), STAT_ACTIONS[key], team, total ? undefined : player, label, key));
        }
        return tr;
      };
      const body = node("tbody");
      for (const player of team.players) body.append(row(player));
      const foot = node("tfoot");
      foot.append(row(team.totals, true));
      table.append(body, foot);
      wrapper.append(table);
      output.append(wrapper);
      const raw = node("details", undefined, "skill-grades");
      raw.append(node("summary", `${team.name}: all skill evaluations`));
      const grades = node("table", undefined, "stats-table");
      const gradeHead = node("thead");
      const labels = node("tr");
      for (const label of ["Skill", "Total", "=", "/", "-", "!", "+", "#"]) {
        const th = node("th", label);
        th.scope = "col";
        labels.append(th);
      }
      gradeHead.append(labels);
      const gradeBody = node("tbody");
      for (const [code, name] of Object.entries(SKILL_NAMES)) {
        const values = team.totals.skills[code];
        const tr = node("tr");
        const label = node("th", name);
        label.scope = "row";
        tr.append(label, cell(String(values.total), [[code]], team, undefined, name, `${code}.total`));
        for (const grade of ["=", "/", "-", "!", "+", "#"]) {
          tr.append(cell(String(values.grades[grade]), [[code, grade]], team, undefined, `${name} ${grade}`, `${code}.${grade}`));
        }
        gradeBody.append(tr);
      }
      grades.append(gradeHead, gradeBody);
      const gradeWrap = node("div", undefined, "stats-table-wrap");
      gradeWrap.append(grades);
      raw.append(gradeWrap);
      output.append(raw);
    }
    const formulas = node("details", undefined, "stat-formulas");
    formulas.append(node("summary", "Definitions and limitations"));
    for (const [, label, definition] of STAT_COLUMNS) formulas.append(node("p", `${label}: ${definition}.`));
    formulas.append(node("p", `A dash means no attempts. Fixed code-based metrics; custom weighted ratings are not applied. Points exclude opponent errors. ${data.auxiliaryRecords} auxiliary & records are excluded to avoid counting the same point twice. No video or skill data is reconstructed from missing records.`));
    output.append(formulas);
  };
  set.addEventListener("change", draw);
  teamSelect.addEventListener("change", draw);
  section.append(controls, output);
  draw();
  return section;
}

$("search").addEventListener("input", renderLibrary);
$("back-library").addEventListener("click", () => {
  generation++;
  currentPlayback?.dispose();
  currentPlayback = null;
  $("match-content").replaceChildren();
  $("match").hidden = true;
  $("library").hidden = false;
  status("Select a published match.");
  $("cards").querySelector("button")?.focus();
});

(async () => {
  if (location.protocol === "file:") {
    status("Open this site through GitHub Pages or a local HTTP preview, not by double-clicking index.html.", true);
    return;
  }
  try {
    const library = await readJSON("data/library.json");
    if (library.version !== 1 || !Array.isArray(library.matches)) throw new Error("Unsupported catalogue. Run publish.py and redeploy.");
    catalogue = library.matches;
    renderLibrary();
    status("Select a published match. No connection to DV4 is required.");
  } catch (error) { status(error.message, true); }
})();
