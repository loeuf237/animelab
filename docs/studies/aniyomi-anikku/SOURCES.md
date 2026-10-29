# Sources et traçabilité

Consultation du 28 octobre 2026. Les URL ci-dessous pointent vers des commits figés ; elles ne suivent pas une branche mouvante. Le [manifest JSON](sources.json) inventorie les 86 fichiers amont récupérés et leurs empreintes de texte canonique.

Les extraits amont ont été conservés temporairement pour l'analyse ; leur code n'est pas incorporé à AnimeLab par ce dossier d'étude. Les conclusions sont des synthèses de lecture, pas des garanties d'exécution sur appareil.

## Références principales

| ID | Projet | Rôle | Fichier figé |
| --- | --- | --- | --- |
| AY-STORE | aniyomiorg/aniyomi | Lecture des stores legacy/JSON/Protobuf/gzip | [AnimeExtensionStoreService.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/java/mihon/data/extension/anime/service/AnimeExtensionStoreService.kt) |
| AY-REPOS | aniyomiorg/aniyomi | Agregation et actualisation des stores | [AnimeExtensionStoreRepositoryImpl.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/java/mihon/data/extension/anime/repository/AnimeExtensionStoreRepositoryImpl.kt) |
| AY-SCHEMA | aniyomiorg/aniyomi | Persistance des stores | [extension_store.sq](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/sqldelightanime/dataanime/extension_store.sq) |
| AY-INDEX | aniyomiorg/aniyomi | Modele du nouvel index | [NetworkAnimeExtensionStore.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/java/mihon/data/extension/anime/model/NetworkAnimeExtensionStore.kt) |
| AY-LEGACY | aniyomiorg/aniyomi | Metadonnees legacy et index_v2 | [NetworkLegacyAnimeExtensionRepo.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/java/mihon/data/extension/anime/model/NetworkLegacyAnimeExtensionRepo.kt) |
| AY-LEGACY-EXT | aniyomiorg/aniyomi | Conversion des anciennes entrees | [NetworkLegacyAnimeExtension.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/data/src/main/java/mihon/data/extension/anime/model/NetworkLegacyAnimeExtension.kt) |
| AY-LOADER | aniyomiorg/aniyomi | Chargement APK, API, signatures, prive/partage | [AnimeExtensionLoader.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/util/AnimeExtensionLoader.kt) |
| AY-TRUST | aniyomiorg/aniyomi | Confiance par depot ou version signee | [TrustAnimeExtension.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/domain/extension/anime/interactor/TrustAnimeExtension.kt) |
| AY-MANAGER | aniyomiorg/aniyomi | Registre, etats et mises a jour | [AnimeExtensionManager.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/AnimeExtensionManager.kt) |
| AY-UPDATE | aniyomiorg/aniyomi | Detection des nouvelles versions | [AnimeExtensionApi.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/api/AnimeExtensionApi.kt) |
| AY-INSTALL | aniyomiorg/aniyomi | Telechargement et installation | [AnimeExtensionInstaller.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/util/AnimeExtensionInstaller.kt) |
| AY-QUEUE | aniyomiorg/aniyomi | File d'installation et annulation | [InstallerAnime.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/installer/InstallerAnime.kt) |
| AY-MODES | aniyomiorg/aniyomi | Quatre modes d'installation | [BasePreferences.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/domain/base/BasePreferences.kt) |
| AY-MODE-CHECK | aniyomiorg/aniyomi | Selection et repli des installateurs | [ExtensionInstallerPreference.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/domain/base/ExtensionInstallerPreference.kt) |
| AY-SOURCES | aniyomiorg/aniyomi | Registre de sources et stubs | [AndroidAnimeSourceManager.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/source/anime/AndroidAnimeSourceManager.kt) |
| AY-HTTP | aniyomiorg/aniyomi | Identite stable, reseau et appels des sources | [AnimeHttpSource.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/online/AnimeHttpSource.kt) |
| AY-SOURCE-API | aniyomiorg/aniyomi | Contrat des sources, saisons et relations | [AnimeSource.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/AnimeSource.kt) |
| AY-FILTER | aniyomiorg/aniyomi | Filtres types | [AnimeFilter.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/AnimeFilter.kt) |
| AY-PREFS-API | aniyomiorg/aniyomi | Preferences scopees par source | [ConfigurableAnimeSource.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/ConfigurableAnimeSource.kt) |
| AY-PREFS-UI | aniyomiorg/aniyomi | Construction de l'ecran de preferences | [AnimeSourcePreferencesScreen.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/ui/browse/anime/extension/details/AnimeSourcePreferencesScreen.kt) |
| AY-VIDEO | aniyomiorg/aniyomi | Contrat video, pistes et memos | [Video.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/Video.kt) |
| AY-HOSTER | aniyomiorg/aniyomi | Resolution des hebergeurs | [Hoster.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/Hoster.kt) |
| AY-HTTP-SERVER | aniyomiorg/aniyomi | Serveur HTTP fourni par une source | [HttpServer.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/HttpServer.kt) |
| AY-NETWORK | aniyomiorg/aniyomi | Client reseau partage | [NetworkHelper.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/NetworkHelper.kt) |
| AY-JS | aniyomiorg/aniyomi | Evaluation JavaScript QuickJS | [JavaScriptEngine.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/JavaScriptEngine.kt) |
| AY-CLASSLOADER | aniyomiorg/aniyomi | Ordre de resolution des classes | [ChildFirstPathClassLoader.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/util/system/ChildFirstPathClassLoader.kt) |
| AY-UI | aniyomiorg/aniyomi | Liste et actions groupees | [AnimeExtensionsScreenModel.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/ui/browse/anime/extension/AnimeExtensionsScreenModel.kt) |
| AY-DETAILS | aniyomiorg/aniyomi | Details et nettoyage des cookies | [AnimeExtensionDetailsScreenModel.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/ui/browse/anime/extension/details/AnimeExtensionDetailsScreenModel.kt) |
| AY-SOURCE-PREFS | aniyomiorg/aniyomi | Langues, masquage, favoris et incognito | [SourcePreferences.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/domain/source/service/SourcePreferences.kt) |
| AY-BACKUP | aniyomiorg/aniyomi | Sauvegarde des stores | [AnimeExtensionStoresBackupCreator.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/data/backup/create/creators/AnimeExtensionStoresBackupCreator.kt) |
| AY-BACKUP-SOURCE | aniyomiorg/aniyomi | Sauvegarde des identites de sources | [AnimeSourcesBackupCreator.kt](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/data/backup/create/creators/AnimeSourcesBackupCreator.kt) |
| AY-MANIFEST | aniyomiorg/aniyomi | Permissions et liens d'import | [AndroidManifest.xml](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/AndroidManifest.xml) |
| AK-REPO | komikku-app/anikku | Lecture de repo.json | [ExtensionRepoService.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/domain/src/main/java/mihon/domain/extensionrepo/service/ExtensionRepoService.kt) |
| AK-CREATE | komikku-app/anikku | Validation URL et doublons | [CreateExtensionRepo.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/domain/src/main/java/mihon/domain/extensionrepo/interactor/CreateExtensionRepo.kt) |
| AK-REPO-UPDATE | komikku-app/anikku | Conservation de l'empreinte a l'actualisation | [UpdateExtensionRepo.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/domain/src/main/java/mihon/domain/extensionrepo/interactor/UpdateExtensionRepo.kt) |
| AK-SCHEMA | komikku-app/anikku | Unicite des empreintes | [extension_repos.sq](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/data/src/main/sqldelight/tachiyomi/data/extension_repos.sq) |
| AK-UPDATE | komikku-app/anikku | Catalogues, depots desactives et filtre API | [ExtensionApi.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/tachiyomi/extension/api/ExtensionApi.kt) |
| AK-LOADER | komikku-app/anikku | Chargement et plage d'API | [ExtensionLoader.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/tachiyomi/extension/util/ExtensionLoader.kt) |
| AK-TRUST | komikku-app/anikku | Confiance et exceptions integrees | [TrustExtension.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/domain/extension/interactor/TrustExtension.kt) |
| AK-MANAGER | komikku-app/anikku | Candidats identifies par package et signature | [ExtensionManager.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/tachiyomi/extension/ExtensionManager.kt) |
| AK-PREFS | komikku-app/anikku | Depots desactives et preferences | [SourcePreferences.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/domain/source/service/SourcePreferences.kt) |
| AK-VIDEO | komikku-app/anikku | Contrat video de la branche Anikku | [Video.kt](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/Video.kt) |
| LIB-INDEX | aniyomiorg/extensions-lib | Schema Protobuf officiel | [index.proto](https://github.com/aniyomiorg/extensions-lib/blob/971ce96e76202bb35432fe71f92553e3ae40d01d/index/index.proto) |
| LIB-README | aniyomiorg/extensions-lib | JSON/Protobuf et compression facultative | [README.md](https://github.com/aniyomiorg/extensions-lib/blob/971ce96e76202bb35432fe71f92553e3ae40d01d/index/README.md) |

## Code AnimeLab examiné

État `75c84ecac74454db5f1a95c6dfa81a699e2ffcc9`. Les chemins ci-dessous sont relatifs à la racine du dépôt.

- [animelab/services/extension_service.py](../../../animelab/services/extension_service.py) — Import, visibilité, activation, réconciliation, mises à jour et cache APK.
- [animelab/services/aniyomi_dex_parser.py](../../../animelab/services/aniyomi_dex_parser.py) — Extraction DEX et modèle SourceRecipe.
- [animelab/services/aniyomi_container.py](../../../animelab/services/aniyomi_container.py) — Source exécutable déclarative et identifiant-package.
- [animelab/services/recipe_runtime.py](../../../animelab/services/recipe_runtime.py) — Interprétation des plans sérialisés.
- [animelab/services/recipe_plans.py](../../../animelab/services/recipe_plans.py) — Plans et corrections de compatibilité.
- [animelab/services/extension_observability.py](../../../animelab/services/extension_observability.py) — Historique des recettes et santé par opération.
- [animelab/services/source_http.py](../../../animelab/services/source_http.py) — Transport, sessions et vérifications.
- [animelab/migrations.py](../../../animelab/migrations.py) — Schéma des dépôts, extensions et révisions.
- [animelab/routers/extensions.py](../../../animelab/routers/extensions.py) — Actions publiques de gestion.
- [frontend/src/views/ExtensionsView.vue](../../../frontend/src/views/ExtensionsView.vue) — Interface de gestion des extensions.
- [android/app/src/main/java/com/animan/app/VerificationBridge.kt](../../../android/app/src/main/java/com/animan/app/VerificationBridge.kt) — Pont WebView existant.
- [docs/extension-recipes.md](../../../docs/extension-recipes.md) — Limites déclarées du moteur de recettes.
- [tests/test_extension_update_regressions.py](../../../tests/test_extension_update_regressions.py) — Échecs de mise à jour conservant la version installée.
- [tests/test_imported_extensions_regression.py](../../../tests/test_imported_extensions_regression.py) — Régressions de protocoles et de formats.
- [tests/test_extension_observability.py](../../../tests/test_extension_observability.py) — Diagnostics et révisions.

## Documentation officielle complémentaire

- [Aniyomi : retrait de la liste d'extensions, 5 juillet 2024](https://aniyomi.org/news/2024-07-05-extensions-removal).
- [Anikku : annonce équivalente](https://anikku-app.github.io/news/2024-07-05-extensions-removal).
- [Guide de démarrage Aniyomi](https://aniyomi.org/docs/guides/getting-started).
- [FAQ des extensions Aniyomi](https://aniyomi.org/docs/faq/browse/extensions).
- [Guide de démarrage Anikku](https://anikku-app.github.io/docs/guides/getting-started).
- [FAQ des extensions Anikku](https://anikku-app.github.io/docs/faq/browse/extensions).
- [Documentation API extensions-lib](https://extension-docs.aniyomi.org/).

Les pages de téléchargement, changelogs et sites peuvent évoluer ou présenter un décalage entre sections. Pour les versions et les comportements techniques de cette étude, les commits et fichiers référencés font foi.

## État des projets et comparaison des versions

- [Aniyomi : release étudiée](https://github.com/aniyomiorg/aniyomi/releases/tag/v0.18.2.1).
- [Anikku : release stable de référence](https://github.com/komikku-app/anikku/releases/tag/v0.2.0).
- [Anikku : comparaison du tag avec le commit étudié](https://github.com/komikku-app/anikku/compare/v0.2.0...6e35b41f0cc7e375d15527bd61375435f998685a).

Les cinq fichiers Anikku contrôlés au tag stable sont listés dans `stableCrossChecks` du manifest. Leur comparaison est limitée à ces fichiers ; les autres comportements sont attribués au commit étudié.

## Complément : exigences Android APK

Pour le [contrat Android](EXIGENCES_ANDROID_APK.md), le manifeste et la configuration Gradle d'AnimeLab ont également été examinés : installation absente, visibilité non déclarée, minSdk 29 et targetSdk 35 au commit étudié. Les références Android suivantes ont été vérifiées le 28 octobre 2026 :

- [Visibilité des paquets](https://developer.android.com/training/package-visibility/declaring).
- [Stockage privé des applications](https://developer.android.com/training/data-storage/app-specific).
- [Chargement dynamique ciblant Android 14+](https://developer.android.com/about/versions/14/behavior-changes-14#safer-dynamic-code-loading).
- [Sessions et résultats de PackageInstaller](https://developer.android.com/reference/android/content/pm/PackageInstaller).

## Résultats des vérifications locales

Les tests utilisent le code du checkout et des fixtures synthétiques, avec HOME/base/cache temporaires. Ils ne prouvent ni le comportement de tous les APK communautaires, ni leur innocuité, ni la disponibilité de leurs sites. Les résultats et commandes figurent dans [validation.json](validation.json) et [verify_current.py](verify_current.py).
