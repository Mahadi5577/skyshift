# Changelog

Format: one section per release, newest first. `scripts/release_check.py` copies the section for
the version being released into cache/release-notes-X.Y.Z.md for the optional GitHub release.

## [0.2.0] - 2026-10-06

Ready for public use: an online showcase, and a server that can run as a public website.
Zenodo: https://doi.org/10.5281/zenodo.23193726 (concept DOI 10.5281/zenodo.23181747).

### Public server
- **Docker image** (`Dockerfile`) and `docs/DEPLOY.md`: Hugging Face Space (deployed by a manual
  GitHub Actions workflow), any Docker host, or plain Python. Settings come from environment
  variables (`backend/config.py`); `run.bat`/`run.sh` honour `PORT` and `SKYSHIFT_HOST`.
- **Limits:** per-visitor rate limits (archive-heavy requests 30/min by default, the rest
  20 times more), at most 6 views downloading at once ("busy" answers that the page retries by
  itself), at most 4 archive searches and 2 SkyBoT lookups at once, and bounded in-memory caches.
- **Cache size limit:** least-recently-used downloads are pruned above 2 GB; tour stops and
  precached Hunt patches are pinned.
- **`/api/health`**, and an optional **precache at start-up** (`SKYSHIFT_PRECACHE=1`, on in the
  image).

### Hunt
- **Fakes are planted by the server.** A round no longer sends the fake's position or the
  sequence id; frames come from `/api/hunt/round/{id}/frame/{i}`, and the track is revealed
  only after answering.
- **Player names** belong to the browser that first used them (a random key kept in the browser).
- **Hunt data survives restarts:** players, rounds and flags live in SQLite under
  `SKYSHIFT_DATA` (`./data`), apart from the deletable cache. Flags store their sky position, so
  the board no longer depends on cached sequences. Optional backup to a private Hugging Face
  dataset for hosts that wipe their disk.

### Online showcase
- **https://mahadi5577.github.io/skyshift/**: a static copy on GitHub Pages (free, no server) with
  the tour stops at every zoom and Hunt practice rounds. Built by `scripts/export_static.py` and
  published by `.github/workflows/pages.yml`. (Hugging Face Docker Spaces turned out to need a paid
  PRO subscription.)

### Explore
- The sky map shows the **SPHEREx QR2 all-sky colour map** (CDS HiPS) by default, with 2MASS as
  an option.

### Fixes
- Sequences that are not in memory are loaded by their id. Before, they were rebuilt from
  their stored parameters, which for some caches produced a different id, a duplicate download
  and, on Windows, failed parallel requests.

## [0.1.0] - 2026-10-06

First public release. Zenodo: https://doi.org/10.5281/zenodo.23181748 (concept DOI 10.5281/zenodo.23181747).

### Web app
- **Explore:** search by name or RA/Dec, a guided tour (asteroid Hygiea, Pluto, the ecliptic,
  M51, the Orion Nebula), and an Aladin Lite sky map.
- **Time zoom:** hours, days, months (survey-pass medians) and a year, using wavelength-matched
  SPHEREx Quick Release 2 frames.
- **Views:** blink, slider and difference (with a noise dead zone and dimmed bright cores),
  asinh stretch, per-frame brightness balancing.
- **Known objects:** IMCCE SkyBoT asteroids and comets, labelled per frame.
- **Hunt Planet X:** practice rounds with planted movers whose brightness levels come from
  injection-recovery tests, real rounds, skill-weighted candidate board.
- **Sharing:** shareable links (`#t=ra,dec&z=zoom`, `#s=stop`).

### Data pipeline
- One SIA query per position. The wavelength at the target comes from archive footprints
  (max error 0.2%).
- Byte-range reads of the IMAGE and FLAGS layers from the public AWS bucket, 8 in parallel,
  with retries and connection reuse.
- Bad pixels are filled before reprojection onto a common north-up grid. Everything is cached
  on disk, and `scripts/precache.py` prepares demos.

### Experiments
- `experiments/00-07` with `FINDINGS.md`: data-access speed, wavelength trap, time-zoom
  coverage (M51 and the ecliptic), Hygiea (hours) and Pluto (days) motion, injection-recovery
  limits.
