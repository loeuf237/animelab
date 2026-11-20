# Exemple synthétique — extension bloquée, sans succès annoncé

**SYNTHÉTIQUE / SYNTHETIC.** Aucun appareil, dépôt, commit ou APK réel n'a été
utilisé. Les identifiants ci-dessous sont fictifs. Cet exemple montre comment
remplir le [modèle vierge](RAPPORT_COMPATIBILITE_APK.md) lorsqu'un site bloque
le catalogue : les étapes non tentées restent `not-tested`, et le parcours
n'est pas déclaré compatible.

Il ne met pas à jour le [registre](IMPLEMENTATION_STATUS.md) ni les fichiers
`evidence/`.

## Environnement

| Champ | Valeur |
| --- | --- |
| Date | 2026-11-06 (**synthétique**) |
| AnimeLab : commit (`git rev-parse HEAD`) ou tag | `synthe0000000000000000000000000000000001` (**synthétique**, pas un commit du dépôt) |
| Variante de build (`debug`, `validation`, `release`) | `validation` |
| Package applicatif testé | `com.example.animelab.synthetic.validation` |
| Android : version et niveau d'API | Android 10 / API 29 (**synthétique**) |
| ABI | `arm64-v8a` |
| Appareil | `emulator`, AVD `Synthetic_API_29`. Numéro de série non demandé et non écrit. |
| Hôte comparé (Aniyomi ou Anikku, version), s'il y en a un | aucun |

## Extension

| Champ | Valeur |
| --- | --- |
| Package Android | `example.invalid.animeextension.syntheticwall` |
| versionName et versionCode | `0.0.0-synthetic` / `1` |
| API d'extension annoncée | 14 |
| Dépôt d'origine (URL publique de l'index, sans jeton) | `https://example.invalid/synthetic-extensions/index.min.json` |
| Source testée (nom affiché et langue) | « Mur synthétique », langue `example` |
| Empreinte SHA-256 du signataire | valeur fictive abrégée `0000…0000` (**synthétique**) |
| Origine du paquet | déjà présent sur l'AVD fictif ; pas réinstallé pour cet essai |

## Exécution APK Android

| Étape | Statut | Preuve |
| --- | --- | --- |
| Découverte / installation | `passed` | Paquet visible, versionCode 1, octets inchangés. Aucune session PackageInstaller lancée. Le téléchargement n'est pas utilisé comme preuve d'installation. |
| Confiance | `passed` | Couple versionCode 1 / signataire synthétique approuvé pour ce build de validation seulement. |
| Catalogue / recherche | `blocked` | L'appel « populaire » part. Réponse HTTP 403, corps réduit à « You are unable to access synthetic.invalid ». Zéro résultat. Requête retirée : `https://synthetic.invalid/catalogue[query-removed]`. |
| Épisodes | `not-tested` | Aucune fiche ouverte : le catalogue est bloqué avant. |
| Filtres / préférences | `passed` | Un filtre local « langue = démo » s'applique sans réseau. La source ne déclare pas de préférence secrète ; aucune n'a été lue. Ce succès ne débloque pas le catalogue. |
| Session WebView | `blocked` | Fenêtre de vérification affichée pour `https://synthetic.invalid/`. Session non terminée. Aucun cookie copié dans ce rapport. |
| Résolution vidéo | `not-tested` | Aucun hébergeur atteint. |
| Lecture | `not-tested` | Non demandée. |
| Téléchargement | `not-tested` | Non demandé. |

## Cause : site ou runtime

| Observation | Classification | Pourquoi |
| --- | --- | --- |
| Catalogue HTTP 403 et texte « unable to access synthetic.invalid » | `website-block` | Le moteur a exécuté l'appel. L'arrêt vient du site fictif, pas d'une erreur de liaison, d'ABI ou d'API. |
| WebView laissée sur le même mur | `website-block` | Défi affiché, session non reprise. Ce n'est pas une incompatibilité du runtime. |
| Épisodes, vidéo, lecture, téléchargement | `not-determined` | Étapes non tentées. On ne les classe ni comme panne du site ni comme panne du moteur. |

Si le catalogue s'était arrêté avant toute réponse HTTP, par exemple sur
`NoSuchMethodError` ou `operation_unavailable`, la ligne serait `failed` et la
classification `runtime-incompatibility`. Ce n'est pas le cas ici. Les lignes
`passed` de découverte, de confiance et de filtre local ne transforment pas
`blocked` en succès.

## Recettes desktop / serveur

| Étape | Statut | Preuve |
| --- | --- | --- |
| Import / exécution de la recette | `not-tested` | Aucune recette Python lancée. |
| Catalogue / recherche | `not-tested` | |
| Lecture ou téléchargement | `not-tested` | |

Plateforme desktop constatée (Linux, Windows ou serveur), ou vide :

non essayée. Le paquet Android fictif ne prouve rien sur le bureau : le
runtime APK n'y est pas chargé.

## Limites et synthèse

Découverte, confiance et filtre local seulement. Catalogue et WebView bloqués
par le site synthétique. Épisodes, résolution, lecture et téléchargement non
testés. Aucune autre extension, ABI ou appareil n'est couvert.

Parcours complet métadonnées → vidéo : non.

Résumé en une phrase, sans transformer un blocage en succès :
l'extension synthétique est découverte et approuvée, puis bloquée par le site
avant tout épisode ou toute vidéo ; elle n'est pas compatible.
