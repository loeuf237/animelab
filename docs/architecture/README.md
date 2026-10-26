# Architecture et dossier UML d’AnimeLab

Ce dossier décrit le code présent dans le dépôt au **20 octobre 2026**. Il contient
**17 diagrammes** : 5 vues de classes, 2 de cas d’utilisation, 7 de séquence,
2 de déploiement et 1 proposition d’architecture cible. Les modèles sont des vues
de conception sélectionnées pour expliquer le fonctionnement ; ils ne reproduisent
pas chaque attribut, méthode ou endpoint.

Ouvrir la [galerie autonome](index.html) pour consulter, filtrer, agrandir ou
imprimer les rendus. Elle fonctionne hors ligne avec les SVG et ne contacte aucun
service externe. Les sources PlantUML sont modifiables.

**L’existant et les propositions sont distingués.** Les diagrammes 01 à 16
représentent l’implémentation observée. Le diagramme 17, en vert, représente une
évolution proposée. Les scénarios décrivent des branches du code, sans constituer
une preuve de test de toutes les sources ou de tous les appareils.

**A01 à A08, A10, A12 et A13 sont maintenant implémentés dans le code source.** Les vues ci-dessous
incluent le suivi par épisode/version, l’export Android indépendant, les étapes
de téléchargement séparées, le registre typé des sources et les migrations SQLite.
Le diagramme 17 distingue ces éléments des ports et événements encore proposés.
Ces changements ne modifient
pas l’APK bêta déjà publié et nécessitent une nouvelle compilation.

## 1. Périmètre et lecture

AnimeLab comprend une interface Vue 3/TypeScript avec Pinia, une API FastAPI, un moteur
Python de catalogue/extraction/téléchargement, une bibliothèque SQLite et des
adaptations de plateforme. Le même moteur sert le bureau, le navigateur/PWA et
l’application Android autonome. Vue est l'unique frontend web ; les anciennes
pages Jinja et leurs scripts/styles ont été supprimés. Les anciens liens
redirigent vers `/app/`, en conservant les paramètres de fiche et de recherche.

Trois familles de sources sont à distinguer : les services intégrés French-Manga,
VoirAnime et AnimePahe ; les conteneurs d’extensions fondés sur une recette ; les
adaptateurs Python spécifiques. Les extracteurs de lecteurs vidéo forment encore
un autre registre. **Importer un APK Aniyomi ne signifie pas exécuter son code
Kotlin/DEX** : AnimeLab en déduit une recette, complétée par des adaptateurs connus.

Le moteur garde en mémoire sa file de tâches et ses sessions HTTP. SQLite conserve
les tâches, favoris, progressions et paramètres ; certains services utilisent
SQLAlchemy, d’autres `sqlite3` directement. Cette architecture correspond à **un
worker applicatif** en mode personnel. Le mode partagé optionnel A09 ajoute une
passerelle authentifiée et un moteur privé par compte.

Notation : le triangle vide représente un héritage réel ; le losange plein une
composition ; une flèche pointillée une dépendance. Les rapprochements entre tables
par URL sont explicitement indiqués et ne sont pas présentés comme des clés
étrangères. Les éléments `module`, `object`, `dataclass` et `table` sont identifiés.
Les relations `include` et `extend` indiquent respectivement un sous-parcours requis
dans le contexte décrit et une extension conditionnelle.

## 2. Inventaire des diagrammes

| Vue | Contenu | Rendu | Source |
| --- | --- | --- | --- |
| 01 — Classes du domaine | DTO, épisodes, versions, tâches, entités SQLite | [SVG](svg/01-classes-domaine.svg) | [PlantUML](plantuml/01-classes-domaine.puml) |
| 02 — Services métier | File, bibliothèque, contrôle média, surveillance, callbacks | [SVG](svg/02-classes-services.svg) | [PlantUML](plantuml/02-classes-services.puml) |
| 03 — Sources et extensions | Catalogue, recettes, adaptateurs et extracteurs | [SVG](svg/03-classes-sources.svg) | [PlantUML](plantuml/03-classes-sources.puml) |
| 04 — Réseau | Sessions par domaine, façades async, proxies, erreurs | [SVG](svg/04-classes-reseau.svg) | [PlantUML](plantuml/04-classes-reseau.puml) |
| 05 — Hôte Android | Activités, service, ponts Kotlin et Python embarqué | [SVG](svg/05-classes-android.svg) | [PlantUML](plantuml/05-classes-android.puml) |
| 06 — Cas fonctionnels | Catalogue, recherche, lecture, téléchargements, favoris | [SVG](svg/06-cas-utilisation.svg) | [PlantUML](plantuml/06-cas-utilisation.puml) |
| 07 — Cas réseau/stockage | Vérification assistée, proxies, permissions et export | [SVG](svg/07-cas-utilisation-reseau-stockage.svg) | [PlantUML](plantuml/07-cas-utilisation-reseau-stockage.puml) |
| 08 — Recherche et vérification | Résultats partiels, CAPTCHA manuel, cookies, reprise | [SVG](svg/08-sequence-recherche-verification.svg) | [PlantUML](plantuml/08-sequence-recherche-verification.puml) |
| 09 — Téléchargement | Direct/HLS, AES, sous-titres, publication, intégrité | [SVG](svg/09-sequence-telechargement.svg) | [PlantUML](plantuml/09-sequence-telechargement.puml) |
| 10 — Reprise et proxy | Flux actif protégé, Range, identité et cache HLS | [SVG](svg/10-sequence-reprise-proxy.svg) | [PlantUML](plantuml/10-sequence-reprise-proxy.puml) |
| 11 — Extensions | Import du dépôt, activation, recette, diagnostic | [SVG](svg/11-sequence-extensions.svg) | [PlantUML](plantuml/11-sequence-extensions.puml) |
| 12 — Stockage Android | SAF, MediaStore, publication et réexport | [SVG](svg/12-sequence-stockage-android.svg) | [PlantUML](plantuml/12-sequence-stockage-android.puml) |
| 13 — Surveillance | Planification et auto-téléchargement actuels | [SVG](svg/13-sequence-auto-telechargement.svg) | [PlantUML](plantuml/13-sequence-auto-telechargement.puml) |
| 14 — Lecture | Fichier local, proxy distant/HLS, pistes, progression | [SVG](svg/14-sequence-lecture.svg) | [PlantUML](plantuml/14-sequence-lecture.puml) |
| 15 — Déploiement bureau/web | Processus, réseau, stockage et services tiers | [SVG](svg/15-deploiement-bureau-web.svg) | [PlantUML](plantuml/15-deploiement-bureau-web.puml) |
| 16 — Déploiement Android | Python autonome, loopback protégé, JNI et stockage | [SVG](svg/16-deploiement-android.svg) | [PlantUML](plantuml/16-deploiement-android.puml) |
| 17 — Cible proposée | Monolithe modulaire, ports et états d’export | [SVG](svg/17-cible-amelioree.svg) | [PlantUML](plantuml/17-cible-amelioree.puml) |

## 3. Cas d’utilisation détaillés

Les références UC correspondent aux deux diagrammes de cas d’utilisation. Un
utilisateur peut être local ou accéder au serveur dans son navigateur ; certaines
actions réseau et toutes les fonctions Android ont des préconditions spécifiques.

### UC01 — Explorer le contenu d’une source

- **Acteur / déclencheur :** utilisateur ouvrant l’onglet Sources et une source.
- **Préconditions :** source intégrée ou extension activée ; connexion disponible.
- **Parcours :** lire les capacités ; choisir sorties, catalogue ou popularité ;
  charger les filtres ; appliquer les tags/tri pris en charge ; parcourir les pages.
- **Variantes :** un filtre peut ne porter que sur la page chargée ; certaines
  sources n’offrent ni popularité ni genres. Un échec doit conserver son diagnostic.
- **Résultat :** catalogue affiché selon les capacités réelles, ou accès au parcours
  UC12/UC13 avec l’URL bloquée. API : `/api/sources` et `/{source_id}/catalogue`.

### UC02 — Rechercher un animé

- **Acteur / déclencheur :** utilisateur via Ctrl+K ou une recherche de source.
- **Préconditions :** critère accepté par l’interface ; source activée si ciblée.
- **Parcours :** choisir une source ou toutes ; lancer les recherches concurrentes ;
  dédupliquer par source/URL ; afficher les résultats et les erreurs par source.
- **Exceptions :** timeout, refus, protection ou source désactivée ; les résultats
  des autres sources sont conservés avec `include_challenges=true`.
- **Résultat :** liste exploitable ; après vérification, seule une recherche encore
  active est rejouée. Séquence 08 ; API `/api/search`.

### UC03 — Consulter une fiche et choisir une version

- **Acteur / déclencheur :** utilisateur ouvrant un résultat de catalogue.
- **Préconditions :** URL de source autorisée et fiche accessible.
- **Parcours :** récupérer la fiche/épisodes ; enrichir via TMDB si configuré ;
  rapprocher favoris et progression ; choisir épisode, VF/VOSTFR/VO, lecteur et qualité.
- **Exceptions :** enrichissement facultatif indisponible, lecteur absent, protection
  du site ; l’identité de la version doit rester conservée dans la sélection.
- **Résultat :** informations prêtes pour lecture ou téléchargement. API
  `/api/anime/detail`, `/api/episode/servers`, `/api/episode/size`.

### UC04 — Lire un épisode

- **Acteur / déclencheur :** utilisateur choisissant Lire.
- **Préconditions :** fichier local accessible ou flux distant résoluble.
- **Parcours :** utiliser la tâche locale correspondante si disponible ; sinon
  résoudre le lecteur ; relayer le média direct/HLS avec les headers nécessaires ;
  présenter les pistes utilisables ; permettre le plein écran.
- **Exceptions :** URL expirée, challenge, fichier absent ou codec non pris en
  charge ; afficher l’erreur et le parcours de vérification approprié.
- **Résultat :** lecture locale ou distante. Le modèle persiste « vu/téléchargé » ;
  la position en secondes et les pistes sont conservées séparément dans `PlaybackProgress`,
  par source/série/épisode/version. Sauvegarde bornée et reprise après métadonnées. Séquence 14.

### UC05 — Télécharger un épisode ou un lot

- **Acteur / déclencheur :** utilisateur validant sa sélection et ses options.
- **Préconditions :** URL autorisée ; destination Android autorisée si applicable ;
  épisode identifié par source, URL, numéro et version.
- **Parcours :** contrôler les doublons/conflits ; produire un nom versionné ; créer
  et persister la tâche ; attendre un créneau ou la date planifiée ; résoudre le
  média ; télécharger en direct ou HLS ; traiter les pistes demandées ; vérifier
  le média ; exporter sur Android ; publier le statut et la progression.
- **Exceptions :** pause/annulation, protection, débit limité, perte réseau,
  fusion/integrité/export échoué. Les reprises doivent préserver le fichier utile.
- **Résultat :** média local vérifié ou état explicite permettant une correction.
  `COMPLETED` décrit la copie privée vérifiée ; `exportStatus` décrit séparément
  sa publication Android, avec erreur et action de réexport si nécessaire.
  Séquence 09 ; `/api/download`, `/api/download/batch`.

### UC06 — Piloter la file de téléchargements

- **Acteur / déclencheur :** utilisateur dans le gestionnaire ou une notification Android.
- **Préconditions :** tâche existante ; commande compatible avec son état.
- **Parcours :** mettre en pause, reprendre, annuler, prioriser un épisode/une série,
  réordonner, limiter le débit ou définir une planification ; persister puis diffuser
  l’état via SSE. L’interface possède un repli par interrogation périodique.
- **Exceptions :** conflit de destination, tâche supprimée, opération déjà en cours.
- **Résultat :** file et préférences de transfert actualisées. Les commandes de
  notification Android autorisées sont la pause/reprise du moteur.

### UC07 — Récupérer et fusionner les sous-titres

- **Acteur / déclencheur :** extension conditionnelle d’UC05 quand l’utilisateur
  demande des sous-titres et que des pistes sont connues.
- **Préconditions :** vidéo locale disponible ; URL/pistes résolues ; outil média
  disponible pour la fusion.
- **Parcours :** normaliser les métadonnées ; récupérer les pistes ; refuser HTML
  ou contenu invalide ; conserver langue/label ; fusionner dans un MKV temporaire ;
  publier avec un nom libre sans écraser une sortie existante ; vérifier le média.
- **Exceptions :** piste expirée, challenge, sous-titre invalide, FFmpeg en erreur ;
  la vidéo complète est conservée pour permettre une nouvelle finalisation locale.
- **Résultat :** pistes intégrées ou fichiers annexes valides. La langue de l’UI ne
  modifie pas la langue du média. Séquence 09.

### UC08 — Contrôler l’intégrité d’un fichier

- **Acteur / déclencheur :** moteur à la finalisation ; utilisateur demandant une
  vérification d’une tâche ou de l’ensemble des téléchargements terminés.
- **Préconditions :** chemin contrôlé ; média attendu identifiable.
- **Parcours :** existence/taille/type ; FFprobe si disponible ; échantillons de
  décodage selon le média ; restituer statut, durée et diagnostic.
- **Exceptions :** média vide, incomplet, corrompu, outil indisponible, timeout.
- **Résultat :** `VerificationResult` persistant dans la tâche. Le contrôle média
  est différent de la vérification humaine d’un site (UC12).

### UC09 — Gérer les favoris et la progression

- **Acteur / déclencheur :** utilisateur ajoutant un animé ou marquant un épisode vu.
- **Préconditions :** identité de fiche et version cohérentes.
- **Parcours :** ajouter/retirer le favori ; lire les épisodes téléchargés/vus ;
  marquer l’épisode concerné ; activer éventuellement la surveillance UC10.
- **Exceptions :** favori déjà présent ; données anciennes sans version nécessitant
  un rapprochement de compatibilité.
- **Résultat :** persistance SQLite ; progression unique sur URL/épisode/version.
  Cette bibliothèque est celle de l’instance, pas un compte cloud personnel.

### UC10 — Surveiller les favoris et planifier les nouveautés

- **Acteur / déclencheur :** politique activée par l’utilisateur ; boucle du watchdog.
- **Préconditions :** favori avec `autoDownload=true` ; moteur en fonctionnement.
- **Parcours :** toutes les cinq secondes vérifier les dates de tâches ; à
  l’intervalle configuré, charger les favoris via le registre commun aux sources
  intégrées et extensions activées. Appliquer les choix de version, sous-titres,
  lecteur et qualité ; persister les découvertes par source/URL/numéro/version.
- **Exceptions :** source indisponible ou versions ambiguës sans choix explicite :
  diagnostic sur le favori. Un échec de mise en file reste `DISCOVERED` ; une tâche
  existante est rattachée au suivi, sans doublon ni relance aveugle d’un échec.
- **Résultat :** tâche portant source, version et URL d’animé. `lastKnownEpisode`
  sert de référence initiale pour les anciens favoris, puis devient informatif.
  Une version publiée plus tard pour un numéro déjà vu reste détectable. Les
  versions anciennement ignorées ne sont pas rétéléchargées après un changement de
  préférence ; les anciens épisodes restent téléchargeables depuis la fiche.

### UC11 — Importer, activer et configurer une extension

- **Acteur / déclencheur :** utilisateur important l’URL d’un dépôt.
- **Préconditions :** dépôt et APK accessibles ; URL autorisée ; format compatible.
- **Parcours :** importer le catalogue du dépôt actif ; conserver les choix des
  entrées existantes ; laisser les nouvelles désactivées ; à l’activation analyser
  l’APK et construire une recette ; charger le conteneur ; tester/configurer si besoin.
- **Exceptions :** sélecteurs insuffisants, logique personnalisée non couverte,
  site fermé, erreur TLS ou challenge ; ne pas présenter cela comme un catalogue vide.
- **Résultat :** source utilisable si sa recette/adaptation est compatible, avec
  diagnostic et configuration disponibles. Séquence 11.

### UC12 — Rétablir l’accès à un site protégé

- **Acteurs / déclencheur :** utilisateur, site protégé, navigateur compatible ;
  protection reconnue lors d’une recherche, navigation ou téléchargement.
- **Préconditions :** URL bloquée connue du moteur. Les commandes de capture et de
  contrôle sont réservées au client loopback ; une session graphique ou WebView
  native compatible est nécessaire pour la capture dédiée.
- **Parcours :** montrer le domaine/URL ; ouvrir une fenêtre dédiée ; faire valider
  manuellement la protection ; lire les cookies du domaine ; les importer ; contrôler
  réellement l’accès avant de lever le blocage ; reprendre la demande active.
- **Variantes :** un simple onglet externe permet la visite manuelle sans transfert
  automatique des cookies ; sa commande de retour effectue un contrôle d’accès.
  La WebView dédiée actuelle ne gère pas une session utilisant un proxy.
- **Exceptions :** fenêtre fermée, session expirée, route incompatible ou refus
  persistant ; conserver l’état de vérification nécessaire. Séquence 08.

### UC13 — Configurer et faire tourner les proxies

- **Acteur / déclencheur :** utilisateur dans Paramètres → Proxy ; moteur lorsque
  la rotation automatique est explicitement activée.
- **Préconditions :** liste publique rafraîchie/testée ou proxy manuel ; pour une
  rotation, domaine connu et session libre ; pas de fenêtre de vérification active.
- **Parcours :** importer/configurer ; tester un échantillon borné ; choisir une
  route admissible ; changer les handles/cookies de la session inactive ; reprendre
  les tâches bloquées correspondantes ; contrôler l’identité avant de reprendre les octets.
- **Exceptions :** aucun candidat sain, flux encore loué, erreur TLS ou protection
  persistante. Une rotation manuelle active est refusée avec 409.
- **Résultat :** nouvelle route ou refus explicite ; aucune garantie qu’un proxy
  public fonctionne pour une source. Séquence 10.

### UC14 — Choisir une destination et gérer les permissions Android

- **Acteurs / déclencheur :** utilisateur et DocumentsUI, depuis Paramètres → Stockage.
- **Préconditions :** exécution dans l’application Android native.
- **Parcours :** afficher le mode courant ; conserver Downloads/AnimeLab ou ouvrir le
  sélecteur de dossier ; obtenir une URI avec droits persistants ; vérifier et
  mémoriser l’autorisation ; permettre l’ouverture du dossier et des paramètres système.
- **Exceptions :** sélection annulée, droit révoqué, fournisseur indisponible ; garder
  un état explicite et permettre un nouveau choix.
- **Résultat :** destination autorisée. Le mode MediaStore par défaut sur Android 10+
  n’exige pas une permission globale de stockage. Séquence 12.

### UC15 — Exporter ou réexporter le média Android

- **Acteurs / déclencheur :** moteur après vérification, ou utilisateur sur une tâche terminée.
- **Préconditions :** copie privée vérifiée ; destination accessible ; réexport manuel
  réservé à une tâche `COMPLETED`.
- **Parcours :** choisir MediaStore ou SAF ; réserver une sortie ; copier la vidéo
  et les sous-titres non fusionnés ; contrôler la taille ; publier ; retenir les URI.
- **Exceptions :** permission perdue, pause/annulation, espace insuffisant ; nettoyer
  la copie incomplète et garder la copie privée. Certains fournisseurs imposent
  `Movies/AnimeLab` pour les sous-titres annexes.
- **Résultat :** `COMPLETED` pour la vidéo privée vérifiée ; export distinct
  `PENDING`, `EXPORTING`, `EXPORTED` ou `EXPORT_FAILED`, avec URI, destination,
  tentatives, date et diagnostic persistés. Une interruption revient à `PENDING`.
  Le réexport relit uniquement la copie privée ; deux demandes simultanées ne
  lancent pas deux copies. Les exports à reprendre survivent au nettoyage groupé.
  Une ancienne tâche sans preuve d’export reste `NOT_REQUESTED`, affichée comme
  « export non renseigné » sur Android.

### UC16 — Personnaliser langue et préférences

- **Acteur / déclencheur :** utilisateur au premier lancement ou dans les paramètres.
- **Préconditions :** interface chargée ; catalogue FR/EN embarqué.
- **Parcours :** détecter la langue ; appliquer une préférence explicite sauvegardée ;
  choisir thème, source par défaut et options ; conserver le choix explicite de source.
- **Variantes :** sans choix préalable, anglais → AnimePahe ; français → French-Manga.
  Les préférences navigateur et certains paramètres moteur ont des portées différentes.
- **Résultat :** interface localisée ; aucune traduction automatique des titres,
  des sous-titres ou de l’audio des sources.

### UC17 — Consulter et nettoyer historique et tâches

- **Acteur / déclencheur :** utilisateur ouvrant Historique ou les actions de nettoyage.
- **Préconditions :** tâche/entrée existante ; périmètre de l’action affiché.
- **Parcours :** consulter états et diagnostics ; supprimer une entrée, une tâche
  ou une catégorie inactive selon l’action ; rafraîchir les vues concernées.
- **Exceptions :** tâche active, fichier manquant, erreur de stockage ; les actions
  de retrait de tâche et d’annulation n’ont pas les mêmes effets.
- **Résultat :** file/historique actualisé. La suppression du média dépend de
  l’endpoint et des options ; elle n’est pas déduite du seul terme « nettoyer ».

### UC18 — Reprendre après interruption ou changement de route

- **Acteur / déclencheur :** utilisateur, moteur au redémarrage ou après accès rétabli.
- **Préconditions :** tâche persistée, partiel exploitable ou média final présent.
- **Parcours :** restaurer l’état ; préférer une finalisation locale possible ;
  résoudre à nouveau les URL expirées ; contrôler Range, validateur, taille et
  recouvrement ; ne garder que les segments HLS de la même playlist/variante.
- **Exceptions :** représentation changée, Range ignoré, 416, partiel invalide,
  protection ; recommencer proprement ou attendre l’action adaptée.
- **Résultat :** aucune concaténation de représentations différentes. Les tâches
  `PAUSED` ne sont pas toutes reprises par `resume_verified_domain`. Séquence 10.

## 4. Contraintes et limites mises en évidence

- **File et sessions locales au processus.** Plusieurs workers Uvicorn créeraient
  plusieurs gestionnaires et états réseau indépendants ; les diagrammes supposent
  l’instance unique actuellement prévue.
- **Identité des épisodes.** Le couple numéro/version évite la confusion VF/VOSTFR,
  complété par la source et l’URL d’animé dans le suivi automatique. Le watchdog
  utilise le même registre de fournisseurs que le catalogue.
- **Terminé et exporté sont différents.** Une vidéo valide dans la bibliothèque
  privée reste `COMPLETED` ; un échec de publication appartient à `exportError`
  et `exportStatus`, avec un réexport local possible.
- **Permissions et espace disque.** Android garde une copie privée puis une copie
  partagée. Une permission SAF persistante peut être révoquée ultérieurement.
- **Vérification de site.** Une visite dans un onglet distant ne donne pas accès aux
  cookies du navigateur à Python. La capture dédiée dépend de la plateforme et de
  la route réseau ; les actions natives du serveur sont locales.
- **Sources importées.** Une recette extraite d’un APK n’est pas l’équivalent de son
  programme d’origine. Les capacités et la compatibilité doivent être explicites.
- **Progression de lecture.** Le modèle conserve des indicateurs vu/téléchargé,
  avec position temporelle persistée dans `PlaybackProgress`. Les pistes audio
  dépendent de ce que HLS ou le navigateur expose ; aucun codec supplémentaire n’est ajouté.
- **HTTP métier et métadonnées.** Les requêtes sources/médias passent par le transport
  partagé ; `TmdbService` crée encore son propre client HTTPX.

## 5. Axes d’amélioration priorisés

Les changements A01 à A08 et A10 à A13 sont implémentés dans le code source ;
A09 dispose désormais d'un mode serveur partagé optionnel : comptes et invitations
gérés par l'administrateur, permissions, sessions révocables et moteurs isolés par
compte. Voir [configuration et limites](../shared-server.md). Les fichiers sont
stockés séparément par compte ; la déduplication physique reste à prévoir.
A14 est partiellement réalisé : le frontend Jinja a été retiré ; l'unification
des préférences locales et moteur reste à poursuivre.
Le [bilan A11](a11-validation.md) décrit la réduction mesurée de l'APK,
les contrôles natifs et la validation séparée du stockage installé.
Le [bilan A10/A12/A13](a10-a12-a13-validation.md) décrit les diagnostics,
la reprise de lecture et les recettes observables et versionnées.
Le [bilan A03–A05](a03-a05-validation.md) décrit l’extraction progressive,
les capacités communes et les migrations transactionnelles.
Le [bilan et la procédure de validation A06–A08](a06-a08-validation.md) décrivent
les contrats ajoutés et les limites de validation sur appareil.
Les tests de contrat utilisent des fournisseurs simulés et ne
prouvent pas l’accès permanent aux sites ni tous les comportements d’appareils Android.
Les charges sont relatives : S = modification localisée, M = plusieurs composants,
L = évolution transversale avec migration/validation. Ce ne sont pas des délais.

| ID | Priorité / charge | Changement concret | Bénéfice et critère de validation |
| --- | --- | --- | --- |
| A01 | Implémenté / P0 / M | Registre commun, identité persistante par source/URL/épisode/version et options de suivi en bibliothèque | Contrats simulés pour les 3 sources et une extension ; VF/VOSTFR séparées ; découverte conservée après échec de mise en file |
| A02 | Implémenté / P0 / M | État d’export, URI, tentatives et erreur séparés ; interface de réexport local | Refus, interruption, copie concurrente, migration et réexport sans réseau couverts ; contrôle Android natif à revalider sur appareil |
| A03 | Implémenté / P1 / L | TransferWorker, MediaPipeline, ExportCoordinator et DownloadScheduler composés par la façade ; transitions contrôlées ; budgets distincts | Tests de concurrence réseau/média/export, annulation conservant le permis natif et reprise après arrêt ; API historique conservée |
| A04 | Implémenté / P1 / M | SourceProvider structurel, RegisteredSource et SourceRegistry ; capacités calculées selon recettes et adaptateurs | Recherche, fiche, flux, catalogue et watchdog partagent le registre ; source inconnue/désactivée refusée ; aucune popularité inventée |
| A05 | Implémenté / P1 / M | Connexions communes, migrations 1–6 avec journal et BEGIN IMMEDIATE ; tâche/progression/export/suivi dans la même transaction | Copie réelle conservée, migration répétée, échec DDL+données annulé, version future refusée et rollback des états liés testés |
| A06 | Implémenté / P1 / M | Contrats Pydantic et TypeScript aux frontières API ; erreurs structurées, traduites et versionnées ; schéma OpenAPI | Entrées invalides refusées avant mise en file ; anciens champs conservés ; JSON variable des recettes explicitement borné au type JSON |
| A07 | Implémenté / P1 / M | Interface de vérification avec mécanismes Chromium installé et WebView ; capacités par plateforme, client et proxy | Matrice bureau/Android/client distant/proxy testée ; changement de route détecté ; recherches actives conservées ; capture non promise pour un onglet manuel |
| A08 | Implémenté / P1 / M | Tests à fautes et protections de reprise/publication : URL renouvelée, cache HLS altéré, arrêt durant assemblage/mux/export | Cache vérifié par empreinte ; assemblage temporaire ; destination concurrente préservée ; finalisation et export sans duplication dans les scénarios couverts |
| A09 | Implémenté, mode optionnel | Comptes administrés, invitations/récupération, permissions et moteurs privés par compte | Tests de deux moteurs réels : bibliothèques/réglages séparés, médias et actions privés, sessions révocables ; voir [guide](../shared-server.md) |
| A10 | Implémenté / P2 / M | Événements structurés bornés, transitions/durées, journaux expurgés et export JSON local dans les paramètres | Liste blanche des champs exportés ; cookies, secrets, URL signées et identifiants proxy exclus ; tests de confidentialité |
| A11 | Implémenté / P2 / M | Symboles natifs retirés des copies générées, R8 et ressources réduits, assets dédupliqués, XML natif inutilisé supprimé | APK testé de 77,76 à 61,31 Mo (−21,16 %) ; stockage au premier affichage de 137,52 à 97,37 Mo (−29,20 %) ; moteur/JNI/HLS/sous-titres/export validés sur Android 10 ARM64 ; APK normal signé de 61,36 Mo |
| A12 | Implémenté / P2 / M | Table de positions par source/série/épisode/version, session et séquence ; choix qualité/serveur/pistes ; lecteur Vue intégré | Reprise après métadonnées, local/distant unifiés, VF/VOSTFR séparées, écriture bornée et anciennes fenêtres exclues |
| A13 | Implémenté / P2 / M | Santé par opération, codes distincts et durées, schéma de recette v1, 20 révisions/restauration et corpus HTML/JSON | Dérive de sélecteur distinguée de protection/réseau ; précontrôle des lots ; observations associées à une révision |
| A14 | Partiellement implémenté / P2 / M | Vue seul frontend, redirections des anciens liens, retrait des templates, styles/scripts et dépendances Jinja ; préférences locales/moteur à unifier | Liens et recherches conservés, mise à jour du cache PWA, distributions et tests adaptés |

**Prochaine étape recommandée :** valider A01–A08 et A10/A12/A13 sur appareil Android ;
poursuivre le découplage des étapes vis-à-vis de la façade et revalider la distribution Android à chaque évolution du moteur.
A09 devient préalable à un usage multiutilisateur exposé. La [cible proposée](svg/17-cible-amelioree.svg)
conserve Python et décrit un monolithe modulaire.

Voir aussi l’[étude de taille APK](../android-apk-size-study.md), la
[distribution Android](../android-distribution.md) et la
[distribution bureau](../desktop-distribution.md). Les travaux proposés ne
doivent pas réduire les garanties existantes de session, reprise ou publication.

## 6. Traçabilité dans le code

La validation d’A01/A02 est reproductible dans
[`test_auto_download_tracking.py`](../../tests/test_auto_download_tracking.py),
[`test_auto_export_migrations.py`](../../tests/test_auto_export_migrations.py),
[`test_android_platform.py`](../../tests/test_android_platform.py) et les
[régressions frontend](../../frontend/tests/regressions.test.mjs).
Elle couvre notamment VF/VOSTFR, choix modifié ou désactivé en cours de requête,
échec de mise en file, migration d’ancienne base, permission révoquée, interruption,
copies concurrentes et réexport sans réseau. La vérification visuelle utilise une
base et un exporteur de démonstration isolés. Le module Kotlin et ses tests natifs
compilent ; leur exécution sur appareil Android reste à effectuer pour ces changements.

Les sources PlantUML contiennent des commentaires `@source chemin:Symbole`.
Le générateur vérifie ces références par AST Python ou déclaration Kotlin ; il
enregistre aussi la révision du dépôt et les dimensions des SVG dans
[`diagrams.json`](diagrams.json). Cette vérification prouve l’existence des
symboles référencés, pas la couverture de tous les comportements du scénario.

| Domaine | Points d’entrée examinés |
| --- | --- |
| Modèles | [anime.py](../../animelab/models/anime.py), [download_task.py](../../animelab/models/download_task.py), [favorite.py](../../animelab/models/favorite.py), [auto_download.py](../../animelab/models/auto_download.py), [watch_progress.py](../../animelab/models/watch_progress.py) |
| API et UI | [run.py](../../run.py), [routeurs](../../animelab/routers), [client TS](../../frontend/src/api/client.ts), [store downloads](../../frontend/src/stores/downloads.ts) |
| Téléchargements | [DownloadManagerService](../../animelab/services/download_manager.py), [reprise](../../animelab/services/download_resume.py), [intégrité](../../animelab/services/verification_service.py), [sous-titres](../../animelab/services/subtitle_service.py) |
| Sources/extensions | [catalogue](../../animelab/services/source_catalogue.py), [extensions](../../animelab/services/extension_service.py), [parseur DEX](../../animelab/services/aniyomi_dex_parser.py), [conteneur](../../animelab/services/aniyomi_container.py) |
| Réseau | [transport](../../animelab/services/source_http.py), [vérification](../../animelab/services/browser_verification.py), [proxies publics](../../animelab/services/proxy_pool.py), [routes réseau](../../animelab/routers/network.py) |
| Bibliothèque et automatisation | [LibraryService](../../animelab/services/library_service.py), [WatchdogService](../../animelab/services/watchdog_service.py) |
| Bureau et Android | [desktop.py](../../desktop.py), [android_runtime.py](../../android_runtime.py), [Kotlin](../../android/app/src/main/java/com/animan/app), [sécurité Android](../../animelab/android_security.py), [façade média](../../animelab/media_tools.py) |

## 7. Régénérer et contrôler le dossier

Pré requis : Python 3.11+, Java, Graphviz et un JAR PlantUML local. Le rendu de ce
dossier a été effectué avec PlantUML 1.2020.02 et le mode Java headless ; les sources
emploient une notation compatible avec ce moteur.

```bash
python3 scripts/render_architecture.py
# ou préciser un JAR différent :
python3 scripts/render_architecture.py --plantuml-jar /chemin/plantuml.jar
# vérifier seulement les références aux symboles du dépôt :
python3 scripts/render_architecture.py --check-only
```

Le script reconstruit les SVG, la galerie et le manifeste, puis crée une archive
transportable dans `build/architecture/animan-uml.zip`. Les liens de code de ce
document supposent le dépôt complet ; la galerie et les figures fonctionnent
seules dans l’archive. Le contrôle documentaire ne démarre pas le serveur, n’exécute
pas de téléchargement, ne modifie pas les paramètres et ne publie aucun fichier.
