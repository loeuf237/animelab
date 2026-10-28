# AnimeLab — étude sous-titres et N_m3u8DL-RE

**Étude initiale du 27 octobre 2026**, sur la révision `1cea1983ec741c502cf5241d3b5ebdfacb38330a` d’AnimeLab. **Statut : socle et sorties P1–P9 implémentés localement (validations fournisseurs réelles P8/P9 en attente) ; intégration N_m3u8DL-RE encore proposée.** Les constats chiffrés décrivent la révision initiale.

[Ouvrir le dossier visuel hors ligne](index.html) · [Inventaire des diagrammes et références](manifest.json) · [Preuve FFmpeg locale](local-proof.json)

**Réalisation : [priorités d’implémentation P1 à P15](PRIORITES_IMPLEMENTATION.md)** — ordre de travail, dépendances, critères de validation et décisions de passage. Cette feuille de route précise les lots de la section 6 ; les diagrammes restent une proposition d’architecture.

**Suivi : [implémentation P1–P5](IMPLEMENTATION_P1_P5.md)** — contrats, propagation des pistes, profils persistants, adaptateurs de transfert et supervision média. Le diagnostic et les chiffres ci-dessous décrivent la révision d’origine ; le compte rendu distingue les changements réalisés et les validations restantes.

**Nouveautés : [implémentation P6–P7](IMPLEMENTATION_P6_P7.md)** — choix des pistes MKV/SIDECAR, incrustation MP4 desktop/serveur, offsets, polices, reprise locale et résultats des tests. Le hardsub Android reste réservé à P14.

**P9 : [SubDL, correspondances et synchronisation réversible](IMPLEMENTATION_P9.md)** — API v2, outil Alass optionnel sur référence locale, [mesures synthétiques](subtitle-sync-proof.json), originaux préservés et validation fournisseur réelle en attente.

**P8 : [import local et OpenSubtitles](IMPLEMENTATION_P8.md)** — aperçu, sélection d’épisode, provenance, quotas, secrets par compte et validation fournisseur réelle encore à effectuer.

**P10–P13 : [évaluation et décision de non-adoption](IMPLEMENTATION_P10_P13.md)** — binaire exécuté sur corpus synthétique sous Linux x64, défauts de reprise et de synchronisation reproduits ; P13/P15 non retenus pour cette version. Voir les [mesures](nm3u8dl-proof.json) et la [décision structurée](nm3u8dl-decision.json). Le diagnostic initial ci-dessous reste une référence historique ; ce bilan précise le résultat de l’expérimentation.

**P14–P15 : [hardsub Android et décision Bionic](IMPLEMENTATION_P14_P15.md)** — chemin JNI et validation conditionnelle implémentés localement ; tests Android/CI encore requis, P15 non retenu pour cette version.

## Décision proposée

**Oui aux nouveaux usages de sous-titres ; oui à une expérimentation N_m3u8DL-RE sur desktop/serveur ; non à son remplacement immédiat de tout le moteur sur toutes les plateformes.** Son meilleur apport est le transfert HLS/DASH et la sélection de pistes de manifestes. Le plus gros bénéfice immédiat pour les sous-titres vient cependant de la conservation des métadonnées des extensions et extracteurs, puis d’une véritable politique de sortie FFmpeg. Ces deux évolutions ne nécessitent pas N_m3u8DL-RE.

Séparer quatre responsabilités : **résoudre la vidéo**, **collecter ses pistes et les sous-titres externes**, **transférer**, **produire et vérifier la sortie**. N_m3u8DL-RE est un backend possible de la troisième responsabilité. FFmpeg reste indispensable, et yt-dlp conserve son rôle de repli d’extraction.

## 1. Ce qui existe réellement

Les références de symboles sont vérifiées par le générateur du dossier ; leurs liens et lignes figurent dans `manifest.json` et la galerie.

| Élément observé | Conséquence pour l’évolution |
| --- | --- |
| `DownloadManagerService` : 1 688 lignes ; `TransferWorker` : 1 154 ; `MediaPipeline` : 622 | Un découpage en étapes existe déjà. Extraire de vrais contrats à partir de ces étapes est plus utile qu’un second orchestrateur placé au-dessus. Les lignes ne mesurent pas à elles seules la complexité. |
| `TransferWorker._download_single_file` : HTTP Range, fichiers `.part`, métadonnées de reprise | Conserver ce chemin éprouvé pour les fichiers directs. |
| `TransferWorker._download_hls_segments_native` : HLS natif, fragments, AES-128 ; refus explicite de BYTERANGE et EXT-X-MAP | Lacune concrète où un backend spécialisé peut apporter un bénéfice. Pas de moteur DASH/MPD dédié identifié dans ce worker. |
| `MediaPipeline._download_subtitles` et `normalize_subtitles` : pistes externes SRT/VTT/ASS, chemins, langue, referer et récupération partielle | Étendre cette représentation au lieu d’introduire une collection parallèle. |
| `MediaPipeline._mux_subtitles_with_ffmpeg` : MKV, vidéo/audio copiés, sous-titres existants conservés, métadonnées, vérification puis publication | **Le MKV avec plusieurs sous-titres existe déjà.** Il manque surtout un choix explicite des pistes, un vrai profil de sortie et un traitement complet des pistes externes audio. |
| `YtDlpFallbackExtractor.extract` : `skip_download=True`, `extract_info(download=False)` | yt-dlp n’est pas ici le moteur principal de transfert. Le supprimer peut faire perdre des résolutions d’hébergeurs sans simplifier le transfert. |
| Le repli yt-dlp ne recopie pas `info['subtitles']` et réduit les formats à une URL | Point de perte à corriger ; les formats vidéo/audio séparés doivent aussi être conservés. |
| `RecipeRuntime.stream` renvoie surtout URL, serveur, qualité et format | Les recettes actuelles ne constituent pas une exécution universelle des APK Kotlin. Les plans pris en charge doivent apprendre à transporter pistes et en-têtes. |
| Android utilise `MediaBridge` JNI et `ffmpeg-kit-min:6.0.4` | La stratégie desktop sous-processus n’est pas automatiquement transposable dans l’APK. |

Ce constat est une lecture du dépôt, complétée par la preuve FFmpeg de la section 7 ; il ne signifie pas que toutes les sources Aniyomi ont été testées.

## 2. Les trois origines des sous-titres

### Pistes fournies par une source ou un manifeste

Aniyomi décrit officiellement un `Video` avec `subtitleTracks`, `audioTracks` et `headers` [S4]. Il faut préserver ces données **du résultat de l’extension jusqu’au plan de téléchargement et à la sortie**, pas seulement pendant la lecture.

Trois cas différents doivent être exposés : fichier externe référencé par l’extension ; piste découpée dans un HLS/DASH ; piste déjà incorporée au fichier vidéo. Une quatrième situation, le texte déjà incrusté dans les pixels de la vidéo source, ne fournit pas une piste récupérable : l’extraction par OCR serait un autre projet.

Pour les recettes reconnues : ajouter les champs de pistes, résoudre les URL relatives, conserver langue, label, rôle, format et en-têtes propres à chaque ressource. Une extension non interprétable reste explicitement non prise en charge. Ni N_m3u8DL-RE ni une liste de chaînes extraites d’un DEX ne remplacent une exécution complète de l’API Aniyomi.

### Sites dédiés

Créer un contrat `SubtitleProvider` avec des adaptateurs indépendants. Deux premiers candidats documentés :

- **OpenSubtitles.com REST**, avec clé d’application, authentification utilisateur suivant l’usage et quotas retournés par l’API. Télécharger via l’identifiant de fichier puis renouveler l’URL temporaire au besoin. Ne pas baser une nouvelle intégration sur l’ancien XML-RPC OpenSubtitles.org [S7].
- **SubDL API v2**, dont la documentation développeur décrit recherche et téléchargement avec une clé Bearer. Le site documente également une API v1 historique : choisir explicitement une version et tester son contrat, sans mélanger les deux [S8].

Ces fournisseurs doivent utiliser un client API qui respecte leur authentification et leur User-Agent applicatif. Notre client de navigation impose actuellement un User-Agent navigateur : réutiliser cette façade sans adaptation serait une erreur. La récupération des CDN reste soumise à la politique réseau du compte.

Aucun tarif ou quota numérique n’est figé dans cette proposition : les comptes, conditions et limites doivent être lus au moment de l’intégration. Aucun compte n’a été créé et aucune recherche authentifiée n’a été effectuée pendant l’étude.

Les critères de correspondance doivent être affichés : identifiant IMDb/TMDB quand connu, saison/épisode ou numéro absolu d’anime, langue, release/groupe, durée et FPS. Un même titre ne garantit pas une synchronisation correcte. Proposer un score explicable, un aperçu et un décalage manuel ; ne pas prétendre que la correction automatique des timestamps retrouve toujours le bon montage.

### Import local

Accepter SRT/VTT/ASS, en conservant l’original. Pour les téléchargements ZIP, extraire dans l’espace privé avec limites de taille/nombre de fichiers, contrôle des chemins et choix du bon épisode. Les secrets d’API et sessions restent propres au compte ; les quotas et erreurs fournisseur ne deviennent pas des erreurs du moteur vidéo.

## 3. MP4 hardsub et MKV multipiste

| Profil proposé | Résultat attendu | Coût / contraintes |
| --- | --- | --- |
| `MP4_HARD` | Une vidéo avec **une langue de sous-titres incrustée**, un audio choisi, aucune piste de sous-titres séparée | Réencodage vidéo obligatoire ; rendu libass, polices, encodeur et espace de travail nécessaires. H.264/AAC pour le profil de compatibilité proposé. |
| `MKV_SOFT` | Une vidéo, audios sélectionnés, plusieurs sous-titres activables, langue/titre/défaut/forcé | Copie des pistes vidéo/audio si compatibles ; généralement bien moins coûteuse. Conserver les styles ASS et joindre les polices lorsque disponibles. |
| `SIDECAR` | Vidéo et fichiers de sous-titres séparés | Utile pour récupérer uniquement le texte, corriger un décalage ou éviter un réencodage. |

Une vidéo avec du son possède normalement au moins **une piste vidéo et une piste audio** : « une seule piste » doit ici signifier que les sous-titres sont intégrés à l’image, pas qu’audio et vidéo seraient une unique piste technique.

Les filtres `subtitles`/`ass` de FFmpeg dépendent de libass [S5]. Une sortie hardsub ne peut pas utiliser `-c:v copy`. Conserver un master jusqu’à validation et selon une préférence de conservation ; l’incrustation n’est pas réversible à partir du seul MP4 final.

Ajouter un `OutputProfile` versionné : mode, vidéo/audio sélectionnés, piste de texte pour burn-in, offsets, conservation du style et des originaux. Le format SRT ne peut pas préserver toute la mise en forme ASS ; une conversion doit être explicite. Les métadonnées `forced` et `default` sont des propriétés distinctes. Les sous-titres bitmap demandent un chemin adapté, pas une conversion textuelle supposée.

**Android : obstacle confirmé statiquement.** Le fichier AAR local `ffmpeg-kit-min-6.0.4.aar` a été inspecté : sa configuration ARM64 contient `--disable-autodetect`, `--enable-mediacodec`, mais aucun `--enable-libass` ni `--enable-libx264`. La matrice de paquets amont distingue bien `min` des variantes contenant libass et des variantes GPL avec x264 [S9]. Il faut sélectionner/construire un package compatible avec le rendu et valider l’encodeur réellement disponible. La présence de MediaCodec n’établit pas la fiabilité d’un encodage H.264 matériel sur tous les appareils. Ne pas changer de variante pendant cette étude.

## 4. Apport et limites de N_m3u8DL-RE

Référence étudiée : **tag `v0.6.0-beta`**, publication indiquée par l’API GitHub au 28 juin 2026 ; projet CLI ciblant .NET 10 [S1–S3]. Les options de `main` ne sont pas assimilées à celles du tag : par exemple, les options récentes `--cookies` et `--no-config` visibles sur `main` ne figurent pas dans le parseur CLI du tag étudié. Le bandeau d’aide du README du tag contient une ancienne date : les fichiers projet et le tag ont servi à identifier la version.

| Besoin | Apport réel | Ce qui reste à AnimeLab |
| --- | --- | --- |
| HLS/DASH/MSS | Outil spécialisé, sélection vidéo/audio/sous-titres, fragments et assemblage | Choix du plan, session, contrôle de destination, état utilisateur et validation |
| Sous-titres des manifestes | Sélection `--select-subtitle`, mode `--sub-only`, sortie SRT/VTT, corrections temporelles | Conservation de provenance/style, choix utilisateur, synchronisation et normalisation cohérente |
| MKV multipiste | Peut déléguer le mux à FFmpeg/mkvmerge | Garder un seul responsable de la **sortie finale** pour éviter deux mux concurrents ; FFmpeg peut déjà intervenir dans l’assemblage interne des pistes |
| MP4 hardsub | Aucun remplacement du rendu vidéo FFmpeg identifié | Filtre, polices, encodeur et vérification visuelle |
| Extraction de pages et compatibilité Aniyomi | Ne remplace pas ces couches | Garder sources, recettes, extracteurs et repli yt-dlp |
| Fournisseurs de sous-titres | Ne recherche pas les catalogues OpenSubtitles/SubDL pour nous | `SubtitleProvider` et résolution d’identité de l’épisode |
| Pause / reprise | Le code réutilise des fragments trouvés sur disque | Vérifier l’intégrité et l’identité de représentation ; pas de garantie équivalente à notre `.part.resume.json` |
| Progression | Console Spectre, fichiers JSON de métadonnées | Pas de contrat d’événements JSON stable identifié dans le tag. Construire un adaptateur testé ; ne pas confondre métadonnées JSON et progression JSON. |
| Protection de site | En-têtes et proxy configurables | Le transport .NET n’est pas notre session curl_cffi/WebView ; cookies et User-Agent ne garantissent pas la même empreinte TLS |

Le code amont ignore certains fragments simplement s’ils existent : leur présence seule n’est pas une preuve d’intégrité. Le nom des répertoires temporaires dépend aussi de l’inventaire de pistes. Pause/reprise, réordonnancement du manifeste et renouvellement des URL exigent un véritable test de panne avant d’activer ce backend par défaut.

### Plateformes et poids

Les archives officielles couvrent nos quatre cibles desktop : Windows x64 environ **5,48 Mo**, Linux x64 **8,05 Mo**, macOS ARM64 **5,46 Mo** et x64 **5,94 Mo**. L’archive Android Bionic ARM64 est d’environ **5,76 Mo** [S2]. Ce sont des **tailles compressées amont**, pas l’augmentation mesurée de nos paquets ou de l’installation. Aucun binaire n’a été téléchargé ou exécuté pour cette étude.

Les builds natifs amont évitent de supposer qu’un SDK .NET doit être installé chez l’utilisateur ; leur autonomie et leurs bibliothèques restent à vérifier sur des machines propres. Épingler version et empreinte, conserver la notice MIT de l’outil [S10], produire les paquets dans GitHub Actions et mesurer les variations de taille avant publication.

**Android n’est pas impossible, mais reste un chantier séparé.** La release propose une cible Bionic indiquée pour Termux. Android 10+ interdit l’exécution directe de fichiers placés dans le répertoire privé inscriptible de l’app [S6]. Notre application utilise déjà JNI pour FFmpeg. Une intégration N_m3u8DL-RE nécessite une preuve de packaging/exécution compatible APK et des essais API 29/30/35, ABI, annulation, mémoire et 16 Ko ; ne pas compter sur un simple téléchargement du binaire dans `files/` suivi d’un `chmod`.

## 5. Architecture d’intégration recommandée

1. **`SourceResolver`** produit `ResolvedMedia` : ressources, toutes les pistes, protocole, qualité, rôle et référence à une session du compte. Corriger les pertes de métadonnées avant de changer le transfert.
2. **`SubtitleCoordinator`** agrège pistes de la source, manifeste, fichiers incorporés, fournisseurs et import. Une absence de piste doit être distinguée d’une extraction non prise en charge ou d’un quota épuisé.
3. **`TransferPlanner`** sélectionne un backend selon protocole et capacités constatées. `HttpRangeBackend` conserve les téléchargements directs. `NativeHlsBackend` reste disponible sur Android. `Nm3u8Backend` est optionnel, d’abord sur desktop et serveur pour les VOD validées.
4. **`DownloadBackend`** expose inventaire, démarrage, arrêt, progression et checkpoint. Déplacer les implémentations existantes progressivement derrière ce contrat, en conservant les méthodes de compatibilité pendant la migration.
5. **`OutputProcessor`** réalise une finalisation locale explicite : MKV multipiste, MP4 incrusté ou fichiers annexes. Un changement de mode ne doit pas retélécharger la vidéo. Le budget réseau et le budget d’encodage restent distincts.
6. **`IntegrityVerifier` + publication** vérifient durée, décodage, langues, disposition et nombre de pistes avant publication atomique et export Android. Pour le hardsub, vérifier le rendu réel, pas seulement l’absence de piste texte.

### Préserver le réseau et l’isolation

Une exécution externe ne doit pas contourner les sessions et restrictions introduites en v0.1.5. Une simple option `--custom-proxy` ne suffit pas : un tunnel HTTPS CONNECT ne reconstitue pas l’empreinte TLS de curl_cffi.

Pour les scénarios protégés/partagés, la cible est un **`ManifestRelay` local à développer**, avec capacité par tâche, qui réécrit manifestes, segments, clés et références vers des URL locales autorisées et récupère les originaux via `SourceHTTPService`. Pour DASH, cela inclut `BaseURL`, templates, périodes, plages et URL résolues. Cette couche a un coût réel : on ne peut pas promettre simultanément une intégration minimale et une parité réseau totale.

La preuve de concept doit d’abord utiliser des fixtures locales. Avant activation sur des sites externes : valider la couverture du relais et empêcher les requêtes qui lui échapperaient. Sinon conserver le backend existant pour ces sources. Ne pas exposer les cookies des sources ou secrets fournisseur dans argv, les logs ou l’interface ; utiliser des références de session et des fichiers privés éphémères si nécessaire. Révoquer les capacités lors de l’arrêt et de l’annulation. Les URL de téléchargement de fournisseurs et leurs CDN exigent également une politique explicite, sans ouvrir un proxy arbitraire.

### Reprise et données

Associer chaque tentative à son backend, sa version, son espace de travail et une empreinte de représentation. Une URL signée peut changer sans que le média change ; une représentation différente ne doit pas réutiliser aveuglément des fragments. Un backend ne récupère pas directement les `.part` d’un autre. Après échec du mux/burn-in, reprendre la finalisation à partir des pistes locales.

Le MCD est conceptuel : le compte représente le propriétaire, mais les bases privées ne sont pas fusionnées dans la passerelle. Évolution du MLD proposée : garder la tâche actuelle, puis ajouter des tables `media_track`, `task_track_selection`, `subtitle_asset`, `transfer_attempt` et `output_artifact`. La sélection porte l’offset, le rôle et les dispositions ; l’asset conserve format, source et empreinte. Identifiants de ressources et URL renouvelables sont distincts. Les anciens champs JSON sont migrés progressivement, sans réécriture destructive des tâches terminées.

## 6. Ordre de réalisation et critères de décision

| Lot | Travail | Critère de passage |
| --- | --- | --- |
| A — métadonnées | Conserver sous-titres/audio/en-têtes des recettes supportées, extracteurs et yt-dlp ; inventaire et choix des pistes | Fixture d’extension → téléchargement → mêmes langues et rôles dans le résultat ; aucune régression des sources actuelles |
| B — profils de sortie | MKV sélectionnable, hardsub desktop et fichiers annexes ; offsets et polices | Tests ffprobe et comparaison de rendu, annulation, reprise de finalisation, collisions et espace disque |
| C — fournisseurs | Un adaptateur API d’abord, puis second fournisseur ; identité d’épisode et choix manuel | Quota, URL expirée, archive, mauvais épisode/FPS et compte séparé testés |
| D — preuve N_m3u8DL-RE | Backend optionnel ; HLS AES-128, fMP4/BYTERANGE, DASH audio séparé, sous-titres segmentés ; relais et supervision | Arrêt réseau, fragment tronqué, renouvellement de session, reprise après redémarrage ; aucune requête hors politique |
| E — desktop/serveur | Packages Windows/Linux/macOS et Docker avec binaire épinglé | Taille installée, consommation, progression, groupes de processus et `ffprobe` vérifiés sur les runners ; Mac réel à prévoir |
| F — Android | FFmpeg compatible hardsub ; expérimentation Bionic/APK séparée | Preuve sur appareils/API/ABI, filtre/encodeur, consommation et annulation. Garder le backend natif jusqu’à validation. |

Pas de retrait immédiat de yt-dlp ni FFmpeg. Aucun gain de vitesse, pourcentage de réduction du code ou délai de livraison n’est annoncé sans benchmark. Pour décider de conserver N_m3u8DL-RE, mesurer surtout **le gain de couverture des flux, la fiabilité de reprise et la complexité déplacée vers l’adaptateur/relais**, puis les débits, RAM/CPU et taille des paquets. Si nos sources sont surtout des MP4 directs ou des HLS simples, l’ajout peut coûter plus qu’il ne rapporte.

## 7. Ce qui a été vérifié pendant l’étude

- Lecture des fichiers AnimeLab et références de symboles vérifiées automatiquement.
- Lecture de la release officielle N_m3u8DL-RE, du README et du code **au tag v0.6.0-beta** : options, progression, reprise de fragments, cibles Bionic et projet .NET.
- Inspection **statique** de la configuration FFmpeg contenue dans l’AAR Android déjà présent dans le cache local ; aucune installation ni reconstruction d’APK.
- Preuve **locale desktop** sur une vidéo synthétique de deux secondes : MP4 H.264/AAC, aucune piste de sous-titres, pixels modifiés par l’incrustation ; MKV avec une vidéo, deux audios `jpn`/`eng` et deux pistes texte `fra`/`eng`, dont le français par défaut. Détails et commandes dans `local-proof.json`. Les médias d’essai restent dans `/tmp`.
- Diagrammes SVG rendus et contrôlés ; galerie locale visualisable, zoomable et imprimable.

**Non vérifié :** exécution du binaire N_m3u8DL-RE, téléchargement sur un site réel, appel authentifié de fournisseurs, vitesse comparative, reprise après panne de ce binaire, intégration Android/Bionic et hardsub Android. Les composants verts des diagrammes sont des propositions, pas des fonctionnalités livrées.

## 8. Sources primaires

Consultées le 27 octobre 2026. Les pages `main` peuvent évoluer ; les références taguées sont préférées pour les options du binaire étudié.

- **S1** — [README N_m3u8DL-RE au tag v0.6.0-beta](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/README.en.md).
- **S2** — [Release officielle et plateformes](https://github.com/nilaoda/N_m3u8DL-RE/releases/tag/v0.6.0-beta), [métadonnées API](https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest).
- **S3** — [Projet .NET](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/src/N_m3u8DL-RE/N_m3u8DL-RE.csproj), [CLI](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/src/N_m3u8DL-RE/CommandLine/CommandInvoker.cs), [reprise de fragments](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/src/N_m3u8DL-RE/Downloader/SimpleDownloader.cs), [progression et assemblage](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/src/N_m3u8DL-RE/DownloadManager/SimpleDownloadManager.cs), [builds Bionic](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/.github/workflows/build_latest.yml).
- **S4** — [Contrat Video Aniyomi](https://extension-docs.aniyomi.org/extensions-lib/eu.kanade.tachiyomi.animesource.model/-video/index.html), [source Kotlin](https://github.com/aniyomiorg/aniyomi/blob/main/source-api/src/commonMain/kotlin/eu/kanade/tachiyomi/animesource/model/Video.kt).
- **S5** — [Filtres FFmpeg, subtitles](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [sélection des streams](https://ffmpeg.org/ffmpeg.html#Stream-selection).
- **S6** — [Android 10 : restrictions d’exécution](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission).
- **S7** — [Documentation officielle OpenSubtitles](https://ai.opensubtitles.com/api-docs), [guide officiel d’intégration REST](https://blog.opensubtitles.com/opensubtitles/how-to-build-a-movie-subtitle-finder-cli-with-python-and-the-opensubtitles-api).
- **S8** — [SubDL développeurs — API v2](https://subdl.com/developers), [documentation v1 distincte](https://subdl.com/api-doc).
- **S9** — [Matrice officielle FFmpegKit maintenu](https://github.com/ffmpegkit-maintained/ffmpeg/blob/main/README.md). La configuration de notre AAR 6.0.4 a été examinée localement, indépendamment de la matrice courante.
- **S10** — [Licence MIT N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.6.0-beta/LICENSE).
- **S11** — [Documentation yt-dlp](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp) ; son usage exact dans AnimeLab est établi par notre propre code.

## Reproduire les vérifications documentaires

Depuis la racine du dépôt :

```bash
python docs/studies/nm3u8dl-re/render.py --check-only
# Rendre à nouveau les SVG et la galerie : PlantUML, Java et Graphviz locaux requis.
python docs/studies/nm3u8dl-re/render.py
# Refaire la preuve synthétique FFmpeg, sans téléchargement réseau :
python docs/studies/nm3u8dl-re/prove_outputs.py
```

Le rendu revalide les liens de code mais ne remplace pas une nouvelle étude si le moteur change. L’archive contient la galerie, le rapport, les sources PlantUML, les SVG et les scripts de reproduction. La galerie se consulte seule hors ligne ; la revalidation des références et la régénération utilisent également le checkout du dépôt.
