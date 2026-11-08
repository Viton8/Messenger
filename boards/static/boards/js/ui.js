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

  toolbar.addEventListener("click", (event) => {
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
  });

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

  editor.onToolChange(syncToolButtons);
  syncToolButtons();
  syncStyles();

  if (editor.readOnly) {
    toolbar.querySelectorAll("[data-tool], [data-edit-only]").forEach((el) => {
      el.hidden = true;
      el.disabled = true;
    });
  }

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
  return "#c9a227";
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
