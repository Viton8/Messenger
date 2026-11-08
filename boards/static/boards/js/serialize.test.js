import { test } from "node:test";
import assert from "node:assert/strict";
import {
  sanitizeProperties,
  toRecord,
  fabricPropsFromRecord,
  patchFromRecords,
  pointsFromPathCommands,
  decimatePoints,
  PATH_POINTS_MAX,
  TEXT_MAX,
} from "./serialize.js";

const ID = "00000000-0000-0000-0000-000000000001";

test("sanitize drops unknown fields and src/url", () => {
  const data = sanitizeProperties("rect", {
    x: 10,
    y: 20,
    width: 30,
    height: 40,
    src: "https://evil.example/x.png",
    url: "https://evil.example/",
    extra: true,
  });
  assert.deepEqual(data, { x: 10, y: 20, width: 30, height: 40 });
});

test("unknown type is rejected", () => {
  assert.throws(() => sanitizeProperties("image", { x: 1 }), /Unknown object type/);
});

test("invalid color is dropped", () => {
  const data = sanitizeProperties("rect", {
    x: 0,
    y: 0,
    width: 1,
    height: 1,
    fill: "red",
    stroke: "#0f0",
  });
  assert.equal(data.fill, undefined);
  assert.equal(data.stroke, "#0f0");
});

test("text is capped", () => {
  const data = sanitizeProperties("textbox", {
    x: 0,
    y: 0,
    width: 10,
    height: 10,
    text: "a".repeat(TEXT_MAX + 20),
  });
  assert.equal(data.text.length, TEXT_MAX);
});

test("toRecord maps left/top to x/y without toJSON", () => {
  const record = toRecord({
    id: ID,
    boardType: "rect",
    left: 8,
    top: 9,
    width: 12,
    height: 14,
    fill: "#abc",
    stroke: "#000000",
    strokeWidth: 3,
    angle: 15,
    scaleX: 1,
    scaleY: 1,
    opacity: 1,
  });
  assert.equal(record.id, ID);
  assert.equal(record.type, "rect");
  assert.equal(record.data.x, 8);
  assert.equal(record.data.y, 9);
  assert.equal(record.data.width, 12);
  assert.equal(record.data.fill, "#abc");
});

test("fabricPropsFromRecord maps x/y back to left/top", () => {
  const props = fabricPropsFromRecord({
    id: ID,
    type: "rect",
    z: 0,
    data: { x: 5, y: 6, width: 7, height: 8, fill: "#ffffff" },
  });
  assert.equal(props.left, 5);
  assert.equal(props.top, 6);
  assert.equal(props.boardType, "rect");
  assert.equal(props.id, ID);
});

test("patchFromRecords keeps only changed keys", () => {
  const before = { id: ID, type: "rect", data: { x: 1, y: 2, fill: "#000" } };
  const after = { id: ID, type: "rect", data: { x: 9, y: 2, fill: "#000" } };
  assert.deepEqual(patchFromRecords(before, after), { x: 9 });
});

test("path needs points on full sanitize", () => {
  assert.throws(() => sanitizeProperties("path", { x: 0, y: 0 }), /Path objects need points/);
  const data = sanitizeProperties("path", { points: [[1, 2], [3, 4]] });
  assert.deepEqual(data.points, [[1, 2], [3, 4]]);
});

test("pointsFromPathCommands reads SVG command lists", () => {
  const points = pointsFromPathCommands([
    ["M", 0, 0],
    ["Q", 10, 10, 20, 0],
  ]);
  assert.deepEqual(points, [[0, 0], [10, 10], [20, 0]]);
});

test("decimatePoints respects the protocol cap", () => {
  const many = Array.from({ length: PATH_POINTS_MAX + 80 }, (_, i) => [i, i]);
  const out = decimatePoints(many);
  assert.equal(out.length, PATH_POINTS_MAX);
  assert.deepEqual(out[0], [0, 0]);
  assert.deepEqual(out[out.length - 1], many[many.length - 1]);
});
