# Livraison P8 — import local et OpenSubtitles

27 octobre 2026. **Implémentation et tests locaux réalisés. Validation OpenSubtitles authentifiée réelle en attente.** Cette livraison prolonge [P6–P7](IMPLEMENTATION_P6_P7.md). Elle n’ajoute ni N_m3u8DL-RE ni synchronisation automatique de la dérive des sous-titres.

## Parcours utilisateur

1. Dans **Téléchargements**, choisir une vidéo locale terminée, échouée ou en pause, puis **Pistes et format → Ajouter des sous-titres**. Attendre l’arrêt réel du traitement si la tâche travaille encore.
2. **Import local :** sélectionner un SRT, VTT, ASS/SSA, ZIP ou GZIP. Une archive contenant plusieurs sous-titres exige un choix explicite de fichier. L’aperçu affiche le texte, le nombre de répliques, leur intervalle et la numérotation détectée dans le nom.
3. **OpenSubtitles :** configurer la clé de l’application, et facultativement un compte OpenSubtitles.com. Rechercher par titre, identifiants IMDb/TMDB, saison/épisode ou numéro absolu. Les identifiants d’une série sont distincts de ceux d’un épisode précis ou d’un film. Le titre n’est pas ajouté au filtre lorsqu’un identifiant est renseigné.
4. Lire langue, release, FPS, indication malentendants/forcé et critères de correspondance. Un écart ou une métadonnée absente est signalé ; aucun résultat n’est automatiquement attaché.
5. **Télécharger et prévisualiser** récupère le fichier : la création du lien peut consommer le quota OpenSubtitles, même sans attacher ensuite le sous-titre. Le quota retourné par le fournisseur est affiché ; aucune allocation journalière fixe n’est supposée.
6. Choisir langue/nom de piste et cocher la confirmation de correspondance avec la vidéo. **Ajouter cette piste** ne change pas encore la vidéo : sélectionner ensuite MKV, SIDECAR ou MP4 hardsub, son décalage et ses dispositions, puis **Produire le fichier**.

Le fichier ajouté rejoint le même inventaire et les mêmes traitements que les pistes des extensions. L’ajout conserve les sélections déjà présentes dans le panneau. En hardsub, la nouvelle piste remplace la sélection de sous-titre unique. Un aperçu n’est jamais exécuté comme HTML.

Les erreurs de fournisseur restent dans ce parcours : elles ne font pas échouer une vidéo déjà téléchargée. Une session OpenSubtitles expirée ne doit pas déconnecter la session AnimeLab du serveur partagé ; l’API locale distingue ces deux authentifications.

## Identité et correspondance

`SubtitleQuery` distingue `series`, `episode` et `movie`. Les identifiants de série utilisent les paramètres `parent_imdb_id` et `parent_tmdb_id` ; ceux d’un épisode précis ou d’un film utilisent `imdb_id` et `tmdb_id`. Un identifiant d’épisode précis se recherche sans filtre saison/épisode supplémentaire.

Le numéro absolu est une demande explicite utilisant le numéro d’épisode du fournisseur, avec avertissement : sa numérotation peut différer de celle de la source AnimeLab. Aucune conversion absolu ↔ saison/épisode n’est inventée. IMDb accepte le préfixe `tt` et retire les zéros initiaux avant requête. Les IDs sont renseignés par l’utilisateur ; leur identification automatique depuis TMDB n’est pas ajoutée dans ce lot.

Les résultats exposent des critères `match`, `mismatch` ou `unknown` pour chaque identifiant et numéro demandé, plutôt qu’un score de confiance arbitraire. Les releases/FPS sont affichées ; ils ne constituent pas une preuve de synchronisation. Les résultats traduits automatiquement sont exclus par défaut.

## API et composants

Routes sous `/api/download` :

```text
GET    /subtitle-provider
PUT    /subtitle-provider
DELETE /subtitle-provider
GET    /{task_id}/subtitles/context
POST   /{task_id}/subtitles/import?filename=episode.srt&encoding=auto
POST   /{task_id}/subtitles/search
POST   /{task_id}/subtitles/provider-preview
POST   /{task_id}/subtitles/attach
```

L’import est un corps binaire `application/octet-stream`, sans dépendance multipart supplémentaire. Le client fournit un nom de fichier, jamais un chemin d’installation. L’attachement utilise les identifiants d’import et d’entrée renvoyés par le serveur, une langue, un label et `confirmedEpisode=true`.

- `SubtitleProvider` définit le contrat ; `OpenSubtitlesProvider` implémente REST v1.
- `SubtitleVault` conserve éventuellement les identifiants chiffrés ; aucune clé n’est créée automatiquement à côté de la base.
- `subtitle_imports` valide contenu, encodage et archives sans extraction suivant les chemins de l’archive.
- `DownloadSubtitles` gère import, recherche, aperçu et attachement au niveau de la tâche. Il ne crée pas un nouveau moteur de téléchargement.
- `OutputProcessor` accepte les pistes locales par chemin privé et empreinte, puis réutilise P6–P7. Une révision des sous-titres invalide l’ancien reçu de finalisation pour éviter d’adopter une sortie antérieure à l’import.

Une migration SQLite additive **11** crée `subtitle_provider_secret`. Les imports et pistes locales sont stockés dans les métadonnées privées de la tâche ; le registre `subtitle_asset` conserve leur empreinte et leur provenance. Les imports survivent à un retéléchargement forcé de la vidéo ; la suppression de la tâche nettoie aussi ses imports. Une sauvegarde SQLite peut contenir les identifiants sous forme chiffrée, mais ne contient pas la clé externe.

## Réseau et quotas

Le client API utilise HTTPX, un User-Agent AnimeLab, `Api-Key` et, lorsque disponible, le jeton utilisateur. Il ne réutilise ni les cookies des sources vidéo ni leur émulation navigateur. Les proxys implicites de l’environnement ne sont pas hérités.

L’API est limitée aux hôtes HTTPS exacts `api.opensubtitles.com` et `vip-api.opensubtitles.com`. L’hôte VIP retourné au login est contrôlé. Les fichiers sont acceptés uniquement sous `/download/` sur `www.opensubtitles.com` ou `dl.opensubtitles.com`, selon le contrat actuellement documenté. Chaque redirection est contrôlée avant requête ; les clés et jetons ne sont jamais transmis aux hôtes de fichiers. Aucun appel n’accepte une URL de téléchargement fournie par le navigateur utilisateur. Un nouveau domaine CDN nécessite une évolution explicite de cette politique.

Les requêtes sont sérialisées et espacées d’au moins une seconde par moteur utilisateur. HTTP 429 respecte `Retry-After` ; 401 invalide la session, avec un seul renouvellement lorsque des identifiants valides sont disponibles ; un login refusé ne boucle pas. Les autres erreurs ne déclenchent pas de repli vers le scraping.

Les liens signés restent en mémoire pendant la récupération immédiate ; ils ne sont ni renvoyés au frontend ni sauvegardés dans la tâche. Un lien expiré exige une nouvelle demande explicite d’aperçu, avec avertissement de quota. Réouvrir un aperçu déjà récupéré utilise sa copie locale sans nouvelle demande facturée. La recherche est bornée à 100 résultats retournés, avec pagination ; les références de résultat expirent après quinze minutes et sont liées à une tâche.

## Stockage des secrets

Par défaut, API key, mot de passe et jeton restent uniquement en mémoire dans le moteur privé du compte. Ils ne sont pas stockés dans `localStorage`, dans les réponses API ou dans les métadonnées des téléchargements. Le jeton est toujours éphémère, même si les identifiants sont mémorisés.

Pour activer **Mémoriser les identifiants chiffrés**, l’opérateur doit provisionner une clé Fernet externe via `ANIMELAB_SUBTITLE_KEY_FILE`. Le chemin doit être absolu, hors du dossier de la base, du cache et des téléchargements. Sous POSIX, le fichier doit être privé (`0600` ou plus restrictif). Aucun fichier de clé n’est généré par l’application en cas d’absence.

Exemple de provisionnement Linux, à exécuter depuis le dépôt par l’opérateur qui lance AnimeLab, uniquement si cette mémorisation est souhaitée :

```bash
uv run --locked python - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
import os
os.umask(0o077)
folder = Path.home() / '.config' / 'animelab-secrets'
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
with (folder / 'opensubtitles.key').open('xb') as output:
    output.write(Fernet.generate_key())
PY
export ANIMELAB_SUBTITLE_KEY_FILE="$HOME/.config/animelab-secrets/opensubtitles.key"
# Redémarrer AnimeLab avec cet environnement, puis cocher la mémorisation.
```

La commande refuse d’écraser une clé existante. Avec Docker, monter ce fichier séparément et en lecture seule ; ne pas le ranger dans une sauvegarde de la base. Sous Windows, les ACL du fichier doivent également être restreintes par l’opérateur ; aucun contrôle d’ACL Windows n’est revendiqué ici.

Chaque worker partagé dispose de sa base, de son espace d’import et de ses sessions. Seul le chemin de la clé externe peut être transmis par l’opérateur ; les identifiants personnels d’un autre compte ne sont pas hérités. Le contenu chiffré est lié au chemin de sa base pour refuser une copie vers un autre espace utilisateur. Déplacer la base ou perdre/changer la clé nécessite une reconnexion. Ce mécanisme protège les copies de données au repos, pas un hôte compromis ni un administrateur contrôlant les processus.

## Limites d’import et protections

- 10 Mo maximum pour le fichier reçu ; ZIP/GZIP seulement pour les archives, pas RAR/7z.
- ZIP : 100 entrées maximum, 10 Mo par fichier, 30 Mo décompressés au total et ratio de compression borné.
- Rejet des chemins absolus, traversées `..`, liens symboliques, fichiers spéciaux, entrées dupliquées, archives chiffrées et méthodes ZIP non admises.
- Les noms de sortie sont des identifiants générés ; aucun `extractall` n’est utilisé.
- Détection UTF-8/UTF-16 ; Windows-1252 et ISO-8859-1 sur choix explicite. Les textes sont normalisés en UTF-8 sans modifier les temps ou styles ASS lors de l’import.
- Aperçu limité à 6 000 caractères, au plus 100 000 répliques et durées bornées. Les formats invalides/HTML sont refusés.
- Au plus dix imports par tâche. Les aperçus non attachés de plus de 24 heures sont nettoyés lors d’un nouvel import. Les fichiers attachés ne sont pas supprimés par cette expiration.
- Le parsing est borné à deux opérations simultanées par moteur. Les mutations empêchent une reprise/suppression concurrente ; une annulation HTTP attend l’arrêt réel de l’opération disque avant de libérer sa réservation.
- La passerelle conserve sa limite générale de 2 Mio ; seule la route d’import binaire accepte jusqu’à 10 Mio. Les écritures restent soumises à la permission `download`.

## Validation

Les tests utilisent des fichiers synthétiques et un transport HTTP simulé pour le fournisseur. Aucun identifiant réel n’a été cherché dans le navigateur ou les fichiers personnels.

- Contrat OpenSubtitles : API key/User-Agent, login VIP, absence de secrets sur CDN, renouvellement de session, login refusé sans répétition, quotas 403/406/429, indisponibilité, lien expiré et redirections hostiles.
- Import : ZIP/GZIP, fichiers malformés, traversées, liens, tailles/nombre d’entrées, encodages, aperçu et sélection d’un épisode différent.
- Isolation : références de résultat/import liées à une tâche ; chiffrement, clé manquante/rotative et copie vers une autre base refusée ; permission sur serveur partagé.
- Intégration : import puis vrai MKV/MP4 FFmpeg ; décalage, métadonnées et reçu invalidé ; conservation des imports après retéléchargement forcé ; verrou maintenu pendant une annulation disque ; aperçu non exécuté comme HTML.
- Interface à 360 et 1280 px : import d’archive, choix explicite, confirmation obligatoire, configuration sans stockage navigateur de secrets, recherche et aperçu manuel.

Commandes : `uv run --locked python scripts/check.py python`, `uv run --locked python scripts/check.py quality`, puis dans `frontend`, `npm test`, `npm run build` et `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome npm run test:ui -- --workers=2`.

| Contrôle | Résultat |
| --- | --- |
| Tests dédiés `tests/test_subtitles_p8.py` | 31 réussis |
| Suite Python isolée | 842 réussis, 2 ignorés |
| Suite navigateur complète | 83 réussis |
| Tests Node frontend | 37 réussis |
| Build frontend | Réussi ; avertissement Vite connu sur la taille d’un chunk |
| Ruff, mypy configuré, ESLint, Prettier, TypeScript | Contrôlés localement |

La première suite complète a également révélé une course préexistante entre fin de vérification et fermeture de Chromium. Le résultat est maintenant publié avant d’attendre la fermeture du navigateur ; un test à fermeture volontairement lente couvre cette fenêtre.

**Validation fournisseur réelle en attente :** sans clé API et compte de test explicitement configurés, aucune recherche/téléchargement authentifié réel n’est revendiqué. Les essais Windows/macOS et Android sur appareil restent distincts de ces validations Linux. Le sélecteur de fichiers Android existant est raccordé aux champs fichier WebView ; aucun APK n’a été construit/signé/envoyé dans ce lot. Le hardsub Android reste désactivé jusqu’à P14.

**Suite : P9**, avec maintien de la réserve sur la validation réelle du fournisseur P8. SubDL, `ffsubsync`/`alass` et correction de dérive ne sont pas livrés ici.

## Références officielles vérifiées le 27 octobre 2026

- [OpenSubtitles REST v1 : paramètres, authentification, quotas et liens temporaires](https://ai.opensubtitles.com/api-docs).
- [Guide API officiel : enregistrement du consommateur et User-Agent](https://opensubtitles.tawk.help/article/getting-started).
- [Portail des consommateurs OpenSubtitles](https://www.opensubtitles.com/en/consumers) : la création/configuration d’une application et l’acceptation de ses conditions restent à faire par son propriétaire ; aucune application n’a été enregistrée automatiquement.

Le parcours utilise l’API officielle ; il n’automatise pas de contournement de quota et ne publie pas de clé API dans le dépôt.
