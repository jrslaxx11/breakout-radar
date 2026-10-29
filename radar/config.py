"""Carga de configuración y utilidades comunes."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DOCS_DATA = ROOT / "docs" / "data"
HISTORY_DIR = DOCS_DATA / "history"
CACHE_DIR = ROOT / "data" / "cache"


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Config:
    settings: dict
    themes: dict
    overrides: dict
    intl: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        intl: list[tuple[str, str]] = []
        path = CONFIG_DIR / "universe_intl.csv"
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                rows = (line for line in fh if not line.startswith("#"))
                for row in csv.DictReader(rows):
                    sym = (row.get("symbol") or "").strip()
                    if sym:
                        intl.append((sym, (row.get("theme_hint") or "").strip()))
        return cls(
            settings=_load_yaml("settings.yaml"),
            themes=_load_yaml("themes.yaml"),
            overrides=_load_yaml("overrides.yaml"),
            intl=intl,
        )

    # --- atajos -------------------------------------------------------------
    @property
    def theme_defs(self) -> dict:
        return self.themes.get("themes", {})

    def suffix(self, sym: str) -> str:
        return sym.rsplit(".", 1)[1] if "." in sym and not sym.startswith("^") else ""

    def currency(self, sym: str) -> str:
        return self.settings["currency_by_suffix"].get(self.suffix(sym), "USD")

    def benchmark(self, sym: str) -> str:
        b = self.settings["benchmarks"]
        return b["by_suffix"].get(self.suffix(sym), b["default"])

    def duplicates(self) -> dict:
        return self.overrides.get("duplicates", {}) or {}
