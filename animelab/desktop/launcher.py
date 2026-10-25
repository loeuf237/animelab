"""Compact Qt Widgets launcher. Engine operations never run on the GUI thread."""
from pathlib import Path
import queue
import sys
import threading
from PySide6.QtCore import QTimer, Qt, QTranslator, QLibraryInfo
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QToolButton, QButtonGroup, QStackedWidget, QLabel, QPushButton,
    QFrame, QMessageBox)

from animelab.diagnostics import redact_text
from .launcher_i18n import language, TEXT
from .launcher_model import LauncherModel
from .launcher_panels import build_page, TABS
from .launcher_widgets import Value, application
from .launcher_dialogs import save_file, choose_directory
from .options import normalize_config
from .state import write_json


class NativeLauncher(QWidget):
    def __init__(self, directory):
        super().__init__()
        self.setFont(QApplication.font())
        self.qt_translator = QTranslator(self)
        self.root, self.model = self, LauncherModel(directory)
        self.config = self.model.config()
        self.lang = language(self.config['launcher']['language'])
        self.variables = {key: Value(value) for key, value in self.config.items() if key != 'launcher'}
        self.variables.update({key: Value(value) for key, value in self.config['launcher'].items()})
        self.speed = Value(format(self.config['launcher']['globalSpeedLimit'] / 1024, 'g'))
        self.proxy_variables = {key: Value(value) for key, value in
            {'proxy_type': 'http', 'host': '', 'port': '', 'username': '', 'password': '',
             'custom_url': '', 'enabled': False}.items()}
        self.address, self.status_text, self.notice_text = Value('—'), Value(self.t('offline')), Value('')
        self.selected = Value('webui')
        self.events = queue.Queue()
        self.busy, self.closed, self.polling = False, False, False
        self.report, self.report_text = None, None
        self.setWindowTitle(self.t('title'))
        self.resize(590, 700)
        self.setMinimumSize(570, 680)
        base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
        self.setWindowIcon(QIcon(str(base / 'animelab/static/img/icon-192.png')))
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(0)
        self.rebuild()
        self.shortcut = QShortcut(QKeySequence('Ctrl+Tab'), self)
        self.shortcut.activated.connect(self.next_tab)
        self.dispatch_timer = QTimer(self)
        self.dispatch_timer.timeout.connect(self.dispatch)
        self.dispatch_timer.start(100)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(1000)
        QTimer.singleShot(0, self.poll)

    @property
    def catalog(self):
        return TEXT[self.lang]

    def t(self, key):
        return self.catalog.get(key, TEXT['en'].get(key, key))

    def rebuild(self):
        app = QApplication.instance()
        app.removeTranslator(self.qt_translator)
        if self.lang == 'fr' and self.qt_translator.load('qtbase_fr',
                QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(self.qt_translator)
        # Disconnect old field bindings before deleting their widgets.
        for value in [*self.variables.values(), *self.proxy_variables.values(), self.speed,
                      self.address, self.status_text, self.notice_text, self.selected]:
            if value.receivers('2changed(PyObject)'):
                value.changed.disconnect()
        self.variables['language'].changed.connect(self.language_changed)
        while self.outer.count():
            widget = self.outer.takeAt(0).widget()
            if widget: widget.hide(); widget.deleteLater()
        self.action_buttons, self.fields, self.pages, self.tabs = [], {}, {}, []
        self.report_text = None
        tabbar = QWidget(self)
        tabbar.setAccessibleName(self.t('title'))
        grid = QGridLayout(tabbar)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self.tab_group = QButtonGroup(tabbar)
        self.tab_group.setExclusive(True)
        for index, name in enumerate(TABS):
            tab = QToolButton(tabbar)
            tab.setText(self.t(name))
            tab.setFont(self.font())
            tab.setAccessibleName(self.t(name))
            tab.setToolTip(self.t(name))
            tab.setCheckable(True)
            tab.setMinimumSize(0, 29)
            from PySide6.QtWidgets import QSizePolicy
            tab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tab.setStyleSheet('QToolButton { border: none; border-bottom: 1px solid #d6d8db; padding: 5px 2px; }'
                'QToolButton:checked { background: white; color: #2465a3; border-bottom: 2px solid #6299cc; }'
                'QToolButton:hover { background: #e8edf2; } QToolButton:focus { border: 1px solid #4389ce; }')
            tab.clicked.connect(lambda checked=False, name=name: self.select_tab(name))
            self.tab_group.addButton(tab, index)
            self.tabs.append(tab)
            grid.addWidget(tab, index // 5, index % 5)
        for column in range(5):
            grid.setColumnStretch(column, 1)
            grid.setColumnMinimumWidth(column, max(self.tabs[index].fontMetrics().horizontalAdvance(
                self.tabs[index].text()) + 16 for index in (column, column + 5)))
        self.outer.addWidget(tabbar)
        self.stack = QStackedWidget(self)
        for name in TABS:
            self.building_page = name
            self.pages[name] = build_page(self, self.stack, name)
            self.stack.addWidget(self.pages[name])
        self.outer.addWidget(self.stack, 1)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        self.outer.addWidget(line)
        footer = QWidget(self)
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(5)
        for variable in (self.status_text, self.notice_text):
            label = QLabel(str(variable.get()))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            variable.changed.connect(label.setText)
            layout.addWidget(label)
        for actions in ((('save', self.save), ('launch', self.launch), ('native', lambda: self.launch(True))),
                        (('restart', self.restart), ('stop', self.stop), ('close', self.close))):
            row = QHBoxLayout()
            row.addStretch()
            for key, callback in actions:
                item = QPushButton(self.t(key))
                item.clicked.connect(lambda checked=False, callback=callback: callback())
                item.setMinimumWidth(94)
                row.addWidget(item)
                if key != 'close': self.action_buttons.append(item)
            row.addStretch()
            layout.addLayout(row)
        hint = QLabel(self.t('close_hint'))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.outer.addWidget(footer)
        # GTK registers per-widget font defaults (e.g. 11pt for QToolButton).
        # Explicit fonts prevent them overriding the compact inherited form font.
        for item in self.findChildren(QWidget):
            if not item.property('launcherHeading'): item.setFont(self.font())
        self.show_page()
        self.outer.activate()
        grid.activate()
        if self.busy:
            for item in self.action_buttons: item.setEnabled(False)

    def select_tab(self, name):
        self.selected.set(name)
        self.show_page()

    def show_page(self):
        index = TABS.index(self.selected.get())
        self.stack.setCurrentIndex(index)
        self.tabs[index].setChecked(True)

    def next_tab(self):
        self.select_tab(TABS[(TABS.index(self.selected.get()) + 1) % len(TABS)])

    def language_changed(self, *_):
        self.lang = language(self.variables['language'].get())
        QTimer.singleShot(0, self.rebuild)

    def collect_config(self):
        data = {'port': int(self.variables['port'].get()), 'browser': self.variables['browser'].get(), 'launcher': {}}
        for key, variable in self.variables.items():
            if key in ('port', 'browser'): continue
            value = variable.get()
            if key in ('maxConcurrentDownloads', 'mediaWorkers'): value = int(value)
            elif key in ('connectTimeout', 'readTimeout'): value = float(value)
            data['launcher'][key] = value
        data['launcher']['globalSpeedLimit'] = int(float(self.speed.get()) * 1024)
        return normalize_config(data)

    def note(self, key):
        self.notice_text.set(self.t(key))

    def task(self, operation, success=None):
        if self.busy or self.closed: return
        self.busy = True
        self.note('busy')
        for item in self.action_buttons: item.setEnabled(False)
        def run():
            try: self.events.put(('result', operation(), success))
            except Exception as error: self.events.put(('error', redact_text(error), None))
        threading.Thread(target=run, daemon=True, name='AnimeLabLauncherAction').start()

    def dispatch(self):
        if self.closed: return
        try:
            while True:
                kind, value, callback = self.events.get_nowait()
                if kind == 'status':
                    self.polling = False
                    self.address.set(value.get('url') or '—')
                    self.status_text.set(self.t('ready' if value.get('ready') else 'starting' if value.get('running') else 'offline'))
                    if value.get('portFallback'): self.status_text.set(self.status_text.get() + ' · ' + self.t('port_fallback'))
                    if value.get('pendingRestart'): self.status_text.set(self.status_text.get() + ' · ' + self.t('pending'))
                    continue
                self.busy = False
                for item in self.action_buttons: item.setEnabled(True)
                if kind == 'error':
                    self.notice_text.set(self.t('failed') + ': ' + value)
                    QMessageBox.critical(self, self.t('failed'), value)
                elif callback:
                    callback(value)
                else:
                    self.notice_text.set('')
        except queue.Empty:
            pass

    def poll(self):
        if self.closed: return
        if not self.polling:
            self.polling = True
            threading.Thread(target=lambda: self.events.put(('status', self.model.status(), None)), daemon=True).start()

    def save(self):
        try: values = self.collect_config()
        except ValueError as error:
            QMessageBox.critical(self, self.t('failed'), str(error))
            return
        self.task(lambda: self.model.save(values), lambda result: self.saved(result))

    def saved(self, result):
        self.config = result
        self.note('saved')

    def launch(self, native=False):
        try: values = self.collect_config()
        except ValueError as error:
            QMessageBox.critical(self, self.t('failed'), str(error))
            return
        if self.address.get() != '—' and not self.confirm('restart', 'restart_confirm'):
            return
        def success(_):
            self.config = self.model.config()
            self.variables['browser'].set(self.config['browser'])
            self.variables['openUi'].set(self.config['launcher']['openUi'])
            self.rebuild()
            self.note('started')
        self.task(lambda: self.model.launch(values, native=native), success)

    def restart(self):
        if not self.confirm('restart', 'restart_confirm'): return
        try: values = self.collect_config()
        except ValueError as error:
            QMessageBox.critical(self, self.t('failed'), str(error))
            return
        self.task(lambda: self.model.restart(values), lambda _: self.note('started'))

    def stop(self):
        if self.confirm('stop', 'stop_confirm'):
            self.task(self.model.stop, lambda _: self.note('stopped'))

    def choose_download_directory(self):
        initial = self.variables['downloadDir'].get() or self.model.paths()['downloads']
        selected = choose_directory(self, self.t('download_dir'), initial)
        if selected: self.variables['downloadDir'].set(selected)

    def copy_address(self):
        if self.address.get() != '—':
            QApplication.clipboard().setText(self.address.get())

    def load_proxy(self):
        def loaded(values):
            for key, variable in self.proxy_variables.items(): variable.set(values.get(key, '' if key != 'enabled' else False))
            self.rebuild()
            self.notice_text.set('')
        self.task(lambda: self.model.engine_api('/api/proxy/settings'), loaded)

    def save_proxy(self):
        values = {key: variable.get() for key, variable in self.proxy_variables.items()}
        self.task(lambda: self.model.engine_api('/api/proxy/settings', values), lambda _: self.note('saved'))

    def run_checks(self):
        def checked(report):
            self.report = report
            self.render_report()
            self.notice_text.set('')
        self.task(self.model.diagnose, checked)

    def render_report(self):
        if self.report is None or self.report_text is None: return
        self.report_text.setPlainText(''.join(
            f"{self.t('pass' if row['ok'] else 'fail')} · {row['name']}\n{row['detail']}\n\n"
            for row in self.report['checks']))

    def export_report(self):
        if self.report is None:
            self.run_checks()
            return
        target = save_file(self, self.t('export_report'), 'animelab-diagnostics.json', 'JSON (*.json)')
        if target: self.task(lambda: write_json(Path(target), self.report), lambda _: self.note('saved'))

    def confirm(self, title, question):
        return QMessageBox.question(self, self.t(title), self.t(question),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, self.t('title'), self.t('busy'))
            event.ignore()
            return
        try:
            dirty = self.collect_config() != self.config
        except ValueError:
            dirty = True
        if dirty and not self.confirm('close', 'discard'):
            event.ignore()
            return
        self.closed = True
        self.dispatch_timer.stop()
        self.poll_timer.stop()
        event.accept()


def open_launcher(directory, probe=False):
    app = application()
    ui = NativeLauncher(directory)
    ui.show()
    if probe:
        def verify():
            try:
                from PySide6.QtGui import QRawFont
                from PySide6.QtTest import QTest
                font = QRawFont.fromFont(ui.font())
                if not font.isValid() or not all(font.supportsCharacter(ord(c)) for c in 'éÀœ’…'):
                    raise RuntimeError('Launcher outline font lacks required Unicode glyphs')
                for lang in ('fr', 'en'):
                    ui.variables['language'].set(lang)
                    QTest.qWait(50)
                    for page in TABS:
                        ui.select_tab(page)
                        app.processEvents()
                        if not ui.pages[page].isVisible():
                            raise RuntimeError('Launcher tab did not render: ' + page)
                    for tab in ui.tabs:
                        if tab.fontMetrics().horizontalAdvance(tab.text()) > tab.width() - 4:
                            raise RuntimeError('Launcher tab title was clipped: ' + tab.text())
                normalize_config(ui.collect_config())
                ui.probe_passed = True
            except Exception as error:
                ui.probe_error = error
            finally:
                ui.closed = True
                ui.hide()
                app.quit()
        QTimer.singleShot(350, verify)
    app.exec()
    if probe and not getattr(ui, 'probe_passed', False):
        raise RuntimeError('Native launcher probe failed') from getattr(ui, 'probe_error', None)
