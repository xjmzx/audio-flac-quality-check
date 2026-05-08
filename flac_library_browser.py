#!/usr/bin/env python3
"""FLAC library browser — view per-artist / album / track classifications
from check_flac_quality.sh's report. Re-scan from the toolbar."""

import os
import re
import subprocess
import threading
import tkinter as tk
from collections import Counter, defaultdict
from pathlib import Path
from tkinter import ttk

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "check_flac_quality.sh"
REPORT = HERE / "flac_report.txt"
DEFAULT_ROOT = "/data/music"

# Catppuccin Mocha palette (matches bpm_tapper.py)
BG = "#1e1e2e"
PANEL = "#181825"
FG = "#cdd6f4"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
MUTED = "#6c7086"
BTN = "#313244"
BTN_HOVER = "#45475a"

VERDICT_COLOR = {
    "LOSSLESS": GREEN,
    "PROBABLY-LOSSY": RED,
    "UNCERTAIN": YELLOW,
    "NOT-FLAC": MUTED,
    "UNKNOWN": MUTED,
}

LINE_RE = re.compile(
    r"^(LOSSLESS|PROBABLY-LOSSY|UNCERTAIN|NOT-FLAC|UNKNOWN)\s+"
    r"(.+?)\s{2,}\((.+)\)\s*$"
)
PEAK_RE = re.compile(r"peak>\d+Hz=([+-]?\d+(?:\.\d+)?)dB")
SR_RE = re.compile(r"sr=(\d+)")
ROOT_RE = re.compile(r"root:\s*(\S.*)$")


def parse_report(path):
    """Return (rows, library_root) parsed from a report file."""
    if not path.exists():
        return [], None
    rows = []
    root = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("FLAC-QUALITY-SCAN"):
                m = ROOT_RE.search(line)
                if m:
                    root = m.group(1).strip()
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            verdict, fp, info = m.groups()
            mp = PEAK_RE.search(info)
            ms = SR_RE.search(info)
            rows.append({
                "verdict": verdict,
                "path": fp,
                "peak": float(mp.group(1)) if mp else None,
                "sr": int(ms.group(1)) if ms else None,
                "info": info,
            })
    return rows, root


def split_path(fp, root):
    """Split a full track path into (artist, album, track)."""
    if root and fp.startswith(root):
        rel = fp[len(root):].lstrip("/")
    else:
        rel = fp.lstrip("/")
    parts = rel.split("/")
    if len(parts) >= 3:
        return parts[0], "/".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], "(no album)", parts[-1]
    return "(unknown)", "(no album)", parts[-1]


class FlacBrowser:
    def __init__(self, root):
        self.root = root
        root.title("FLAC Library Browser")
        root.geometry("1100x700")
        root.configure(bg=BG)

        self.rows = []
        self.lib_root = DEFAULT_ROOT
        self.scan_thread = None

        self._style_ttk()
        self._build_ui()
        self._bind_keys()
        self.load_report()

    # ---- styling ---------------------------------------------------
    def _style_ttk(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(
            "Treeview",
            background=PANEL, foreground=FG, fieldbackground=PANEL,
            bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL,
            rowheight=22, font=("Helvetica", 10),
        )
        s.configure(
            "Treeview.Heading",
            background=BG, foreground=ACCENT, relief="flat",
            font=("Helvetica", 10, "bold"), borderwidth=0,
        )
        s.map("Treeview",
              background=[("selected", BTN_HOVER)],
              foreground=[("selected", FG)])
        s.map("Treeview.Heading", background=[("active", BG)])
        s.configure(
            "TCombobox",
            fieldbackground=BTN, background=BTN, foreground=FG,
            arrowcolor=ACCENT, bordercolor=BTN, lightcolor=BTN, darkcolor=BTN,
            selectbackground=BTN, selectforeground=FG,
        )
        s.configure(
            "Vertical.TScrollbar",
            background=BTN, troughcolor=PANEL, bordercolor=PANEL,
            arrowcolor=MUTED, lightcolor=BTN, darkcolor=BTN,
        )

    # ---- layout ----------------------------------------------------
    def _build_ui(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 6))

        self.scan_btn = tk.Button(
            top, text="↻  Re-scan", font=("Helvetica", 10, "bold"),
            bg=BTN, fg=FG, activebackground=BTN_HOVER, activeforeground=FG,
            relief="flat", bd=0, padx=14, pady=8, cursor="hand2",
            command=self.start_scan,
        )
        self.scan_btn.pack(side="left")

        tk.Label(top, text="filter", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(side="left", padx=(20, 6))
        self.filter_var = tk.StringVar(value="All")
        self.filter_combo = ttk.Combobox(
            top, textvariable=self.filter_var,
            values=["All", "LOSSLESS", "PROBABLY-LOSSY",
                    "UNCERTAIN", "NOT-FLAC", "UNKNOWN"],
            state="readonly", width=16, font=("Helvetica", 10),
        )
        self.filter_combo.pack(side="left")
        self.filter_combo.bind(
            "<<ComboboxSelected>>", lambda e: self.refresh_tree())

        tk.Label(top, text="search", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(side="left", padx=(20, 6))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            top, textvariable=self.search_var,
            bg=BTN, fg=FG, insertbackground=FG, relief="flat", bd=0,
            font=("Helvetica", 10), width=24,
        )
        self.search_entry.pack(side="left", ipady=6)
        self.search_var.trace_add("write", lambda *a: self.refresh_tree())

        self.summary_label = tk.Label(
            top, text="", bg=BG, fg=MUTED, font=("Helvetica", 10),
        )
        self.summary_label.pack(side="right")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.tree = ttk.Treeview(
            body, columns=("verdict", "peak", "sr"), selectmode="browse",
        )
        self.tree.heading("#0", text="Library")
        self.tree.heading("verdict", text="Verdict")
        self.tree.heading("peak", text="Peak above 16 kHz")
        self.tree.heading("sr", text="Sample rate")
        self.tree.column("#0", width=620, stretch=True)
        self.tree.column("verdict", width=220, anchor="w")
        self.tree.column("peak", width=120, anchor="e")
        self.tree.column("sr", width=110, anchor="e")

        for v, color in VERDICT_COLOR.items():
            self.tree.tag_configure(v, foreground=color)
        self.tree.tag_configure(
            "artist", font=("Helvetica", 11, "bold"), foreground=ACCENT)
        self.tree.tag_configure(
            "album", font=("Helvetica", 10, "italic"), foreground=FG)

        ysb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._open_selected)

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        self.status_label = tk.Label(
            bottom, text="", bg=BG, fg=MUTED,
            font=("Helvetica", 9), anchor="w",
        )
        self.status_label.pack(fill="x")

    def _bind_keys(self):
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.root.bind("<Control-r>", lambda e: self.start_scan())
        self.root.bind("<Escape>", lambda e: (
            self.search_var.set(""), self.filter_var.set("All"),
            self.refresh_tree()))

    # ---- data loading ----------------------------------------------
    def load_report(self):
        rows, root = parse_report(REPORT)
        if root:
            self.lib_root = root
        self.rows = rows
        self._update_summary()
        self.refresh_tree()
        if rows:
            self.status_label.config(
                text=f"loaded {len(rows):,} entries from {REPORT}",
                fg=MUTED)
        else:
            self.status_label.config(
                text=f"no report at {REPORT} — click Re-scan", fg=YELLOW)

    def _update_summary(self):
        c = Counter(r["verdict"] for r in self.rows)
        total = len(self.rows)
        if not total:
            self.summary_label.config(text="")
            return
        bits = [f"{total:,} tracks"]
        for v in ("LOSSLESS", "PROBABLY-LOSSY", "UNCERTAIN",
                  "NOT-FLAC", "UNKNOWN"):
            if c[v]:
                bits.append(f"{c[v]:,} {v.lower()}")
        self.summary_label.config(text="   ·   ".join(bits))

    # ---- filtering / tree --------------------------------------------
    def _matches_filter(self, row):
        f = self.filter_var.get()
        if f != "All" and row["verdict"] != f:
            return False
        q = self.search_var.get().strip().lower()
        if q and q not in row["path"].lower():
            return False
        return True

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        rows = [r for r in self.rows if self._matches_filter(r)]

        groups = defaultdict(lambda: defaultdict(list))
        for r in rows:
            artist, album, track = split_path(r["path"], self.lib_root)
            r["_artist"], r["_album"], r["_track"] = artist, album, track
            groups[artist][album].append(r)

        any_filter = (self.filter_var.get() != "All"
                      or bool(self.search_var.get().strip()))

        for artist in sorted(groups, key=str.lower):
            albums = groups[artist]
            artist_total = sum(len(t) for t in albums.values())
            artist_counts = Counter()
            for tracks in albums.values():
                for r in tracks:
                    artist_counts[r["verdict"]] += 1
            artist_id = self.tree.insert(
                "", "end",
                text=artist,
                values=(self._fmt_counts(artist_counts, artist_total,
                                          n_albums=len(albums)), "", ""),
                tags=("artist",),
                open=any_filter,
            )
            for album in sorted(albums, key=str.lower):
                tracks = sorted(albums[album],
                                key=lambda r: r["_track"].lower())
                ac = Counter(r["verdict"] for r in tracks)
                album_id = self.tree.insert(
                    artist_id, "end",
                    text=album,
                    values=(self._fmt_counts(ac, len(tracks)), "", ""),
                    tags=("album",),
                    open=any_filter,
                )
                for r in tracks:
                    peak = (f"{r['peak']:+.1f} dB"
                            if r["peak"] is not None else "")
                    sr = f"{r['sr']:,} Hz" if r["sr"] else ""
                    self.tree.insert(
                        album_id, "end",
                        text=r["_track"],
                        values=(r["verdict"], peak, sr),
                        tags=(r["verdict"],),
                    )

    def _fmt_counts(self, counts, total, n_albums=None):
        order = ["LOSSLESS", "UNCERTAIN", "PROBABLY-LOSSY",
                 "NOT-FLAC", "UNKNOWN"]
        present = [(v, counts[v]) for v in order if counts[v]]
        breakdown = "  ".join(
            f"{n} {v.split('-')[0].lower()}" for v, n in present)
        prefix = (f"{n_albums} albums · {total} tracks"
                  if n_albums is not None else f"{total} tracks")
        return f"{prefix}    {breakdown}".rstrip()

    def _open_selected(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0], "tags")
        if "artist" in tags or "album" in tags:
            self.tree.item(
                sel[0], open=not self.tree.item(sel[0], "open"))
            return
        # leaf row → reveal containing folder in file manager (best-effort)
        idx = self.tree.index(sel[0])
        # Reconstruct path from artist/album/track text fields
        album_id = self.tree.parent(sel[0])
        artist_id = self.tree.parent(album_id)
        track = self.tree.item(sel[0], "text")
        album = self.tree.item(album_id, "text")
        artist = self.tree.item(artist_id, "text")
        full = Path(self.lib_root) / artist / album / track
        folder = full.parent
        try:
            subprocess.Popen(["xdg-open", str(folder)])
            self.status_label.config(
                text=f"opened {folder}", fg=MUTED)
        except FileNotFoundError:
            self.status_label.config(
                text=f"track: {full}", fg=MUTED)

    # ---- re-scan ---------------------------------------------------
    def start_scan(self):
        if self.scan_thread and self.scan_thread.is_alive():
            return
        if not SCRIPT.exists():
            self.status_label.config(
                text=f"scan script missing: {SCRIPT}", fg=RED)
            return
        self.scan_btn.config(state="disabled", text="scanning…")
        self.status_label.config(text="starting scan…", fg=YELLOW)
        self.scan_thread = threading.Thread(target=self._scan, daemon=True)
        self.scan_thread.start()

    def _scan(self):
        cmd = ["python3", str(SCRIPT), self.lib_root, str(REPORT)]
        ok = False
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                line = line.strip()
                if line:
                    self.root.after(
                        0, lambda l=line: self.status_label.config(
                            text=l, fg=YELLOW))
            proc.wait()
            ok = proc.returncode == 0
        except FileNotFoundError as e:
            self.root.after(0, lambda err=e: self.status_label.config(
                text=f"error: {err}", fg=RED))
        self.root.after(0, lambda: self._scan_done(ok))

    def _scan_done(self, ok):
        self.scan_btn.config(state="normal", text="↻  Re-scan")
        if ok:
            self.load_report()
            self.status_label.config(text="scan complete", fg=GREEN)
        else:
            self.status_label.config(text="scan failed", fg=RED)


def main():
    root = tk.Tk()
    FlacBrowser(root)
    root.mainloop()


if __name__ == "__main__":
    main()
