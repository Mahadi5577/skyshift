"""Build the online showcase: the web app plus the tour and Hunt data as plain files, so it runs
on a static host such as GitHub Pages, with no server.

    python scripts/export_static.py               # writes site/
    python scripts/export_static.py --out site --patches 6

It downloads whatever is missing first (like scripts/precache.py), so it also works on a fresh
machine; .github/workflows/pages.yml runs it on every push. In the showcase, Explore offers the
tour stops at every zoom level and Hunt offers practice rounds; everything else needs the full
app. The page switches to this mode because of the <meta name="skyshift-static"> tag added here.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import __version__, precache, sequences, tour  # noqa: E402


def fixed(v, digits):
    return "" if v is None else f"{v:.{digits}f}"


def request_key(ra, dec, zoom, wave=None, n=48, tol=None, t_min=None, t_max=None):
    """Same key as requestKey() in web/js/static.js, built from a POST /api/sequence body."""
    return ",".join([fixed(ra, 5), fixed(dec, 5), zoom, fixed(wave, 3), str(n or 48),
                     fixed(tol, 3), fixed(t_min, 5), fixed(t_max, 5)])


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site", help="output folder (replaced)")
    ap.add_argument("--patches", type=int, default=6, help="ecliptic patches for Hunt mode")
    args = ap.parse_args()
    out = (ROOT / args.out).resolve()
    if out == ROOT or ROOT not in out.parents or (out / ".git").exists():
        sys.exit(f"refusing to replace {out}: pick a build folder inside the repository")

    done = precache.run(args.patches, include_tour=True, tour_zooms=True, log=lambda m: print(m, flush=True))

    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / "web", out)
    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head>\n<meta name="skyshift-static" content="1">', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")  # serve every file as it is

    data = out / "static"
    keys, exported, frames = {}, set(), 0
    for label, kw, seq in done:
        meta = seq["meta"]
        sid = meta["id"]
        keys[request_key(**kw)] = sid
        if sid in exported:
            continue
        status = []
        for i in range(len(meta["entries"])):
            raw = sequences.entry_bytes(seq, i)
            if raw is None:
                status.append("failed")
                continue
            (data / "seq" / sid).mkdir(parents=True, exist_ok=True)
            (data / "seq" / sid / f"{i}.bin").write_bytes(raw)
            status.append("ready")
            frames += 1
        write_json(data / "seq" / f"{sid}.json", meta | {"status": status, "errors": {}})
        known = seq["dir"] / "known.json"
        if known.exists():
            shutil.copyfile(known, data / "seq" / sid / "known.json")
        exported.add(sid)

    for s in tour.stops():
        cov = sequences.public_coverage(sequences.coverage(s["ra"], s["dec"]))
        write_json(data / "coverage" / f"{fixed(s['ra'], 5)}_{fixed(s['dec'], 5)}.json", cov)

    hunt = [{"id": m["id"], "n": m["n"], "zoom": m["zoom"],
             "entries": [{"mjd": e["mjd"], "date": e["date"], "wave": e["wave"]} for e in m["entries"]]}
            for m in sequences.cached_sequences(max_age=0) if m["id"] in exported]
    write_json(data / "index.json", {
        "version": __version__, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sequences": keys, "hunt": hunt, "tour": tour.stops()})
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {out}: {len(exported)} sequences, {frames} frames, {len(hunt)} Hunt patches, "
          f"{size / 1024 ** 2:.1f} MB")
    if not hunt or not keys:
        sys.exit("nothing to show: the archive may be unreachable")


if __name__ == "__main__":
    main()
