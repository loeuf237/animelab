"""Generate tiny reference media offline, outside the user's media library."""
import argparse
from pathlib import Path
import subprocess


def generate(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parents[1] / 'tests/fixtures/media_pipeline'
    video = directory / 'reference.mp4'
    multi = directory / 'reference.mkv'
    if video.exists() or multi.exists():
        raise FileExistsError('Reference media already exist; choose a new directory')
    def ffmpeg(args):
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', *map(str, args)],
                       capture_output=True, check=True, timeout=30)
    ffmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=10', '-f', 'lavfi', '-i',
            'sine=frequency=440', '-t', '2', '-c:v', 'mpeg4', '-g', '10', '-c:a', 'aac', video])
    ffmpeg(['-i', video, '-f', 'lavfi', '-i', 'sine=frequency=660', '-i', fixtures / 'styled.ass',
            '-t', '2', '-map', '0:v', '-map', '0:a', '-map', '1:a', '-map', '2:s',
            '-c:v', 'copy', '-c:a', 'aac', '-c:s', 'ass', '-metadata:s:a:0', 'language=jpn',
            '-metadata:s:a:1', 'language=eng', '-metadata:s:s:0', 'language=fra', multi])
    return dict(mp4=video, mkv=multi)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='New/empty output directory; existing files are never overwritten')
    print({key: str(path) for key, path in generate(parser.parse_args().directory).items()})
