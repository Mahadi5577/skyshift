"""Optional backup of the Hunt database to a private Hugging Face dataset repository, for hosts
whose disk is wiped on every restart (such as a free Hugging Face Space).

Off unless SKYSHIFT_BACKUP_REPO (e.g. "your-name/skyshift-hunt") and HF_TOKEN are set. At start-up
the last backup is restored if there is no local database; afterwards the server uploads a
snapshot whenever the database has changed (checked every few minutes) and once more on shutdown.
"""
import logging
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from . import config, hunt

log = logging.getLogger("skyshift.backup")
FILE = "hunt.sqlite"
_last = {"mtime": None, "repo": False}


def enabled():
    return bool(config.BACKUP_REPO and config.HF_TOKEN)


def _api():
    from huggingface_hub import HfApi  # only needed on servers that use the backup
    return HfApi(token=config.HF_TOKEN)


def _ensure_repo(api):
    if not _last["repo"]:
        api.create_repo(config.BACKUP_REPO, repo_type="dataset", private=True, exist_ok=True)
        _last["repo"] = True


def restore(api=None):
    """Fetch the last backup if there is no local database yet. Returns True if one was restored."""
    if not enabled() or hunt.DB.exists():
        return False
    api = api or _api()
    try:
        _ensure_repo(api)
        with tempfile.TemporaryDirectory() as d:
            path = api.hf_hub_download(config.BACKUP_REPO, FILE, repo_type="dataset", local_dir=d)
            hunt.DB.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, hunt.DB)
    except Exception as e:  # first run (no backup yet) or the Hub is unreachable
        log.warning("Hunt database not restored from %s: %s", config.BACKUP_REPO, e)
        return False
    _last["mtime"] = hunt.DB.stat().st_mtime
    log.info("Hunt database restored from %s", config.BACKUP_REPO)
    return True


def sync(api=None):
    """Upload a consistent snapshot of the Hunt database if it changed since the last upload."""
    if not enabled() or not hunt.DB.exists():
        return False
    mtime = hunt.DB.stat().st_mtime
    if mtime == _last["mtime"]:
        return False
    api = api or _api()
    _ensure_repo(api)
    with tempfile.TemporaryDirectory() as d:
        snap = Path(d) / FILE
        with closing(sqlite3.connect(hunt.DB)) as src, closing(sqlite3.connect(snap)) as dst:
            src.backup(dst)
        api.upload_file(path_or_fileobj=str(snap), path_in_repo=FILE, repo_id=config.BACKUP_REPO,
                        repo_type="dataset", commit_message="Hunt database backup")
    _last["mtime"] = mtime
    return True
