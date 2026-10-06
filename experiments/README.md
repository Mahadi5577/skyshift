# SkyShift experiments

Standalone Python experiments with NASA SPHEREx data. They are the evidence behind SkyShift's
design: data access speed, the wavelength trap, time-zoom coverage, asteroid and Pluto motion,
and planted-fake detection limits. Every number we rely on is logged in [FINDINGS.md](FINDINGS.md).

These scripts have their own environment (`setup.bat` / `setup.sh`) and do not depend on the app
in the parent folder. GUIDE.md was written as a team guide and still mentions NASA Space Apps
plans from October 2026.

## Start here

| Read | For |
|---|---|
| **[GUIDE.md](GUIDE.md)** | What the project is, SPHEREx basics, setup, how to use each experiment, troubleshooting |
| **[FINDINGS.md](FINDINGS.md)** | Everything we have measured so far, plus open questions. Add yours |

## Quick start

Needs Python 3.11-3.13 (3.12 tested).

```bash
# Windows: double-click setup.bat, then
.venv\Scripts\python 01_epochs.py M51
.venv\Scripts\python 02_stamps.py M51
.venv\Scripts\python 03_blink.py M51

# macOS / Linux
bash setup.sh
source .venv/bin/activate
python 01_epochs.py M51 && python 02_stamps.py M51 && python 03_blink.py M51
```

Run `01_epochs.py M51` and `02_stamps.py M51` first (the repository ships no data), then
`03_blink.py M51`. Results land in `data/M51/`.

## Files

| File | What |
|---|---|
| `00_check.py` | Checks packages and online services |
| `01_epochs.py` | When and at which wavelengths SPHEREx looked at a spot |
| `02_stamps.py` | Downloads small wavelength-matched images |
| `03_blink.py` | Flipbook GIFs, difference image, contrast comparison |
| `04_asteroid.py` | Catches a known asteroid moving (uses NASA JPL Horizons) |
| `05_aladin.html` | Aladin Lite sky-viewer test page (open in a browser) |
| `06_speed.py` | Predicts speed next to the data, measured from your own network |
| `07_inject.py` | Plants fake movers in real frames; measures detection vs brightness |
| `spx.py` | Shared helpers |
| `data/` | Included M51 sample data and outputs; the asteroid run outputs |
| `docs/img/` | Images used in GUIDE.md |
