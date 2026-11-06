"use strict";

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function runTests() {
  let assertions = 0;
  const check = (condition, message) => {
    assertions++;
    if (!condition) throw new Error(message);
  };
  const tick = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
  const make = (overrides = {}) => ({ side: "*", player: 17, skill: "A", grade: "#", set: 1, videoIndex: 0, videoSeconds: 20, ...overrides });
  const actions = [make(), make({ grade: "=" }), make({ grade: "/", set: 2 }),
    make({ side: "a" }), make({ player: 4 }), make({ player: null }),
    make({ skill: "S" }), make({ skill: "R", grade: "+" }), make({ skill: "R", grade: "#" })];
  for (const [key, count] of Object.entries({
    points: 2, serve: 1, aces: 1, serveErrors: 0, receptions: 2, receptionErrors: 0,
    positiveReception: 2, perfectReception: 1, attacks: 3, kills: 1, attackErrors: 1,
    blocked: 1, killPercent: 1, attackEfficiency: 3, blockPoints: 0,
  })) check(statisticActions(actions, "*", 17, "all", STAT_ACTIONS[key]).length === count, key);
  check(statisticActions(actions, "*", 17, "2", [["A"]]).length === 1, "Set filter");
  check(statisticActions(actions, "*", null, "all", [["A"]]).length === 1, "Unassigned filter");
  check(statisticActions(actions, "*", undefined, "all", [["A"]]).length === 5, "Team total");
  const videos = [{ id: "7yl0EOYuQ64", offsetSeconds: 5 }, { id: "abcdefghijk", offsetSeconds: -10 }];
  const clip = timedClip(make(), videos);
  check(clip.start === 23 && clip.end === 29 && clip.seconds === 25, "Positive offset");
  check(timedClip(make({ videoIndex: 1 }), videos).start === 8, "Negative offset");
  check(timedClip(make({ videoSeconds: 0 }), [{ ...videos[0], offsetSeconds: 0 }]).start === 0, "Zero timestamp");
  for (const action of [make({ videoSeconds: null }), make({ videoSeconds: -1 }), make({ videoSeconds: NaN }),
    make({ videoIndex: 99 }), make({ videoIndex: null }), make({ videoIndex: 1, videoSeconds: 5 })]) {
    check(timedClip(action, videos) === null, "Invalid or missing reference must not be guessed");
  }
  const originalYT = window.YT;
  let fake = null;
  let delayedReady = null;
  let delayReady = false;
  class FakePlayer {
    constructor(element, options) {
      fake = this;
      this.events = options.events;
      this.time = 0;
      this.duration = 100;
      this.state = -1;
      this.id = "";
      this.loads = [];
      this.destroyed = false;
      if (delayReady) delayedReady = () => options.events.onReady({ target: this });
      else queueMicrotask(() => options.events.onReady({ target: this }));
    }
    loadVideoById(parameters) {
      this.loads.push(parameters);
      this.id = parameters.videoId;
      this.time = parameters.startSeconds;
      this.state = 1;
      this.events.onStateChange({ data: 1 });
    }
    cueVideoById(parameters) { this.id = parameters.videoId; this.time = 0; this.state = 5; }
    pauseVideo() { this.state = 2; }
    getCurrentTime() { return this.time; }
    getDuration() { return this.duration; }
    getVideoData() { return { video_id: this.id }; }
    getPlayerState() { return this.state; }
    destroy() { this.destroyed = true; this.state = 2; }
    ended() {
      this.time = this.loads.at(-1).endSeconds;
      this.state = 0;
      this.events.onStateChange({ data: 0 });
    }
  }
  window.YT = { Player: FakePlayer };
  const host = node("div");
  document.body.append(host);
  const playback = youtubePlayback({ videos });
  host.append(playback.element);
  const message = () => host.querySelector(".playback > p").textContent;
  let second = null;
  try {
    playback.showActions([make(), make({ videoSeconds: 40 }), make({ videoIndex: 1, videoSeconds: 60 })], "Attacks");
    await tick();
    check(fake.loads[0].startSeconds === 23 && fake.loads[0].endSeconds === 29, "First clip bounds");
    check(host.querySelectorAll(".clip-list button").length === 3, "Queue count");
    fake.ended();
    await tick();
    check(fake.loads.at(-1).startSeconds === 43 && fake.state === 1, "Automatic next clip");
    fake.ended();
    await tick();
    check(fake.id === "abcdefghijk" && fake.time === 48, "Multi-video reference");
    fake.ended();
    await tick();
    check(fake.state === 2 && message().includes("Playlist finished: 3"), "Last clip stops");
    const buttons = host.querySelectorAll(".clip-controls button");
    buttons[1].click();
    await tick();
    check(fake.state === 1 && fake.time === 48, "Replay");
    buttons[0].click();
    await tick();
    check(fake.id === "7yl0EOYuQ64" && fake.time === 43, "Previous");
    playback.reset();
    check(fake.state === 2 && host.querySelector(".action-playlist").hidden, "Reset stops playback");
    playback.showActions([make({ videoSeconds: 110 })], "Out of range");
    await tick();
    check(message().includes("outside the YouTube recording"), "Duration validation");
    playback.showActions([make({ videoSeconds: null })], "Missing");
    check(message().includes("No playable clips"), "Missing time error");
    playback.showActions([make()], "Autoplay");
    await tick();
    fake.events.onAutoplayBlocked();
    check(message().includes("blocked autoplay"), "Autoplay explanation");
    fake.events.onError({ data: 150 });
    check(fake.state === 2 && message().includes("does not allow embedded playback"), "Embedding error");
    playback.showActions([make()], "Rapid old selection");
    playback.showActions([make({ videoSeconds: 70 })], "Rapid new selection");
    await tick();
    check(fake.loads.at(-1).startSeconds === 73, "Late async selection cannot replace new clip");
    playback.dispose();
    check(fake.destroyed, "Destroy player");
    delayReady = true;
    second = youtubePlayback({ videos });
    host.append(second.element);
    second.showActions([make()], "First while initializing");
    await tick();
    const pending = fake;
    second.showActions([make({ videoSeconds: 80 })], "Second while initializing");
    await tick();
    check(pending.loads.length === 0, "Wait for ready before playing");
    delayedReady();
    await tick();
    check(pending.loads.length === 1 && pending.loads[0].startSeconds === 83, "Only latest selection after ready");
    second.dispose();
    check(pending.destroyed, "Pending player is cleaned up");
  } finally {
    playback.dispose();
    second?.dispose();
    host.remove();
    window.YT = originalYT;
  }
  return { assertions, result: "passed" };
}

runTests().then(result => {
  document.getElementById("result").textContent = JSON.stringify(result);
  document.body.dataset.result = "passed";
}).catch(error => {
  document.getElementById("result").textContent = error.stack;
  document.body.dataset.result = "failed";
});
