import QtQuick

Image {
    property real size: 48
    width: size
    height: size
    sourceSize.width: size * 2
    sourceSize.height: size * 2
    source: theme.logo
    smooth: true
}
