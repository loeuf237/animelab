# Registre d'implémentation

Mise à jour : 29 octobre 2026. L'exigence de véritables APK Android est obligatoire.
Ce registre distingue code écrit, tests sur fixtures et compatibilité avec les
applications/paquets réellement distribués. Il ne certifie pas une release.

## Fonctionnalités présentes

| Lots | Réalisation | Validation / limites |
| --- | --- | --- |
| E01–E02 | Migration 12 ; offres, installations, artefacts, sources, opérations et confiance séparées ; catalogue conservant versions/recettes et extensions retirées. | Régressions Python et suite complète ; identités natives de 64 bits transmises comme chaînes. |
| E03–E04 | Dépôts coexistants, activation indépendante, récupération avec erreurs partielles ; JSON/Protobuf/gzip et listes externes/index_v2 bornés. | Tests des formats, migrations circulaires et limites ; liens applicatifs restant à raccorder. |
| E05–E06 | VersionCode numérique ; clé annoncée/pending et approbation explicite ; inspection native des APK et confiance par package/version/signataires actuels. | Signataire multiple lié à tout son ensemble ; aucune authentification cryptographique d'index annoncée. Anciennes ABI réelles restant à tester. |
| E07 | Sérialisation par package ; lots avec succès/échecs/attentes séparés ; PackageInstaller, autorisations, confirmation, résultat système et annulation. | Régressions Python ; reçu Android vérifiant version/signataire. |
| E08–E10 | Fabriques multi-sources, stubs conservés, activations et préférences natives par source ; filtres et groupes récursifs. | Collisions, mémos et UI testés ; migration des anciennes références encore incomplète. |
| E11 | OkHttp par défaut relayé vers SourceHTTP, budgets corps/IPC, défis typés, annulation et délai du parent. | Même UID : séparation de crash, **aucun bac à sable**. Sockets/accès directs possibles pour du code approuvé. Isolation hostile non validée. |
| E12 | Détails/épisodes, saisons/relations, hébergeurs/vidéos ; métadonnées/mémos ; en-têtes privés, ressources HLS et sous-titres via capacités temporaires. | DASH avec en-têtes, audio externe et rendu ASS incomplets ; options de lecteur non admises ; pas d'admission implicite des torrents/serveurs locaux. |
| E13 | Panneaux dépôts et APK, états réels, import, approbation/révocation, désinstallation partagée, préférences et activation des sources. | Tests navigateur ; nettoyage ciblé et parcours avancés restant à compléter. |
| E14 | Archive d'identités/stubs ; artefacts optionnels vérifiés SHA-256 ; restauration sans confiance implicite. | Tests hors ligne, secrets/confiance exclus, chemins/empreintes ; recettes et préférences non secrètes complètes restant à intégrer. |
| E15 | Vrai host Android, API hôte à la référence amont, chargeur des classes des APK installés, signatures système, installateur et pont Python. | Banc optimisé validé sur Android 10/11/15 ; chargement de trois APK réels sur ARM64 acquis. Réception APK01–APK14 et parcours complet encore à terminer. |
| E16 | Moteur de recettes conservé sur bureau. | Prototype JVM non réalisé ; aucune promesse d'exécution APK sur Linux/Windows. |
| E17–E18 | Corpus synthétique, workflow dédié et artefacts ; moteur désactivé dans les builds release. | Adoption Android non prononcée tant que les critères obligatoires ne sont pas démontrés. |

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

Le contrat final reste [APK01–APK14](EXIGENCES_ANDROID_APK.md). Les lots
incomplets restent nécessaires ; une limite ou non-adoption provisoire
ne termine pas l'objectif Android.
