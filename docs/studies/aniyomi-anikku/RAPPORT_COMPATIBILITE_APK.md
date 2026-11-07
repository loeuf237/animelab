# Modèle de rapport de compatibilité APK — Aniyomi / Anikku

Reusable report for one Android extension APK. The GitHub issue form is only
an intake summary: attach this filled matrix instead of opening a second form.
Status values are exactly `passed`, `failed`, `blocked` or `not-tested`.
A `blocked` row is not a success. Keep website blocks apart from runtime
incompatibilities, and desktop Python recipes apart from Android APK runs.
Remove serial numbers, cookies, tokens and signed URLs before publishing.
The [filled example](RAPPORT_COMPATIBILITE_APK_EXEMPLE.md) is synthetic: it
records a blocked catalogue and does not claim the extension works.

Ce fichier est un **modèle vierge**. Il ne consigne aucun essai réel et ne
modifie pas les preuves du [registre](IMPLEMENTATION_STATUS.md). Le
[formulaire GitHub](../../../.github/ISSUE_TEMPLATE/extension_compatibility.yml)
reste un résumé : le compte rendu reproductible est ce modèle rempli.
L'[exemple synthétique](RAPPORT_COMPATIBILITE_APK_EXEMPLE.md) montre comment
écrire un blocage sans le compter comme une réussite.

Ce modèle ne remplace pas les scénarios
[APK01–APK14](EXIGENCES_ANDROID_APK.md). Une ligne `passed` ne couvre pas
les autres étapes, appareils ou extensions.

## Statuts

Un seul statut par ligne :

| Statut | Sens |
| --- | --- |
| `passed` | L'étape a été tentée et le résultat observé correspond au critère de la ligne. |
| `failed` | L'étape a été tentée et s'arrête sur une erreur d'exécution, de contrat ou de données. |
| `blocked` | L'étape a été tentée, mais un facteur extérieur empêche de la conclure (site, vérification, autorisation, attente système). |
| `not-tested` | L'étape n'a pas été tentée. |

`blocked` et `not-tested` ne deviennent pas `passed`. Une installation réussie
ne prouve pas le catalogue, la vidéo, la lecture ni le téléchargement.

## Deux distinctions obligatoires

**Site ou runtime.** Un blocage de site (`website-block`) signifie que le
moteur a bien lancé l'appel, puis que le site, un défi (WebView, vérification),
un refus HTTP ou le réseau empêche le contenu. Une incompatibilité d'exécution
(`runtime-incompatibility`) est une erreur de liaison, d'ABI, d'API, une
exception du moteur ou un écart avec Aniyomi/Anikku alors que la réponse du
site n'est pas en cause. Si la preuve ne permet pas de trancher, écrire
`not-determined` : ne pas attribuer l'échec au site ni au moteur.

**APK Android ou recette desktop.** L'exécution APK charge les classes d'un
paquet installé par Android, dans un build `debug` ou `validation`. Le moteur
APK n'est pas chargé sur Linux, Windows ou le serveur : une recette Python y
est un autre essai, à remplir dans la section desktop. Un paquet visible ne
prouve pas la recette, et une recette ne prouve pas l'APK.

## Retirer les données privées

Aucune de ces données n'est demandée : numéro de série, identifiant ADB,
Android ID, cookie, jeton, en-tête `Authorization` ou `Cookie`, URL signée ou
temporaire (paramètres de signature, expiration, hôte de média avec jeton).

Avant de publier le rapport ou une capture :

1. Supprimer les lignes de log qui contiennent `Cookie`, `Set-Cookie`,
   `Authorization`, `token`, `sig` ou `expires`.
2. Remplacer la chaîne de requête d'une URL par `[query-removed]`, et ne pas
   coller l'URL de lecture.
3. Remplacer un numéro de série ou un identifiant de transport ADB par
   `[serial-removed]`. L'option `--device` ne s'écrit pas ici.
4. Décrire un compte, un courriel ou un pseudo par « compte de test retiré ».
5. Ne pas joindre de sauvegarde, d'archive d'artefacts, de base ni de
   préférences secrètes. Les mémos internes restent hors du rapport.
6. Recadrer une capture sur le message d'erreur, sans barre de statut, compte
   ni URL complète.

L'empreinte SHA-256 du certificat du paquet est une identité publique
d'extension, pas un secret d'appareil. Elle reste facultative. Toute valeur
inventée pour illustrer le rapport doit être marquée **synthétique**.

## Environnement

| Champ | Valeur |
| --- | --- |
| Date | |
| AnimeLab : commit (`git rev-parse HEAD`) ou tag | |
| Variante de build (`debug`, `validation`, `release`) | |
| Package applicatif testé | |
| Android : version et niveau d'API | |
| ABI | |
| Appareil (`phone` ou `emulator`, modèle ou AVD, sans numéro de série) | |
| Hôte comparé (Aniyomi ou Anikku, version), s'il y en a un | |

## Extension

| Champ | Valeur |
| --- | --- |
| Package Android | |
| versionName et versionCode | |
| API d'extension annoncée | |
| Dépôt d'origine (URL publique de l'index, sans jeton) | |
| Source testée (nom affiché et langue) | |
| Empreinte SHA-256 du signataire | |
| Origine du paquet (autre hôte, ou installation depuis AnimeLab) | |

## Exécution APK Android

Preuve attendue, une fois les secrets retirés : code ou phase observée, décompte
ou message court. Un téléchargement seul n'est pas une installation. Les
préférences ne sont tentées que si la source les déclare.

| Étape | Statut | Preuve |
| --- | --- | --- |
| Découverte / installation | `not-tested` | |
| Confiance | `not-tested` | |
| Catalogue / recherche | `not-tested` | |
| Épisodes | `not-tested` | |
| Filtres / préférences | `not-tested` | |
| Session WebView | `not-tested` | |
| Résolution vidéo | `not-tested` | |
| Lecture | `not-tested` | |
| Téléchargement | `not-tested` | |

## Cause : site ou runtime

| Observation | Classification (`website-block`, `runtime-incompatibility` ou `not-determined`) | Pourquoi |
| --- | --- | --- |
| | | |

## Recettes desktop / serveur

À remplir seulement pour une recette Python essayée à part. Ne pas recopier
le résultat Android dans ce tableau.

| Étape | Statut | Preuve |
| --- | --- | --- |
| Import / exécution de la recette | `not-tested` | |
| Catalogue / recherche | `not-tested` | |
| Lecture ou téléchargement | `not-tested` | |

Plateforme desktop constatée (Linux, Windows ou serveur), ou vide :

## Limites et synthèse

Étapes encore ouvertes, et ce que ce rapport ne démontre pas :

Parcours complet métadonnées → vidéo : oui / non.

Résumé en une phrase, sans transformer un blocage en succès :
