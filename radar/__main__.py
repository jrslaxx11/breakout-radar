"""Uso:  python -m radar run [--force]"""
from __future__ import annotations

import argparse
import logging
import sys
import warnings

from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radar", description="Global Thematic Leaders & Breakout Radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ejecuta el cálculo diario y escribe docs/data/latest.json")
    r.add_argument("--force", action="store_true", help="recalcula aunque la sesión ya esté procesada")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    # yfinance aún usa `inplace=`, que pandas 3.1 marca como obsoleto: miles de avisos que tapan el registro.
    # Además del filtro, se intercepta la impresión (alguna librería reinicia los filtros durante la descarga).
    warnings.filterwarnings("ignore", message=r".*inplace keyword.*")
    show = warnings.showwarning

    def quiet(message, category, filename, lineno, file=None, line=None):
        if "inplace keyword" not in str(message):
            show(message, category, filename, lineno, file, line)

    warnings.showwarning = quiet
    if args.cmd == "run":
        out = run(force=args.force)
        if out.get("skipped"):
            print(f"Sesión {out['session']} ya procesada: no hay datos nuevos que publicar.")
            return 0
        meta = out["meta"]
        print(f"Sesión {meta['session']} · régimen {out['regime']['label']} · "
              f"{meta['coverage']['liquid']} valores líquidos · temáticas {', '.join(out['selected_themes'])} · "
              f"{len(out['lists']['presented'])} candidatas")
        lu, st = out.get("luk_universe") or {}, out.get("luk_stats") or {}
        print(f"Luk · modo sugerido {(out.get('luk_regime') or {}).get('mode')} · L1 {lu.get('n_l1')} · L1b {lu.get('n_l1b')} · "
              f"universo {lu.get('n')} · líderes {lu.get('leaders')}")
        # Avisos en el registro de GitHub Actions (anotaciones): la lista no se relaja sola.
        warn = (out.get("luk_const") or {}).get("empty_warn_days", 3)
        if not (lu.get("n_l1") or lu.get("n_l1b")):
            print("::notice title=Retrocesos Luk::Hoy no hay ningún L1 ni L1b.")
        if (st.get("empty_streak") or 0) >= warn:
            print(f"::warning title=Retrocesos Luk::La lista de L1 y L1b lleva {st['empty_streak']} sesiones vacía. "
                  "Revisa qué filtro la vacía antes de tocar umbrales.")
        if st.get("avg") is not None and st["avg"] > (out.get("luk_const") or {}).get("list_target", 15):
            print(f"::notice title=Retrocesos Luk::Media de {st['avg']:.1f} valores al día en las últimas {st['days']} sesiones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
