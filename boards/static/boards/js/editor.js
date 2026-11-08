/**
 * Fabric canvas, viewport, and store-to-canvas sync.
 */

import {
  Canvas,
  Ellipse,
  Line,
  PencilBrush,
  Point,
  Polyline,
  Rect,
  Textbox,
  classRegistry,
} from "../vendor/fabric.min.mjs";
import { createFromRecord, toRecord, patchFromRecords } from "./serialize.js";

export class Arrow extends Line {
  static type = "Arrow";

  _render(ctx) {
    super._render(ctx);
    const { x1, y1, x2, y2 } = this.calcLinePoints();
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const length = 12;
    const width = 7;
    ctx.save();
    ctx.translate(x2, y2);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-length, width);
    ctx.lineTo(-length, -width);
    ctx.closePath();
    ctx.fillStyle = this.stroke || "#e8eaed";
    ctx.fill();
    ctx.restore();
  }
}

classRegistry.setClass(Arrow);

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 16;
const FIT_PADDING = 0.9;

export function newObjectId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "00000000-0000-4000-8000-000000000000".replace(/0/g, () =>
    Math.floor(Math.random() * 16).toString(16),
  );
}

export class BoardEditor {
  constructor({ canvasEl, store, history, readOnly = false }) {
    this.store = store;
    this.history = history;
    this.readOnly = Boolean(readOnly);
    this.styles = {
      fill: "#c9a227",
      stroke: "#e8eaed",
      strokeWidth: 2,
      fontSize: 24,
      fontFamily: "sans-serif",
    };
    this.toolName = "select";
    this._byId = new Map();
    this._spaceDown = false;
    this._panning = false;
    this._panLast = null;
    this._pointers = new Map();
    this._pinch = null;
    this._tools = {};
    this._onToolChange = [];
    this.classes = {
      rect: Rect,
      ellipse: Ellipse,
      line: Line,
      arrow: Arrow,
      path: Polyline,
      textbox: Textbox,
      sticker: Textbox,
    };

    const stage = canvasEl.parentElement;
    const size = stage.getBoundingClientRect();
    this.canvas = new Canvas(canvasEl, {
      width: Math.max(1, size.width),
      height: Math.max(1, size.height),
      backgroundColor: "#1a2332",
      preserveObjectStacking: true,
      selection: !this.readOnly,
      stopContextMenu: true,
      fireRightClick: true,
      fireMiddleClick: true,
      skipTargetFind: this.readOnly,
    });
    this.canvas.freeDrawingBrush = new PencilBrush(this.canvas);

    this._onOps = (ops) => this._applyOpsToCanvas(ops);
    this.store.subscribe(this._onOps);

    this._resizeObserver = new ResizeObserver(() => this._resize());
    this._resizeObserver.observe(stage);

    this._bindViewport();
    this._bindObjectEvents();
    this._setReadOnlyMode();
  }

  onToolChange(fn) {
    this._onToolChange.push(fn);
  }

  registerTools(tools) {
    this._tools = tools;
    this.setTool(this.readOnly ? "select" : "select");
  }

  setTool(name) {
    if (this.readOnly && name !== "select") {
      name = "select";
    }
    const next = this._tools[name];
    if (!next) {
      return;
    }
    if (this._tools[this.toolName] && this._tools[this.toolName].deactivate) {
      this._tools[this.toolName].deactivate();
    }
    this.toolName = name;
    if (next.activate) {
      next.activate();
    }
    this._applySelectability();
    for (const fn of this._onToolChange) {
      fn(name);
    }
  }

  scenePoint(opt) {
    if (opt && opt.scenePoint) {
      return opt.scenePoint;
    }
    const event = opt && opt.e ? opt.e : opt;
    return this.canvas.getScenePoint(event);
  }

  shouldIgnorePointer(opt) {
    const event = opt && opt.e ? opt.e : opt;
    if (this._panning || this._pinch || this._spaceDown) {
      return true;
    }
    if (event && (event.button === 1 || event.buttons === 4)) {
      return true;
    }
    if (this._pointers.size >= 2) {
      return true;
    }
    return false;
  }

  defaultData(type, extra) {
    const base = {
      fill: type === "line" || type === "arrow" || type === "path" ? "transparent" : this.styles.fill,
      stroke: this.styles.stroke,
      strokeWidth: this.styles.strokeWidth,
      opacity: 1,
      angle: 0,
      scaleX: 1,
      scaleY: 1,
    };
    if (type === "textbox" || type === "sticker") {
      base.text = extra && extra.text != null ? extra.text : type === "sticker" ? "Note" : "Text";
      base.fontSize = this.styles.fontSize;
      base.fontFamily = this.styles.fontFamily;
    }
    if (type === "sticker") {
      base.fill = "#f5e6a3";
      base.stroke = "#333333";
    }
    return { ...base, ...(extra || {}) };
  }

  commitAdd(type, extra) {
    const data = this.defaultData(type, extra);
    const id = newObjectId();
    this.history.push([{ op: "add", id, type, data }]);
    const obj = this._byId.get(id);
    if (obj && (type === "textbox" || type === "sticker") && obj.enterEditing) {
      this.canvas.setActiveObject(obj);
      obj.enterEditing();
      obj.selectAll && obj.selectAll();
    }
    return id;
  }

  selectedObjects() {
    const active = this.canvas.getActiveObject();
    if (!active) {
      return [];
    }
    if (active.boardType || active.id) {
      return [active];
    }
    if (typeof active.getObjects === "function") {
      return active.getObjects().filter((item) => item.id);
    }
    return [];
  }

  deleteSelection() {
    if (this.readOnly) {
      return;
    }
    const objects = this.selectedObjects();
    if (!objects.length) {
      return;
    }
    this.history.push(objects.map((obj) => ({ op: "remove", id: obj.id })));
    this.canvas.discardActiveObject();
  }

  duplicateSelection() {
    if (this.readOnly) {
      return;
    }
    const objects = this.selectedObjects();
    if (!objects.length) {
      return;
    }
    const ops = objects.map((obj) => {
      const record = toRecord(obj);
      const data = { ...record.data };
      if (data.x != null) {
        data.x += 16;
      }
      if (data.y != null) {
        data.y += 16;
      }
      if (data.x1 != null) {
        data.x1 += 16;
        data.x2 += 16;
        data.y1 += 16;
        data.y2 += 16;
      }
      if (Array.isArray(data.points)) {
        data.points = data.points.map(([x, y]) => [x + 16, y + 16]);
      }
      return { op: "add", id: newObjectId(), type: record.type, data };
    });
    this.history.push(ops);
  }

  bringToFront() {
    this._moveZ(-1);
  }

  sendToBack() {
    this._moveZ(0);
  }

  _moveZ(indexOrFront) {
    if (this.readOnly) {
      return;
    }
    const objects = this.selectedObjects();
    if (objects.length !== 1) {
      return;
    }
    const live = this.store.snapshot();
    const index = indexOrFront === -1 ? live.length - 1 : 0;
    this.history.push([{ op: "z", id: objects[0].id, index }]);
  }

  applyStylesToSelection() {
    if (this.readOnly) {
      return;
    }
    const objects = this.selectedObjects();
    const ops = [];
    for (const obj of objects) {
      const type = obj.boardType;
      const patch = {
        stroke: this.styles.stroke,
        strokeWidth: this.styles.strokeWidth,
      };
      if (type === "textbox") {
        patch.fill = this.styles.fill;
        patch.fontSize = this.styles.fontSize;
        patch.fontFamily = this.styles.fontFamily;
      } else if (type === "sticker") {
        patch.fill = this.styles.fill;
        patch.stroke = this.styles.stroke;
        patch.fontSize = this.styles.fontSize;
        patch.fontFamily = this.styles.fontFamily;
      } else if (type === "line" || type === "arrow" || type === "path") {
        patch.fill = "transparent";
      } else {
        patch.fill = this.styles.fill;
      }
      ops.push({ op: "patch", id: obj.id, patch });
    }
    if (ops.length) {
      this.history.push(ops);
    }
  }

  zoomBy(factor, point) {
    const origin = point || new Point(this.canvas.getWidth() / 2, this.canvas.getHeight() / 2);
    const zoom = clamp(this.canvas.getZoom() * factor, MIN_ZOOM, MAX_ZOOM);
    this.canvas.zoomToPoint(origin, zoom);
  }

  fitAll() {
    const records = this.store.snapshot();
    const bounds = sceneBounds(this.canvas, records, this._byId);
    if (!bounds) {
      this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
      return;
    }
    const width = Math.max(bounds.width, 1);
    const height = Math.max(bounds.height, 1);
    const zoom = clamp(
      Math.min(this.canvas.getWidth() / width, this.canvas.getHeight() / height) * FIT_PADDING,
      MIN_ZOOM,
      MAX_ZOOM,
    );
    const vpt = [zoom, 0, 0, zoom, 0, 0];
    vpt[4] = this.canvas.getWidth() / 2 - (bounds.left + width / 2) * zoom;
    vpt[5] = this.canvas.getHeight() / 2 - (bounds.top + height / 2) * zoom;
    this.canvas.setViewportTransform(vpt);
  }

  exportPng({ all = false } = {}) {
    if (!all) {
      return this.canvas.toCanvasElement(2).toDataURL("image/png");
    }
    const bounds = sceneBounds(this.canvas, this.store.snapshot(), this._byId);
    const prevVpt = [...this.canvas.viewportTransform];
    const prevW = this.canvas.getWidth();
    const prevH = this.canvas.getHeight();
    if (!bounds) {
      return this.canvas.toCanvasElement(2).toDataURL("image/png");
    }
    const width = Math.max(Math.ceil(bounds.width) + 16, 32);
    const height = Math.max(Math.ceil(bounds.height) + 16, 32);
    this.canvas.setDimensions({ width, height });
    this.canvas.setViewportTransform([1, 0, 0, 1, 8 - bounds.left, 8 - bounds.top]);
    const url = this.canvas.toCanvasElement(2).toDataURL("image/png");
    this.canvas.setDimensions({ width: prevW, height: prevH });
    this.canvas.setViewportTransform(prevVpt);
    return url;
  }

  downloadPng(all) {
    const url = this.exportPng({ all });
    const link = document.createElement("a");
    link.href = url;
    link.download = all ? "board-all.png" : "board-view.png";
    link.click();
  }

  _setReadOnlyMode() {
    this.canvas.selection = !this.readOnly;
    this.canvas.skipTargetFind = this.readOnly;
    this._applySelectability();
  }

  _applySelectability() {
    const selectable = !this.readOnly && this.toolName === "select";
    this.canvas.selection = selectable;
    this.canvas.skipTargetFind =
      this.readOnly || (this.toolName !== "select" && this.toolName !== "eraser");
    this.canvas.forEachObject((obj) => {
      if (obj.boardPreview) {
        obj.selectable = false;
        obj.evented = false;
        return;
      }
      obj.selectable = selectable;
      obj.evented = !this.readOnly;
      obj.hasControls = selectable;
    });
    if (!selectable) {
      this.canvas.discardActiveObject();
    }
    this.canvas.requestRenderAll();
  }

  _resize() {
    const stage = this.canvas.getElement().closest(".board-page__stage");
    if (!stage) {
      return;
    }
    const rect = stage.getBoundingClientRect();
    this.canvas.setDimensions({
      width: Math.max(1, rect.width),
      height: Math.max(1, rect.height),
    });
  }

  _bindViewport() {
    const canvas = this.canvas;
    canvas.on("mouse:wheel", (opt) => {
      const event = opt.e;
      event.preventDefault();
      event.stopPropagation();
      const factor = event.deltaY > 0 ? 0.9 : 1.1;
      this.zoomBy(factor, new Point(event.offsetX, event.offsetY));
    });
    canvas.on("mouse:down", (opt) => {
      const event = opt.e;
      if (event.button === 1 || this._spaceDown) {
        this._panning = true;
        this._panLast = { x: event.clientX, y: event.clientY };
        canvas.selection = false;
        canvas.setCursor("grab");
      }
    });
    canvas.on("mouse:move", (opt) => {
      if (!this._panning || !this._panLast) {
        return;
      }
      const event = opt.e;
      const vpt = [...canvas.viewportTransform];
      vpt[4] += event.clientX - this._panLast.x;
      vpt[5] += event.clientY - this._panLast.y;
      canvas.setViewportTransform(vpt);
      this._panLast = { x: event.clientX, y: event.clientY };
    });
    canvas.on("mouse:up", () => {
      if (this._panning) {
        this._panning = false;
        this._panLast = null;
        this._applySelectability();
      }
    });

    const surface = canvas.upperCanvasEl || (canvas.elements && canvas.elements.upper && canvas.elements.upper.el);
    if (surface) {
      surface.addEventListener("pointerdown", (event) => this._onPointerDown(event));
      surface.addEventListener("pointermove", (event) => this._onPointerMove(event));
      surface.addEventListener("pointerup", (event) => this._onPointerUp(event));
      surface.addEventListener("pointercancel", (event) => this._onPointerUp(event));
    }

    window.addEventListener("keydown", (event) => {
      if (event.code === "Space" && !this._isTyping(event)) {
        this._spaceDown = true;
        event.preventDefault();
      }
    });
    window.addEventListener("keyup", (event) => {
      if (event.code === "Space") {
        this._spaceDown = false;
        if (!this._panning) {
          this._applySelectability();
        }
      }
    });
  }

  _onPointerDown(event) {
    this._pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this._pointers.size === 2) {
      const pts = [...this._pointers.values()];
      this._pinch = {
        dist: distance(pts[0], pts[1]),
        mid: midpoint(pts[0], pts[1]),
        zoom: this.canvas.getZoom(),
        vpt: [...this.canvas.viewportTransform],
      };
      this.canvas.selection = false;
    }
  }

  _onPointerMove(event) {
    if (!this._pointers.has(event.pointerId)) {
      return;
    }
    this._pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this._pointers.size === 2 && this._pinch) {
      const pts = [...this._pointers.values()];
      const dist = distance(pts[0], pts[1]);
      const mid = midpoint(pts[0], pts[1]);
      const zoom = clamp(this._pinch.zoom * (dist / Math.max(this._pinch.dist, 1)), MIN_ZOOM, MAX_ZOOM);
      const vpt = [...this._pinch.vpt];
      vpt[0] = zoom;
      vpt[3] = zoom;
      vpt[4] += mid.x - this._pinch.mid.x;
      vpt[5] += mid.y - this._pinch.mid.y;
      this.canvas.setViewportTransform(vpt);
    }
  }

  _onPointerUp(event) {
    this._pointers.delete(event.pointerId);
    if (this._pointers.size < 2) {
      this._pinch = null;
      this._applySelectability();
    }
  }

  _bindObjectEvents() {
    this.canvas.on("object:modified", (opt) => {
      if (this.readOnly) {
        return;
      }
      const objects = this._targets(opt.target);
      const ops = [];
      for (const obj of objects) {
        const before = obj._boardBefore;
        const after = toRecord(obj);
        if (!before) {
          ops.push({ op: "patch", id: obj.id, patch: after.data });
          continue;
        }
        const patch = patchFromRecords(before, after);
        if (Object.keys(patch).length) {
          ops.push({ op: "patch", id: obj.id, patch });
        }
      }
      if (ops.length) {
        this.history.push(ops);
      }
    });
    this.canvas.on("before:transform", (opt) => {
      const target = opt.transform && opt.transform.target;
      for (const obj of this._targets(target)) {
        obj._boardBefore = toRecord(obj);
      }
    });
    this.canvas.on("editing:exited", (opt) => {
      const obj = opt.target;
      if (!obj || !obj.id || this.readOnly) {
        return;
      }
      const before = obj._boardBeforeText;
      const after = toRecord(obj);
      if (!before) {
        this.history.push([{ op: "patch", id: obj.id, patch: { text: after.data.text } }]);
        return;
      }
      const patch = patchFromRecords(before, after);
      if (Object.keys(patch).length) {
        this.history.push([{ op: "patch", id: obj.id, patch }]);
      }
    });
    this.canvas.on("editing:entered", (opt) => {
      if (opt.target) {
        opt.target._boardBeforeText = toRecord(opt.target);
      }
    });
  }

  _targets(target) {
    if (!target) {
      return [];
    }
    if (target.id && this._byId.has(target.id)) {
      return [target];
    }
    if (typeof target.getObjects === "function") {
      return target.getObjects().filter((item) => item.id && this._byId.has(item.id));
    }
    return [];
  }

  _applyOpsToCanvas(ops) {
    const selected = this.selectedObjects().map((obj) => obj.id);
    for (const op of ops) {
      if (op.op === "add" || op.op === "patch") {
        const record = this.store.get(op.id);
        if (record) {
          this._upsert(record);
        }
      } else if (op.op === "remove") {
        this._removeFromCanvas(op.id);
      } else if (op.op === "z") {
        this._syncZ();
      }
    }
    this._syncZ();
    const still = selected.map((id) => this._byId.get(id)).filter(Boolean);
    if (still.length === 1) {
      this.canvas.setActiveObject(still[0]);
    }
    this._applySelectability();
  }

  _upsert(record) {
    const existing = this._byId.get(record.id);
    if (existing) {
      this.canvas.remove(existing);
      this._byId.delete(record.id);
    }
    const obj = createFromRecord(record, this.classes);
    this.canvas.add(obj);
    this._byId.set(record.id, obj);
  }

  _removeFromCanvas(id) {
    const obj = this._byId.get(id);
    if (obj) {
      this.canvas.remove(obj);
      this._byId.delete(id);
    }
  }

  _syncZ() {
    const live = this.store.snapshot();
    live.forEach((record, index) => {
      const obj = this._byId.get(record.id);
      if (obj && this.canvas.moveObjectTo) {
        this.canvas.moveObjectTo(obj, index);
      }
    });
  }

  _isTyping(event) {
    const target = event.target;
    if (!target) {
      return false;
    }
    const tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      return true;
    }
    if (target.isContentEditable) {
      return true;
    }
    const active = this.canvas.getActiveObject();
    return Boolean(active && active.isEditing);
  }
}

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function distance(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function midpoint(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function sceneBounds(canvas, records, byId) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let found = false;
  for (const record of records) {
    const obj = byId.get(record.id);
    if (obj && typeof obj.getBoundingRect === "function") {
      const rect = obj.getBoundingRect(true);
      minX = Math.min(minX, rect.left);
      minY = Math.min(minY, rect.top);
      maxX = Math.max(maxX, rect.left + rect.width);
      maxY = Math.max(maxY, rect.top + rect.height);
      found = true;
      continue;
    }
    const data = record.data || {};
    if (data.x != null && data.y != null) {
      minX = Math.min(minX, data.x);
      minY = Math.min(minY, data.y);
      maxX = Math.max(maxX, data.x + (data.width || 0));
      maxY = Math.max(maxY, data.y + (data.height || 0));
      found = true;
    }
  }
  if (!found) {
    return null;
  }
  return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };
}

export function bindDragCreate(editor, { type, fromPoints }) {
  const canvas = editor.canvas;
  let start = null;
  let preview = null;

  function clearPreview() {
    if (preview) {
      canvas.remove(preview);
      preview = null;
    }
  }

  function onDown(opt) {
    if (editor.readOnly || editor.shouldIgnorePointer(opt)) {
      return;
    }
    if (opt.target && !opt.target.boardPreview) {
      return;
    }
    start = editor.scenePoint(opt);
    const extra = fromPoints(start, start, editor);
    preview = createFromRecord(
      { id: "preview", type, z: 0, data: editor.defaultData(type, extra) },
      editor.classes,
    );
    preview.boardPreview = true;
    preview.selectable = false;
    preview.evented = false;
    canvas.add(preview);
  }

  function onMove(opt) {
    if (!start || !preview) {
      return;
    }
    const end = editor.scenePoint(opt);
    const extra = fromPoints(start, end, editor);
    const record = {
      id: "preview",
      type,
      z: 0,
      data: editor.defaultData(type, extra),
    };
    canvas.remove(preview);
    preview = createFromRecord(record, editor.classes);
    preview.boardPreview = true;
    preview.selectable = false;
    preview.evented = false;
    canvas.add(preview);
  }

  function onUp(opt) {
    if (!start) {
      return;
    }
    const end = editor.scenePoint(opt);
    const extra = fromPoints(start, end, editor);
    clearPreview();
    start = null;
    const tooSmall =
      extra.width != null && extra.height != null && extra.width < 2 && extra.height < 2;
    if (tooSmall) {
      return;
    }
    editor.commitAdd(type, extra);
  }

  return {
    activate() {
      canvas.selection = false;
      canvas.on("mouse:down", onDown);
      canvas.on("mouse:move", onMove);
      canvas.on("mouse:up", onUp);
    },
    deactivate() {
      canvas.off("mouse:down", onDown);
      canvas.off("mouse:move", onMove);
      canvas.off("mouse:up", onUp);
      clearPreview();
      start = null;
    },
  };
}
