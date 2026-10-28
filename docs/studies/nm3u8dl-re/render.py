"""Render/revalidate this proposal dossier; never imports the running engine.

Run from the repository root: python docs/studies/nm3u8dl-re/render.py
Requires the existing local PlantUML executable, Java and Graphviz.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.render_architecture import check_reference, gallery

REFERENCES = {
    '01-cas-utilisation': ['animelab/api_contracts.py:SubtitleTrack'],
    '02-composants-existants': [
        'animelab/services/download_manager.py:DownloadManagerService',
        'animelab/services/download_stages/transfer.py:TransferWorker._download_single_file',
        'animelab/services/download_stages/transfer.py:TransferWorker._download_hls_segments_native',
        'animelab/services/download_stages/media.py:MediaPipeline._mux_subtitles_with_ffmpeg',
        'animelab/services/extractors/ytdlp_fallback.py:YtDlpFallbackExtractor.extract'],
    '03-composants-cibles': [
        'animelab/services/source_http.py:SourceHTTPService',
        'animelab/media_policy.py:validate_media_url',
        'animelab/services/download_stages/scheduler.py:DownloadScheduler'],
    '04-classes-cibles': [
        'animelab/models/download_task.py:DownloadTask',
        'animelab/services/subtitle_service.py:normalize_subtitles',
        'animelab/services/recipe_runtime.py:RecipeRuntime.stream'],
    '05-sequence-episode': [
        'animelab/services/aniyomi_container.py:AniyomiContainerSource.get_episode_sources',
        'animelab/services/download_stages/media.py:MediaPipeline._download_subtitles'],
    '06-activite-sortie': ['animelab/services/download_stages/media.py:MediaPipeline._prepare'],
    '07-etats-reprise': ['animelab/services/download_stages/state.py:transition'],
    '08-merise-mcd': ['animelab/models/download_task.py:DownloadTaskEntity'],
    '09-deploiement': [
        'animelab/media_tools.py:run',
        'android/app/src/main/java/com/animan/app/MediaBridge.kt:MediaBridge'],
}
CATEGORIES = ['cas', 'classes', 'cible', 'classes', 'sequence', 'cible', 'cible', 'classes', 'deploiement']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    sources = sorted((DIRECTORY / 'plantuml').glob('*.puml'))
    if len(sources) != 9:
        raise ValueError('Expected nine study diagrams')
    if not args.check_only:
        subprocess.run(['plantuml', '-charset', 'UTF-8', '-tsvg', '-o', '../svg',
                        *map(str, sources)], check=True, timeout=180)
    diagrams = []
    for source, category in zip(sources, CATEGORIES):
        title = next(line[6:] for line in source.read_text().splitlines() if line.startswith('title '))
        svg = DIRECTORY / 'svg' / (source.stem + '.svg')
        # PlantUML embeds CRLF source text in some SVG comments. Normalize the
        # generated file so newly staged diagrams pass Git's whitespace checks.
        content = svg.read_bytes()
        normalized = content.replace(b'\r\n', b'\n')
        if content != normalized:
            svg.write_bytes(normalized)
        root = ET.fromstring(svg.read_text())
        if 'syntax error' in ' '.join(root.itertext()).lower():
            raise ValueError('Invalid rendered diagram: ' + source.name)
        diagrams.append(dict(id=source.stem, title=title, category=category,
            proposed=not source.stem.startswith('02-'),
            references=[check_reference(ref) for ref in REFERENCES[source.stem]],
            source='plantuml/' + source.name, svg='svg/' + svg.name,
            width=int(root.attrib['width'].removesuffix('px')),
            height=int(root.attrib['height'].removesuffix('px'))))
    if args.check_only:
        print(f'Validated {len(diagrams)} SVG diagrams and {sum(len(x["references"]) for x in diagrams)} code references')
        return
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = {'analysis_date': '2026-10-27', 'analyzed_commit': commit,
                'scope': 'P1-P9 implemented locally; P14 JNI implementation awaiting Android validation; P12 not adopted, P13/P15 not retained',
                'upstream_tag': 'v0.6.0-beta', 'diagrams': diagrams}
    (DIRECTORY / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    html = gallery(diagrams, commit)
    html = html.replace('AnimeLab — dossier UML et architecture', 'AnimeLab — sous-titres et N_m3u8DL-RE')
    html = html.replace('AnimeLab — dossier UML', 'AnimeLab — sous-titres et N_m3u8DL-RE')
    html = html.replace('17 diagrammes affichés', '9 diagrammes affichés')
    html = html.replace('Cible partiellement réalisée ; découplages restants proposés', 'Socle P1–P9 réalisé ; P13/P15 non retenus ; P14 implémenté, validation Android en attente')
    html = html.replace('Les vues de l’existant sont issues du code ; la vue verte décrit une évolution proposée.',
        'Le diagramme violet décrit l’existant ; les vues vertes sont des propositions. Binaire N_m3u8DL-RE évalué sous Linux x64 ; non adopté en production.')
    html = html.replace('Cas d’utilisation détaillés et axes d’amélioration', 'Étude de faisabilité et plan de migration')
    html = html.replace('href="../../', 'href="../../../')
    html = html.replace('<nav aria-label=', '''<p>27 octobre 2026 · <a href="dossier-nm3u8dl-re.zip">Télécharger tout le dossier</a> · <a href="local-proof.json">Preuve FFmpeg locale</a> · <a href="PRIORITES_IMPLEMENTATION.md">Priorités d’implémentation P1 à P15</a> · <a href="IMPLEMENTATION_P1_P5.md">Livraison P1–P5</a> · <a href="IMPLEMENTATION_P6_P7.md">Livraison P6–P7</a> · <a href="IMPLEMENTATION_P8.md">Livraison P8 et validations</a> · <a href="IMPLEMENTATION_P9.md">Livraison P9 et synchronisation</a> · <a href="subtitle-sync-proof.json">Mesures Alass</a></p>
<p><a href="IMPLEMENTATION_P10_P13.md">Bilan P10–P13</a> · <a href="nm3u8dl-proof.json">Mesures du vrai binaire</a> · <a href="nm3u8dl-decision.json">Décision P12</a> · <a href="N_m3u8DL-RE-LICENSE.txt">Licence amont MIT</a></p>
<p><a href="IMPLEMENTATION_P14_P15.md">Bilan P14–P15</a> · <a href="android-p14-p15-decision.json">Validation Android et décision Bionic</a> : JNI implémenté localement, essais Android/CI encore requis.</p>
<aside><h2>Décision P12 : non adopté en production</h2><p>Conserver les extracteurs et FFmpeg. N_m3u8DL-RE 0.6.0-beta a été évalué sur un corpus synthétique sous Linux x64. Deux défauts de reprise et de synchronisation empêchent son adoption ; P13/P15 sont non retenus pour cette version.</p>
<ul><li><strong>MP4 hardsub :</strong> une langue incrustée dans l’image, un audio choisi, aucune piste de sous-titres séparée. Réencodage requis.</li>
<li><strong>MKV multipiste :</strong> langues sélectionnables et pistes vidéo/audio copiées lorsque compatibles. Une base de multiplexage existe déjà dans AnimeLab.</li>
<li><strong>Sous-titres externes :</strong> préserver les pistes des extensions et ajouter des fournisseurs API indépendants (OpenSubtitles/SubDL), avec aperçu et décalage.</li></ul>
<p>Preuves locales : sorties FFmpeg vérifiées et cinq cas N_m3u8DL-RE utilisables sur six, avec contre-exemples conservés. Ces mesures ne démontrent pas un gain réseau en production. Hardsub Android P14, autres plateformes et fournisseurs authentifiés restent à valider. <a href="README.md">Lire l’étude et les critères de passage</a>.</p></aside><nav aria-label=''')
    (DIRECTORY / 'index.html').write_text(html)
    archive = DIRECTORY / 'dossier-nm3u8dl-re.zip'
    shutil_source = ROOT / 'scripts' / 'evaluate_subtitle_sync.py'
    # Include the reproducible source in the downloadable dossier.
    (DIRECTORY / 'evaluate_subtitle_sync.py').write_bytes(shutil_source.read_bytes())
    files = [DIRECTORY / name for name in ('README.md', 'PRIORITES_IMPLEMENTATION.md', 'IMPLEMENTATION_P1_P5.md', 'IMPLEMENTATION_P6_P7.md', 'IMPLEMENTATION_P8.md', 'IMPLEMENTATION_P9.md', 'subtitle-sync-proof.json', 'evaluate_subtitle_sync.py', 'index.html', 'manifest.json', 'local-proof.json', 'upstream-release.json', 'render.py', 'prove_outputs.py')]
    files += [DIRECTORY / name for name in ('IMPLEMENTATION_P10_P13.md', 'nm3u8dl-proof.json', 'nm3u8dl-decision.json', 'N_m3u8DL-RE-LICENSE.txt')]
    files += [DIRECTORY / name for name in ('IMPLEMENTATION_P14_P15.md', 'android-p14-p15-decision.json')]
    files += sorted((DIRECTORY / 'plantuml').glob('*')) + sorted((DIRECTORY / 'svg').glob('*.svg'))
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as bundle:
        for file in files:
            bundle.write(file, file.relative_to(DIRECTORY))
    print(f'Rendered {len(diagrams)} diagrams; archive {archive.stat().st_size} bytes')


if __name__ == '__main__':
    main()
