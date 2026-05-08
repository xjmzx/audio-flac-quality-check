# audio-flac-quality-check

Scan a FLAC library and flag files whose audio looks like a lossy source
(MP3, AAC) re-encoded as FLAC. Pure spectral analysis via `ffmpeg`; no
third-party Python packages.

Two scripts:

| File | What it does |
| --- | --- |
| `check_flac_quality.sh` | CLI scanner. Walks a tree of `.flac` files, classifies each, writes a plain-text report. (Despite the `.sh` name, this is Python 3.) |
| `flac_library_browser.py` | Tk GUI. Reads the report, shows artist → album → track with verdict / peak-above-16-kHz / sample-rate columns, and a Re-scan button. |

## How it decides

For each file the scanner runs `ffmpeg` with a `highpass=f=16000,volumedetect`
filter and reads the **peak sample (dBFS)** above 16 kHz.

- Genuine lossless 44.1 kHz audio retains measurable energy above 16 kHz —
  cymbals, sibilance, ambient air. Peak typically lands between **−45 and
  −10 dBFS** for music with high-frequency content.
- Lossy codecs low-pass below their bandwidth limit (≈16 kHz at 128 kbps
  MP3, ≈19 kHz at 256 kbps AAC), so the high band is essentially silence —
  peak well **below −65 dBFS**.

| Verdict | Peak above 16 kHz |
| --- | --- |
| `LOSSLESS` | ≥ −35 dB |
| `UNCERTAIN` | between (review manually — quiet/ambient genuine lossless can land here) |
| `PROBABLY-LOSSY` | ≤ −65 dB |
| `NOT-FLAC` | codec is not flac |
| `UNKNOWN` | ffprobe / ffmpeg failed |

The method does **not** rely on file size or compression ratio — those
cannot distinguish real lossless from a lossy source re-encoded as FLAC.

## Install dependencies (Debian / Ubuntu)

```sh
sudo apt update
sudo apt install python3 python3-tk ffmpeg
```

`ffmpeg` provides both `ffmpeg` and `ffprobe`. `python3-tk` is required
only for the GUI (`flac_library_browser.py`); the CLI scanner runs without
it.

On other distros, install the equivalents (`pacman -S python tk ffmpeg`,
`dnf install python3 python3-tkinter ffmpeg`, etc.).

## Quick start (no install)

```sh
git clone https://github.com/xjmzx/audio-flac-quality-check.git
cd audio-flac-quality-check

# CLI: scan a directory and write the report
python3 check_flac_quality.sh /path/to/music flac_report.txt

# GUI: browse the report
python3 flac_library_browser.py
```

The GUI reads `flac_report.txt` from its own directory, and its **Re-scan**
button re-runs the CLI in a worker thread.

## Build / install / deploy

The repo ships a `Makefile` that places the scripts under `PREFIX/bin`,
the icon under `PREFIX/share/icons/hicolor/scalable/apps`, and a
`.desktop` entry under `PREFIX/share/applications` (so the app appears in
GNOME / KDE / XFCE app menus).

```sh
# user-level install (no sudo) — default PREFIX is $HOME/.local
make install

# system-wide
sudo make install PREFIX=/usr/local

# remove
make uninstall                     # or: sudo make uninstall PREFIX=/usr/local
```

After `make install`, "FLAC Library Browser" appears in *Show
Applications*. The desktop entry is generated from
`audio-flac-quality-check.desktop.in` with the install paths substituted
in, so it works regardless of `PREFIX`.

Other handy targets:

```sh
make help              # list everything
make run               # launch the GUI in place (no install)
make scan ROOT=/music  # run the scanner on ROOT (default /data/music)
make check             # py_compile + desktop-file-validate
```

## CLI usage

```
python3 check_flac_quality.sh <root-dir> [output-file] [--workers N]
```

- `<root-dir>` — top of the FLAC tree (e.g. `/data/music`).
- `[output-file]` — where the report goes (default `flac_report.txt`).
- `--workers N` — parallel `ffmpeg` processes (default `cpu/2`).

Progress lines stream to stderr; the report is written when the scan
finishes. A tail-end summary block reports counts per verdict.

## GUI

Loads the report in the same directory and shows a hierarchical tree:

```
ARTIST                       3 albums · 28 tracks    27 lossless  1 uncertain
  ALBUM (2008)                          12 tracks    12 lossless
    01 Track.flac      LOSSLESS   −12.4 dB   44,100 Hz
    …
```

Verdict cells are colour-coded (green / yellow / red / muted). Use the
filter dropdown (or set Ctrl+F + the search box) to narrow the view, e.g.
filter to `PROBABLY-LOSSY` to jump straight to the suspect tracks. **Esc**
clears filter + search. **Ctrl+R** re-runs the scan. Double-clicking a
track row opens its containing folder via `xdg-open`.

## Caveats

Spectral cutoff is a heuristic; pure drone / sub-bass / silent ambient
tracks have no high-frequency content even when fully lossless and will
show up as `PROBABLY-LOSSY`. Verify suspect tracks by listening, by
checking metadata (encoder, source bitrate), or with a spectrum
visualiser like Spek.
