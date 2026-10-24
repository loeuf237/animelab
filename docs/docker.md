# Docker server

This distribution runs the Python backend and compiled Vue interface in one
container, with FFmpeg and ffprobe included. Open it in a browser; it does not
require a desktop AnimeLab process. Node.js is used only during the image build.
The server runs as UID/GID **1000:1000**, without root privileges, with one Python
process and automatic development reload disabled.

## Start

Install [Docker Engine with Compose](https://docs.docker.com/engine/install/) on
Linux, or [Docker Desktop](https://docs.docker.com/desktop/) on Windows/macOS.
Run these commands in the cloned repository:

```bash
docker compose up -d --build --wait
docker compose ps
```

Open **http://localhost:8080/app/**. The initial build downloads the base images
and dependencies, and compiles Vue. A `healthy` status means the running server
can serve the built interface. Logs are available with:

```bash
docker compose logs -f animelab
```

If the desktop application already occupies port 8080, create a `.env` file in
the repository with `ANIMELAB_PORT=8081`, then start Compose again and open
http://localhost:8081/app/. The internal container port remains 8080.

The image is built locally as `animelab:local`; no registry account is required.
CI builds and tests Linux x86_64. Other host CPU architectures are not yet
validated. This image is independent of the Android APK and desktop packages.

## Persistent storage

The default Compose project is named `animelab`, regardless of the checkout folder.

| Docker volume | Container directory | Contents |
| --- | --- | --- |
| `animelab_data` | `/data` | SQLite library and settings under `.animan/db`, installed extensions under `.animan/extensions`, cache and source sessions under `.animan/cache` |
| `animelab_downloads` | `/downloads` | Videos, subtitles, partial files and media-processing work files |

The writable home directory is `/data`. All generated user data stays outside
the application image. Existing desktop data is **not imported automatically**.
Download concurrency, speed limits, library organization, selected user agent
and default VoirAnime server are saved in SQLite and restored at startup.
Keep one server per data volume; do not run multiple replicas against the same
SQLite database and download queue.

To stop and remove the container while retaining its data:

```bash
docker compose down
```

Start it again with `docker compose up -d --wait`. **`docker compose down -v`
deletes the volumes and their contents.** Ordinary updates do not use that option.

### Use a visible folder for videos

Named volumes work without preparing host-directory permissions. If you prefer
videos in a regular folder or on a NAS disk, create `compose.override.yaml` beside
`compose.yaml`:

```yaml
services:
  animelab:
    volumes:
      - type: bind
        source: ./downloads
        target: /downloads
        bind:
          create_host_path: false
```

Create `downloads` yourself before starting Compose. On Linux, the folder must
be writable by UID/GID 1000:1000; a folder owned by your usual UID 1000 generally
works directly. On Windows/macOS, allow Docker Desktop to share the selected
location. An absolute host path can replace `./downloads`.

Compose replaces the `/downloads` mount, retaining the default data volume.
Existing files in the old named volume are not moved automatically. Change the
mount before your first download, or stop AnimeLab and copy the files to the new
location before changing it. Keep the container path `/downloads` so database
references remain valid. Personal overrides and `.env` are excluded from Git.

### Backup and update

Stop the server before copying the database, so the database and SQLite WAL
files are consistent. To copy both persistent directories into an existing
`backup` folder without deleting the stopped container:

```bash
docker compose stop
docker compose cp animelab:/data/.animan ./backup/
docker compose cp animelab:/downloads ./backup/
docker compose start
```

Backups contain source sessions and private settings; keep them private. Before
an update, back up both directories. From a clean checkout:

```bash
git pull --ff-only
docker compose up -d --build --wait
```

The volumes survive image rebuilds and container replacement. A database schema
upgrade can prevent running older code against it; restoring an older version
may require restoring its matching backup.

## Configuration and access

Compose reads these optional values from `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANIMELAB_PORT` | `8080` | Host port |
| `ANIMELAB_BIND_ADDRESS` | `127.0.0.1` | Host address on which the port is published |
| `ANIMAN_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Accepted incoming HTTP hosts, comma-separated, without schemes or ports |
| `ANIMELAB_LANGUAGE` | `fr` | Default application language; browser language detection still applies |
| `ANIMELAB_STARTUP_REFRESH` | `true` | Refresh source feeds and the proxy list on startup |

For access from a trusted LAN, set both the bind address and the accepted hosts
in `.env` (replace the example IP with the server's actual address):

```dotenv
ANIMELAB_BIND_ADDRESS=0.0.0.0
ANIMAN_ALLOWED_HOSTS=127.0.0.1,localhost,192.168.1.50
```

Then open `http://SERVER_IP:8080/app/`. Unlisted HTTP hosts receive HTTP 400;
binding to all interfaces does not authorize all hostnames. Include the public
hostname when using a reverse proxy. The server has no multi-user login system;
do not publish it directly to the Internet. Port binding defaults to this computer.
Additional backend `ANIMAN_*` variables can be set in the service's `environment`
through a Compose override. Paths inside the container differ from host paths.

The image has no graphical browser or native WebView. Website verification can
offer a manual link in your browser, but that visit does not transfer browser
cookies to the container. Capturing cookies from the host browser is unavailable
in this distribution. Source protections and provider limitations still apply.
Host-only diagnostic export is also unavailable through the forwarded port;
do not weaken its loopback restriction to expose it.

## Automated checks

The Docker CI job builds the complete image from source and runs:

```bash
python3 scripts/docker_smoke.py
```

The smoke test uses a unique temporary Compose project, random loopback port and
fresh volumes. It checks non-root execution, Vue assets and the API, actual
FFmpeg encoding/decoding, graceful shutdown, then replaces the container and
checks retained settings, favorites, extension/session directories and HTTP
Range playback of the retained video. It removes only its own temporary volumes.
No existing AnimeLab server, user library or external source is used.
