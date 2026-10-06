# Changelog

Format: one section per release, newest first. `scripts/release_check.py` copies the section for
the version being released into cache/release-notes-X.Y.Z.md for the optional GitHub release.

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
