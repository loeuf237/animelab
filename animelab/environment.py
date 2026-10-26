"""Read new environment names first without breaking established integrations.

Explicit child-process overrides set both aliases, so inherited operator values
cannot override a worker's private database or a launcher's selected port.
"""
import os


def names(name):
    if name.startswith('ANIMAN_'):
        return 'ANIMELAB_' + name[len('ANIMAN_'):], name
    if name.startswith('ANIMELAB_'):
        return name, 'ANIMAN_' + name[len('ANIMELAB_'):]
    return name, name


def getenv(name, default=None, *, environ=None):
    values = os.environ if environ is None else environ
    current, legacy = names(name)
    return values.get(current, values.get(legacy, default))


def with_aliases(values):
    result = dict(values)
    for name in values:
        current, legacy = names(name)
        value = values.get(current, values.get(legacy))
        result[current] = result[legacy] = value
    return result


def update_environment(values=None, **kwargs):
    os.environ.update(with_aliases({**(values or {}), **kwargs}))
