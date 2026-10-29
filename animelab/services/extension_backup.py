"""Portable extension identities and stubs, without sessions or executable trust.

Restoring metadata never installs/approves an APK or enables a source. Existing
library/download rows are untouched; conflicting identities are reported.
"""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from animelab.services.extension_catalog import canonical_url

MAX_BACKUP = 128*1024*1024
MAX_METADATA = 8*1024*1024


def snapshot(service):
    with service._get_conn() as conn:
        repositories = [dict(row) for row in conn.execute('SELECT id,url,name,signing_key FROM extension_repos')]
        installations = [dict(row) for row in conn.execute(
            'SELECT id,repo_id,pkg,name,lang,runtime,installed_version,installed_code,extension_lib,base_url FROM imported_extensions '
            'WHERE installed_version IS NOT NULL OR recipe_json IS NOT NULL OR is_enabled=1 OR id IN (SELECT ext_id FROM extension_sources)')]
        sources = [dict(row) for row in conn.execute(
            'SELECT source_key,ext_id,upstream_id,pkg,name,lang,base_url,runtime,hidden,pinned FROM extension_sources')]
    return {'format':'animelab-extension-backup','version':1,'repositories':repositories,
            'installations':installations,'sources':sources,'includesCredentials':False,'includesTrust':False,
            'notice':'APK et recettes à revérifier avant activation ; aucune session ni préférence secrète sauvegardée.'}


def export_backup(service, include_artifacts=False):
    document=snapshot(service)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr('extensions.json',json.dumps(document,ensure_ascii=False))
        if include_artifacts:
            with service._get_conn() as conn:
                artifacts=conn.execute('SELECT sha256,path FROM extension_artifacts').fetchall()
            total=0
            for artifact in artifacts:
                path=Path(artifact['path'])
                if not path.is_file():
                    continue
                total+=path.stat().st_size
                if total>MAX_BACKUP-MAX_METADATA:
                    raise ValueError('Artefacts trop volumineux pour cette sauvegarde.')
                with path.open('rb') as stream:
                    digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if digest!=artifact['sha256']:
                    raise ValueError('Un artefact en cache a été modifié.')
                output.write(path,'apks/'+digest+'.apk')
    return archive.getvalue()


def restore_backup(service, raw):
    if len(raw)>MAX_BACKUP:
        raise ValueError('Sauvegarde trop volumineuse.')
    try:
        archive=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as error:
        raise ValueError('Archive de sauvegarde invalide.') from error
    with archive:
        members=archive.infolist()
        if len(members)>2000 or len({m.filename for m in members})!=len(members):
            raise ValueError('Archive ambiguë ou trop volumineuse.')
        if sum(m.file_size for m in members)>MAX_BACKUP:
            raise ValueError('Archive décompressée trop volumineuse.')
        for member in members:
            if member.filename!='extensions.json' and not re.fullmatch(r'apks/[a-f0-9]{64}\.apk',member.filename):
                raise ValueError('Chemin de sauvegarde non autorisé.')
        try:
            meta=archive.getinfo('extensions.json')
        except KeyError as error:
            raise ValueError('Métadonnées absentes.') from error
        if meta.file_size>MAX_METADATA:
            raise ValueError('Métadonnées trop volumineuses.')
        try:
            document=json.loads(archive.read(meta))
        except (ValueError,UnicodeError) as error:
            raise ValueError('Métadonnées illisibles.') from error
        if not isinstance(document,dict) or document.get('format')!='animelab-extension-backup' or document.get('version')!=1:
            raise ValueError('Format de sauvegarde non pris en charge.')
        for key in ('repositories','installations','sources'):
            if not isinstance(document.get(key),list) or len(document[key])>20000 or any(not isinstance(row,dict) for row in document[key]):
                raise ValueError('Liste de sauvegarde invalide.')
        # Verify every embedded artifact before changing the database/cache.
        artifacts=[]
        for member in members:
            if member.filename.startswith('apks/'):
                digest=hashlib.sha256(archive.read(member)).hexdigest()
                if member.filename!='apks/'+digest+'.apk':
                    raise ValueError('Empreinte d’artefact invalide.')
                artifacts.append((member,digest))
        warnings=[]
        repo_ids, extension_ids = {}, {}
        with service._get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for repo in document['repositories']:
                if repo['url']=='android:installed':
                    url=repo['url']
                else:
                    url=canonical_url(repo['url'])
                conn.execute('INSERT INTO extension_repos(url,name,is_active) VALUES (?,?,0) ON CONFLICT(url) DO NOTHING',(url,str(repo.get('name') or url)))
                current=conn.execute('SELECT id,signing_key FROM extension_repos WHERE url=?',(url,)).fetchone()
                repo_ids[repo['id']]=current['id']
                if repo.get('signing_key') and repo['signing_key']!=current['signing_key']:
                    warnings.append({'repo':url,'code':'restored_key_requires_verification'})
            for entry in document['installations']:
                if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+',entry.get('pkg','')):
                    raise ValueError('Identité de package invalide.')
                if entry['repo_id'] not in repo_ids or entry.get('runtime') not in ('recipe','android-apk'):
                    raise ValueError('Moteur ou dépôt de sauvegarde invalide.')
                conn.execute('INSERT INTO imported_extensions(repo_id,pkg,name,lang,version,runtime,is_enabled,catalog_state) '
                             "VALUES (?,?,?,?,?,?,0,'restored') ON CONFLICT(repo_id,pkg) DO NOTHING",
                             (repo_ids[entry['repo_id']],entry['pkg'],str(entry['name']),str(entry['lang']),entry.get('installed_version'),entry['runtime']))
                row=conn.execute('SELECT id FROM imported_extensions WHERE repo_id=? AND pkg=?',(repo_ids[entry['repo_id']],entry['pkg'])).fetchone()
                extension_ids[entry['id']]=row['id']
            for source in document['sources']:
                if source['ext_id'] not in extension_ids:
                    warnings.append({'source':source.get('source_key'),'code':'missing_extension_stub'})
                    continue
                existing=conn.execute('SELECT pkg FROM extension_sources WHERE source_key=?',(source['source_key'],)).fetchone()
                if existing and existing['pkg']!=source['pkg']:
                    warnings.append({'source':source['source_key'],'code':'source_identity_conflict'})
                    continue
                conn.execute('INSERT INTO extension_sources(source_key,ext_id,upstream_id,pkg,name,lang,base_url,runtime,enabled,hidden,pinned) '
                             'VALUES (?,?,?,?,?,?,?,?,0,?,?) ON CONFLICT(source_key) DO NOTHING',
                             (source['source_key'],extension_ids[source['ext_id']],source.get('upstream_id'),source['pkg'],source['name'],source['lang'],
                              source.get('base_url') or '',source['runtime'],int(bool(source.get('hidden'))),int(bool(source.get('pinned')))))
        from animelab.services.extension_service import APKS_DIR
        for member,digest in artifacts:
            path=APKS_DIR/(digest+'.apk')
            temporary=APKS_DIR/(digest+'.restore')
            try:
                temporary.write_bytes(archive.read(member)); temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return {'success':True,'repositories':len(repo_ids),'extensions':len(extension_ids),'sources':len(document['sources']),
                'artifacts':len(artifacts),'warnings':warnings,'requiresRevalidation':True,'installedAPKCount':0}
