"""Persist observations and immutable, bounded recipe revisions without remote payloads."""
from datetime import datetime, timezone
import hashlib
import json
import httpx
from pydantic import ValidationError
from animelab.database import sqlite_connection
from animelab.diagnostics import telemetry, domain


class SelectorMismatch(ValueError):
    pass


class InvalidSelector(ValueError):
    pass


HEALTH_MESSAGES = {
    'healthy':'Source opérationnelle.',
    'empty':'La source a répondu sans contenu exploitable.',
    'protection':'Le site demande une vérification.',
    'rate_limited':'Le site limite les requêtes. Patientez avant de réessayer.',
    'network_error':'La connexion au site a échoué. Réessayez.',
    'http_error':'Le site a refusé la requête.',
    'selector_error':'Les éléments attendus sont absents ou le sélecteur est invalide. Vérifiez la recette.',
    'parse_error':'La réponse du site ne correspond pas au format attendu.',
    'unsupported':'Cette source ne propose pas cette fonctionnalité.',
    'internal_error':'Une erreur interne est survenue.',
}


def classify(error):
    from animelab.services.source_http import VerificationRequired, RateLimited
    from animelab.services.aniyomi_dex_parser import RecipeVersionError
    from animelab.api_errors import APIProblem
    if isinstance(error,APIProblem) and error.problem.code=='source_operation_unsupported': return 'unsupported','operation_unsupported'
    if isinstance(error,RecipeVersionError): return 'unsupported','recipe_schema_unsupported'
    if isinstance(error, VerificationRequired): return 'protection','verification_required'
    if isinstance(error, RateLimited): return 'rate_limited','rate_limited'
    if isinstance(error,(InvalidSelector,SelectorMismatch)): return 'selector_error',type(error).__name__
    if isinstance(error,httpx.HTTPStatusError): return ('rate_limited','rate_limited') if error.response.status_code==429 else ('http_error','upstream_http_error')
    if isinstance(error,(httpx.RequestError,TimeoutError)): return 'network_error','source_unreachable'
    if isinstance(error,(json.JSONDecodeError,ValidationError,ValueError,KeyError,TypeError)): return 'parse_error','unexpected_payload'
    if isinstance(error,NotImplementedError): return 'unsupported','operation_unsupported'
    return 'internal_error','source_failure'


def save_recipe_revision(conn, ext_id, recipe, reason, *, force=False):
    payload=json.dumps(recipe,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    fingerprint=hashlib.sha256(payload.encode()).hexdigest()
    previous=conn.execute('SELECT revision,fingerprint FROM extension_recipe_versions WHERE ext_id=? ORDER BY revision DESC LIMIT 1',(ext_id,)).fetchone()
    if not force and previous and previous['fingerprint']==fingerprint: return previous['revision']
    revision=(previous['revision'] if previous else 0)+1
    conn.execute('INSERT INTO extension_recipe_versions(ext_id,revision,schema_version,fingerprint,recipe_json,reason) VALUES (?,?,?,?,?,?)',
                 (ext_id,revision,1,fingerprint,payload,reason))
    conn.execute('UPDATE imported_extensions SET recipe_revision=? WHERE id=?',(revision,ext_id))
    conn.execute('DELETE FROM extension_recipe_versions WHERE ext_id=? AND revision NOT IN '
                 '(SELECT revision FROM extension_recipe_versions WHERE ext_id=? ORDER BY revision DESC LIMIT 20)',(ext_id,ext_id))
    return revision


class ExtensionObservability:
    def record(self,pkg,operation,*,count=0,error=None,duration_ms=0,db_path=None,base_url='',recipe_revision=None):
        status,code=classify(error) if error else ('healthy','ok') if count or operation=='search' else ('empty','no_content')
        stamp=datetime.now(timezone.utc).isoformat()
        with sqlite_connection(db_path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            ext=conn.execute('SELECT e.id,e.recipe_revision FROM imported_extensions e JOIN extension_repos r ON r.id=e.repo_id WHERE e.pkg=? AND r.is_active=1',(pkg,)).fetchone()
            if not ext: return {'status':status,'code':code}
            if recipe_revision is not None and recipe_revision != ext['recipe_revision']:
                return {'status':status,'code':code,'discarded':True}
            prior=conn.execute('SELECT * FROM extension_health WHERE ext_id=? AND operation=?',(ext['id'],operation)).fetchone()
            success=status=='healthy'
            conn.execute('INSERT INTO extension_health(ext_id,operation,status,code,checked_at,success_at,failure_streak,duration_ms,result_count,recipe_revision) '
                'VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ext_id,operation) DO UPDATE SET '
                'status=excluded.status,code=excluded.code,checked_at=excluded.checked_at,success_at=excluded.success_at,'
                'failure_streak=excluded.failure_streak,duration_ms=excluded.duration_ms,result_count=excluded.result_count,recipe_revision=excluded.recipe_revision',
                (ext['id'],operation,status,code,stamp,stamp if success else prior['success_at'] if prior else None,
                 0 if success else (prior['failure_streak'] if prior else 0)+1,max(0,duration_ms),count,ext['recipe_revision']))
        telemetry.event('extension_check',source=pkg,operation=operation,status=status,code=code,count=count,durationMs=duration_ms,domain=domain(base_url))
        return {'status':status,'code':code}

    def history(self,conn,ext_id):
        return [dict(row) for row in conn.execute('SELECT revision,schema_version,fingerprint,reason,created_at FROM extension_recipe_versions WHERE ext_id=? ORDER BY revision DESC LIMIT 20',(ext_id,))]

    def health(self,conn,ext_id):
        rows=[dict(row) for row in conn.execute('SELECT operation,status,code,checked_at,success_at,failure_streak,duration_ms,result_count,recipe_revision FROM extension_health WHERE ext_id=? ORDER BY checked_at DESC',(ext_id,))]
        for row in rows: row['messageKey']=HEALTH_MESSAGES.get(row['status'],HEALTH_MESSAGES['internal_error'])
        return rows


extension_observability=ExtensionObservability()
