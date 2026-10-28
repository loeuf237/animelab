# Gestion des extensions : utilisation et état de validation

Mise à jour : 29 octobre 2026. Les résultats de l'étude décrivent le commit initial ;
le [registre d'implémentation](IMPLEMENTATION_STATUS.md) suit les changements.

## Dépôts et installations

Dans **Extensions**, ajouter plusieurs dépôts les conserve simultanément. Désactiver
un dépôt suspend ses offres, sans supprimer ses extensions installées. Un
rafraîchissement ne remplace pas la recette ou la version installée. Les extensions
retirées restent conservées. Le code de version numérique prime sur le nom affiché
pour décider d'une mise à jour ; une vérification n'installe rien.

Les index historiques JSON ainsi que les stores JSON/Protobuf, gzip, listes externes
et migrations `index_v2` passent par des lecteurs bornés. Un changement de clé
annoncée apparaît dans le panneau des dépôts et bloque les nouvelles installations
Android concernées jusqu'à approbation explicite. Une empreinte publiée dans un
index n'est pas une preuve cryptographique de l'authenticité de cet index.

## APK Android : builds de validation

Le nouveau moteur est activé dans les builds `debug` et `validation`. Son adoption
dans les builds `release` reste désactivée jusqu'aux tests de réception APK01–APK14.
Le workflow **Android extension APK runtime** construit les APK et exécute les tests
sur émulateurs ; aucune compilation d'APK locale n'est nécessaire.

Dans un build de validation, **Extensions APK Android** affiche les véritables
paquets découverts par Android. Un paquet téléchargé ou une recette compilée ne
compte pas comme APK installé.

1. Installer un fichier APK original depuis le panneau, ou activer une offre de
   dépôt. Android peut demander l'autorisation d'installer depuis AnimeLab, puis
   une confirmation d'installation. Le résultat système reste distinct du téléchargement.
2. Examiner package, version et empreinte. Approuver précisément ce couple
   version/signataire permet l'exécution de ses classes. Une autre version doit
   être approuvée à nouveau.
3. Les différentes sources d'une fabrique ont chacune leur identifiant, leurs
   préférences et leur activation. **Ouvrir la source** donne accès aux catalogues
   et filtres réellement fournis par l'APK.
4. Révoquer la confiance arrête son admission. Désactiver une source ou un paquet
   ne désinstalle pas son APK. La désinstallation du **paquet partagé** concerne
   aussi les autres hôtes qui l'utilisent ; une confirmation Android est nécessaire.

Les extensions déjà installées comme paquets Android sont découvertes sans avoir
à transformer leurs APK. La compatibilité avec un APK communautaire donné et les
parcours réciproques dans Aniyomi/Anikku doivent encore être testés. Les extensions
privées conservées dans le stockage d'une autre application nécessitent un export
ou un téléchargement de leur APK ; ce stockage n'est pas accessible directement.

Le processus `:extensions` partage l'UID d'AnimeLab. Il sépare les arrêts et permet
de terminer un appel bloqué ; **il ne constitue pas un bac à sable de sécurité**.
Approuver un APK lui accorde la possibilité d'accéder aux données et au réseau de
l'application. Le client réseau par défaut utilise le broker d'AnimeLab ; du code
approuvé peut créer ses propres clients/sockets. Aucune protection absolue contre
ce contournement n'est annoncée.

## Vidéos et capacités encore incomplètes

Recherche, catalogue, détails/épisodes, filtres, préférences, hébergeurs et résolution
vidéo utilisent les callbacks natifs. Les mémos et données internes restent dans
ces échanges. Les en-têtes de lecture restent côté serveur, derrière des liens
temporaires, et les sous-ressources HLS sont réécrites avec validation des destinations.

La lecture navigateur de DASH avec en-têtes APK, de pistes audio externes et le
rendu ASS exigent encore un raccordement spécifique. Ces parcours échouent
explicitement ; ils ne sont pas présentés comme compatibles. Les options mpv/FFmpeg
fournies par un APK ne deviennent pas une commande exécutable. Les serveurs HTTP
locaux et torrents d'extensions ne sont pas admis automatiquement.

Les API annoncées 12–17 sont admises par le chargeur. Le corpus synthétique actuel
est compilé contre l'ABI hôte actuelle : il vérifie la plomberie et les admissions,
sans démontrer toutes les anciennes ABI d'extensions distribuées. La compatibilité
historique, l'interopérabilité avec les deux vrais hôtes et les essais ARM64 doivent
être inscrits séparément dans le registre.

## Sauvegarde des identités

`GET /api/extensions/backup` produit une archive des dépôts, versions de référence
et identifiants de sources. L'option `include_artifacts=true` ajoute les artefacts
APK connus du cache, vérifiés par SHA-256. `POST /api/extensions/backup/restore`
accepte cette archive comme corps HTTP binaire.

Cette sauvegarde ne contient pas les cookies, les préférences natives secrètes,
les recettes pouvant contenir des identifiants, ni les approbations d'exécution.
La restauration conserve les stubs, ne remplace pas les téléchargements et ne
réinstalle aucun APK. Les métadonnées et artefacts doivent être revérifiés avant
activation. La sauvegarde complète des recettes et préférences non secrètes reste
un travail distinct à achever ; ce format initial ne prétend pas les restaurer.

## Bureau

Linux et Windows conservent le moteur de recettes Python. Le runtime APK Android
n'est pas chargé sur ces plateformes. Un moteur JVM de bureau reste à évaluer :
une extraction de constantes DEX n'est pas une exécution équivalente à Android.
