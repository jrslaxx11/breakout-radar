# Radar de rupturas

Watchlist diaria de acciones con las mejores estructuras de ruptura dentro de las temáticas
que lideran el mercado mundial. Se calcula sola cada día laborable tras el cierre de EE. UU.
y se publica como una web en GitHub Pages.

- **Motor:** Python (`radar/`), datos diarios de Yahoo Finance vía `yfinance`.
- **Ejecución:** GitHub Actions, de lunes a viernes a las 22:30 UTC.
- **Vista:** página estática en `docs/` que lee `docs/data/latest.json`.
- **Histórico:** una foto por sesión en `docs/data/history/`, que permite marcar cada valor
  como NUEVA, CONTINÚA, MEJORA, DETERIORA o ELIMINADA respecto a la sesión anterior.

Ninguna fila es una recomendación de inversión: es una lista de estructuras para estudiar.

## Puesta en marcha (una sola vez)

1. **Activar la web:** en el repositorio, *Settings → Pages → Build and deployment → Source:
   GitHub Actions*.
2. **Primera ejecución:** *Actions → Radar diario → Run workflow* (marca "Recalcular" si quieres
   forzarla). Tarda entre 10 y 30 minutos.
3. La web queda en `https://<tu-usuario>.github.io/breakout-radar/`.

A partir de ahí se ejecuta sola. También se recalcula al cambiar cualquier archivo de `config/`
o `radar/`, así que editar un catalizador y guardarlo actualiza la web en unos minutos.

## Qué se puede ajustar

| Archivo | Para qué |
| --- | --- |
| `config/overrides.yaml` | Catalizadores verificados de acciones (caducan a los 21 días), exclusiones (OPA, suspensiones) y cotizaciones duplicadas. |
| `config/themes.yaml` | Definición de temáticas: listas fijas de tickers, subindustrias GICS, industrias de Yahoo y ETF de referencia. |
| `config/settings.yaml` | Filtros de liquidez, umbrales de cada estado, número de temáticas, temáticas forzadas, índices del régimen. |
| `config/universe_intl.csv` | Valores internacionales que se analizan siempre. |
| `config/mis_valores.csv` | Tus valores: se calculan cada día aunque no superen los filtros de liquidez y se pueden abrir desde el buscador. |

## Buscador de cualquier acción

La caja de la cabecera abre la ficha de cualquier valor (gráfico, niveles, puntuación y plan
Qullamaggie):

- **Valores del universo diario** (≈ 2.700): funciona sin nada más; los datos son los del último
  cálculo del radar.
- **Cualquier otro ticker de Yahoo Finance:** la web lo calcula al momento en el navegador con
  `docs/engine.js`, una réplica exacta del motor de Python (la prueba `tests/test_js_parity.py`
  comprueba que ambos dan los mismos estados, niveles y puntuaciones). Como el navegador no puede
  pedir datos a Yahoo directamente, hace falta un pequeño intermediario gratuito en Cloudflare:

  1. Crear una cuenta gratuita en <https://dash.cloudflare.com>.
  2. *Workers & Pages → Create → Create Worker* → ponerle un nombre (por ejemplo `radar-yahoo`) →
     *Deploy*.
  3. *Edit code* → borrar el contenido, pegar el de `cloudflare/worker.js` → *Deploy*.
  4. Copiar la dirección del Worker (`https://radar-yahoo.<tu-subdominio>.workers.dev`) en
     `config/settings.yaml`, apartado `web: worker_url`, y guardar. La web se republica sola.

  El Worker solo acepta peticiones de tu web, guarda los gráficos 15 minutos y los precios 1 minuto,
  y el plan gratuito permite 100.000 consultas al día. Si cambia `cloudflare/worker.js`, hay que volver
  a pegarlo en Cloudflare (*Edit code → Deploy*).

## Precios en vivo

Con el Worker configurado, mientras la web está abierta la watchlist y la ficha abierta se actualizan
cada minuto (cada 5 si no hay ningún mercado abierto) con el último precio de Yahoo Finance: casi en
tiempo real en EE. UU. y con 15-20 minutos de retraso en la mayoría de bolsas de fuera. La columna
"Ahora" compara ese precio con los niveles del cierre (pivote, entrada del plan Qullamaggie,
invalidación) y estima el volumen del día al cierre. Los estados y las puntuaciones siguen siendo los
del cierre: una ruptura no se confirma hasta que cierra la sesión. Los valores calculados al momento no tienen temática,
  catalizador ni fechas de resultados (su peso se redistribuye, como en el motor diario).

## Método

**Universo.** S&P 500, S&P 400 y S&P 600 (con su clasificación GICS), la lista fija internacional
y un descubrimiento semanal de los mayores ganadores de 52 semanas en 18 mercados. Filtros:
mediana de valor negociado ≥ 5 M USD y precio ≥ 5 USD; capitalización ≥ 500 M USD en las
candidatas finales.

**Régimen (fase 1).** Suma de señales (+1/−1): S&P 500 sobre SMA50 y SMA200, Nasdaq 100 y
Russell 2000 sobre SMA50, amplitud del S&P 500, nuevos máximos frente a mínimos, estructura del
VIX, STOXX 600 y mayoría de índices asiáticos sobre su SMA50. ≥ 5 favorable, 2-4 mixto, ≤ 1
desfavorable.

**Temáticas (fases 2-3).** 0-100, pesos en `config/settings.yaml` (`theme_score`):

| Componente | Puntos | Cálculo |
| --- | --- | --- |
| Fuerza relativa | 45 | Posición de la temática frente a las demás (la más fuerte 45, la más débil 0) según la mediana de la RS compuesta de sus valores: 20% 1 mes, 40% 3 meses, 40% 6 meses, cada valor frente a su índice regional |
| Consistencia | 15 | 5 por cada plazo (1, 3 y 6 meses) en el que la mediana supera a su índice |
| Amplitud | 20 | % de valores sobre la SMA50 y sobre la SMA200 (solo valores de selección no sesgada) |
| Cerca de máximos | 10 | % de valores a menos de un 10% de su máximo de 52 semanas (60% o más = 10) |
| Volumen | 10 | Volumen de las últimas 20 sesiones frente a las 50 anteriores, valores y ETF del sector (0,8x = 0; 1,2x = 10) |

Se seleccionan las 5 mejores, las empatadas a ≤ 0,5 puntos y las forzadas.

**Estados (fase 5).** La consolidación empieza en el máximo más alto de las últimas 60 sesiones que
tenga al menos 5 sesiones de antigüedad (máximo de la base); si algún cierre posterior lo superó, esa
base ya está rota. Su borde superior es la línea más plana que parte de ese máximo y deja por debajo
todos los máximos posteriores: plana en un canal o una base de techo plano, descendente en triángulos y
flags (como dibuja Qullamaggie). La línea descendente solo vale si la base tocó su zona de mínimos en
sus dos primeros tercios (mínimos crecientes); en un rebote en V la resistencia sigue siendo el máximo.
El **nivel de ruptura** de cada día es esa línea proyectada a ese día o, si queda por encima, el máximo
de las 3 sesiones anteriores (incluidos los máximos intradía que superaron la base sin cerrar fuera).

| Estado | Regla |
| --- | --- |
| Confirmada | Cierre sobre el nivel de ruptura con volumen ≥ 1,5x la media de 20 sesiones y cierre en la mitad alta del día |
| Temprana | Cruza el nivel sin volumen suficiente o sin continuidad |
| Pre-breakout | A ≤ 5% del nivel, base ≥ 10 sesiones y ≤ 30% de profundidad (o flag de 5-9 sesiones y ≤ 12%), sobre la SMA50 |
| Retest | Cruzó el nivel en las últimas 5 sesiones y vuelve a menos de un 3% |
| Extendida | > 10% sobre el nivel o > 3 ATR sobre la SMA20 |
| En base | A ≤ 12% del nivel, o base en formación (el valor sigue marcando máximos) |
| Descartada | Ruptura fallida (> 3% bajo el nivel tras cruzarlo), bajo una SMA50 descendente, precio anclado o liquidez insuficiente |

**Setup de Qullamaggie (solo rupturas).** Reglas de su artículo
["3 timeless setups"](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions)
con umbrales objetivos (`config/settings.yaml` → `qullamaggie`):

| Regla | Tipo | Cálculo |
| --- | --- | --- |
| Líder | Obligatoria | Entre el 2% del universo que más sube a 1, 3 o 6 meses |
| ADR ≥ 5% | Obligatoria | Media de máximo/mínimo − 1 en 20 sesiones (escáneres de su comunidad) |
| Subida previa ≥ 30% | Obligatoria | Del mínimo de las 63 sesiones anteriores al máximo de la base hasta ese máximo |
| Consolidación de 2 semanas a 2 meses | Obligatoria | 5 a 42 sesiones desde el máximo (5-9 = flag) |
| Retroceso ordenado | Obligatoria | La base corrige ≤ 50% de la subida previa |
| Mínimos crecientes | Secundaria | El último tercio de la base se mantiene por encima del mínimo de la base |
| Rango que se estrecha | Secundaria | Rango de precios de las últimas 5 sesiones ≤ 50% del rango de toda la base |
| Surfea medias | Secundaria | Sobre las SMA10 y SMA20 ascendentes, o sobre la SMA50 ascendente |

"Cumple" exige todas y el Nasdaq 100 sobre sus SMA10 y SMA20 ascendentes; si falla una secundaria o el
mercado no está en verde, "Con reservas". La sección "Setups Qullamaggie" aplica estas reglas a todo
el universo líquido, no solo a las temáticas, y lista los valores que rompen o están a ≤ 5% del nivel.
Entrada en el máximo de la primera vela de 1, 5 o 60 minutos; stop en el mínimo del día (nunca más ancho
que el ADR); vender 1/3-1/2 a los 3-5 días, stop a la entrada y el resto al primer cierre bajo la SMA10 o
la SMA20. Posición habitual 10-20% de la cuenta, nunca más del 30%; riesgo 0,25-1%.

**Puntuación de acciones (fase 6).** Fuerza relativa 25, base y estructura 25, ruptura y volumen
20, tendencia diaria y semanal 15, liquidez 10, catalizador 5. El riesgo se etiqueta aparte
(volatilidad: ATR ≥ 3%, 5% o 7%; resultados en ≤ 14 o ≤ 30 días; invalidación a más de 2,5 ATR o 10%;
liquidez < 20 M USD). Bajo 0-1, medio 2-3, alto 4 o más.

**Datos de la última sesión.** Tras el cierre, Yahoo publica la vela del día sin el precio de cierre
durante horas (EE. UU. y Europa), y la descarga la descarta. El radar la completa con la cotización
de cierre de la sesión regular (precio, apertura, máximo, mínimo y volumen) del mismo día, descarta
la vela de los mercados que siguen abiertos y excluye los valores que aun así no tienen la última
sesión de su mercado. El registro de cada ejecución (`docs/data/run-log.txt`) indica, por mercado,
la fecha de la última vela y cuántos valores la tienen.

**Gráficos.** Velas diarias con las medias de 10, 20 y 50 sesiones que usa Qullamaggie para seguir
la tendencia y gestionar las salidas; la de 200 se activa a mano.

## Ejecutar en local

```bash
pip install -r requirements.txt
python -m pytest -q
python -m radar run --force
python -m http.server -d docs 8000   # y abrir http://localhost:8000
```

## Limitaciones

- Solo cierres diarios confirmados; nada en tiempo real.
- Resistencias e invalidaciones son algorítmicas: valídalas en el gráfico.
- La amplitud de mercado solo se mide en EE. UU.
- Yahoo puede limitar peticiones; si faltan datos, el informe lo indica en la cobertura y en
  `docs/data/run-log.txt`.
- Las fechas de resultados marcadas como estimadas no están confirmadas por la empresa.
