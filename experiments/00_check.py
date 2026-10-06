"""Experiment 0: can this machine run the sandbox? Checks packages and every remote service used.

    python 00_check.py
"""
import sys
import time

failures = 0
state = {}


def check(name, fn):
    global failures
    t0 = time.time()
    try:
        detail = fn()
        print(f"  OK    {name:28s} {time.time() - t0:5.1f}s  {detail or ''}", flush=True)
    except Exception as e:
        failures += 1
        print(f"  FAIL  {name:28s} {type(e).__name__}: {str(e)[:150]}", flush=True)


def packages():
    import astropy, astroquery, fsspec, matplotlib, numpy, pyvo, reproject, requests, s3fs  # noqa: F401
    return f"astropy {astropy.__version__}, numpy {numpy.__version__}"


def sia():
    import spx
    rows = spx.query_images(202.4696, 47.1952)
    state["key"] = spx.s3_key(rows[0])
    return f"{len(rows)} SPHEREx images at M51"


def header():
    import spx
    return f"EXTNAME={spx.image_header(state['key'])['EXTNAME']}"


def s3_stamp():
    import spx
    img, _, _, _ = spx.read_stamp(state["key"], 202.4696, 47.1952, half=4)
    return f"{img.shape[0]}x{img.shape[1]} px stamp"


def resolver():
    from astropy.coordinates import SkyCoord
    c = SkyCoord.from_name("M51")
    return f"M51 -> {c.ra.deg:.3f}, {c.dec.deg:.3f}"


def horizons():
    from astroquery.jplhorizons import Horizons
    eph = Horizons(id="10", id_type="smallbody", location="500", epochs=2461000.5).ephemerides()
    return f"{eph['targetname'][0]} V={float(eph['V'][0]):.1f}"


print(f"Python {sys.version.split()[0]}")
if sys.version_info < (3, 11):
    print("  WARN  Python 3.11 or newer is needed (3.12 tested)")
check("packages installed", packages)
if failures:
    sys.exit("Install packages first: see GUIDE.md, section 4 (Setup).")
check("IRSA image search (SIA)", sia)
if "key" in state:
    check("S3 header read (32 KB)", header)
    check("S3 stamp read", s3_stamp)
check("name resolver (CDS Sesame)", resolver)
check("JPL Horizons", horizons)
print("\nAll good. Next: python 01_epochs.py M51, then 02_stamps.py M51, then 03_blink.py M51."
      if not failures else f"\n{failures} check(s) failed: see GUIDE.md, section 8 (Troubleshooting).")
sys.exit(1 if failures else 0)
