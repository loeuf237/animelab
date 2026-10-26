"""Shared-server media destinations, including every redirect and HLS child URL."""
import os
import re

from fastapi import HTTPException

from animelab.security import get_all_allowed_domains, is_safe_url


def media_domains():
    domains = get_all_allowed_domains()
    # Extractors also contain loose matching fragments such as 'vidmoly'. Those
    # are not domain grants: accept only complete DNS hostnames here.
    from animelab.services.extractors import extractor_registry
    domains.update(domain for domain in extractor_registry.domains()
                   if re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z]{2,}', domain))
    domains.update(value.strip().lower() for value in os.getenv('ANIMELAB_MEDIA_DOMAINS', '').split(',')
                   if re.fullmatch(r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}', value.strip()))
    return domains


def validate_media_url(url):
    domains = media_domains() if os.getenv('ANIMELAB_SHARED_WORKER') == '1' else None
    if not is_safe_url(str(url), allowed_domains=domains):
        raise HTTPException(400, 'URL de média non autorisée ; demandez à l’administrateur d’approuver son domaine')
