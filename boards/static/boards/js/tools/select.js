export function createSelectTool(editor) {
  return {
    name: "select",
    activate() {
      editor.canvas.isDrawingMode = false;
      editor.canvas.selection = !editor.readOnly;
      editor.canvas.skipTargetFind = editor.readOnly;
    },
    deactivate() {},
  };
}
