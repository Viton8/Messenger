import { bindDragCreate } from "../editor.js";

function fromPoints(start, end) {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  return {
    x: left,
    y: top,
    width: Math.max(1, Math.abs(end.x - start.x)),
    height: Math.max(1, Math.abs(end.y - start.y)),
  };
}

export function createEllipseTool(editor) {
  return bindDragCreate(editor, { type: "ellipse", fromPoints });
}
