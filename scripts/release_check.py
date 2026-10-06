"""Pre-release gate for a SkyShift release archived on Zenodo (manual upload, see docs/ZENODO.md).

    python scripts/release_check.py 0.1.0            # check only
    python scripts/release_check.py 0.1.0 --write    # also regenerate .zenodo.json from CITATION.cff

Blocking problems make it exit with code 1. .zenodo.json is generated from CITATION.cff (plus the
SPHEREx dataset DOI as a related identifier) so the two never drift apart; it is the reference
for the fields to enter when publishing a new version on Zenodo.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RELATED = [  # datasets and works this software builds on
    {"identifier": "https://doi.org/10.26131/IRSA652", "relation": "references",
     "resource_type": "dataset"},
]

blockers, warnings = [], []


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, shell=isinstance(cmd, str))


def zenodo_metadata(cff):
    creators = []
    for a in cff["authors"]:
        c = {"name": f"{a.get('family-names', '')}, {a.get('given-names', '')}".strip(", ")
             if "family-names" in a else a.get("name", "")}
        if a.get("affiliation"):
            c["affiliation"] = a["affiliation"]
        if a.get("orcid"):
            c["orcid"] = a["orcid"].rsplit("/", 1)[-1]
        creators.append(c)
    return {
        "title": cff["title"],
        "upload_type": "software",
        "description": cff["abstract"],
        "creators": creators,
        "version": str(cff["version"]),
        "license": cff["license"].lower(),  # Zenodo wants lowercase ids, e.g. "bsd-3-clause"
        "access_right": "open",
        "language": "eng",
        "keywords": cff.get("keywords", []),
        "related_identifiers": RELATED,
        "notes": "Includes the experiment scripts and findings behind the design (experiments/). "
                 "Developed with generative-AI assistance; see AI_USE.md.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="the version you are about to release, e.g. 0.1.0")
    ap.add_argument("--write", action="store_true", help="regenerate .zenodo.json")
    args = ap.parse_args()

    cff_text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cff = yaml.safe_load(cff_text)

    # 1. Metadata is complete
    if "TODO" in cff_text:
        blockers.append("CITATION.cff still contains TODO placeholders (authors, affiliations)")
    if "_TODO_" in (ROOT / "AUTHORS.md").read_text(encoding="utf-8"):
        blockers.append("AUTHORS.md is not filled in and signed")
    if str(cff.get("version")) != args.version:
        blockers.append(f"CITATION.cff version is {cff.get('version')}, not {args.version}")
    code_version = re.search(r'__version__ = "(.+?)"', (ROOT / "backend" / "__init__.py").read_text()).group(1)
    if code_version != args.version:
        blockers.append(f"backend/__init__.py __version__ is {code_version}, not {args.version}")
    released = cff.get("date-released")
    if str(released) != dt.date.today().isoformat():
        warnings.append(f"CITATION.cff date-released is {released}; set it to the release day")
    for a in cff["authors"]:
        if "orcid" not in a:
            warnings.append(f"author {a.get('given-names', a.get('name'))} has no ORCID (recommended)")
    exe = shutil.which("cffconvert", path=str(Path(sys.executable).parent)) or shutil.which("cffconvert")
    v = run([exe, "--validate"]) if exe else None
    if v is None:
        blockers.append("cffconvert not found: pip install -r requirements-dev.txt")
    elif v.returncode != 0:
        blockers.append(f"CITATION.cff fails validation: {(v.stdout + v.stderr).strip()[-200:]}")

    # 2. Code is tested and pushed
    t = run([sys.executable, "-m", "pytest", "-q"])
    if t.returncode != 0:
        blockers.append("tests fail: run `pytest` to see why")
    if run(["git", "status", "--porcelain"]).stdout.strip():
        blockers.append("uncommitted changes: commit them first")
    run(["git", "fetch", "-q"])
    ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"]).stdout.strip()
    if ahead not in ("", "0"):
        blockers.append(f"{ahead} commit(s) not pushed")
    if run(["git", "tag", "-l", f"v{args.version}"]).stdout.strip():
        blockers.append(f"tag v{args.version} already exists")

    # 3. Zenodo can see the repository (its GitHub integration lists public repositories)
    vis = run(["gh", "repo", "view", "--json", "visibility", "--jq", ".visibility"]).stdout.strip()
    if vis != "PUBLIC":
        blockers.append(f"repository is {vis or 'unknown'}: make it public before enabling it in Zenodo")
    # SkyShift is versioned by manual upload under one concept DOI (docs/ZENODO.md). If Zenodo's
    # GitHub integration is on, a GitHub release would create a second, unrelated record.
    hooks = run(["gh", "api", "repos/{owner}/{repo}/hooks", "--jq", ".[].config.url"])
    if hooks.returncode != 0:
        warnings.append("could not list webhooks: confirm Zenodo's GitHub switch is OFF at "
                        "https://zenodo.org/account/settings/github/")
    elif "zenodo" in hooks.stdout:
        blockers.append("Zenodo's GitHub integration is ON: turn it off at "
                        "https://zenodo.org/account/settings/github/ (a GitHub release would make a duplicate DOI)")

    # 4. Release notes exist
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[?v?{re.escape(args.version)}\]?", changelog, re.M):
        blockers.append(f"CHANGELOG.md has no section for {args.version}")

    meta = zenodo_metadata(cff)
    path = ROOT / ".zenodo.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if args.write:
        path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote .zenodo.json (commit it before releasing)")
    elif current != meta:
        blockers.append(".zenodo.json is missing or out of date: rerun with --write, then commit")

    for w in warnings:
        print(f"  WARN   {w}")
    for b in blockers:
        print(f"  BLOCK  {b}")
    if blockers:
        print(f"\nNot ready to release {args.version}: fix the BLOCK items above.")
        return 1
    notes_path = ROOT / "cache" / f"release-notes-{args.version}.md"  # cache/ is git-ignored
    notes = re.search(rf"^## \[?v?{re.escape(args.version)}\]?.*?\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    notes_path.parent.mkdir(exist_ok=True)
    notes_path.write_text(notes.group(1).strip() + "\n", encoding="utf-8")
    v = args.version
    print(f"\nReady. Next (details in docs/ZENODO.md):\n"
          f"  git tag -a v{v} -m \"SkyShift {v}\" && git push origin v{v}\n"
          f"  git archive --format=zip --prefix=skyshift-{v}/ -o skyshift-{v}.zip v{v}\n"
          f"  Zenodo: https://zenodo.org/records/23181748 -> New version -> upload skyshift-{v}.zip -> Publish\n"
          f"  optional GitHub release: gh release create v{v} --title \"SkyShift {v}\" "
          f"--notes-file {notes_path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
