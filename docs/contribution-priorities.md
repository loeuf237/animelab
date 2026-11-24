# AnimeLab recherche des contributeurs

[Français](contribution-priorities.md) | [English](contribution-priorities.en.md)

Nous recherchons des personnes pour améliorer AnimeLab : design, développement
Android/Kotlin, Python/FastAPI, Vue/TypeScript, tests sur appareils, traductions
et documentation. Une maquette, un scénario de reproduction ou un retour de
test précis est déjà une contribution utile.

Les chantiers ci-dessous sont des **travaux proposés**, à préciser avec les
contributeurs. Ils ne constituent pas une liste de fonctionnalités terminées.
Les propositions de fonctionnalités et d’architecture sont les bienvenues.

Pour participer, ouvrez ou rejoignez une
[issue](https://github.com/loeuf237/animelab/issues) en indiquant le chantier
concerné et ce que vous souhaitez prendre en charge. Vous pouvez aussi échanger
avec la communauté sur **[Telegram — AnimeLab Group](https://t.me/AnimeLabGroup)**
ou directement avec le mainteneur sur **[Telegram — @loeuf237](https://t.me/loeuf237)**.
Consignez les décisions techniques et les résultats de tests dans l’issue ou
la PR afin que les autres contributeurs puissent les retrouver.

Consultez le [guide de contribution](../CONTRIBUTING.md) pour l’installation,
les vérifications et les pull requests.

## Points de départ — 24 novembre 2026 (après v0.2.0)

La version [`v0.2.0`](releases/v0.2.0.md) a livré la comparaison, le téléchargement, la vérification SHA-256 et l’installation intégrée des releases, les correctifs de duplication et de dossiers de téléchargement, la prise en charge du format BDD d’Anime-Sama, les en-têtes adaptés à Codeberg et la lisibilité de la fiche animé en modes clair et sombre.

Commencez par les [trois fiches pratiques](first-contribution.md) :
guide Linux #21, palette de thème #28 ou chantiers ciblés (`good first issue`) comme #51, #57, #58, #60, #62, #68, #71, #74 ou #78.
Demandez de l’aide dans l’issue choisie ; un rapport ou une maquette annotée est utile.
La comparaison des versions (#14), le filtre de bibliothèque (#31) et le rapport hors ligne Android (#32) sont déjà terminés.
Les seize chantiers ci-dessous précisent fonctions existantes et travail restant ;
lisez leur état avant de proposer une implémentation.

## 1. Repenser l’écran de chargement Android

**Objectif :** rendre le démarrage plus agréable et compréhensible, avec une
présentation cohérente avec l’identité d’AnimeLab.

Nous recherchons des propositions de design puis une implémentation Android.
Présenter les étapes réellement connues du démarrage, gérer une attente longue
et proposer une récupération en cas d’échec. Éviter un pourcentage inventé qui
donne une fausse impression de progression.

**Validation attendue :** maquettes et captures, lisibilité sur petits écrans,
thèmes clair/sombre, accessibilité et essais d’un démarrage normal, lent et en
erreur sur Android. Point d’entrée :
[`MainActivity.kt`](../android/app/src/main/java/com/animan/app/MainActivity.kt).

## 2. Détecter et télécharger automatiquement les nouvelles versions

**Disponible :** vérification des versions, comparaison numérique, canaux
stable/bêta, liens de release, téléchargement in-app avec barre de progression,
vérification `SHA256SUMS.txt`, relais vers Android `PackageInstaller` et
extraction d’archives Desktop livrés en `v0.2.0` dans
[`app_updates.py`](../animelab/services/app_updates.py) et
[`startup.py`](../animelab/routers/startup.py), avec tests dans
[`test_app_startup.py`](../tests/test_app_startup.py). Voir le
[guide de démarrage et mises à jour](startup-and-updates.md).
**Reste à faire (#54) :** remplacement atomique sur place pour les builds
Desktop figés (avec sauvegarde/restauration), nettoyage automatique du cache
des anciens paquets et réglage « Wi-Fi uniquement » sur Android. Étendre le
service existant sans créer un second comparateur de versions.

**Objectif :** proposer dans l’application un parcours de mise à jour inspiré
de Mihon/Aniyomi, en commençant par Android : détection d’une nouvelle version,
présentation des changements, téléchargement automatique configurable et
installation via le mécanisme Android.

Le module doit sélectionner le bon paquet pour la plateforme et l’architecture,
comparer correctement les versions et distinguer les canaux bêta/stable. Le
statut GitHub « pre-release » ne doit pas être le seul critère : une version
bêta peut être publiée comme release ordinaire.

**Validation attendue :** tester l’absence de mise à jour, une nouvelle version,
les canaux, une erreur réseau et un téléchargement interrompu. Respecter les
préférences réseau et de téléchargement, vérifier l’intégrité du fichier et
la compatibilité de signature avant installation, conserver les données et
laisser Android demander sa confirmation normale. Une mise à jour téléchargée
doit rester distincte d’une mise à jour effectivement installée.

## 3. Corriger les téléchargements et enregistrements en double

**Disponible :** la PR #33 a corrigé des copies finales conservées inutilement.
**Reste à faire :** vérifier dans #15 si un cas distinct de duplication persiste
sur bêta.5 ; consigner aussi une absence de reproduction. Ne pas considérer le
bug historique comme toujours présent ni supprimer les éditions voulues.

**Problème signalé :** un même fichier peut être téléchargé ou enregistré
plusieurs fois avec la source intégrée **French-Manga**. Il faut reproduire le
cas, identifier l’étape responsable et vérifier si d’autres sources sont affectées.

La correction doit couvrir les demandes répétées, les ajouts en lot ou
automatiques, les requêtes concurrentes, la reprise après redémarrage et
l’enregistrement/export du fichier final. Examiner les protections existantes
dans [`download_manager.py`](../animelab/services/download_manager.py) avant
d’ajouter un mécanisme parallèle.

**Validation attendue :** tests de régression montrant qu’une même demande ne
crée pas plusieurs tâches ou copies finales involontaires, y compris après une
relance. Préserver les téléchargements volontairement distincts : VF/VOSTFR/VO,
qualités et profils de sortie. Ne pas identifier un épisode uniquement par son
nom de fichier, son numéro ou une URL vidéo temporaire. Ajouter des cas pour
French-Manga et les autres chemins concernés ; conserver une action explicite
si l’utilisateur veut retélécharger.

## 4. Améliorer la compatibilité des extensions Aniyomi / Anikku / Animiru (Android & PC)

**Disponible :** exécution isolée des APK Android via `:extension-runtime`,
et moteur multiplateforme de traduction de bytecode DEX en recettes sûres sur
PC/Serveur/Web dans
[`aniyomi_dex_parser.py`](../animelab/services/aniyomi_dex_parser.py),
[`recipe_plans.py`](../animelab/services/recipe_plans.py),
[`recipe_runtime.py`](../animelab/services/recipe_runtime.py) et
[`aniyomi_container.py`](../animelab/services/aniyomi_container.py) (avec prise
en charge du nouveau format BDD `lien:` / `epsJeton` d’Anime-Sama en `v0.2.0`).
**Reste à faire (#61, #62) :** résoudre les extensions **Anikku**, **Animiru**
et **Aniyomi** encore défaillantes en améliorant le parseur DEX/héritage et les
opérations de recettes (#61 — API JSON/GraphQL, POST, filtres, sous-titres
externes) et en enrichissant les extracteurs d’hébergeurs vidéo (#62).

**Objectif :** améliorer la compatibilité réelle des dépôts et extensions
Aniyomi/Anikku/Animiru aussi bien sur le moteur APK Android que sur le moteur
de traduction de recettes PC/Serveur, avec des résultats reproductibles.

Tester les paquets déjà installés, l’installation et la mise à jour depuis un
dépôt, la confiance, les sources multiples, la recherche, les catalogues,
épisodes, filtres, préférences, résolution vidéo, lecture et téléchargement.
Vérifier aussi le parcours de session WebView puis la reprise de l’extension,
sans requêtes d’émulation concurrentes pendant la vérification.

**Validation attendue :** une matrice précisant version d’AnimeLab, APK/version,
version Android, appareil ou émulateur, opérations réussies et erreurs. Distinguer
un blocage du site d’une incompatibilité du moteur. La présence d’un paquet ne
prouve pas la réussite du parcours complet. Les recettes desktop/serveur doivent
être documentées séparément du moteur APK Android.

Partir de l’[étude existante](studies/aniyomi-anikku/README.md) et du
[guide de validation](studies/aniyomi-anikku/UTILISATION.md). Les APK de test sont
construits dans GitHub Actions ; les essais sur téléphone restent nécessaires.

## 5. Créer l’onglet Outils et un atelier de sous-titrage (#17, #18, #66)

**Issues liées :** #17 (entrée de navigation Outils), #18 (maquette sous-titres)
et **#66** (atelier complet de sous-titrage). Voir aussi la section **16 (#67)**
pour l’atelier de transcription audio sur PC.

**Objectif :** ajouter **Outils** dans la barre de navigation et y
regrouper des outils multimédias. Le premier chantier est un outil complet de
sous-titrage pour des séries ou épisodes déjà téléchargés.

Le parcours souhaité comprend :

- sélectionner une série ou des épisodes de la bibliothèque ;
- rechercher, comparer et télécharger des sous-titres correspondants, ou les
  importer depuis des fichiers ;
- choisir langue, épisode et version, prévisualiser, corriger le décalage et
  gérer les pistes et les outils/fournisseurs disponibles ;
- traduire les sous-titres avec une **clé d’API personnelle** Gemini, DeepL,
  OpenAI ou un autre fournisseur proposé ;
- exporter les sous-titres séparément ou les intégrer à une sortie vidéo avec
  les profils compatibles.

Réutiliser les services de sous-titres et de profils déjà présents dans
`animelab/services/`, plutôt que créer une seconde chaîne indépendante. Prévoir
une navigation adaptée au mobile comme au bureau.

**Validation attendue :** un premier parcours complet sur une vidéo locale,
sans retélécharger la vidéo, puis l’intégration des fournisseurs. Conserver les
originaux, le découpage et les timestamps lors de la traduction, signaler les
pertes éventuelles de style et vérifier la synchronisation à l’export. Les clés
restent privées et propres à l’utilisateur ; l’envoi du texte à un fournisseur
doit être explicite. Afficher les erreurs, quotas et coûts annoncés par le
fournisseur et permettre l’annulation ou la reprise des traitements.

## 6. Ajouter un atelier audio et la création de MKV multipistes

**Objectif :** compléter Outils avec un parcours de téléchargement et d’édition
de pistes audio provenant de sources fournies par des extensions audio, puis
les assembler avec une vidéo existante dans un **MKV multipistes audio**.

Commencer par une proposition d’architecture précisant ce qu’est une extension
audio prise en charge, ses contrats de données et ses différences avec une
extension vidéo. Cette compatibilité reste à définir et à valider.

Le parcours visé couvre la découverte et le téléchargement des pistes, leur
préécoute, la correspondance avec l’épisode, le choix des langues, le décalage,
les ajustements audio et l’assemblage. Une proposition peut préciser les étapes
ultérieures de l’éditeur.

**Validation attendue :** un MKV lisible contenant plusieurs pistes audio
sélectionnables, avec langues, titres et piste par défaut corrects, une durée
et une synchronisation vérifiées. Réutiliser les contrats média, profils de
sortie et traitements FFmpeg existants ; préserver les originaux. Procéder par
petites étapes testables avant d’étendre l’outil.

## 7. Repenser la page Extensions

**Disponible :** navigation Sources/Extensions, listes par langue, épingles,
recherche, préférences des paquets et actions de mise à jour dans bêta.5.
**Reste à faire :** identifier des problèmes concrets d’accessibilité, de petits
écrans ou de compréhension des états. #20 part désormais de ces écrans existants.
Voir aussi **#52** (tableau de bord de santé des sources et diagnostics anonymisés)
et **#53** (vérification périodique des nouveaux épisodes).

**Objectif :** améliorer son ergonomie et son apparence en s’inspirant de
Mihon/Aniyomi : navigation claire, listes lisibles et actions faciles à repérer.

Proposer des maquettes pour les dépôts, extensions installées/disponibles,
mises à jour, recherche et filtres de langue. Rendre visibles les états utiles :
installée, désactivée, confiance à approuver, mise à jour disponible, erreur ou
vérification nécessaire. Distinguer clairement un dépôt, une extension et les
sources qu’elle fournit.

**Validation attendue :** captures mobile/bureau, thèmes clair/sombre,
accessibilité et parcours d’ajout de dépôt, installation, activation, mise à
jour et récupération après erreur. Une amélioration visuelle ne doit pas
supprimer les informations de compatibilité ou les confirmations nécessaires.
La référence visuelle sert d’inspiration ; préserver l’identité d’AnimeLab et
respecter les licences des éléments réutilisés.

## 8. Améliorer le README et la documentation

**Objectif :** aider un nouvel utilisateur à installer, démarrer et comprendre
AnimeLab, puis permettre à un contributeur de reproduire les vérifications.

Nous recherchons des guides Linux/Windows/Android/macOS, captures actualisées,
exemples, traductions français/anglais et explications d’architecture. Clarifier
les différences entre release et sources, les limites connues, les extensions
et le dépannage. Rechercher les informations obsolètes ou contradictoires.

**Validation attendue :** liens fonctionnels, commandes vérifiées sur les
plateformes annoncées et distinction explicite entre fonctions disponibles,
expérimentales et envisagées. Un tutoriel suivi et corrigé par une personne
découvrant le projet est particulièrement utile.

## 9. Créer des thèmes pour l’application

**Disponible :** modes système/clair/sombre, palettes turquoise/violet/ambre/AMOLED,
sélecteur et choix persistant. Partir de
[`themes.css`](../frontend/src/themes.css),
[`ThemePicker.vue`](../frontend/src/components/ThemePicker.vue) et
[`appearance.ts`](../frontend/src/stores/appearance.ts).
**Reste à faire :** documenter les variables existantes, proposer une palette dans
#28 et vérifier contrastes et replis. Un import arbitraire de thèmes demande une
proposition séparée ; réutiliser le sélecteur actuel.

**Objectif :** permettre aux contributeurs de proposer des thèmes et aux
utilisateurs de choisir l’apparence d’AnimeLab, au-delà des modes clair/sombre.

Documenter les variables de palette et l’intégration au sélecteur existant.
Les premiers livrables peuvent être une palette supplémentaire documentée et
des maquettes, puis son intégration. Prévoir le choix
persistant, le retour au thème par défaut et la cohérence des écrans Android,
desktop et web. Un éventuel import de thèmes doit utiliser des données
déclaratives validées, avec des ressources disponibles hors ligne.

**Validation attendue :** captures du lecteur, de la bibliothèque, des
extensions et des paramètres ; contraste, focus, états d’erreur et texte lisibles
sur mobile et bureau. Vérifier la conservation du choix après redémarrage, le
repli sur le thème par défaut en cas de palette invalide et l’absence de
régression des thèmes existants.

## 10. Choisir un dossier externe au premier démarrage Android

**Disponible :** le choix initial du dossier existe depuis bêta.4, conservé dans
[`StartupFlow.vue`](../frontend/src/components/StartupFlow.vue) avec le pont de stockage Android.
**Reste à faire :** #24 suit les preuves sur appareil pour annulation, redémarrage,
export, dossier indisponible et autorisation révoquée ; #29 propose des améliorations
de texte et de récupération sur cet écran. Ne pas recréer le parcours initial.

**Objectif :** proposer dès le premier lancement un dossier AnimeLab choisi par
l’utilisateur pour ses médias, sous-titres et exports, en réutilisant le choix
de dossier déjà disponible dans les paramètres Android.

Valider l’étape existante : explication du dossier, sélecteur système,
confirmation du choix et destination par défaut explicite. Préserver l’autorisation persistante et permettre de modifier le
choix plus tard. Définir clairement quelles données sont exportées ; les bases,
cookies et secrets restent dans le stockage privé de l’application.

**Validation attendue :** premier démarrage, annulation du sélecteur, dossier
autorisé, non inscriptible ou devenu indisponible, redémarrage et autorisation
révoquée. Respecter les restrictions du sélecteur Android et proposer un dossier
valide ou la destination par défaut. Un changement ne doit pas déplacer ou
supprimer silencieusement les médias existants ; toute migration éventuelle
doit avoir son parcours explicite et vérifié.

## 11. Améliorer le lecteur vidéo Android

**Issues liées :** #25, #30 (audit portrait/paysage), **#49** (lecteurs
externes : mpv, VLC, Intent Android), **#50** (bouton Passer l’intro/outro et
enchaînement auto) et **#51** (raccourcis clavier et Picture-in-Picture sur
Desktop/Web).

**Objectif :** rendre la lecture plus confortable sur téléphone, pour le
streaming et les fichiers téléchargés, avec des commandes tactiles accessibles.

Proposer puis tester une meilleure disposition des contrôles : lecture/pause,
recherche temporelle, plein écran, orientation, vitesse, audio, sous-titres et
passage à l’épisode suivant. Les gestes supplémentaires peuvent faire l’objet
de petites propositions séparées. Réutiliser le suivi de progression et les
contrats média existants ; justifier toute évolution du moteur de lecture.

**Validation attendue :** petits écrans, portrait/paysage, commandes et menus
utilisables, reprise de position après fermeture ou recréation de l’activité,
erreur de décodage et média local indisponible. Vérifier les pistes réellement
prises en charge et annoncer explicitement les limites de formats/codecs.
Inclure une lecture locale sans réseau et préserver le comportement desktop/web.

## 12. Améliorer la gestion de la bibliothèque

**Disponible :** le filtre de titres local, non destructif et insensible aux
accents a été intégré par la PR #34 ; #31 est terminée.
**Reste à faire :** choisir une amélioration distincte : filtre de source ou d’état
de lecture, tri ou disponibilité locale vérifiée. Conserver le filtre actuel et
éviter une migration générale de bibliothèque comme première tâche. Pistes liées :
**#46** (sauvegarde/restauration portable complète), **#47** (migration d’une
série vers une autre source) et **#48** (suivi optionnel AniList / MyAnimeList).

**Objectif :** faciliter la recherche et l’organisation des séries, des épisodes
et des médias téléchargés dans une bibliothèque qui grandit.

Les propositions peuvent couvrir tri, recherche, filtres par source ou état de
lecture, catégories, actions groupées et affichage de la disponibilité locale.
Distinguer un favori, une entrée de bibliothèque et un fichier réellement
disponible. Conserver les identités de source, épisode et édition ainsi que les
progressions et préférences existantes.

**Validation attendue :** bibliothèque vide ou volumineuse, séries homonymes de
sources différentes, VF/VOSTFR/VO, recherche accentuée, redémarrage et opérations
groupées avec confirmation adaptée. Retirer une série de la bibliothèque et
supprimer ses fichiers doivent rester deux actions clairement distinguées.
Toute évolution du schéma doit prévoir une migration sans perte ; les médias
locaux doivent rester repérables en mode hors ligne.

## 13. Adapter Android à la lecture vidéo hors ligne

**Objectif :** permettre d’ouvrir AnimeLab, parcourir les épisodes disponibles et
les lire sans accès Internet, avec les métadonnées utiles conservées localement.

Identifier les dépendances réseau du démarrage, de la bibliothèque et du
lecteur. La lecture locale ne doit pas attendre un catalogue, une mise à jour ou
une résolution distante. Rendre visibles les épisodes réellement disponibles,
leur progression, leurs pistes audio et leurs sous-titres locaux. Prévoir la
reprise après fermeture et le retour au réseau sans doubler les tâches.

**Validation attendue :** téléchargement préalable, fermeture complète de
l’application, mode avion, redémarrage, navigation et lecture locale avec
recherche temporelle et reprise de position. Tester aussi un fichier supprimé,
un dossier externe indisponible et un média partiellement téléchargé, sans les
présenter comme disponibles. Distinguer les médias privés, les exports et les
URI de dossiers autorisés ; ne pas promettre la lecture de tous les formats.

## 14. Faire fonctionner le moteur d’extensions Seanime sur Android (#63)

**Disponible :** les extensions Seanime JS/TS fonctionnent déjà sur PC/Serveur
via `mini-racer` (V8), et un premier pont `WebView` hors écran existe dans
[`SeanimeJsBridge.kt`](../android/app/src/main/java/com/animan/app/SeanimeJsBridge.kt),
[`seanime_runtime.py`](../animelab/services/seanime_runtime.py) et
[`android_runtime.py`](../android_runtime.py).

**Objectif (#63) :** corriger l’interopérabilité Kotlin/Chaquopy (`@JvmStatic`
sur les points d’entrée de `SeanimeJsBridge`), stabiliser la sandbox `WebView`
hors écran sur Android API 29–35 y compris sur les builds release optimisés R8,
garantir la parité complète avec [`seanime_shim.js`](../animelab/services/seanime_shim.js)
(appels `fetch`, persistance `store`, transpilation TypeScript) et maintenir 100 %
du trafic réseau routé via `android_runtime.seanime_fetch`.

**Validation attendue :** `seanime_runtime.is_available()` retourne `True` sur
APK release optimisé, l’import, la recherche et la résolution de flux réussissent
sur Android, et des tests d’instrumentation valident une extension Seanime en CI.

## 15. Créer un moteur pour décoder et exécuter les extensions CloudStream sur PC et Android (#64, #65)

**Objectif :** prendre en charge les dépôts CloudStream (`repo.json` / `plugins.json`)
et les paquets `.cs3` sur toutes les plateformes :

- **Desktop / Serveur / PC (#64) :** inspecter les archives `.cs3`
  (`manifest.json` + `classes.dex`) et concevoir/implémenter un moteur sûr sur
  PC (extension du traducteur statique DEX vers recettes dans
  [`aniyomi_dex_parser.py`](../animelab/services/aniyomi_dex_parser.py) /
  [`recipe_runtime.py`](../animelab/services/recipe_runtime.py) ou interpréteur
  isolé) sans exécution de code arbitraire sur l’hôte, en routant toutes les
  requêtes HTTP via [`source_http.py`](../animelab/services/source_http.py).
- **Android (#65) :** exécuter nativement les plugins `.cs3` vérifiés dans le
  processus isolé `:extension-runtime` après approbation explicite et contrôle
  SHA-256, via une couche de compatibilité `com.lagradost.cloudstream3.*`
  pontée vers `IExtensionHttp`.

**Validation attendue :** courte RFC d’architecture pour les garde-fous PC,
métadonnées de dépôts/sources cohérentes entre PC et Android, tests hors ligne
sur `search` / `load` / `loadLinks`, et test d’instrumentation Android avec une
fixture `.cs3`.

## 16. Atelier de transcription audio en sous-titres sur PC — TurboScribe / Whisper (#67)

**Objectif (#67) :** dans l’espace **Outils** sur PC (Desktop/Serveur, #17),
permettre de générer des sous-titres synchronisés (`.srt`/`.vtt`/`.ass`) à
partir de la piste audio d’un épisode téléchargé grâce à l’extraction FFmpeg
([`media_tools.py`](../animelab/media_tools.py),
[`output_processor.py`](../animelab/services/output_processor.py)) associée à
des moteurs de transcription modulaires :

- **Whisper local hors ligne** (`faster-whisper`, `whisper.cpp` ou binaire
  utilisateur) en dépendance optionnelle sans alourdir les paquets PyInstaller
  ni Android.
- **Workflows externes / TurboScribe** (export audio optimisé + réimport `.srt`
  guidé pour TurboScribe ou API compatibles Whisper avec clé personnelle BYOK).

Les tâches tournent en arrière-plan avec annulation possible et transmettent
directement le fichier généré vers l’Atelier de sous-titrage (#66).

**Validation attendue :** restriction explicite aux environnements PC, médias
originaux préservés, annulation propre des tâches longues et tests automatisés
avec moteurs simulés/fixtures.

## Autres issues ouvertes après la v0.2.0

- **Sauvegarde, Bibliothèque & Découverte :** #46 (export/import portable complet), #47 (migration d’une série entre sources), #48 (synchronisation AniList / MyAnimeList), #68 (ajout auto à la bibliothèque au clic sur une carte — `good first issue`), #75 (calendrier hebdomadaire de diffusion), #77 (scanner de dossiers locaux / NAS)
- **Lecteur vidéo & Navigation :** #49 (lecteurs externes mpv/VLC/Intent Android), #50 (Passer l’intro/outro & enchaînement auto), #51 (raccourcis clavier & Picture-in-Picture — `good first issue`), #72 (rendu natif `.ass`/`.ssa` via JASSUB/libass WASM), #73 (navigation D-Pad / télécommande / Android TV), #74 (Discord Rich Presence optionnel sur Desktop — `good first issue`)
- **Sources, Vérification WebView & Mises à jour :** #52 (santé des sources & diagnostics anonymisés), #53 (vérification périodique & notifications), #54 (mise à jour atomique Desktop, nettoyage du cache & option Wi-Fi uniquement), #69 (refonte vérification WebView système style Anikku/Mihon avec capture auto des cookies), #70 (vérification PC WebKitGTK/WebView2/WKWebView & repli Chromium)
- **Stockage, Nommage & Communauté :** #71 (invitation au groupe Telegram au premier lancement & section À propos — `good first issue`), #76 (tableau d’espace disque, seuil libre & nettoyage des épisodes vus), #78 (modèles de nommage Plex / Jellyfin / Kodi — `good first issue`)
- **Distribution, Android & Qualité :** #55 (validation matérielle macOS & `.dmg`), #56 (AppImage/Flatpak & installeur Windows), #57 (code-splitting Vite — `good first issue`), #58 (vérification automatique i18n en CI — `good first issue`), #59 (découpage des gros modules), #60 (actualisation de la feuille de route — `good first issue`), #79 (réduction de la taille de l’APK Android)

Les issues et premières tâches des seize chantiers sont regroupées dans le
[suivi des contributions #12](https://github.com/loeuf237/animelab/issues/12).

## Proposer une autre idée

Ces chantiers n’excluent aucune proposition pertinente. Décrivez le besoin,
un exemple d’usage, les plateformes concernées, les compromis et une première
étape vérifiable. Une refonte d’architecture doit expliquer les problèmes
qu’elle résout et comment migrer les données et comportements existants.

Les personnes qui testent, dessinent, traduisent et documentent sont aussi
bienvenues que celles qui écrivent le code. Prenez un périmètre que vous pouvez
valider et indiquez les points pour lesquels vous avez besoin d’aide.
