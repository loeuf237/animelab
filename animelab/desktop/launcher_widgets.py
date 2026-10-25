"""Qt rendering primitives; no web engine or downloaded fonts are required."""
import os
import sys
from PySide6.QtCore import QObject, Signal, Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette, QPen, QPainter
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle


class Value(QObject):
    changed = Signal(object)

    def __init__(self, value):
        super().__init__()
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        if self.value != value:
            self.value = value
            self.changed.emit(value)


class LauncherStyle(QProxyStyle):
    """Vector checkbox ticks stay crisp at every device pixel ratio."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor('#4386c9' if checked and enabled else '#a7aaad'), 1))
        painter.setBrush(QColor('#4b90d3' if checked and enabled else '#ffffff' if enabled else '#e4e5e6'))
        painter.drawRoundedRect(rect, 2, 2)
        if checked:
            painter.setPen(QPen(QColor('#ffffff' if enabled else '#92969a'), 1.8,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * .22, rect.top() + rect.height() * .50)
            path.lineTo(rect.left() + rect.width() * .43, rect.top() + rect.height() * .72)
            path.lineTo(rect.left() + rect.width() * .80, rect.top() + rect.height() * .28)
            painter.drawPath(path)
        painter.restore()


def application():
    app = QApplication.instance()
    if app is None:
        if sys.platform.startswith('linux') and 'gnome' in os.getenv('XDG_CURRENT_DESKTOP', '').lower():
            os.environ.setdefault('QT_QPA_PLATFORMTHEME', 'gtk3')
        app = QApplication(['AnimeLabLauncher'])
        app.setApplicationName('AnimeLab')
        app.setApplicationDisplayName('AnimeLab Desktop Launcher')
        app.setOrganizationName('AnimeLab')
        # Widgets use the OS text rasterizer/Fontconfig, never Tk bitmap fonts.
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
        font.setPointSizeF(10 if sys.platform == 'darwin' else 9)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
        app.setStyle(LauncherStyle('Fusion'))
        palette = app.palette()
        for role, color in ((QPalette.ColorRole.Window, '#f4f4f4'),
                            (QPalette.ColorRole.WindowText, '#202124'),
                            (QPalette.ColorRole.Base, '#ffffff'),
                            (QPalette.ColorRole.Text, '#202124'),
                            (QPalette.ColorRole.Button, '#f7f7f7'),
                            (QPalette.ColorRole.ButtonText, '#202124'),
                            (QPalette.ColorRole.Highlight, '#4389ce'),
                            (QPalette.ColorRole.HighlightedText, '#ffffff')):
            palette.setColor(role, QColor(color))
        app.setPalette(palette)
    return app
