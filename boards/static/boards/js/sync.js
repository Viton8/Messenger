/**
 * WebSocket client for board ops, presence, cursors, and reconnect.
 */

const GAP_MS = 2000;
const TRANSIENT_MS = 1000 / 15;
const MAX_BACKOFF_MS = 8000;
const BASE_BACKOFF_MS = 400;
const RATE_PAUSE_MS = 2000;

function defaultId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "00000000-0000-4000-8000-000000000000".replace(/0/g, () =>
    Math.floor(Math.random() * 16).toString(16),
  );
}

export class BoardSync {
  constructor(options = {}) {
    this.store = options.store;
    this.history = options.history || null;
    this.boardId = String(options.boardId || "");
    this._WS = options.WebSocket || globalThis.WebSocket;
    this._setTimeout = options.setTimeout || ((fn, ms) => globalThis.setTimeout(fn, ms));
    this._clearTimeout = options.clearTimeout || ((id) => globalThis.clearTimeout(id));
    this._now = options.now || (() => Date.now());
    this._random = options.random || Math.random;
    this._location = options.location || globalThis.location;
    this._loginUrl = options.loginUrl || "/accounts/login/";
    this._newId = options.newId || defaultId;

    this.state = "connecting";
    this.lastSeq = -1;
    this.canEdit = false;
    this.self = null;
    this.users = [];

    this.onState = options.onState || null;
    this.onNotice = options.onNotice || null;
    this.onPresence = options.onPresence || null;
    this.onCanEdit = options.onCanEdit || null;
    this.onCursor = options.onCursor || null;
    this.onTransient = options.onTransient || null;
    this.onLock = options.onLock || null;
    this.onPresenceEvent = options.onPresenceEvent || null;

    this._ws = null;
    this._pending = [];
    this._seqBuffer = new Map();
    this._gapTimer = null;
    this._reconnectTimer = null;
    this._attempts = 0;
    this._resyncPause = false;
    this._resyncPauseTimer = null;
    this._lastCursorAt = 0;
    this._lastTransientAt = 0;
    this._closed = false;

    if (this.history) {
      this.history.onCommit = (ops) => this.sendOps(ops);
    }
    this._connect();
  }

  sendOps(ops) {
    if (!Array.isArray(ops) || !ops.length) {
      return null;
    }
    const client_op_id = this._newId();
    const entry = { client_op_id, ops, resent: false };
    this._pending.push(entry);
    if (this.state === "live") {
      this._send({ type: "ops", client_op_id, ops });
    }
    return client_op_id;
  }

  sendCursor(x, y) {
    if (this.state !== "live") {
      return;
    }
    const now = this._now();
    if (now - this._lastCursorAt < TRANSIENT_MS) {
      return;
    }
    this._lastCursorAt = now;
    this._send({ type: "cursor", x, y });
  }

  sendTransient(id, patch) {
    if (this.state !== "live" || !this.canEdit) {
      return;
    }
    const now = this._now();
    if (now - this._lastTransientAt < TRANSIENT_MS) {
      return;
    }
    this._lastTransientAt = now;
    this._send({ type: "transient", id, patch });
  }

  requestResync() {
    if (this.state !== "live" || this._resyncPause) {
      return;
    }
    this._send({ type: "resync" });
  }

  close() {
    this._closed = true;
    this._clearTimers();
    this._setState("closed");
    if (this._ws) {
      this._ws.onclose = null;
      this._ws.close();
      this._ws = null;
    }
  }

  _connect() {
    if (this._closed) {
      return;
    }
    this.lastSeq = -1;
    this._seqBuffer.clear();
    this._clearGapTimer();
    this._setState(this._attempts ? "reconnecting" : "connecting");
    const loc = this._location || {};
    const proto = loc.protocol === "https:" ? "wss:" : "ws:";
    const host = loc.host || "localhost";
    const url = `${proto}//${host}/ws/boards/${this.boardId}/`;
    const ws = new this._WS(url);
    this._ws = ws;
    ws.onopen = () => {};
    ws.onmessage = (event) => this._onMessage(event && event.data);
    ws.onclose = (event) => this._onClose(event || {});
    ws.onerror = () => {};
  }

  _onClose(event) {
    const code = event.code;
    this._ws = null;
    this._clearGapTimer();
    if (this._closed) {
      return;
    }
    if (code === 4401) {
      this._setState("closed");
      this._closed = true;
      this._redirectLogin();
      return;
    }
    if (code === 4403) {
      this._setState("closed");
      this._closed = true;
      this._notice("Доска удалена или доступ закрыт");
      return;
    }
    this._scheduleReconnect();
  }

  _scheduleReconnect() {
    this._setState("reconnecting");
    const attempt = this._attempts;
    this._attempts += 1;
    const base = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** attempt);
    const delay = base * (0.5 + this._random());
    this._reconnectTimer = this._setTimeout(() => {
      this._reconnectTimer = null;
      this._connect();
    }, delay);
  }

  _onMessage(raw) {
    let data;
    try {
      data = typeof raw === "string" ? JSON.parse(raw) : raw;
    } catch {
      return;
    }
    if (!data || typeof data !== "object") {
      return;
    }
    const kind = data.type;
    if (kind === "init") {
      this._onInit(data);
    } else if (kind === "ops") {
      this._onOps(data);
    } else if (kind === "error") {
      this._onError(data);
    } else if (kind === "cursor") {
      this._onCursor(data);
    } else if (kind === "transient") {
      if (this.onTransient && !this._isSelf(data.user)) {
        this.onTransient(data);
      }
    } else if (kind === "presence") {
      this._onPresence(data);
    } else if (kind === "lock") {
      if (this.onLock) {
        this.onLock(Boolean(data.is_locked));
      }
    } else if (kind === "can_edit") {
      this._setCanEdit(Boolean(data.value));
    }
  }

  _onInit(msg) {
    this.lastSeq = Number.isInteger(msg.seq) ? msg.seq : 0;
    for (const seq of [...this._seqBuffer.keys()]) {
      if (seq <= this.lastSeq) {
        this._seqBuffer.delete(seq);
      }
    }
    this._clearGapTimer();
    this.self = msg.self || null;
    this.users = Array.isArray(msg.users) ? msg.users : [];
    if (this.store && this.store.reset) {
      this.store.reset(msg.objects || []);
    }
    this._replayPending();
    this._setCanEdit(Boolean(msg.can_edit));
    this._attempts = 0;
    this._setState("live");
    if (this.onPresence) {
      this.onPresence(this.users);
    }
    this._resendPending();
    this._flushSeqBuffer();
  }

  _onOps(msg) {
    const seq = msg.seq;
    if (!Number.isInteger(seq)) {
      return;
    }
    if (this.lastSeq < 0) {
      this._seqBuffer.set(seq, msg);
      return;
    }
    if (seq <= this.lastSeq) {
      return;
    }
    if (seq === this.lastSeq + 1) {
      this._applyOpsMessage(msg);
      this.lastSeq = seq;
      this._flushSeqBuffer();
      return;
    }
    this._seqBuffer.set(seq, msg);
    this._armGapTimer();
  }

  _flushSeqBuffer() {
    while (this._seqBuffer.has(this.lastSeq + 1)) {
      const next = this.lastSeq + 1;
      const msg = this._seqBuffer.get(next);
      this._seqBuffer.delete(next);
      this._applyOpsMessage(msg);
      this.lastSeq = next;
    }
    if (!this._seqBuffer.size) {
      this._clearGapTimer();
    }
  }

  _applyOpsMessage(msg) {
    const own = this._pending.find((row) => row.client_op_id === msg.client_op_id);
    if (own) {
      this._ackPending(own, msg.ops || []);
      return;
    }
    const ops = this._filterRemoteOps(msg.ops || []);
    if (ops.length && this.store && this.store.applyRemote) {
      this.store.applyRemote(ops);
    }
  }

  _filterRemoteOps(ops) {
    const blocked = this._pendingPatchKeys();
    const out = [];
    for (const op of ops) {
      if (!op || op.op !== "patch") {
        out.push(op);
        continue;
      }
      const keys = blocked.get(String(op.id));
      if (!keys || !keys.size) {
        out.push(op);
        continue;
      }
      const patch = {};
      for (const [key, value] of Object.entries(op.patch || {})) {
        if (!keys.has(key)) {
          patch[key] = value;
        }
      }
      if (Object.keys(patch).length) {
        out.push({ ...op, patch });
      }
    }
    return out;
  }

  _pendingPatchKeys() {
    const map = new Map();
    for (const entry of this._pending) {
      for (const op of entry.ops || []) {
        if (op.op !== "patch" || op.id == null) {
          continue;
        }
        const id = String(op.id);
        if (!map.has(id)) {
          map.set(id, new Set());
        }
        for (const key of Object.keys(op.patch || {})) {
          map.get(id).add(key);
        }
      }
    }
    return map;
  }

  _ackPending(entry, serverOps) {
    this._pending = this._pending.filter((row) => row !== entry);
    if (!this.store || !this.store.setZ) {
      return;
    }
    for (const op of serverOps) {
      if (op && op.op === "add" && Number.isInteger(op.z)) {
        this.store.setZ(op.id, op.z);
      }
    }
  }

  _onError(msg) {
    const code = msg.code || "";
    const pending = msg.client_op_id
      ? this._pending.find((row) => row.client_op_id === msg.client_op_id)
      : null;
    if (pending && pending.resent) {
      const kinds = new Set((pending.ops || []).map((op) => op.op));
      if (code === "duplicate_id" && kinds.has("add")) {
        this._ackPending(pending, []);
        return;
      }
      if (code === "not_found" && (kinds.has("remove") || kinds.has("patch"))) {
        this._ackPending(pending, []);
        return;
      }
    }
    if (code === "rate_limited") {
      this._notice("Слишком много запросов, подождите.");
      this._resyncPause = true;
      if (this._resyncPauseTimer) {
        this._clearTimeout(this._resyncPauseTimer);
      }
      this._resyncPauseTimer = this._setTimeout(() => {
        this._resyncPause = false;
        this._resyncPauseTimer = null;
      }, RATE_PAUSE_MS);
      return;
    }
    if (code === "locked") {
      this._setCanEdit(false);
      if (pending) {
        this._pending = this._pending.filter((row) => row !== pending);
      }
      this.requestResync();
      return;
    }
    if (
      code.startsWith("invalid_") ||
      code === "limit" ||
      code === "too_many_ops" ||
      code === "duplicate_id" ||
      code === "not_found" ||
      code === "bad_payload"
    ) {
      this._notice(msg.detail || "Ошибка синхронизации");
      if (pending) {
        this._pending = this._pending.filter((row) => row !== pending);
      }
      this.requestResync();
    }
  }

  _onCursor(msg) {
    if (this._isSelf(msg.user)) {
      return;
    }
    if (this.onCursor) {
      this.onCursor(msg);
    }
  }

  _onPresence(msg) {
    const user = msg.user;
    if (!user || !user.id) {
      return;
    }
    if (msg.action === "join") {
      if (!this.users.some((row) => row.id === user.id)) {
        this.users = [...this.users, user];
      }
    } else if (msg.action === "leave") {
      this.users = this.users.filter((row) => row.id !== user.id);
    }
    if (this.onPresence) {
      this.onPresence(this.users);
    }
    if (this.onPresenceEvent) {
      this.onPresenceEvent(msg);
    }
  }

  _replayPending() {
    if (!this.store || !this.store.applyRemote) {
      return;
    }
    const kept = [];
    for (const entry of this._pending) {
      const applied = this.store.applyRemote(entry.ops || []);
      if (applied.length) {
        kept.push(entry);
      }
    }
    this._pending = kept;
  }

  _resendPending() {
    for (const entry of this._pending) {
      entry.resent = true;
      this._send({
        type: "ops",
        client_op_id: entry.client_op_id,
        ops: entry.ops,
      });
    }
  }

  _send(payload) {
    const ws = this._ws;
    if (!ws || ws.readyState !== 1) {
      return;
    }
    ws.send(JSON.stringify(payload));
  }

  _armGapTimer() {
    if (this._gapTimer != null) {
      return;
    }
    this._gapTimer = this._setTimeout(() => {
      this._gapTimer = null;
      this.requestResync();
    }, GAP_MS);
  }

  _clearGapTimer() {
    if (this._gapTimer != null) {
      this._clearTimeout(this._gapTimer);
      this._gapTimer = null;
    }
  }

  _clearTimers() {
    this._clearGapTimer();
    if (this._reconnectTimer != null) {
      this._clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._resyncPauseTimer != null) {
      this._clearTimeout(this._resyncPauseTimer);
      this._resyncPauseTimer = null;
    }
  }

  _setState(state) {
    this.state = state;
    if (this.onState) {
      this.onState(state);
    }
  }

  _setCanEdit(value) {
    this.canEdit = Boolean(value);
    if (this.onCanEdit) {
      this.onCanEdit(this.canEdit);
    }
  }

  _isSelf(user) {
    return Boolean(this.self && user && String(user.id) === String(this.self.id));
  }

  _notice(text) {
    if (this.onNotice) {
      this.onNotice(text);
    }
  }

  _redirectLogin() {
    const loc = this._location;
    const next = encodeURIComponent((loc && loc.pathname) || "/");
    const url = `${this._loginUrl}?next=${next}`;
    if (loc && typeof loc.assign === "function") {
      loc.assign(url);
    } else if (loc) {
      loc.href = url;
    }
  }
}
