"""P10-P12 evaluation adapter. Never selected by the production planner.

The pinned downloader's resume must be evaluated independently of our verified
resource cache. An explicit unsafe_cache_probe exists only in the offline study
runner to reproduce corruption, never in the production download API.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from animelab.services.download_resume import write_metadata
from animelab.services.media_contracts import BackendCapabilities, MediaEvent, TransferResult, UnsupportedMedia
from animelab.services.media_execution import run_process
from animelab.services.experimental.manifest_relay import ManifestRelay

ROOT=Path(__file__).resolve().parents[3]
LOCK=json.loads(Path(__file__).with_name('nm3u8dl-lock.json').read_text())


def pinned_tool(path):
    path=Path(path).resolve()
    if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):
        raise UnsupportedMedia('Bac à sable évalué uniquement sur Linux x64')
    if not path.is_file() or not os.access(path,os.X_OK) or hashlib.sha256(path.read_bytes()).hexdigest()!=LOCK['linuxX64BinarySha256']:
        raise UnsupportedMedia('Le binaire ne correspond pas à la version Linux x64 épinglée')
    result=run_process([path,'--version'],timeout=5,cancel=lambda:False,emit=lambda event:None)
    if result.returncode or result.stdout.strip()!=LOCK['version']:raise UnsupportedMedia('Version N_m3u8DL-RE incompatible')
    return path


def namespace_available():
    if sys.platform!='linux' or not shutil.which('unshare') or not Path('/usr/sbin/ip').is_file():return False
    try:
        return subprocess.run(['unshare','--user','--map-root-user','--net','true'],capture_output=True,timeout=5).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


class N_m3u8Backend:
    name='nm3u8dl-re-evaluation'
    capabilities=BackendCapabilities(frozenset({'hls','dash'}),frozenset({'aes128','fmp4','byterange','separate_audio','segmented_subtitles'}))
    def __init__(self,directory,tool,*,evaluation=False,client_factory=None,validator=None,clock_probe=False):
        if not evaluation:raise UnsupportedMedia('Backend non adopté : évaluation explicite uniquement')
        self.directory=Path(directory).resolve();self.tool=Path(tool);self.client_factory=client_factory;self.validator=validator
        self.last_relay=None;self.last_result=None;self.last_console='';self.last_network={}
        self.clock_probe=clock_probe

    async def transfer(self,task,media,emit,*,unsafe_cache_probe=False):
        if not self.capabilities.accepts(media):raise UnsupportedMedia('Format hors périmètre du bac à sable')
        if media.tracks:raise UnsupportedMedia('Pistes externes au manifeste non encore validées dans le bac à sable')
        tool=await asyncio.to_thread(pinned_tool,self.tool)
        if not await asyncio.to_thread(namespace_available):raise UnsupportedMedia('Isolation réseau indisponible ; exécution refusée')
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:raise UnsupportedMedia('FFmpeg requis pour l’assemblage interne')
        work=self.directory/hashlib.sha256(task.id.encode()).hexdigest()[:24];work.mkdir(parents=True,exist_ok=True,mode=0o700)
        relay=ManifestRelay(work/'relay',client_factory=self.client_factory,validator=self.validator,headers=media.headers,cancel=lambda:task.cancelled or task.paused,clock_probe=self.clock_probe)
        self.last_relay=relay
        state={'backend':self.name,'version':LOCK['version'],'workspace':str(work),'status':'acquiring'}
        write_metadata(work/'checkpoint.json',state)
        try:
            emit(MediaEvent('started'))
            entry=await relay.materialize(media.url);plan=relay.seal(entry)
            state.update(status='assembling',representation=plan['representation'],resources=len(plan['files']))
            write_metadata(work/'checkpoint.json',state)
            emit(MediaEvent('network',bytes_received=relay.downloaded))
            # N_m3u8DL-RE trusts existence of its cache files. Rebuild from our
            # independently verified relay cache; never trust tool intermediates.
            if not unsafe_cache_probe:
                shutil.rmtree(work/'tool-cache',ignore_errors=True)
            shutil.rmtree(work/'assembled',ignore_errors=True)
            args=['unshare','--user','--map-root-user','--net',sys.executable,str(ROOT/'scripts/nm3u8dl_worker.py'),str(relay.directory),str(tool),ffmpeg,os.readlink('/proc/self/ns/net')]
            job=asyncio.create_task(asyncio.to_thread(run_process,args,timeout=180,cancel=lambda:task.cancelled or task.paused,emit=lambda event:None))
            try:result=await asyncio.shield(job)
            except asyncio.CancelledError:
                task.cancelled=True
                try:await job
                except Exception:pass
                raise
            self.last_console=result.stdout+result.stderr
            for line in result.stdout.splitlines():
                if line.startswith('ANIMELAB_OFFLINE_RESULT='):self.last_network=json.loads(line.partition('=')[2])
            if result.returncode:raise UnsupportedMedia('Assemblage N_m3u8DL-RE échoué ; ressources vérifiées conservées')
            path=work/'assembled/assembled.mkv'
            if not path.is_file():raise UnsupportedMedia('Assemblage absent malgré la sortie du programme')
            probe=await asyncio.to_thread(run_process,[shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',path],timeout=20,cancel=lambda:task.cancelled or task.paused,emit=lambda event:None)
            if probe.returncode:raise UnsupportedMedia('Assemblage illisible ; aucun résultat complet annoncé')
            inventory=json.loads(probe.stdout)
            if not any(s.get('codec_type')=='video' for s in inventory.get('streams',[])) or not any(s.get('codec_type')=='audio' for s in inventory.get('streams',[])):
                raise UnsupportedMedia('Piste vidéo ou audio obligatoire absente')
            if sum(s.get('codec_type')=='subtitle' for s in inventory['streams'])<plan['expectedSubtitles']:
                raise UnsupportedMedia('Piste de sous-titres annoncée mais absente')
            duration=float(inventory.get('format',{}).get('duration') or 0)
            if not duration or abs(duration-plan['expectedDuration'])>max(.25,.02*plan['expectedDuration']):
                raise UnsupportedMedia('Durée assemblée différente du manifeste ; résultat incomplet refusé')
            decode=await asyncio.to_thread(run_process,[ffmpeg,'-v','error','-xerror','-nostdin','-protocol_whitelist','file,pipe','-i',path,'-map','0:v','-map','0:a','-f','null','-'],timeout=60,cancel=lambda:task.cancelled or task.paused,emit=lambda event:None)
            if decode.returncode:raise UnsupportedMedia('Le décodage complet de l’assemblage a échoué')
            state.update(status='negative-probe-only' if self.clock_probe else 'assembled',bytes=path.stat().st_size,
                         usableForFinalization=not self.clock_probe)
            write_metadata(work/'checkpoint.json',state)
            self.last_result=inventory
            emit(MediaEvent('checkpoint',bytes_received=relay.downloaded))
            return TransferResult(self.name,str(path),not self.clock_probe,state)
        except BaseException:
            state['status']='interrupted' if task.cancelled or task.paused else 'failed'
            write_metadata(work/'checkpoint.json',state)
            raise
        finally:relay.revoke()
