export function createEraserTool(editor) {
  function onDown(opt) {
    if (editor.readOnly || editor.shouldIgnorePointer(opt)) {
      return;
    }
    const target = opt.target;
    if (target && target.id) {
      editor.history.push([{ op: "remove", id: target.id }]);
    }
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
