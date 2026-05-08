PREFIX  ?= $(HOME)/.local
BINDIR  ?= $(PREFIX)/bin
APPDIR  ?= $(PREFIX)/share/applications
ICONDIR ?= $(PREFIX)/share/icons/hicolor/scalable/apps

DESKTOP_OUT := $(APPDIR)/audio-flac-quality-check.desktop

.PHONY: help run scan check install uninstall

help:
	@echo "Targets:"
	@echo "  make run          launch the library browser without installing"
	@echo "  make scan ROOT=…  run the scanner on ROOT (default /data/music)"
	@echo "  make check        syntax-check the Python sources"
	@echo "  make install      copy scripts + desktop entry under PREFIX"
	@echo "                    (default PREFIX=$$HOME/.local; sudo PREFIX=/usr/local for system-wide)"
	@echo "  make uninstall    remove what 'install' put down"

run:
	python3 flac_library_browser.py

ROOT ?= /data/music
scan:
	python3 check_flac_quality.sh "$(ROOT)" flac_report.txt

check:
	python3 -m py_compile check_flac_quality.sh flac_library_browser.py
	@if command -v desktop-file-validate >/dev/null 2>&1; then \
		tmp=$$(mktemp --suffix=.desktop); \
		sed -e 's|@BINDIR@|/tmp|g' -e 's|@ICONDIR@|/tmp|g' \
		    audio-flac-quality-check.desktop.in > $$tmp; \
		desktop-file-validate $$tmp && echo "desktop file ok"; \
		rm -f $$tmp; \
	fi
	@echo "syntax ok"

install:
	install -d $(BINDIR) $(APPDIR) $(ICONDIR)
	install -m 0755 check_flac_quality.sh   $(BINDIR)/check_flac_quality.sh
	install -m 0755 flac_library_browser.py $(BINDIR)/flac_library_browser.py
	install -m 0644 icon.svg                $(ICONDIR)/audio-flac-quality-check.svg
	sed -e 's|@BINDIR@|$(BINDIR)|g' \
	    -e 's|@ICONDIR@|$(ICONDIR)|g' \
	    audio-flac-quality-check.desktop.in > $(DESKTOP_OUT)
	chmod 0644 $(DESKTOP_OUT)
	@if command -v update-desktop-database >/dev/null 2>&1; then \
		update-desktop-database $(APPDIR) >/dev/null 2>&1 || true; \
	fi
	@echo "installed to $(PREFIX)"
	@echo "  scripts -> $(BINDIR)"
	@echo "  desktop -> $(DESKTOP_OUT)"

uninstall:
	rm -f $(BINDIR)/check_flac_quality.sh
	rm -f $(BINDIR)/flac_library_browser.py
	rm -f $(ICONDIR)/audio-flac-quality-check.svg
	rm -f $(DESKTOP_OUT)
	@if command -v update-desktop-database >/dev/null 2>&1; then \
		update-desktop-database $(APPDIR) >/dev/null 2>&1 || true; \
	fi
	@echo "uninstalled from $(PREFIX)"
