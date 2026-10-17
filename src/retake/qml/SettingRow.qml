import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: row
    property string label
    property string hint
    property string section
    property string key
    property string type: "combo"
    property var options: []
    property real from: 0
    property real to: 100
    property real step: 1
    property int decimals: 0
    property string zeroText: ""
    property var value: app.settings[section] ? app.settings[section][key] : undefined
    Layout.fillWidth: true
    spacing: 16

    function store(v) { app.setSetting(section, key, v) }

    ColumnLayout {
        Layout.preferredWidth: 260
        spacing: 0
        Label { text: row.label }
        Label { visible: row.hint !== ""; text: row.hint; font.pixelSize: 12; opacity: 0.5; wrapMode: Text.Wrap; Layout.preferredWidth: 260 }
    }

    ComboBox {
        visible: row.type === "combo"
        Layout.fillWidth: true
        model: row.options.map(o => o[1])
        currentIndex: Math.max(0, row.options.findIndex(o => o[0] === row.value))
        onActivated: (index) => row.store(row.options[index][0])
    }
    Switch {
        visible: row.type === "switch"
        checked: row.value === true
        onToggled: row.store(checked)
    }
    Item { visible: row.type === "switch"; Layout.fillWidth: true }
    Slider {
        id: slider
        visible: row.type === "slider"
        Layout.fillWidth: true
        from: row.from
        to: row.to
        stepSize: row.step
        value: typeof row.value === "number" ? row.value : row.from
        onMoved: row.store(row.decimals > 0 ? Number(value.toFixed(row.decimals)) : Math.round(value))
    }
    Label {
        visible: row.type === "slider"
        text: typeof row.value === "number" ? (row.value === 0 && row.zeroText !== "" ? row.zeroText : row.value.toFixed(row.decimals)) : ""
        Layout.preferredWidth: 48
    }
    TextField {
        visible: row.type === "text" || row.type === "password"
        Layout.fillWidth: true
        text: row.value !== undefined ? String(row.value) : ""
        echoMode: row.type === "password" ? TextInput.Password : TextInput.Normal
        onEditingFinished: row.store(text)
    }
}
