import { test } from "node:test";
import assert from "node:assert/strict";
import { BoardStore } from "./store.js";
import { BoardSync } from "./sync.js";

const A = "00000000-0000-0000-0000-00000000000a";
const B = "00000000-0000-0000-0000-00000000000b";
const BOARD = "11111111-1111-1111-1111-111111111111";

class FakeSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    FakeSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000) {
    this.readyState = 3;
    if (this.onclose) {
      this.onclose({ code });
    }
  }

  emit(obj) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(obj) });
    }
  }
}

function createClock() {
  let now = 0;
  const timers = [];
  let nextId = 1;
  return {
    now: () => now,
    setTimeout(fn, ms) {
      const handle = nextId;
      nextId += 1;
      timers.push({ handle, at: now + ms, fn });
      return handle;
    },
    clearTimeout(handle) {
      const index = timers.findIndex((row) => row.handle === handle);
      if (index >= 0) {
        timers.splice(index, 1);
      }
    },
    advance(ms) {
      now += ms;
      timers.sort((a, b) => a.at - b.at);
      while (timers.length && timers[0].at <= now) {
        const row = timers.shift();
        row.fn();
      }
    },
  };
}

function startSync(extra = {}) {
  FakeSocket.instances = [];
  const clock = extra.clock || createClock();
  const ids = extra.ids || ["op-1", "op-2", "op-3"];
  let n = 0;
  const store = extra.store || new BoardStore();
  const location = extra.location || {
    protocol: "http:",
    host: "localhost",
    pathname: `/boards/${BOARD}/`,
    assigned: null,
    assign(url) {
      this.assigned = url;
    },
  };
  const sync = new BoardSync({
    boardId: BOARD,
    store,
    WebSocket: FakeSocket,
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
    now: () => clock.now(),
    random: () => 0,
    location,
    loginUrl: "/accounts/login/",
    newId: () => ids[n++] || `op-${n}`,
    ...extra.options,
  });
  const socket = FakeSocket.instances[0];
  return { sync, store, socket, clock, location };
}

function initPayload(extra) {
  return {
    type: "init",
    seq: 0,
    objects: [],
    can_edit: true,
    self: { id: "1", username: "alice", color: "#e53935" },
    users: [{ id: "1", username: "alice", color: "#e53935" }],
    ...extra,
  };
}

test("seq applies in order and buffers a gap until the missing frame arrives", () => {
  const { sync, store, socket } = startSync();
  socket.emit(initPayload());
  socket.emit({
    type: "ops",
    seq: 2,
    client_op_id: "remote-2",
    ops: [{ op: "patch", id: A, patch: { fill: "#111111" } }],
  });
  assert.equal(store.get(A), null);
  assert.equal(sync.lastSeq, 0);
  socket.emit({
    type: "ops",
    seq: 1,
    client_op_id: "remote-1",
    ops: [
      {
        op: "add",
        id: A,
        type: "rect",
        z: 0,
        data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
      },
    ],
  });
  assert.equal(sync.lastSeq, 2);
  assert.equal(store.get(A).data.fill, "#111111");
});

test("a seq gap that stays open for 2s sends resync", () => {
  const { socket, clock } = startSync();
  socket.emit(initPayload());
  socket.sent = [];
  socket.emit({
    type: "ops",
    seq: 3,
    client_op_id: "gap",
    ops: [{ op: "patch", id: A, patch: { x: 1 } }],
  });
  assert.equal(socket.sent.length, 0);
  clock.advance(2000);
  assert.deepEqual(socket.sent, [{ type: "resync" }]);
});

test("own client_op_id is an ack and is not applied twice", () => {
  const { sync, store, socket } = startSync();
  socket.emit(initPayload());
  store.applyOps([
    {
      op: "add",
      id: A,
      type: "rect",
      data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
    },
  ]);
  const cid = sync.sendOps([
    {
      op: "add",
      id: A,
      type: "rect",
      data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
    },
  ]);
  socket.emit({
    type: "ops",
    seq: 1,
    client_op_id: cid,
    ops: [
      {
        op: "add",
        id: A,
        type: "rect",
        z: 4,
        data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
      },
    ],
  });
  assert.equal(store.get(A).z, 4);
  assert.equal(sync.lastSeq, 1);
  assert.equal(sync._pending.length, 0);
});

test("resent add duplicate_id is treated as confirmation", () => {
  const { sync, socket } = startSync();
  socket.emit(initPayload());
  const cid = sync.sendOps([
    {
      op: "add",
      id: A,
      type: "rect",
      data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
    },
  ]);
  socket.emit(initPayload({ seq: 1 }));
  const resent = socket.sent.filter((row) => row.type === "ops");
  assert.equal(resent.length, 2);
  assert.equal(resent[1].client_op_id, cid);
  socket.emit({
    type: "error",
    code: "duplicate_id",
    detail: "duplicate",
    client_op_id: cid,
  });
  assert.equal(sync._pending.length, 0);
  assert.equal(sync.lastSeq, 1);
});

test("foreign patch skips keys with an unconfirmed local patch", () => {
  const { sync, store, socket } = startSync();
  socket.emit(initPayload());
  store.applyOps([
    {
      op: "add",
      id: A,
      type: "rect",
      data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc" },
    },
  ]);
  store.applyOps([{ op: "patch", id: A, patch: { x: 50 } }]);
  sync.sendOps([{ op: "patch", id: A, patch: { x: 50 } }]);
  socket.emit({
    type: "ops",
    seq: 1,
    client_op_id: "other",
    ops: [{ op: "patch", id: A, patch: { x: 1, y: 9 } }],
  });
  assert.equal(store.get(A).data.x, 50);
  assert.equal(store.get(A).data.y, 9);
  assert.equal(sync.lastSeq, 1);
});

function reconnect(socket, clock) {
  socket.close(1006);
  clock.advance(200);
  return FakeSocket.instances[FakeSocket.instances.length - 1];
}

function rectOp(id, extra) {
  return {
    op: "add",
    id,
    type: "rect",
    data: { x: 0, y: 0, width: 10, height: 10, fill: "#abcabc", ...(extra || {}) },
  };
}

test("pending add survives reconnect init and ack does not duplicate it", () => {
  const { sync, store, socket, clock } = startSync();
  socket.emit(initPayload());
  store.applyOps([rectOp(A)]);
  const cid = sync.sendOps([rectOp(A)]);
  const next = reconnect(socket, clock);
  next.emit(initPayload());
  assert.equal(store.snapshot().length, 1);
  assert.equal(store.get(A).type, "rect");
  next.emit({
    type: "ops",
    seq: 1,
    client_op_id: cid,
    ops: [{ ...rectOp(A), z: 6 }],
  });
  assert.equal(store.snapshot().length, 1);
  assert.equal(store.get(A).z, 6);
  assert.equal(sync._pending.length, 0);
});

test("pending add patch remove replay; invalid batch is dropped", () => {
  const { sync, store, socket, clock } = startSync({
    ids: ["add-a", "patch-a", "add-b", "remove-b", "bad"],
  });
  socket.emit(initPayload());
  store.applyOps([rectOp(A)]);
  sync.sendOps([rectOp(A)]);
  store.applyOps([{ op: "patch", id: A, patch: { x: 40 } }]);
  sync.sendOps([{ op: "patch", id: A, patch: { x: 40 } }]);
  store.applyOps([rectOp(B)]);
  sync.sendOps([rectOp(B)]);
  store.applyOps([{ op: "remove", id: B }]);
  sync.sendOps([{ op: "remove", id: B }]);
  sync.sendOps([{ op: "patch", id: "not-a-uuid", patch: { x: 1 } }]);
  const next = reconnect(socket, clock);
  next.emit(initPayload());
  assert.equal(store.get(A).data.x, 40);
  assert.equal(store.get(B), null);
  assert.equal(
    sync._pending.some((row) => row.client_op_id === "bad"),
    false,
  );
  assert.equal(sync._pending.length, 4);
});

test("reconnect resets lastSeq and the seq buffer before init", () => {
  const { sync, socket, clock } = startSync();
  socket.emit(initPayload({ seq: 5 }));
  assert.equal(sync.lastSeq, 5);
  const next = reconnect(socket, clock);
  assert.equal(sync.lastSeq, -1);
  assert.equal(sync._seqBuffer.size, 0);
  next.emit({
    type: "ops",
    seq: 6,
    client_op_id: "early",
    ops: [{ op: "patch", id: A, patch: { x: 1 } }],
  });
  assert.equal(sync._seqBuffer.size, 1);
  assert.equal(next.sent.some((row) => row.type === "resync"), false);
});

test("locked drops the rejected pending batch and requests resync", () => {
  const { sync, socket } = startSync();
  socket.emit(initPayload());
  const cid = sync.sendOps([rectOp(A)]);
  socket.sent = [];
  socket.emit({
    type: "error",
    code: "locked",
    detail: "This board is locked.",
    client_op_id: cid,
  });
  assert.equal(sync._pending.length, 0);
  assert.equal(sync.canEdit, false);
  assert.deepEqual(socket.sent, [{ type: "resync" }]);
});

test("4403 closes without reconnecting", () => {
  const { sync, socket, clock } = startSync();
  const notices = [];
  sync.onNotice = (text) => notices.push(text);
  socket.close(4403);
  clock.advance(8000);
  assert.equal(sync.state, "closed");
  assert.equal(FakeSocket.instances.length, 1);
  assert.equal(notices[0], "Доска удалена или доступ закрыт");
});

test("4401 redirects to login", () => {
  const { sync, socket, location } = startSync();
  socket.close(4401);
  assert.equal(sync.state, "closed");
  assert.equal(location.assigned, `/accounts/login/?next=${encodeURIComponent(`/boards/${BOARD}/`)}`);
});
