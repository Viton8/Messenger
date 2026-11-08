export function createStickerTool(editor) {
  function onDown(opt) {
    if (editor.readOnly || editor.shouldIgnorePointer(opt)) {
      return;
    }
    if (opt.target && opt.target.id) {
      return;
    }
    const point = editor.scenePoint(opt);
    editor.commitAdd("sticker", {
      x: point.x,
      y: point.y,
      width: 160,
      height: 120,
      text: "Note",
      fill: "#f5e6a3",
      stroke: "#333333",
    });
    editor.setTool("select");
  }

  return {
    activate() {
      editor.canvas.selection = false;
      editor.canvas.on("mouse:down", onDown);
    },
    deactivate() {
      editor.canvas.off("mouse:down", onDown);
    },
  };
}
