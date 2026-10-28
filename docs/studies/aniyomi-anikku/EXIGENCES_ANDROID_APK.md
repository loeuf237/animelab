# Exigence Android : véritables APK et interopérabilité Aniyomi/Anikku

**Décision utilisateur du 28 octobre 2026, préalable à l'implémentation.**

Ce document complète et, en cas de divergence, précise le [rapport](RAPPORT.md) et le [plan E01–E18](PLAN_IMPLEMENTATION.md). Le moteur Android de véritables extensions APK devient un **résultat obligatoire** du chantier. Un gestionnaire de recettes amélioré ne suffit pas à remplir cette exigence.

## 1. Résultat demandé

Dans la variante Android d'AnimeLab :

1. Installer une extension signifie soumettre son **APK original** à l'installateur de paquets Android, puis vérifier le résultat d'installation effectif. Le paquet doit être visible dans `PackageManager` et dans les informations d'applications d'Android lorsqu'il y est présenté par le système.
2. L'APK conserve son package, son identité de signature et sa version ; AnimeLab ne le reconditionne pas, ne le resigne pas et ne le remplace pas par une recette.
3. Une extension anime déjà installée comme paquet Android par Aniyomi ou Anikku est détectée et peut être chargée par AnimeLab, dans le même profil Android, sans réinstallation ni modification de son APK.
4. Les classes et fabriques de l'extension sont réellement exécutées via leur API ; les sources, préférences, filtres et fonctions vidéo ne sont pas simulés à partir de constantes DEX.
5. Réciproquement, les APK installés par AnimeLab restent des paquets partagés standards que les autres hôtes peuvent détecter, sous réserve que chacun supporte leur API et approuve leur signataire.

La vérification de confiance propre à AnimeLab reste nécessaire : un APK détecté n'est pas automatiquement approuvé parce qu'une autre application l'a installé. « Directement compatible » signifie réutilisable sans portage ni transformation du paquet ; cela n'importe pas les sessions ou approbations privées d'un autre hôte.

## 2. État actuel vérifié

Au commit étudié `75c84ec` :

- `extension_service.py` télécharge des APK comme données et génère des `SourceRecipe` ; il ne demande pas leur installation comme paquets Android.
- Le manifeste `android/app/src/main/AndroidManifest.xml` ne déclare pas de permission `REQUEST_INSTALL_PACKAGES` ni de mécanisme de visibilité de l'ensemble des extensions installées.
- Les classes Android examinées ne contiennent pas de chargeur `PathClassLoader`/`DexClassLoader` d'extensions ni de registre de leurs sources natives.
- Le projet cible Android 35 et son minimum est Android 29 : la visibilité des paquets et les règles récentes de chargement de code doivent être traitées explicitement.

Il n'est donc pas possible de déclarer cette compatibilité déjà acquise. Les vérifications de structure DEX et les tests Python du rapport ne la démontrent pas.

## 3. Deux emplacements à distinguer

| Cas | Résultat exigé | Limite technique |
| --- | --- | --- |
| Extension installée par l'installateur Android, depuis Aniyomi ou Anikku | Découverte et chargement direct dans AnimeLab après validation de confiance/API. | Même appareil et profil Android, paquet visible et API compatible. |
| APK obtenu depuis un dépôt ou un fichier choisi par l'utilisateur | Installation Android par AnimeLab puis découverte/chargement. | L'utilisateur autorise l'installation depuis AnimeLab et confirme ce qu'Android demande. |
| Extension stockée seulement dans le répertoire privé d'Aniyomi/Anikku | Importer un APK exporté ou télécharger le même APK depuis sa provenance, puis l'installer. | AnimeLab ne peut pas lire directement les fichiers privés d'une autre application. |
| Installation privée proposée en option par AnimeLab | Charger de vrais APK vérifiés dans son stockage ; l'étiqueter clairement comme privée. | Ne remplace pas le parcours partagé demandé et n'est pas annoncée comme visible par les autres hôtes. |

Les loaders amont distinguent déjà les paquets partagés des fichiers `.ext` de leur stockage privé : [Aniyomi, chargement des extensions](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/extension/anime/util/AnimeExtensionLoader.kt), [Anikku, chargement des extensions](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/tachiyomi/extension/util/ExtensionLoader.kt). Le stockage interne est protégé entre applications par [Android](https://developer.android.com/training/data-storage/app-specific).

Ni les autorisations de stockage ordinaires ni la seule installation d'Aniyomi ou d'Anikku ne rendent leurs répertoires privés partageables. Il ne faut pas demander un accès root pour remplir le parcours standard.

## 4. Installation réelle et suivi des paquets

### 4.1 Service d'installation Android

Le backend Android du gestionnaire doit :

- vérifier l'APK et sa provenance avant de préparer une session d'installation ;
- utiliser `PackageInstaller` pour le paquet original, avec les autorisations et confirmations du système ;
- distinguer téléchargement terminé, attente utilisateur, installation effective, annulation et erreur ;
- relire le `PackageInfo` réellement installé et vérifier package, versionCode et signature ;
- ne marquer « installé » qu'après confirmation de l'état Android ;
- traiter une installation déjà présente comme un cas de réutilisation, pas comme une obligation de réinstallation.

`PackageInstaller` gère les sessions d'installation et leurs résultats : [référence Android](https://developer.android.com/reference/android/content/pm/PackageInstaller). Le choix ne repose pas sur une exécution root ou Shizuku ; ces modes resteraient des options distinctes si un besoin ultérieur le justifie.

### 4.2 Découverte inter-applications

La découverte doit examiner les packages visibles et identifier les extensions anime par leur fonctionnalité et leurs métadonnées. Une déclaration ne listant que les packages des applications Aniyomi et Anikku ne suffirait pas : les extensions sont des paquets indépendants dont les noms varient.

Déterminer le mécanisme de visibilité nécessaire pour la distribution Android visée, et le vérifier sur Android 11+. Si la découverte de packages d'extension arbitraires exige `QUERY_ALL_PACKAGES`, cette permission doit être justifiée par la fonction d'interopérabilité et testée ; un simple `<queries>` couvrant quelques noms connus ne doit pas être présenté comme universel. [Visibilité des paquets Android](https://developer.android.com/training/package-visibility/declaring).

Surveiller les ajouts, remplacements et suppressions de paquets, revalider au démarrage et à la reprise de l'application, et réconcilier les installations sans effacer les références de bibliothèque. L'API doit indiquer l'emplacement partagé ou privé et le package réel.

### 4.3 Effets partagés

Mettre à jour ou désinstaller un paquet Android partagé affecte les autres applications qui l'utilisent. L'interface doit l'expliquer au moment de ces actions. Désactiver une source seulement dans AnimeLab n'a pas cet effet.

Un retour arrière fonctionnel après une mise à jour partagée ne doit pas supposer qu'Android autorise un downgrade ordinaire. En cas de refus système, conserver les preuves et proposer une récupération explicite ; ne pas afficher un rollback réussi. L'activation de nos données et registres doit rester cohérente même si le paquet évolue à l'extérieur d'AnimeLab.

## 5. Moteur Android obligatoire

Installer le fichier ne suffit pas. Le runtime doit fournir les classes et services attendus par les extensions, avec leurs véritables noms et signatures publiques :

- `AnimeSource`, `AnimeCatalogueSource`, `AnimeHttpSource`, sources parsées, configurables et fabriques ;
- modèles d'anime, épisodes, saisons, relations, filtres, hébergeurs et vidéos ;
- compatibilité des appels historiques RxJava et des appels Kotlin suspendus nécessaires ;
- services d'injection utilisés par les APK, client OkHttp, parsing HTML/JSON et préférences ;
- JavaScript, résolveurs et ressources requis par le périmètre validé ;
- conversions contrôlées entre les objets Kotlin réels, le moteur Python et l'interface Vue.

La cible fonctionnelle couvre l'union des API des versions étudiées : **12, 13, 14, 15, 16 et 17**, avec cas de compatibilité pour chaque niveau annoncé. Il ne faut pas simplement charger l'API la plus récente et supposer que l'ancienne ABI existe encore : les constructeurs, interfaces, types et méthodes doivent être vérifiés.

L'identité des sources et la totalité des sources d'une fabrique doivent être conservées. Les préférences et les cookies sont ceux d'AnimeLab ; ils ne sont pas implicitement copiés d'Aniyomi ou d'Anikku.

Les bibliothèques natives, exigences d'OS/ABI et dépendances propres à certains APK doivent être testées. Une extension incompatible avec l'appareil ou nécessitant une API future doit être signalée ; elle ne peut pas être déclarée compatible sur la seule base de son nom de package.

Sur Android 14+ ciblé par notre application, les fichiers de code dynamiquement chargés doivent respecter les règles de lecture seule ; toute copie privée ou cache de code doit les appliquer. [Règles Android de chargement dynamique](https://developer.android.com/about/versions/14/behavior-changes-14#safer-dynamic-code-loading).

Le choix d'isolation et d'IPC doit être compatible avec ces fonctions et validé. Il reste interdit de considérer un processus au même UID comme une frontière de sécurité démontrée.

## 6. Tests de réception obligatoires

Ces scénarios doivent produire des artifacts de preuve datés, avec versions des hôtes, version Android, ABI, package/versionCode/API et empreinte du signataire. Aucun cookie ni identifiant personnel ne doit y figurer.

| ID | Scénario | Preuve attendue |
| --- | --- | --- |
| APK01 | Installer depuis AnimeLab un APK d'extension original signé. | Succès système, `PackageInfo` correspondant et source exécutable ; identité de signature conservée. |
| APK02 | Installer l'extension via Aniyomi en mode partagé, puis ouvrir AnimeLab. | Détection et chargement sans nouvel appel d'installation ni transformation du paquet. |
| APK03 | Même scénario via Anikku. | Même critère de réutilisation directe. |
| APK04 | Installer via AnimeLab, puis ouvrir chacun des autres hôtes compatibles avec l'API. | Source détectable et utilisable après leurs contrôles de confiance. |
| APK05 | Mettre à jour le paquet via un autre hôte. | AnimeLab observe la vraie version, revalide la confiance et recharge sans état mélangeant ancien et nouveau code. |
| APK06 | Supprimer le paquet partagé hors d'AnimeLab. | Source indisponible/stub, bibliothèque et téléchargements conservés. |
| APK07 | Paquet déjà présent avec autre signataire ou version plus récente. | Aucun remplacement silencieux, aucune fausse annonce d'installation ou downgrade réussi. |
| APK08 | Annuler la confirmation Android ou refuser l'autorisation d'installation. | Opération annulée/échouée clairement, aucun état installé inventé. |
| APK09 | APK à fabrique exposant plusieurs sources/langues. | Toutes les sources ont leur identité, préférences et actions propres. |
| APK10 | APK de test calculant un résultat à l'exécution, avec préférences et JavaScript. | Résultat calculé et callback effectivement exécutés ; aucune substitution par extraction de constantes. |
| APK11 | Parcours complet catalogue → recherche/filtres → détails → épisodes → hébergeur → vidéo/pistes. | Parité sur fixtures et essai réel autorisé, en distinguant les pannes du site des incompatibilités du moteur. |
| APK12 | Redémarrage Android/application et build optimisé de distribution. | Redécouverte, conservation des références et absence de classes supprimées à tort par R8/ProGuard. |
| APK13 | Extension privée dans un autre hôte. | Limite expliquée, import par APK exporté ou téléchargé ; aucune prétention de lecture du stockage privé. |
| APK14 | APK de chaque niveau d'API annoncé et de chaque famille fonctionnelle du corpus. | Matrice explicite, erreurs de liaison absentes ou incompatibilités bloquantes documentées avant validation finale. |

Répéter les scénarios pertinents sur Android 10, Android 11+ pour la visibilité, Android 14+ pour les règles récentes et sur un appareil ARM64 supporté. L'appareil de test et le build AnimeLab doivent être compatibles ; une validation de manifeste ou de ressources seule ne vaut pas test d'exécution.

Les constructions APK et les campagnes d'émulateurs passent par GitHub Actions. L'installation sur appareil pour les essais sera une étape distincte, avec conservation des données utilisateur et versions documentées.

## 7. Condition de fin et engagement de compatibilité

Le chantier Android ne peut être déclaré terminé sur un résultat limité aux recettes ou à un prototype non adopté. E15 doit aboutir à la prise en charge réelle des paquets partagés et au contrat de compatibilité ci-dessus.

Un échec de faisabilité ou un APK incompatible impose un constat et un travail supplémentaire ou une décision de périmètre explicite avec l'utilisateur ; il ne satisfait pas automatiquement l'objectif initial. La validation finale doit publier le corpus exécuté et les incompatibilités restantes. L'affirmation « tous les APK Aniyomi/Anikku fonctionnent » ne peut pas être déduite d'une inspection statique ni d'un échantillon réduit.

Ce document fixe une obligation de résultat et ses preuves. **Il ne certifie pas que l'implémentation actuelle la respecte déjà.**
