"""Offline synthetic proof of MP4 burn-in and MKV selectable subtitle tracks.
Run with Python; requires local FFmpeg/libass/libx264 and ffprobe.
Does not run N_m3u8DL-RE or change the application.
"""
from pathlib import Path
import subprocess,json
import tempfile
temporary = tempfile.TemporaryDirectory(prefix='animelab-subtitle-proof-')
root = Path(temporary.name)
def run(args):
    return subprocess.run(args,cwd=root,capture_output=True,text=True,check=True,timeout=45)
(root/'fr.srt').write_text('1\n00:00:00,000 --> 00:00:01,700\nBonjour AnimeLab\n\n',encoding='utf8')
(root/'en.srt').write_text('1\n00:00:00,000 --> 00:00:01,700\nHello AnimeLab\n\n',encoding='utf8')
run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=320x180:r=10','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-f','lavfi','-i','sine=frequency=880:sample_rate=48000','-t','2','-map','0:v:0','-map','1:a:0','-map','2:a:0','-metadata:s:a:0','language=jpn','-metadata:s:a:1','language=eng','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','source.mp4'])
hard=['ffmpeg','-v','error','-y','-i','source.mp4','-map','0:v:0','-map','0:a:0?','-vf','subtitles=fr.srt','-c:v','libx264','-crf','20','-preset','veryfast','-c:a','aac','-sn','-movflags','+faststart','hardsub.mp4']
soft=['ffmpeg','-v','error','-y','-i','source.mp4','-i','fr.srt','-i','en.srt','-map','0:v:0','-map','0:a?','-map','1:s:0','-map','2:s:0','-c:v','copy','-c:a','copy','-c:s','srt','-metadata:s:s:0','language=fra','-metadata:s:s:1','language=eng','-disposition:s:0','default','-disposition:s:1','0','multipiste.mkv']
run(hard); run(soft)
def probe(name):
    return json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',name]).stdout)
h,s=probe('hardsub.mp4'),probe('multipiste.mkv')
assert [x['codec_type'] for x in h['streams']]==['video','audio']
assert [x['codec_type'] for x in s['streams']].count('subtitle')==2
assert [x['codec_type'] for x in s['streams']].count('audio')==2
assert [x['tags'].get('language') for x in s['streams'] if x['codec_type']=='subtitle']==['fra','eng']
# Decode a frame at the same time to prove visible pixels changed, not merely container metadata.
frames=[]
for name in ['source.mp4','hardsub.mp4']:
    data=subprocess.run(['ffmpeg','-v','error','-ss','1','-i',str(root/name),'-frames:v','1','-f','rawvideo','-pix_fmt','gray','-'],capture_output=True,check=True,timeout=30).stdout
    frames.append(data)
assert frames[0]!=frames[1]
assert sum(x>100 for x in frames[1])>sum(x>100 for x in frames[0])+100
result={'scope':'offline synthetic FFmpeg proof; not N_m3u8DL-RE or Android runtime validation','source_seconds':2,'ffmpeg_version':run(['ffmpeg','-version']).stdout.splitlines()[0],'commands':{'hardsub':hard,'multipiste':soft},'outputs':{n:{'bytes':(root/n).stat().st_size,'streams':[{'type':x['codec_type'],'codec':x['codec_name'],'language':x.get('tags',{}).get('language'),'default':x.get('disposition',{}).get('default')} for x in p['streams']]} for n,p in [('hardsub.mp4',h),('multipiste.mkv',s)]},'burned_pixels_confirmed':True}
Path(__file__).with_name('local-proof.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))

temporary.cleanup()
