# Releasing SkyShift

The first release (with Zenodo setup) is covered in **[ZENODO.md](ZENODO.md)**, step by step.

## Every release, in short
1. Update `version` and `date-released` in `CITATION.cff`, and add a `## [X.Y.Z]` section to
   `CHANGELOG.md`.
2. Run `python scripts/release_check.py X.Y.Z --write`. Fix every BLOCK item it reports.
3. Commit and push (including the regenerated `.zenodo.json`).
4. Run `python scripts/release_check.py X.Y.Z` until it says **Ready**.
5. Run `gh release create vX.Y.Z --title "SkyShift X.Y.Z" --notes-file cache/release-notes-X.Y.Z.md`
6. Zenodo archives the release and adds a new version DOI under the same concept DOI.

## What the release check enforces
- No `TODO` left in `CITATION.cff` or `AUTHORS.md`; `CITATION.cff` is valid and has the right
  version.
- Tests pass; nothing uncommitted or unpushed; the tag doesn't exist yet.
- The repository is public (Zenodo cannot see private repositories), and Zenodo is switched on
  for it (its webhook exists; a release made before that gets no DOI).
- `CHANGELOG.md` has notes for the version; `.zenodo.json` matches `CITATION.cff`.
- Warnings, which don't block: no ORCID for an author, and a release date that isn't today.

## ASCL (later)
ASCL only registers code used in research that is published, submitted for peer review, or part
of an accepted thesis. Submit at https://ascl.net/code/submit once the first paper is submitted,
using `docs/outreach/ascl-entry.md`.
