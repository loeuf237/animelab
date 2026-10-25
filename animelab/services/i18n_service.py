"""
Service d'internationalisation (i18n) pour AnimeLab.
Fournit les catalogues de traductions (Français & Anglais),
la détection de langue et les helpers de traduction.
"""

from typing import Dict, Any, Optional
from contextvars import ContextVar
import logging
import os
import locale

logger = logging.getLogger("animelab.i18n")

SUPPORTED_LANGUAGES = ("fr", "en")
DEFAULT_LANGUAGE = "fr"

current_request_lang: ContextVar[str] = ContextVar("current_request_lang", default="")

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "fr": {
        # Navigation & Shell
        "nav_brand": "AnimeLab",
        "nav_home": "Accueil",
        "nav_search": "Recherche",
        "nav_downloads": "Téléchargements",
        "nav_library": "Bibliothèque",
        "nav_history": "Historique",
        "nav_extensions": "Extensions",
        "nav_settings": "Paramètres",
        "theme_toggle_title": "Changer le thème",
        "lang_switch_title": "Changer de langue (FR / EN)",

        # Search & Command Palette
        "search_placeholder": "Rechercher un anime...",
        "palette_search_placeholder": "Rechercher un anime, un film ou une série...",
        "palette_clear_title": "Effacer la recherche",
        "palette_esc_badge": "Échap",
        "palette_tab_all": "Toutes (Multi)",
        "palette_empty_hint": "Tapez au moins 2 caractères pour rechercher parmi tous les catalogues...",
        "palette_loading": "Recherche en direct...",
        "palette_no_results": "Aucun résultat trouvé pour cette recherche.",
        "palette_view_details": "Voir la fiche anime",
        "palette_hint_navigate": "Naviguer",
        "palette_hint_open": "Ouvrir",
        "palette_hint_close": "Fermer",
        "palette_ready": "Prêt",
        "palette_results_count": "{count} résultat(s)",

        # Home page (index.html)
        "home_hero_title": "Votre plateforme anime tout-en-un",
        "home_hero_sub": "Recherchez, lisez en streaming et téléchargez vos animés préférés avec gestion multithread et résilience réseau.",
        "home_source_label": "Source d'anime",
        "home_search_btn": "Rechercher",
        "home_filter_all": "Tous",
        "home_filter_vf": "VF (Français)",
        "home_filter_vostfr": "VOSTFR",
        "home_latest_releases": "Dernières sorties",
        "home_recent_episodes": "Épisodes récents",
        "home_explore_catalog": "Explorer le catalogue",
        "home_empty_title": "Aucun anime trouvé",
        "home_empty_sub": "Essayez une autre recherche ou vérifiez la source sélectionnée.",
        "anime_card_view": "Voir la fiche",
        "anime_card_episodes": "épisodes",

        # Anime Detail page
        "detail_synopsis_title": "Synopsis",
        "detail_no_synopsis": "Synopsis non disponible pour cet anime.",
        "detail_chapters": "chapitres",
        "detail_episodes": "épisodes",
        "detail_range_all": "Tous",
        "detail_search_ep_placeholder": "N° d'épisode...",
        "detail_search_ep_title": "Filtrer un numéro d'épisode précis",
        "detail_batch_all": "Tout",
        "detail_batch_not_downloaded": "Non téléchargés",
        "detail_batch_not_watched": "Non vus",
        "detail_batch_invert": "Inverser",
        "detail_batch_server": "Serveur :",
        "detail_batch_quality": "Qualité :",
        "detail_batch_subtitles": "Sous-titres",
        "detail_batch_subtitles_title": "Télécharger les sous-titres pour tous les épisodes sélectionnés",
        "detail_batch_selected_count": "{count} sélectionné(s)",
        "detail_batch_download_btn": "Télécharger la sélection",
        "detail_batch_server_auto": "Auto (Défaut)",
        "detail_batch_quality_auto": "Auto / Max",
        "detail_ep_subtitles": "Sous-titres",
        "detail_ep_subtitles_active": "✓ Sous-titres",
        "detail_ep_subtitles_title": "Activer / désactiver le téléchargement des sous-titres pour cet épisode",
        "detail_ep_tracks": "Pistes ▾",
        "detail_ep_tracks_title": "Choisir la piste de sous-titres (Français, etc.)",
        "detail_ep_downloaded": "Téléchargé",
        "detail_ep_queued": "En file d'attente",
        "detail_ep_play_local_title": "Lecture locale (Disque dur)",
        "detail_ep_play_stream_title": "Streaming direct (En ligne)",
        "detail_ep_download_title": "Télécharger l'épisode",
        "detail_fab_start": "Commencer",
        "detail_fab_resume": "Reprendre (Ep. {num})",
        "detail_fab_rewatch": "Revoir (Ep. 1)",

        # Modals
        "modal_quality_title": "Choisir la qualité vidéo",
        "modal_quality_close": "Fermer",
        "modal_subtitle_title": "Pistes de sous-titres disponibles",
        "modal_subtitle_close": "Fermer",
        "modal_subtitle_none": "Aucune piste alternative de sous-titres trouvée.",
        "modal_subtitle_active": "✓ Actif",
        "modal_subtitle_select": "Sélectionner",

        # Downloads page
        "dl_title": "Gestionnaire de téléchargements",
        "dl_sub": "Gérez votre file d'attente, vos priorités et vos téléchargements actifs en temps réel.",
        "dl_stat_active": "Téléchargements en cours",
        "dl_stat_queued": "En file d'attente",
        "dl_stat_speed": "Vitesse actuelle",
        "dl_tab_queue": "File d'attente",
        "dl_tab_done": "Terminés",
        "dl_tab_errors": "Erreurs",
        "dl_tab_all": "Tous",
        "dl_stat_errors": "En échec",
        "dl_section_errors": "Téléchargements en échec",
        "dl_empty_errors": "Aucun téléchargement en échec",
        "dl_clean_errors": "Nettoyer les erreurs",
        "dl_no_errors": "Aucune erreur",
        "dl_no_errors_desc": "Tous vos téléchargements se déroulent sans incident.",
        "dl_btn_pause_all": "Tout mettre en pause",
        "dl_btn_resume_all": "Tout reprendre",
        "dl_btn_cancel_all": "Tout annuler",
        "dl_btn_settings": "Paramètres",
        "dl_btn_clean": "Nettoyer inactifs",
        "dl_empty_active": "Aucun téléchargement en cours",
        "dl_empty_queue": "File d'attente vide",
        "dl_empty_done": "Aucun téléchargement terminé",
        "dl_action_pause": "Pause",
        "dl_action_resume": "Reprendre",
        "dl_action_cancel": "Annuler",
        "dl_action_remove": "Retirer",
        "dl_action_retry": "Réessayer",
        "dl_action_verify": "Vérifier l'intégrité",
        "dl_action_play": "Lire",
        "dl_limit_btn": "Limiter",
        "dl_limit_modify": "Modifier",
        "dl_speed_modal_title": "Limiter la vitesse de téléchargement",
        "dl_speed_modal_desc": "Définissez un débit maximal pour ce téléchargement (en Ko/s). Entrez 0 pour aucune limite.",
        "dl_speed_modal_apply": "Appliquer",
        "dl_speed_modal_cancel": "Annuler",

        # Task statuses
        "status_pending": "En attente",
        "status_scheduled": "Planifié",
        "status_downloading": "Téléchargement",
        "status_retrying": "Nouvelle tentative",
        "status_paused": "Pause",
        "status_completed": "Terminé",
        "status_failed": "Échec",
        "status_cancelled": "Annulé",
        "status_muxing": "Multiplexage",

        # Verification statuses
        "verif_verified": "✓ Intègre",
        "verif_corrupted": "✗ Corrompu",
        "verif_empty": "✗ Vide",
        "verif_missing": "✗ Fichier introuvable",
        "verif_unverified": "Non vérifié",

        # Library page
        "lib_title": "Bibliothèque Locale",
        "lib_sub": "Tous vos animes et épisodes téléchargés sur votre machine.",
        "lib_stat_animes": "Animes",
        "lib_stat_episodes": "Épisodes",
        "lib_stat_disk": "Espace disque",
        "lib_stat_integrity": "Intégrité globale",
        "lib_search_placeholder": "Filtrer la bibliothèque...",
        "lib_filter_all": "Tous",
        "lib_filter_verified": "✓ Intègres",
        "lib_filter_issues": "⚠️ Problèmes",
        "lib_btn_verify_all": "Vérifier l'intégrité de la bibliothèque",
        "lib_btn_sync": "Actualiser les dossiers",
        "lib_empty_title": "Bibliothèque vide",
        "lib_empty_sub": "Téléchargez vos premiers épisodes depuis la recherche pour les voir apparaître ici.",

        # History page
        "hist_title": "Historique de lecture & téléchargements",
        "hist_sub": "Retrouvez l'historique complet de vos sessions de visionnage et de vos téléchargements.",
        "hist_stat_plays": "Lectures",
        "hist_stat_downloads": "Téléchargements",
        "hist_stat_time": "Temps total estimé",
        "hist_filter_all": "Tous",
        "hist_filter_watched": "Lectures",
        "hist_filter_downloaded": "Téléchargements",
        "hist_btn_clear": "Effacer l'historique",
        "hist_th_anime": "Anime",
        "hist_th_episode": "Épisode",
        "hist_th_source": "Source",
        "hist_th_date": "Date",
        "hist_th_status": "Statut",
        "hist_th_actions": "Actions",
        "hist_empty_title": "Aucun historique",
        "hist_empty_sub": "Vos lectures et téléchargements récents apparaîtront ici.",

        # Extensions page
        "ext_title": "Gestionnaire d'Extensions",
        "ext_sub": "Gérez et découvrez des connecteurs et parsers Aniyomi / Tachiyomi pour débloquer de nouveaux catalogues.",
        "ext_btn_check_updates": "Vérifier les mises à jour",
        "ext_btn_add_repo": "Ajouter un dépôt",
        "ext_search_placeholder": "Rechercher une extension...",
        "ext_filter_all_langs": "Toutes les langues",
        "ext_filter_fr": "Français",
        "ext_filter_en": "Anglais",
        "ext_filter_multi": "Multi",
        "ext_badge_installed": "Installé",
        "ext_badge_active": "Actif",
        "ext_badge_inactive": "Désactivé",
        "ext_badge_new": "Nouveau",
        "ext_btn_install": "Installer",
        "ext_btn_uninstall": "Désinstaller",
        "ext_repo_modal_title": "Ajouter un dépôt de plugins",
        "ext_repo_modal_desc": "Saisissez l'URL d'un dépôt d'extensions Aniyomi compatible (index.min.json).",
        "ext_repo_modal_import": "Importer",
        "ext_repo_modal_close": "Fermer",

        # Settings page
        "set_title": "Configuration & Préférences",
        "set_sub": "Ajustez les paramètres de connexion, le moteur de téléchargement et l'organisation des médias.",
        "set_tab_general": "Général",
        "set_tab_downloads": "Téléchargements",
        "set_tab_sources": "Sources",
        "set_tab_system": "Système",
        "set_tab_proxy": "Réseau & Proxy",
        "set_proxy_title": "Configuration du Serveur Proxy",
        "set_proxy_sub": "Acheminez le trafic réseau, les recherches de flux et les téléchargements via un proxy HTTP ou SOCKS.",
        "set_proxy_enable_title": "Activer le proxy réseau",
        "set_proxy_enable_desc": "Lorsque cette option est activée, toutes les requêtes externes transitent par ce serveur proxy.",
        "set_proxy_type_title": "Protocole du proxy",
        "set_proxy_type_desc": "Sélectionnez le protocole supporté par votre serveur proxy (HTTP, HTTPS ou SOCKS5).",
        "set_proxy_host_title": "Hôte / Adresse IP",
        "set_proxy_host_desc": "Nom d'hôte ou adresse IP (ex: 127.0.0.1, proxy.example.com).",
        "set_proxy_port_title": "Port",
        "set_proxy_port_desc": "Numéro de port d'écoute (ex: 1080 pour SOCKS5, 8080 pour HTTP, 9050 pour Tor).",
        "set_proxy_auth_title": "Authentification (Optionnel)",
        "set_proxy_auth_desc": "Laissez vide si votre proxy ne requiert pas d'identifiants.",
        "set_proxy_user_label": "Identifiant / Utilisateur",
        "set_proxy_pass_label": "Mot de passe",
        "set_proxy_custom_title": "URL complète personnalisée (Optionnel)",
        "set_proxy_custom_desc": "Laissez vide pour générer automatiquement l'URL à partir des champs ci-dessus.",
        "set_proxy_test_btn": "Tester la connexion",
        "set_proxy_testing": "Test en cours...",
        "set_proxy_test_ok": "Connexion proxy réussie ! IP de sortie : {ip} ({latency} ms)",
        "set_proxy_test_fail": "Échec de connexion au proxy : {error}",
        "set_proxy_effective_url": "URL effective",
        "set_proxy_not_configured": "Non configuré",
        "set_proxy_test_desc": "Vérifiez l'accessibilité du proxy, la latence et l'adresse IP publique de sortie.",
        "offline_waiting": "En attente du réseau...",
        "offline_prompt": "Connexion interrompue. Se connecter via un proxy ?",
        "offline_btn_enable": "Activer le proxy",
        "offline_btn_configure": "Configurer un proxy",
        "offline_btn_settings": "Paramètres",
        "offline_reconnected": "Connecté !",
        "offline_dismiss": "Ignorer",
        "offline_proxy_enabling": "Activation du proxy...",
        "offline_proxy_enabled": "Proxy activé !",
        "set_lang_title": "Langue de l'interface",
        "set_lang_desc": "Langue d'affichage de l'application et des messages système.",
        "set_ua_title": "User-Agent HTTP",
        "set_ua_desc": "Empreinte navigateur transmise lors des requêtes pour contourner les protections anti-bot.",
        "set_ua_custom_title": "User-Agent personnalisé",
        "set_ua_custom_desc": "Saisissez une chaîne User-Agent brute valide.",
        "set_plex_title": "Organisation des dossiers Plex / Jellyfin",
        "set_plex_desc": "Structure automatiquement les dossiers en Nom Anime/Season 01/Nom Anime - S01E01.mp4.",
        "set_max_concurrent_title": "Téléchargements simultanés",
        "set_max_concurrent_desc": "Nombre maximal de fichiers téléchargés en parallèle. Les autres restent en attente.",
        "set_speed_limit_title": "Limite globale de vitesse de téléchargement",
        "set_speed_limit_desc": "Débit maximal alloué à l'ensemble des téléchargements actifs (0 = illimité).",
        "set_save_btn": "Enregistrer les modifications",
        "set_save_success": "Paramètres enregistrés avec succès",
        "set_system_storage_title": "Dossier de stockage des téléchargements",
        "set_system_ffmpeg_title": "Statut de FFmpeg",
        "set_system_ffmpeg_ok": "Installé et opérationnel (Multiplexage & Fusion HLS activés)",
        "set_system_ffmpeg_ko": "Non détecté (Le multiplexage automatique ne sera pas disponible)",

        # Common toasts & alerts
        "toast_dl_started": "Téléchargement lancé !",
        "toast_dl_all_paused": "Tous les téléchargements ont été mis en pause",
        "toast_dl_all_resumed": "Tous les téléchargements ont été repris",
        "toast_dl_all_cancelled": "Tous les téléchargements ont été annulés",
        "toast_dl_clean": "Tâches inactives nettoyées",
        "toast_all_watched": "Tous les épisodes ont été marqués comme vus",
        "toast_all_unwatched": "Tous les épisodes ont été marqués comme non vus",
        "toast_settings_saved": "Paramètres enregistrés avec succès",
        "toast_error": "Une erreur est survenue",
        "toast_conn_error": "Erreur de connexion au serveur",
        "toast_theme_switched": "Thème basculé : {theme}",
        "toast_lang_switched": "Langue basculée en Français",

        # Additional keys
        "dl_hint_reorder": "Les premiers épisodes de la file sont téléchargés en priorité. Vous pouvez réordonner par glisser-déposer.",
        "dl_section_active": "Téléchargements en cours",
        "dl_section_queue": "En file d'attente",
        "dl_section_done": "Terminés et inactifs",
        "dl_verify_files_btn": "Vérifier les fichiers",
        "dl_no_active_now": "Aucun téléchargement actif en ce moment",
        "dl_active_empty": "Aucun téléchargement actif",
        "lib_stat_favs": "Animes favoris",
        "lib_stat_hist": "Entrées d'historique",
        "lib_stat_watchdog": "Watchdog (Nouveaux épisodes)",
        "lib_watchdog_active": "Actif",
        "lib_check_releases": "Vérifier les sorties",
        "lib_clear_all": "Vider la bibliothèque",
        "lib_recent_activity": "Activité récente",
        "lib_recent_activity_sub": "Derniers téléchargements complétés ou modifiés.",
        "lib_view_all_history": "Voir tout l'historique",
        "lib_fav_badge": "Favori",
        "lib_auto_dl": "Auto-DL",
        "hist_entries_total": "{count} entrée(s) au total",
        "hist_clean_failed": "Nettoyer échecs",
        "hist_th_file": "Fichier",
        "hist_th_size": "Taille",
        "ext_header_title": "Magasins & Extensions Aniyomi",
        "ext_header_sub": "Importez vos dépôts d'extensions compatibles (Yuzono, Keiyoushi, etc.) et activez à la carte les sources anime de votre choix.",
        "ext_active_sources": "{enabled} / {total} sources actives",
        "ext_add_repo_title": "Ajouter un magasin d'extensions",
        "ext_add_repo_sub": "Entrez l'URL d'un dépôt d'extensions (fichier index.min.json). Seul le dernier magasin ajouté est visible.",
        "ext_import_btn": "Importer le magasin",
        "ext_recommended_repos": "Dépôts recommandés :",
        "ext_active_repo_label": "Magasin actif :",
        "ext_catalog_count": "Catalogue : {count} extensions",
        "ext_active_count": "Actives : {count}",
        "ext_filter_active_only": "⚡ Activées uniquement",
        "ext_filter_placeholder": "Filtrer une extension...",
        "home_quick_lib": "Bibliothèque rapide",
        "home_view_all": "Tout afficher",
        "home_open_manager": "Ouvrir le gestionnaire",
        "home_clear_search": "Effacer",
        "home_search_for": "Recherche pour",
    },
    "en": {
        # Navigation & Shell
        "nav_brand": "AnimeLab",
        "nav_home": "Home",
        "nav_search": "Search",
        "nav_downloads": "Downloads",
        "nav_library": "Library",
        "nav_history": "History",
        "nav_extensions": "Extensions",
        "nav_settings": "Settings",
        "theme_toggle_title": "Toggle Theme",
        "lang_switch_title": "Switch Language (FR / EN)",

        # Search & Command Palette
        "search_placeholder": "Search for an anime...",
        "palette_search_placeholder": "Search an anime, movie or series...",
        "palette_clear_title": "Clear search",
        "palette_esc_badge": "Esc",
        "palette_tab_all": "All (Multi)",
        "palette_empty_hint": "Type at least 2 characters to search across all catalogs...",
        "palette_loading": "Live search...",
        "palette_no_results": "No results found for this search.",
        "palette_view_details": "View anime details",
        "palette_hint_navigate": "Navigate",
        "palette_hint_open": "Open",
        "palette_hint_close": "Close",
        "palette_ready": "Ready",
        "palette_results_count": "{count} result(s)",

        # Home page (index.html)
        "home_hero_title": "Your all-in-one anime platform",
        "home_hero_sub": "Search, stream and download your favorite anime with multi-threaded downloads and network resilience.",
        "home_source_label": "Anime Source",
        "home_search_btn": "Search",
        "home_filter_all": "All",
        "home_filter_vf": "VF (French Dub)",
        "home_filter_vostfr": "VOSTFR (Subbed)",
        "home_latest_releases": "Latest Releases",
        "home_recent_episodes": "Recent Episodes",
        "home_explore_catalog": "Explore Catalog",
        "home_empty_title": "No anime found",
        "home_empty_sub": "Try another search query or check the selected source.",
        "anime_card_view": "View details",
        "anime_card_episodes": "episodes",

        # Anime Detail page
        "detail_synopsis_title": "Synopsis",
        "detail_no_synopsis": "Synopsis not available for this anime.",
        "detail_chapters": "chapters",
        "detail_episodes": "episodes",
        "detail_range_all": "All",
        "detail_search_ep_placeholder": "Episode #...",
        "detail_search_ep_title": "Filter a specific episode number",
        "detail_batch_all": "All",
        "detail_batch_not_downloaded": "Not downloaded",
        "detail_batch_not_watched": "Unwatched",
        "detail_batch_invert": "Invert",
        "detail_batch_server": "Server:",
        "detail_batch_quality": "Quality:",
        "detail_batch_subtitles": "Subtitles",
        "detail_batch_subtitles_title": "Download subtitles for all selected episodes",
        "detail_batch_selected_count": "{count} selected",
        "detail_batch_download_btn": "Download selection",
        "detail_batch_server_auto": "Auto (Default)",
        "detail_batch_quality_auto": "Auto / Max",
        "detail_ep_subtitles": "Subtitles",
        "detail_ep_subtitles_active": "✓ Subtitles",
        "detail_ep_subtitles_title": "Enable / disable subtitles download for this episode",
        "detail_ep_tracks": "Tracks ▾",
        "detail_ep_tracks_title": "Choose subtitle track (French, English, etc.)",
        "detail_ep_downloaded": "Downloaded",
        "detail_ep_queued": "In queue",
        "detail_ep_play_local_title": "Local playback (Hard drive)",
        "detail_ep_play_stream_title": "Direct stream (Online)",
        "detail_ep_download_title": "Download episode",
        "detail_fab_start": "Start",
        "detail_fab_resume": "Resume (Ep. {num})",
        "detail_fab_rewatch": "Rewatch (Ep. 1)",

        # Modals
        "modal_quality_title": "Choose Video Quality",
        "modal_quality_close": "Close",
        "modal_subtitle_title": "Available Subtitle Tracks",
        "modal_subtitle_close": "Close",
        "modal_subtitle_none": "No alternative subtitle tracks found.",
        "modal_subtitle_active": "✓ Active",
        "modal_subtitle_select": "Select",

        # Downloads page
        "dl_title": "Download Manager",
        "dl_sub": "Manage your queue, priorities and active downloads in real-time.",
        "dl_stat_active": "Active Downloads",
        "dl_stat_queued": "In Queue",
        "dl_stat_speed": "Current Speed",
        "dl_tab_queue": "Queue",
        "dl_tab_done": "Completed",
        "dl_tab_errors": "Errors",
        "dl_tab_all": "All",
        "dl_stat_errors": "Failed",
        "dl_section_errors": "Failed Downloads",
        "dl_empty_errors": "No failed downloads",
        "dl_clean_errors": "Clean Errors",
        "dl_no_errors": "No errors",
        "dl_no_errors_desc": "All your downloads are proceeding without issues.",
        "dl_btn_pause_all": "Pause All",
        "dl_btn_resume_all": "Resume All",
        "dl_btn_cancel_all": "Cancel All",
        "dl_btn_settings": "Settings",
        "dl_btn_clean": "Clean Inactive",
        "dl_empty_active": "No active downloads",
        "dl_empty_queue": "Download queue is empty",
        "dl_empty_done": "No completed downloads",
        "dl_action_pause": "Pause",
        "dl_action_resume": "Resume",
        "dl_action_cancel": "Cancel",
        "dl_action_remove": "Remove",
        "dl_action_retry": "Retry",
        "dl_action_verify": "Verify integrity",
        "dl_action_play": "Play",
        "dl_limit_btn": "Limit",
        "dl_limit_modify": "Modify",
        "dl_speed_modal_title": "Limit download speed",
        "dl_speed_modal_desc": "Set a maximum transfer rate for this download (in KB/s). Enter 0 for unlimited.",
        "dl_speed_modal_apply": "Apply",
        "dl_speed_modal_cancel": "Cancel",

        # Task statuses
        "status_pending": "Pending",
        "status_scheduled": "Scheduled",
        "status_downloading": "Downloading",
        "status_retrying": "Retrying",
        "status_paused": "Paused",
        "status_completed": "Completed",
        "status_failed": "Failed",
        "status_cancelled": "Cancelled",
        "status_muxing": "Muxing",

        # Verification statuses
        "verif_verified": "✓ Verified",
        "verif_corrupted": "✗ Corrupted",
        "verif_empty": "✗ Empty",
        "verif_missing": "✗ File not found",
        "verif_unverified": "Unverified",

        # Library page
        "lib_title": "Local Library",
        "lib_sub": "All your downloaded anime and episodes on your machine.",
        "lib_stat_animes": "Anime",
        "lib_stat_episodes": "Episodes",
        "lib_stat_disk": "Disk Space",
        "lib_stat_integrity": "Overall Integrity",
        "lib_search_placeholder": "Filter library...",
        "lib_filter_all": "All",
        "lib_filter_verified": "✓ Verified",
        "lib_filter_issues": "⚠️ Issues",
        "lib_btn_verify_all": "Verify library integrity",
        "lib_btn_sync": "Refresh folders",
        "lib_empty_title": "Library is empty",
        "lib_empty_sub": "Download your first episodes from search to see them appear here.",

        # History page
        "hist_title": "Watch & Download History",
        "hist_sub": "View complete history of your watch sessions and downloads.",
        "hist_stat_plays": "Plays",
        "hist_stat_downloads": "Downloads",
        "hist_stat_time": "Estimated Time",
        "hist_filter_all": "All",
        "hist_filter_watched": "Watched",
        "hist_filter_downloaded": "Downloads",
        "hist_btn_clear": "Clear History",
        "hist_th_anime": "Anime",
        "hist_th_episode": "Episode",
        "hist_th_source": "Source",
        "hist_th_date": "Date",
        "hist_th_status": "Status",
        "hist_th_actions": "Actions",
        "hist_empty_title": "No history",
        "hist_empty_sub": "Your recent watch sessions and downloads will appear here.",

        # Extensions page
        "ext_title": "Extension Manager",
        "ext_sub": "Manage and discover Aniyomi / Tachiyomi connectors to unlock new anime catalogs.",
        "ext_btn_check_updates": "Check for updates",
        "ext_btn_add_repo": "Add repository",
        "ext_search_placeholder": "Search an extension...",
        "ext_filter_all_langs": "All languages",
        "ext_filter_fr": "French",
        "ext_filter_en": "English",
        "ext_filter_multi": "Multi",
        "ext_badge_installed": "Installed",
        "ext_badge_active": "Active",
        "ext_badge_inactive": "Disabled",
        "ext_badge_new": "New",
        "ext_btn_install": "Install",
        "ext_btn_uninstall": "Uninstall",
        "ext_repo_modal_title": "Add Plugin Repository",
        "ext_repo_modal_desc": "Enter the URL of a compatible Aniyomi extension repository (index.min.json).",
        "ext_repo_modal_import": "Import",
        "ext_repo_modal_close": "Close",

        # Settings page
        "set_title": "Configuration & Preferences",
        "set_sub": "Configure connection parameters, download engine and media organization.",
        "set_tab_general": "General",
        "set_tab_downloads": "Downloads",
        "set_tab_sources": "Sources",
        "set_tab_system": "System",
        "set_tab_proxy": "Network & Proxy",
        "set_proxy_title": "Proxy Server Configuration",
        "set_proxy_sub": "Route network traffic, stream scraping, and downloads through an HTTP or SOCKS proxy.",
        "set_proxy_enable_title": "Enable network proxy",
        "set_proxy_enable_desc": "When enabled, all external outbound requests will route through this proxy server.",
        "set_proxy_type_title": "Proxy Protocol",
        "set_proxy_type_desc": "Select the protocol supported by your proxy server (HTTP, HTTPS, or SOCKS5).",
        "set_proxy_host_title": "Host / IP Address",
        "set_proxy_host_desc": "Hostname or IP address (e.g. 127.0.0.1, proxy.example.com).",
        "set_proxy_port_title": "Port",
        "set_proxy_port_desc": "Listening port number (e.g. 1080 for SOCKS5, 8080 for HTTP, 9050 for Tor).",
        "set_proxy_auth_title": "Authentication (Optional)",
        "set_proxy_auth_desc": "Leave blank if your proxy does not require authentication credentials.",
        "set_proxy_user_label": "Username",
        "set_proxy_pass_label": "Password",
        "set_proxy_custom_title": "Custom Full URL (Optional)",
        "set_proxy_custom_desc": "Leave empty to automatically construct the proxy URL from the structured fields above.",
        "set_proxy_test_btn": "Test Connection",
        "set_proxy_testing": "Testing connection...",
        "set_proxy_test_ok": "Proxy connection successful! Exit IP: {ip} ({latency} ms)",
        "set_proxy_test_fail": "Proxy connection failed: {error}",
        "set_proxy_effective_url": "Effective URL",
        "set_proxy_not_configured": "Not configured",
        "set_proxy_test_desc": "Verify proxy reachability, latency and exit public IP address.",
        "offline_waiting": "Waiting for network...",
        "offline_prompt": "Connection lost. Connect via proxy?",
        "offline_btn_enable": "Enable proxy",
        "offline_btn_configure": "Configure proxy",
        "offline_btn_settings": "Settings",
        "offline_reconnected": "Connected!",
        "offline_dismiss": "Dismiss",
        "offline_proxy_enabling": "Enabling proxy...",
        "offline_proxy_enabled": "Proxy enabled!",
        "set_lang_title": "Interface Language",
        "set_lang_desc": "Display language for the web application and notifications.",
        "set_ua_title": "HTTP User-Agent",
        "set_ua_desc": "Browser fingerprint sent during requests to bypass anti-bot protections.",
        "set_ua_custom_title": "Custom User-Agent",
        "set_ua_custom_desc": "Enter a valid raw User-Agent string.",
        "set_plex_title": "Plex / Jellyfin Folder Organization",
        "set_plex_desc": "Automatically structures folders as Anime Name/Season 01/Anime Name - S01E01.mp4.",
        "set_max_concurrent_title": "Simultaneous Downloads",
        "set_max_concurrent_desc": "Maximum number of parallel downloads. Additional downloads remain in queue.",
        "set_speed_limit_title": "Global Download Speed Limit",
        "set_speed_limit_desc": "Maximum bandwidth allocated to all active downloads (0 = unlimited).",
        "set_save_btn": "Save Changes",
        "set_save_success": "Settings saved successfully",
        "set_system_storage_title": "Download Storage Directory",
        "set_system_ffmpeg_title": "FFmpeg Status",
        "set_system_ffmpeg_ok": "Installed and operational (Muxing & HLS merging enabled)",
        "set_system_ffmpeg_ko": "Not detected (Automatic multiplexing will not be available)",

        # Common toasts & alerts
        "toast_dl_started": "Download started!",
        "toast_dl_all_paused": "All downloads paused",
        "toast_dl_all_resumed": "All downloads resumed",
        "toast_dl_all_cancelled": "All downloads cancelled",
        "toast_dl_clean": "Inactive tasks cleaned",
        "toast_all_watched": "All episodes marked as watched",
        "toast_all_unwatched": "All episodes marked as unwatched",
        "toast_settings_saved": "Settings saved successfully",
        "toast_error": "An error occurred",
        "toast_conn_error": "Server connection error",
        "toast_theme_switched": "Theme switched: {theme}",
        "toast_lang_switched": "Language switched to English",

        # Additional keys
        "dl_hint_reorder": "Episodes at the top of the queue are downloaded first. You can reorder by drag-and-drop.",
        "dl_section_active": "Active downloads",
        "dl_section_queue": "In queue",
        "dl_section_done": "Completed and inactive",
        "dl_verify_files_btn": "Verify files",
        "dl_no_active_now": "No active downloads at the moment",
        "dl_active_empty": "No active downloads",
        "lib_stat_favs": "Favorite anime",
        "lib_stat_hist": "History entries",
        "lib_stat_watchdog": "Watchdog (New episodes)",
        "lib_watchdog_active": "Active",
        "lib_check_releases": "Check releases",
        "lib_clear_all": "Clear library",
        "lib_recent_activity": "Recent activity",
        "lib_recent_activity_sub": "Latest completed or updated downloads.",
        "lib_view_all_history": "View all history",
        "lib_fav_badge": "Favorite",
        "lib_auto_dl": "Auto-DL",
        "hist_entries_total": "{count} total entry(ies)",
        "hist_clean_failed": "Clean failed",
        "hist_th_file": "File",
        "hist_th_size": "Size",
        "ext_header_title": "Aniyomi Repositories & Extensions",
        "ext_header_sub": "Import compatible extension repositories (Yuzono, Keiyoushi, etc.) and selectively enable anime sources.",
        "ext_active_sources": "{enabled} / {total} active sources",
        "ext_add_repo_title": "Add an extension repository",
        "ext_add_repo_sub": "Enter the URL of an extension repository (index.min.json file). Only the latest repository is visible.",
        "ext_import_btn": "Import repository",
        "ext_recommended_repos": "Recommended repositories:",
        "ext_active_repo_label": "Active repository:",
        "ext_catalog_count": "Catalog: {count} extensions",
        "ext_active_count": "Active: {count}",
        "ext_filter_active_only": "⚡ Enabled only",
        "ext_filter_placeholder": "Filter an extension...",
        "home_quick_lib": "Quick Library",
        "home_view_all": "View all",
        "home_open_manager": "Open manager",
        "home_clear_search": "Clear",
        "home_search_for": "Search for",
    }
}


class I18nService:
    def __init__(self):
        self.default_language = DEFAULT_LANGUAGE

    def translate(self, key: str, lang: Optional[str] = None, **kwargs) -> str:
        """
        Traduit une clé dans la langue demandée.
        Repli gracieux : lang demandée -> ContextVar -> français -> clé brute.
        """
        if not lang or lang not in SUPPORTED_LANGUAGES:
            req_lang = current_request_lang.get()
            lang = req_lang if req_lang in SUPPORTED_LANGUAGES else self.default_language

        catalog = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANGUAGE])
        text = catalog.get(key)
        if text is None and "." in key:
            text = catalog.get(key.replace(".", "_"))
        if text is None and "_" in key:
            text = catalog.get(key.replace("_", "."))

        if text is None:
            # Fallback français
            fr_cat = TRANSLATIONS[DEFAULT_LANGUAGE]
            text = fr_cat.get(key)
            if text is None and "." in key:
                text = fr_cat.get(key.replace(".", "_"))
            if text is None and "_" in key:
                text = fr_cat.get(key.replace("_", "."))
            if text is None:
                text = key

        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def get_catalog(self, lang: Optional[str] = None) -> Dict[str, str]:
        """Retourne le catalogue complet de traductions pour une langue."""
        if not lang or lang not in SUPPORTED_LANGUAGES:
            req_lang = current_request_lang.get()
            lang = req_lang if req_lang in SUPPORTED_LANGUAGES else self.default_language
        return TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANGUAGE])

    def get_translations(self, lang: Optional[str] = None) -> Dict[str, str]:
        """Alias pour get_catalog."""
        return self.get_catalog(lang)

    def get_all_catalogs(self) -> Dict[str, Dict[str, str]]:
        """Retourne l'ensemble des dictionnaires (pour le client JS)."""
        return TRANSLATIONS


i18n_service = I18nService()


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    return i18n_service.translate(key, lang, **kwargs)


def current_lang() -> str:
    ctx = current_request_lang.get()
    return ctx if ctx in SUPPORTED_LANGUAGES else i18n_service.default_language


def detect_client_language(accept_language: Optional[str] = None) -> str:
    """
    Détecte automatiquement si l'utilisateur est francophone :
    1. Si le navigateur envoie un Accept-Language, analyse les priorités (q-values).
       Si le français est préféré ou présent en priorité égale, renvoie 'fr'.
       Si une autre langue est préférée (ex: en, es, de), renvoie 'en'.
    2. Si aucun Accept-Language n'est fourni, inspecte la locale système.
       Si francophone -> 'fr', sinon 'en'.
    """
    if accept_language and accept_language.strip():
        try:
            # Parser les langues avec leurs poids q=...
            langs_with_weights = []
            for item in accept_language.split(","):
                parts = item.strip().split(";")
                tag = parts[0].strip().lower()
                q = 1.0
                for p in parts[1:]:
                    p = p.strip()
                    if p.startswith("q="):
                        try:
                            q = float(p[2:])
                        except Exception:
                            pass
                if tag:
                    langs_with_weights.append((tag, q))

            if langs_with_weights:
                # Trier par poids décroissant
                langs_with_weights.sort(key=lambda x: x[1], reverse=True)
                top_q = langs_with_weights[0][1]

                # Vérifier si une variante francophone figure parmi les choix prioritaires
                for tag, q in langs_with_weights:
                    if q == top_q and tag.startswith("fr"):
                        return "fr"

                # Si le premier choix est francophone
                if langs_with_weights[0][0].startswith("fr"):
                    return "fr"

                # L'utilisateur a explicitement demandé une autre langue
                return "en"
        except Exception:
            pass

    # Fallback système (environnement local du serveur / machine utilisateur)
    try:
        sys_lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        if not sys_lang:
            loc = locale.getdefaultlocale()[0]
            sys_lang = loc or ""
        if sys_lang.lower().startswith("fr"):
            return "fr"
    except Exception:
        pass

    return "en"


def resolve_language(
    query_param: Optional[str] = None,
    cookie_lang: Optional[str] = None,
    accept_language: Optional[str] = None,
) -> str:
    """
    Résout la langue applicable selon l'ordre :
    Query param > Cookie > Détection francophone (Navigateur / Système)
    """
    if query_param and query_param in SUPPORTED_LANGUAGES:
        return query_param
    if cookie_lang and cookie_lang in SUPPORTED_LANGUAGES:
        return cookie_lang
    return detect_client_language(accept_language)
