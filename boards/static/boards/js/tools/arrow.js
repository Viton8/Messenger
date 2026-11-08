import { bindDragCreate } from "../editor.js";

function fromPoints(start, end) {
  return {
    x1: start.x,
    y1: start.y,
    x2: end.x,
    y2: end.y,
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
    fill: "transparent",
  };
}

export function createArrowTool(editor) {
  return bindDragCreate(editor, { type: "arrow", fromPoints });
}
