"""Official store wire formats, migrations and bounded transport regressions."""
import gzip
import importlib
import json

import httpx
import pytest

from animelab.services.extension_catalog import decode_index, read_catalog, normalize_entries
from animelab.services.extension_versions import newer


def field(number, value):
    def varint(value):
        result=bytearray()
        while value > 127:
            result.append((value & 127)|128); value >>= 7
        return bytes(result)+bytes([value])
    if isinstance(value,int):
        return varint(number << 3)+varint(value)
    value=value.encode() if isinstance(value,str) else value
    return varint(number << 3 | 2)+varint(len(value))+value


def entry():
    return {'name':'A','packageName':'study.alpha','versionName':'17.2','versionCode':2,'extensionLib':'17',
            'resources':{'apkUrl':'https://cdn.example/a.apk','iconUrl':'https://cdn.example/a.png'},
            'sources':[{'id':str(2**60+1),'name':'Alpha','language':'fr','homeUrl':'https://source.example'}]}


def protobuf_store():
    # Field numbers come from upstream index/index.proto, not Python DTO names.
    source=field(1,2**60+1)+field(2,'Alpha')+field(3,'fr')+field(4,'https://source.example')
    resources=field(1,'https://cdn.example/a.apk')+field(2,'https://cdn.example/a.png')
    extension=field(1,'A')+field(2,'study.alpha')+field(3,resources)+field(4,'17')+field(5,2)+field(6,'17.2')+field(9,source)
    return field(1,'Store')+field(2,'ST')+field(3,'a'*64)+field(4,field(1,'https://store.example'))+field(101,field(1,extension))


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding',['json','protobuf','gzip-json','gzip-protobuf'])
async def test_modern_store_formats_preserve_full_source_identity(encoding):
    document={'name':'Store','badgeLabel':'ST','signingKey':'a'*64,'contact':{'website':'https://store.example'},
              'extensionList':{'extensions':[entry()]}}
    wire=json.dumps(document).encode() if encoding.endswith('json') else protobuf_store()
    if encoding.startswith('gzip'):
        wire=gzip.compress(wire)
    async def fetch(url): return wire
    result=await read_catalog('https://store.example/index.pb',fetch)
    assert result.entries[0]['sources'][0]['id']==str(2**60+1)
    assert result.entries[0]['apk']=='https://cdn.example/a.apk'
    assert result.entries[0]['code']==2
    assert result.metadata['signingKeyFingerprint']=='a'*64


@pytest.mark.asyncio
async def test_legacy_metadata_migrates_to_external_list():
    payloads={
        'https://store.example/index.min.json':b'[]',
        'https://store.example/repo.json':json.dumps({'meta':{'name':'Old'},'index_v2':'/modern.pb'}).encode(),
        'https://store.example/modern.pb':json.dumps({'name':'New','extensionListUrl':'https://cdn.example/list.json'}).encode(),
        'https://cdn.example/list.json':gzip.compress(json.dumps({'extensions':[entry()]}).encode()),
    }
    visited=[]
    async def fetch(url): visited.append(url); return payloads[url]
    result=await read_catalog('https://store.example/index.min.json',fetch)
    assert result.metadata['name']=='New'
    assert len(visited)==4


@pytest.mark.asyncio
async def test_cyclic_migration_fails_without_returning_an_empty_catalog():
    async def fetch(url):
        return json.dumps({'meta':{'name':'Cycle'},'index_v2':url}).encode()
    with pytest.raises(ValueError,match='Boucle'):
        await read_catalog('https://store.example/repo.json',fetch)


@pytest.mark.parametrize('wire',[b'\x0a\x80',b'\x00',b'\x0a\xff\xff\xff\x7f',b'\x0b',b'\x08\x01'])
def test_malformed_protobuf_is_rejected(wire):
    with pytest.raises(ValueError): decode_index(wire)


def test_gzip_expansion_budget_and_duplicate_packages(monkeypatch):
    module=importlib.import_module('animelab.services.extension_catalog')
    monkeypatch.setattr(module,'MAX_INDEX_BYTES',1024)
    with pytest.raises(ValueError): decode_index(gzip.compress(b' '*2048))
    with pytest.raises(ValueError,match='dupliqué'): normalize_entries([entry(),entry()],'https://store.example')
    assert decode_index(b'\xef\xbb\xbf \n[]')==[]


@pytest.mark.parametrize('remote,local,rc,lc,expected',[
    ('17.2','17.20',2,20,False),('renamed','old',2,1,True),('different','same',1,1,False),
    ('1.4.30','1.4.29',None,None,True),('14.2','14.20',None,None,False),('new','old',None,None,False),
])
def test_update_uses_numeric_build_identity(remote,local,rc,lc,expected):
    assert newer(remote,local,rc,lc) is expected


@pytest.mark.asyncio
async def test_bounded_source_response_closes_before_consuming_the_remaining_body(monkeypatch):
    module=importlib.import_module('animelab.services.source_http')
    state={'chunks':0,'closed':False}
    class Response:
        status_code=200
        headers={}
        request=httpx.Request('GET','https://source.example')
        async def aiter_bytes(self):
            for _ in range(1000):
                state['chunks']+=1
                yield b'x'*100
    class Stream:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return Response()
        async def __aexit__(self,*args): state['closed']=True
    monkeypatch.setattr(module,'SourceStream',Stream)
    client=module.AsyncSourceClient(module.source_http)
    with pytest.raises(ValueError,match='taille'):
        await client.get('https://source.example',max_response_bytes=250)
    assert state=={'chunks':3,'closed':True}
