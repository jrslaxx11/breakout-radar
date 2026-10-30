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
| `config/overrides.yaml` | Catalizadores verificados (temáticas y acciones), exclusiones (OPA, suspensiones) y cotizaciones duplicadas. Cada entrada caduca a los 21 días. |
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

  El Worker solo acepta peticiones de tu web, guarda las respuestas 15 minutos y el plan gratuito
  permite 100.000 consultas al día. Los valores calculados al momento no tienen temática,
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

**Temáticas (fases 2-3).** 0-100: fuerza relativa 30 (mediana de la RS compuesta frente al índice
regional: 20% 1 mes, 40% 3 meses, 40% 6 meses), consistencia 20, amplitud 20 (solo con valores de
selección no sesgada), volumen 15 y catalizadores 15. El catalizador es manual y con fuente
(`config/overrides.yaml`) cuando existe; si no, se usa su huella en el precio: proporción neta de
valores con una sesión de +4% y volumen ≥ 1,8x en las últimas 21 sesiones. Si un componente no
tiene dato, sus puntos se redistribuyen. Se seleccionan las 5 mejores, las empatadas a ≤ 0,5 puntos y las forzadas.

**Estados (fase 5).** Pivote = máximo de las sesiones 6 a 60 anteriores.

| Estado | Regla |
| --- | --- |
| Confirmada | Cierre sobre el pivote con volumen ≥ 1,5x la media de 20 sesiones y cierre en la mitad alta del día |
| Temprana | Cruza el pivote sin volumen suficiente o sin continuidad |
| Pre-breakout | A ≤ 5% del pivote, base ≥ 10 sesiones y ≤ 30% de profundidad (o flag de 5-9 sesiones y ≤ 12%), sobre la SMA50 |
| Retest | Cruzó el pivote en las últimas 5 sesiones y vuelve a menos de un 3% |
| Extendida | > 10% sobre el pivote o > 3 ATR sobre la SMA20 |
| Descartada | Ruptura fallida (> 3% bajo el pivote tras cruzarlo), bajo una SMA50 descendente, precio anclado o liquidez insuficiente |

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
