import os
import sys
from pathlib import Path

HOME_DIR = Path.home()

# Détection de l'environnement Android
IS_ANDROID = hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ or "chaquopy" in sys.modules

if IS_ANDROID:
    _data_dir = os.getenv("ANIMAN_DATA_DIR")
    if not _data_dir:
        try:
            from com.chaquo.python import Python
            _app = Python.getPlatform().getApplication()
            _data_dir = str(_app.getFilesDir().getAbsolutePath())
        except Exception:
            _data_dir = None
    if not _data_dir:
        _data_dir = "/data/data/com.animan.app/files"
    APP_STORAGE_DIR = Path(_data_dir)
    # Partial media and the library remain private. Kotlin exports completed
    # files through MediaStore on modern Android, without broad storage access.
    DEFAULT_DOWNLOAD_DIR = str(APP_STORAGE_DIR / "downloads")
    DEFAULT_DB_DIR = APP_STORAGE_DIR / "db"
    DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "animan.sqlite3")
    DEFAULT_CACHE_DIR = APP_STORAGE_DIR / "cache"
else:
    DEFAULT_DOWNLOAD_DIR = str(HOME_DIR / "Downloads" / "Animan")
    DEFAULT_DB_DIR = HOME_DIR / ".animan" / "db"
    DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "animan.sqlite3")
    DEFAULT_CACHE_DIR = HOME_DIR / ".animan" / "cache"

def parse_allowed_hosts(value: str | None) -> list[str]:
    """Parse incoming HTTP hosts independently of the server's bind address."""
    if value is None:
        return ["127.0.0.1", "localhost"]
    hosts = list(dict.fromkeys(host.strip().lower() for host in value.split(",") if host.strip()))
    if not hosts:
        raise ValueError("ANIMAN_ALLOWED_HOSTS must contain at least one host")
    for host in hosts:
        name = host[2:] if host.startswith("*.") else host
        if host != "*" and (
            not name or "*" in name or any(char.isspace() or char in ":/\\?#@" for char in name)
        ):
            raise ValueError("ANIMAN_ALLOWED_HOSTS expects hosts without schemes, ports or paths")
    return hosts


class Settings:
    MAX_MEDIA_WORKERS: int = max(1, int(os.getenv("ANIMAN_MEDIA_WORKERS", "1")))
    MAX_EXPORT_WORKERS: int = max(1, int(os.getenv("ANIMAN_EXPORT_WORKERS", "1")))
    PORT: int = int(os.getenv("ANIMAN_PORT", "8080"))
    HOST: str = os.getenv("ANIMAN_HOST", "127.0.0.1")
    ALLOWED_HOSTS: list[str] = parse_allowed_hosts(os.getenv("ANIMAN_ALLOWED_HOSTS"))
    SSL_VERIFY: bool = os.getenv("ANIMAN_SSL_VERIFY", "true").lower() in ("1", "true", "yes")

    # Sources anime
    BASE_URL: str = os.getenv("ANIMAN_BASE_URL", "https://w16.french-manga.net")
    VOIR_ANIME_URL: str = os.getenv("ANIMAN_VOIR_ANIME_URL", "https://voir-anime.to")
    ANIMEPAHE_URL: str = os.getenv("ANIMAN_ANIMEPAHE_URL", "https://animepahe.pw")
    ANIMEPAHE_BACKUP_URLS: list = [
        "https://animepahe.pw",
        "https://animepahe.com",
        "https://animepahe.org",
    ]
    ANIMEPAHE_COOKIE: str = os.getenv("ANIMAN_ANIMEPAHE_COOKIE", "")
    ANIMEPAHE_USER_AGENT: str = os.getenv(
        "ANIMAN_ANIMEPAHE_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
    )
    DEFAULT_USER_AGENT: str = os.getenv(
        "ANIMAN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    # Téléchargement
    DOWNLOAD_DIR: str = os.getenv("ANIMAN_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("ANIMAN_MAX_CONCURRENT", "3"))
    CONNECTION_TIMEOUT: float = float(os.getenv("ANIMAN_CONNECT_TIMEOUT", "15.0"))
    READ_TIMEOUT: float = float(os.getenv("ANIMAN_READ_TIMEOUT", "30.0"))
    VOIRANIME_DEFAULT_SERVER: str = os.getenv("ANIMAN_VOIRANIME_DEFAULT_SERVER", "auto")

    # TMDB (The Movie Database)
    TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")
    TMDB_ENABLED: bool = os.getenv("ANIMAN_TMDB_ENABLED", "true").lower() in ("1", "true", "yes")

    # Miroirs VoirAnime
    VOIRANIME_BACKUP_URLS: list = ["https://voiranime.io", "https://voiranime.homes"]

    # Watchdog
    WATCHDOG_INTERVAL_SECONDS: int = int(os.getenv("ANIMAN_WATCHDOG_INTERVAL", "3600"))

    # Database
    DATABASE_PATH: str = os.getenv("ANIMAN_DB_PATH", DEFAULT_DB_PATH)
    DATABASE_URL: str = f"sqlite:///{DATABASE_PATH}"

    # Proxies
    PROXIES_CONFIG: str = os.getenv("ANIMAN_PROXIES", "")

    # Internationalization (i18n)
    DEFAULT_LANGUAGE: str = os.getenv("ANIMAN_LANGUAGE", "fr")
    LOG_LANGUAGE: str = os.getenv("ANIMAN_LOG_LANGUAGE", "en")

    # Project directories
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        BASE_DIR: Path = Path(sys._MEIPASS) / "animan"
    else:
        BASE_DIR: Path = Path(__file__).resolve().parent
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    STATIC_DIR: Path = BASE_DIR / "static"
    CACHE_DIR: Path = Path(os.getenv("ANIMAN_CACHE_DIR", str(DEFAULT_CACHE_DIR)))

settings = Settings()

# Ensure directories exist safely
for _dir_path in [settings.DOWNLOAD_DIR, str(DEFAULT_DB_DIR), str(settings.CACHE_DIR)]:
    try:
        Path(_dir_path).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
