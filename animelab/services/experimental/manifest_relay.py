"""Bounded offline relay prototype. No provider URL is given to an external tool.

Network acquisition uses SourceHTTP, with destination validation on every hop.
The tool receives only generated manifests and verified local resource copies.
This module is deliberately not registered in production.
"""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from animelab.media_policy import validate_media_url
from animelab.services.source_http import source_http
from animelab.services.media_contracts import UnsupportedMedia
from animelab.services.media_execution import MediaInterrupted
from animelab.services.download_resume import segment_digest, write_metadata

MAX_ASSETS=4096
MAX_BYTES=2*1024**3
MAX_RESOURCE=128*1024**2
MAX_MANIFEST=2*1024**2


def sha(value):
    return hashlib.sha256(value).hexdigest()


def attributes(line):
    result={}
    for match in re.finditer(r'(?:^|,)([A-Z0-9-]+)=("[^"]*"|[^,]*)',line.partition(':')[2]):
        key,value=match.groups()
        if key in result:raise UnsupportedMedia('Attribut HLS dupliqué')
        result[key]=value.strip('"')
    return result


def byte_range(value,default=None):
    match=re.fullmatch(r'(\d+)(?:@(\d+))?',value)
    if not match:raise UnsupportedMedia('Plage HLS invalide')
    length=int(match[1]);start=int(match[2]) if match[2] else default
    if start is None or not 0<length<=MAX_RESOURCE or start<0:raise UnsupportedMedia('Plage HLS implicite ambiguë')
    return start,start+length-1


def seconds(value):
    match=re.fullmatch(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?',value or '')
    if not match:raise UnsupportedMedia('Durée DASH statique non reconnue')
    result=sum(float(v or 0)*factor for v,factor in zip(match.groups(),(3600,60,1)))
    if not 0<result<=86400:raise UnsupportedMedia('Durée DASH hors limites')
    return result


class ManifestRelay:
    def __init__(self,directory,*,client_factory=None,validator=None,headers=None,cancel=None,clock_probe=False):
        self.directory=Path(directory).resolve();self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.validator=validator or validate_media_url
        self.client_factory=client_factory or (lambda **kw:source_http.async_client(timeout=30,url_validator=self.validator,**kw))
        self.headers=dict(headers or {})
        self.origin=None
        self.clock_probe=clock_probe
        self.cancel=cancel or (lambda:False)
        self.capability=secrets.token_urlsafe(32)
        self.revoked=False
        self.files={};self.resources={};self.manifests={};self.visiting=set();self.total=0;self.requests=0;self.downloaded=0
        self.expected_duration=0;self.expected_subtitles=0
        self.cache=self.directory/'cache.json'
        try:self.previous=json.loads(self.cache.read_text()) if self.cache.stat().st_size<4*1024**2 else {}
        except (OSError,ValueError):self.previous={}

    def check(self):
        if self.revoked or self.cancel():raise MediaInterrupted('Relais révoqué ou téléchargement interrompu')

    def revoke(self):
        self.revoked=True;self.capability=''

    def read(self,capability,name):
        if self.revoked or not secrets.compare_digest(capability,self.capability) or name not in self.files:
            raise PermissionError('Capacité de relais invalide')
        return self.directory/name

    def destination(self,url):
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.fragment:
            raise UnsupportedMedia('Destination de manifeste non autorisée')
        self.validator(url)
        return url

    async def fetch(self,url,*,ranges=None,manifest=False,key=False,_hops=0):
        self.check();self.destination(url)
        if _hops>6:raise UnsupportedMedia('Trop de redirections de ressource')
        identity=sha(json.dumps([url,ranges]).encode())
        extension=urlsplit(url).path.rsplit('.',1)[-1].lower()
        if extension not in ('ts','m4s','mp4','vtt','key','bin','m4a','aac'):extension='bin'
        name=identity+'.'+extension
        path=self.directory/name
        prior=self.previous.get(identity,{})
        valid=(not manifest and path.is_file() and prior.get('digest')==segment_digest(path))
        request_headers=dict(self.headers)
        # Authentication is origin scoped; SourceHTTP strips it on redirects too.
        if urlsplit(url).netloc!=self.origin:
            request_headers={k:v for k,v in request_headers.items() if k.lower() not in ('authorization','cookie')}
        if valid and prior.get('etag','').startswith('"') and not ranges:
            request_headers['If-None-Match']=prior['etag']
        if ranges:request_headers['Range']=f'bytes={ranges[0]}-{ranges[1]}'
        limit=MAX_MANIFEST if manifest else 16 if key else MAX_RESOURCE
        if len(self.resources)+len(self.manifests)>=MAX_ASSETS:raise UnsupportedMedia('Trop de ressources dans le manifeste')
        self.requests+=1
        async with self.client_factory(headers=request_headers,follow_redirects=False) as client:
            async with client.stream('GET',url) as response:
                # Mock clients must obey the same final destination check.
                self.destination(str(response.url))
                if response.status_code in (301,302,303,307,308):
                    target=urljoin(url,response.headers.get('location',''))
                    self.destination(target)
                    return await self.fetch(target,ranges=ranges,manifest=manifest,key=key,_hops=_hops+1)
                if response.status_code==304 and valid:
                    self.resources[identity]=prior;self.files[name]=prior['digest'];self.total+=prior['digest']['size']
                    if self.total>MAX_BYTES:raise UnsupportedMedia('Relais trop volumineux')
                    return path,prior.get('finalUrl',url)
                response.raise_for_status()
                if ranges:
                    declared_range=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('content-range',''))
                    if response.status_code!=206 or not declared_range or tuple(map(int,declared_range.groups()[:2]))!=ranges or int(declared_range[3])<=ranges[1]:
                        raise UnsupportedMedia('Le serveur ne respecte pas les plages du manifeste')
                content=bytearray()
                async for block in response.aiter_bytes(65536):
                    self.check();content.extend(block);self.downloaded+=len(block)
                    if len(content)>limit or self.total+len(content)>MAX_BYTES:raise UnsupportedMedia('Ressource de manifeste trop volumineuse')
                    if shutil.disk_usage(self.directory).free<len(content)+16*1024**2:raise UnsupportedMedia('Espace insuffisant pour le relais')
                declared=response.headers.get('content-length')
                if declared is not None and (not declared.isdigit() or int(declared)!=len(content)):
                    raise ConnectionError('Fragment tronqué ; aucun fragment partiel réutilisé')
                if not content or (ranges and len(content)!=ranges[1]-ranges[0]+1) or (key and len(content)!=16):
                    raise UnsupportedMedia('Ressource vide, plage ou clé AES invalide')
                if manifest:return bytes(content),str(response.url)
                partial=path.with_suffix('.partial')
                try:
                    with partial.open('wb') as output:
                        output.write(content);output.flush();os.fsync(output.fileno())
                    partial.replace(path);path.chmod(0o600)
                finally:partial.unlink(missing_ok=True)
                record={'digest':segment_digest(path),'etag':response.headers.get('etag','')[:512]}
                self.resources[identity]=record;self.files[name]=record['digest'];self.total+=len(content)
                # Persist verified whole resources so an interrupted materialization can resume.
                write_metadata(self.cache,{**self.previous,**self.resources})
                return path,str(response.url)

    async def resource(self,url,**kwargs):
        return (await self.fetch(url,**kwargs))[0].name

    async def materialize(self,url):
        self.check();self.destination(url)
        if self.origin is None:self.origin=urlsplit(url).netloc
        if url in self.visiting or len(self.visiting)>=8:raise UnsupportedMedia('Cycle ou profondeur de manifeste excessive')
        if url in self.manifests:return self.manifests[url]
        self.visiting.add(url)
        try:
            data,final=await self.fetch(url,manifest=True)
            if data.lstrip().startswith(b'#EXTM3U'):content=await self.hls(data.decode('utf-8-sig'),final);suffix='.m3u8'
            elif data.lstrip().startswith(b'<'):content=await self.dash(data,final);suffix='.mpd'
            else:raise UnsupportedMedia('Manifeste HLS/DASH attendu')
            name=sha(url.encode())+suffix
            path=self.directory/name;path.write_bytes(content);path.chmod(0o600)
            self.files[name]=segment_digest(path);self.manifests[url]=name
            return name
        finally:self.visiting.discard(url)

    async def hls(self,text,base):
        lines=text.splitlines();master=any(line.startswith('#EXT-X-STREAM-INF:') for line in lines)
        if not self.clock_probe and any(line.startswith('#EXT-X-DISCONTINUITY') for line in lines):
            raise UnsupportedMedia('Discontinuités non retenues : erreur de synchronisation reproduite avec la version épinglée')
        if not master and '#EXT-X-ENDLIST' not in lines:raise UnsupportedMedia('Live HLS non retenu dans le périmètre VOD')
        if sum(line.startswith('#EXT-X-STREAM-INF:') for line in lines)>1:raise UnsupportedMedia('Variantes multiples : sélection explicite non encore validée')
        for role in ('AUDIO','SUBTITLES'):
            if sum(line.startswith('#EXT-X-MEDIA:') and attributes(line).get('TYPE')==role for line in lines)>1:
                raise UnsupportedMedia('Plusieurs pistes de même rôle : aucune piste ne sera ignorée')
        self.expected_subtitles=max(self.expected_subtitles,sum(line.startswith('#EXT-X-MEDIA:') and attributes(line).get('TYPE')=='SUBTITLES' for line in lines))
        if not master:
            self.expected_duration=max(self.expected_duration,sum(float(line.partition(':')[2].partition(',')[0]) for line in lines if line.startswith('#EXTINF:')))
        output=[];pending=None;last_range=None;sequence=0
        for line in lines:
            self.check();line=line.strip()
            if line.startswith(('#EXT-X-SESSION-KEY','#EXT-X-SESSION-DATA','#EXT-X-I-FRAME','#EXT-X-PART','#EXT-X-PRELOAD','#EXT-X-DEFINE','#EXT-X-RENDITION-REPORT')):
                raise UnsupportedMedia('Extension HLS non validée')
            if line.startswith('#EXT-X-BYTERANGE:'):
                pending=line.partition(':')[2];continue
            if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):sequence=int(line.partition(':')[2])
            if line.startswith(('#EXT-X-MEDIA:','#EXT-X-KEY:','#EXT-X-MAP:')):
                attrs=attributes(line);uri=attrs.get('URI')
                if line.startswith('#EXT-X-KEY:'):
                    if attrs.get('METHOD')=='NONE':output.append(line);continue
                    if attrs.get('METHOD')!='AES-128' or attrs.get('KEYFORMAT','identity')!='identity':raise UnsupportedMedia('Seul AES-128 HLS standard est évalué')
                if not uri:raise UnsupportedMedia('URI HLS absente')
                target=urljoin(base,uri)
                if line.startswith('#EXT-X-MEDIA:'):new=await self.materialize(target)
                else:new=await self.resource(target,ranges=byte_range(attrs['BYTERANGE'],0) if 'BYTERANGE'in attrs else None,key=line.startswith('#EXT-X-KEY:'))
                line=line.replace('URI="'+uri+'"','URI="'+new+'"') if 'URI="' in line else re.sub(r'URI=[^,]*','URI="'+new+'"',line)
                if 'BYTERANGE'in attrs:line=re.sub(r'BYTERANGE=(?:"[^"]*"|[^,]*)','BYTERANGE="'+str(byte_range(attrs['BYTERANGE'],0)[1]-byte_range(attrs['BYTERANGE'],0)[0]+1)+'@0"',line)
                output.append(line);continue
            if line and not line.startswith('#'):
                target=urljoin(base,line)
                if master:new=await self.materialize(target)
                else:
                    same=last_range is not None and last_range[0]==target
                    bounds=byte_range(pending,last_range[1]+1 if same else None) if pending else None
                    new=await self.resource(target,ranges=bounds)
                    if bounds:
                        output.append('#EXT-X-BYTERANGE:'+str(bounds[1]-bounds[0]+1)+'@0')
                        last_range=(target,bounds[1])
                    else:last_range=None
                    pending=None;sequence+=1
                output.append(new);continue
            if line.startswith('#') and ('URI='in line or 'http://'in line or 'https://'in line):raise UnsupportedMedia('Référence HLS inconnue')
            output.append(line)
        if pending:raise UnsupportedMedia('Plage sans segment')
        return ('\n'.join(output)+'\n').encode()

    async def dash(self,data,base):
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise UnsupportedMedia('Entités XML non autorisées')
        try:root=ET.fromstring(data)
        except ET.ParseError as exc:raise UnsupportedMedia('XML DASH invalide') from exc
        ns='{urn:mpeg:dash:schema:mpd:2011}'
        ET.register_namespace('',ns[1:-1])
        if root.tag!=ns+'MPD' or root.get('type','static')!='static':raise UnsupportedMedia('Seul DASH statique est évalué')
        if any(element.tag.rsplit('}',1)[-1] in ('ContentProtection','Location','PatchLocation','UTCTiming','EventStream') or any('href' in attr for attr in element.attrib) for element in root.iter()):
            raise UnsupportedMedia('DASH protégé, référence externe ou extension non validée')
        periods=root.findall(ns+'Period')
        if len(periods)!=1:raise UnsupportedMedia('DASH multi-périodes non encore validé')
        period=periods[0];duration=seconds(period.get('duration') or root.get('mediaPresentationDuration'))
        self.expected_duration=max(self.expected_duration,duration)
        def location(node,parent):
            urls=node.findall(ns+'BaseURL')
            if len(urls)>1:raise UnsupportedMedia('BaseURL multiples non validées')
            value=urljoin(parent,(urls[0].text or '').strip()) if urls else parent
            for item in urls:node.remove(item)
            self.destination(value)
            return value
        base=location(period,location(root,base))
        for adaptation in period.findall(ns+'AdaptationSet'):
            ab=location(adaptation,base);representations=adaptation.findall(ns+'Representation')
            if len(representations)!=1:raise UnsupportedMedia('DASH : une représentation explicite par piste est requise')
            for rep in representations:
                rb=location(rep,ab)
                template=rep.find(ns+'SegmentTemplate')
                if template is None:template=adaptation.find(ns+'SegmentTemplate')
                segment_list=rep.find(ns+'SegmentList')
                if segment_list is None:segment_list=adaptation.find(ns+'SegmentList')
                if template is None and segment_list is None:raise UnsupportedMedia('DASH SegmentBase/SIDX non encore validé')
                if template is not None:
                    scale=int(template.get('timescale','1'));start=int(template.get('startNumber','1'))
                    if scale<=0:raise UnsupportedMedia('Échelle DASH invalide')
                    timeline=template.find(ns+'SegmentTimeline');values=[];cursor=0
                    if timeline is not None:
                        for s in timeline.findall(ns+'S'):
                            cursor=int(s.get('t',str(cursor)));d=int(s.get('d','0'));r=int(s.get('r','0'))
                            if d<=0 or r < -1:raise UnsupportedMedia('Timeline DASH invalide')
                            if r==-1:r=max(0,math.ceil((duration*scale-cursor)/d)-1)
                            if len(values)+r+1>MAX_ASSETS:raise UnsupportedMedia('Timeline DASH trop grande')
                            for _ in range(r+1):values.append((cursor,d));cursor+=d
                    else:
                        d=int(template.get('duration','0'))
                        if d<=0:raise UnsupportedMedia('Durée de segment DASH absente')
                        count=math.ceil(duration*scale/d)
                        if count>MAX_ASSETS:raise UnsupportedMedia('DASH trop grand')
                        values=[(i*d,d) for i in range(count)]
                    def expand(text,index,t):
                        def sub(match):
                            name,width=match.groups();value={'RepresentationID':rep.get('id',''),'Bandwidth':rep.get('bandwidth',''),'Number':str(start+index),'Time':str(t)}[name]
                            return value.zfill(int(width)) if width else value
                        expanded=re.sub(r'\$(RepresentationID|Bandwidth|Number|Time)(?:%0(\d{1,2})d)?\$',sub,text)
                        if '$'in expanded:raise UnsupportedMedia('Template DASH inconnu')
                        return urljoin(rb,expanded)
                    converted=ET.fromstring(ET.tostring(template))
                    init=template.get('initialization')
                    if not values or not template.get('media'):raise UnsupportedMedia('DASH sans segment média')
                    if init:converted.set('initialization',await self.resource(expand(init,0,values[0][0])))
                    prefix=sha((rb+rep.get('id','')).encode())
                    converted.set('media',prefix+'_$Number$.m4s')
                    converted.set('startNumber',str(start))
                    for i,(t,d) in enumerate(values):
                        stored=await self.resource(expand(template.get('media',''),i,t))
                        alias=prefix+'_'+str(start+i)+'.m4s'
                        shutil.copyfile(self.directory/stored,self.directory/alias)
                        (self.directory/alias).chmod(0o600)
                        self.files[alias]=self.files[stored]
                else:
                    converted=ET.fromstring(ET.tostring(segment_list))
                    if not converted.get('duration'):raise UnsupportedMedia('SegmentList sans durée non validé par la version épinglée')
                    for item in converted:
                        if item.tag not in (ns+'Initialization',ns+'SegmentURL',ns+'SegmentTimeline'):raise UnsupportedMedia('SegmentList DASH inconnu')
                        if item.tag==ns+'SegmentTimeline':continue
                        field='sourceURL' if item.tag==ns+'Initialization' else 'media';range_key='range' if field=='sourceURL' else 'mediaRange'
                        bounds=None
                        if range_key in item.attrib:
                            match=re.fullmatch(r'(\d+)-(\d+)',item.get(range_key))
                            if not match or int(match[2])<int(match[1]) or int(match[2])-int(match[1])+1>MAX_RESOURCE:raise UnsupportedMedia('Plage DASH invalide')
                            bounds=(int(match[1]),int(match[2]));item.attrib.pop(range_key)
                        if not item.get(field):raise UnsupportedMedia('Référence DASH absente')
                        item.set(field,await self.resource(urljoin(rb,item.get(field)),ranges=bounds))
                for child in list(rep):
                    if child.tag in (ns+'SegmentTemplate',ns+'SegmentList'):rep.remove(child)
                rep.append(converted)
            for child in list(adaptation):
                if child.tag in (ns+'SegmentTemplate',ns+'SegmentList'):adaptation.remove(child)
        return ET.tostring(root,encoding='utf-8',xml_declaration=True)

    def seal(self,entry):
        self.check()
        plan={'version':1,'entry':entry,'files':self.files,'representation':sha(json.dumps(self.files,sort_keys=True).encode()),
              'expectedDuration':self.expected_duration,'expectedSubtitles':self.expected_subtitles}
        write_metadata(self.directory/'plan.json',plan)
        return plan
