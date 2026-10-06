# Releasing SkyShift

Releases are archived on Zenodo by manual upload, under concept DOI
[10.5281/zenodo.23181747](https://doi.org/10.5281/zenodo.23181747). The full procedure is in
**[ZENODO.md](ZENODO.md)**.

## Every release, in short
1. Bump `version` and `date-released` in `CITATION.cff` and `__version__` in
   `backend/__init__.py`, and turn `CHANGELOG.md`'s "Unreleased" section into the version's
   section.
2. Run `python scripts/release_check.py X.Y.Z --write` until it says **Ready** (commit and push
   in between).
3. `git tag -a vX.Y.Z -m "SkyShift X.Y.Z" && git push origin vX.Y.Z`
4. `git archive --format=zip --prefix=skyshift-X.Y.Z/ -o skyshift-X.Y.Z.zip vX.Y.Z`
5. On Zenodo, open the record, press **New version**, upload the zip, update the version and
   date, then press **Publish**.
6. Record the new version DOI in `CITATION.cff` and `CHANGELOG.md`.

## What the release check enforces
- No `TODO` in `CITATION.cff` or `AUTHORS.md`; `CITATION.cff` is valid, and it and
  `backend/__init__.py` have the right version.
- Tests pass; nothing uncommitted or unpushed; the tag doesn't exist yet.
- The repository is public.
- Zenodo's GitHub integration is **off** (otherwise a GitHub release would create a duplicate
  record).
- `CHANGELOG.md` has notes for the version; `.zenodo.json` matches `CITATION.cff`.
- Warnings, which don't block: no ORCID for an author, and a release date that isn't today.

## ASCL (later)
ASCL only registers code used in research that is published, submitted for peer review, or part
of an accepted thesis. Submit at https://ascl.net/code/submit once the first paper is submitted,
using `docs/outreach/ascl-entry.md`.
