# Running SkyShift as a public website

SkyShift is one Python web server (FastAPI + uvicorn) that serves both the web page and the
API. For a public site, run it in the Docker image from the [`Dockerfile`](../Dockerfile). The
image runs on any Docker host.

The server is fastest close to the data. The SPHEREx pixels sit in an AWS bucket in the US, so
a frame takes about 0.4 s to read there (modelled), against ~2.6 s on our ~240 ms test
connection. Visitors' browsers only fetch small, already-processed frames from the server.

## Settings

All settings are environment variables. Defaults suit a laptop; the Docker image changes the
ones marked *.

| Variable | Default | What it does |
|---|---|---|
| `PORT` | 8000 (* 7860) | Port to listen on |
| `SKYSHIFT_CACHE` | `./cache` (* `/data/cache`) | Downloaded data. Safe to delete; rebuilt on demand |
| `SKYSHIFT_DATA` | `./data` (* `/data`) | Hunt players, rounds and flags (`hunt.sqlite`). **Keep it** |
| `SKYSHIFT_CACHE_MAX_MB` | 2048 | Above this, the least recently used downloads are deleted every 10 min. Tour stops and precached Hunt patches are never deleted. 0 = no limit |
| `SKYSHIFT_RATE_LIMIT` | 30 | Archive-heavy requests (name lookups, archive searches, new views, known objects) per minute per visitor. Other requests get 20 times more. 0 = off |
| `SKYSHIFT_MAX_FETCHES` | 6 | Views downloading at once. Beyond that, visitors get "busy" and the page retries by itself |
| `SKYSHIFT_PRECACHE` | 0 (* 1) | 1 = download the tour and 6 Hunt patches in the background at start-up |
| `SKYSHIFT_PRECACHE_PATCHES` | 6 | Number of ecliptic Hunt patches for that precache |
| `SKYSHIFT_BACKUP_REPO` | off | Hugging Face dataset (e.g. `your-name/skyshift-hunt`) that the Hunt database is backed up to. Only needed where the disk is wiped on restart |
| `HF_TOKEN` | off | Hugging Face token that may write to that dataset. Set it as a **secret** |
| `FORWARDED_ALLOW_IPS` | 127.0.0.1 (* `*`) | Which proxies uvicorn trusts for the visitor's address. `*` is only safe behind a proxy, as on Hugging Face |

Check a running server at `/api/health`: version, downloads in progress, cache size, Hunt pool
size and precache state.

## Option A: Hugging Face Space (free)

A free "CPU basic" Space (2 vCPU, 16 GB RAM) is enough. It runs in the US, close to the data.
You need no credit card, and **the upload runs on GitHub's servers**, so nothing large leaves your
computer.

1. Create a free account at https://huggingface.co.
2. Create a token at https://huggingface.co/settings/tokens with **write** access.
3. In the GitHub repository, open **Settings > Secrets and variables > Actions**:
   - **Secrets** tab: add `HF_TOKEN` = the token.
   - **Variables** tab: add `HF_SPACE` = `your-hf-name/skyshift`.
4. Open **Actions > Deploy to Hugging Face > Run workflow**. The workflow creates the Space if
   needed and uploads `backend/`, `web/`, `scripts/`, the `Dockerfile` and the Space's card
   ([`deploy/huggingface/README.md`](../deploy/huggingface/README.md)). With **backup** ticked
   (the default), it also sets up the Hunt database backup described below.
5. Hugging Face builds the image (about 5-10 minutes), then the app opens at
   `https://huggingface.co/spaces/your-hf-name/skyshift`. The first start precaches the tour
   and Hunt patches in the background. Watch `/api/health` until `precache` says `done`.
6. Run the workflow again whenever you want the Space to pick up new code from `main`.

### Keep Hunt data across restarts
A free Space's disk is wiped every time it restarts or rebuilds. A Space also sleeps after a
couple of days without visitors, and waking it is a restart. The download cache simply comes
back, but players and the candidate board would be lost. Choose one:

- **Free (the workflow's default):** back the database up to a private dataset. The workflow
  stores your token as the Space secret `HF_TOKEN` and sets the Space variable
  `SKYSHIFT_BACKUP_REPO` = `your-hf-name/skyshift-hunt`. Space secrets are hidden from
  visitors; only the server code reads it. The server creates the private dataset, restores
  from it at start-up, and uploads a copy every 10 minutes when something changed and once
  more at shutdown. You can lose up to 10 minutes of play. To do this by hand instead, untick
  **backup** and add the two settings in the Space's **Settings > Variables and secrets**.
- **Paid:** add persistent storage to the Space. It is mounted at `/data`, where the image
  already keeps its data.

## Option B: any Docker host

```bash
docker build -t skyshift .
docker run -d --name skyshift -p 7860:7860 -v skyshift-data:/data --restart unless-stopped skyshift
```

The named volume keeps the cache and the Hunt database across restarts and upgrades. Put a
reverse proxy with HTTPS (Caddy, nginx) in front. Set `FORWARDED_ALLOW_IPS` to the proxy's
address, or the rate limit sees only the proxy (with `*` and no proxy, a visitor could fake
their address and dodge the limit).

## Option C: without Docker

```bash
pip install -r requirements.txt
SKYSHIFT_HOST=0.0.0.0 PORT=8000 bash run.sh     # Windows: set SKYSHIFT_HOST=0.0.0.0, then run.bat
```

Run one server process only: the download queue and the limits live in that process's
memory.

## What a public server stores
- **Hunt:** each player's chosen name, a hash of a random key kept in their browser (so nobody
  else can play under that name), their scores, and the positions they flag in real rounds.
- **Not stored:** IP addresses. They are only held in memory for the rate limit. The host's own
  access logs may still record them, so check your host's policy if you publish a privacy
  notice.
