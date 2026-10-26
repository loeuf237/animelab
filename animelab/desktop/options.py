"""Validated native-launcher preferences and their engine startup mapping."""
import math
import os
from pathlib import Path

from .state import valid_port

DEFAULTS = {
    'openUi': True, 'startPage': 'home', 'language': 'auto', 'downloadDir': '',
    'maxConcurrentDownloads': 3, 'globalSpeedLimit': 0, 'plexOrganization': False,
    'mediaWorkers': 1, 'connectTimeout': 15.0, 'readTimeout': 30.0,
    'authMode': 'none', 'authSessionHours': 12, 'authIdleMinutes': 30,
    'authMaxEngines': 4,
}
PAGES = {'home': '', 'downloads': 'downloads', 'library': 'library', 'sources': 'sources',
         'extensions': 'extensions', 'settings': 'settings'}


def normalize_config(data):
    if not isinstance(data, dict) or set(data) - {'port', 'browser', 'launcher'}:
        raise ValueError('Invalid launcher settings')
    if type(data.get('browser')) is not bool:
        raise ValueError('Invalid browser preference')
    values = data.get('launcher', {})
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise ValueError('Invalid launcher preferences')
    options = {**DEFAULTS, **values}
    for name in ('openUi', 'plexOrganization'):
        if type(options[name]) is not bool: raise ValueError('Invalid boolean preference: ' + name)
    for name, maximum in [('maxConcurrentDownloads', 32), ('mediaWorkers', 8), ('globalSpeedLimit', 1_000_000_000)]:
        value = options[name]
        minimum = 0 if name == 'globalSpeedLimit' else 1
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('Invalid numeric preference: ' + name)
    for name in ('connectTimeout', 'readTimeout'):
        value = options[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 600:
            raise ValueError('Timeouts must be between 1 and 600 seconds')
    if options['authMode'] not in ('none', 'accounts'):
        raise ValueError('Unsupported authentication mode')
    for name, maximum in [('authSessionHours', 168), ('authIdleMinutes', 1440), ('authMaxEngines', 32)]:
        if type(options[name]) is not int or not 1 <= options[name] <= maximum:
            raise ValueError('Invalid authentication preference: ' + name)
    if options['authIdleMinutes'] > options['authSessionHours'] * 60:
        raise ValueError('Idle timeout cannot exceed the session lifetime')
    if (not isinstance(options['startPage'], str) or options['startPage'] not in PAGES
            or options['language'] not in ('auto', 'fr', 'en')):
        raise ValueError('Invalid language or initial page')
    path = options['downloadDir']
    if not isinstance(path, str) or '\x00' in path or '\n' in path or len(path) > 4096:
        raise ValueError('Invalid download directory')
    if path and not Path(path).expanduser().is_absolute():
        raise ValueError('The download directory must be an absolute path')
    return {'port': valid_port(data.get('port')), 'browser': data['browser'], 'launcher': options}


def preferences(config):
    return {**DEFAULTS, **config.get('launcher', {})}


def ui_path(config):
    return '/spa/' + PAGES[preferences(config)['startPage']]


def shared_directory(directory):
    return Path(os.getenv('ANIMELAB_SHARED_DIR', str(Path(directory).parent / 'shared'))).expanduser().resolve()


def engine_environment(config, directory=None):
    """Only supported settings become environment variables; no arbitrary env import."""
    if 'launcher' not in config:
        return {}
    import json
    values = normalize_config(config)['launcher']
    env = {'ANIMAN_CONNECT_TIMEOUT': str(values['connectTimeout']),
           'ANIMAN_READ_TIMEOUT': str(values['readTimeout']),
           'ANIMAN_MEDIA_WORKERS': str(values['mediaWorkers']),
           'ANIMAN_DESKTOP_PREFERENCES': json.dumps({key: values[key] for key in
               ('maxConcurrentDownloads', 'globalSpeedLimit', 'plexOrganization')})}
    env['ANIMELAB_DESKTOP_AUTH'] = ''
    if values['authMode'] == 'accounts':
        if directory is None:
            from .state import state_directory
            directory = state_directory()
        env['ANIMELAB_DESKTOP_AUTH'] = json.dumps({
            'root': str(shared_directory(directory)), 'sessionHours': values['authSessionHours'],
            'idleMinutes': values['authIdleMinutes'], 'maxEngines': values['authMaxEngines']})
    if values['downloadDir']:
        env['ANIMAN_DOWNLOAD_DIR'] = str(Path(values['downloadDir']).expanduser())
    if values['language'] != 'auto':
        env['ANIMAN_LANGUAGE'] = values['language']
    return env


def apply_download_preferences():
    import json
    data = os.environ.get('ANIMAN_DESKTOP_PREFERENCES')
    if data:
        values = json.loads(data)
        from animelab.services.download_manager import download_manager
        download_manager.update_settings(values['maxConcurrentDownloads'], values['globalSpeedLimit'],
                                         values['plexOrganization'])
