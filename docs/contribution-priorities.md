# AnimeLab recherche des contributeurs

[Français](contribution-priorities.md) | [English](contribution-priorities.en.md)

Nous recherchons des personnes pour améliorer AnimeLab : design, développement
Android/Kotlin, Python/FastAPI, Vue/TypeScript, tests sur appareils, traductions
et documentation. Une maquette, un scénario de reproduction ou un retour de
test précis est déjà une contribution utile.

Les chantiers ci-dessous sont des **travaux proposés**, à préciser avec les
contributeurs. Ils ne constituent pas une liste de fonctionnalités terminées.
Les propositions de fonctionnalités et d’architecture sont les bienvenues.

Pour participer, ouvrez ou rejoignez une
[issue](https://github.com/loeuf237/animelab/issues) en indiquant le chantier
concerné et ce que vous souhaitez prendre en charge. Pour échanger directement
avec le mainteneur : **[Telegram — @loeuf237](https://t.me/loeuf237)**.
Consignez les décisions techniques et les résultats de tests dans l’issue ou
la PR afin que les autres contributeurs puissent les retrouver.

Consultez le [guide de contribution](../CONTRIBUTING.md) pour l’installation,
les vérifications et les pull requests.

## 1. Repenser l’écran de chargement Android

**Objectif :** rendre le démarrage plus agréable et compréhensible, avec une
présentation cohérente avec l’identité d’AnimeLab.

Nous recherchons des propositions de design puis une implémentation Android.
Présenter les étapes réellement connues du démarrage, gérer une attente longue
et proposer une récupération en cas d’échec. Éviter un pourcentage inventé qui
donne une fausse impression de progression.

**Validation attendue :** maquettes et captures, lisibilité sur petits écrans,
thèmes clair/sombre, accessibilité et essais d’un démarrage normal, lent et en
erreur sur Android. Point d’entrée :
[`MainActivity.kt`](../android/app/src/main/java/com/animan/app/MainActivity.kt).

## 2. Détecter et télécharger automatiquement les nouvelles versions

**Objectif :** proposer dans l’application un parcours de mise à jour inspiré
de Mihon/Aniyomi, en commençant par Android : détection d’une nouvelle version,
présentation des changements, téléchargement automatique configurable et
installation via le mécanisme Android.

Le module doit sélectionner le bon paquet pour la plateforme et l’architecture,
comparer correctement les versions et distinguer les canaux bêta/stable. Le
statut GitHub « pre-release » ne doit pas être le seul critère : une version
bêta peut être publiée comme release ordinaire.

**Validation attendue :** tester l’absence de mise à jour, une nouvelle version,
les canaux, une erreur réseau et un téléchargement interrompu. Respecter les
préférences réseau et de téléchargement, vérifier l’intégrité du fichier et
la compatibilité de signature avant installation, conserver les données et
laisser Android demander sa confirmation normale. Une mise à jour téléchargée
doit rester distincte d’une mise à jour effectivement installée.

## 3. Corriger les téléchargements et enregistrements en double

**Problème signalé :** un même fichier peut être téléchargé ou enregistré
plusieurs fois avec la source intégrée **French-Manga**. Il faut reproduire le
cas, identifier l’étape responsable et vérifier si d’autres sources sont affectées.

La correction doit couvrir les demandes répétées, les ajouts en lot ou
automatiques, les requêtes concurrentes, la reprise après redémarrage et
l’enregistrement/export du fichier final. Examiner les protections existantes
dans [`download_manager.py`](../animelab/services/download_manager.py) avant
d’ajouter un mécanisme parallèle.

**Validation attendue :** tests de régression montrant qu’une même demande ne
crée pas plusieurs tâches ou copies finales involontaires, y compris après une
relance. Préserver les téléchargements volontairement distincts : VF/VOSTFR/VO,
qualités et profils de sortie. Ne pas identifier un épisode uniquement par son
nom de fichier, son numéro ou une URL vidéo temporaire. Ajouter des cas pour
French-Manga et les autres chemins concernés ; conserver une action explicite
si l’utilisateur veut retélécharger.

## 4. Vérifier l’intégration des extensions Aniyomi/Anikku

**Objectif :** vérifier et améliorer la compatibilité des véritables APK
d’extensions sur Android, avec des résultats reproductibles.

Tester les paquets déjà installés, l’installation et la mise à jour depuis un
dépôt, la confiance, les sources multiples, la recherche, les catalogues,
épisodes, filtres, préférences, résolution vidéo, lecture et téléchargement.
Vérifier aussi le parcours de session WebView puis la reprise de l’extension,
sans requêtes d’émulation concurrentes pendant la vérification.

**Validation attendue :** une matrice précisant version d’AnimeLab, APK/version,
version Android, appareil ou émulateur, opérations réussies et erreurs. Distinguer
un blocage du site d’une incompatibilité du moteur. La présence d’un paquet ne
prouve pas la réussite du parcours complet. Les recettes desktop/serveur doivent
être documentées séparément du moteur APK Android.

Partir de l’[étude existante](studies/aniyomi-anikku/README.md) et du
[guide de validation](studies/aniyomi-anikku/UTILISATION.md). Les APK de test sont
construits dans GitHub Actions ; les essais sur téléphone restent nécessaires.

## 5. Créer l’onglet Outils et un atelier de sous-titrage

**Objectif :** ajouter **Outils** dans la barre de navigation et y
regrouper des outils multimédias. Le premier chantier est un outil complet de
sous-titrage pour des séries ou épisodes déjà téléchargés.

Le parcours souhaité comprend :

- sélectionner une série ou des épisodes de la bibliothèque ;
- rechercher, comparer et télécharger des sous-titres correspondants, ou les
  importer depuis des fichiers ;
- choisir langue, épisode et version, prévisualiser, corriger le décalage et
  gérer les pistes et les outils/fournisseurs disponibles ;
- traduire les sous-titres avec une **clé d’API personnelle** Gemini, DeepL,
  OpenAI ou un autre fournisseur proposé ;
- exporter les sous-titres séparément ou les intégrer à une sortie vidéo avec
  les profils compatibles.

Réutiliser les services de sous-titres et de profils déjà présents dans
`animelab/services/`, plutôt que créer une seconde chaîne indépendante. Prévoir
une navigation adaptée au mobile comme au bureau.

**Validation attendue :** un premier parcours complet sur une vidéo locale,
sans retélécharger la vidéo, puis l’intégration des fournisseurs. Conserver les
originaux, le découpage et les timestamps lors de la traduction, signaler les
pertes éventuelles de style et vérifier la synchronisation à l’export. Les clés
restent privées et propres à l’utilisateur ; l’envoi du texte à un fournisseur
doit être explicite. Afficher les erreurs, quotas et coûts annoncés par le
fournisseur et permettre l’annulation ou la reprise des traitements.

## 6. Ajouter un atelier audio et la création de MKV multipistes

**Objectif :** compléter Outils avec un parcours de téléchargement et d’édition
de pistes audio provenant de sources fournies par des extensions audio, puis
les assembler avec une vidéo existante dans un **MKV multipistes audio**.

Commencer par une proposition d’architecture précisant ce qu’est une extension
audio prise en charge, ses contrats de données et ses différences avec une
extension vidéo. Cette compatibilité reste à définir et à valider.

Le parcours visé couvre la découverte et le téléchargement des pistes, leur
préécoute, la correspondance avec l’épisode, le choix des langues, le décalage,
les ajustements audio et l’assemblage. Une proposition peut préciser les étapes
ultérieures de l’éditeur.

**Validation attendue :** un MKV lisible contenant plusieurs pistes audio
sélectionnables, avec langues, titres et piste par défaut corrects, une durée
et une synchronisation vérifiées. Réutiliser les contrats média, profils de
sortie et traitements FFmpeg existants ; préserver les originaux. Procéder par
petites étapes testables avant d’étendre l’outil.

## 7. Repenser la page Extensions

**Objectif :** améliorer son ergonomie et son apparence en s’inspirant de
Mihon/Aniyomi : navigation claire, listes lisibles et actions faciles à repérer.

Proposer des maquettes pour les dépôts, extensions installées/disponibles,
mises à jour, recherche et filtres de langue. Rendre visibles les états utiles :
installée, désactivée, confiance à approuver, mise à jour disponible, erreur ou
vérification nécessaire. Distinguer clairement un dépôt, une extension et les
sources qu’elle fournit.

**Validation attendue :** captures mobile/bureau, thèmes clair/sombre,
accessibilité et parcours d’ajout de dépôt, installation, activation, mise à
jour et récupération après erreur. Une amélioration visuelle ne doit pas
supprimer les informations de compatibilité ou les confirmations nécessaires.
La référence visuelle sert d’inspiration ; préserver l’identité d’AnimeLab et
respecter les licences des éléments réutilisés.

## 8. Améliorer le README et la documentation

**Objectif :** aider un nouvel utilisateur à installer, démarrer et comprendre
AnimeLab, puis permettre à un contributeur de reproduire les vérifications.

Nous recherchons des guides Linux/Windows/Android/macOS, captures actualisées,
exemples, traductions français/anglais et explications d’architecture. Clarifier
les différences entre release et sources, les limites connues, les extensions
et le dépannage. Rechercher les informations obsolètes ou contradictoires.

**Validation attendue :** liens fonctionnels, commandes vérifiées sur les
plateformes annoncées et distinction explicite entre fonctions disponibles,
expérimentales et envisagées. Un tutoriel suivi et corrigé par une personne
découvrant le projet est particulièrement utile.

## Proposer une autre idée

Ces chantiers n’excluent aucune proposition pertinente. Décrivez le besoin,
un exemple d’usage, les plateformes concernées, les compromis et une première
étape vérifiable. Une refonte d’architecture doit expliquer les problèmes
qu’elle résout et comment migrer les données et comportements existants.

Les personnes qui testent, dessinent, traduisent et documentent sont aussi
bienvenues que celles qui écrivent le code. Prenez un périmètre que vous pouvez
valider et indiquez les points pour lesquels vous avez besoin d’aide.
