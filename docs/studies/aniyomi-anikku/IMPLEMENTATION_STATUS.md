# Registre d'implémentation

Mise à jour : 29 octobre 2026. L'exigence de véritables APK Android est obligatoire.
Ce registre distingue code écrit, tests sur fixtures et compatibilité avec les
applications/paquets réellement distribués. Il ne certifie pas une release.

L'[étude WebView et sessions](WEBVIEW_SESSIONS.md) du 29 octobre complète ce
registre : audit de concurrence, différences entre les deux hôtes, suspension
SourceHTTP pendant la fenêtre et limites du partage de cookies entre processus.

## Fonctionnalités présentes

| Lots | Réalisation | Validation / limites |
| --- | --- | --- |
| E01–E02 | Migration 12 ; offres, installations, artefacts, sources, opérations et confiance séparées ; catalogue conservant versions/recettes et extensions retirées. | Régressions Python et suite complète ; identités natives de 64 bits transmises comme chaînes. |
| E03–E04 | Dépôts coexistants, activation indépendante, récupération avec erreurs partielles ; JSON/Protobuf/gzip et listes externes/index_v2 bornés. | Tests des formats, migrations circulaires et limites ; liens applicatifs restant à raccorder. |
| E05–E06 | VersionCode numérique ; clé annoncée/pending et approbation explicite ; inspection native des APK et confiance par package/version/signataires actuels. | Signataire multiple lié à tout son ensemble ; aucune authentification cryptographique d'index annoncée. Anciennes ABI réelles restant à tester. |
| E07 | Sérialisation par package ; lots avec succès/échecs/attentes séparés ; PackageInstaller, autorisations, confirmation, résultat système et annulation. | Régressions Python ; reçu Android vérifiant version/signataire. |
| E08–E10 | Fabriques multi-sources, stubs conservés, activations et préférences natives par source ; filtres et groupes récursifs. Migration 13 : références originales/mémos privés persistants, quota transactionnel sans éviction silencieuse. | Reprise après redémarrage et désinstallation/réinstallation testée en Python ; anciennes références non enregistrées avant cette migration encore incomplètes. |
| E11 | OkHttp par défaut relayé vers SourceHTTP, budgets corps/IPC, défis typés, annulation et délai du parent. | Même UID : séparation de crash, **aucun bac à sable**. Sockets/accès directs possibles pour du code approuvé. Isolation hostile non validée. |
| E12 | Détails/épisodes, saisons/relations, hébergeurs/vidéos ; métadonnées/mémos ; en-têtes privés, ressources HLS et sous-titres via capacités temporaires. | DASH avec en-têtes, audio externe et rendu ASS incomplets ; options de lecteur non admises ; pas d'admission implicite des torrents/serveurs locaux. |
| E13 | Panneaux dépôts et APK, états réels, import, approbation/révocation, désinstallation partagée, préférences et activation des sources. | Tests navigateur ; nettoyage ciblé et parcours avancés restant à compléter. |
| E14 | Archive d'identités/stubs ; artefacts optionnels vérifiés SHA-256 ; restauration sans confiance implicite. | Tests hors ligne, secrets/confiance exclus, chemins/empreintes ; recettes et préférences non secrètes complètes restant à intégrer. |
| E15 | Vrai host Android, API hôte à la référence amont, chargeur des classes des APK installés, signatures système, installateur et pont Python. | Banc optimisé validé sur Android 10/11/15 ; chargement de trois APK réels sur ARM64 acquis. Réception APK01–APK14 et parcours complet encore à terminer. |
| E16 | Moteur de recettes conservé sur bureau. | Prototype JVM non réalisé ; aucune promesse d'exécution APK sur Linux/Windows. |
| E17–E18 | Corpus synthétique, workflow dédié et artefacts ; moteur désactivé par défaut dans les builds release. | À la demande explicite de l'utilisateur, `v0.1.6-beta.2` active le moteur expérimental ; l'adoption en production reste non prononcée tant que les critères obligatoires ne sont pas démontrés. |

## Résultats acquis

- Suite Python locale : **961 réussis, 5 ignorés**, deux avertissements de dépendances.
- Nouveaux contrats ciblés : **42 réussis**, inclus dans la suite complète.
- Frontend : compilation/typecheck/lint réussis ; **37 tests unitaires** réussis.
- Navigateur : approbation annulée puis acceptée et filtres natifs imbriqués
  avec identifiant supérieur à 2^53/rechargement, **2 essais réussis**.
  Les deux essais existants de filtres aux largeurs 390 et 1440 px passent aussi.
- Compilation Kotlin du runtime et du banc APK réussie dans GitHub Actions.
- Workflow [40788401486](https://github.com/loeuf237/animelab/actions/runs/40788401486),
  job Android 35 : six APK installés via PackageInstaller puis exécutés,
  fabriques FR/EN, résultat calculé, QuickJS, filtres, préférences séparées,
  détails, hébergeur et sous-titres. Banc **debug**, ABI hôte actuelle.
- Au commit `16c5cac`, les deux workflows sont entièrement réussis :
  [CI générale, 7 jobs](https://github.com/loeuf237/animelab/actions/runs/40798123649)
  et [runtime Android, 5 jobs](https://github.com/loeuf237/animelab/actions/runs/40798123645).
  Le second construit l'application ARM64 optimisée et exécute les six APK
  synthétiques sur Android 10, 11 et 15 (API 29/30/35). Les tests couvrent
  aussi arrêt du worker bloqué, reprise des préférences et révocation.
- Sur le SCV38 Android 10 ARM64, le banc optimisé a chargé les classes/fabriques
  des APK AnimeSama, FRAnime et AniSama déjà installés par Aniyomi 0.18.2.1,
  avec découverte de leurs sources, sans réinstallation ni transformation.
  Voir la [preuve enregistrée](evidence/android-arm64-shared-apks-2026-10-29.json).
  Cela ne prouve pas encore leurs recherches, détails ou vidéos dans AnimeLab.
- L'application AnimeLab ARM64 optimisée `16c5cac`, installée séparément sous
  `com.animan.app.a11test`, a réussi le parcours serveur Python → APK API17 →
  catalogue calculé, préférences, filtres et QuickJS sur le SCV38.
  Voir la [preuve Python/Android](evidence/android-arm64-python-integration-2026-10-29.json).
  Pour ce premier essai, la fixture originale était préinstallée par ADB :
  l'installation depuis l'API AnimeLab et les sites réels restent à valider.
- Sur le build optimisé `6ebb32b`, le SCV38 a ensuite réussi **l'installation
  depuis l'API Python d'AnimeLab via PackageInstaller**, puis la comparaison des
  octets réellement installés et l'exécution catalogue/préférences/filtres/QuickJS.
  Voir la [preuve APK01 sur ARM64](evidence/android-arm64-package-installer-2026-10-29.json).
  Il s'agit d'un APK synthétique original, pas d'une extension communautaire transformée.
- Les deux workflows de `6ebb32b` sont entièrement réussis :
  [7 jobs généraux](https://github.com/loeuf237/animelab/actions/runs/40802379189),
  [5 jobs Android](https://github.com/loeuf237/animelab/actions/runs/40802379208).
  Le timeout Windows de l'exécution précédente ne s'est pas reproduit.
- Premier parcours communautaire dans l'application complète : AnimeSama renvoie
  deux résultats de catalogue et une fiche, sans épisodes sur la première entrée ;
  AniSama rencontre une erreur réseau ; FRAnime est arrêté par un appel de
  préférences que cette source ne déclare pas. Ce dernier est une hypothèse
  erronée du test, pas une incompatibilité démontrée de FRAnime.
  Voir la [preuve partielle](evidence/android-arm64-community-initial-2026-10-29.json)
  et l'[inspection statique FRAnime](evidence/franime-preferences-static-2026-10-29.json).
  Le test est corrigé pour respecter cette capacité et essayer au maximum trois
  entrées de catalogue, sans ignorer leurs erreurs réseau/runtime.
- Le correctif `a1c364b` réussit les cinq jobs de la
  [matrice Android](https://github.com/loeuf237/animelab/actions/runs/40801273325)
  (dont annulation définitive et corrélation du callback à la session).
  Dans la [CI générale](https://github.com/loeuf237/animelab/actions/runs/40801273248),
  les six autres jobs réussissent ; le job Windows échoue par expiration du
  test d'ouverture WebView2 à 60 secondes, après réussite des tests de régression.
  Cette exécution n'est donc pas annoncée entièrement verte.

## Réception restant obligatoire

Les six variantes déclarent des API 12–17 mais sont compilées contre l'ABI
actuelle. Elles ne prouvent pas toutes les anciennes ABI. Les vrais hôtes
Aniyomi/Anikku n'ont pas encore été exécutés dans un parcours réciproque
complet pour APK02–APK04. La preuve ARM64 ci-dessus reste limitée au
chargement et à la découverte dans une application de validation distincte.

Le téléphone SCV38 connecté a été identifié en lecture seule comme Android 10,
ARM64. Les tests prévus utilisent des applications/paquets de fixtures distincts.
Les APK sont construits par GitHub Actions, sans compilation locale.

Le dernier échec d'installation physique a été reproduit avec la confirmation
Android affichée et acceptée : Android refuse la signature d'une ancienne
fixture `animelabfixture.api12`, identifiée par son SHA-256 comme issue du
banc `2796d8a`. Il ne démontre pas un blocage d'affichage de la confirmation.
Seul ce paquet synthétique identifié est supprimé pour reprendre la campagne ;
les extensions communautaires et les données des autres hôtes sont conservées.

L'analyse statique du véritable APK AnimeSama constate un client dérivé avec
`followRedirects(false)` et un intercepteur d'application qui suit les redirections
et met à jour l'adresse de base. Le premier broker court-circuitait ces callbacks.
Un adaptateur de chaîne OkHttp 5.4 les conserve désormais. Les cinq jobs du
[workflow Android de `64c591a`](https://github.com/loeuf237/animelab/actions/runs/40805875973)
réussissent, y compris le test dédié des clients dérivés sur API 29/30/35.
Le premier essai API 35 avait échoué avant installation sur l'autorisation du banc ;
cet échec ne s'est pas reproduit lors de la réexécution. La
[CI générale correspondante](https://github.com/loeuf237/animelab/actions/runs/40805875978)
réussit également.

Le nouveau parcours physique `64c591a` est consigné dans la
[preuve communautaire après correction des redirections](evidence/android-arm64-community-redirects-2026-10-29.json).
L'instrumentation réussit, mais **zéro parcours complet métadonnées → vidéo** :
AnimeSama fournit deux entrées, une fiche sans épisodes puis demande une vérification ;
FRAnime et AniSama échouent au catalogue par `source_network_error`.
Le test respecte désormais l'absence de préférences de FRAnime.
La fenêtre de vérification AnimeSama affiche « You are unable to access anime-sama.to ».
Ces résultats ne permettent ni d'attribuer tous les échecs au site, ni de valider
la compatibilité vidéo. Aucun de ces trois APK n'a été réinstallé.
Les intercepteurs **réseau** nécessitant une connexion/TLS native ne sont pas
émulés : une erreur d'opération indisponible remplace leur omission silencieuse.
La gestion commune des cookies après vérification navigateur et les options de
transport propres aux extensions restent à couvrir avant adoption générale.

## Correctifs de reprise et de contrat en cours de réception

La migration 13 conserve par source/type/URL publique les URL originales et les
mémos nécessaires aux prochains callbacks, y compris après arrêt du processus.
Le quota est global (64 Mio et 250 000 références), avec bornes UTF-8/UTF-16 par
objet ; un lot dépassant le quota est entièrement annulé. Ces données privées
ne sont pas incluses dans les sauvegardes de métadonnées. Leur portabilité
inter-appareils reste donc à réaliser pour E14.

Une désinstallation externe conserve l'intention d'activation ; réinstaller
le paquet ne réactive pas une source explicitement désactivée. Les mémos et
`internalData` ne sont plus exposés dans les réponses d'animés/épisodes, mais
restent disponibles pour le moteur. Les opérations catalogue/saisons/relations
conservent aussi leurs références privées avant de répondre à l'interface.

Le codec accepte les fiches de détail dont les champs `lateinit` URL/titre ne
sont pas initialisés, en reprenant uniquement ces identités de la requête.
Les valeurs explicitement fournies restent intactes. Il conserve également les
champs optionnels nuls et les en-têtes vidéo absents. La fixture exerce un
véritable parseur de détail sans URL/titre, au lieu de masquer ce cas.

L'API des serveurs d'épisodes accepte l'identité de la source native et renvoie
uniquement les noms/qualités. Le test communautaire utilise les routes Python
serveurs/résolution média, plutôt que des appels JNI directs transportant les
mémos dans le client. Une erreur native typée reste identifiable ; un hébergeur
fonctionnel peut encore réussir si un autre échoue. Ces nouveaux changements
nécessitent leur propre CI et leur propre réception physique ; les preuves
`64c591a` ci-dessus ne les valident pas.

Le commit `e0718ea` de ces correctifs réussit la suite locale complète
(1 013 tests, 5 ignorés), puis les
[7 jobs généraux](https://github.com/loeuf237/animelab/actions/runs/40844963392)
et [5 jobs Android](https://github.com/loeuf237/animelab/actions/runs/40844963382).
La fixture de détail sans URL/titre réussit donc sur API 29/30/35.
L'application ARM64 complète est construite, mais ce commit n'a pas encore
été réceptionné physiquement sur le SCV38.

Le contrat final reste [APK01–APK14](EXIGENCES_ANDROID_APK.md). Les lots
incomplets restent nécessaires ; une limite ou non-adoption provisoire
ne termine pas l'objectif Android.
