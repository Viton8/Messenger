import { BoardStore } from "./store.js";
import { History } from "./history.js";
import { BoardEditor } from "./editor.js";
import { bindBoardUi } from "./ui.js";
import { createSelectTool } from "./tools/select.js";
import { createRectTool } from "./tools/rect.js";
import { createEllipseTool } from "./tools/ellipse.js";
import { createLineTool } from "./tools/line.js";
import { createArrowTool } from "./tools/arrow.js";
import { createTextboxTool } from "./tools/textbox.js";
import { createStickerTool } from "./tools/sticker.js";
import { createPathTool } from "./tools/path.js";
import { createEraserTool } from "./tools/eraser.js";

function boot() {
  const root = document.querySelector("[data-board-root]");
  const canvasEl = document.getElementById("board-canvas");
  if (!root || !canvasEl) {
    return;
  }
  const readOnly = root.getAttribute("data-read-only") === "true";
  const store = new BoardStore();
  const history = new History(store);
  const editor = new BoardEditor({ canvasEl, store, history, readOnly });
  editor.registerTools({
    select: createSelectTool(editor),
    rect: createRectTool(editor),
    ellipse: createEllipseTool(editor),
    line: createLineTool(editor),
    arrow: createArrowTool(editor),
    textbox: createTextboxTool(editor),
    sticker: createStickerTool(editor),
    path: createPathTool(editor),
    eraser: createEraserTool(editor),
  });
  bindBoardUi(editor, root);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
