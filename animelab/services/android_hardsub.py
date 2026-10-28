"""Absolute subtitle paths for JNI: never change the process working directory."""
from pathlib import Path


def filter_path(path):
    value = str(Path(path).resolve())
    # Two FFmpeg grammars: option values, then the containing filter graph.
    value = ''.join('\\' + c if c in "\\': \t\n" else c for c in value)
    return ''.join('\\' + c if c in "\\'[],; \t\n" else c for c in value)


def subtitle_filter(subtitle, fonts):
    return f'subtitles=filename={filter_path(subtitle)}:fontsdir={filter_path(fonts)}'
