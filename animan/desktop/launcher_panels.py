"""Native Qt settings pages. Every control persists or invokes an engine operation."""
from datetime import datetime
from pathlib import Path
import webbrowser
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit, QSpinBox,
    QDoubleSpinBox, QCheckBox, QComboBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QScrollArea, QPlainTextEdit, QFrame, QMessageBox)

from animan import __version__
from .launcher_dialogs import choose_directory, save_file
from .launcher_widgets import Value
from .state import write_json

TABS = ('webui', 'server', 'downloads', 'folders', 'requests', 'proxy',
        'extensions', 'diagnostics', 'backups', 'about')


def label(ui, parent, key):
    item = QLabel(ui.t(key))
    item.setWordWrap(True)
    parent.addWidget(item)
    return item


def button(ui, parent, key, command):
    item = QPushButton(ui.t(key))
    item.clicked.connect(lambda checked=False: command())
    parent.addWidget(item, 0, Qt.AlignmentFlag.AlignHCenter)
    ui.action_buttons.append(item)
    return item


def form(ui, parent, key, control):
    layout = QFormLayout()
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    caption = QLabel(ui.t(key))
    caption.setMinimumWidth(185)
    caption.setBuddy(control)
    layout.addRow(caption, control)
    parent.addLayout(layout)
    ui.fields[(ui.building_page, key)] = control


def field(ui, parent, key, variable, *, readonly=False, spin=None, secret=False):
    if spin:
        entry = QDoubleSpinBox() if len(spin) > 2 else QSpinBox()
        entry.setRange(spin[0], spin[1])
        if len(spin) > 2:
            entry.setSingleStep(spin[2])
            entry.setDecimals(1)
        entry.setValue(float(variable.get()) if len(spin) > 2 else int(variable.get()))
        entry.valueChanged.connect(variable.set)
        variable.changed.connect(entry.setValue)
    else:
        entry = QLineEdit(str(variable.get()))
        entry.setReadOnly(readonly)
        if secret: entry.setEchoMode(QLineEdit.EchoMode.Password)
        entry.textChanged.connect(variable.set)
        variable.changed.connect(entry.setText)
    form(ui, parent, key, entry)
    return entry


def choice(ui, parent, key, variable, values):
    combo = QComboBox()
    for value, name in values.items(): combo.addItem(ui.t(name) if name in ui.catalog else name, value)
    combo.setCurrentIndex(list(values).index(variable.get()))
    combo.currentIndexChanged.connect(lambda index: variable.set(combo.itemData(index)))
    variable.changed.connect(lambda value: combo.setCurrentIndex(list(values).index(value)))
    form(ui, parent, key, combo)


def checkbox(ui, parent, key, variable):
    item = QCheckBox(ui.t(key))
    item.setChecked(variable.get())
    item.toggled.connect(variable.set)
    variable.changed.connect(item.setChecked)
    parent.addWidget(item)
    ui.fields[(ui.building_page, key)] = item


def build_page(ui, parent, name):
    # Scroll only when the user scales text or shrinks the window; forms stay centred.
    scroll = QScrollArea(parent)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(30, 20, 30, 20)
    content = QVBoxLayout()
    content.setSpacing(12)
    if name != 'diagnostics': outer.addStretch()
    outer.addLayout(content, 1 if name == 'diagnostics' else 0)
    if name != 'diagnostics': outer.addStretch()
    getattr(Pages, name)(ui, content)
    scroll.setWidget(page)
    return scroll


class Pages:
    @staticmethod
    def webui(ui, frame):
        checkbox(ui, frame, 'open_ui', ui.variables['openUi'])
        choice(ui, frame, 'interface', ui.variables['browser'], {True: 'browser', False: 'native'})
        choice(ui, frame, 'page', ui.variables['startPage'],
               {key: key for key in ('home', 'downloads', 'library', 'sources', 'extensions', 'settings')})
        choice(ui, frame, 'language', ui.variables['language'], {'auto': 'auto', 'fr': 'Français', 'en': 'English'})

    @staticmethod
    def server(ui, frame):
        field(ui, frame, 'host', Value('127.0.0.1'), readonly=True)
        field(ui, frame, 'port', ui.variables['port'], spin=(1, 65535))
        field(ui, frame, 'address', ui.address, readonly=True)
        button(ui, frame, 'test_port', lambda: ui.task(
            lambda: ui.model.test_port(int(ui.variables['port'].get())),
            lambda result: ui.note('port_active' if result == 'active' else 'port_free')))
        button(ui, frame, 'copy_address', ui.copy_address)
        label(ui, frame, 'local_only')

    @staticmethod
    def downloads(ui, frame):
        field(ui, frame, 'concurrent', ui.variables['maxConcurrentDownloads'], spin=(1, 32))
        field(ui, frame, 'media', ui.variables['mediaWorkers'], spin=(1, 8))
        field(ui, frame, 'speed', ui.speed, spin=(0, 976562, 1))
        checkbox(ui, frame, 'plex', ui.variables['plexOrganization'])

    @staticmethod
    def folders(ui, frame):
        paths = ui.model.paths()
        field(ui, frame, 'download_dir', ui.variables['downloadDir'])
        button(ui, frame, 'browse', ui.choose_download_directory)
        field(ui, frame, 'data_dir', Value(str(paths['data'])), readonly=True)
        field(ui, frame, 'cache_dir', Value(str(paths['cache'])), readonly=True)
        button(ui, frame, 'open', lambda: ui.task(lambda: ui.model.open_folder('data')))
        label(ui, frame, 'folder_hint')

    @staticmethod
    def requests(ui, frame):
        field(ui, frame, 'connect', ui.variables['connectTimeout'], spin=(1, 600, .5))
        field(ui, frame, 'read', ui.variables['readTimeout'], spin=(1, 600, .5))
        label(ui, frame, 'request_hint')

    @staticmethod
    def proxy(ui, frame):
        label(ui, frame, 'proxy_hint')
        checkbox(ui, frame, 'proxy_enabled', ui.proxy_variables['enabled'])
        choice(ui, frame, 'type', ui.proxy_variables['proxy_type'],
               {'http': 'HTTP', 'https': 'HTTPS', 'socks5': 'SOCKS5', 'socks5h': 'SOCKS5H',
                'socks4': 'SOCKS4', 'socks4a': 'SOCKS4A'})
        for key, word in [('host', 'proxy_host'), ('port', 'proxy_port'), ('username', 'username'),
                          ('password', 'password'), ('custom_url', 'custom_url')]:
            field(ui, frame, word, ui.proxy_variables[key], secret=key in ('password', 'custom_url'))
        button(ui, frame, 'load_proxy', ui.load_proxy)
        button(ui, frame, 'save_proxy', ui.save_proxy)

    @staticmethod
    def extensions(ui, frame):
        label(ui, frame, 'extensions_hint')
        button(ui, frame, 'manage_extensions', lambda: ui.task(lambda: ui.model.open_page('extensions')))
        button(ui, frame, 'browse_sources', lambda: ui.task(lambda: ui.model.open_page('sources')))
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        frame.addWidget(line)
        label(ui, frame, 'verification_hint')
        button(ui, frame, 'verification', lambda: ui.task(lambda: ui.model.open_page('sources')))

    @staticmethod
    def diagnostics(ui, frame):
        label(ui, frame, 'diagnostic_hint')
        button(ui, frame, 'run_checks', ui.run_checks)
        ui.report_text = QPlainTextEdit()
        ui.report_text.setReadOnly(True)
        frame.addWidget(ui.report_text, 1)
        bottom = QHBoxLayout()
        button(ui, bottom, 'export_report', ui.export_report)
        button(ui, bottom, 'logs', lambda: ui.task(lambda: ui.model.open_folder('logs')))
        frame.addLayout(bottom)
        ui.render_report()

    @staticmethod
    def backups(ui, frame):
        field(ui, frame, 'db_path', Value(str(ui.model.paths()['database'])), readonly=True)
        label(ui, frame, 'backup_hint')
        def backup():
            selected = save_file(ui, ui.t('backup_db'),
                'animelab-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3', 'SQLite (*.sqlite3)')
            if selected: ui.task(lambda: ui.model.backup(selected), lambda _: ui.note('backup_ok'))
        button(ui, frame, 'backup_db', backup)
        def export():
            try: values = ui.collect_config()
            except ValueError as error:
                QMessageBox.critical(ui, ui.t('failed'), str(error))
                return
            target = save_file(ui, ui.t('export_settings'), 'animelab-launcher.json', 'JSON (*.json)')
            if target: ui.task(lambda: write_json(Path(target), values), lambda _: ui.note('saved'))
        button(ui, frame, 'export_settings', export)
        label(ui, frame, 'private_settings')

    @staticmethod
    def about(ui, frame):
        title = QLabel('AnimeLab Desktop')
        title.setProperty('launcherHeading', True)
        font = title.font()
        font.setPointSize(15)
        font.setBold(True)
        title.setFont(font)
        frame.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        for text in (ui.t('version') + ' ' + __version__, 'Python · FastAPI · Vue · Qt Widgets', 'GPL-3.0-only'):
            frame.addWidget(QLabel(text), 0, Qt.AlignmentFlag.AlignHCenter)
        label(ui, frame, 'inspiration')
        button(ui, frame, 'website', lambda: webbrowser.open('https://github.com/loeuf237/animelab'))
