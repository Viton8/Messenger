import { test } from "node:test";
import assert from "node:assert/strict";
import { BoardStore } from "./store.js";
import { History, invertOps } from "./history.js";

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

test("add undo redo restores the object", () => {
  const store = new BoardStore();
  const history = new History(store);
  history.push([rect(A)]);
  assert.equal(store.snapshot().length, 1);
  assert.equal(store.get(A).data.width, 10);
  history.undo();
  assert.equal(store.snapshot().length, 0);
  history.redo();
  assert.equal(store.snapshot().length, 1);
  assert.equal(store.get(A).id, A);
});

test("patch of two fields undoes both keys", () => {
  const store = new BoardStore();
  const history = new History(store);
  history.push([rect(A, { fill: "#000000", stroke: "#ffffff" })]);
  history.push([{ op: "patch", id: A, patch: { fill: "#ff0000", x: 40 } }]);
  const after = store.get(A);
  assert.equal(after.data.fill, "#ff0000");
  assert.equal(after.data.x, 40);
  assert.equal(after.data.stroke, "#ffffff");
  history.undo();
  const undone = store.get(A);
  assert.equal(undone.data.fill, "#000000");
  assert.equal(undone.data.x, 0);
  assert.equal(undone.data.stroke, "#ffffff");
});

test("z inverse restores the previous index", () => {
  const store = new BoardStore();
  const history = new History(store);
  history.push([rect(A), rect(B)]);
  const before = store.snapshot().map((row) => row.id);
  assert.deepEqual(before, [A, B]);
  history.push([{ op: "z", id: A, index: 1 }]);
  assert.deepEqual(
    store.snapshot().map((row) => row.id),
    [B, A],
  );
  history.undo();
  assert.deepEqual(
    store.snapshot().map((row) => row.id),
    [A, B],
  );
});

test("remove inverse is add with original data", () => {
  const store = new BoardStore();
  const history = new History(store);
  history.push([rect(A, { fill: "#123456" })]);
  const inverse = invertOps(store, [{ op: "remove", id: A }]);
  assert.equal(inverse[0].op, "add");
  assert.equal(inverse[0].data.fill, "#123456");
  history.push([{ op: "remove", id: A }]);
  assert.equal(store.snapshot().length, 0);
  history.undo();
  assert.equal(store.get(A).data.fill, "#123456");
});

test("redo is cleared after a new action", () => {
  const store = new BoardStore();
  const history = new History(store);
  history.push([rect(A)]);
  history.undo();
  assert.equal(history.canRedo(), true);
  history.push([rect(B)]);
  assert.equal(history.canRedo(), false);
  assert.equal(store.get(B).type, "rect");
});
