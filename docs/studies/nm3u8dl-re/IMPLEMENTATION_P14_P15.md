# P14–P15 — Hardsub Android et décision sur le backend spécialisé

27 octobre 2026. **P14 : implémentation locale et banc de validation prêts ; validation des APK sur Android compatible encore requise. P15 : non retenu pour la version étudiée.** Aucun APK construit, signé ou installé localement ; aucun workflow distant déclenché ni release publiée pendant ce lot.

## P14 : comportement et composants

Les modules application et sonde JNI utilisent désormais la même dépendance épinglée `dev.ffmpegkit-maintained:ffmpeg-kit-full-gpl:6.0.4`, en remplacement de `min`. Le POM Maven de cette version a été consulté ; le fournisseur annonce libass et les encodeurs GPL dont x264. Cette annonce ne remplace pas l’exécution du filtre et de l’encodeur sur Android. La version 6.0.4 conserve l’API `com.arthenica.ffmpegkit` utilisée par le pont.

`HardsubProbe`, appelé via `MediaBridge.probeHardsub`, ne donne pas son accord sur la seule présence du nom d’un filtre :

1. Vérifier les capacités `subtitles`, `libx264` et `aac`.
2. Sélectionner une police Android système lisible ; aucun fichier de police système n’est redistribué dans le dépôt ou l’APK.
3. Encoder deux secondes de vidéo noire avec audio et un sous-titre visible de 1 à 2 secondes.
4. Vérifier avec FFprobe une vidéo H.264 et un audio AAC, sans piste de sous-titres séparée.
5. Décoder deux images, avant et pendant le sous-titre, et vérifier une différence de pixels significative.

Le résultat est mis en cache uniquement pour la durée du processus. Toute erreur garde le profil indisponible ; relancer l’application permet un nouvel essai. Les fichiers de sonde sont supprimés. Un ancien pont sans cette méthode, une police absente ou un rendu non prouvé ne peuvent pas autoriser le hardsub. L’API de profils et la mise en file appliquent ce contrôle ; l’exécution le vérifie aussi.

Le processeur P6/P7 utilise des chemins absolus correctement échappés dans les filtres JNI, sans changement du répertoire global. Le chemin desktop conserve son fonctionnement. Les offsets, le contrôle de durée/pistes, les fichiers intermédiaires, la vérification avant publication et la conservation des sources passent par les mécanismes existants. Le traitement JNI continue à utiliser les événements, statistiques et annulations supervisés de P5.

Précautions initiales Android : une seule tâche média à la fois, un seul thread d’encodage et de filtrage ; limite de 1920 × 1080, trois heures et durée connue. Les contrôles d’espace temporaire existants restent appliqués. Ces bornes sont conservatrices et ne constituent pas une mesure de performance sur téléphone. L’auto-test court n’atteste ni la consommation d’un épisode complet, ni la reprise après arrêt brutal de l’application. Ces validations restent à effectuer avant distribution.

## Licences, polices et provenance

AnimeLab est déjà sous GPL-3.0-only. Les notices Android et les métadonnées de release identifient la variante full-gpl ; le texte GPL est déjà livré dans `assets/licenses`. Les sources et instructions de construction du fournisseur restent référencées. Libass, FreeType, FriBidi et x264 sont explicitement signalés. Les polices système restent sur l’appareil ; les polices jointes aux médias restent traitées comme des ressources du média. Le contrôle final des notices de tous les composants de l’AAR résolu et les tailles réelles d’APK restent à effectuer sur le build GitHub Actions avant publication.

## Banc GitHub Actions

Le workflow manuel `.github/workflows/android-hardsub-evaluation.yml` :

- construit seulement les APK de sonde JNI en x86_64 et ARM64, sur les runners ;
- contrôle l’ABI et l’alignement ELF de 16 Kio avec `scripts/android_hardsub_audit.py`, et relève taille d’APK et taille des bibliothèques natives ;
- exécute l’instrumentation x86_64 sur API 29, 30 et 35 ;
- exige des preuves structurées de rendu, progression, annulation et export via `--require-hardsub` ;
- conserve APK de test, audit ELF, logs et `hardsub-proof.json` ; aucune release n’est signée ou publiée par ce workflow.

L’instrumentation encode un vrai fichier incrusté, exporte ses octets par le mécanisme Android existant et vérifie leur identité. Elle contrôle les exports interrompus et observe les statistiques puis l’arrêt d’un encodage JNI. Le rapport inclut ABI, API, taille de page, temps de sonde, allocation native avant/après et état thermique avant/après. Il ne mesure pas l’énergie consommée ni le pic mémoire d’un épisode complet.

L’audit ELF n’est pas une exécution sur appareil à pages de 16 Kio ; le JSON garde `device16kbTested: false`. L’émulation x86_64 n’est pas une preuve ARM64 réelle. Les APK de sonde ARM64 sont préparés pour cette dernière validation. L’APK de l’application complète conserve ses propres contrôles de packaging et de signature dans les workflows de release existants.

## Validation locale et limites

- Le test du chemin de traitement Android emploie un adaptateur JNI simulé autour du vrai FFmpeg Linux : incrustation avec chemins Unicode/apostrophe, codecs de sortie et conservation de l’original vérifiés. **Ce n’est pas une exécution JNI Android.**
- Les sources Kotlin du pont, de la sonde et de l’instrumentation compilent avec les API Android/JNI déjà en cache. Aucun AAR full-gpl n’a été téléchargé pour ce contrôle ; il atteste la compilation des appels d’API communs, pas le chargement des nouvelles bibliothèques.
- Les tests couvrent le refus d’un rendu non prouvé, l’absence de police/codecs, le plafonnement de concurrence, les preuves d’instrumentation obligatoires et le rejet d’un ELF aligné sur 4 Kio.
- Le seul appareil ADB constaté pendant ce lot indique API 19 et `armeabi-v7a` ; il est incompatible avec le minimum API 29 et ARM64 de l’application. Aucun paquet n’y a été installé ni ses données modifiées.
- La CI préparée n’a pas été exécutée. Taille finale, audit de l’AAR, chargement JNI full-gpl, performance, consommation, thermique sur épisode complet, interruption puis relancement de l’application et validation API/ARM64 restent à confirmer.

Résultats locaux finaux : **916 passed, 5 skipped, 2 warnings in 232.43s (0:03:52)** pour la suite Python complète ; **12 tests de garde et d’audit réussis**, **31 tests du traitement des sorties et du chemin JNI simulé réussis**, contrôles de qualité Python/frontend réussis et compilation Kotlin des ponts/de l’instrumentation réussie. Les résultats précis figurent dans `android-p14-p15-decision.json`. P14 reste **en attente de validation Android**, même si les tests hôtes passent. Le profil reste refusé sur une installation ne passant pas la sonde réelle.

## P15 : décision Android distincte

L’étude amont conserve bien des assets **Android Bionic ARM64 et x64** pour `v0.6.0-beta`. Leur présence est reconnue : le refus ne repose pas sur l’absence de binaire Android. Les archives du relevé GitHub font respectivement 5 764 262 et 6 078 228 octets ; elles n’ont pas été téléchargées ni exécutées pendant P15.

La décision [structurée](android-p14-p15-decision.json) est **non retenu pour cette version**, pour les raisons suivantes :

- P12 n’a pas donné son accord ; les défauts de reprise et de synchronisation n’ont pas été levés sur Android. Les reproductions Linux ne sont pas présentées comme une exécution Bionic.
- Aucun mode de chargement ou exécution depuis l’APK, cycle de vie, arrêt, dépendances, alignement 16 Kio et comportement API 29/30/35 n’a été démontré pour ces binaires.
- L’isolation par namespace Linux du prototype ne constitue pas une preuve de cloisonnement disponible dans l’application Android. Relais seul, URL réécrites ou binaire Bionic ne suffisent pas à garantir la politique réseau.
- Aucun gain représentatif n’a été mesuré face au backend Android actuel ; poids installé, mémoire et énergie du backend spécialisé restent inconnus.

Les téléchargements Android gardent donc leur backend existant. Aucun téléchargement à la demande du binaire, exécution dans un répertoire privé inscriptible, contournement des restrictions Android ou permission réseau supplémentaire n’est introduit.

P15 peut être rouvert avec une version candidate corrigeant les contre-exemples, une intégration APK reproductible, des preuves réseau et de reprise sur ABI/API cibles, des mesures comparatives et une nouvelle décision d’adoption Android. P14 ne dépend pas de cette adoption.

## Références consultées

- [Matrice FFmpegKit du fournisseur](https://github.com/ffmpegkit-maintained/ffmpeg/blob/main/README.md) et [POM exact 6.0.4](https://repo.maven.apache.org/maven2/dev/ffmpegkit-maintained/ffmpeg-kit-full-gpl/6.0.4/ffmpeg-kit-full-gpl-6.0.4.pom).
- [Android : restrictions d’exécution depuis le répertoire privé](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission).
- [Android : vérification et essais des pages de 16 Kio](https://developer.android.com/guide/practices/page-sizes).
- Étude et preuves locales [P10–P13](IMPLEMENTATION_P10_P13.md), [relevé des assets amont](upstream-release.json) et [décision P12](nm3u8dl-decision.json).
