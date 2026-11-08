/**
 * Local undo/redo. Each user action is a pair of protocol ops (forward + inverse).
 */

export function filterOpsForStore(store, ops) {
  const live = new Set(store.snapshot().map((row) => String(row.id)));
  const out = [];
  for (const op of ops || []) {
    if (!op || typeof op !== "object") {
      continue;
    }
    const id = op.id != null ? String(op.id) : "";
    if (op.op === "add") {
      if (!live.has(id)) {
        out.push(op);
        live.add(id);
      }
    } else if (op.op === "remove" || op.op === "patch" || op.op === "z") {
      if (live.has(id)) {
        out.push(op);
        if (op.op === "remove") {
          live.delete(id);
        }
      }
    }
  }
  return out;
}

export function invertOps(store, ops) {
  const inverse = [];
  const simulated = new Map();
  for (const rec of store.snapshot()) {
    simulated.set(rec.id, rec);
  }
  for (const op of ops) {
    if (op.op === "add") {
      inverse.push({ op: "remove", id: op.id });
      simulated.set(op.id, {
        id: op.id,
        type: op.type,
        z: op.z,
        data: { ...(op.data || {}) },
      });
    } else if (op.op === "remove") {
      const rec = simulated.get(op.id);
      if (rec) {
        inverse.push({
          op: "add",
          id: rec.id,
          type: rec.type,
          data: { ...rec.data },
          z: rec.z,
        });
        simulated.delete(op.id);
      }
    } else if (op.op === "patch") {
      const rec = simulated.get(op.id);
      if (rec) {
        const oldPatch = {};
        for (const key of Object.keys(op.patch || {})) {
          oldPatch[key] = rec.data[key];
        }
        inverse.push({ op: "patch", id: op.id, patch: oldPatch });
        rec.data = { ...rec.data, ...(op.patch || {}) };
      }
    } else if (op.op === "z") {
      const live = [...simulated.values()].sort((a, b) => {
        if (a.z !== b.z) {
          return a.z - b.z;
        }
        return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
      });
      const oldIndex = live.findIndex((item) => item.id === op.id);
      inverse.push({ op: "z", id: op.id, index: oldIndex });
      const rec = simulated.get(op.id);
      if (rec && oldIndex >= 0) {
        live.splice(oldIndex, 1);
        live.splice(op.index, 0, rec);
        live.forEach((item, z) => {
          item.z = z;
        });
      }
    }
  }
  inverse.reverse();
  return inverse;
}

export class History {
  constructor(store, { onStale } = {}) {
    this.store = store;
    this.onStale = onStale || null;
    this.onCommit = null;
    this._undo = [];
    this._redo = [];
  }

  push(ops) {
    const forward = Array.isArray(ops) ? ops : [ops];
    if (!forward.length) {
      return;
    }
    const inverse = invertOps(this.store, forward);
    this.store.applyOps(forward);
    this._undo.push({ forward, inverse });
    this._redo = [];
    if (this.onCommit) {
      this.onCommit(forward);
    }
  }

  undo() {
    return this._applyFromStack(this._undo, this._redo, "inverse");
  }

  redo() {
    return this._applyFromStack(this._redo, this._undo, "forward");
  }

  _applyFromStack(from, to, key) {
    while (from.length) {
      const item = from.pop();
      const filtered = filterOpsForStore(this.store, item[key]);
      if (!filtered.length) {
        if (this.onStale) {
          this.onStale();
        }
        continue;
      }
      this.store.applyOps(filtered);
      const stored = { forward: item.forward, inverse: item.inverse };
      stored[key] = filtered;
      to.push(stored);
      if (this.onCommit) {
        this.onCommit(filtered);
      }
      return true;
    }
    return false;
  }

  canUndo() {
    return this._undo.length > 0;
  }

  canRedo() {
    return this._redo.length > 0;
  }
}
