import { test } from "node:test";
import assert from "node:assert/strict";
import { BoardStore } from "./store.js";

const A = "00000000-0000-0000-0000-00000000000a";
const B = "00000000-0000-0000-0000-00000000000b";

function rect(id, extra) {
  return {
    op: "add",
    id,
    type: "rect",
    data: { x: 0, y: 0, width: 10, height: 10, fill: "#abc", ...(extra || {}) },
  };
}

test("applyRemote skips a bad op and still applies the rest", () => {
  const store = new BoardStore();
  store.applyOps([rect(A)]);
  const events = [];
  store.subscribe((ops) => events.push(ops));
  const applied = store.applyRemote([
    { op: "patch", id: "missing", patch: { x: 9 } },
    { op: "patch", id: A, patch: { x: 4 } },
    { op: "nope" },
    { op: "add", id: B, type: "rect", data: { x: 1, y: 1, width: 2, height: 2 } },
  ]);
  assert.equal(applied.length, 2);
  assert.equal(store.get(A).data.x, 4);
  assert.equal(store.get(B).type, "rect");
  assert.equal(events.length, 1);
  assert.equal(events[0].length, 2);
});

test("reset replaces the document and notifies once", () => {
  const store = new BoardStore();
  store.applyOps([rect(A), rect(B)]);
  const events = [];
  store.subscribe((ops) => events.push(ops));
  store.reset([
    {
      id: A,
      type: "rect",
      z: 3,
      data: { x: 8, y: 9, width: 5, height: 5, fill: "#000" },
      updated_at: "ignore-me",
    },
  ]);
  assert.equal(store.snapshot().length, 1);
  assert.equal(store.get(A).data.x, 8);
  assert.equal(store.get(A).z, 3);
  assert.equal(store.get(B), null);
  assert.deepEqual(events, [[{ op: "reset" }]]);
});

test("setZ updates z without adding a new object", () => {
  const store = new BoardStore();
  store.applyOps([rect(A)]);
  store.setZ(A, 7);
  assert.equal(store.get(A).z, 7);
});
