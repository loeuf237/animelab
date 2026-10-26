# Python package namespace

The engine package is `animelab`. Use imports such as:

```python
from animelab.config import settings
from animelab.models.download_task import DownloadTask
from animelab.services.download_manager import download_manager
```

The package contains the engine, routers, services, desktop launcher
and static assets. The web frontend is the Vue SPA in `frontend/`; legacy Jinja
templates and their runtime dependency have been removed. Desktop packaging uses `animelab.spec`; Android's Chaquopy
source sync/extraction and Docker copy the same `animelab/` tree. Application
entry points remain `run.py`, `desktop.py` and `android_runtime.py`.

There is no compatibility shim for Python imports under the former namespace.
Development integrations and scripts importing that namespace must update their
imports. A running source process needs a normal restart to load the new code.

Existing installation state remains compatible:

- Environment variables retain the `ANIMAN_` prefix, including the existing
  `ANIMAN_RELOAD` behavior.
- User files remain in `~/.animan`, `db/animan.sqlite3` and `Downloads/Animan`
  unless configured otherwise. Library schemas and saved download paths do not
  change as part of this refactor.
- Android keeps `com.animan.app` (including JNI bridge class names), its signing
  identity and existing storage grants. The macOS bundle identifier also stays
  unchanged.
- Existing browser storage keys, cookies and public API headers are preserved.

These identifiers are persisted compatibility contracts, not Python package
names. Renaming them independently would require a dedicated data/installation
migration.
