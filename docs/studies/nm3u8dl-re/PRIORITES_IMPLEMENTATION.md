# Sous-titres et moteur de téléchargement — ordre d’implémentation

**Date : 27 octobre 2026. Statut : P1–P9 implémentés localement ; validations fournisseurs réelles P8/P9 en attente ; P10–P12 évalués sous Linux x64, décision de non-adoption ; P13/P15 non retenus pour cette version ; P14 implémenté localement, validation Android en attente.** Voir les comptes rendus [P1–P5](IMPLEMENTATION_P1_P5.md), [P6–P7](IMPLEMENTATION_P6_P7.md), [P8](IMPLEMENTATION_P8.md), [P9](IMPLEMENTATION_P9.md), [P10–P13](IMPLEMENTATION_P10_P13.md) et [P14–P15](IMPLEMENTATION_P14_P15.md), les preuves et les limites de validation par plateforme.

Référence : [rapport de faisabilité](README.md), [diagrammes UML/Merise](index.html). Le rapport analyse la révision `1cea1983ec741c502cf5241d3b5ebdfacb38330a` ; les points de raccordement seront revérifiés au début de chaque lot.

## Règles de progression

- **P1 à P15 constituent l’ordre de travail**, et non des niveaux de gravité. Terminer et valider un lot avant le suivant ; ne pas confondre une interface créée avec une fonctionnalité intégrée.
- Chaque lot livre code, migrations éventuelles, tests pertinents, documentation et résultat de validation. Une petite PR par lot est préférable ; un lot trop volumineux peut être subdivisé sans changer l’ordre.
- P1–P9 livrent le socle et les nouveaux usages sans dépendre de N_m3u8DL-RE. P10–P13 évaluent puis distribuent ce backend **si les critères sont satisfaits**. P14 et P15 traitent Android séparément.
- Une décision négative sur N_m3u8DL-RE clôt explicitement les lots dépendants comme « non retenus », sans bloquer les améliorations indépendantes, dont P14. Un échec technique non résolu n’est pas une validation.
- Conserver l’ordonnanceur existant et la distinction entre état du téléchargement, phase de traitement et état d’export Android. Éviter un deuxième orchestrateur concurrent.
- Aucun repli ne doit supprimer silencieusement un audio ou un sous-titre sélectionné. Distinguer absence réelle, récupération impossible et fonction non prise en charge.
- L’isolation des comptes, les permissions et la politique réseau restent applicables à toutes les ressources et à tous les backends.
- Builds, signature et publication des APK de release passent par **GitHub Actions**. Ne pas envoyer de binaire APK local vers GitHub. La publication d’une release reste une étape explicite.

## Vue d’ensemble

| Ordre | Livraison principale | Dépendances techniques principales | Plateformes |
| --- | --- | --- | --- |
| P1 | Contrats et cas de référence | Code actuel | Toutes |
| P2 | Conservation des pistes des sources | P1 | Toutes |
| P3 | Profils et persistance compatibles | P2 | Toutes |
| P4 | Transferts existants derrière une interface | P1–P3 | Toutes |
| P5 | Exécution média supervisée | P3–P4 | Desktop/serveur ; contrat Android |
| P6 | MKV multipiste et fichiers annexes | P2–P5 | Toutes selon capacités |
| P7 | MP4 hardsub | P5–P6 | Desktop/serveur d’abord |
| P8 | Premier fournisseur externe et import local | P2–P7 | Toutes selon accès réseau |
| P9 | Deuxième fournisseur et synchronisation | P8 | Toutes ; synchronisation desktop/serveur d’abord |
| P10 | Preuve N_m3u8DL-RE hors ligne | P4–P5 et socle validé | Desktop/serveur |
| P11 | Relais réseau et isolation du backend | P10 concluant | Desktop/serveur |
| P12 | Résilience et décision d’adoption | P10–P11 | Desktop/serveur |
| P13 | Distribution du backend retenu | P12 favorable | Windows/Linux/macOS/Docker |
| P14 | Hardsub Android | P3, P5–P7 ; décision P13 consignée | Android |
| P15 | Étude puis intégration N_m3u8DL-RE Android | P12 favorable, P14 évalué | Android, expérimental |

Les dépendances indiquent les raccordements nécessaires ; la réalisation suit néanmoins l’ordre numérique ci-dessus. Les dates et estimations de charge seront établies après P1, sans promesse de débit ni de réduction du code avant mesure.

## P1 — Fixer les contrats et les cas de référence

**But :** rendre la migration vérifiable sans changer le comportement utilisateur.

Travaux :

- Définir `ResolvedMedia`, `MediaTrack`, `DownloadBackend`, `TransferResult` et les capacités déclarées des backends. Distinguer piste vidéo, audio, texte et pièce jointe de police.
- Définir les événements de progression, arrêt, annulation, checkpoint et erreur ; distinguer octets réseau et progression d’encodage.
- Définir le résultat attendu lorsqu’une piste requise manque. Les sous-titres automatiques doivent être identifiés comme tels, sans sélection automatique implicite.
- Préparer des fixtures locales : MP4 direct, HTTP Range, HLS simple/AES-128, HLS audio séparé, fMP4/BYTERANGE, DASH, WebVTT segmenté, ASS et MKV incorporant des pistes.
- Relever les tests existants et les résultats de référence ; ne pas réécrire le moteur pendant ce lot.

**Validation :** contrats documentés, fixtures reproductibles hors ligne, tests de caractérisation du comportement actuel passants. Un format aujourd’hui refusé est enregistré comme tel, pas présenté comme pris en charge.

## P2 — Conserver les pistes de bout en bout

**But :** récupérer ce que les extensions et extracteurs fournissent déjà.

Travaux :

- Préserver sous-titres, pistes audio, en-têtes, langue, label, format et provenance dans les recettes prises en charge, extracteurs et repli yt-dlp.
- Corriger le chemin de résolution des flux directs ; conserver les URL relatives résolues et les en-têtes propres à chaque ressource.
- Conserver les associations entre représentations vidéo et audio des formats séparés. Ne pas fabriquer un flux autonome à partir d’une vidéo muette.
- Normaliser et dédupliquer sans fusionner deux pistes de même langue mais de rôle ou de version différents.
- Appliquer les contrôles réseau au moment des requêtes, y compris après redirection ; aucune promesse d’exécution universelle des APK Aniyomi.

**Validation :** une fixture de source traverse résolution, API, création de tâche et récupération sans perdre ses pistes ni ses métadonnées ; aucun accès croisé entre comptes.

## P3 — Ajouter les profils de sortie et leur persistance

**But :** mémoriser précisément le résultat demandé et préserver les anciennes tâches.

Travaux :

- Introduire des profils versionnés : `ORIGINAL` (comportement sans traitement demandé), `SIDECAR`, `MKV_SOFT`, `MP4_HARD`.
- Enregistrer dans chaque tâche une copie du profil et des sélections : audio, sous-titres, piste à incruster, offsets, défaut/forcé, conservation des originaux.
- Prévoir les entités du rapport : pistes, sélections, assets de sous-titres, tentatives de transfert et artefacts de sortie. Le fournisseur externe est facultatif.
- Séparer références de session, identité du média et URL temporaires. Ne pas dupliquer les secrets dans les tâches ou les réponses API.
- Migrer progressivement les anciens champs JSON avec sauvegarde et stratégie de récupération documentée. Préserver le comportement réel des préférences existantes, sans transformer indistinctement toutes les tâches terminées en MKV.
- Exposer les choix dans les API et l’interface ; désactiver les profils indisponibles avec une raison lisible.

**Validation :** anciennes tâches chargées et reprenables, tâches terminées intactes, migration répétable, sélections conservées après redémarrage et changement des préférences globales.

## P4 — Découpler les transferts existants

**But :** simplifier le moteur à partir du découpage déjà présent.

Travaux :

- Extraire un registre de résolveurs et un planificateur de transfert à partir du gestionnaire actuel.
- Placer HTTP Range, HLS natif et chunks myTV derrière le contrat de P1, en conservant temporairement les points d’entrée de compatibilité.
- Sélectionner selon les capacités réellement requises ; refuser explicitement les variantes non prises en charge.
- Conserver fichiers `.part`, métadonnées de reprise, budgets, permissions et gestion des vérifications de source.
- Ne pas entreprendre dans ce lot une réécriture complète du HLS. Les nouveaux cas complexes seront évalués en P10.

**Validation :** mêmes résultats, pause/reprise/annulation et reprise après redémarrage sur les chemins existants. Un changement de backend ne réutilise jamais aveuglément les fragments d’un autre.

## P5 — Superviser les traitements et détecter les capacités

**But :** rendre FFmpeg et les futurs outils pilotables et observables.

Travaux :

- Introduire une exécution supervisée : événements de progression, délais, arrêt, annulation, code de sortie et nettoyage limité à l’espace de travail de la tâche.
- Gérer les groupes de processus desktop/serveur ; définir un adaptateur distinct pour JNI Android, sans supposer que `subprocess` est utilisable partout.
- Détecter FFmpeg/FFprobe, filtres, encodeurs et capacités nécessaires. Limiter séparément la concurrence réseau et la concurrence de réencodage.
- Prévoir chemins avec espaces/Unicode, sélection sécurisée des arguments et masquage des secrets dans diagnostics et journaux.

**Validation :** progression réelle, interruption sans processus orphelin, erreur exploitable si un outil manque, et aucune suppression du master après échec. Reprise de la finalisation sans téléchargement réseau supplémentaire.

## P6 — Fiabiliser le MKV multipiste et le mode SIDECAR

**But :** livrer les premières sorties améliorées sans réencodage vidéo inutile.

Travaux :

- Unifier collecte des pistes externes et inventaire FFprobe des pistes incorporées.
- Produire le MKV avec les audios et sous-titres sélectionnés, leurs langues, titres et dispositions ; préserver ASS et polices disponibles.
- Produire les fichiers annexes avec noms déterministes, provenance et offsets appliqués sans écraser les originaux.
- Centraliser la publication atomique et la vérification ; conserver le master jusqu’à validation suivant le profil.
- Exposer clairement les pistes manquantes et les conversions de format susceptibles de perdre le style.

**Validation :** fixture avec une vidéo, deux audios et deux sous-titres ; vérification du contenu, langues, défaut/forcé, styles et absence de doublons. Tester collision, espace disque insuffisant, erreur de mux et export Android quand applicable.

## P7 — Livrer le MP4 avec sous-titres incrustés

**But :** produire un MP4 lisible avec le texte directement dans l’image.

Travaux :

- Sélectionner une vidéo, un audio et une piste de sous-titres à incruster ; sortie sans piste de sous-titres séparée.
- Proposer H.264/AAC comme profil de compatibilité, avec filtre libass et gestion des polices. Copier l’audio uniquement si compatible ; sinon le convertir.
- Appliquer le décalage choisi et préserver les styles compatibles. Identifier les sous-titres bitmap et les refuser explicitement tant qu’un chemin adapté n’est pas validé.
- Afficher le coût de réencodage, la progression et les conséquences de l’arrêt : ne pas promettre une reprise d’encodage au milieu du fichier.
- Conserver les pistes locales pour recommencer la finalisation ; l’accélération matérielle reste optionnelle et testée par capacité.

**Validation :** FFprobe confirme vidéo/audio attendus et zéro piste texte ; décodage et comparaison de frames prouvent l’incrustation. Tester accents, ASS, polices absentes, annulation et relance sans retéléchargement.

## P8 — Ajouter l’import local et un premier fournisseur externe

**But :** obtenir des sous-titres absents de la source vidéo.

Travaux :

- Définir `SubtitleProvider` et implémenter d’abord OpenSubtitles.com REST, après vérification de son contrat et de ses conditions au moment du développement.
- Ajouter recherche, sélection, aperçu, téléchargement et renouvellement d’URL ; afficher quotas et erreurs d’authentification sans faire échouer le transfert vidéo.
- Faire correspondre les identifiants IMDb/TMDB, saison/épisode ou numéro absolu ; afficher les critères de correspondance plutôt que sélectionner uniquement sur le titre.
- Accepter import SRT/VTT/ASS et archives, avec contrôles de chemins, taille décompressée, nombre de fichiers et sélection de l’épisode.
- Isoler les clés et sessions par compte. Documenter le stockage de la clé de chiffrement ; éviter une protection illusoire avec une clé stockée à côté des données.
- Utiliser un client API adapté au fournisseur et une politique explicite pour ses URL/CDN ; ne pas transformer le service en proxy ouvert.

**Validation :** tests de contrat simulés pour quotas, 401/429, URL expirée, archives malformées et mauvais épisode ; parcours réel limité avec un compte de test autorisé. Sans compte disponible, conserver le statut « validation fournisseur réelle en attente ».

## P9 — Étendre les fournisseurs et la synchronisation

**But :** améliorer la couverture et le choix du bon sous-titre.

Travaux :

- Ajouter SubDL via une version d’API explicitement choisie et vérifiée ; dédupliquer les résultats sans perdre leur provenance.
- Comparer langue, release, durée, FPS et numérotation ; proposer un décalage manuel avant toute dépendance supplémentaire.
- Évaluer `ffsubsync` ou `alass` sur des exemples connus avant de retenir un outil optionnel desktop/serveur. Toujours conserver le texte original et permettre le retour arrière.
- Distinguer simple décalage, dérive et montage différent ; ne pas garantir une correction automatique universelle.
- Évaluer Jimaku ultérieurement si un besoin de sous-titres japonais est confirmé ; il n’est pas prioritaire pour la couverture française.

**Validation :** même épisode sous plusieurs releases, numérotation absolue, mauvais FPS et montage incompatible. Présenter les limites et mesurer les corrections obtenues sur un corpus identifié.

## P10 — Prouver l’apport de N_m3u8DL-RE hors ligne

**But :** démontrer le gain avant d’engager sa distribution.

Travaux :

- Épingler une version et ses empreintes après vérification des options exactes. Le tag du rapport est une référence étudiée, pas une obligation de distribuer cette version bêta.
- Créer un backend désactivé par défaut, derrière le contrat de P1, pour des VOD locales synthétiques et sans secrets.
- Couvrir HLS simple/AES-128, fMP4/BYTERANGE, DASH audio séparé et sous-titres segmentés, dont synchronisation WebVTT/discontinuités.
- Distinguer assemblage interne des pistes et sortie finale : le traitement de P6/P7 garde la responsabilité du résultat demandé.
- Tester et documenter les limites de progression console, checkpoints et formats. Ne pas assimiler JSON de métadonnées et API stable de progression.

**Validation :** comparaison des sorties avec les fixtures de référence, gain de couverture démontré, arrêt et récupération de fragments testés. Aucun accès à des sources externes n’est activé par ce seul lot. Live, DRM et déchiffrement non validé restent hors périmètre.

## P11 — Préserver les sessions et la politique réseau

**But :** empêcher le backend externe de contourner les protections d’AnimeLab.

Travaux :

- Développer et tester `ManifestRelay` : capacité privée par tâche, réécriture des références, récupération via `SourceHTTPService` et contrôle à chaque requête/redirection.
- Couvrir segments, clés, pistes et playlists HLS, puis les références DASH nécessaires au périmètre retenu : BaseURL, templates, périodes et plages.
- Révoquer les capacités à l’arrêt ; isoler caches et sessions des comptes ; exclure cookies et clés de argv, des rapports et des logs.
- Vérifier qu’aucune requête du sous-processus ne peut sortir de la politique prévue, par restriction d’exécution réseau ou mécanisme équivalent démontré. La seule réécriture des URL n’est pas une preuve suffisante.
- Garder les cas non couverts sur un backend existant compatible, ou les refuser explicitement.

**Validation :** manifestes hostiles, redirections vers réseau privé, URL imbriquées, renouvellement de session, révocation et accès d’un autre compte refusés. Observer les destinations réellement contactées ; aucun déploiement partagé avant réussite.

## P12 — Tester la résilience et décider de l’adoption

**But :** décider sur preuves si le nouveau backend mérite d’être conservé.

Travaux :

- Tester panne réseau, fragment tronqué, URL signée renouvelée, changement de représentation, redémarrage du serveur et annulation.
- Persister backend/version, espace de travail et empreinte de représentation ; vérifier l’intégrité des fragments plutôt que leur seule présence.
- Mesurer couverture, réussite/reprise, débit, CPU/RAM, disque temporaire, qualité des diagnostics et complexité du relais/adaptateur sur un corpus décrit.
- Consigner une décision : expérimental, adopté pour certains formats, ou non retenu. Ne pas activer un backend globalement sur la seule base d’un gain de débit.

**Validation :** aucun fichier annoncé complet avec piste obligatoire absente, pas de mélange de fragments incompatibles ni de régression réseau. Décision écrite et restrictions connues ; en cas de refus, clôturer P13/P15 comme non retenus.

## P13 — Distribuer sur desktop et serveur

**But :** fournir une intégration maintenable si P12 est favorable.

Travaux :

- Ajouter le binaire épinglé aux builds Windows, Linux, macOS x64/ARM64 et Docker ; contrôler les empreintes et les notices/licences applicables.
- Ajouter configuration et diagnostic dans le launcher/paramètres : backend disponible, version, chemin éventuel, restrictions et erreurs utiles.
- Tester installation propre, chemins Unicode/espaces, permissions et terminaison des processus ; vérifier le fonctionnement sans backend optionnel.
- Mesurer archive et taille installée, documenter le retour au moteur existant et conserver l’activation expérimentale tant que nécessaire.
- Préparer les artefacts via GitHub Actions et le format de release existant ; ne pas publier automatiquement du seul fait que ce lot est terminé.

**Validation :** sorties média et contrôles de lancement réussis sur chaque cible. Distinguer les résultats des runners et les essais sur appareil réel, notamment macOS.

## P14 — Rendre le hardsub disponible sur Android

**But :** apporter les profils de sortie Android indépendamment du choix de N_m3u8DL-RE.

Travaux :

- Choisir une variante FFmpeg ou un build JNI contenant libass et un encodeur compatible, avec licences et polices vérifiées.
- Raccorder progression, annulation et diagnostics JNI au contrat de P5 ; vérifier export, stockage temporaire et finalisation après arrêt de l’application.
- Adapter la concurrence, les messages utilisateur et les restrictions aux capacités, à l’espace disque et au coût de réencodage constatés.
- Conserver les identifiants d’installation et la chaîne de signature. GitHub Actions construit/signe les APK destinés à être distribués.

**Validation :** filtre et encodeur réellement exécutés sur les ABI supportées, appareils/API représentatifs, export et rendu vérifiés ; observer mémoire, consommation et température. Waydroid seul ne valide pas les performances sur téléphone. Si le support reste insuffisant, désactiver le profil avec explication.

## P15 — Évaluer N_m3u8DL-RE dans l’APK

**But :** décider si Android doit bénéficier du backend spécialisé.

Travaux :

- Prouver une méthode d’intégration compatible APK/Bionic et les restrictions Android ; ne pas exécuter un binaire téléchargé dans le répertoire privé inscriptible.
- Valider ABI, API 29/30/35, compatibilité des pages mémoire de 16 Ko, dépendances, taille et modèle de permissions.
- Reprendre les contrats P10–P12 : réseau, isolation, progression, arrêt, checkpoints et renouvellement de session.
- Comparer avec le backend natif avant toute activation ; garder un chemin natif et un diagnostic lisible.

**Validation :** preuve sur appareils et APK distribuable par CI ; décision d’adoption distincte de celle du desktop. Sans preuve concluante, clôturer ce lot comme non retenu et conserver le moteur Android existant.

## Vérifications communes et suivi

Depuis la racine du dépôt, sélectionner les tests pertinents pendant le développement. Exemples de suites existantes à compléter selon le lot :

```bash
uv run --locked python -m pytest tests/test_subtitle_pipeline.py tests/test_download_stages.py tests/test_download_robustness.py tests/test_transfer_fault_contracts.py -q
```

Avant intégration, exécuter les contrôles applicables de la CI. Le runner documenté du projet est :

```bash
uv run --locked python scripts/check.py all
```

Les nouveaux contrats ajoutent leurs propres tests ; les suites actuelles ne suffisent pas à valider des fonctionnalités nouvelles. Les essais FFmpeg, N_m3u8DL-RE, fournisseur authentifié et appareil Android sont consignés séparément, avec version, plateforme, résultat et limites. Un test simulé ne remplace pas un essai d’intégration réel.

Pour chaque lot, tenir ce relevé dans sa PR ou son compte rendu :

| Champ | Contenu attendu |
| --- | --- |
| Statut | À faire / en cours / validé / bloqué / non retenu avec décision |
| Livré | Comportement utilisateur et composants modifiés |
| Preuves | Commandes, versions, résultats et cas de régression |
| Données | Migration et récupération, si nécessaire |
| Limites | Plateformes ou cas non testés, capacités désactivées |
| Suite | Lot suivant et éventuelle condition restant à lever |

**Suite : valider P14 sur les APK GitHub Actions et des appareils compatibles.** Le [bilan P14–P15](IMPLEMENTATION_P14_P15.md) décrit le chemin JNI implémenté, la sonde de rendu et les limites de validation. P14 n’est pas déclaré validé sur Android. P15 est confirmé non retenu pour cette version après examen distinct des assets Bionic et des preuves manquantes ; le backend Android existant est conservé. P13 reste non retenu selon la décision P12. Les validations fournisseurs authentifiées P8/P9 et les essais des plateformes non couvertes restent distincts des tests Linux.
