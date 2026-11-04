"""Calendario de sesiones de la bolsa de EE. UU. (NYSE): fines de semana y festivos."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter(y: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano anónimo)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = date(y, month + 1, 1) - timedelta(days=1) if month < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """Festivo en sábado → viernes anterior; en domingo → lunes siguiente (regla de la NYSE)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def holidays(y: int) -> frozenset[date]:
    days = {
        _nth_weekday(y, 1, 0, 3),            # Martin Luther King Jr. (3.er lunes de enero)
        _nth_weekday(y, 2, 0, 3),            # Presidents' Day (3.er lunes de febrero)
        _easter(y) - timedelta(days=2),      # Viernes Santo
        _last_weekday(y, 5, 0),              # Memorial Day (último lunes de mayo)
        _observed(date(y, 7, 4)),            # Independence Day
        _nth_weekday(y, 9, 0, 1),            # Labor Day (1.er lunes de septiembre)
        _nth_weekday(y, 11, 3, 4),           # Thanksgiving (4.º jueves de noviembre)
        _observed(date(y, 12, 25)),          # Navidad
    }
    ny = date(y, 1, 1)
    if ny.weekday() != 5:                    # Año Nuevo en sábado no se traslada al 31 de diciembre
        days.add(_observed(ny))
    if y >= 2022:
        days.add(_observed(date(y, 6, 19)))  # Juneteenth
    return frozenset(days)


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def sessions_until(today: date, target: date) -> int | None:
    """Sesiones de EE. UU. desde mañana hasta `target` incluido (0 si es hoy, None si ya pasó)."""
    if target < today:
        return None
    n, d = 0, today
    while d < target:
        d += timedelta(days=1)
        n += is_session(d)
    return n
