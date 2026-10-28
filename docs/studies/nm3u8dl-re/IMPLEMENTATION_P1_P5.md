# P1–P5 — contrats, pistes, profils et supervision

Livraison locale du 27 octobre 2026, suivant [l’ordre de réalisation](PRIORITES_IMPLEMENTATION.md). Les changements du moteur sont implémentés ; les limites et les validations par plateforme figurent ci-dessous. Aucun backend N_m3u8DL-RE ni nouveau traitement hardsub n’est activé dans ces lots.

## Ce qui est raccordé

| Lot | Livraison | Points d’entrée |
| --- | --- | --- |
| P1 | Ressources et pistes typées, capacités, événements et résultats ; cas de référence hors ligne | `media_contracts.py`, fixtures et tests de contrats |
| P2 | Pistes manuelles/automatiques et audio de yt-dlp, métadonnées des recettes JSON et des sources importées, en-têtes privés, propagation jusqu’à la tâche | `merge_stream_metadata`, `ExtractorResult`, `RecipeRuntime.stream`, résolution importée et inventaire public |
| P3 | Profils versionnés enregistrés par tâche ; migration additive 10 ; inventaire et journal privés ; API et sélecteur de format sur la fiche | `output_profiles.py`, `media_state.py`, `migrations.py`, `OutputProfilePicker.vue` |
| P4 | Registre de résolution ; adaptateurs des trois transferts existants ; sélection selon les capacités ; journal des tentatives | `source_resolvers.py`, `transfer_backends.py`, `TransferWorker` |
| P5 | Progression FFmpeg, délais, interruption, diagnostics bornés, arrêt des groupes desktop, pont JNI supervisé et détection des filtres/encodeurs | `media_execution.py`, `media_tools.py`, `MediaPipeline._run_media`, `MediaBridge.kt` |

Les modules cités sont dans `animelab/services/`, sauf le modèle `animelab/models/media_state.py`, les migrations `animelab/migrations.py`, le composant `frontend/src/components/OutputProfilePicker.vue` et le pont `android/app/src/main/java/com/animan/app/MediaBridge.kt`.

L’ordonnanceur, les budgets réseau/média/export et les points d’entrée de compatibilité restent en place. Le registre remplace les branches de résolution du worker ; les méthodes HTTP Range, HLS et myTV existantes continuent d’effectuer les transferts. Le refactoring ne remplace pas les recettes par une exécution universelle d’APK.

## Comportement utilisateur et API

- La fiche d’une série propose un format de sortie pour un épisode ou un lot. Le choix par défaut garde le comportement de la case « Sous-titres ».
- `ORIGINAL` et le chemin MKV existant sont proposés. `SIDECAR`, `MP4_HARD`, la sélection individuelle des pistes et les offsets sont décrits par le contrat mais refusés à la création : leurs traitements relèvent des lots P6/P7.
- Un profil explicitement choisi est strict : pas de succès MP4 annoncé comme MKV si les pistes nécessaires manquent. Les fichiers récupérés sont conservés. Les anciens profils implicites conservent leur politique historique.
- Les sous-titres automatiques sont identifiés dans l’inventaire, sans téléchargement implicite. Les pistes de même langue mais de rôle différent ne sont pas fusionnées.
- Les formats vidéo seule nécessitant un assemblage audio séparé et les manifestes HLS hors capacités sont refusés explicitement. Le moteur n’annonce pas un téléchargement complet en ignorant ces besoins.
- Les phases d’assemblage/fusion exposent des secondes de média traitées, séparément des octets reçus. Le transfert, la phase média et l’export Android gardent leurs états distincts.

API ajoutées :

```text
GET /api/download/output-profiles
GET /api/download/media-capabilities
POST /api/download          + outputProfile facultatif
POST /api/download/batch    + outputProfile facultatif par épisode
```

Exemple de choix explicite disponible :

```json
{
  "version": 1,
  "mode": "MKV_SOFT",
  "keepOriginals": true
}
```

Ce choix utilise le multiplexage existant ; il ne signifie pas encore que toutes les sélections multipistes prévues en P6 sont disponibles. Une source sans sous-titres utilisables provoque un message explicite pour ce profil strict. Les profils non disponibles et les sélections avancées sont refusés avant ajout à la file.

`GET /api/download/status` et les événements de tâche exposent `outputProfile`, `mediaTracks` et `mediaProgressSeconds`. L’inventaire public contient identifiant, langue, rôle, label et provenance automatique ; il ne contient ni en-têtes d’authentification ni URL de piste. Les API de téléchargement restent soumises à la permission correspondante en serveur partagé.

## Données et récupération

La migration 10 ajoute `mediaJson`, `outputProfileJson` et les tables `media_track`, `task_track_selection`, `subtitle_asset`, `transfer_attempt`, `output_artifact`, dans la base privée existante de chaque compte.

Avant de mettre à niveau une bibliothèque existante, une sauvegarde SQLite incluant le WAL est créée, vérifiée puis publiée sous :

```text
<base>.before-media-v10.<identifiant>.sqlite3
```

La migration est transactionnelle et répétable. Elle ne réécrit pas les fichiers média, les anciens champs de sous-titres ou le statut des tâches terminées. Les profils historiques sont dérivés au chargement et enregistrés à la prochaine sauvegarde normale. Des sauvegardes déjà publiées ne sont pas écrasées.

En cas de problème après mise à niveau : arrêter les processus utilisant cette bibliothèque, conserver une copie de la base courante et de ses journaux, puis restaurer une copie de la sauvegarde avec une version compatible. Ne pas remplacer une base ouverte et ne pas tenter un downgrade destructif du schéma. La sauvegarde contient les données d’avant migration ; les tâches créées ensuite ne s’y trouvent pas.

Les sessions sont conservées par le transport existant. Les en-têtes runtime sont reconstitués à la résolution ; les copies persistées excluent les en-têtes sensibles. Les clés/session ne sont pas incorporées au profil. Une tentative mémorise backend, version, identité de ressource et checkpoint ; les fragments existants conservent leurs contrôles de représentation. Une reprise avec un backend différent est refusée sans réinitialisation explicite.

## Reproduire les validations

Depuis la racine du dépôt :

```bash
uv run --locked python -m pytest tests/test_media_contracts.py tests/test_media_pipeline_p1_p5.py tests/test_subtitle_pipeline.py tests/test_download_stages.py tests/test_download_robustness.py tests/test_transfer_fault_contracts.py tests/test_versioned_database.py tests/test_android_platform.py -q
uv run --locked python scripts/check.py quality
uv run --locked python scripts/check.py frontend
uv run --locked python scripts/check.py python
# Cas MP4/MKV synthétiques, dans un dossier de travail neuf :
uv run --locked python scripts/media_pipeline_fixtures.py /tmp/animelab-media-reference
```

Les manifestes de `tests/fixtures/media_pipeline/` décrivent les capacités acceptées/refusées ; ils ne constituent pas tous des médias autonomes lisibles. Le générateur produit les petits MP4/MKV réels nécessaires aux inventaires FFprobe. Les tests de transfert existants couvrent HTTP Range et les pannes/reprises de segments sans site distant.

Depuis `frontend/`, avec Chromium Playwright installé ou un Chrome local explicitement choisi :

```bash
npm run test:ui
# Exemple pour la machine de développement Linux :
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome npm run test:ui
```

Depuis `android/`, avec un JDK compatible Gradle/Android et les dépendances déjà présentes :

```bash
./gradlew --offline :app:compileDebugKotlin
```

## Limites de validation

Résultats locaux de cette livraison :

| Contrôle | Résultat |
| --- | --- |
| Suite Python isolée, Python 3.13 | 788 réussis, 2 ignorés |
| Tests frontend Node | 37 réussis |
| Parcours navigateur avec Chrome local | 77 réussis, dont profils à 360/1280 px |
| Ruff, mypy (7 modules), ESLint, Prettier, Vue/TypeScript | Réussis |
| Build frontend de production | Réussi |
| Compilation `:app:compileDebugKotlin`, JDK 21, hors ligne | Réussie |
| Sous-ensemble supervision destiné à la CI Windows, exécuté sur Linux | 4 réussis ; exécution Windows encore à faire |
| Dossier UML | 9 SVG et 19 références de code vérifiés |

La première tentative de compilation avec le JDK 25 système a échoué avant compilation ; le JDK 21 compatible a été utilisé pour la validation. La suite navigateur a été relancée avec Chrome déjà installé, car le navigateur attendu dans le cache Playwright n’était pas disponible. Aucun téléchargement de navigateur n’a été nécessaire.

Les tests Python, les médias synthétiques et les essais navigateur sont exécutés localement sur Linux. La compilation Kotlin vérifie le raccordement au SDK FFmpegKit ; un faux pont teste le protocole JNI de progression et d’annulation. Cela ne remplace pas un essai sur téléphone Android.

L’arrêt POSIX est testé avec un vrai processus enfant. Le chemin Windows associe les sous-processus à un Job Object avec arrêt des descendants, en complément du groupe dédié ; les essais réels Windows/macOS et Android restent à réaliser sur leurs environnements. Aucun APK n’est signé ou transféré dans cette livraison. Les capacités FFmpeg sont sondées sur l’installation effective et peuvent différer selon la plateforme.

**Prochain lot : P6**, pour la sélection multipiste, les dispositions, les polices et les sorties annexes complètes.
