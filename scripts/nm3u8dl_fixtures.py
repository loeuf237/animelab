"""Synthetic clear VOD for N_m3u8DL-RE evaluation, no network/media library."""
from pathlib import Path
import subprocess


def generate(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    def ff(args):
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y',*map(str,args)],check=True,capture_output=True,timeout=30)
    video=root/'reference.mp4'
    if video.exists():raise FileExistsError('Choose a new fixture directory')
    ff(['-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
        '-t','4','-c:v','libx264','-preset','ultrafast','-g','25','-keyint_min','25','-sc_threshold','0','-c:a','aac',video])
    for name in ('simple','aes','fmp4','dash','subtitle'):(root/name).mkdir(exist_ok=True)
    ff(['-i',video,'-c','copy','-f','hls','-hls_time','1','-hls_list_size','0',root/'simple/index.m3u8'])
    key=root/'aes/key.bin';key.write_bytes(bytes(range(16)))
    info=root/'key-info.txt';info.write_text('key.bin\n'+str(key.resolve())+'\n00000000000000000000000000000001\n')
    ff(['-i',video,'-c','copy','-f','hls','-hls_time','1','-hls_list_size','0','-hls_key_info_file',info,root/'aes/index.m3u8']);info.unlink()
    ff(['-i',video,'-c','copy','-f','hls','-hls_time','1','-hls_list_size','0','-hls_segment_type','fmp4','-hls_flags','single_file','-hls_segment_filename',root/'fmp4/media.mp4',root/'fmp4/index.m3u8'])
    ff(['-i',video,'-c','copy','-map','0:v','-map','0:a','-f','dash','-seg_duration','1','-use_timeline','1','-use_template','1',root/'dash/index.mpd'])
    sub=root/'subtitle'
    (sub/'index.m3u8').write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="French",LANGUAGE="fr",AUTOSELECT=YES,URI="subs.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=250000,SUBTITLES="subs"\n../simple/index.m3u8\n')
    (sub/'subs.m3u8').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:2,\na.vtt\n#EXTINF:2,\nb.vtt\n#EXT-X-ENDLIST\n')
    for name,first,line in [('a',.2,'Bonjour'),('b',2.2,'Au revoir')]:
        (sub/(name+'.vtt')).write_text(f'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:126000\n\n00:00:0{first:.3f} --> 00:00:0{first+.6:.3f}\n{line}\n')
    dis=root/'discontinuity';dis.mkdir(exist_ok=True)
    (dis/'index.m3u8').write_text((sub/'index.m3u8').read_text().replace('../simple/index.m3u8','video.m3u8'))
    (dis/'video.m3u8').write_text((root/'simple/index.m3u8').read_text().replace('index','../simple/index').replace('#EXTINF:1.000000,\n../simple/index2.ts','#EXT-X-DISCONTINUITY\n#EXTINF:1.000000,\n../simple/index2.ts'))
    (dis/'subs.m3u8').write_text((sub/'subs.m3u8').read_text().replace('#EXTINF:2,\nb.vtt','#EXT-X-DISCONTINUITY\n#EXTINF:2,\nb.vtt'))
    (dis/'a.vtt').write_bytes((sub/'a.vtt').read_bytes())
    (dis/'b.vtt').write_text('WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:306000\n\n00:00:00.200 --> 00:00:00.800\nAu revoir\n')
    return {name:root/name/('index.mpd' if name=='dash' else 'index.m3u8') for name in ('simple','aes','fmp4','dash','subtitle','discontinuity')}


if __name__=='__main__':
    import sys
    print(generate(Path(sys.argv[1])))
