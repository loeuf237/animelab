# Étude de la gestion des extensions Aniyomi et Anikku

Complément du 29 octobre : [WebView, sessions HTTP et reprise des extensions](WEBVIEW_SESSIONS.md),
avec analyse séparée des deux hôtes, audit de concurrence et état des corrections.

**Date : 28 octobre 2026 — AnimeLab étudié au commit `75c84ec`.**

## Résultat principal

La gestion complète des extensions demande deux chantiers complémentaires : un véritable gestionnaire de dépôts, de paquets et de sources ; puis, pour la compatibilité avec le comportement arbitraire des APK, un moteur capable d'exécuter leur code et leur API. Améliorer les heuristiques DEX ne remplace pas ce second chantier.

**Exigence Android confirmée par l'utilisateur :** installer de véritables APK via Android et réutiliser directement les paquets d'extensions déjà installés par Aniyomi ou Anikku. Le moteur Android et cette interopérabilité sont obligatoires pour achever ce chantier. Voir les [exigences et tests de réception APK](EXIGENCES_ANDROID_APK.md), notamment la distinction entre paquets partagés et fichiers privés d'une autre application.

Aniyomi et Anikku exécutent les classes des extensions après vérification de leur compatibilité et de leur confiance. AnimeLab produit actuellement une recette déclarative à partir de constantes et de plans de compatibilité. Cette différence explique pourquoi une extension peut être fonctionnelle dans ces applications et seulement partiellement utilisable chez nous.

L'étude identifie aussi des corrections indépendantes du moteur : coexistence des dépôts, séparation catalogue/installation, conservation des extensions retirées, identité des sources, signatures, versions numériques, opérations annulables et préférences par source.

## Documents

- [Rapport détaillé et comparaison](RAPPORT.md).
- [Plan d'implémentation, dépendances et critères de validation](PLAN_IMPLEMENTATION.md).
- [Exigence Android : installation réelle et compatibilité des APK partagés](EXIGENCES_ANDROID_APK.md).
- [Utilisation, nouveaux parcours et limites actuelles](UTILISATION.md).
- [Registre d'implémentation et preuves](IMPLEMENTATION_STATUS.md).
- [Registre des sources primaires](SOURCES.md) et [inventaire JSON des références figées](sources.json).
- [Résultats des vérifications locales](validation.json).
- [Reproduction isolée des six constats AnimeLab](verify_current.py), avec [cas d'audit](audit_current_cases.py).

## Versions étudiées

| Projet | Référence | Précision |
| --- | --- | --- |
| Aniyomi | `v0.18.2.1`, commit `97414446b8a95994c72dd33c41c971a89d4d25b8` | `main` et cette version sont identiques au moment de l'étude. |
| Anikku | `master`, commit `6e35b41f0cc7e375d15527bd61375435f998685a` | 54 commits après `v0.2.0`, publié le 11 septembre 2026. Cinq fichiers centraux ont aussi été comparés au tag ; ils sont identiques après normalisation des fins de ligne. |
| extensions-lib | commit `971ce96e76202bb35432fe71f92553e3ae40d01d` | Contrat et schéma d'index officiel Aniyomi. |
| AnimeLab | `75c84ecac74454db5f1a95c6dfa81a699e2ffcc9` | Gestion Python, API, migrations, interface Vue et ponts Android actuels. |

## Vérifications et limites

86 fichiers amont ont été récupérés à des références figées. L'étude repose sur leur lecture et sur le code local, pas sur une exécution d'Aniyomi ou d'Anikku sur téléphone. Aucun APK amont ni catalogue complet d'un dépôt communautaire n'a été téléchargé pour cette étude.

La couverture locale existante sélectionnée passe : **79 tests**. Six cas d'audit supplémentaires reproduisent des comportements problématiques actuels : **6 constats reproduits**. Ce dernier résultat confirme les défauts décrits ; il ne signifie pas qu'ils sont corrigés.

Ces cas d'audit sont historiques : ils attendent les défauts au commit `75c84ec`.
Leur échec après correction est attendu. Pour vérifier l'implémentation courante,
exécuter la suite `uv run --locked python scripts/check.py python` après avoir
compilé l'interface. Les commandes ci-dessous servent à reproduire l'étude sur
son commit initial, depuis la racine du dépôt :

```bash
uv run --locked python docs/studies/aniyomi-anikku/verify_current.py
```

Pour relancer aussi les 79 tests existants sélectionnés :

```bash
uv run --locked python docs/studies/aniyomi-anikku/verify_current.py --baseline
```

Le lanceur de vérification utilise un HOME, une base et un cache temporaires. Les cas d'audit remplacent le téléchargement des catalogues par des réponses synthétiques. Il ne modifie pas la bibliothèque personnelle.

**Ce document décrit l'étude initiale au commit `75c84ec`.** L'implémentation
ultérieure et ses preuves sont suivies dans le
[registre courant](IMPLEMENTATION_STATUS.md), avec les
[instructions d'utilisation et de validation](UTILISATION.md).
Les fonctions écrites, les essais réussis et les critères restant à démontrer
y sont distingués ; cette étude historique ne certifie pas la livraison.
