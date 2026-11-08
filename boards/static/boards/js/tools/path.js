import { PencilBrush } from "../../vendor/fabric.min.mjs";
import { pointsFromPathCommands } from "../serialize.js";

export function createPathTool(editor) {
  const canvas = editor.canvas;

  function onPath(opt) {
    const path = opt.path;
    if (path) {
      canvas.remove(path);
    }
    if (editor.readOnly) {
      return;
    }
    const commands = path && path.path;
    let points = pointsFromPathCommands(commands);
    if (!points.length && path) {
      const left = path.left || 0;
      const top = path.top || 0;
      points = [[left, top]];
    }
    if (points.length < 2) {
      return;
    }
    const xs = points.map((pair) => pair[0]);
    const ys = points.map((pair) => pair[1]);
    editor.commitAdd("path", {
      points,
      x: Math.min(...xs),
      y: Math.min(...ys),
      width: Math.max(...xs) - Math.min(...xs),
      height: Math.max(...ys) - Math.min(...ys),
      fill: "transparent",
      stroke: editor.styles.stroke,
      strokeWidth: editor.styles.strokeWidth,
    });
  }

  return {
    activate() {
      const brush = new PencilBrush(canvas);
      brush.color = editor.styles.stroke;
      brush.width = editor.styles.strokeWidth;
      canvas.freeDrawingBrush = brush;
      canvas.isDrawingMode = true;
      canvas.on("path:created", onPath);
    },
    deactivate() {
      canvas.isDrawingMode = false;
      canvas.off("path:created", onPath);
    },
  };
}
