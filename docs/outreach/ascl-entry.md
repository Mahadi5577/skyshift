# ASCL submission draft

Submit at https://ascl.net/code/submit **after** the first paper using SkyShift is submitted for
peer review (an ASCL requirement). Fill in the TODOs first.

- **Code name:** SkyShift
- **Title:** SkyShift: Time-zoom exploration of SPHEREx spectral images for moving and variable
  sources
- **Credit (authors):** Amin, MD. Nurol
- **Abstract:**
  SkyShift finds and displays wavelength-matched exposures from the SPHEREx all-sky near-infrared
  survey at four time scales (hours, days, months and a year), so changes and motion between
  epochs are easy to see. It works out the wavelength each linear-variable-filter image samples at
  a target directly from archive footprints, without downloading image headers. It reads only the
  needed pixels from the public cloud archive, reprojects them onto a common grid, and labels known
  Solar System objects with IMCCE SkyBoT. A web interface provides blink, slider and difference
  views. A citizen-science mode calibrates users with injected synthetic movers before collecting
  skill-weighted candidate flags from real data. The package includes the experiment scripts used
  to measure data-access performance, time-sampling coverage and injection-recovery detection
  limits.
- **Site list:** https://github.com/Mahadi5577/skyshift ; Zenodo DOI _TODO_
- **Keywords:** SPHEREx; time-domain; solar system; asteroids; visualization; citizen science
- **Paper(s) using the code:** _TODO: the submitted paper's citation or arXiv ID_
