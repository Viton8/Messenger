/**
 * Local undo/redo. Each user action is a pair of protocol ops (forward + inverse).
 */

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
  constructor(store) {
    this.store = store;
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
  }

  undo() {
    const item = this._undo.pop();
    if (!item) {
      return false;
    }
    this.store.applyOps(item.inverse);
    this._redo.push(item);
    return true;
  }

  redo() {
    const item = this._redo.pop();
    if (!item) {
      return false;
    }
    this.store.applyOps(item.forward);
    this._undo.push(item);
    return true;
  }

  canUndo() {
    return this._undo.length > 0;
  }

  canRedo() {
    return this._redo.length > 0;
  }
}
