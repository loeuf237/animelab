# AnimeLab

[English](README.md) | [Français](README.fr.md)

<img src="docs/branding/animelab-wordmark.png" alt="AnimeLab" width="360" />

[![CI](https://github.com/loeuf237/animelab/actions/workflows/ci.yml/badge.svg)](https://github.com/loeuf237/animelab/actions/workflows/ci.yml)
[![Version bêta](https://img.shields.io/github/v/release/loeuf237/animelab?include_prereleases)](https://github.com/loeuf237/animelab/releases)
[![Licence : GPLv3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

**AnimeLab** permet de découvrir, regarder, télécharger et organiser des épisodes d’anime depuis les sources prises en charge. L’application associe un moteur **Python / FastAPI** à une interface **Vue 3 / TypeScript**, disponible sur ordinateur, sur Android et dans un navigateur.

## Téléchargements

Choisissez un paquet dans les [releases GitHub](https://github.com/loeuf237/animelab/releases). Les téléchargements Android et desktop sont regroupés dans la même release.

**Toutes les versions actuelles sont des bêtas.** Les [notes de la v0.1.6-beta.3](docs/releases/v0.1.6-beta.3.md)
décrivent le moteur expérimental d’extensions APK Android, les changements des sessions WebView et les limites restantes.

| Plateforme | Paquet | Démarrage |
| --- | --- | --- |
| Windows x64 | Archive ZIP | Extrayez toute l’archive et lancez `AnimeLab.exe`. |
| Linux x64 | Archive TAR.GZ | Extrayez l’archive et lancez `./AnimeLab`. Nécessite glibc 2.35 ou plus récent. |
| macOS Intel / Apple Silicon | ZIP contenant une application | Choisissez l’architecture de votre processeur et ouvrez `AnimeLab.app`. **NON TESTÉ sur un Mac physique ; application non signée et non notariée.** |
| Android 10+ / ARM64 | APK signé, bêta | Installez l’APK. Le moteur Python et l’interface sont inclus ; aucun serveur sur ordinateur n’est nécessaire. |
| Navigateur / web mobile | Interface web | Démarrez le serveur ou le conteneur Docker, puis ouvrez son adresse. |

Les paquets desktop incluent Python, l’interface compilée, FFmpeg et ffprobe. Windows utilise WebView2 ; Linux utilise GTK/WebKit et peut ouvrir un navigateur installé si une fenêtre native n’est pas disponible.

Les versions desktop ouvrent un launcher natif à onglets. Choisissez l’interface, le port, les dossiers et les paramètres de téléchargement, puis cliquez sur **Launch**. Le launcher propose aussi des diagnostics, des paramètres de proxy, des sauvegardes et un arrêt propre. Consultez les [notes de la version 0.1.4](docs/releases/v0.1.4.md) et le [guide des outils desktop et de récupération](docs/desktop-distribution.md).

La prise en charge des appareils Android reste en **bêta**. Les [notes de la version 0.1.6-beta.3](docs/releases/v0.1.6-beta.3.md) expliquent le moteur APK expérimental, les essais sur émulateurs et la validation sur appareils physiques encore attendue. Les fichiers de release incluent les empreintes de contrôle et les informations de build.

Dans les navigateurs compatibles, installez l’interface web comme PWA avec l’option d’installation ou **Ajouter à l’écran d’accueil**. Le serveur AnimeLab doit rester disponible.

## Démarrer l’application sur ordinateur

**Si votre dossier contient `desktop.py`, `pyproject.toml` et un répertoire `animelab/`, vous disposez du code source.** Ouvrez un terminal dans ce dossier et exécutez :

```bash
uv run --locked --group desktop python desktop.py
```

Cette commande fonctionne sous Linux et Windows et installe les dépendances desktop verrouillées si nécessaire. Le répertoire `animelab/` est le paquet Python, pas un exécutable. Consultez [Exécuter depuis les sources](#exécuter-depuis-les-sources) pour les prérequis et la compilation de l’interface nécessaires avant de démarrer le moteur.

Sous Linux, vous pouvez aussi lancer **`./launcher.sh`** depuis la racine du dépôt. Le script ouvre le launcher, installe les dépendances Python desktop verrouillées si nécessaire et compile l’interface si elle manque (Node.js/npm requis). Exécutez `./launcher.sh --help` pour les options de démarrage, d’état, d’arrêt et d’autotest du launcher.

Les instructions Linux et Windows suivantes concernent les **archives téléchargées depuis les releases**, qui contiennent un exécutable `AnimeLab` ou `AnimeLab.exe`.

Téléchargez le paquet de votre plateforme depuis les [releases GitHub](https://github.com/loeuf237/animelab/releases) et **extrayez toute l’archive**. Conservez l’exécutable à côté des fichiers et dossiers fournis. Ces paquets incluent les dépendances Python et l’interface compilée ; vous n’avez pas besoin d’installer Python, Node.js ou uv.

### Linux

Extrayez l’archive Linux x64 TAR.GZ, puis ouvrez un terminal dans le dossier extrait contenant `AnimeLab` et exécutez :

```bash
chmod +x AnimeLab
./AnimeLab
```

Les versions Linux nécessitent glibc 2.35 ou plus récent, par exemple Ubuntu 22.04 ou une version ultérieure.

### Windows

Extrayez l’archive Windows x64 ZIP, puis double-cliquez sur **`AnimeLab.exe`** dans le dossier extrait. Vous pouvez aussi ouvrir PowerShell dans ce dossier et exécuter :

```powershell
.\AnimeLab.exe
```

### Utiliser le launcher

Le launcher s’ouvre en premier. Choisissez l’interface, le port et le dossier de téléchargement, puis cliquez sur **Launch** pour démarrer le moteur et ouvrir l’application. Choisissez le mode navigateur pour utiliser votre navigateur installé ; une fenêtre native intégrée nécessite les bibliothèques WebView de la plateforme.

Utilisez l’adresse affichée par le launcher. Si le port demandé est occupé, AnimeLab choisit un port libre : l’adresse peut donc être différente de `http://localhost:8080/`.

Fermer la fenêtre de configuration laisse le serveur démarré en fonctionnement. Utilisez **Stop** pour l’arrêter. Pour rouvrir le launcher, exécutez `./AnimeLab --admin` sous Linux ou `.\AnimeLab.exe --admin` dans PowerShell sous Windows. Utilisez `--launch` à la place pour démarrer directement avec les préférences enregistrées.

Depuis le code source, suivez la section [Exécuter depuis les sources](#exécuter-depuis-les-sources) ci-dessous, notamment la compilation de l’interface et l’installation des dépendances desktop. Consultez le [guide des outils desktop et de récupération](docs/desktop-distribution.md) pour le dépannage et les commandes supplémentaires.

## Fonctionnalités principales

- **Parcourir et rechercher :** sources intégrées French-Manga, VoirAnime et AnimePahe, ainsi que les sources importées prises en charge. Dernières sorties, titres populaires, genres et tags dépendent des capacités de chaque source.
- **Regarder :** streaming et lecture locale, sous-titres, choix de qualité disponibles et progression enregistrée par épisode.
- **Télécharger :** téléchargements individuels ou en lot, file d’attente, pause/reprise, limites de débit, traitement des sous-titres et vérifications d’intégrité.
- **Séparer les versions :** les sélections VF, VOSTFR et VO disposent d’identités et de noms de fichiers distincts pour éviter de s’écraser mutuellement.
- **Organiser :** favoris, historique, suivi automatique des épisodes et organisation optionnelle des dossiers pour Plex/Jellyfin.
- **Utiliser sur mobile :** interface adaptative en français et en anglais, thèmes clair/sombre et recherche globale avec **Ctrl+K / Cmd+K**.

Sur Android, les vidéos terminées peuvent être exportées dans le stockage partagé. Un export échoué peut être relancé sans télécharger à nouveau la vidéo.

## Serveur partagé et comptes

Un mode serveur partagé optionnel propose des comptes gérés par l’administrateur,
des codes d’invitation et de récupération, des permissions, ainsi que des
bibliothèques, sessions de sources et téléchargements privés. Il fonctionne
depuis les sources ou Docker ; l’onglet Authentication du launcher desktop permet
aussi d’activer des comptes en local. Le mode personnel desktop/Android reste le
mode par défaut. Consultez la [configuration et la sécurité du serveur partagé](docs/shared-server.md)
pour l’initialisation, le déploiement HTTPS, les limites de ressources et les essais manuels.

## Sources et extensions

Importez un dépôt compatible Aniyomi depuis **Sources → Extensions**, puis activez les sources souhaitées. Les contrôles de disponibilité et la configuration des recettes aident à diagnostiquer les échecs.

Plusieurs dépôts peuvent coexister et l’actualisation de leurs catalogues préserve les versions et recettes installées. Le moteur d’APK Android originaux est disponible dans les builds de validation pendant que ses essais d’interopérabilité sont complétés. Consultez le [guide d’utilisation et l’état de validation des extensions](docs/studies/aniyomi-anikku/UTILISATION.md) pour l’installation, la confiance, les paquets partagés et les limites actuelles.

Sur desktop/serveur, AnimeLab extrait des sélecteurs et constantes de requêtes depuis les APK, puis exécute des recettes sérialisables avec un interpréteur Python commun. Il n’existe pas d’adaptateurs d’exécution propres à chaque source. Les recettes peuvent décrire du HTML, des catalogues JSON, des épisodes AJAX, des tableaux littéraux de lecteurs et des redirections. Certaines sources connues utilisent des plans de compatibilité déclaratifs pour compléter les constantes extraites.

Un APK contient du code Kotlin compilé, **pas une recette de scraping portable**. Le moteur de recettes desktop/serveur n’exécute pas le bytecode Android : une logique Kotlin arbitraire, des requêtes chiffrées et des parseurs non pris en charge ne peuvent pas être convertis automatiquement en recettes complètes. La compatibilité dépend donc des opérations prises en charge par l’interpréteur et du site externe. Les builds de validation Android utilisent un hôte natif distinct pour les APK originaux installés, avec les limites de validation indiquées ci-dessus. Consultez [l’exécution des recettes et ses limites](docs/extension-recipes.md).

Si un site bloque l’accès ou demande une vérification, AnimeLab propose un lien pour l’ouvrir manuellement et des commandes de nouvelle tentative. Les fenêtres de vérification prises en charge peuvent récupérer les cookies une fois la vérification terminée. Ouvrir un simple onglet dans un navigateur ne transfère pas ses cookies vers AnimeLab. Les paramètres permettent de configurer un proxy et une rotation optionnelle ; cela ne garantit pas l’accès au site.

## Exécuter depuis les sources

Prérequis :

- **Python 3.12 ou 3.13** ; ces versions sont couvertes par la CI.
- **Node.js 22 LTS (22.13+) et npm** pour compiler et vérifier l’interface.
- **FFmpeg et ffprobe** sur le `PATH` pour le traitement multimédia et l’intégration vérifiée des sous-titres.
- **uv 0.13.1**, le gestionnaire de dépendances Python ([installation](https://docs.astral.sh/uv/getting-started/installation/)).

Clonez le dépôt et installez l’environnement Python verrouillé :

```bash
git clone https://github.com/loeuf237/animelab.git
cd animelab
uv sync --locked
```

uv sélectionne Python 3.13 à partir de `.python-version` et le télécharge si nécessaire. Aucune activation d’environnement virtuel n’est requise ; les mêmes commandes fonctionnent dans PowerShell.

Installez les dépendances et compilez l’interface :

```bash
cd frontend
npm ci
npm run build
cd ..
```

Choisissez ensuite comment démarrer l’application depuis la racine du dépôt. Recompilez l’interface après toute modification de ses sources.

### Launcher desktop (Linux et Windows)

Installez les dépendances desktop et ouvrez le launcher. Ces commandes fonctionnent dans un terminal Linux et dans PowerShell sous Windows :

```bash
uv sync --locked --group desktop
uv run --locked --group desktop python desktop.py
```

Choisissez les paramètres, puis cliquez sur **Launch**. Le mode navigateur utilise votre navigateur installé. Pour une fenêtre native intégrée, consultez les prérequis WebView de votre plateforme dans le [guide des paquets desktop](docs/desktop-distribution.md).

### Serveur web

Pour démarrer directement le serveur :

```bash
uv run --locked python run.py
```

Ouvrez **[http://localhost:8080/app/](http://localhost:8080/app/)**.

Vue est l’unique interface web. Les anciens favoris (`/downloads`, `/settings`,
`/anime`, `/search`, etc.) redirigent vers l’écran correspondant de l’application
SPA en conservant leurs paramètres de requête. Les anciennes pages Jinja,
leurs scripts et leurs styles ne sont plus distribués.

L’environnement verrouillé par défaut permet d’exécuter le serveur web ; il n’installe pas les dépendances natives desktop ni celles de compilation Android.

### Configuration et données

Les paramètres de l’application gèrent la langue, les téléchargements, les sources et les proxys. Depuis les sources, des variables d’environnement permettent aussi de configurer le serveur :

| Variable | Rôle | Valeur par défaut |
| --- | --- | --- |
| `ANIMELAB_HOST` | Adresse d’écoute du serveur | `127.0.0.1` |
| `ANIMELAB_CHROMIUM_PATH` | Exécutable Chromium ou dérivé installé, pour la vérification des sources | Détection automatique |
| `ANIMELAB_CHROMIUM_HEADLESS` | Exécuter Chromium sans affichage pour la vérification | `false` |
| `ANIMELAB_ALLOWED_HOSTS` | Hôtes HTTP acceptés, séparés par des virgules, sans protocole ni port | `127.0.0.1,localhost` |
| `ANIMELAB_PORT` | Port HTTP | `8080` |
| `ANIMELAB_RELOAD` | Recharger le serveur de développement après modification du code | `true` |
| `ANIMELAB_DOWNLOAD_DIR` | Destination des téléchargements | `~/Downloads/AnimeLab` sur desktop |

Seuls les hôtes HTTP locaux sont acceptés par défaut ; les autres reçoivent une erreur HTTP 400. Pour un accès sur le réseau local ou via un reverse proxy, listez explicitement les adresses IP ou noms de domaine utilisés pour joindre AnimeLab, par exemple `ANIMELAB_ALLOWED_HOSTS=127.0.0.1,localhost,192.168.1.50,anime.example.org`. Cette configuration fonctionne aussi avec Docker Compose. Définir uniquement `ANIMELAB_HOST=0.0.0.0` n’autorise pas les autres hôtes. Les sous-domaines peuvent être autorisés avec `*.example.org` ; `*` désactive la validation des hôtes et doit être évité. Il s’agit des hôtes utilisés pour accéder à l’application, pas des domaines des sources d’anime.

Pour un usage local sans rechargement automatique, sous Linux/macOS :

```bash
ANIMELAB_HOST=127.0.0.1 ANIMELAB_RELOAD=false uv run --locked python run.py
```

AnimeLab s’appelait auparavant **Animan**. Le paquet Python se nomme désormais `animelab`. Le moteur privilégie les variables `ANIMELAB_*` et accepte les anciens alias `ANIMAN_*`. Les dossiers de données `.animan` et l’identifiant Android `com.animan.app` sont conservés pour assurer la compatibilité. Les paramètres desktop et la bibliothèque sont enregistrés dans `~/.animan` ; Android utilise son stockage privé et exporte séparément les médias terminés.

Les nouveaux téléchargements et exports Android partagés utilisent par défaut
`Downloads/AnimeLab`. Les fichiers existants, les chemins des tâches enregistrées
et les destinations personnalisées sont préservés. Consultez les
[anciens identifiants restants et les options de migration](docs/legacy-identifiers.md).

## Docker

Depuis le dépôt cloné, avec Docker Compose installé :

```bash
docker compose up -d --build --wait
```

Ouvrez **[http://localhost:8080/app/](http://localhost:8080/app/)**. Le conteneur inclut l’interface compilée et les outils multimédias. Des volumes nommés conservent la bibliothèque, les paramètres et les téléchargements.

Arrêtez-le avec `docker compose down`. Consultez le [guide Docker](docs/docker.md) pour les dossiers de téléchargement visibles depuis l’hôte, les sauvegardes, les ports et l’accès réseau.

## Développement et contributions

Commencez par le guide de contribution ([Français](CONTRIBUTING.md) /
[English](CONTRIBUTING.en.md)) pour les signalements de bugs, l’installation,
la validation et les pull requests. Les contributions en français et en anglais
sont les bienvenues.

**Nous recherchons des contributeurs :** refonte de l’écran de chargement Android,
détection des mises à jour et téléchargement automatique, correction des
téléchargements en double (French-Manga et autres sources affectées), validation
des extensions Aniyomi/Anikku, nouvel onglet **Outils** pour le sous-titrage et
la création de MKV multipistes audio, refonte de la page Extensions et documentation.
Nous recherchons aussi des thèmes, un choix de dossier Android au premier
démarrage, des améliorations du lecteur vidéo, une meilleure gestion de la
bibliothèque et une lecture hors ligne fiable sur Android.
Il s’agit de chantiers ouverts : leurs objectifs et critères de validation sont
décrits dans l’appel à contributions ([Français](docs/contribution-priorities.md) /
[English](docs/contribution-priorities.en.md)). Les propositions de fonctionnalités
et d’architecture sont les bienvenues. Contactez le mainteneur sur
[Telegram — @loeuf237](https://t.me/loeuf237).
Les tâches publiées sont regroupées dans le
[suivi des contributions #12](https://github.com/loeuf237/animelab/issues/12).

Le moteur Python se trouve dans `animelab/` ; le packaging desktop utilise
`animelab.spec`. Consultez les [notes sur le nom du paquet et la compatibilité](docs/package-namespace.md).

Les signalements de bugs, traductions, adaptateurs de sources, améliorations de l’interface et essais sur appareils sont les bienvenus. [Ouvrez une issue](https://github.com/loeuf237/animelab/issues) en indiquant les étapes de reproduction, la plateforme et la version de l’application ; discutez des changements importants avant de soumettre une pull request. Retirez les cookies, identifiants de connexion et URL privées des diagnostics.

Pour développer l’interface, gardez le serveur Python actif et lancez Vite dans un autre terminal :

```bash
cd frontend
npm run dev
```

Vite sert l’interface à l’adresse **http://localhost:5173** et transmet les requêtes API au port **8080**.

La [CI](.github/workflows/ci.yml) s’exécute sur les pushes et les pull requests. Elle vérifie Python, la compilation de l’interface, les mises en page adaptatives, la persistance Docker et les ressources Android. Elle applique aussi les contrôles Ruff, mypy sur un périmètre progressif, ESLint, Prettier et Vue/TypeScript. Le workflow de release unifié appelle la compilation Android et publie toutes les plateformes ensemble après validation.

Après l’installation depuis les sources décrite ci-dessus, exécutez tous les contrôles de développement depuis la racine du dépôt :

```bash
cd frontend
npx playwright install --with-deps chromium
cd ..
uv run --locked python scripts/check.py all
```

Le runner exécute les contrôles de code, le typage, les tests unitaires, la compilation de l’interface, les tests Python et les tests navigateur. Les tests Python utilisent un dossier personnel, une base, un cache et un dossier de téléchargement temporaires. Pour ne lancer que les tests backend, après compilation de l’interface, utilisez **`uv run --locked python scripts/check.py python`** ; la CI emploie la même commande avec une option de rapport JUnit.

Les tests partagent une fixture DNS hors ligne dans `tests/conftest.py` ; les adresses numériques et les connexions de boucle locale restent utilisables et les tests de sécurité DNS peuvent la remplacer. Un appel direct à `python -m pytest tests` ignore le test de service de la SPA si `frontend/dist/index.html` est absent. Le runner isolé et la CI exigent toujours cette compilation : son absence fait échouer la validation.

Les dépendances Python, y compris les outils de développement, sont verrouillées dans `uv.lock` ; `requirements.txt` est un export généré des seules dépendances d’exécution pour pip et Docker. Les dépendances de l’interface sont verrouillées dans `frontend/package-lock.json`. Consultez le [guide de développement](docs/development.md) pour les prérequis système, les contrôles individuels, les mises à jour des dépendances et le périmètre actuel du typage et des vérifications de code.

## Documentation

- [Architecture, diagrammes UML et plan d’amélioration](docs/architecture/README.md)
- [Distribution desktop](docs/desktop-distribution.md) et [guide de build et de stockage Android](docs/android-distribution.md)
- [Étude et plan d’implémentation de la gestion des extensions Aniyomi/Anikku](docs/studies/aniyomi-anikku/README.md)
- [Configuration Docker](docs/docker.md)
- [Validation de l’interface mobile](docs/mobile-ui.md) et [étude des fournisseurs de proxys](docs/proxy-providers.md)
- [Notes de version](docs/releases/) et [éléments graphiques](docs/branding/README.md)

## Licence

AnimeLab est un logiciel libre sous **GNU General Public License, version 3 uniquement** (`GPL-3.0-only`). Vous pouvez l’utiliser, le modifier et le redistribuer selon ces conditions. Les versions redistribuées à partir d’AnimeLab doivent respecter la GPLv3, notamment ses obligations relatives au code source correspondant. Le logiciel est fourni sans garantie.

Consultez [LICENSE](LICENSE) pour les conditions complètes et [NOTICE](NOTICE) pour la notice du projet et l’emplacement des sources. Les composants tiers conservent leurs propres licences ; consultez les [notices des composants tiers Android](android/app/src/main/assets/THIRD-PARTY-NOTICES.txt) et celles incluses dans les paquets de release.

Pour le partage des sessions de navigateur, les chemins Chromium et la configuration d’un serveur sans interface graphique, consultez le [guide de vérification par navigateur](docs/browser-verification.md).
