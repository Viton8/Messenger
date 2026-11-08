/**
 * Map board objects to the server whitelist. Never use Fabric toJSON/loadFromJSON.
 *
 * A fabric-like object is a plain dict or anything with get(key) plus the usual
 * geometry fields (left, top, width, ...). Tests can pass plain objects.
 */

export const ALLOWED_TYPES = new Set([
  "rect",
  "ellipse",
  "line",
  "path",
  "textbox",
  "arrow",
  "sticker",
]);

export const FONT_FAMILIES = new Set([
  "sans-serif",
  "serif",
  "monospace",
  "Georgia",
  "Verdana",
  "Comic Sans MS",
]);

export const COMMON_KEYS = [
  "x",
  "y",
  "width",
  "height",
  "angle",
  "scaleX",
  "scaleY",
  "fill",
  "stroke",
  "strokeWidth",
  "opacity",
];

export const KEYS_BY_TYPE = {
  rect: new Set(COMMON_KEYS),
  ellipse: new Set(COMMON_KEYS),
  line: new Set([...COMMON_KEYS, "x1", "y1", "x2", "y2"]),
  arrow: new Set([...COMMON_KEYS, "x1", "y1", "x2", "y2"]),
  path: new Set([...COMMON_KEYS, "points"]),
  textbox: new Set([...COMMON_KEYS, "text", "fontSize", "fontFamily"]),
  sticker: new Set([...COMMON_KEYS, "text", "fontSize", "fontFamily"]),
};

export const COORD_MIN = -100000;
export const COORD_MAX = 100000;
export const SIZE_MIN = 0;
export const SIZE_MAX = 20000;
export const ANGLE_MIN = -360;
export const ANGLE_MAX = 360;
export const SCALE_MIN = 0.01;
export const SCALE_MAX = 100;
export const OPACITY_MIN = 0;
export const OPACITY_MAX = 1;
export const STROKE_MIN = 0;
export const STROKE_MAX = 80;
export const FONT_SIZE_MIN = 8;
export const FONT_SIZE_MAX = 400;
export const PATH_POINTS_MAX = 500;
export const TEXT_MAX = 2000;

const COLOR_RE = /^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$/;

export function getProp(obj, key) {
  if (obj == null) {
    return undefined;
  }
  if (typeof obj.get === "function") {
    const value = obj.get(key);
    if (value !== undefined) {
      return value;
    }
  }
  return obj[key];
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function clampNumber(value, lo, hi) {
  if (!isNumber(value)) {
    return null;
  }
  if (value < lo || value > hi) {
    return null;
  }
  return value;
}

function cleanColor(value) {
  if (value === "transparent") {
    return value;
  }
  if (typeof value === "string" && COLOR_RE.test(value)) {
    return value;
  }
  return null;
}

function cleanPoints(value) {
  if (!Array.isArray(value)) {
    return null;
  }
  const sliced = value.slice(0, PATH_POINTS_MAX);
  const points = [];
  for (const item of sliced) {
    let x;
    let y;
    if (Array.isArray(item) && item.length >= 2) {
      x = item[0];
      y = item[1];
    } else if (item && isNumber(item.x) && isNumber(item.y)) {
      x = item.x;
      y = item.y;
    } else {
      continue;
    }
    const cx = clampNumber(x, COORD_MIN, COORD_MAX);
    const cy = clampNumber(y, COORD_MIN, COORD_MAX);
    if (cx === null || cy === null) {
      continue;
    }
    points.push([cx, cy]);
  }
  return points;
}

function cleanField(key, value) {
  if (key === "x" || key === "y" || key === "x1" || key === "y1" || key === "x2" || key === "y2") {
    return clampNumber(value, COORD_MIN, COORD_MAX);
  }
  if (key === "width" || key === "height") {
    return clampNumber(value, SIZE_MIN, SIZE_MAX);
  }
  if (key === "angle") {
    return clampNumber(value, ANGLE_MIN, ANGLE_MAX);
  }
  if (key === "scaleX" || key === "scaleY") {
    return clampNumber(value, SCALE_MIN, SCALE_MAX);
  }
  if (key === "opacity") {
    return clampNumber(value, OPACITY_MIN, OPACITY_MAX);
  }
  if (key === "strokeWidth") {
    return clampNumber(value, STROKE_MIN, STROKE_MAX);
  }
  if (key === "fontSize") {
    return clampNumber(value, FONT_SIZE_MIN, FONT_SIZE_MAX);
  }
  if (key === "fill" || key === "stroke") {
    return cleanColor(value);
  }
  if (key === "fontFamily") {
    return typeof value === "string" && FONT_FAMILIES.has(value) ? value : null;
  }
  if (key === "text") {
    if (typeof value !== "string") {
      return null;
    }
    return value.slice(0, TEXT_MAX);
  }
  if (key === "points") {
    return cleanPoints(value);
  }
  return null;
}

export function sanitizeProperties(objType, raw, partial = false) {
  if (!ALLOWED_TYPES.has(objType)) {
    throw new Error("Unknown object type.");
  }
  const source = raw && typeof raw === "object" ? raw : {};
  const allowed = KEYS_BY_TYPE[objType];
  const out = {};
  for (const [key, value] of Object.entries(source)) {
    if (key === "type" || !allowed.has(key)) {
      continue;
    }
    const cleaned = cleanField(key, value);
    if (cleaned !== null) {
      out[key] = cleaned;
    }
  }
  if (!partial && objType === "path" && !("points" in out)) {
    throw new Error("Path objects need points.");
  }
  return out;
}

export function applyMatrix(matrix, x, y) {
  return [
    matrix[0] * x + matrix[2] * y + matrix[4],
    matrix[1] * x + matrix[3] * y + matrix[5],
  ];
}

function lineEndpoints(obj) {
  if (typeof obj.calcLinePoints === "function" && typeof obj.getCenterPoint === "function") {
    const local = obj.calcLinePoints();
    const center = obj.getCenterPoint();
    const angle = ((getProp(obj, "angle") || 0) * Math.PI) / 180;
    const scaleX = getProp(obj, "scaleX") ?? 1;
    const scaleY = getProp(obj, "scaleY") ?? 1;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const mapPoint = (x, y) => {
      const sx = x * scaleX;
      const sy = y * scaleY;
      return {
        x: center.x + sx * cos - sy * sin,
        y: center.y + sx * sin + sy * cos,
      };
    };
    const start = mapPoint(local.x1, local.y1);
    const end = mapPoint(local.x2, local.y2);
    return { x1: start.x, y1: start.y, x2: end.x, y2: end.y };
  }
  return {
    x1: getProp(obj, "x1"),
    y1: getProp(obj, "y1"),
    x2: getProp(obj, "x2"),
    y2: getProp(obj, "y2"),
  };
}

function pathPoints(obj) {
  const raw = getProp(obj, "points") || getProp(obj, "boardPoints");
  if (!raw) {
    return undefined;
  }
  const matrix = typeof obj.calcTransformMatrix === "function" ? obj.calcTransformMatrix() : null;
  const offset = getProp(obj, "pathOffset");
  const mapped = [];
  for (const item of raw) {
    let x;
    let y;
    if (Array.isArray(item)) {
      x = item[0];
      y = item[1];
    } else if (item && isNumber(item.x) && isNumber(item.y)) {
      x = item.x;
      y = item.y;
    } else {
      continue;
    }
    if (offset && isNumber(offset.x) && isNumber(offset.y)) {
      x -= offset.x;
      y -= offset.y;
    }
    if (matrix) {
      const scene = applyMatrix(matrix, x, y);
      mapped.push(scene);
    } else {
      const left = getProp(obj, "left") || 0;
      const top = getProp(obj, "top") || 0;
      mapped.push([x + left, y + top]);
    }
  }
  return mapped;
}

export function objectType(obj) {
  const boardType = getProp(obj, "boardType");
  if (ALLOWED_TYPES.has(boardType)) {
    return boardType;
  }
  const raw = String(getProp(obj, "type") || "").toLowerCase();
  if (raw === "rect") {
    return "rect";
  }
  if (raw === "ellipse") {
    return "ellipse";
  }
  if (raw === "line") {
    return "line";
  }
  if (raw === "arrow") {
    return "arrow";
  }
  if (raw === "path" || raw === "polyline") {
    return "path";
  }
  if (raw === "textbox" || raw === "i-text" || raw === "text") {
    return "textbox";
  }
  if (raw === "sticker") {
    return "sticker";
  }
  throw new Error("Unknown object type.");
}

export function toRecord(obj) {
  const type = objectType(obj);
  const raw = {
    x: getProp(obj, "left"),
    y: getProp(obj, "top"),
    width: getProp(obj, "width"),
    height: getProp(obj, "height"),
    angle: getProp(obj, "angle") || 0,
    scaleX: getProp(obj, "scaleX") ?? 1,
    scaleY: getProp(obj, "scaleY") ?? 1,
    fill: getProp(obj, "fill"),
    stroke: getProp(obj, "stroke"),
    strokeWidth: getProp(obj, "strokeWidth"),
    opacity: getProp(obj, "opacity") ?? 1,
  };
  if (type === "sticker") {
    raw.fill = getProp(obj, "backgroundColor") ?? raw.fill;
    raw.stroke = getProp(obj, "fill") ?? raw.stroke;
  }
  if (type === "line" || type === "arrow") {
    Object.assign(raw, lineEndpoints(obj));
  }
  if (type === "path") {
    raw.points = pathPoints(obj);
  }
  if (type === "textbox" || type === "sticker") {
    raw.text = getProp(obj, "text") || "";
    raw.fontSize = getProp(obj, "fontSize");
    raw.fontFamily = getProp(obj, "fontFamily");
  }
  const data = sanitizeProperties(type, raw, false);
  return {
    id: String(getProp(obj, "id")),
    type,
    z: getProp(obj, "boardZ") ?? 0,
    data,
  };
}

export function patchFromRecords(before, after) {
  const patch = {};
  const keys = new Set([...Object.keys(before.data || {}), ...Object.keys(after.data || {})]);
  for (const key of keys) {
    const left = before.data[key];
    const right = after.data[key];
    if (JSON.stringify(left) !== JSON.stringify(right)) {
      patch[key] = right;
    }
  }
  return patch;
}

export function fabricPropsFromRecord(record) {
  const data = record.data || {};
  const props = {
    id: record.id,
    boardType: record.type,
    left: data.x ?? 0,
    top: data.y ?? 0,
    width: data.width ?? 100,
    height: data.height ?? 100,
    angle: data.angle ?? 0,
    scaleX: data.scaleX ?? 1,
    scaleY: data.scaleY ?? 1,
    fill: data.fill ?? "transparent",
    stroke: data.stroke ?? "#e8eaed",
    strokeWidth: data.strokeWidth ?? 2,
    opacity: data.opacity ?? 1,
    originX: "left",
    originY: "top",
    objectCaching: false,
  };
  if (typeUsesText(record.type)) {
    props.text = data.text ?? "";
    props.fontSize = data.fontSize ?? 24;
    props.fontFamily = data.fontFamily ?? "sans-serif";
  }
  if (record.type === "sticker") {
    props.backgroundColor = data.fill ?? "#f5e6a3";
    props.fill = data.stroke ?? "#333333";
    props.stroke = "transparent";
    props.strokeWidth = 0;
  }
  if (record.type === "ellipse") {
    props.rx = (data.width ?? 0) / 2;
    props.ry = (data.height ?? 0) / 2;
  }
  if (record.type === "path") {
    props.points = (data.points || []).map(([x, y]) => ({ x, y }));
    props.fill = data.fill ?? "transparent";
  }
  if (record.type === "line" || record.type === "arrow") {
    props.x1 = data.x1 ?? 0;
    props.y1 = data.y1 ?? 0;
    props.x2 = data.x2 ?? 0;
    props.y2 = data.y2 ?? 0;
    props.fill = "";
    props.originX = "center";
    props.originY = "center";
  }
  return props;
}

function typeUsesText(type) {
  return type === "textbox" || type === "sticker";
}

export function createFromRecord(record, classes) {
  const type = record.type;
  if (!ALLOWED_TYPES.has(type)) {
    throw new Error("Unknown object type.");
  }
  const Ctor = classes[type];
  if (!Ctor) {
    throw new Error("Missing constructor for " + type);
  }
  const props = fabricPropsFromRecord(record);
  let obj;
  if (type === "line" || type === "arrow") {
    const lineProps = { ...props };
    delete lineProps.left;
    delete lineProps.top;
    obj = new Ctor([props.x1, props.y1, props.x2, props.y2], lineProps);
  } else if (type === "path") {
    const pathProps = { ...props };
    delete pathProps.left;
    delete pathProps.top;
    obj = new Ctor(props.points, pathProps);
  } else if (typeUsesText(type)) {
    obj = new Ctor(props.text, props);
  } else {
    obj = new Ctor(props);
  }
  if (typeof obj.set === "function") {
    obj.set({ id: record.id, boardType: type, boardZ: record.z ?? 0 });
  } else {
    obj.id = record.id;
    obj.boardType = type;
    obj.boardZ = record.z ?? 0;
  }
  return obj;
}

export function applyProps(obj, record) {
  const props = fabricPropsFromRecord(record);
  const skip = new Set(["x1", "y1", "x2", "y2", "points", "text"]);
  const next = {};
  for (const [key, value] of Object.entries(props)) {
    if (skip.has(key)) {
      continue;
    }
    next[key] = value;
  }
  if (typeof obj.set === "function") {
    obj.set(next);
    if (record.type === "line" || record.type === "arrow") {
      obj.set({ x1: props.x1, y1: props.y1, x2: props.x2, y2: props.y2 });
    }
    if (record.type === "path" && props.points) {
      obj.set({ points: props.points });
    }
    if (typeUsesText(record.type)) {
      obj.set({ text: props.text });
    }
    obj.set({ id: record.id, boardType: record.type, boardZ: record.z ?? 0 });
  } else {
    Object.assign(obj, next, {
      id: record.id,
      boardType: record.type,
      boardZ: record.z ?? 0,
    });
  }
  if (typeof obj.setCoords === "function") {
    obj.setCoords();
  }
}

export function decimatePoints(points, maxPoints = PATH_POINTS_MAX) {
  if (!Array.isArray(points) || points.length <= maxPoints) {
    return points || [];
  }
  const step = (points.length - 1) / (maxPoints - 1);
  const out = [];
  for (let i = 0; i < maxPoints; i += 1) {
    const idx = Math.round(i * step);
    out.push(points[idx]);
  }
  return out;
}

export function pointsFromPathCommands(pathCommands) {
  const points = [];
  if (!Array.isArray(pathCommands)) {
    return points;
  }
  for (const cmd of pathCommands) {
    if (!cmd) {
      continue;
    }
    const values = Array.isArray(cmd) ? cmd.slice(1) : [];
    for (let i = 0; i + 1 < values.length; i += 2) {
      if (isNumber(values[i]) && isNumber(values[i + 1])) {
        points.push([values[i], values[i + 1]]);
      }
    }
  }
  return decimatePoints(points);
}
