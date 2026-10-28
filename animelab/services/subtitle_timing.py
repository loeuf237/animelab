"""Shift textual subtitle cues without throwing away ASS styles or VTT headers."""
import re


def seconds(value: str) -> float:
    result = 0.0
    for part in value.replace(',', '.').split(':'):
        result = result * 60 + float(part)
    return result


def stamp(value: float, *, ass=False, comma=False) -> str:
    precision = 100 if ass else 1000
    ticks = max(0, round(value * precision))
    whole, fraction = divmod(ticks, precision)
    hours, remainder = divmod(whole, 3600)
    minutes, second = divmod(remainder, 60)
    if ass:
        return f'{hours}:{minutes:02}:{second:02}.{fraction:02}'
    return f'{hours:02}:{minutes:02}:{second:02}{"," if comma else "."}{fraction:03}'


def shift(content: bytes, offset: float, extension: str, *, factor: float = 1) -> bytes:
    if not offset and factor == 1:
        return content
    text = content.decode('utf-8-sig')
    lines = text.splitlines(keepends=True)
    if extension.lower() in ('.ass', '.ssa'):
        fields = []
        events = False
        output = []
        for line in lines:
            if line.lstrip().startswith('['):
                events = line.strip().lower() == '[events]'
            if events and line.lower().startswith('format:'):
                fields = [item.strip().lower() for item in line.partition(':')[2].split(',')]
            if events and line.lower().startswith('dialogue:'):
                if 'start' not in fields or 'end' not in fields:
                    raise ValueError('Format ASS incomplet')
                values = line.partition(':')[2].lstrip().split(',', len(fields) - 1)
                start, end = fields.index('start'), fields.index('end')
                finish = seconds(values[end]) * factor + offset
                if finish <= 0:
                    continue
                values[start] = stamp(seconds(values[start]) * factor + offset, ass=True)
                values[end] = stamp(finish, ass=True)
                line = 'Dialogue: ' + ','.join(values)
            output.append(line)
        return ''.join(output).encode('utf-8')
    pattern = re.compile(r'(?m)^(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})(\s+-->\s+)(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})([^\r\n]*)\r?$')
    # Work on cue blocks so removing an entirely negative cue also removes text.
    output = []
    for block in re.split(r'\r?\n\r?\n', text):
        match = pattern.search(block)
        if not match:
            output.append(block)
            continue
        end = seconds(match[3]) * factor + offset
        if end <= 0:
            continue
        def replace(found):
            return (stamp(seconds(found[1]) * factor + offset, comma=extension == '.srt') + found[2]
                    + stamp(end, comma=extension == '.srt') + found[4])
        output.append(pattern.sub(replace, block, count=1))
    return '\n\n'.join(output).encode('utf-8')


def intervals(content: bytes, extension: str) -> list[tuple[float, float]]:
    text = content.decode('utf-8-sig')
    result = []
    if extension in ('.ass', '.ssa'):
        fields = []
        for line in text.splitlines():
            if line.lower().startswith('format:'):
                fields = [value.strip().lower() for value in line.partition(':')[2].split(',')]
            elif line.lower().startswith('dialogue:') and 'start' in fields and 'end' in fields:
                values = line.partition(':')[2].split(',', len(fields) - 1)
                result.append((seconds(values[fields.index('start')]), seconds(values[fields.index('end')])))
    else:
        for match in re.finditer(r'(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})', text):
            result.append((seconds(match[1]), seconds(match[2])))
    return [(start, end) for start, end in result if end > start]
