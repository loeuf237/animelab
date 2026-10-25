# A06, A07 et A08 — réalisation et validation

Ces changements concernent le code source. Ils ne modifient pas les APK déjà
distribués. La validation du moteur utilise des serveurs et fournisseurs simulés
afin de reproduire les fautes sans dépendre des protections des sites.

## A06 — Contrats API et erreurs exploitables

`animelab/api_contracts.py` valide les entrées des routes historiques qui lisaient
directement `request.json()` et les réponses JSON des API. Les corps déjà typés
par FastAPI conservent leur validation native. Les champs supplémentaires
existants sont conservés, notamment les indicateurs d'épisodes vus/téléchargés.
Les recettes et paramètres propres à chaque extension restent des valeurs JSON
typées ; leur structure métier sera unifiée avec A04.

Le client TypeScript dispose de contrats pour les paramètres, téléchargements,
sessions réseau, vérifications, stockage, bibliothèque et réponses d'erreur.
Les requêtes de serveurs et de taille d'épisode transmettent désormais `url`,
le paramètre attendu par le serveur.

Le contrat d'erreur ajoute `problem` sans supprimer les anciens champs :

```json
{
  "error": "Storage access unavailable; authorize a folder in Settings > Storage",
  "code": "storage_permission_required",
  "problem": {
    "code": "storage_permission_required",
    "category": "permission",
    "messageKey": "Autorisez le stockage dans les paramètres.",
    "action": "storage_settings",
    "retryAfter": null,
    "domain": null,
    "url": null
  }
}
```

| Catégorie | Action proposée |
| --- | --- |
| `protection` | Vérifier l'accès au site |
| `network` | Réessayer |
| `rate_limit` | Attendre ; `retryAfter` exprime des secondes |
| `media` | Réessayer le traitement/téléchargement |
| `permission` | Ouvrir les réglages de stockage |
| `export` | Réexporter la copie locale |
| `validation`, `conflict`, `not_found`, `internal` | Afficher le diagnostic |

Les routes historiques renvoyant `success: false` avec HTTP 200 conservent ce
statut et reçoivent aussi un diagnostic structuré. Les erreurs HTTP sont
traduites par le client à partir de `messageKey`. Les parcours existants de
vérification, stockage et réexport portent les actions de récupération.
Les erreurs de validation ne renvoient pas les valeurs d'entrée refusées.

Les réponses API portent l'en-tête `X-Animan-API-Version: 1`. Le schéma
`/openapi.json` décrit les requêtes et erreurs ; les opérations GET/HEAD ont des
identifiants distincts. Les réponses vidéo, sous-titres et SSE ne sont pas mises
en mémoire par le middleware de contrat.

## A07 — Vérification selon la plateforme et la route

`VerificationMechanism` sépare l'ouverture, la capture de cookies et la fermeture.
Deux mécanismes l'implémentent : navigateur Chromium déjà installé et WebView
native. L'API fournit les modes et les raisons d'indisponibilité, globalement et
pour chaque session source.

| Situation | Onglet manuel | Capture Chromium | Capture WebView |
| --- | --- | --- | --- |
| Bureau local, session graphique, navigateur installé | Oui | Oui | Si intégrée |
| Bureau local sans session graphique/navigateur | Oui | Non | Si intégrée |
| Android local sans proxy | Oui | Non | Oui si intégrée |
| Client distant | Oui | Non | Non |
| Proxy sans authentification | Oui | Bureau compatible uniquement | Non |
| Proxy avec authentification | Oui | Non | Non |

L'onglet manuel utilise le navigateur de l'utilisateur et ne transmet pas ses
cookies à Python. Une visite peut donc ne pas débloquer la requête du moteur.
Un mode indisponible n'est pas présenté comme un bouton utilisable.

La capture est liée à la génération de session et au proxy présents à son
ouverture. Un changement de route pendant l'ouverture, la capture ou le contrôle
d'accès empêche de déclarer la source débloquée. Il faut fermer cette fenêtre et
recommencer. Une annulation garde la recherche en attente ; une recherche fermée
ou remplacée n'est jamais relancée après validation.

## A08 — Reprise, assemblage et publication

- Une URL HTTP signée renouvelée peut reprendre le même chemin et la même
  origine. Un changement d'origine, de port ou de chemin impose un redémarrage.
  Les validateurs HTTP et la comparaison des octets de chevauchement restent
  nécessaires ; l'identité d'URL seule ne prouve pas l'identité du média.
- Une réponse 206 sans taille totale connue est refusée avant publication.
- Le cache HLS vérifie taille et SHA-256 de chaque segment enregistré. Un segment
  modifié, tronqué ou dépourvu de marqueur est retéléchargé. Le changement de
  playlist invalide le cache correspondant.
- L'assemblage écrit dans un fichier temporaire. Une interruption conserve les
  segments utilisables sans créer de fichier final partiel. Le chemin natif
  refuse explicitement les playlists `EXT-X-BYTERANGE` et `EXT-X-MAP` non prises
  en charge ; il ne concatène pas ces formats comme du MPEG-TS classique.
- La publication refuse d'écraser une destination apparue pendant le transfert.
- La finalisation est exclusive par tâche. Après annulation de l'attente Python,
  un worker de mux encore actif reste suivi et bloque un nouvel essai ou une
  suppression concurrente.
- Une finalisation répétée ne réexporte pas une publication déjà confirmée.
  Un échec de suppression d'une publication Android inachevée conserve son
  identifiant de récupération et bloque la création d'une copie supplémentaire.

Ces garanties couvrent les fautes reproduites par les tests. Une panne électrique
à tout instant et tous les fournisseurs de documents Android ne sont pas
simulés. Sur un système de fichiers refusant les liens physiques, la publication
réserve exclusivement le nom avant remplacement ; un arrêt brutal entre ces
deux opérations peut laisser une réservation vide à diagnostiquer.

## Vérifications reproductibles

Depuis la racine du dépôt, avec une base et des dossiers de test isolés :

```bash
ANIMAN_DB_PATH=/tmp/animan-validation.sqlite3 \
ANIMAN_DOWNLOAD_DIR=/tmp/animan-validation-downloads \
ANIMAN_CACHE_DIR=/tmp/animan-validation-cache \
ANIMAN_STARTUP_REFRESH=false \
python3 -m pytest -q

npm test --prefix frontend
npm run build --prefix frontend
```

La compilation Kotlin valide les appels natifs sans produire un APK de diffusion :

```bash
cd android
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 \
./gradlew :app:compileValidationKotlin --offline --no-daemon --max-workers=2
```

Les tests dédiés sont dans `tests/test_api_contracts.py`,
`tests/test_verification_platform.py`, `tests/test_transfer_fault_contracts.py`
et `frontend/tests/api-contracts.test.mjs`. Ils complètent les tests de reprise
réseau, vérification navigateur, mux et export Android existants.

Validation effectuée le 20 octobre 2026 : **443 tests Python** et **26 tests
frontend** réussis, compilation TypeScript/Vite et compilation Kotlin
`compileValidationKotlin` réussies. Deux avertissements de dépréciation de
Starlette/AnyIO subsistent dans les tests ; Vite signale également un bundle
supérieur à 500 Ko. Sur le serveur local, les schémas OpenAPI n'ont aucune
référence manquante, une entrée invalide reçoit HTTP 422 avec `problem`, un média
absent reçoit HTTP 404, et un fichier local répond en HEAD 200 puis Range 206
avec les 64 octets demandés. Le worker de rechargement bloqué a été relancé après
confirmation de l'absence de transfert actif en base. Aucun APK n'a été généré
pour cette validation et aucun test sur appareil Android n'a été réalisé.

## Parcours manuels à refaire

1. Sur bureau, passer l'interface en français puis en anglais. Provoquer une
   erreur API de validation et un refus de stockage ; vérifier le message traduit
   et l'absence de valeur sensible dans la réponse.
2. Lancer une recherche sur une source bloquée. Vérifier les modes disponibles,
   terminer la vérification et constater la relance de la recherche active.
   Refaire après fermeture de la recherche : elle ne doit pas réapparaître.
3. Depuis un autre appareil connecté au serveur, vérifier que seul le lien manuel
   est utilisable. Aucun navigateur ne doit être lancé sur le serveur distant.
4. Sur une version Android reconstruite, vérifier la WebView sans proxy puis son
   indisponibilité avec proxy. Refuser l'accès à un dossier, réautoriser le
   stockage et réexporter une copie locale sans nouveau téléchargement.
5. Télécharger un épisode de test HTTP et un épisode HLS, couper la connexion,
   puis reprendre. Contrôler la lecture et la durée du fichier final. Répéter
   avec une rotation après fermeture de la connexion interrompue.
6. Mettre en pause pendant le mux, puis reprendre après arrêt du worker. Interrompre
   une publication Android et relancer le réexport : contrôler les URI confirmées
   et l'absence de doublon dans le stockage partagé.

La matrice et les fautes sont testées automatiquement ; la résolution effective
d'un CAPTCHA, la rotation sur un fournisseur réel et les parcours Android sur
appareil restent à valider dans ces conditions réelles.
