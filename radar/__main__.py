"""Uso:  python -m radar run [--force]"""
from __future__ import annotations

import argparse
import logging
import sys

from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radar", description="Global Thematic Leaders & Breakout Radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ejecuta el cálculo diario y escribe docs/data/latest.json")
    r.add_argument("--force", action="store_true", help="recalcula aunque la sesión ya esté procesada")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    if args.cmd == "run":
        out = run(force=args.force)
        if out.get("skipped"):
            print(f"Sesión {out['session']} ya procesada.")
            return 0
        meta = out["meta"]
        print(f"Sesión {meta['session']} · régimen {out['regime']['label']} · "
              f"{meta['coverage']['liquid']} valores líquidos · temáticas {', '.join(out['selected_themes'])} · "
              f"{len(out['lists']['presented'])} candidatas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
