const TOOLS = [
  { name: "select", label: "Select", shortcut: "V" },
  { name: "rect", label: "Rectangle", shortcut: "R" },
  { name: "ellipse", label: "Ellipse", shortcut: "O" },
  { name: "line", label: "Line", shortcut: "L" },
  { name: "arrow", label: "Arrow", shortcut: "A" },
  { name: "textbox", label: "Text", shortcut: "T" },
  { name: "sticker", label: "Sticker", shortcut: "S" },
  { name: "path", label: "Draw", shortcut: "P" },
  { name: "eraser", label: "Eraser", shortcut: "E" },
];

const HELP_ITEMS = [
  ["V", "Select"],
  ["R", "Rectangle"],
  ["O", "Ellipse"],
  ["L", "Line"],
  ["A", "Arrow"],
  ["T", "Text"],
  ["S", "Sticker"],
  ["P", "Free draw"],
  ["E", "Eraser"],
  ["Delete", "Delete selection"],
  ["Ctrl+D", "Duplicate"],
  ["Ctrl+Z", "Undo"],
  ["Ctrl+Shift+Z / Ctrl+Y", "Redo"],
  ["[", "Send to back"],
  ["]", "Bring to front"],
  ["Space+drag", "Pan"],
  ["Middle mouse", "Pan"],
  ["Wheel / pinch", "Zoom"],
  ["Ctrl+0", "Fit all"],
  ["?", "This help"],
];

export function bindBoardUi(editor, root) {
  const toolbar = root.querySelector("[data-board-toolbar]");
  const help = root.querySelector("[data-board-help]");
  const fillInput = root.querySelector("[data-board-fill]");
  const strokeInput = root.querySelector("[data-board-stroke]");
  const widthInput = root.querySelector("[data-board-stroke-width]");
  const fontInput = root.querySelector("[data-board-font-size]");
  const connEl = root.querySelector("[data-board-conn]");
  const presenceEl = root.querySelector("[data-board-presence]");
  const overlayEl = root.querySelector("[data-board-reconnect]");
  const lockEl = root.querySelector("[data-board-lock]");
  const readOnlyEl = root.querySelector("[data-board-readonly]");
  const toastsEl = root.querySelector("[data-board-toasts]");
  const cursorLayer = root.querySelector("[data-board-cursors]");
  const cursors = new Map();
  let cursorTick = false;

  function syncToolButtons() {
    toolbar.querySelectorAll("[data-tool]").forEach((button) => {
      const active = button.getAttribute("data-tool") === editor.toolName;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.classList.toggle("is-active", active);
    });
  }

  function syncStyles() {
    if (fillInput) {
      fillInput.value = toColorInput(editor.styles.fill);
    }
    if (strokeInput) {
      strokeInput.value = toColorInput(editor.styles.stroke);
    }
    if (widthInput) {
      widthInput.value = String(editor.styles.strokeWidth);
    }
    if (fontInput) {
      fontInput.value = String(editor.styles.fontSize);
    }
  }

  function onToolbarClick(event) {
    const button = event.target.closest("button");
    if (!button) {
      return;
    }
    const tool = button.getAttribute("data-tool");
    if (tool) {
      editor.setTool(tool);
      return;
    }
    const action = button.getAttribute("data-action");
    if (action === "undo") {
      editor.history.undo();
    } else if (action === "redo") {
      editor.history.redo();
    } else if (action === "front") {
      editor.bringToFront();
    } else if (action === "back") {
      editor.sendToBack();
    } else if (action === "zoom-in") {
      editor.zoomBy(1.15);
    } else if (action === "zoom-out") {
      editor.zoomBy(1 / 1.15);
    } else if (action === "fit") {
      editor.fitAll();
    } else if (action === "export-view") {
      editor.downloadPng(false);
    } else if (action === "export-all") {
      editor.downloadPng(true);
    } else if (action === "help") {
      if (help && help.showModal) {
        help.showModal();
      }
    } else if (action === "delete") {
      editor.deleteSelection();
    } else if (action === "duplicate") {
      editor.duplicateSelection();
    }
  }

  toolbar.addEventListener("click", onToolbarClick);
  const hud = root.querySelector(".board-hud");
  if (hud) {
    hud.addEventListener("click", onToolbarClick);
  }

  function onStyleChange() {
    if (fillInput) {
      editor.styles.fill = fillInput.value;
    }
    if (strokeInput) {
      editor.styles.stroke = strokeInput.value;
    }
    if (widthInput) {
      editor.styles.strokeWidth = Number(widthInput.value) || 2;
    }
    if (fontInput) {
      editor.styles.fontSize = Number(fontInput.value) || 24;
    }
    editor.applyStylesToSelection();
  }

  fillInput && fillInput.addEventListener("input", onStyleChange);
  strokeInput && strokeInput.addEventListener("input", onStyleChange);
  widthInput && widthInput.addEventListener("change", onStyleChange);
  fontInput && fontInput.addEventListener("change", onStyleChange);

  function applyReadOnly() {
    const locked = editor.readOnly;
    toolbar.querySelectorAll("[data-tool], [data-edit-only]").forEach((el) => {
      el.hidden = locked;
      el.disabled = locked;
    });
    root.setAttribute("data-read-only", locked ? "true" : "false");
  }

  function setReadOnlyBadge(show) {
    if (readOnlyEl) {
      readOnlyEl.hidden = !show;
    }
  }

  function notice(text) {
    if (!toastsEl || !text) {
      return;
    }
    const item = document.createElement("div");
    item.className = "board-toast";
    item.textContent = text;
    toastsEl.appendChild(item);
    setTimeout(() => item.remove(), 4000);
  }

  function setConn(state) {
    if (!connEl) {
      return;
    }
    const labels = {
      live: "В сети",
      connecting: "Переподключение",
      reconnecting: "Переподключение",
      closed: "Нет связи",
    };
    connEl.textContent = labels[state] || labels.connecting;
    connEl.setAttribute("data-state", state);
  }

  function setReconnecting(show) {
    if (overlayEl) {
      overlayEl.hidden = !show;
    }
  }

  function setLockedBadge(isLocked) {
    if (lockEl) {
      lockEl.hidden = !isLocked;
    }
  }

  function setPresence(users) {
    if (!presenceEl) {
      return;
    }
    presenceEl.replaceChildren();
    for (const user of users || []) {
      const chip = document.createElement("span");
      chip.className = "board-presence__user";
      chip.title = user.username || "";
      chip.style.setProperty("--board-user-color", user.color || "#5b5bd6");
      const mark = document.createElement("span");
      mark.className = "board-presence__avatar";
      mark.textContent = (user.username || "?").slice(0, 1).toUpperCase();
      const name = document.createElement("span");
      name.className = "board-presence__name";
      name.textContent = user.username || "";
      chip.append(mark, name);
      presenceEl.appendChild(chip);
    }
  }

  function screenPos(x, y) {
    const vpt = editor.canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
    return { left: x * vpt[0] + vpt[4], top: y * vpt[3] + vpt[5] };
  }

  function renderCursors() {
    cursorTick = false;
    for (const cur of cursors.values()) {
      const pos = screenPos(cur.x, cur.y);
      cur.el.style.transform = `translate(${pos.left}px, ${pos.top}px)`;
    }
    if (cursors.size) {
      cursorTick = true;
      requestAnimationFrame(renderCursors);
    }
  }

  function showCursor(msg) {
    if (!cursorLayer || !msg || !msg.user) {
      return;
    }
    const id = String(msg.user.id);
    let cur = cursors.get(id);
    if (!cur) {
      const el = document.createElement("div");
      el.className = "board-cursor";
      el.innerHTML =
        '<svg class="board-cursor__arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M1 1 L15 7 L8 9 L6 15 Z"/></svg>' +
        '<span class="board-cursor__name"></span>';
      cursorLayer.appendChild(el);
      cur = { el, x: 0, y: 0, timer: null };
      cursors.set(id, cur);
    }
    cur.x = Number(msg.x) || 0;
    cur.y = Number(msg.y) || 0;
    cur.el.style.setProperty("--board-cursor-color", msg.user.color || "#5b5bd6");
    const label = cur.el.querySelector(".board-cursor__name");
    if (label) {
      label.textContent = msg.user.username || "";
    }
    if (cur.timer) {
      clearTimeout(cur.timer);
    }
    cur.timer = setTimeout(() => hideCursor(id), 5000);
    if (!cursorTick) {
      cursorTick = true;
      requestAnimationFrame(renderCursors);
    }
  }

  function hideCursor(userId) {
    const cur = cursors.get(String(userId));
    if (!cur) {
      return;
    }
    if (cur.timer) {
      clearTimeout(cur.timer);
    }
    cur.el.remove();
    cursors.delete(String(userId));
  }

  editor.onToolChange(syncToolButtons);
  editor.onReadOnlyChange(applyReadOnly);
  syncToolButtons();
  syncStyles();
  applyReadOnly();

  window.addEventListener("keydown", (event) => {
    if (isTyping(event, editor)) {
      return;
    }
    if (event.key === "?" || (event.key === "/" && event.shiftKey)) {
      event.preventDefault();
      if (help && help.showModal) {
        help.open ? help.close() : help.showModal();
      }
      return;
    }
    if (event.key === "Escape" && help && help.open) {
      help.close();
      return;
    }
    const meta = event.ctrlKey || event.metaKey;
    if (meta && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) {
        editor.history.redo();
      } else {
        editor.history.undo();
      }
      return;
    }
    if (meta && event.key.toLowerCase() === "y") {
      event.preventDefault();
      editor.history.redo();
      return;
    }
    if (meta && event.key.toLowerCase() === "d") {
      event.preventDefault();
      editor.duplicateSelection();
      return;
    }
    if (meta && event.key === "0") {
      event.preventDefault();
      editor.fitAll();
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      editor.deleteSelection();
      return;
    }
    if (event.key === "[") {
      editor.sendToBack();
      return;
    }
    if (event.key === "]") {
      editor.bringToFront();
      return;
    }
    if (editor.readOnly) {
      return;
    }
    const tool = TOOLS.find((item) => item.shortcut.toLowerCase() === event.key.toLowerCase());
    if (tool && !meta) {
      editor.setTool(tool.name);
    }
  });

  return {
    notice,
    setConn,
    setReconnecting,
    setLockedBadge,
    setReadOnlyBadge,
    setPresence,
    showCursor,
    hideCursor,
  };
}

export { TOOLS, HELP_ITEMS };

function toColorInput(value) {
  if (typeof value === "string" && /^#[0-9A-Fa-f]{6}$/.test(value)) {
    return value;
  }
  if (typeof value === "string" && /^#[0-9A-Fa-f]{3}$/.test(value)) {
    return (
      "#" +
      value[1] +
      value[1] +
      value[2] +
      value[2] +
      value[3] +
      value[3]
    );
  }
  return "#5b5bd6";
}

function isTyping(event, editor) {
  const target = event.target;
  const tag = target && target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  if (target && target.isContentEditable) {
    return true;
  }
  const active = editor.canvas.getActiveObject();
  return Boolean(active && active.isEditing);
}
