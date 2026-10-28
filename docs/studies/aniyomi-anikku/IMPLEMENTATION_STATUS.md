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
| E15 | Vrai host Android, API hôte à la référence amont, chargeur des classes des APK installés, signatures système, installateur et pont Python. | Preuve initiale Android 15 ci-dessous ; réception APK01–APK14, vrais hôtes et ARM64 encore à compléter. |
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
- Les premiers bancs Android 29/30 n'ont pas validé la réception ; correctifs
  et essais optimisés en cours. La preuve Android 35 ne les remplace pas.

## Réception restant obligatoire

Les six variantes déclarent des API 12–17 mais sont compilées contre l'ABI
actuelle. Elles ne prouvent pas toutes les anciennes ABI. Les vrais hôtes
Aniyomi/Anikku n'ont pas encore été exécutés pour APK02–APK04. Aucun résultat
sur téléphone ARM64 ni build optimisé n'est annoncé avant enregistrement.

Le téléphone SCV38 connecté a été identifié en lecture seule comme Android 10,
ARM64. Les tests prévus utilisent des applications/paquets de fixtures distincts.
Les APK sont construits par GitHub Actions, sans compilation locale.

Le contrat final reste [APK01–APK14](EXIGENCES_ANDROID_APK.md). Les lots
incomplets restent nécessaires ; une limite ou non-adoption provisoire
ne termine pas l'objectif Android.
