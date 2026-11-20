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
        dark = option.palette.color(QPalette.ColorRole.Window).lightness() < 128
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
        accent_border = '#80d3dc' if dark else '#006874'
        accent_fill = '#80d3dc' if dark else '#006874'
        unchecked_border = '#54696d' if dark else '#8fa0a4'
        unchecked_fill = '#111e21' if dark else '#ffffff'
        disabled_fill = '#18272a' if dark else '#e4e8e9'
        tick_color = '#00363c' if dark else '#ffffff'
        painter.setPen(QPen(QColor(accent_border if checked and enabled else unchecked_border), 1))
        painter.setBrush(QColor(accent_fill if checked and enabled else unchecked_fill if enabled else disabled_fill))
        painter.drawRoundedRect(rect, 3, 3)
        if checked:
            painter.setPen(QPen(QColor(tick_color if enabled else '#829397'), 1.8,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * .22, rect.top() + rect.height() * .50)
            path.lineTo(rect.left() + rect.width() * .43, rect.top() + rect.height() * .72)
            path.lineTo(rect.left() + rect.width() * .80, rect.top() + rect.height() * .28)
            painter.drawPath(path)
        painter.restore()


def _is_dark_system_theme(app) -> bool:
    try:
        hints = app.styleHints()
        if hasattr(hints, 'colorScheme'):
            return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        pass
    return False


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
        if sys.platform.startswith('linux') and 'DejaVu Sans' in QFontDatabase.families():
            font.setFamily('DejaVu Sans')
        font.setPointSizeF(10 if sys.platform == 'darwin' else 9)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
        app.setStyle(LauncherStyle('Fusion'))
        palette = app.palette()
        if _is_dark_system_theme(app):
            colors = ((QPalette.ColorRole.Window, '#0b1517'),
                      (QPalette.ColorRole.WindowText, '#dce7e9'),
                      (QPalette.ColorRole.Base, '#111e21'),
                      (QPalette.ColorRole.Text, '#dce7e9'),
                      (QPalette.ColorRole.Button, '#18272a'),
                      (QPalette.ColorRole.ButtonText, '#dce7e9'),
                      (QPalette.ColorRole.Highlight, '#80d3dc'),
                      (QPalette.ColorRole.HighlightedText, '#00363c'))
            disabled = '#829397'
        else:
            colors = ((QPalette.ColorRole.Window, '#f5fafb'),
                      (QPalette.ColorRole.WindowText, '#000000'),
                      (QPalette.ColorRole.Base, '#ffffff'),
                      (QPalette.ColorRole.Text, '#000000'),
                      (QPalette.ColorRole.Button, '#eaf2f3'),
                      (QPalette.ColorRole.ButtonText, '#000000'),
                      (QPalette.ColorRole.Highlight, '#006874'),
                      (QPalette.ColorRole.HighlightedText, '#ffffff'))
            disabled = '#647c81'
        for role, color in colors:
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled))
        app.setPalette(palette)
    return app
