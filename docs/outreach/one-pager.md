# SkyShift: zoom through time in NASA SPHEREx sky images

**Author:** MD. Nurol Amin, Daffodil International University (ORCID [0009-0005-8289-7804](https://orcid.org/0009-0005-8289-7804)) · **Contact:** amin15-5577@diu.edu.bd · **Code:** https://github.com/Mahadi5577/skyshift (DOI: [10.5281/zenodo.23181747](https://doi.org/10.5281/zenodo.23181747)) · **Demo video:** _TODO link_

## The opportunity
Since May 2025, NASA's SPHEREx has imaged the whole sky every six months in 102 near-infrared
bands (0.75-5 um). Each position is revisited minutes, hours, days and months apart, so the
archive is also a time-domain survey for moving Solar System objects. Two things make it hard to
use for this:
- **Colour varies across each frame.** Each detector sits behind a linear variable filter, so
  consecutive images of a spot are taken at different wavelengths, and brightness changes can
  mimic real changes.
- **The data is far away.** On our test connection (~240 ms round trip to the US archive), a single IRSA cutout takes
  about 37 s.

## What we built
SkyShift, an open-source web tool and analysis toolkit:
- Selects **wavelength-matched** exposures of any sky position at four time scales (hours,
  days, months, a year).
- Computes the wavelength at the target from archive footprints alone: **max error 0.2%**
  against full WCS-WAVE header solutions, with zero per-image downloads.
- Reads only the needed pixels from the public AWS bucket: about 2.6 s per frame on our
  test connection, about 0.4 s modelled in-region.
- Shows blink, slider and difference views, with known asteroids labelled through IMCCE SkyBoT.
- Includes a citizen-science mode that trains users on **planted synthetic movers** before
  they flag real candidates. Votes are weighted by each user's measured skill.

## Evidence so far (SPHEREx Quick Release 2)
- **Coverage:** matching-wavelength image pairs exist from 2 minutes to over 8 months apart,
  both at high latitude (M51) and on the ecliptic.
- **Hours:** (10) Hygiea moves 32″ (5 px) in 1.6 h, on the predicted track.
- **Days:** Pluto (~35 AU) appears in 201 frames and drifts ~3 px/day over three weeks.
- **Injection-recovery:** a moving point source is recovered 99.5% of the time at peak S/N 12,
  89% at S/N 8 and 13% at S/N 5 (ecliptic field, 4.5 um).

## Where we want to go
1. **A completeness study:** how well can SPHEREx detect moving Solar System bodies, as a function
   of brightness, rate, wavelength and position? Run large-scale injection-recovery and validate on
   known asteroids. Target: AJ or PASP.
2. **A public citizen-science search** (e.g. on Zooniverse), reporting candidates to the Minor
   Planet Center.

## What we're asking for
Scientific mentorship and, if it is a good fit, co-authorship. We especially need guidance on
photometric calibration to magnitudes, the statistics of completeness estimates, and how best
to work alongside the SPHEREx team's own Solar System efforts.

_Disclosure: the software was developed with generative-AI assistance (details in AI_USE.md)._
