# Findings log

What the team has learned about SPHEREx data, with numbers. This is the one thing we carry
into the hackathon. The sandbox code stays behind.

**Adding a finding:** append under the right heading as
`- (YYYY-MM-DD, your name) what you did -> what you saw, with numbers`.
Record failures too: "X does not work because Y" saves the team hours at the event.

## 2026-10-05: first exploration session (measured on a home connection ~240 ms from the US servers)
### Data access
- **Collection:** `spherex_qr2` has the data (413 images at M51). `spherex_qr3` returned 0 rows at
  M51; re-check closer to the event. QR1 is superseded.
- **astroquery is slow for search:** `Irsa.query_sia` took ~33 s; the same SIA query over plain HTTP
  takes ~1.5 s. In astroquery 0.4.11 `query_sia` already returns a `Table` (no `.to_table()`).
- **VOTable parsing:** pass `use_names_over_ids=True`, or columns come back as `col_48`, etc.
- **Bandwidth (test connection):** Cloudflare 2.9 MB/s, S3 us-east-1 0.89 MB/s, IRSA 0.24 MB/s.
  The data servers are the bottleneck, not the home line.
- **IRSA cutout service:** ~37 s and 5 MB per cutout, because every cutout carries the full
  101x101x121 PSF cube. The image itself is only 29x29 px.
- **S3 partial reads win:** `fits.open(s3://nasa-irsa-spherex/..., use_fsspec=True)` with
  `default_block_size=256 KB` reads IMAGE + FLAGS + ZODI + WCS-WAVE sections in ~6 s.
  With the default block size, just opening the file took 106 s.
- **For the app:** host the backend in AWS us-east-1 next to the bucket, and cache aggressively.

### Wavelength (the filter trap)
- `em_min` / `em_max` in search results give the **whole detector's** range, not the wavelength at
  your target.
- The wavelength at a pixel comes from the `WCS-WAVE` lookup table: a 9 x 14 grid with a break at
  y = 140/141. Load it with `WCS(header, fobj=hdul, key="W")` and set `sip = None`.
- **The table is identical for every exposure of a detector** (checked D3 and D5, a year apart).
  So one 32 KB header range request plus a cached table gives the wavelength at the target.
  That's ~1.5 s per image; 413 images took 1 min 48 s on 8 threads.
- Within one pass, the wavelength at a fixed target climbs day by day as the field slides along
  the filter (see `data/M51/epochs.png`).

### Time-zoom feasibility (M51)
- 3 survey passes: 2025-05-05 to 05-26, 2025-12-03 to 12-19, 2026-05-15 to 06-19.
- Image pairs whose wavelengths match within 2%, by time gap:

  | Gap | Pairs |
  |---|---|
  | < 1 h | 157 |
  | 1 h - 1 day | 68 |
  | 1 - 30 days | 388 |
  | 1 - 8 months | 1252 |
  | > 8 months | 544 |

  The shortest gap is 2.1 min. **Every time-zoom level has data at M51.** Still to check: a
  target near the ecliptic and one near the celestial equator.

### Images
- **Roll angle changes each pass:** stamps must be reprojected to a common north-up grid before
  blinking or subtracting. Fetch stamps ~1.42x (sqrt 2) bigger than the displayed area, or the
  corners come out blank.
- **Stretch:** asinh with a 99.5% interval reads best. Min-max hides everything except the core;
  zscale burns out the core. Use one shared normalisation for all frames, so brightness changes
  are real and not caused by re-scaling.
- **False change at bright cores:** the M51 last-minus-first difference leaves a core residual of
  0.4-0.6 MJy/sr against ~0.03 MJy/sr noise. Static bright objects will look like they changed
  unless the PSFs are matched or the cores are masked.
- **FLAGS bits** (from the `MP_*` header keys): mask TRANSIENT, OVERFLOW, SUR_ERROR, PHANTOM,
  NONFUNC, MISSING_DATA, HOT, COLD, NONLINEAR and PERSIST. OUTLIER (bit 19) is deliberately *not*
  masked, because a moving object may be flagged as an outlier. Test this with the asteroid run.

### Asteroid (04): (10) Hygiea
- **255 SPHEREx images contain Hygiea**, in two passes: 2025-09-19 onward and 2026-03-13 to 03-18.
  Finding them took 13 min (425 daily SIA queries with POS + TIME, then header checks).
  An app needs a faster lookup: query only days when the asteroid is near SPHEREx's
  pointing zone, or precompute.
- **The hours time-zoom works:** on 2025-09-30 the asteroid sits exactly on the JPL-predicted
  ring and moves 32" (5.2 px) in 1.6 h, plainly visible in `data/ast_10/asteroid.gif`.
- Exposures come in pairs (D1 + D4, D2 + D5...) about every 2 min, so one visit gives several
  frames at 2 wavelengths at once.
- **Asteroid pixels carry the SOURCE flag** (bit 21, "mapped to a known source"). To check: does the
  pipeline mark known solar-system objects? If so, a moving blob *without* SOURCE is a candidate.
- **The PERSIST flag hit the asteroid** in 1 of 8 frames (bright source, peak 56 MJy/sr at
  1.34 um). Masking PERSIST punches holes in bright movers. For display, mask only the
  hardware-bad bits (NONFUNC, HOT, COLD, MISSING_DATA, OVERFLOW) and fill the holes with a local
  median. White NaN squares in the frames distract non-experts.
- Frame-to-frame wavelength changes make the stars flicker in brightness too. Scaling each frame
  by its own background noise helps, but a matched-wavelength mode is still needed for the
  "is it moving?" judgement.


### Speed without a US server (`06_speed.py`)
- **Breakdown on the test connection:** round trip to S3 us-east-1 241 ms; S3's own processing 42 ms
  per request (the same anywhere); one-stream bandwidth 1.6 MB/s.
- **One 32x32 stamp = 8 S3 requests and 1.84 MB.** FITS stores whole rows, so 32 rows of a
  2040 px layer is 261 KB per layer, whatever the stamp width. Measured 2.6 s here; the model
  predicts **~0.4 s in us-east-1**.
- **30-frame flipbook:** ~10 s from here (8 in parallel), ~1.5 s modelled in us-east-1, under
  0.5 s from pre-rendered files.
- **Reuse connections:** a fresh TLS handshake per request cost ~1 s. A kept-alive session per
  thread cut header reads from 1.51 s to 0.44 s (one at a time) and from 0.30 s to 0.15 s
  (8 in parallel). More than 8 in parallel gave no further gain.
- **Conclusion:** distance costs ~6x, but a cache beats any server location. Pre-render tour
  and featured targets as static files (fast worldwide from any free static host or CDN).
  Live search of arbitrary spots streams frames one by one; the first frame shows in ~2.5 s
  even from here.
- To shave further: for previews, skip the ZODI layer (subtract a median instead) and FLAGS.
  That cuts bytes by about 2/3.

## 2026-10-06: experiments for the app

### Ecliptic coverage (`01_epochs.py "180,0"`)
- 341 images, 3 passes (2025-05-16 to 06-07, 2025-12-19 to 12-28, 2026-05-20 to 06-25).
- Matching-wavelength pairs: < 1 h 114, 1 h - 1 day 29, 1 - 30 days 157, 1 - 8 months 740,
  > 8 months 392. **Every time scale is covered on the ecliptic too**, a bit thinner than at M51.

### Days time-zoom: Pluto (`04_asteroid.py 999 --major --spread --field 10`)
- Horizons treats Pluto as a major body (`id_type=None`); added `--major` and `--spread`.
- **201 SPHEREx images contain Pluto** (V 14.4-14.6). From 2025-09-25 to 10-12 it drifts 300″
  (49 px), about 3 px/day: the slow, distant-mover case behind the Planet X story.
- Clearly visible at 1.19 and 3.56 um, and not visible in a 4.92 um frame.

### Planting fakes (`07_inject.py "180,0"`)
- 22 frames at 4.48 um; per-frame noise ~0.032 MJy/sr; PSF FWHM ~2.1 px (Gaussian sigma ~0.9 px).
- Matched-filter recovery of a moving fake by peak S/N per frame: 2 -> 1.5%, 3 -> 2.1%,
  5 -> 12.6%, **8 -> 89%, 12 -> 99.5%**. Noise alone gives ~4.8 false 5-sigma pixels per frame.
- By eye (`inject_panels.png`): S/N 8-12 is obvious, S/N 5 or lower is hard.
- **Hunt mode levels: S/N 12 -> 8 -> 6 -> 5.**

### Wavelength from search results alone
- The SIA `s_region` polygon lists corners in pixel order (0,0), (2039,0), (2039,2039), (0,2039),
  then repeats the first corner. An affine fit on the tangent plane predicts the target pixel within
  6.5 px (median), 9.6 px max, over 413 images.
- Wavelength error vs header-based: median 0.074%, **max 0.2%**. Coverage now needs one search
  (~5-12 s) and no per-image header reads.
- Interpolating the WCS-WAVE table directly (scipy `RegularGridInterpolator`, grid -1 offset)
  matches astropy's WAVE-TAB result.

### Known objects (IMCCE SkyBoT)
- `Skybot.cone_search` works from here (~10 s first call; astroquery caches after that).
  Hygiea was returned 1.5″ from its predicted position.
- `RA_rate` / `DEC_rate` are arcsec/hour on the sky (RA rate already includes cos Dec): Hygiea
  19.9″/h, matching the 32″ in 1.6 h we measured.
- An empty field raises an error ("No table found"); treat that as "no objects".

### Display
- Fill hidden pixels on the native stamp *before* reprojecting: reprojection marks NaN inputs
  as no coverage, which left 2-3% holes.
- A 2.5-sigma dead zone in difference images keeps noise dark so real changes stand out.

## Open questions
- Does QR3 fill in before November? (`spherex_qr3` returned 0 rows at M51 on 2026-10-05.)
- Is there a SPHEREx HiPS (all-sky tiled map) at IRSA for Aladin Lite? If not, use 2MASS as the
  backdrop and overlay SPHEREx stamps.
- Does Aladin Lite's `displayFITS` accept a local file (blob URL)? Test with `05_aladin.html`.
- How many visits per pass near the ecliptic, where the asteroids are? Try `01_epochs.py "180,0"`.
- Does the SOURCE flag mark known asteroids? Compare an asteroid frame against an empty field.
- How faint an asteroid can we still see? Try `04_asteroid.py` on fainter numbered asteroids.
