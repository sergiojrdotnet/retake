import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    property alias text: field.text
    property string placeholder: ""
    property string action: ""
    property string target: ""
    property bool done: false
    signal submitted(string action, string target, string text)
    width: Math.min(parent.width - 60, 520)
    standardButtons: Dialog.Ok | Dialog.Cancel
    onOpened: { done = false; field.forceActiveFocus(); field.selectAll() }
    // Enter in the field and the dialog's own Ok can both accept; submit only once.
    onAccepted: {
        if (done || field.text.trim() === "")
            return
        done = true
        dialog.submitted(dialog.action, dialog.target, field.text.trim())
    }

    function ask(title, action, target, text, placeholder) {
        dialog.title = title
        dialog.action = action
        dialog.target = target
        dialog.placeholder = placeholder || ""
        field.text = text || ""
        open()
    }

    TextField {
        id: field
        anchors.left: parent.left
        anchors.right: parent.right
        placeholderText: dialog.placeholder
        onAccepted: if (!dialog.done) dialog.accept()
    }
}
