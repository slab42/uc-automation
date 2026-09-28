#!/usr/bin/env python3

"""
Persistence for the UC Automation menu launcher's per-user preferences:
favorites, hidden scripts, and display toggles.

State lives at <root>/.var/launcher.json. Every mutation writes
immediately and atomically (dump to launcher.json.tmp, then os.replace),
so a Ctrl-C mid-session never loses or corrupts what the user just did.

A broken or unreadable config must never crash the launcher: invalid
JSON is quarantined to launcher.json.bak and defaults are used instead.
"""

import json
import os
from pathlib import Path
from typing import List, Set

CONFIG_VERSION = 1


class LauncherConfig:
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = root / '.var'
        self.path = self.config_dir / 'launcher.json'

        self.favorites: List[str] = []
        self.hidden: Set[str] = set()
        self.show_hidden: bool = False
        self.clear_screen: bool = True
        # True when the on-disk file is a newer format than we understand.
        # We keep running (read-only) rather than risk clobbering it.
        self.read_only: bool = False

        self._load()

    # -- loading ----------------------------------------------------------

    def _defaults(self):
        self.favorites = []
        self.hidden = set()
        self.show_hidden = False
        self.clear_screen = True
        self.read_only = False

    def _load(self):
        if not self.path.exists():
            self._defaults()
            return

        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            self._quarantine_bad_config()
            self._defaults()
            return

        if not isinstance(data, dict):
            self._quarantine_bad_config()
            self._defaults()
            return

        version = data.get('version', 1)
        if not isinstance(version, int) or version > CONFIG_VERSION:
            print(f"Warning: {self.path} is version {version!r}, newer than "
                  f"this launcher understands (max {CONFIG_VERSION}). "
                  f"Running read-only so your settings are not overwritten.")
            self.read_only = True

        self.favorites = [str(x) for x in (data.get('favorites') or [])]
        self.hidden = {str(x) for x in (data.get('hidden') or [])}
        self.show_hidden = bool(data.get('show_hidden', False))
        self.clear_screen = bool(data.get('clear_screen', True))

    def _quarantine_bad_config(self):
        try:
            bak = self.config_dir / 'launcher.json.bak'
            self.path.replace(bak)
            print(f"Warning: {self.path} was not valid JSON. "
                  f"Moved it to {bak} and starting from defaults.")
        except OSError as e:
            print(f"Warning: could not read {self.path} ({e}). "
                  f"Starting from defaults; it will not be overwritten.")
            self.read_only = True

    # -- saving -------------------------------------------------------

    def _save(self):
        if self.read_only:
            return
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            data = {
                'version': CONFIG_VERSION,
                'favorites': self.favorites,
                'hidden': sorted(self.hidden),
                'show_hidden': self.show_hidden,
                'clear_screen': self.clear_screen,
            }
            tmp_path = self.config_dir / 'launcher.json.tmp'
            tmp_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
            os.replace(str(tmp_path), str(self.path))
        except OSError as e:
            print(f"Warning: could not save launcher settings: {e}")

    # -- favorites ----------------------------------------------------

    def is_favorite(self, rel: str) -> bool:
        return rel in self.favorites

    def toggle_favorite(self, rel: str) -> bool:
        """Flip favorite status for rel; returns the new state."""
        if rel in self.favorites:
            self.favorites.remove(rel)
            result = False
        else:
            self.favorites.append(rel)
            result = True
        self._save()
        return result

    def remove_stale_favorites(self, rels_to_remove: Set[str]):
        """Remove exactly the given favorites (paths confirmed missing on disk).

        The caller must pass the explicit set of rels to remove - favorites
        already verified as pointing to files that no longer exist. This
        function does not infer staleness itself and does not touch any
        favorite whose rel is not in rels_to_remove (e.g. a favorite whose
        script still exists on disk but currently lacks a "# TITLE:" line
        must never be passed here).
        """
        kept = [r for r in self.favorites if r not in rels_to_remove]
        if kept != self.favorites:
            self.favorites = kept
            self._save()

    # -- hidden ---------------------------------------------------------

    def is_hidden(self, rel: str) -> bool:
        return rel in self.hidden

    def toggle_hidden(self, rel: str) -> bool:
        """Flip hidden status for rel; returns the new state."""
        if rel in self.hidden:
            self.hidden.discard(rel)
            result = False
        else:
            self.hidden.add(rel)
            result = True
        self._save()
        return result

    def toggle_show_hidden(self) -> bool:
        self.show_hidden = not self.show_hidden
        self._save()
        return self.show_hidden
