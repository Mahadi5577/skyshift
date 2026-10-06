"""Experiment 6: how fast would SkyShift be on a server next to the data, measured from here?

We can't rent a US server, but we can split today's delays into parts that depend on distance
(network round trip, bandwidth) and parts that don't (S3's own processing time, number of
requests, bytes). Swap in in-region values for the distance-dependent parts to predict the
speed in AWS us-east-1.

    python 06_speed.py
"""
import logging
import re
import socket
import ssl
import statistics as st
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from astropy.table import Table

import spx

HOST = f"{spx.S3_BUCKET}.s3.us-east-1.amazonaws.com"
# In-region assumptions (AWS: same-region round trip ~1-2 ms; one S3 stream ~50-100 MB/s).
US_RTT, US_BW = 0.002, 50e6

idx = Table.read(spx.DATA / "M51" / "index.csv")
keys = list(idx["key"])
key = keys[0]

# --- 1. Network basics -------------------------------------------------------------------
ip = socket.gethostbyname(HOST)
rtts = []
for _ in range(5):
    t0 = time.perf_counter()
    socket.create_connection((ip, 443), timeout=10).close()  # TCP handshake = one round trip
    rtts.append(time.perf_counter() - t0)
rtt = st.median(rtts)

s = requests.Session()
s.get(spx.S3_HTTP + key, headers={"Range": "bytes=0-0"}, timeout=60)  # warm the connection
ttfb = st.median(
    s.get(spx.S3_HTTP + key, headers={"Range": "bytes=0-0"}, timeout=60).elapsed.total_seconds()
    for _ in range(5))
s3_latency = max(ttfb - rtt, 0.005)  # S3's own time per request, the same anywhere

t0 = time.perf_counter()
n = len(s.get(spx.S3_HTTP + key, headers={"Range": "bytes=0-3999999"}, timeout=120).content)
bw = n / max(time.perf_counter() - t0 - ttfb, 1e-3)

print(f"Round trip to S3 us-east-1  {rtt * 1000:6.0f} ms   (in-region: ~{US_RTT * 1000:.0f} ms)")
print(f"S3 processing per request   {s3_latency * 1000:6.0f} ms   (same anywhere)")
print(f"Bandwidth, one stream       {bw / 1e6:6.2f} MB/s (in-region: ~{US_BW / 1e6:.0f} MB/s)")

# --- 2. What one stamp read costs ---------------------------------------------------------
calls, fetched = [], []


class Count(logging.Handler):
    def emit(self, rec):
        msg = rec.getMessage()
        if msg.startswith("CALL:"):
            calls.append(msg.split()[1])
        m = re.search(r"Fetch: .*, (\d+)-(\d+)", msg)
        if m:
            fetched.append(int(m[2]) - int(m[1]))


log = logging.getLogger("s3fs")
log.setLevel(logging.DEBUG)
log.addHandler(Count())
spx.read_stamp(keys[1], 202.4696, 47.1952, half=16)  # warm-up: first use sets up the S3 client
calls.clear(), fetched.clear()
t0 = time.perf_counter()
spx.read_stamp(key, 202.4696, 47.1952, half=16)
stamp_here = time.perf_counter() - t0
log.setLevel(logging.WARNING)
n_calls, n_bytes = len(calls), sum(fetched)


def model(rtt_, bw_):
    return n_calls * (rtt_ + s3_latency) + n_bytes / bw_


print(f"\nOne 32x32 stamp: {n_calls} S3 requests ({', '.join(sorted(set(calls)))}), "
      f"{n_bytes / 1e6:.2f} MB fetched")
print(f"  measured here         {stamp_here:6.2f} s")
print(f"  model here            {model(rtt, bw):6.2f} s   (sanity check: should be close)")
print(f"  model in us-east-1    {model(US_RTT, US_BW):6.2f} s")

# --- 3. Does running requests in parallel hide the distance? -------------------------------
sample = keys[2:26]
print(f"\nHeader reads (32 KB each) for {len(sample)} images:")
for workers in (1, 8, 24):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(spx.image_header, sample))
    dt = time.perf_counter() - t0
    print(f"  {workers:2d} parallel  {dt:6.1f} s total  {dt / len(sample):5.2f} s per image")

# --- 4. What it means for SkyShift ---------------------------------------------------------
frames = 30
print(f"\nA {frames}-frame flipbook (one stamp per frame, 8 in parallel):")
print(f"  from here        ~{frames / 8 * stamp_here:5.1f} s")
print(f"  from us-east-1   ~{frames / 8 * model(US_RTT, US_BW):5.1f} s")
print(f"  from a cache     ~0.1-0.5 s (pre-rendered PNGs on any static host or CDN)")
