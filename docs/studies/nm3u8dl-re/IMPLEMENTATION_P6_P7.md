# Livraison P6–P7 — sorties multipistes et MP4 hardsub

27 octobre 2026. **Implémenté et validé localement sur Linux.** Cette livraison prolonge [P1–P5](IMPLEMENTATION_P1_P5.md), sans ajouter N_m3u8DL-RE ni remplacer les extracteurs. Les fournisseurs externes et l’import manuel appartiennent à P8.

## Utilisation

1. Sur une fiche animé, choisir le format de sortie avant de lancer le téléchargement. Les profils explicites utilisent le nouveau traitement ; les anciennes tâches conservent leur politique historique.
2. Dans **Téléchargements**, ouvrir l’onglet **Terminés**, **Erreurs** ou **Tous**, puis **Pistes et format** pour une tâche locale terminée, échouée ou en pause.
3. Choisir les pistes, le décalage en secondes, défaut/forcé et le format. Un décalage positif retarde la piste ; un décalage négatif l’avance. Les événements de sous-titres entièrement antérieurs à zéro sont retirés ; ceux qui chevauchent zéro sont raccourcis.
4. Cliquer sur **Produire le fichier**. Le gestionnaire remet la tâche dans sa file avec le master local ; il ne résout ni ne télécharge à nouveau la vidéo. Les pistes externes non encore mises en cache nécessitent toutefois le réseau.

Le profil et les identifiants des sélections sont persistants. Modifier les préférences globales ne modifie pas une tâche existante.

## Sorties livrées

| Profil | Résultat | Sélection et limites |
| --- | --- | --- |
| `ORIGINAL` | Vidéo selon le transfert existant | Aucun traitement de pistes demandé ; profil conservé pour la compatibilité |
| `MKV_SOFT` | Une vidéo, les audios et sous-titres sélectionnés, les polices jointes | Vidéo/audio copiés sans réencodage ; langues, titres, défaut/forcé vérifiés. ASS préservé. WebVTT converti en SRT avec avertissement sur le style |
| `SIDECAR` | Copie vidéo/audio inchangée et fichiers texte séparés | SRT/VTT/ASS, offsets, polices jointes et fichier de provenance JSON. La sélection audio n’est pas applicable à ce mode |
| `MP4_HARD` | MP4 H.264, un audio AAC, un sous-titre rendu dans les pixels | Réencodage complet via libass/libx264 ; copie AAC ou conversion audio. Aucune piste de sous-titres ou police jointe dans le MP4 final |

Sans sélection avancée, le MKV utilise les pistes non automatiques ; le hardsub choisit une piste par défaut par type, ou la première disponible. Les sous-titres automatiques nécessitent un choix explicite. Une sélection requise absente échoue avec explication : elle n’est pas supprimée silencieusement. Une seule piste par type peut être marquée par défaut.

Pour le hardsub, les sous-titres bitmap sont refusés explicitement. Les formats texte externes attendus sont UTF-8. Les styles ASS compatibles et polices attachées sont transmis à libass. Sans police attachée, l’interface signale que le rendu utilise les polices de l’ordinateur. Les pistes vides ou entièrement hors de la durée vidéo ne produisent pas un faux succès d’incrustation.

L’interface affiche la progression FFmpeg en secondes, et le pourcentage du réencodage quand la durée est connue. Une pause/annulation interrompt le traitement supervisé. **La conversion reprend depuis le début**, à partir des fichiers locaux ; aucune reprise au milieu de l’encodage n’est annoncée.

## Architecture et sécurité

- `OutputProcessor` unifie l’inventaire FFprobe et les pistes externes des sources. `subtitle_timing` applique les offsets sans retirer les styles ASS.
- Les ressources réseau passent par le client `SourceHTTPService` existant : sessions, vérification interactive, contrôle des URL/redirections, limitation de débit et créneaux de l’ordonnanceur. Pas de second orchestrateur.
- Les pistes externes HLS/DASH segmentées sont refusées dans ce lot ; leur support relève de P10–P12. Les fichiers audio directs sont pris en charge.
- Le traitement FFmpeg reçoit uniquement des fichiers locaux. Chaque entrée est limitée aux protocoles `file,pipe`, y compris FFprobe ; un manifeste déguisé en fichier audio/vidéo est refusé.
- Les champs de sélection acceptent des identifiants d’inventaire, jamais des chemins ni des filtres FFmpeg fournis par l’utilisateur. L’inventaire public ne contient ni URL ni chemin de ressource.
- Les routes `/api/download/...` conservent la permission `download` et l’isolation par moteur/compte de la passerelle partagée.
- La concurrence CPU utilise le budget média existant ; la collecte des pistes partage les créneaux réseau des téléchargements. L’inventaire interactif est borné à deux opérations.

## Master, publication et récupération

Un dossier privé `.animelab-media-<identité de tâche>` est créé à côté de la source, dans le dossier de téléchargements autorisé. Il contient une copie indépendante du master, les pistes récupérées et les reçus de finalisation. Les empreintes SHA-256 sont vérifiées avant réutilisation.

**Coût disque :** le master privé est conservé même si « Conserver les fichiers sources visibles » est décoché. Cette option retire uniquement le fichier source visible, après publication valide. Les anciennes sorties restent disponibles lorsqu’on change de format. Supprimer la tâche nettoie son espace privé, en attendant la fin d’un worker réseau actif ; la suppression pendant une étape média ou un export est refusée jusqu’à l’arrêt réel ; les sorties publiées restent présentes. Un retéléchargement forcé invalide l’ancien master et ses reçus, pour ne pas restaurer la vidéo précédente par erreur.

La génération se fait dans un répertoire temporaire propre à la tâche. Pour MKV/MP4, FFprobe vérifie pistes, langues, dispositions, polices, codecs et durée, puis FFmpeg décode un échantillon des deux premières secondes. Cette vérification n’est pas une analyse exhaustive de chaque frame. SIDECAR conserve les octets de la vidéo source et vérifie le format des textes.

La publication réutilise le mécanisme atomique existant, sans écraser une destination occupée ; un suffixe lié à la tâche résout la collision. Pour SIDECAR, le lot contient vidéo, textes, polices et provenance. Une erreur pendant la publication retire les nouveaux fichiers du lot, puis conserve master et ressources pour relance. L’ensemble de plusieurs fichiers n’est pas une transaction atomique du système de fichiers : une coupure brutale peut laisser un fichier déjà publié ; une relance ne l’écrase pas.

Un reçu privé contient profil, chemins de sortie et empreintes. Après redémarrage, une finalisation complète et intacte peut être adoptée sans la répéter. Un fichier final modifié n’est pas adopté ; une relance repart du master conservé. Les fichiers de travail et le master ne sont pas exportés vers Android : seuls la sortie et ses annexes le sont. Le lecteur ne présente comme sous-titres que les annexes textuelles, avec leur langue et leur label.

## API

```text
GET  /api/download/output-profiles
GET  /api/download/media-capabilities
GET  /api/download/{task_id}/media-inventory
POST /api/download/{task_id}/output
```

L’inventaire expose pistes, durée, profil enregistré, capacités et avertissements. Un téléchargement actif doit d’abord être mis en pause. L’envoi suivant remet une tâche existante dans la file de finalisation ; remplacer les identifiants par ceux renvoyés par son inventaire :

```json
{
  "version": 1,
  "mode": "MP4_HARD",
  "keepOriginals": true,
  "burnTrackId": "embedded:subtitle:3",
  "selections": [
    {"trackId": "embedded:audio:1", "default": true, "offsetSeconds": 0},
    {"trackId": "embedded:subtitle:3", "offsetSeconds": 0.5}
  ]
}
```

Une vidéo unique est conservée implicitement si elle n’est pas sélectionnée. Pour MKV, sélectionner plusieurs audios/sous-titres dans `selections`. Pour SIDECAR, sélectionner uniquement les sous-titres ; son audio source reste inchangé. Le champ historique `strict` ne permet pas de contourner les contrôles : tout profil explicite est strict.

Aucune migration SQL supplémentaire n’est nécessaire au-delà de P3 : `outputProfileJson` conserve les choix et `mediaJson.outputState` conserve état, cache, provenance et artefacts. Le registre média existant conserve les sélections et les sorties terminées.

## Preuves locales

Environnement : Linux, Python 3.13.16, FFmpeg/FFprobe 8.0.1 système. Les médias sont synthétiques, produits hors de la bibliothèque personnelle, sans téléchargement de vidéo externe.

| Contrôle | Résultat |
| --- | --- |
| `uv run --locked python scripts/check.py python` | **810 réussis, 2 ignorés** |
| `tests/test_output_profiles_p6_p7.py`, inclus dans la suite complète | **22 réussis** ; fichiers réels, dont collecte audio via transport HTTP simulé |
| `uv run --locked python scripts/check.py quality` | Ruff, mypy sur le périmètre configuré, ESLint, Prettier et TypeScript réussis |
| `cd frontend && npm test` | **37 réussis** |
| `cd frontend && npm run build` | Réussi ; avertissement Vite préexistant sur un chunk de plus de 500 Ko |
| `cd frontend && PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome npm run test:ui -- --workers=2` | **79 réussis** ; dont sélection de pistes/décalages à 360 et 1280 px |

Les 22 tests ajoutés couvrent notamment : deux audios/deux sous-titres et métadonnées ; conservation ASS ; offsets positifs/négatifs et CRLF ; encodage H.264/AAC et comparaison de frames avant/après texte ; audio PCM converti ; polices attachées transmises au MKV puis au hardsub ; refus bitmap ; piste absente ; espace insuffisant ; annulation et relance locale ; panne de publication ; collision ; export Android des annexes ; reçu corrompu et retéléchargement forcé ; suppression et arrêt d’un worker sans réapparition de la tâche ; partage des créneaux réseau ; manifeste déguisé.

## Limites et passage au lot suivant

- MKV/SIDECAR : pris en charge selon les outils réellement disponibles. L’adaptateur JNI Android et les chemins d’export sont raccordés ; ces nouveaux traitements n’ont pas été exécutés dans un APK sur téléphone dans ce lot.
- Hardsub : activé sur desktop/serveur si FFprobe, filtre `subtitles`, encodeur `libx264` et AAC sont détectés. **Désactivé sur Android**, conformément à P14.
- Les essais réels Windows/macOS restent à effectuer ; les tests Linux ne prouvent pas leurs codecs et polices installés.
- Pas d’accélération matérielle automatique : profil logiciel reproductible. Aucun fournisseur de sous-titres, OCR ou synchronisation de dérive livré ici.
- Aucun binaire N_m3u8DL-RE distribué ou exécuté. Aucun APK construit/signé/envoyé et aucune release publiée dans ce lot.

**Prochain lot : P8 — import local et premier fournisseur externe.**
