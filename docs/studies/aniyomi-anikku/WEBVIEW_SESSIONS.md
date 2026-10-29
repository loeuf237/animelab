# WebView, sessions et reprise des extensions Aniyomi/Anikku

Étude du **29 octobre 2026**. Périmètre confirmé par l'utilisateur : **récupérer
la session WebView puis reprendre l'extension**, sans extraction générale des
requêtes réseau ou des liens vidéo observés dans le navigateur.

## 1. Conclusion et niveau de preuve

AnimeLab comportait une concurrence évitable : ouvrir une WebView déclenchait
un GET de contrôle dans le transport HTTP avec émulation de Chrome. Un
changement de cookies pouvait déclencher une autre sonde et fermer la fenêtre.
La lecture du code et un audit hors ligne avec fenêtre/serveur simulés
reproduisent ce défaut, sans solliciter un site protégé.

Les hôtes étudiés utilisent une autre continuité : leur client OkHttp emploie
un `AndroidCookieJar` raccordé au `CookieManager` de la WebView. Lors de leur
traitement automatique Cloudflare, l'appel concerné attend le traitement
WebView avant de reprendre. Ils ne produisent pas une recette de scraping
universelle à partir d'une visite.

**Le correctif du checkout supprime les sondes du mode WebView et suspend les
accès SourceHTTP au domaine pendant cette fenêtre.** Il récupère la session
avant reprise, sans annoncer que le site a nécessairement accordé l'accès.
Le partage complet des cookies entre processus Android reste un chantier
distinct ; il ne faut pas le présenter comme terminé.

Le message observé sur téléphone, « You are unable to access anime-sama.to »,
établit un refus dans cette WebView, pas sa cause exacte. Empreinte du client,
IP, politique géographique et version du navigateur restent des hypothèses.
Les erreurs réseau FRAnime/AniSama ne prouvent pas une détection de bot.

## 2. Références et méthode

| Projet | Commit effectivement lu | Périmètre |
| --- | --- | --- |
| Aniyomi | `97414446b8a95994c72dd33c41c971a89d4d25b8` | Écran WebView, intercepteurs, réglages, cookies |
| Anikku | `6e35b41f0cc7e375d15527bd61375435f998685a` | Composants équivalents, différences examinées séparément |
| AnimeLab | `e0718ea`, puis correctif local décrit ici | Python, JNI, worker APK, fenêtre de vérification et interface |

Les **18 fichiers primaires** sont inventoriés avec leur URL, commit et
identifiant Git du contenu dans [le manifeste](webview-sources-2026-10-29.json).
La référence Anikku vise ce commit précis ; tous ces fichiers ne sont pas
annoncés identiques à la release stable. Cette lecture n'est pas un essai
réciproque complet des deux applications sur téléphone.

Les tests Python emploient des bases/caches temporaires. L'audit n'ouvre aucun
navigateur réel et n'envoie aucune requête externe. Les résultats communautaires
physiques cités figurent dans [leur preuve séparée](evidence/android-arm64-community-redirects-2026-10-29.json).

## 3. Fonctionnement d'Aniyomi

### Client HTTP et magasin de cookies

`NetworkHelper` construit un client **OkHttp**, avec cache, délais,
`UserAgentInterceptor` et `CloudflareInterceptor`. L'alias `cloudflareClient`
renvoie ce client dans la référence étudiée. Le chemin par défaut examiné ne
passe pas par curl-cffi et un profil TLS imitant Chrome.

`AndroidCookieJar` lit les cookies applicables à l'URL via
`CookieManager.getInstance().getCookie(url)` et sauvegarde les réponses avec
`setCookie(url, cookie.toString())`. La WebView et le client HTTP sont raccordés
au même magasin. Ce mécanisme n'accède pas aux cookies d'une autre application.

Sources : [NetworkHelper](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/NetworkHelper.kt),
[AndroidCookieJar](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/AndroidCookieJar.kt).

### WebView visible

`WebViewActivity` et `WebViewScreenModel` récupèrent les en-têtes de la source.
`WebViewScreenContent` les fournit à la navigation et applique le User-Agent
de la source lorsqu'il trouve la clé attendue `user-agent`. L'écran offre
navigation, actualisation, navigateur externe et suppression ciblée des cookies.

JavaScript et le stockage DOM sont activés. Le HTML est lu pour afficher une
aide en présence de marqueurs Cloudflare. Cette lecture ne construit pas une
recette d'extension et n'extrait pas automatiquement une vidéo.

Cet écran ne démontre **aucune suspension globale** des appels de l'application.
La règle demandée pour AnimeLab, « aucun appel HTTP émulé au domaine pendant
la WebView », est donc une exigence locale supplémentaire.

Sources : [WebViewActivity](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/tachiyomi/ui/webview/WebViewActivity.kt),
[WebViewScreenContent](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/app/src/main/java/eu/kanade/presentation/webview/WebViewScreenContent.kt),
[WebViewUtil](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/util/system/WebViewUtil.kt).

### WebView interne de traitement d'un défi

L'intercepteur examiné réagit à certaines réponses 403/503 portant un en-tête
`Server` Cloudflare. Il ferme la réponse, prépare la clearance, crée une
WebView sur le thread principal et attend jusqu'à 30 secondes. Il cherche une
clearance nouvelle et contrôle les erreurs de navigation. Après ce traitement,
il reprend la requête interceptée ; un échec devient une exception.

Cette WebView temporaire diffère de l'écran visible. L'attente concerne la
chaîne interceptée, pas nécessairement les autres requêtes. Elle ne garantit
pas la résolution des défis interactifs ou des refus de politique du site.

Sources : [CloudflareInterceptor](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/interceptor/CloudflareInterceptor.kt),
[WebViewInterceptor](https://github.com/aniyomiorg/aniyomi/blob/97414446b8a95994c72dd33c41c971a89d4d25b8/core/common/src/main/java/eu/kanade/tachiyomi/network/interceptor/WebViewInterceptor.kt).

## 4. Différences utiles d'Anikku

Anikku conserve CookieManager, OkHttp et la continuité des en-têtes. Son
intercepteur User-Agent ne remplace la valeur de la requête que si elle est
absente ou vide.

Son `CloudflareInterceptor` examine aussi des identifiants HTML
`challenge-error-title` ou `challenge-error-text`. Le commentaire réserve le
traitement WebView au défi plutôt qu'au blocage géographique. Cette heuristique
plus ciblée ne constitue pas une détection universelle des causes d'un 403.

L'écran gère également une pile de fenêtres et les popups. Son callback de
navigation recharge une URL web différente avec les en-têtes, puis renvoie
`true` pour prendre explicitement la responsabilité de cette navigation.

Sources : [NetworkHelper Anikku](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/core/common/src/main/kotlin/eu/kanade/tachiyomi/network/NetworkHelper.kt),
[CloudflareInterceptor Anikku](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/core/common/src/main/kotlin/eu/kanade/tachiyomi/network/interceptor/CloudflareInterceptor.kt),
[UserAgentInterceptor Anikku](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/core/common/src/main/kotlin/eu/kanade/tachiyomi/network/interceptor/UserAgentInterceptor.kt),
[WebViewScreenContent Anikku](https://github.com/komikku-app/anikku/blob/6e35b41f0cc7e375d15527bd61375435f998685a/app/src/main/java/eu/kanade/presentation/webview/WebViewScreenContent.kt).

## 5. Diagnostic d'AnimeLab

| Constat | Preuve locale | Conséquence | État |
| --- | --- | --- | --- |
| `needsProbe` à l'ouverture et contrôle après changement de cookies | `browser_verification.py` et audit | GET émulé pendant la fenêtre, fermeture prématurée possible | Corrigé pour WebView |
| `verify_challenge=True` franchit le blocage ordinaire | Requêtes et flux SourceHTTP | Des contrôles restent possibles en concurrence | Verrou ajouté aux leases et aux deux chemins |
| Fermeture Android simplement postée | Ancien `VerificationBridge.close` | Reprise avant arrêt du navigateur | Arrêt natif désormais attendu |
| Profil `extension-runtime` distinct | Service du worker | CookieManager natif différent de celui de l'interface | Unification encore nécessaire |
| Cookie explicite éventuellement ancien, ajouté par le jar natif | NetworkHelper et broker Python | La clearance récente du parent peut être masquée | À traiter avec le magasin unique |
| User-Agent et profil curl Chrome imposés | SourceHTTP et fenêtre Android | En-têtes particuliers de source non fidèlement conservés | À traiter ; cause d'un refus non prouvée |
| Cookies relus pour l'URL de départ | VerificationWindow | Couverture incomplète des chemins de redirection | Capture bornée à compléter |
| Attributs des nouveaux cookies incomplets | Reconstruction depuis `getCookie` | Limites de path, expiration, doublons et suppressions | Ne pas annoncer un export fidèle |
| Stockage DOM activé, sans équivalent HTTP générique | Activity et transport | localStorage ne devient pas un cookie par magie | Intégration spécifique si nécessaire |

Le profil distinct évite un conflit de verrouillage entre processus. **Retirer
simplement le suffixe n'est pas une solution** : Android documente les
contraintes d'accès multiprocessus et le partage explicite des cookies.
Source : [WebView.setDataDirectorySuffix](https://developer.android.com/reference/android/webkit/WebView#setDataDirectorySuffix(java.lang.String)).

`getCookie(url)` fournit des paires nom/valeur au format d'un en-tête Cookie,
pas tous leurs attributs. `flush()` assure la persistance, sans restaurer ces
informations perdues. Source : [CookieManager](https://developer.android.com/reference/android/webkit/CookieManager#getCookie(java.lang.String)).

## 6. Ce qu'il faut récupérer et conserver

Le résultat attendu est un **état privé de session**, associé à une source et
une route réseau : cookies cohérents, User-Agent choisi, origines/chemins
autorisés et version de session permettant de rejeter les données anciennes.
Il ne remplace ni l'APK original, ni son parsing.

Les règles Domain/Path/Secure/expiration restent applicables. Les cookies ne
doivent apparaître ni dans une recette publique, ni dans les logs, les rapports,
les URL du lecteur ou une sauvegarde ordinaire. Les données Aniyomi, Anikku
et AnimeLab restent propres à chaque application : partager un APK ne partage
pas leurs comptes ou leur session navigateur.

Le stockage DOM reste dans la WebView. Une source exigeant un jeton qui existe
seulement dans localStorage nécessitera une intégration explicite et ciblée.
Exporter arbitrairement tout ce stockage vers des en-têtes HTTP ne reproduirait
pas le comportement du site.

Une chaîne User-Agent ne rend pas WebView et curl/OkHttp identiques : TLS,
Client Hints et capacités JavaScript peuvent différer. Android précise qu'un
User-Agent personnalisé peut aussi affecter les Client Hints et
`navigator.userAgentData`.
Source : [WebSettings.setUserAgentString](https://developer.android.com/reference/android/webkit/WebSettings#setUserAgentString(java.lang.String)).

## 7. Parcours corrigé

```mermaid
sequenceDiagram
    participant E as Extension
    participant S as Session du domaine
    participant W as WebView
    E->>S: Vérification nécessaire
    S-->>E: Opération suspendue
    S->>S: Bloquer les nouveaux accès HTTP et attendre les accès actifs
    S->>W: Ouvrir avec la session initiale
    Note over S,W: Échanges locaux de cookies ; aucune sonde HTTP du broker
    W-->>S: Retour et état de session
    S->>W: Arrêter la navigation et fermer
    S->>S: Libérer le transport
    S-->>E: Reprendre l'opération réelle
    E-->>S: Succès, erreur, refus ou nouveau défi
```

Le verrou concerne le domaine de la vérification, sans fermer les autres
téléchargements ni changer leur proxy. Une source utilisant plusieurs origines
demandera un périmètre explicite. Les accès directs d'un APK hors du broker
ne sont pas couverts : ce worker au même UID n'est pas un bac à sable.

Avant ouverture, les handles actifs doivent se terminer ; après 30 secondes
d'attente, l'ouverture est refusée si nécessaire. Les nouvelles requêtes et
les flux sont bloqués, même avec `verify_challenge=True`. Un ancien identifiant
ne peut pas libérer le verrou du job courant.

Le watcher échange uniquement les cookies par IPC local pendant la fenêtre.
Le retour Android ou la confirmation explicite ferme cette fenêtre avant la
reprise. Une seule WebView est admise à la fois, conformément au pont qui
ne représente qu'une activité active.

Le résultat expose `sessionImported=true`, `accessVerified=false`. L'interface
annonce une session récupérée, puis laisse le résultat réel de l'extension
établir l'accès. Un refus reste un refus. Le mode Chromium distinct conserve
son mécanisme antérieur de validation ; il n'est pas présenté comme équivalent
au nouveau mode WebView.

## 8. Travaux restant nécessaires pour la parité

1. **Un propriétaire des cookies dans le processus principal.** Raccorder le
   jar du worker au service utilisé par la WebView via un IPC borné et typé ;
   éviter une seconde copie durable qui réintroduit des cookies périmés.
2. **Respect du client de la source.** Préserver son User-Agent explicite et
   ses en-têtes autorisés ; exclure les en-têtes réservés et les fuites vers une
   origine différente. Étudier un transport OkHttp natif sur Android au lieu
   d'imposer l'émulation curl à ces APK.
3. **Redirections de session.** Suivre uniquement les origines/chemins permis,
   conserver suppressions et doublons de noms, sans capturer les comptes
   d'autres sites. Un en-tête Cookie seul ne suffit pas à tout reconstruire.
4. **Reprise maîtrisée.** Dédupliquer les tentatives et reprendre les lectures
   idempotentes ; ne pas rejouer automatiquement un formulaire POST arbitraire
   ou une action à effet de bord.
5. **Qualification des refus.** Séparer défi, 403 ordinaire, limitation de débit,
   DNS/TLS et incompatibilité du runtime. Éviter les boucles de changements
   de profil, d'IP ou de navigateur devant un refus stable.

Ces points ne sont pas acquis par le seul patch de suspension. Une session
Aniyomi/Anikku intégralement partagée avec AnimeLab n'est pas encore démontrée.

## 9. Tests, preuves et réception

L'audit [avant correction](evidence/webview-concurrent-probe-before-2026-10-29.json)
enregistre un GET simulé pendant l'ouverture, sans changement de cookies.
L'audit [après correction](evidence/webview-concurrent-probe-after-2026-10-29.json)
n'en enregistre aucun dans la fenêtre d'observation. Ce sont des preuves de
contrôle de flux, **pas des captures de paquets du téléphone**.

```bash
uv run --locked python docs/studies/aniyomi-anikku/audit_webview_concurrency.py
```

Les **80 tests Python ciblés** couvrent transport, cookies et vérification :
absence de sonde, import, reprise après fermeture, verrou des requêtes/flux,
annulation, expiration et changements de route. La suite complète du commit
précédent `e0718ea` compte **1 013 réussites, 5 ignorés** ; ses
[7 jobs généraux](https://github.com/loeuf237/animelab/actions/runs/40844963392)
et [5 jobs Android](https://github.com/loeuf237/animelab/actions/runs/40844963382)
réussissent. Le patch WebView passe ensuite la suite Python complète :
**1 019 réussites, 5 ignorés**. Après ajout des champs publics de résultat et
du verrou de rotation, la campagne ciblée finale réussit **91 tests**.
Un essai Playwright hors ligne réussit aussi : retour de session, un seul
rechargement du catalogue et absence de fausse annonce d'accès vérifié.
Le navigateur Chrome déjà installé a été utilisé, sans téléchargement de navigateur.
Ces résultats locaux ne remplacent pas la CI ni une réception sur le téléphone.

Les tests supplémentaires vérifient aussi qu'un échec de fermeture native
conserve le verrou, qu'une ouverture partielle reste récupérable et qu'un
ancien travail de drainage annulé ne peut pas réacquérir une session orpheline.

Réception physique encore requise, avec APK construits dans GitHub Actions :

- serveur contrôlé : seul trafic navigateur pendant la fenêtre, zéro requête
  du broker ;
- bouton de retour et retour système : session disponible avant un unique retry ;
- worker déjà chargé : aucun cookie ancien ne masque le nouveau ;
- rotation/recréation, annulation, échec d'ouverture et expiration : pas de
  fenêtre orpheline ni de transport verrouillé ;
- HttpOnly, Secure, suppression, doublons et redirections : session cohérente,
  sans valeur secrète dans les preuves ;
- site restant en 403 : pas de fausse réussite ni de boucle ;
- recherche, détails, épisodes et vidéo d'un APK réel après une vérification acceptée.

L'adoption reste conditionnée à [APK01–APK14](EXIGENCES_ANDROID_APK.md). Une
visite WebView ou un test unitaire réussi ne suffit pas à prononcer la réception.
