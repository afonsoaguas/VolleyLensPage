"use strict";

const SKILL_NAMES = { S: "Serve", R: "Reception", A: "Attack", B: "Block", D: "Dig", E: "Set", F: "Freeball" };
const STAT_ACTIONS = {
  points: [["S", "#"], ["A", "#"], ["B", "#"]],
  serve: [["S"]], aces: [["S", "#"]], serveErrors: [["S", "="]],
  receptions: [["R"]], receptionErrors: [["R", "="]],
  positiveReception: [["R", "+#"]], perfectReception: [["R", "#"]],
  attacks: [["A"]], kills: [["A", "#"]], attackErrors: [["A", "="]], blocked: [["A", "/"]],
  killPercent: [["A", "#"]], attackEfficiency: [["A"]], blockPoints: [["B", "#"]],
};

function statisticActions(actions, side, player, set, rules) {
  return actions.filter(action => action.side === side
    && (player === undefined || action.player === player)
    && (set === "all" || action.set === Number(set))
    && rules.some(([skill, grades]) => action.skill === skill && (!grades || grades.includes(action.grade))));
}

function timedClip(action, videos) {
  if (!Number.isInteger(action.videoIndex) || !Number.isFinite(action.videoSeconds)) return null;
  const video = videos[action.videoIndex];
  if (!video) return null;
  const seconds = action.videoSeconds + video.offsetSeconds;
  if (action.videoSeconds < 0 || !Number.isFinite(seconds) || seconds < 0) return null;
  const start = Math.max(0, seconds - 2);
  return { action, videoId: video.id, seconds, start, end: start + 6 };
}

let youtubeAPI = null;
function loadYouTubeAPI() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (youtubeAPI) return youtubeAPI;
  youtubeAPI = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    const fail = message => {
      clearTimeout(timer);
      youtubeAPI = null;
      script.remove();
      reject(new Error(message));
    };
    const timer = setTimeout(() => fail("YouTube could not load. Check your connection or content blocker, then try Load YouTube again."), 20000);
    window.onYouTubeIframeAPIReady = () => { clearTimeout(timer); resolve(window.YT); };
    script.src = "https://www.youtube.com/iframe_api";
    script.onerror = () => fail("YouTube is blocked or unreachable. Statistics remain available; try loading video again.");
    document.head.append(script);
  });
  return youtubeAPI;
}

function youtubePlayback(item) {
  const section = node("section", undefined, "playback");
  section.append(node("h3", "YouTube / action clips"));
  const choice = node("select");
  const label = node("label", "Associated YouTube video");
  label.htmlFor = "video-choice";
  choice.id = label.htmlFor;
  item.videos.forEach((video, index) => {
    const option = node("option", `Video ${index + 1} (${video.offsetSeconds >= 0 ? "+" : ""}${video.offsetSeconds}s offset)`);
    option.value = String(index);
    choice.append(option);
  });
  const watch = node("button", "Load YouTube");
  watch.type = "button";
  watch.disabled = item.videos.length === 0;
  const mount = node("div", undefined, "youtube-mount");
  mount.hidden = true;
  const message = node("p", item.videos.length
    ? "Load YouTube to watch the match, or click a statistic to start an action playlist."
    : "No YouTube video is configured for this match. Statistics are still available.", "muted");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  const external = node("a", "Open selected video on YouTube", "external-video");
  external.target = "_blank";
  external.rel = "noopener noreferrer";
  external.hidden = !item.videos.length;
  const playlist = node("div", undefined, "action-playlist");
  playlist.hidden = true;
  const title = node("h4");
  title.tabIndex = -1;
  const description = node("p", undefined, "muted");
  const controls = node("div", undefined, "clip-controls");
  const previous = node("button", "Previous clip", "secondary");
  const replay = node("button", "Replay clip", "secondary");
  const next = node("button", "Next clip", "secondary");
  const back = node("button", "Back to statistics", "secondary");
  for (const button of [previous, replay, next, back]) {
    button.type = "button";
    controls.append(button);
  }
  const list = node("ol", undefined, "clip-list");
  playlist.append(title, description, controls, list);
  section.append(label, choice, watch, mount, message, external, playlist);
  let player = null;
  let initializing = null;
  let cancelInitialization = null;
  let disposed = false;
  let serial = 0;
  let timer = null;
  let active = null;
  let queue = [];
  let position = -1;
  let returnTarget = null;
  let fullMode = true;

  const report = (text, error = false) => {
    if (disposed) return;
    message.textContent = text;
    message.classList.toggle("error", error);
  };
  const link = (id, seconds = 0) => {
    external.href = `https://www.youtube.com/watch?v=${encodeURIComponent(id)}&t=${Math.floor(seconds)}s`;
  };
  if (item.videos.length) link(item.videos[0].id);
  const pause = () => {
    clearInterval(timer);
    timer = null;
    active = null;
    if (player?.pauseVideo) player.pauseVideo();
  };
  const cancel = () => { serial++; pause(); watch.disabled = !item.videos.length; };
  const update = () => {
    previous.disabled = position <= 0;
    next.disabled = position < 0 || position >= queue.length - 1;
    replay.disabled = position < 0;
    [...list.children].forEach((entry, index) => entry.firstChild.setAttribute("aria-current", index === position ? "true" : "false"));
  };
  const finish = () => {
    if (!active) return;
    pause();
    if (position + 1 < queue.length) void run(position + 1);
    else report(`Playlist finished: ${queue.length} clips. Replay a clip or return to statistics.`);
  };
  const boundary = () => {
    if (disposed || !active || !player?.getCurrentTime) return;
    if (player.getVideoData().video_id !== active.videoId) return;
    const duration = player.getDuration();
    if (duration > 0) {
      if (active.seconds >= duration) {
        pause();
        report("This timestamp is outside the YouTube recording. Check offsetSeconds or use the same untrimmed video as the scout.", true);
        return;
      }
      active.end = Math.min(active.end, duration);
    }
    const time = player.getCurrentTime();
    if (player.getPlayerState() === 1 && time >= active.end) finish();
  };
  const initialize = async () => {
    if (initializing) return initializing;
    if (player?.getPlayerState) return player;
    initializing = (async () => {
      await loadYouTubeAPI();
      if (disposed) return null;
      mount.hidden = false;
      const element = node("div");
      mount.replaceChildren(element);
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          cancelInitialization = null;
          initializing = null;
          player?.destroy();
          player = null;
          reject(new Error("YouTube player initialization timed out. Check content blocking or embedding restrictions, then retry."));
        }, 20000);
        cancelInitialization = () => {
          clearTimeout(timeout);
          cancelInitialization = null;
          reject(new Error("YouTube player was closed before initialization finished."));
        };
        player = new YT.Player(element, {
          host: "https://www.youtube-nocookie.com",
          width: "100%", height: "100%",
          playerVars: { playsinline: 1, origin: location.origin, rel: 0 },
          events: {
            onReady: event => { clearTimeout(timeout); cancelInitialization = null; resolve(event.target); },
            onError: event => {
              const errors = {
                2: "YouTube rejected the video ID or playback parameters.",
                5: "This YouTube video cannot play in this browser.",
                100: "This YouTube video is unavailable, deleted or private.",
                101: "The video owner does not allow embedded playback.",
                150: "The video owner does not allow embedded playback.",
                153: "YouTube requires valid site identification. Open this site using HTTP/HTTPS, not as a local file.",
              };
              pause();
              report(`${errors[event.data] || `YouTube playback error ${event.data}.`} Use the YouTube link below to watch externally; embedded action playlists cannot run while this error persists.`, true);
            },
            onAutoplayBlocked: () => report("The clip is ready, but your browser blocked autoplay. Tap Play in the YouTube player; the playlist will continue afterwards."),
            onStateChange: event => {
              if (disposed || fullMode || !queue.length) return;
              if (event.data === 1 && !active) { void run(position); return; }
              boundary();
              if (event.data === 0 && active && player.getVideoData().video_id === active.videoId
                  && player.getCurrentTime() >= active.end - 0.5) finish();
            },
          },
        });
      });
    })();
    try { return await initializing; }
    catch (error) { initializing = null; throw error; }
  };
  const run = async (index, full = false) => {
    if (disposed || (!full && !queue[index])) return;
    cancel();
    const request = serial;
    fullMode = full;
    if (!full) position = index;
    update();
    watch.disabled = true;
    report("Loading YouTube...");
    try {
      const current = await initialize();
      if (disposed || request !== serial || !current) return;
      if (full) {
        const video = item.videos[Number(choice.value)];
        link(video.id);
        current.cueVideoById({ videoId: video.id, startSeconds: 0 });
        report("Full match ready. Press Play in the YouTube player.");
        return;
      }
      const clip = queue[position];
      choice.value = String(clip.action.videoIndex);
      link(clip.videoId, clip.start);
      active = { ...clip };
      report(`Clip ${position + 1} of ${queue.length} | Set ${clip.action.set} | ${SKILL_NAMES[clip.action.skill]} ${clip.action.grade} | ${formatTime(clip.start)} - ${formatTime(clip.end)}. Tap Play if needed.`);
      timer = setInterval(boundary, 100);
      current.loadVideoById({ videoId: clip.videoId, startSeconds: clip.start, endSeconds: clip.end });
    } catch (error) {
      if (!disposed && request === serial) { pause(); report(error.message, true); }
    } finally {
      if (!disposed && request === serial) watch.disabled = !item.videos.length;
    }
  };
  const reset = () => {
    cancel();
    fullMode = true;
    queue = [];
    position = -1;
    playlist.hidden = true;
    list.replaceChildren();
    update();
  };
  watch.addEventListener("click", () => { reset(); void run(0, true); });
  choice.addEventListener("change", () => { reset(); void run(0, true); });
  previous.addEventListener("click", () => { void run(position - 1); });
  replay.addEventListener("click", () => { void run(position); });
  next.addEventListener("click", () => { void run(position + 1); });
  back.addEventListener("click", () => {
    cancel();
    const target = returnTarget?.isConnected ? returnTarget : document.querySelector(".statistics h3");
    target?.scrollIntoView({ block: "center" });
    target?.focus({ preventScroll: true });
    report("Playlist paused. Select another statistic or replay a clip.");
  });
  update();
  return {
    element: section,
    reset,
    showActions(actions, heading, target) {
      reset();
      returnTarget = target;
      fullMode = false;
      playlist.hidden = false;
      title.textContent = heading;
      queue = actions.map(action => timedClip(action, item.videos)).filter(Boolean);
      const missing = actions.length - queue.length;
      description.textContent = `${actions.length} matching actions; ${queue.length} timed clips. About 6 seconds per action, starting 2 seconds before its timestamp (plus configured offset).${missing ? ` ${missing} actions have missing video/timing or fall before the YouTube video starts.` : ""} No new video files are created.`;
      queue.forEach((clip, index) => {
        const entry = node("li");
        const action = clip.action;
        const button = node("button", `${index + 1}. Set ${action.set} | ${action.player === null ? "Unassigned" : "#" + action.player} ${SKILL_NAMES[action.skill]} ${action.grade} | ${formatTime(clip.seconds)}`, "secondary");
        button.type = "button";
        button.addEventListener("click", () => { void run(index); });
        entry.append(button);
        list.append(entry);
      });
      section.scrollIntoView({ block: "start" });
      title.focus({ preventScroll: true });
      if (queue.length) void run(0);
      else report("No playable clips for this selection. Check the match's YouTube mapping, offset and scouting timestamps.", true);
    },
    dispose() {
      disposed = true;
      reset();
      cancelInitialization?.();
      player?.destroy();
      player = null;
    },
  };
}

function formatTime(seconds) {
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
