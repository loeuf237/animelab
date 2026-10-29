# Contribuer à AnimeLab

[Français](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)

Merci de contribuer à AnimeLab ! Le projet accueille les corrections, les
traductions, la documentation, les améliorations d’interface et les essais sur
appareils. Il n’est pas nécessaire de savoir programmer pour participer.

Les échanges peuvent se faire en français ou en anglais. Soyez respectueux,
décrivez les problèmes avec précision et gardez les discussions centrées sur
les changements proposés.

## Par où commencer ?

- Consultez les [issues ouvertes](https://github.com/loeuf237/animelab/issues)
  avant de proposer un travail, afin d’éviter les doublons.
- Si des tâches portent les labels `good first issue` ou `help wanted`, elles
  constituent un bon point de départ. Sinon, proposez une petite amélioration
  ou demandez dans une issue si quelqu’un travaille déjà sur le sujet.
- Pour une évolution importante, décrivez d’abord le problème, l’approche
  envisagée et les plateformes concernées dans une issue.
- Une correction limitée, une traduction ou une clarification de documentation
  peut faire directement l’objet d’une pull request.

## Chantiers pour lesquels nous recherchons de l’aide

L’[appel à contributions détaillé](docs/contribution-priorities.md) présente
les objectifs et critères de validation de chaque chantier :

- refonte de l’écran de chargement Android ;
- détection des nouvelles versions et téléchargement automatique configurable ;
- correction des téléchargements/enregistrements en double dans French-Manga
  et les autres sources affectées ;
- validation des extensions APK Aniyomi/Anikku ;
- nouvel onglet **Outils** et atelier complet de sous-titrage, avec
  recherche, téléchargement et traduction via des clés d’API personnelles ;
- téléchargement et édition audio depuis des extensions, puis création de
  MKV multipistes audio ;
- ergonomie et présentation de la page Extensions, inspirées de Mihon/Aniyomi ;
- amélioration du README et de la documentation ;
- création de thèmes et choix d’une apparence personnalisée ;
- choix d’un dossier externe Android dès le premier démarrage ;
- amélioration du lecteur vidéo Android ;
- organisation, recherche et gestion de la bibliothèque ;
- lecture vidéo hors ligne et accès fiable aux médias locaux sur Android.

Retrouvez les tâches publiées et leurs liens dans le
[suivi des contributions #12](https://github.com/loeuf237/animelab/issues/12).
Les petites tâches portent le label `good first issue` ; les chantiers complets
sont ouverts sous `help wanted`.

Les propositions de fonctionnalités et d’architecture sont les bienvenues.
Vous pouvez contacter le mainteneur sur
[Telegram — @loeuf237](https://t.me/loeuf237). Consignez les décisions et
résultats utiles dans une issue ou une PR. Précisez toujours ce que vous avez
réellement testé.

## Signaler un bug

[Ouvrez une issue](https://github.com/loeuf237/animelab/issues/new) avec ces
informations, autant que possible :

```text
Version d’AnimeLab ou commit :
Système, version et architecture :
Installation : release / sources / Docker
Mode : launcher / navigateur / Android

Étapes pour reproduire :
1.
2.

Résultat attendu :
Résultat obtenu :
Fréquence du problème :
Logs ou capture utiles, après suppression des données privées :
```

Pour un problème d’extension, ajoutez son nom, son identifiant de paquet et sa
version, le dépôt utilisé, la plateforme et l’opération qui échoue : installation,
recherche, catalogue, épisodes, lecture ou téléchargement. Indiquez si une
vérification dans la WebView a été demandée et si elle a été terminée.

Retirez les mots de passe, clés d’API, cookies, jetons, liens privés ou signés,
ainsi que les données personnelles des logs et captures. Évitez de joindre une
base de données ou une sauvegarde personnelle complète.

Si vous découvrez une vulnérabilité, ne publiez pas ses détails exploitables
dans une issue. Utilisez **Report a vulnerability** dans l’onglet **Security** si
cette option est disponible ; sinon, contactez le mainteneur en privé sur
[Telegram](https://t.me/loeuf237).

## Préparer l’environnement

Pour modifier le code, faites un **fork** du dépôt sur GitHub, clonez votre fork,
puis ouvrez un terminal à la racine du projet, là où se trouve `pyproject.toml`.
Créez une branche dédiée à votre changement.

Prérequis :

- Git ;
- Python **3.12 ou 3.13** ; `uv` sélectionne 3.13 par défaut ;
- **uv 0.13.1** ;
- Node.js **22.13 ou plus récent dans la branche 22**, avec npm ;
- FFmpeg et ffprobe sur le `PATH` pour les traitements et tests multimédias.

Installez les dépendances et compilez l’interface :

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
```

Ces commandes fonctionnent sous Linux et dans PowerShell sous Windows.
Consultez le [guide de développement](docs/development.md) pour les paquets
système supplémentaires, les contrôles et la mise à jour des dépendances.
Une contribution documentaire seule ne nécessite pas cette installation.

### Démarrer l’application

Pour ouvrir le launcher depuis les sources, à la racine du projet :

```bash
uv run --locked --group desktop python desktop.py
```

Pour démarrer uniquement le serveur :

```bash
uv run --locked python run.py
```

Ouvrez ensuite <http://localhost:8080/app/>. Pour travailler sur l’interface,
gardez ce serveur actif et lancez Vite dans un second terminal :

```bash
cd frontend
npm run dev
```

L’interface de développement est disponible sur <http://localhost:5173> et
transmet les appels API au serveur sur le port 8080. Les prérequis des fenêtres
natives figurent dans le [guide desktop](docs/desktop-distribution.md).

## Se repérer dans le code

| Emplacement | Contenu |
| --- | --- |
| `animelab/` | Moteur Python, API FastAPI, services et données |
| `frontend/src/` | Interface Vue 3 et TypeScript |
| `frontend/src/locales/` | Traductions de l’interface |
| `android/` | Application Android, ponts natifs et moteur d’extensions APK |
| `tests/` | Tests Python et régressions |
| `frontend/tests/` | Tests unitaires de l’interface |
| `scripts/` | Vérifications, outils de build et de distribution |
| `docs/` | Guides, architecture, études et résultats de validation |
| `.github/workflows/` | CI, validations Android et releases |

Consultez l’[architecture](docs/architecture/README.md) pour les interactions
entre les composants. Pour les traductions, conservez les clés et paramètres
des messages existants et vérifiez le résultat dans l’interface.

## Vérifier les changements

Utilisez les contrôles adaptés à votre contribution. Pour une correction de bug,
ajoutez un test de régression lorsque le comportement peut être automatisé.
Pour une modification visuelle, joignez une capture et indiquez les tailles
d’écran testées. Pour la documentation seule, vérifiez les liens, chemins et
commandes concernés.

Depuis la racine, après l’installation des dépendances :

```bash
uv run --locked python scripts/check.py quality
uv run --locked python scripts/check.py frontend
uv run --locked python scripts/check.py python
```

Le contrôle `frontend` construit l’interface, nécessaire avant le contrôle
`python`. Ce dernier utilise une bibliothèque, une base et des dossiers
temporaires : privilégiez ce runner aux appels directs à pytest avec votre
environnement personnel. Pour cibler un sujet, par exemple les sous-titres :

```bash
uv run --locked python scripts/check.py python -k subtitle
```

Pour exécuter tous les contrôles, y compris les tests dans Chromium, installez
d’abord le navigateur de test :

```bash
cd frontend
npx playwright install --with-deps chromium
cd ..
uv run --locked python scripts/check.py all
```

L’installation de Chromium peut télécharger des fichiers volumineux et demander
des droits administrateur pour les dépendances système. Elle est nécessaire pour
les tests navigateur, pas pour une simple correction documentaire.

Le [guide de développement](docs/development.md) détaille Ruff, mypy, ESLint,
Prettier, TypeScript et les contrôles individuels. Si un test ne peut pas être
exécuté sur votre plateforme, signalez-le dans la PR avec la raison.

## Extensions et validation Android

AnimeLab utilise des recettes Python sur desktop/serveur et un moteur
expérimental d’APK originaux sur Android. Un succès sur une plateforme ne prouve
pas la compatibilité sur l’autre. Documentez les opérations vérifiées et les
limites restantes ; consultez le [guide des extensions](docs/extension-recipes.md)
et l’[état de validation Android](docs/studies/aniyomi-anikku/UTILISATION.md).

Pour les builds APK de contribution, utilisez les workflows de validation dans
GitHub Actions. Le workflow
[Android extension APK runtime](.github/workflows/android-extensions.yml)
compile le moteur et exécute ses essais sur émulateurs. Les builds de validation
ne nécessitent pas la clé de signature de production ; ne demandez ni ne joignez
cette clé. La publication des releases est gérée par le mainteneur.

Un essai sur téléphone reste utile : indiquez modèle, version Android,
architecture, version d’AnimeLab et scénario testé. Distinguez les résultats sur
émulateur des résultats sur appareil physique.

Un nouveau moteur externe doit rester expérimental tant que ses critères
d’adoption ne sont pas démontrés et documentés. Les études et décisions existantes
sont regroupées dans [les dossiers d’étude](docs/studies/).

## Proposer une pull request

Ouvrez votre PR depuis la branche de votre fork vers `main` du dépôt AnimeLab.
Une PR en brouillon est bienvenue pour un travail encore incomplet.

- Gardez un objectif précis par PR ; évitez les reformatages sans rapport.
- Expliquez le problème, le comportement obtenu et les éventuelles limites.
- Reliez l’issue concernée, par exemple avec `Fixes #123` si la PR la résout.
- Listez les commandes de vérification exécutées et leurs résultats ; indiquez
  les contrôles non exécutés.
- Actualisez la documentation si l’utilisation ou la configuration change.
- Conservez les fichiers de verrouillage cohérents avec les dépendances.
  `requirements.txt` est généré : suivez le
  [guide de mise à jour](docs/development.md#dependency-changes).
- Ne versionnez pas les secrets, données personnelles, environnements virtuels,
  dépendances téléchargées ou fichiers de build générés.

Utilisez un titre clair, par exemple `fix(launcher): preserve the running server`
ou `docs: clarify Linux startup`. La CI complète les vérifications locales.
Consultez ses résultats et corrigez les échecs liés à votre changement avant
de demander la revue finale.

## Assistance par IA et licence

Vous pouvez vous aider d’un outil comme Codex. Lorsque cette assistance a joué
un rôle important, mentionnez-le brièvement dans la description de la PR.
Relisez, comprenez et vérifiez le code soumis ; vous restez responsable de votre
contribution. Ne transmettez pas de secrets ou de données privées à ces outils.

AnimeLab est distribué sous **GPL-3.0-only** : les contributions doivent être
compatibles avec la [licence du projet](LICENSE). Préservez les notices des
composants tiers et indiquez la provenance de tout code ou asset repris.
