# P10–P13 — Évaluation du backend spécialisé et décision de distribution

27 octobre 2026. **Décision P12 : N_m3u8DL-RE 0.6.0-beta non adopté en production. P13 est clôturé « non retenu », conformément à sa condition de passage.** Le socle P1–P9 et les moteurs existants restent utilisables. P14, consacré au hardsub Android, est indépendant ; P15, consacré au même backend dans l’APK, est non retenu pour cette version.

## Statut des lots

| Lot | Résultat | Conséquence |
| --- | --- | --- |
| P10 | Backend d’évaluation sous contrat P1, binaire épinglé, corpus local et mesures réelles | Gain de couverture démontré sur certains flux ; contre-exemples conservés |
| P11 | Prototype `ManifestRelay`, SourceHTTP, caches vérifiés et isolation réseau réellement testés sous Linux x64 | Aucune activation dans le serveur partagé ; Windows/macOS non validés |
| P12 | Reprise, corruption, panne, renouvellement, arrêt et isolation testés ; décision écrite | Refus de l’adoption de cette version |
| P13 | Condition P12 non remplie : distribution non retenue | Aucun binaire ajouté aux releases desktop, au Docker ou à l’APK ; workflow d’étude manuel seulement |

Cette clôture suit la règle du [plan de priorités](PRIORITES_IMPLEMENTATION.md) : « en cas de refus, clôturer P13/P15 comme non retenus ». Elle ne signifie pas que des packages Windows/macOS auraient été construits ou validés. Aucun commit, push ou déclenchement distant n’est réalisé par ce lot.

## Résultats qui motivent la décision

Deux contre-exemples ont été reproduits avec le **vrai binaire**, sur des fichiers synthétiques connus :

1. **Fragment corrompu conservé dans le cache de l’outil.** Le programme le réutilise sans le récupérer de nouveau et termine avec un code de sortie zéro. L’assemblage obtenu est plus court que le manifeste. Notre vérification de durée refuse ce résultat. Effacer le cache interne et reconstruire depuis notre propre cache vérifié restaure les bonnes images, mais prive l’intégration de la reprise native attendue de cet outil.
2. **WebVTT avec discontinuité et changement de `X-TIMESTAMP-MAP`.** Les deux textes sont présents mais le second apparaît à **0,2–0,8 s**, au lieu de **2,2–2,8 s**. Une simple vérification de présence de piste, de nombre de sous-titres ou de durée de vidéo ne détecte pas cette erreur. Le prototype refuse donc les discontinuités par défaut. Un commutateur réservé au banc d’essai permet de reproduire le défaut ; son résultat n’est jamais annoncé complet ni utilisable pour la finalisation.

Le gain de couverture est réel pour fMP4/BYTERANGE, DASH à audio séparé et WebVTT segmenté sans rupture. En revanche, le raccordement sûr nécessite déjà un téléchargeur vérifié, un cache de ressources, la réécriture des manifestes, un serveur HTTP local et une isolation réseau. Cette version **ne simplifie pas suffisamment le moteur** au regard des défauts reproduits et du coût de portabilité. Les moteurs existants ne sont pas remplacés.

Le programme échoue également dans certains lancements avec sortie redirigée, à cause d’une exception de rendu `Spectre.Console`. `--force-ansi-console`, `COLUMNS=160` et `LINES=50` ont évité le problème dans les essais. Les segments `file://` n’ont pas fonctionné dans le premier essai du binaire épinglé : le prototype utilise donc un relais HTTP privé dans le namespace. Ces observations concernent cette version et ce corpus, pas toutes les versions amont.

## Version, origine et poids

- [Release officielle v0.6.0-beta](https://github.com/nilaoda/N_m3u8DL-RE/releases/tag/v0.6.0-beta), commit `df70f0b3da0c630bd413bf617e758051f6b64757`.
- Version renvoyée : `0.6.0+df70f0b3da0c630bd413bf617e758051f6b64757`.
- Archive Linux x64 : **8 045 197 octets**, SHA-256 `2ebcd450594a08c0de0bcd502a80c5d3f89a702a0fa6604199527bb8d6eee4db`, identique au digest de l’asset publié par GitHub.
- Binaire extrait : **18 450 176 octets**, SHA-256 `87e5bf963d9c1a72aee8eb5a75edbe398de2b00ec209b595f621ac6a9c344186`.
- Licence amont MIT : [notice](N_m3u8DL-RE-LICENSE.txt). Les empreintes d’archives des six cibles desktop Linux/Windows/macOS x64/ARM64 sont enregistrées dans `animelab/services/experimental/nm3u8dl-lock.json`. Seule la cible Linux x64 a été exécutée ici.

Ces nombres décrivent l’outil autonome ; le coût d’une archive AnimeLab recompressée n’a pas été mesuré, puisqu’aucune distribution n’est retenue. Le binaire testé reste dans `/tmp`, hors dépôt. Le script de préparation vérifie taille et SHA-256, lit seulement l’exécutable attendu dans l’archive, ignore les autres chemins, refuse les liens et n’installe rien dans l’application. Les digests GitHub constituent un contrôle de correspondance des assets, pas une signature indépendante de l’éditeur.

## Architecture du prototype et périmètre P11

Le backend se trouve dans `animelab/services/experimental/` et implémente `transfer(task, media, emit)` selon le contrat P1. Sa construction exige une option d’évaluation explicite. Il n’est pas enregistré dans `TransferPlanner` et aucune route API ne permet de l’activer.

Le chemin d’une tâche d’étude est :

```text
ResolvedMedia
  → ManifestRelay / SourceHTTP
  → ressources locales vérifiées + manifestes réécrits
  → namespace réseau Linux neuf, sans route externe
  → serveur HTTP privé sur le loopback de ce namespace
  → N_m3u8DL-RE + FFmpeg pour l’assemblage interne
  → contrôle des pistes, durée, décodage et images de référence
  → résultat de banc d’essai ; aucune publication utilisateur
```

FFmpeg et la politique de sortie P6/P7 conservent leur responsabilité. L’assemblage interne de l’outil est un MKV de travail ; ce n’est ni une demande de MP4 hardsub ni une publication finale en bibliothèque.

Le relais :

- récupère les ressources via `SourceHTTPService` par défaut ; la session, les cookies, les challenges et les limitations restent gérés par ce service ;
- contrôle chaque URL avant requête, y compris les redirections ; limite les schémas à HTTP/HTTPS, refuse les identifiants intégrés et applique la politique de domaines du serveur partagé ;
- limite l’authentification à l’origine initiale ; retire les en-têtes Authorization/Cookie pour une autre origine ; les cookies de session restent ceux du client HTTP par domaine ;
- réécrit playlists, segments, clés AES-128, initialisations et plages HLS ; conserve les cadences/timelines DASH et crée des alias de segments locaux pour ses templates ;
- attribue une capacité privée à chaque instance, vérifie le nom des ressources, refuse l’accès croisé et révoque la capacité à l’arrêt ;
- borne le nombre de ressources, la taille des manifestes, chaque ressource, le total temporaire et la profondeur ; refuse les références non couvertes au lieu de les transmettre intactes au programme.

Le serveur HTTP du worker se trouve **dans un autre namespace réseau**, et son jeton est valable seulement pendant cette exécution. Un autre compte du serveur n’a pas de route vers ce loopback. Le programme n’obtient ni URL de fournisseur, ni cookie, ni clé dans ses arguments ou son environnement. Les clés AES du corpus sont des données synthétiques publiques ; les caches temporaires sont privés.

L’isolation n’est pas déduite de la seule réécriture : un test réel de socket vers `192.0.2.1:443` retourne **ENETUNREACH**, et les identifiants de namespace parent/enfant diffèrent. `strace` observe les appels `connect` du programme et de ses descendants ; le relevé JSON précise les adresses constatées. Les tentatives externes provoquent un refus du worker. Les résultats restent des preuves Linux locales ; aucun équivalent Windows/macOS ni fonctionnement dans un conteneur Docker restreint n’a été validé.

Périmètre évalué : VOD statiques, une variante HLS explicite, au plus une piste audio et une piste sous-titre déclarées par rôle, un Period DASH, une représentation explicite par AdaptationSet, BaseURL simples, SegmentTemplate/Timeline bornés et SegmentList avec durées/plages explicites. Live, DRM, SAMPLE-AES, SegmentBase/SIDX, variantes ambiguës, templates inconnus, pistes externes au manifeste et multi-périodes sont refusés ou hors périmètre. Les discontinuités sont désormais refusées par défaut à la suite du contre-exemple.

## Reprise, intégrité et limites de progression

Les checkpoints conservent backend/version, espace de travail, empreinte de représentation, état et inventaire des ressources. Chaque ressource entière a une taille et un SHA-256. Les téléchargements partiels ne sont jamais repris par simple présence sur disque. Les caches valides sont revalidés par ETag fort ; sans preuve de fraîcheur, la ressource est récupérée de nouveau. Un fichier local altéré est retéléchargé.

Les URL signées ne sont pas stockées dans les checkpoints : des identités hachées servent à nommer les ressources. Un changement de manifeste ou de représentation change l’empreinte. Les anciennes ressources non référencées ne sont pas servies dans le nouveau plan. Une URL renouvelée est traitée de manière conservatrice, ce qui peut occasionner un nouveau téléchargement plutôt qu’une reprise ambiguë.

Le cache interne de N_m3u8DL-RE est effacé avant chaque exécution normale du prototype. Seul le banc négatif le conserve volontairement pour reproduire la corruption. La réutilisation du cache vérifié du relais reste possible après panne, annulation ou recréation de l’objet backend. L’annulation du vrai sous-processus attend sa terminaison, révoque le relais et conserve les ressources complètes pour un nouvel essai.

La progression remontée provient de nos propres ressources et étapes. La console de l’outil n’est pas interprétée comme une API stable. `--write-meta-json false` évite d’assimiler son JSON de métadonnées à un protocole de progression ou de reprise.

## Corpus et mesures

Six cas synthétiques de quatre secondes : vidéo bleue H.264, audio sinusoïdal AAC, deux répliques connues lorsque présentes. Aucun média externe n’est téléchargé. L’acquisition amont du benchmark utilise un transport simulé ; le vrai programme télécharge ensuite depuis le relais HTTP local isolé. Les images décodées sont comparées à la référence par empreinte de `framemd5`.

Les mesures reproductibles figurent dans [nm3u8dl-proof.json](nm3u8dl-proof.json). Les temps/CPU/disque et débit de pipeline sont propres à ce petit corpus local ; **ils ne mesurent pas le débit d’un site ni un gain réseau en production**. Le RSS du worker correspond au maximum de ses processus enfants, notamment le programme et FFmpeg ; le RSS relevé par le processus d’étude peut aussi inclure la génération des fixtures et reste indiqué séparément.

| Cas synthétique | Résultat utilisable | Temps du pipeline | CPU | Disque temporaire |
| --- | --- | ---: | ---: | ---: |
| HLS simple | Oui | 1.288 s | 0.764 s | 225 498 octets |
| HLS AES-128 | Oui | 1.249 s | 0.745 s | 226 213 octets |
| fMP4/BYTERANGE | Oui | 1.107 s | 0.671 s | 166 838 octets |
| DASH audio séparé | Oui | 1.275 s | 0.839 s | 215 156 octets |
| WebVTT segmenté | Oui | 1.229 s | 0.810 s | 228 847 octets |
| WebVTT avec discontinuité | Non : horloge incorrecte | 1.814 s | 1.049 s | 228 782 octets |

Le RSS maximal des enfants du processus d’étude va de 98 036 à 98 564 Kio selon le cas ; il ne représente pas la mémoire du seul binaire. Les valeurs sont celles du JSON conservé, et non une nouvelle exécution lors de la finalisation du rapport.

Le corpus montre cinq assemblages conservant les images de référence, dont les deux répliques correctes sans rupture, et un cas de rupture dont la mauvaise horloge est volontairement reproduite puis exclue du périmètre utilisable. La capacité native indiquée dans le JSON vient des contrôles de formats existants ; ce n’est pas un benchmark de vitesse du téléchargeur natif.

## Validation effectuée

Les journaux locaux du 27 octobre, relus après la reprise du travail dans un autre chat, indiquent :

- `ANIMELAB_NM3U8DL_EVAL_PATH=/tmp/animelab-p10/verified/N_m3u8DL-RE uv run --locked python -m pytest tests/test_nm3u8dl_p10_p13.py -q` : **34 réussis en 29,80 s**, avec le vrai binaire Linux x64, les deux contre-exemples et l’annulation du sous-processus.
- `uv run --locked python scripts/check.py python` : **903 réussis, 5 ignorés, 2 avertissements en 160,96 s**. Les essais exigeant le binaire optionnel restent distincts de cette suite ordinaire.
- `uv run --locked python scripts/check.py quality` : réussi, avec Ruff, Mypy et les contrôles frontend de lint, formatage et typage.
- Génération de `nm3u8dl-proof.json` avec le binaire épinglé : terminée ; les résultats du tableau et le refus du cache corrompu proviennent de ce fichier.

Ces contrôles précèdent les dernières modifications documentaires ; les suites applicatives n’ont pas été relancées pour ces seules modifications. Les références, le dossier régénéré et les liens locaux sont contrôlés séparément. Aucune exécution du workflow GitHub Actions, validation Windows/macOS du backend ou validation sur appareil Android n’est revendiquée.

## Reproduire et réévaluer

Prérequis Linux x64 : FFmpeg/FFprobe, `unshare`, `iproute2`, namespaces utilisateur autorisés ; `strace` pour observer les connexions. Le programme est facultatif et n’est pas nécessaire aux tests ordinaires du dépôt.

```bash
uv sync --locked
uv run --locked python scripts/fetch_nm3u8dl_eval.py --directory /tmp/animelab-nm3u8dl
ANIMELAB_NM3U8DL_EVAL_PATH=/tmp/animelab-nm3u8dl/N_m3u8DL-RE uv run --locked python -m pytest tests/test_nm3u8dl_p10_p13.py -q
uv run --locked python scripts/evaluate_nm3u8dl.py --tool /tmp/animelab-nm3u8dl/N_m3u8DL-RE --output /tmp/nm3u8dl-proof.json
```

La commande de téléchargement peut utiliser `--archive /chemin/archive-officielle.tar.gz` pour réutiliser une copie déjà présente, avec les mêmes contrôles. Les tests sans cette variable ignorent les deux essais exigeant le binaire. Un namespace indisponible est une raison de refus, jamais un motif pour exécuter le programme avec le réseau de l’hôte.

Le workflow **Optional N_m3u8DL-RE offline evaluation**, à déclenchement manuel, prépare le binaire sur le runner, lance les tests et produit uniquement les JSON d’étude et de vérification. Permissions `contents: read` ; aucune publication de release et aucun APK envoyé depuis cet ordinateur. Ce workflow est préparé localement et n’a pas été exécuté sur GitHub pendant cette tâche.

Une réévaluation future exige la correction et la vérification des deux contre-exemples, un gain démontré sur des flux représentatifs autorisés, une reprise sûre sans duplication excessive, et une isolation maîtrisée sur les plateformes à distribuer. Le lot P13 ne doit être rouvert qu’après une nouvelle décision P12 favorable. [Décision structurée](nm3u8dl-decision.json).
