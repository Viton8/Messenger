import { BoardStore } from "./store.js";
import { History } from "./history.js";
import { BoardEditor } from "./editor.js";
import { bindBoardUi } from "./ui.js";
import { BoardSync } from "./sync.js";
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
  const boardId = root.getAttribute("data-board-id");
  const loginUrl = root.getAttribute("data-login-url") || "/accounts/login/";
  const store = new BoardStore();
  const history = new History(store);
  const editor = new BoardEditor({ canvasEl, store, history, readOnly: true });
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
  const ui = bindBoardUi(editor, root);
  history.onStale = () => {
    ui.notice("часть действия уже изменена другим участником");
  };
  const sync = new BoardSync({
    boardId,
    store,
    history,
    loginUrl,
    onState(state) {
      ui.setConn(state);
      ui.setReconnecting(state !== "live" && state !== "closed");
      editor.setReadOnly(state !== "live" || !sync.canEdit);
      ui.setReadOnlyBadge(state === "live" && !sync.canEdit);
    },
    onCanEdit(value) {
      editor.setReadOnly(sync.state !== "live" || !value);
      ui.setReadOnlyBadge(sync.state === "live" && !value);
    },
    onLock(isLocked) {
      ui.setLockedBadge(isLocked);
    },
    onNotice: (text) => ui.notice(text),
    onPresence: (users) => ui.setPresence(users),
    onCursor: (msg) => ui.showCursor(msg),
    onTransient: (msg) => editor.applyRemoteTransient(msg),
    onPresenceEvent(msg) {
      if (msg.action === "leave" && msg.user) {
        editor.clearTransientsForUser(msg.user.id);
        ui.hideCursor(msg.user.id);
      }
    },
  });
  editor.sync = sync;
  ui.setConn(sync.state);
  ui.setReconnecting(true);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
