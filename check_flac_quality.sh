#!/usr/bin/env python3
"""
check_flac_quality – scan a FLAC library and detect probable lossy
sources (MP3 / AAC) re-encoded as FLAC, using spectral analysis.

Method
------
For each .flac file:
  1. ffprobe verifies the stream is really FLAC and reads sample rate.
  2. ffmpeg applies a high-pass filter at 16 kHz and runs volumedetect
     to measure the peak sample (dBFS) in the high band.
  3. Genuine lossless 44.1 kHz audio has measurable energy above
     16 kHz (peak typically > -45 dBFS for music with cymbals/sibilance,
     down to ~ -50 dBFS for very quiet/ambient material). Lossy codecs
     low-pass below their bandwidth limit, so the peak above 16 kHz is
     essentially silence (well below -65 dBFS).

Verdicts
--------
  LOSSLESS         peak >= -35 dBFS
  PROBABLY-LOSSY   peak <= -65 dBFS
  UNCERTAIN        in between (review manually)
  NOT-FLAC         codec is not flac
  UNKNOWN          ffprobe / ffmpeg failed

Note: the .sh extension is historical; this is a Python 3 script.
Run with:  python3 check_flac_quality.sh <root-dir> [output-file]

Dependencies: ffmpeg, ffprobe.  No third-party Python packages.
"""

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HIGHPASS_HZ = 16000
LOSSY_DB = -65.0
LOSSLESS_DB = -35.0

MAX_VOL_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_fields(path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0",
           "-show_entries", "stream=codec_name,sample_rate",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    out = run(cmd).stdout.splitlines()
    codec = out[0].strip() if len(out) > 0 else ""
    try:
        sr = int(out[1].strip()) if len(out) > 1 else 0
    except ValueError:
        sr = 0
    return codec or None, sr or None


def measure_high_band_peak(path, cutoff_hz):
    cmd = ["ffmpeg", "-nostdin", "-i", str(path),
           "-af", f"highpass=f={cutoff_hz},volumedetect",
           "-f", "null", "-"]
    res = run(cmd)
    m = MAX_VOL_RE.search(res.stderr)
    if not m:
        return None
    return float(m.group(1))


def classify(path):
    codec, sr = ffprobe_fields(path)
    if codec is None:
        return "UNKNOWN", path, "ffprobe failed"
    if codec != "flac":
        return "NOT-FLAC", path, f"codec={codec}"
    if not sr:
        return "UNKNOWN", path, "no sample rate"

    cutoff = HIGHPASS_HZ
    if sr < 2 * HIGHPASS_HZ:  # paranoia: low-rate file
        cutoff = max(sr // 4, 4000)

    peak = measure_high_band_peak(path, cutoff)
    if peak is None:
        return "UNKNOWN", path, "ffmpeg/volumedetect failed"

    info = f"peak>{cutoff}Hz={peak:+.1f}dB sr={sr}"
    if peak <= LOSSY_DB:
        return "PROBABLY-LOSSY", path, info
    if peak >= LOSSLESS_DB:
        return "LOSSLESS", path, info
    return "UNCERTAIN", path, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="library root (e.g. /data/music)")
    ap.add_argument("output", nargs="?", type=Path,
                    default=Path("flac_report.txt"))
    ap.add_argument("--workers", type=int,
                    default=max(2, (os.cpu_count() or 4) // 2),
                    help="parallel ffmpeg processes (default: cpu/2)")
    args = ap.parse_args()

    if not args.root.is_dir():
        sys.exit(f"Error: '{args.root}' is not a directory.")

    files = sorted(args.root.rglob("*.flac"))
    n = len(files)
    if n == 0:
        sys.exit(f"No .flac files found under {args.root}")

    print(f"Scanning {n} FLAC files with {args.workers} workers...",
          file=sys.stderr)

    counts = {"LOSSLESS": 0, "PROBABLY-LOSSY": 0, "UNCERTAIN": 0,
              "NOT-FLAC": 0, "UNKNOWN": 0}
    started = time.time()
    lines = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (verdict, path, info) in enumerate(
                ex.map(classify, files), start=1):
            counts[verdict] = counts.get(verdict, 0) + 1
            lines.append(f"{verdict:<15} {path}   ({info})")
            if i % 50 == 0 or i == n:
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (n - i) / rate if rate else 0
                print(f"  [{i}/{n}] {elapsed:.0f}s elapsed, "
                      f"{rate:.1f} files/s, ETA {eta:.0f}s",
                      file=sys.stderr)

    with args.output.open("w", encoding="utf-8") as out:
        out.write(f"FLAC-QUALITY-SCAN  root: {args.root}\n")
        out.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"Method: highpass {HIGHPASS_HZ} Hz + volumedetect; "
                  f"lossy<={LOSSY_DB} dB, lossless>={LOSSLESS_DB} dB\n\n")
        for line in lines:
            out.write(line + "\n")
        out.write("\n--- SUMMARY ---\n")
        for k in ("LOSSLESS", "PROBABLY-LOSSY", "UNCERTAIN",
                  "NOT-FLAC", "UNKNOWN"):
            out.write(f"  {k:<15}: {counts.get(k, 0)}\n")
        out.write(f"  {'TOTAL':<15}: {n}\n")

    print(f"Report saved as: {args.output}", file=sys.stderr)
    print("Summary:", file=sys.stderr)
    for k in ("LOSSLESS", "PROBABLY-LOSSY", "UNCERTAIN",
              "NOT-FLAC", "UNKNOWN"):
        print(f"  {k:<15}: {counts.get(k, 0)}", file=sys.stderr)


if __name__ == "__main__":
    main()
