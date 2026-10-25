# A11 — Réduction de la taille Android

## Modifications livrées

- R8 et réduction des ressources activés dans les variantes release et validation.
  Les classes appelées par Python et JNI conservent leurs noms et leurs méthodes.
- Symboles inutiles retirés des bibliothèques Python dans les archives générées
  par Chaquopy. Les wheels téléchargés restent intacts. Les sections allouées,
  adresses, tailles, drapeaux et alignements des segments sont comparés avant
  publication. Les originaux et leurs empreintes sont conservés hors APK.
- Six copies publiques identiques retirées des entrées Android ; les fichiers
  canoniques servis depuis `animelab/static` et les assets Vue restent présents.
- lxml, libxml2 et libxslt retirés des dépendances Android : les adaptateurs
  utilisent BeautifulSoup avec `html.parser`. Les dépendances bureau restent
  inchangées. Tous les extracteurs yt-dlp et les outils FFmpeg restent inclus.
- Contrôle des empreintes Chaquopy après optimisation, des passerelles dans le
  DEX, de l'absence des bibliothèques XML et de l'alignement ELF 16 Ko.
- Rapports de taille reproductibles et mesure séparée de l'espace installé dans
  l'instrumentation Android. Le cache est inclus dans les données, pas additionné
  une seconde fois.

Les bibliothèques JNI restent non compressées pour leur chargement direct.
L'allègement ne repose pas sur un téléchargement ultérieur du moteur.

## Mesures APK et stockage installé

Mesures du 21 octobre 2026, Android 10 / ARM64, version 0.1.0 / code 213.
1 Mo = 1 000 000 octets. Le témoin et l'optimisé contiennent le même moteur
Python corrigé et la même interface ; l'optimisé aligne aussi AndroidX Tracing
sur la version 1.1.0 attendue par le pilote, contre 1.0.0 dans le témoin.

| Mesure | Témoin | Optimisé | Réduction |
| --- | ---: | ---: | ---: |
| APK de la copie testée | 77 762 449 o (77,76 Mo) | 61 311 286 o (61,31 Mo) | **16 451 163 o (21,16 %)** |
| Code installé, relevé Android | 78 020 608 o | 61 435 904 o | 16 584 704 o |
| Données privées, cache inclus | 59 498 496 o | 35 930 112 o | 23 568 384 o |
| Total installé après premier affichage | **137 519 104 o (137,52 Mo)** | **97 366 016 o (97,37 Mo)** | **40 153 088 o (29,20 %)** |

Le cache est respectivement de 1 327 104 et 1 314 816 octets ; il est déjà
inclus dans les données. Les mesures sont prises après réinitialisation des
seules données de la copie de test, avant les médias synthétiques. Les fichiers
personnels, les téléchargements et les caches ultérieurs peuvent faire varier
l'espace occupé. La RAM et la vitesse de démarrage ne sont pas mesurées ici.

Le fichier normal signé livré, **Animan-v0.1.0-A11-Android-arm64.apk**, fait
**61 363 021 octets (61,36 Mo)**. Le manifeste, le nom de paquet et la signature
diffèrent de la copie de test ; les **39 entrées du moteur/bibliothèques natives
et les fichiers DEX sont strictement identiques**. Cette différence de packaging
explique la légère différence de taille. L'APK utilise l'identité de signature
habituelle et peut mettre à jour la version existante sans désinstallation.

Gain de payload ZIP entre les copies testées : DEX 7 171 732 octets ; archives
Python et assets 8 703 532 octets ; ressources 518 926 octets. Les autres écarts
proviennent des métadonnées, de la signature et de l'alignement ZIP.

Les rapports locaux sont dans `build/a11/phone-comparison/` et le livrable dans
`build/a11/release/`. Les originaux natifs restent dans
`android/app/build/reports/native-optimization/` et les cartes R8 dans
`android/app/build/outputs/mapping/`, hors APK. L'étude et les premières mesures
du 20 octobre sont conservées : elles précèdent les derniers ajustements R8.

## Vérifications exécutées

- **494 tests Python réussis**, avec lxml rendu indisponible, couvrant notamment
  sources, extensions, reprises, sous-titres, migrations et assemblage HLS natif.
- Les 8 contrôles de packaging font partie de cette validation. Ils comprennent
  le chargement d'une bibliothèque après stripping, le refus d'une modification
  des segments exécutables et la vérification des empreintes Chaquopy.
- APK applicatif et instrumentation compilés avec R8 et réduction des ressources.
  Les interfaces partagées par Kotlin, AndroidX et le pilote sont conservées pour
  éviter la suppression ou la réécriture des méthodes utilisées par le test.
- Inspection du moteur et de l'alignement 16 Ko réussie ; signature et alignement
  ZIP vérifiés. 137 fichiers embarqués comparés aux sources locales, dont le
  bytecode de `run.py` et `android_runtime.py`.
- **Témoin et optimisé : test complet réussi sur le téléphone ARM64 Android 10**
  (`OK (1 test)` pour chaque APK), avec les opérations médias activées.

## Validation sur téléphone et corrections découvertes

La copie `Animan A11 test` utilise `com.animan.app.a11test` et ses propres données.
Le test vérifie Python, TLS/Chrome, SQLite, rendu Vue, recréation d'activité,
AES Java, reprise HTTP, HLS chiffré, fusion et langue des sous-titres, décodage
FFmpeg et export MediaStore avec comparaison des octets. Le sélecteur de dossier
est ouvert puis annulé ; un véritable choix de dossier avec droit persistant
reste à exercer manuellement. Les flux médias de test sont synthétiques ; ceci
ne valide pas l'accès permanent à tous les sites ni tous les codecs WebView.

Les essais ont également conduit à trois corrections :

1. Le banc de test autorise son domaine fictif dans le module MediaPipeline
   extrait en A03, puis restaure la protection d'origine après le test.
2. L'assemblage HLS utilise des chemins absolus et la résolution relative au
   manifeste concat FFmpeg. Aucun dossier de travail global n'est transmis à JNI.
   Un test de régression couvre ce cas et un dossier contenant une apostrophe.
3. Le pilote garde sa fenêtre éveillée sans changer le délai de veille personnel.
   Les API partagées et la version Tracing sont alignées pour le test de l'APK
   minifié ; R8 reste actif dans l'application et dans le pilote.

Les fichiers exportés par la copie isolée sont supprimés par leurs URI exactes.
Les deux applications de test ont ensuite été désinstallées. L'APK de production
installé sur le téléphone est **inchangé**, vérifié par SHA-256 contre la release
initiale ; aucune donnée de cette installation n'a été réinitialisée.

L'APK normal livré n'a pas été installé sur la bibliothèque personnelle. Son
équivalence binaire avec la copie testée est enregistrée dans
`physical-build-equivalence.json`, à côté du livrable. Le code indique donc
explicitement `physical_device_tested: false` pour ce paquet exact et
`isolated_build_physical_device_tested: true` pour la copie validée.
Les versions Android 11/15 de cette optimisation, la veille prolongée et la
lecture de tous les médias réels restent à revalider ; les anciens tests de la
beta publiée ne sont pas réattribués au nouveau build.

## Reproduction

Voir [la procédure Android](../android-distribution.md) pour les outils requis,
`ANIMAN_BUILD_PYTHON`, `ANIMAN_LLVM_STRIP` et le mode isolé.

```bash
cd android
./gradlew :app:assembleValidation :app:assembleValidationAndroidTest \
  -Paniman.isolatedValidation=true
cd ..
python3 scripts/android_instrumentation.py \
  android/app/build/outputs/apk/validation/app-validation.apk \
  android/app/build/outputs/apk/androidTest/validation/app-validation-androidTest.apk \
  build/a11-device-results --package com.animan.app.a11test
python3 scripts/android_apk_size.py optimized.apk --output build/a11-size \
  --baseline baseline.apk
```

Pour le témoin, utiliser `-Paniman.optimizeApk=false` et une copie de l'ancienne
liste via `ANIMAN_ANDROID_REQUIREMENTS`. Comparer deux installations vierges de
la seule copie de test ; ne pas effacer les données de l'application personnelle.
La CI conserve les diagnostics d'optimisation et les rapports de validation.
