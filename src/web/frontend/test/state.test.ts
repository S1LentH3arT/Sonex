import assert from "node:assert/strict";
import test from "node:test";
import { initialState, reduce, position } from "../src/state";

test("events from a running session never enter the history being viewed", () => {
  const state = { ...initialState, activeId: "a", viewedId: "b" };
  const next = reduce(state, {
    type: "chat",
    session_id: "a",
    role: "agent",
    text: "answer",
  });
  assert.equal(next.viewedId, "b");
  assert.equal(next.messages.a[0].content, "answer");
  assert.equal(next.messages.b, undefined);
});

test("late history responses do not switch the currently selected conversation", () => {
  let state = reduce(initialState, { type: "view", id: "newer" });
  state = reduce(state, {
    type: "web_history",
    viewed_session_id: "older",
    messages: [],
  });
  assert.equal(state.viewedId, "newer");
});

test("a stale turn completion cannot unlock a newer task", () => {
  let state = reduce(initialState, {
    type: "agent_working_state",
    session_id: "a",
    turn_id: "new",
    active: true,
  });
  state = reduce(state, {
    type: "agent_working_state",
    turn_id: "old",
    active: false,
  });
  assert.equal(state.working?.turnId, "new");
});

test("session changes preserve global playback and queue references", () => {
  const queue = [{ entry_id: "one", title: "Track" }];
  const state = reduce(
    { ...initialState, queue },
    {
      type: "web_snapshot",
      session_id: "b",
      messages: [],
      sessions: [],
      user: "me",
      home: "/home/me/.sonex",
      protocol_version: 1,
    },
  );
  assert.equal(state.queue, queue);
});

test("playback interpolation freezes during buffering and stays within duration", () => {
  const player = {
    name: "a",
    artist: "b",
    album: "c",
    duration_ms: 5000,
    progress_ms: 3000,
    timestamp: 1000,
    is_playing: true,
  };
  assert.equal(position(player, 9000), 5000);
  assert.equal(position({ ...player, paused_for_cache: true }, 9000), 3000);
  assert.equal(position({ ...player, progress_sync_lost: true }, 9000), 3000);
  assert.equal(position({ ...player, progress_anchor_ms: 8000 }, 9000), 4000);
});

test("a late cover image cannot replace the current track artwork", () => {
  const state = reduce(initialState, { type: "cover", url: "new-cover" });
  const next = reduce(state, {
    type: "cover_image",
    source_url: "old-cover",
    data: "old",
    format: "png",
    width: 1,
    height: 1,
  });
  assert.equal(next.cover, null);
});
