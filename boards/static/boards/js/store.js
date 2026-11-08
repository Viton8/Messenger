/**
 * In-memory board document. All mutations go through applyOps using the
 * server op format (add / patch / remove / z).
 */

import { ALLOWED_TYPES, sanitizeProperties } from "./serialize.js";

export class BoardStore {
  constructor() {
    this._objects = new Map();
    this._listeners = new Set();
  }

  subscribe(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  get(id) {
    const row = this._objects.get(String(id));
    if (!row || row.deleted) {
      return null;
    }
    return cloneRecord(row);
  }

  snapshot() {
    return this._live()
      .sort(compareLive)
      .map(cloneRecord);
  }

  applyOps(ops) {
    if (!Array.isArray(ops) || !ops.length) {
      return [];
    }
    const applied = [];
    for (const raw of ops) {
      applied.push(this._applyOne(raw));
    }
    this._emit(applied);
    return applied;
  }

  applyRemote(ops) {
    if (!Array.isArray(ops) || !ops.length) {
      return [];
    }
    const applied = [];
    for (const raw of ops) {
      try {
        applied.push(this._applyOne(raw));
      } catch {
        // Skip a bad remote op; keep applying the rest of the batch.
      }
    }
    if (applied.length) {
      this._emit(applied);
    }
    return applied;
  }

  reset(objects) {
    this._objects = new Map();
    if (Array.isArray(objects)) {
      for (const raw of objects) {
        if (!raw || raw.id == null) {
          continue;
        }
        const type = raw.type || (raw.data && raw.data.type);
        if (!ALLOWED_TYPES.has(type)) {
          continue;
        }
        const data = sanitizeProperties(type, raw.data || {}, false);
        const z = Number.isInteger(raw.z) ? raw.z : 0;
        const id = String(raw.id);
        this._objects.set(id, { id, type, z, data, deleted: false });
      }
    }
    this._emit([{ op: "reset" }]);
  }

  setZ(id, z) {
    const row = this._objects.get(String(id));
    if (!row || row.deleted || !Number.isInteger(z) || row.z === z) {
      return;
    }
    row.z = z;
    this._emit([{ op: "z", id: row.id, index: z }]);
  }

  _emit(ops) {
    for (const fn of this._listeners) {
      fn(ops);
    }
  }

  _live() {
    return [...this._objects.values()].filter((row) => !row.deleted);
  }

  _nextZ() {
    const live = this._live();
    if (!live.length) {
      return 0;
    }
    return Math.max(...live.map((row) => row.z)) + 1;
  }

  _applyOne(raw) {
    if (!raw || typeof raw !== "object") {
      throw new Error("Each op must be an object.");
    }
    const kind = raw.op;
    if (kind === "add") {
      return this._add(raw);
    }
    if (kind === "patch") {
      return this._patch(raw);
    }
    if (kind === "remove") {
      return this._remove(raw);
    }
    if (kind === "z") {
      return this._reorder(raw);
    }
    throw new Error("Unknown op.");
  }

  _add(raw) {
    const id = String(raw.id);
    const type = raw.type || (raw.data && raw.data.type);
    if (!ALLOWED_TYPES.has(type)) {
      throw new Error("Unknown object type.");
    }
    const existing = this._objects.get(id);
    if (existing && !existing.deleted) {
      throw new Error("That object already exists.");
    }
    const data = sanitizeProperties(type, raw.data || {}, false);
    const z = Number.isInteger(raw.z) ? raw.z : this._nextZ();
    const row = { id, type, z, data, deleted: false };
    this._objects.set(id, row);
    return { op: "add", id, type, data: { ...data }, z };
  }

  _patch(raw) {
    const row = this._requireLive(raw.id);
    const patch = sanitizeProperties(row.type, raw.patch || {}, true);
    row.data = { ...row.data, ...patch };
    return { op: "patch", id: row.id, patch };
  }

  _remove(raw) {
    const row = this._requireLive(raw.id);
    row.deleted = true;
    return { op: "remove", id: row.id };
  }

  _reorder(raw) {
    const row = this._requireLive(raw.id);
    const index = Number(raw.index);
    const live = this._live().sort(compareLive);
    if (!Number.isInteger(index) || index < 0 || index >= live.length) {
      throw new Error("z index is out of range.");
    }
    const rest = live.filter((item) => item.id !== row.id);
    rest.splice(index, 0, row);
    rest.forEach((item, z) => {
      item.z = z;
    });
    return { op: "z", id: row.id, index };
  }

  _requireLive(id) {
    const row = this._objects.get(String(id));
    if (!row || row.deleted) {
      throw new Error("Object not found.");
    }
    return row;
  }
}

function compareLive(a, b) {
  if (a.z !== b.z) {
    return a.z - b.z;
  }
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function cloneRecord(row) {
  return {
    id: row.id,
    type: row.type,
    z: row.z,
    data: { ...row.data },
  };
}
