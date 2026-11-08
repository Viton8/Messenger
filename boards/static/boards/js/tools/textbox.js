export function createTextboxTool(editor) {
  function onDown(opt) {
    if (editor.readOnly || editor.shouldIgnorePointer(opt)) {
      return;
    }
    if (opt.target && opt.target.id) {
      return;
    }
    const point = editor.scenePoint(opt);
    editor.commitAdd("textbox", {
      x: point.x,
      y: point.y,
      width: 180,
      height: 48,
      text: "Text",
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
