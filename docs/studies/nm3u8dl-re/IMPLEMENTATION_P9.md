# P9 — Fournisseurs, correspondances et synchronisation réversible

Livraison locale du 27 octobre 2026. P9 est implémenté et testé localement, avec **validation SubDL authentifiée réelle encore en attente**. Aucun compte fournisseur n’a été créé, aucune clé personnelle n’a été recherchée ou utilisée et aucun APK/binaire n’a été publié.

## Utilisation

Depuis **Téléchargements → Terminés → Pistes et format → Ajouter des sous-titres** :

1. Importer un fichier ou configurer OpenSubtitles/SubDL. Les identifiants sont privés au compte AnimeLab. SubDL demande uniquement une clé API.
2. Choisir un ou deux fournisseurs, préciser titre/identifiants, langue et numérotation. Les critères facultatifs release, FPS et durée servent à comparer, sans sélection automatique.
3. Télécharger explicitement un aperçu et choisir le fichier de l’archive. Cela peut consommer du quota fournisseur.
4. Dans **Corriger la synchronisation**, appliquer un décalage ou renseigner les deux cadences. Une copie est créée, prévisualisée, puis doit être confirmée avant d’être ajoutée.
5. **Revenir au sous-titre original** restaure l’aperçu d’origine. Après ajout d’une copie corrigée, **Restaurer la piste originale** ajoute/réactive l’original dans l’inventaire et désélectionne la copie. Produire ensuite le MKV/MP4/sidecar souhaité.

Une correction de timing ne modifie pas le texte des dialogues. Avec une correction de cadence, la formule est `temps_corrigé = temps_original × FPS_sous_titre / FPS_vidéo + décalage`. Par exemple un sous-titre issu d’une version 25 FPS pour une vidéo 23,976 FPS s’allonge d’un facteur `25/23,976`. Les répliques entièrement avant zéro sont retirées de la copie uniquement.

## Fournisseur SubDL

Version choisie : **API REST v2**, d’après la [documentation officielle consultée](https://subdl.com/developers). Appels retenus : `GET /api/v2/me`, `GET /api/v2/subtitles/search`, `GET /api/v2/subtitles/{nId}/download?format=zip`. Clé dans `Authorization: Bearer`, jamais dans l’URL. Les services IA et la recherche de fichiers utilisant implicitement l’IA ne sont pas appelés.

L’adaptateur normalise l’enveloppe `subtitles`/`results`, exige un identifiant `n_id` ou `nId` et ne déduit pas les identifiants absents à partir de la requête. **La documentation v2 n’illustre pas complètement la réponse de cet endpoint : ce contrat de normalisation doit être confirmé avec une réponse authentifiée autorisée.** Un schéma incompatible provoque une erreur explicite ; aucun repli silencieux sur l’API v1. La pagination v2 n’étant pas documentée pour cet endpoint, seule sa première page est acceptée ; affiner la recherche ensuite. Une recherche combinée continue à présenter les résultats de l’autre fournisseur.

Les quotas retournés par le fournisseur sont présentés sans valeur inventée. Les erreurs d’authentification, de quota, de réseau et d’archive sont distinctes. Une requête n’est pas répétée automatiquement après erreur. Redirections vérifiées, réponses bornées, destinations fixes API/CDN ; aucun en-tête d’authentification sur le CDN. Les archives réutilisent les limites et validations P8.

Les clés OpenSubtitles et SubDL ont des entrées SQLite chiffrées distinctes. La clé de chiffrement externe P8 reste optionnelle : sans elle, stockage en mémoire seulement. L’enveloppe chiffrée lie désormais explicitement compte et fournisseur ; les anciennes enveloppes OpenSubtitles restent lisibles. Pas de nouvelle migration du schéma, car la table P8 possédait déjà une clé `provider`.

## Choix et déduplication

- Même identité de fichier chez un fournisseur, ou véritable empreinte MD5/SHA de fichier partagée : regroupement possible si langue, release et rôles forcé/HI sont identiques. Une empreinte MD5 sert uniquement à dédupliquer, jamais à garantir l’intégrité de stockage.
- Titres semblables, cadences ou tailles proches ne prouvent pas l’identité. Les releases, langues et rôles différents restent séparés.
- Chaque provenance et chaque identifiant de téléchargement opaque est conservé ; le fournisseur de téléchargement peut être choisi explicitement. À l’import, SHA-256 du contenu stocké et provenance permettent aussi de reconnaître un fichier identique.
- Langue, IMDb/TMDB, saison/épisode et numérotation absolue restent des preuves séparées. Une numérotation absolue ne garantit pas que le fournisseur utilise le même découpage.
- FPS : tolérance 0,02 ; durée vidéo : maximum de 2 secondes et 2 %. La durée du dernier sous-titre n’est **pas** assimilée à celle de la vidéo. Les informations absentes restent « non vérifié ».
- Release : recouvrement de mots normalisés, seuil 0,8, seulement si l’utilisateur indique une release attendue. Ce n’est ni une probabilité de correspondance ni une preuve de contenu identique.

## Décision concernant Alass

**Alass 2.0.0 retenu comme outil optionnel desktop/serveur**, sur référence de sous-titres locale déjà synchronisée. L’extraction audio et l’alignement sur la voix ne sont pas intégrés dans P9. ffsubsync n’a pas été installé ni évalué : le plan demandait l’évaluation de l’un des deux outils. Les corrections manuelles fonctionnent sans Alass.

Pour l’activer, installer une copie de confiance du binaire [amont v2.0.0](https://github.com/kaegi/alass/releases/tag/v2.0.0) puis lancer, par exemple sous Linux :

```bash
ANIMELAB_ALASS_PATH=/chemin/absolu/alass-cli uv run --locked python run.py
```

Le chemin est une configuration de l’opérateur, jamais un argument accepté depuis l’API ou le navigateur. À défaut, `alass-cli` ou `alass` est cherché sur PATH. La version doit retourner exactement `alass-cli 2.0.0`. Sur serveur partagé, la variable doit être accessible aux workers. Aucun téléchargement du programme au démarrage, aucune intégration dans les archives desktop ou APK dans ce lot. La redistribution éventuelle nécessite la [licence GPL-3.0 d’Alass](https://github.com/kaegi/alass/blob/v2.0.0/LICENSE).

L’utilisateur sélectionne une piste texte locale et confirme qu’elle est synchronisée. Au moins cinq répliques par fichier sont nécessaires. Alass ne reçoit que deux SRT temporaires contenant des marqueurs et timings : ni URL, ni cookies, ni vidéo, ni texte original. Ses timings sont réappliqués au fichier d’origine pour préserver dialogues, styles ASS et en-têtes VTT. Exécution supervisée, sans shell, délai de 120 secondes, budget CPU partagé et annulation indépendante du téléchargement. Les fichiers temporaires sont retirés après terminaison réelle du processus.

Par défaut, les coupures sont désactivées. L’option explicite **Autoriser plusieurs décalages** permet les montages comportant des ruptures, avec vérification humaine requise. Attention : le binaire 2.0.0 testé utilise le drapeau **`--no-split`**, alors que son README mentionne `--no-splits`.

Un recouvrement temporel intersection/union inférieur à 0,55 refuse la copie. Le nombre et l’identité des marqueurs de répliques doivent rester identiques ; les timings sont réassociés à ces marqueurs si l’outil réordonne des répliques. Le résultat doit être un sous-titre valide. Le résultat indique décalage constant, dérive approximativement affine ou correction non uniforme. **Le recouvrement n’est pas une mesure de justesse sémantique** : un mauvais montage peut malgré tout passer le seuil. Vérifier début, milieu, fin et ruptures de scène avant publication.

Les imports originaux restent immuables et vérifiés par SHA-256. L’ascendance de la copie est persistée ; le retour à l’original fonctionne après redémarrage. L’annulation ne supprime pas l’original et attend la fin du travail réel avant de libérer le verrou. Limites P8 maintenues : dix imports par tâche, taille bornée et pas de suppression d’original attaché.

## Corpus et résultats reproductibles

Essai réel du binaire Linux x64 amont v2.0.0, 3 032 792 octets. SHA-256 calculé localement : `7bd0b9ae7e035d3ba940eacffb21243614df36231d47f21f0b4ce42001ab7fcd`. Cette empreinte n’est pas une signature de l’éditeur. Le binaire est resté dans `/tmp`, hors dépôt et hors distribution.

Corpus synthétique déterministe : 70 répliques irrégulières, graine 9321, environ huit minutes, avec référence connue. Chaque variante conserve exactement le même texte ; aucun épisode protégé n’a été téléchargé. Coupures autorisées pour ce benchmark, pénalité 10. Mesure : erreur moyenne absolue des débuts de répliques par rapport à la vérité connue.

| Variante | Erreur avant | Erreur après | Recouvrement après | Décision |
| --- | ---: | ---: | ---: | --- |
| Décalage constant +3,2 s | 3,200000 s | 0,000277 s | 99,9752 % | Acceptée |
| Dérive 23,976/25 | 10,612060 s | 0,000534 s | 99,9455 % | Acceptée |
| Rupture +20 s après la réplique 35 | 10,000000 s | 0,000277 s | 99,9752 % | Acceptée avec coupures |
| Montage incompatible, non uniforme | 89,696480 s | 17,276468 s | 43,7898 % | Refusée |

Ces faibles erreurs résultent d’une référence synthétique exacte ; elles ne prédisent pas la précision sur des dialogues réels. Le benchmark ne valide ni doublages différents, ni OCR, ni audio, ni des vidéos arbitraires. Le corpus anglais/français réel et le ressenti utilisateur restent à compléter.

[Résultats JSON](subtitle-sync-proof.json). Commande de reproduction depuis la racine :

```bash
ANIMELAB_ALASS_PATH=/chemin/absolu/alass-cli uv run --locked python scripts/evaluate_subtitle_sync.py --output /tmp/subtitle-sync-proof.json
ANIMELAB_ALASS_PATH=/chemin/absolu/alass-cli uv run --locked python -m pytest tests/test_subtitles_p9.py -q
```

Sans outil explicitement fourni, le test d’intégration Alass est ignoré ; les contrats, imports, corrections manuelles et parcours UI restent testés. Pas de validation native Windows/macOS ni Android automatique : capacité automatique Android désactivée. Jimaku reste différé.

## Validation et suite

Validation locale :

- Suite Python complète isolée : **869 réussis, 3 ignorés** (dont le test Alass optionnel, absent de l’environnement isolé).
- Vérification ciblée finale P8/P9/serveur partagé, avec le vrai binaire Alass : **93 réussis**. Cela inclut les deux tests ajoutés après la suite complète : propagation du chemin opérateur aux workers et référence non textuelle refusée proprement.
- Dernier contrôle P9 seul avec Alass réel, après validation des marqueurs de répliques : **30 réussis**.
- Interface Playwright : **86 réussis**, dont les parcours de recherche, correction et annulation, avec vues 360 et 1280 px.
- Node : **37 réussis** ; compilation Vue/TypeScript réussie.
- Ruff, mypy sur le périmètre configuré, ESLint et Prettier : réussis.
- FFmpeg réel : MKV contenant la copie décalée à 0,5 s, puis MKV contenant l’original restauré à 0,2 s ; aucun téléchargement vidéo.
- SubDL : tests HTTP simulés de contrat, quotas, erreurs, redirections, secrets et schémas invalides. **Aucun appel fournisseur authentifié réel.**

Les avertissements de dépréciation Starlette/httpx existants et l’avertissement Vite de taille de bundle ne sont pas des échecs de contrôle. Le parcours fournisseur réel exige encore un compte de test autorisé. Le prochain lot est P10 : évaluation hors ligne de N_m3u8DL-RE, distincte de l’outil de synchronisation Alass.
