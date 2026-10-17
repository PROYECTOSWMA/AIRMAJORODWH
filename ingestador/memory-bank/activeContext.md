# 🚨 LEER PRIMERO — ESTADO Y PENDIENTES (actualizado 2026-09-25)

**Sesión anterior (SIRE): `memory-bank/HANDOFF-propagacion-dagster-SIRE.md`.**

## ✅ 2 bugs de integridad en SIRE: compras con importe 0 y documentos que se caían (2026-10-09)
El cliente avisó de filas "vacías" en `dwh.vista_reporte_gerencial` (cantidad NULL, importe 0,
sin descripción ni centro de costo). Eran **dos fallos distintos del pipeline**, ambos en la rama
de compras de SUNAT (SIRE), y **ambos silenciosos** (`dbt run` daba PASS):

1. **Importe 0 en 395 compras sin detalle de ítems.** El modelo solo leía `bi_gravado_dg`; hay
   comprobantes en los que SUNAT **no informa esa base** y el importe está en otros campos:
   * **DAM de importación (tipo 54): 66 filas / 93.323,00 S/** → todo en `otros_trib_cargos`
     (y a nivel de comprobante en `total_cp`); **0 de esas filas tiene detalle**.
   * **Facturas de banco / servicios no gravados (tipo 1): 324 filas / 383.459,11 S/** →
     en `valor_adq_ng` + `total_cp` (`bi_gravado_dg`, `igv`, `isc`, `icbper` = 0).
   * **Notas de crédito (tipo 7): 5 filas / −800,00.**
   * Arreglo en `purchs/sire/sire_purchs_std.sql`: cadena `d.mto_val_unitario*d.cnt_items` (si hay
     detalle) → `NULLIF(bi_gravado_dg,0)` → `NULLIF(bi_gravado_dgng+dng+valor_adq_ng,0)` →
     `total_cp − igv − isc − icbper`. **NUNCA se reparte el total del padre entre líneas hijas**
   (solo entra cuando NO hay detalle, que es cuando no hay riesgo de duplicar).
   Efecto en `moves` (DuckDB): 9.642.312,21 → **9.410.683,84**; filas con importe 0: 15.458 → **15.260**.

2. **`WHERE partner_doc NOT IN (...)` tiraba TODA fila sin RUC.** En SQL `NULL NOT IN (...)` es
   NULL, no TRUE ⇒ **26 comprobantes DAM de VSE AVIATION (`nro_doc_identidad` NULL,
   40.033,00 S/) nunca llegaban a `moves`** (y `tipo 54` solo tenía 8 de 34 documentos).
   Arreglo en `purchs/purchs_std.sql`: `coalesce(partner_doc, '') NOT IN (...)`.
   ⚠️ **Pendiente cliente**: esas 26 filas entran con la cuenta por defecto **659902**, porque
   `static_aux_accounts_assignment.csv` mapea los otros DAM (`'0'` y `US003990`) a **603301** pero
   no tiene regla para `NULL`. Si quieren 603301 hay que añadir la fila (el CSV es dato suyo).

**Verificado en `dwh`** (`dbt_run` PASS=13 · `publish_dwh` 13 tablas / **139.206 filas**, +26):
los 5 documentos avisados ya traen importe (−72 · −2.853 · −1.924 · −295 · −580), `tipo 54` pasa
de 8 a **34** documentos (−48.146,00) y 603301 baja de 15 a **10** filas en 0.

**Precision (PAG): NO es un bug.** Esos importes 0 son las líneas de **devolución de core**
(condición `AR`, "Return Core on R.M.A.", `$ 0.00` en el propio PDF): cada factura trae el par
`OH` (cobrado) + `AR` (core, 0). Igual que dice el modelo desde el principio.

**Los 0 que siguen en `moves` (15.260) son ceros del ORIGEN**, no del parser:
**planilla 13.364** (el `UNPIVOT` de `payroll_std` saca un concepto por fila y los conceptos no
usados vienen en 0) y **LAP 1.820** (el Excel `Importe Bruto` = 0 en los servicios no cobrados,
con `Matricula`/`Servicio` sí informados). `603301` solo tiene 10 (7 core de Precision + 3 sin
importe en el origen). Decisión abierta: ocultar esas filas con importe 0 en el reporte.


## ✅ Textron: el parser perdía las líneas de un formato de export (2026-10-09)
- **Detectado al revisar** por qué el reporte mostraba documentos sin importe: en la
  comprobación *líneas vs total de la factura* apareció que **Textron tenía 13 facturas
  sin ninguna línea** y un hueco de **52.225,09** en el EERR (`suma_lineas` 33.880,92 vs
  `suma_totales` 86.106,01).
- **Causa**: Textron exporta la tabla de ítems de **dos formas** y el parser solo entendía
  una. En el formato viejo el Nº de línea y el P/N van **juntos en la misma celda**
  (`'1 MS28778-5'`) y `_ITEM_RE` (`^(line)\s+(part)$`) los reconocía; en el nuevo van
  **partidos en dos celdas** (`['1', 'MS28778-5', 'PACKING', …]`) → el regex no casaba y la
  factura se quedaba **sin líneas**.
- **Arreglo** (`textron.py`, `_LINEA_RE` + `fin_pn`): se aceptan las dos formas; los
  importes ya se leían **desde el final** de la fila, así que solo hacía falta saber en qué
  celda termina el P/N (la descripción empieza una celda más a la derecha en la partida).
- **Resultado publicado**: Textron **65 → 235 líneas** (46 facturas; de 13 sin líneas a 4),
  `invoice_std` **187 → 357 filas** / 654.249,01 → **703.506,66** y `moves` 603301
  **+49.257,65** (total **2.513.029,10** en 92.865 filas de `moves`). `dbt_run` PASS=12 ·
  `publish_dwh` 12 tablas / **138.228 filas**.
- **Lo que queda de hueco (~4.101) NO son líneas**: es el **shipping & handling + impuesto**
  de la cabecera (las líneas suman el `subtotal`, y `total = subtotal + flete + impuesto`).
  El EERR hoy cuenta el `subtotal` (decisión pendiente del cliente).
- **Las 4 facturas sin líneas que quedan** (`TEXTRON 0091603497`, `Textron 0091582203/204`,
  `TextronAviationInvoice_91579509`) no traen `INVOICE TOTAL` ni ítems (no son facturas de
  consumo); como `invoice_std` cruza cabecera ↔ detalles por `source_file`, **no entran** al
  DWH.

## ⚠️ 6 facturas están IMPRESAS DOS VECES (ficheros duplicados) — decisión pendiente
- Comprobado fichero a fichero: son **copias exactas** (mismo Nº, mismo total y las mismas
  líneas) con el nombre ligeramente distinto (con/sin el Nº de PO o el `WH…`):
  `FENIX/INVC-16395` (+50,00), `FENIX/INVC-16499` (+278,00), `PRECISION/99214038` (+1.695,00),
  `TEXTRON/IJ17562168` (+19,58), `TEXTRON/IJ17593468` (+1.862,10), `TEXTRON/IJ17593524` (+888,34)
  ⇒ **sobre-coste 4.793,02** (el EERR las cuenta dos veces).
- Arreglo: borrar los PDF repetidos de las carpetas (lo más honesto) **o** que el pipeline
  lea cada Nº de factura **una sola vez** (dedupe por proveedor + Nº, solo si el contenido es
  idéntico). **Pendiente de que lo decida el cliente**.
- Y `FENIX/INVC-17884` (1 fichero) tiene **una línea sin leer**: sus líneas suman 9.454,07 y
  su total es 14.422,07 (faltan **4.968,00**) — pendiente de mirar ese PDF.

## ℹ️ Por qué hay documentos con importe **0** o vacío en el reporte (no falta nada)
- Las líneas con **0,00** son la 2ª línea del ítem: el **CORE** (`condition = 'AR'`, sin
  precio: `1 8210-003-01 OH … 2.950,00` + `2 8210-003-01 AR … 0,00`). En el reporte sale
  también la línea del ítem, con el importe. Hoy: 3 en Precision + 1 en JetSet (la orden
  `LOG-RO- 0133-2025`, que se emite sin precio: "we send our formal PO when receive the
  final cost, after evaluation").
- Las de **importe vacío** son **notas** de la orden de compra (`CORE $ 10,500`, `TAG 2025`)
  sin cantidad ni precio: `qnt` y `amnt_taxable` van NULL, y `subtotal_base_soles` NULL.


- **Pedido del cliente**: (1) cruzar el **código de PO** de cada factura con la orden;
  (2) a las facturas que **tienen** PO, completarlas con el **centro de costo (aeronave)**
  —ya se hacía— y con el **tipo de mantenimiento** de la orden; (3) las órdenes que
  **no tienen factura** también deben entrar a `moves` (solo con los datos de la orden);
  (4) sin que nada se cuente dos veces.
- **Contrato: 26 → 27 columnas.** La nueva es `appended_tipo_mantenimiento` (texto), la
  última de `moves`, y sale de `static_invoice_po_details.maintenance_note` = la columna
  **`TIPO DE MANTENIMIENTO`** del formulario de la PO (`CORRECTIVO`, `PREVENTIVO`,
  `SECCION CALIENTE DE MOTOR`, `1000 hrs.`, `STOCK`…). Se añade en:
  - `models/invoices/po_cost_center.sql` (ephemeral, el apoyo del cruce): `por_part` la
    aporta por (PO, P/N) y la fila general `'*'` **solo si toda la orden tiene un único
    tipo** (misma regla que el centro de costo; si la PO mezcla tipos queda NULL).
  - los **6 `*_std`** de proveedor: `COALESCE(po_part…, po_gen…)` (igual que `cost_center`).
  - `po_std` (los de las órdenes sin factura) y, para que el `UNION ALL` cierre:
    `purchs_std` (las 4 ramas de reporte ponen `CAST(NULL AS VARCHAR)`), `sales_std` y
    `labor_std` (envuelven su unión y añaden el NULL) y `moves` (columna 27).
- **Las órdenes van DENTRO de `invoice_std`** (2026-10-09 se eliminó el modelo `po_std`):
  `invoice_std` = las 6 ramas de factura **+ las órdenes SIN factura** (dos CTEs nuevas:
  `facturas` con la clave canónica de PO de las 6 carpetas, y `orden` con cada línea de la
  orden en el contrato). **Cada compra entra una sola vez** (la factura si existe y, si no,
  la orden). El **proveedor de la orden se sabe por su carpeta** (una carpeta = un
  proveedor): el parser de PO ahora escribe `source_file = '<CARPETA>/<archivo>.pdf'` (antes
  solo el nombre del archivo: dos PDF homónimos en subcarpetas distintas habrían mezclado sus
  ítems, porque cabecera y detalles se cruzan por `source_file`) y `invoice_std` lo mapea al
  **mismo código** que las facturas de ese proveedor (`FENIX` → `INVC-FENIX AEROSPACE`,
  `PRECISION HELIPARTS (PAG)` → `INVC-PRECISION HELIPARTS`, `JETSET`/`KAL AIRPARTS`/`PENIEL`/
  `TEXTRON` → igual). `move_type` = `'Compras'` (confirmado por el cliente, igual que las
  facturas y que planilla/RH). De las 620 filas de OC se descartan las de relleno (solo el
  Nº de ítem).
- **Números (publicado el 2026-10-09, `dwh`, 12 tablas / 137.888 filas)**:
  `invoice_std` **187 / 654.249,01** = 162 líneas de **factura** (632.716,65) + **25 líneas
  de órdenes sin factura** (21.532,36): 11 documentos — PO 698/699/700/705/707/713/731/738/
  840-2026, OS 814-2026 y LOG-RO- 0133-2025). Con tipo de mantenimiento: **45/67 Fenix ·
  8/15 JetSet · 10/13 Kal · 5/8 Peniel · 11/15 Precision · 49/69 Textron**. `moves`
  **92.695** (Compras 68.750 / Ventas 23.945) y cuenta **603301: 2.463.771,45** en 270 filas.
  **Verificado que no se duplica**: 0 filas de órdenes que ya tengan factura y 0 claves
  repetidas en el override.
- **Caso bonito (la razón del pedido)**: las 5 facturas de **Precision** no traían Nº de PO
  (ver abajo), así que sus POs salían como huérfanas **y** la factura entraba sin aeronave
  ni tipo. Al arreglar el parser, esas POs dejan de ser huérfanas (−9 filas en `moves`) y sus
  líneas salen completas: `99214018/19` → **2104 PREVENTIVO**, `99214024/38` → **2221 PREVENTIVO**,
  `99214131` → **2104 CORRECTIVO**.

## ✅ Parser: factura 54402 de JetSet (detalles que no se leían) + 2 arreglos más (2026-10-09)
- **Síntoma**: la factura **54402** (`JETSET AIRMOTIVE _54402 PO 069-2025.pdf`) no daba
  **ninguna** línea de detalle (0 ítems) mientras las otras 5 de JetSet salían bien.
- **Causa**: la tabla de ítems se leía con la **rejilla por coordenadas**
  (`rejilla(gap=6)` + `alinear_x`) y en esa factura (a) el **número de línea va pegado a la
  descripción** (hueco < 6 pt: `1` + `C.T. DISC BALANCING ASSEMBLY…` caían en la misma
  celda) y (b) las columnas `Shipped/BackOrd/CD` van **~5 pt más arriba** que el texto, así
  que `y_tol=3` partía la fila lógica en tres. Probé `gap` de 2 a 7: **ningún valor**
  arreglaba la 54402 sin romper las otras (o daban 0 ítems o el P/N salía `C.T.`).
- **Arreglo (enfoque simple, sin umbrales)**: la tabla de ítems de **Quantum Control** ahora
  se lee del **texto por líneas** (`_common.read_pages`), que es como el software la imprime
  (`1 <P/N y descripción> Shipped BackOrd CD Unit Price UOM Total Amt`, una línea por ítem):
  - `_cola_tabla()` lee la cola **de derecha a izquierda** (importe, UOM, precio y, si caben,
    Shipped/BackOrd/CD), así que no hay que adivinar dónde corta cada columna;
  - el P/N y la descripción salen de `_parte_desc` (con `//` = P/N alterno, como antes);
  - las líneas sin Nº de línea son continuación → `extras`; y si el ítem imprime la
    **descripción arriba** y el P/N **rotulado** (`P/N: 3049291-01`), ése es el P/N real y la
    primera línea queda como descripción (es el caso de la 54402);
  - las cantidades que caen en su propio renglón (`58 0 NE`) rellenan al ítem en curso.
  - La **cabecera** (formulario de dos columnas) sigue leyéndose con la rejilla.
  - `_common.py` ya documentaba este formato como de **texto con expresiones regulares**; el
    `rejilla`+`gap` era la desviación.
- **Verificado**: los 9 PDFs de Quantum Control (6 JetSet + 3 Peniel) dan lo mismo que antes
  **excepto** la 54402, que pasa de **0 → 3 líneas**; y su suma, **6.190,00**, es exactamente
  su `SubTotal` (antes la factura entraba al EERR sin detalle). JetSet: 6 → **9 líneas /
  467.755,00**; Peniel sigue **5 / 459,30**. `invoice_std` 159 → **162 filas** /
  626.526,65 → **632.716,65**.
- **Precision (PAG) perdía el Nº de PO** (5 de 6 facturas): el PDF imprime el `:` en su
  **propia celda** (`['Customer P.O.', ':PO 717-2026']`) y la etiqueta se quedaba sin dos
  puntos, así que `_CAMPO_RE` no casaba. Arreglo: `precision._textos()` **pega** la celda que
  empieza por `:` a la anterior antes de emparejar etiquetas → se recuperan **también**
  `Invoice Date`, `Due Date`, `Terms`, `Ship Via`… (antes `po_number`, `invoice_date` y
  `due_date` salían NULL). El Nº de factura se sigue leyendo igual (`re.split('pg')`).
- **Kal**: el Nº de PO se leía solo como `CUSTOMER ORDER NO.`; se añade el fallback sin punto.
- **Tests nuevos** `src/tests/test_invoices_intl_items.py` (5): tabla de Quantum en texto,
  factura 54402 sintética (P/N rotulado + cantidades en otro renglón + suma = SubTotal), el
  pie numerado (`1. Material is subject…`) **no** genera ítems, el pegado de la celda `:`
  de Precision y un test sobre los **PDF reales** (54402 = 3 líneas / 6.190,00; Peniel 5 / 459,30).
- **Fechas arregladas (`_common.py`)**: las compras del exterior salían sin fecha o **en el
  mes equivocado** (`precision_std` 0 de 9 líneas con `doc_date`, Textron 34 de 65). Eran
  **dos** fallos: (a) `iso_from_slash` tenía el **día y el mes invertidos** en su modo US
  (`dia, mes = (b, a) if day_first else (a, b)`): `'03/26/26'` daba el **3 de junio** y las
  de día > 12 (`'1/22/2026'`) quedaban en **NULL** (mes inválido) — afectaba a los 4 campos
  de fecha de Quantum (JetSet/Peniel) y a los 3 de Textron; y (b) `iso_from_text` no
  reconocía **`'Feb-04-2026'`** (mes primero, Precision/PAG). Ahora **casi todas** las
  líneas del exterior tienen `doc_date` (Fenix 65/67 · JetSet 15/15 · Kal 13/13 · Peniel 8/8
  · Precision 15/15 · Textron 69/69), incluido el **54402 → 2026-01-06** (antes 2026-06-01)
  y Precision 99214024 → **2026-02-04 / vence 2026-03-06**.
- **Nota**: `payroll_std`/`prof_invoice_std` con `move_type = 'Compras'` **es lo pedido**
  (igual que las facturas del exterior): las 28.226 líneas de planilla/RH van dentro de
  `Compras` en `moves`, con su cuenta propia (el comentario de `moves.sql` que decía
  `'PLANILLA'` quedó corregido).

> **⚠️ Ya NO existe `scripts/` (2026-09-25)**: el pipeline se ejecuta **solo con Dagster**
> (assets/jobs de `definitions.py`). Las referencias a `scripts/run_pipeline.py` y
> `scripts/pipeline_cron.sh` del README y de este banco de memoria quedan **obsoletas**:
> usa `python -m dagster asset materialize -m definitions --select ...` desde la raíz.
> **Cierra DBeaver antes de `dbt run`**: DuckDB abre `analytics_poc.duckdb` con lock
> exclusivo y si está abierto `dbt_run` falla con `IO Error: Could not set lock`.

## 🚨 BUG de DuckDB (cte_inlining) con los 6 modelos `ephemeral` de facturas (2026-10-08)
- **Síntoma**: `dwh.invoice_std` publicaba **las filas de Peniel como las de JetSet**
  (6 filas / 461.565,00 en lugar de 5 / 459,30; total 160 en vez de 159). El EERR habría
  sumado 461.105,70 de más en la 603301. `dbt run` acababa **PASS** sin avisar: dato erróneo silencioso.
- **Cuándo aparece**: cuando los 6 `*_std` de `models/invoices/` (Fenix/JetSet/Kal/Peniel/
  Precision/Textron) son **`ephemeral`** y se inlinean juntos en el `UNION ALL` de
  `invoice_std`. Como **tablas** cada rama se compila y ejecuta aparte y sale bien (así
  estaba el 2026-10-07): el bug NO es del SQL, ni del `CAST`, ni de la CTE interna
  `factura` (renombrarla no cambia nada), ni del escáner sqlite.
- **Causa real**: es del **optimizador de DuckDB 1.5.5**. Bisecado con el SQL compilado
  ejecutado a mano: con el `UNION ALL` completo falla; cualquier pareja de ramas o
  poniendo Peniel primero sale bien; renombrar CTE / `SELECT *` vs columnas explícitas /
  `UNION ALL BY NAME` / grupos 3+3 o 2+2+2 **no** lo arreglan. Probando
  `SET disabled_optimizers=...`: **`cte_inlining` → datos correctos**, `common_subplan` y
  `unused_columns` también (son la misma maquinaria de reescritura de CTE).
- **Arreglo (en `src/dbt/profiles.yml`)**: `settings: disabled_optimizers: cte_inlining`.
  Con eso los 6 modelos pueden seguir siendo **`ephemeral`** y los datos salen bien.
  Si algún día se quita, **comprobar** Fenix 61 · JetSet 6 · Kal 13 · **Peniel 5** ·
  Precision 9 · Textron 65 = **159 filas / 626.526,65** antes de publicar.
- **Nota de mantenimiento**: `po_std` también es `ephemeral` y **nadie lo referencia**, así
  que dbt **no lo construye** (no entra al DuckDB ni se publica). Y las tablas viejas de
  estos modelos **siguen en `dwh`** desde el 2026-10-07 (`fenix_std`…`textron_std`, `po_std`):
  como ya no se producen, quedan congeladas (el `publish_dwh` las avisa como "ya NO están").

## ✅ `partner_doc` de las facturas del exterior y de las ambulancias sin RUC (2026-10-08)
- **Pedido del cliente**: en las facturas del exterior, `partner_doc` = **`INVC-<proveedor>`**
  (no su tax id de EE.UU.) y en `partners` la **descripción es solo el nombre** del
  proveedor. Y en ambulancias, los terceros **sin RUC** = **`NORUC-<nombre>`**, también con
  el nombre como descripción.
- **Proveedor = carpeta** (una carpeta = un proveedor, confirmado por el cliente):
  `FENIX AEROSPACE`, `JETSET`, `KAL AIRPARTS`, `PENIEL`, `PRECISION HELIPARTS`, `TEXTRON`.
  En los 6 modelos se escribe el literal: `'INVC-FENIX AEROSPACE' AS partner_doc`, etc.
  El tax id del PDF **no se pierde**: sigue en `static_invoice_<prov>_header.vat_tax_id` /
  `.fed_tax_id`. En `ambulance_sales_std` (rama de ventas) ahora:
  `CASE WHEN <hay RUC en SIRE> THEN s.nro_doc_identidad WHEN <hay cliente> THEN 'NORUC-' || trim(b.cliente) END`.
- **`partners.sql`**: dos vías nuevas con **prioridad 1** (la más alta, no chocan con ningún
  documento real) que se leen de `invoice_std` y de `ambulance_sales_std`, y quitan el
  prefijo para la descripción (`replace(partner_doc, 'INVC-', '')` / `'NORUC-'`). Es DRY: si
  mañana aparece otra carpeta/proveedor, su descripción sale sola.
- **Verificado en el DWH**: `dwh.invoice_std` 159 / 626.526,65 con los 6 códigos `INVC-*`;
  `dwh.partners` con los 6 `INVC-*` + **39 `NORUC-*`**; `dwh.moves` 92.667 / 9.719.292,22 y
  la **603301** 242 / −2.436.049,09 (idéntico a antes del cambio salvo las etiquetas).


## 🚨 FIX pipeline: dos `CAST` crudos tumbaban `moves` con el xlsm nuevo de ambulancias (2026-10-07)
- **Síntoma**: al materializar `static_data_asset` + `dbt_run` (Dagster) el run **caía**:
  `Runtime Error in model moves` → **`Conversion Error: Could not convert string '' to INT64`**
  (PASS=18 ERROR=1, y `publish_dwh` ni se ejecutaba).
- **Causa (dato, no código)**: el reporte de ambulancia (`VENTAS-C X C ... .xlsm`) trae ahora un
  comprobante **sin correlativo**: `agregado_factura = ["B001"]`. Con `split_part('B001','-',2)`
  el 2º trozo es `''` y un `CAST('' AS BIGINT)` **aborta la consulta entera**. Antes no pasaba
  porque el `db.sqlite` tenía una ingesta de un xlsm viejo (la fragilidad estaba latente).
- **Arreglado en 2 sitios** (mismo patrón, ambos `materialized='ephemeral'` → el error aparecía
  en `moves` con un `LINE` distinto cada vez, que es lo que confunde al depurar):
  - `src/dbt/models/sales/from_reports/ambulance_sales_std.sql` (LEFT JOIN a `sire_sales`): el
    `CAST(... AS BIGINT)` de `split_part(agregado_factura[0],'-',2)` → **`TRY_CAST`**. Esa venta
    ya no cruza con SIRE (sin número no hay con qué) y se queda con la fecha del vuelo, que es lo
    que ya hacía el `coalesce` de `doc_date`.
  - `src/dbt/models/sales/sales_std.sql` (CTE `amb_docs`, clave del anti-join contra SISA/SIRE)
    → **`TRY_CAST`**; la fila queda con `doc_number` NULL.
- **Lección**: en este repo los números de documento de reportes **siempre** con `TRY_CAST` (ya
  se hacía así en `cost_centers.sql` con esa misma columna). Un `CAST` crudo sobre dato de
  origen = bomba de relojería que solo estalla cuando al cliente se le ocurre emitir una boleta.
- **Verificado**: `dbt run` → **PASS=20 ERROR=0** (moves en 1,3 s; el aviso viejo de los 8,9 GB
  de spill ya no aplica) y `publish_dwh` → **20 tablas / 138.811 filas** al schema `dwh`.

## ✅ Publicado en el DWH: facturas del exterior como CONSUMIBLES (2026-10-07)
- **Cadena lanzada** (desde la raíz, `DAGSTER_HOME=$PWD/dagsterhome`):
  `python -m dagster asset materialize -m definitions --select "static_data_asset,dbt_run,publish_dwh"`.
  `env/.env` lo carga solo `publish_resource` (no hace falta exportar `PG*` a mano con el CLI).
- **`static_data_asset`** OK (2m) → `db.sqlite`; **`dbt_run`** PASS=20; **`publish_dwh`** OK
  (29 s, 20 tablas, 138.811 filas) al schema **`dwh`**.
- **Ya están en el DWH**: `dwh.invoice_std` (159 filas / **626.526,65**), `dwh.fenix_std` (61),
  `dwh.jetset_std` (6), `dwh.kal_std` (13), `dwh.peniel_std` (5), `dwh.precision_std` (9),
  `dwh.textron_std` (65) y `dwh.po_std` (620 / 246.225,79, **maestro, no suma**).
- **En `dwh.moves`** (compras, importe **negativo**): cuenta **603301** = 242 filas / −2.436.049,09,
  de las cuales las del exterior se ven por serie (INVC 61, KA26 13, `IJ*`/`I*` Textron+Peniel,
  `(sin serie)` 15 = JetSet+PAG) y el resto son compras de SIRE/RH que ya caían en 603301.
- **Ojo**: las **órdenes** (`po_std`) no entran al EERR a propósito (duplicarían el gasto).


## ✅ dbt: carpeta `models/invoices/` con las facturas del exterior en formato DWH (2026-10-07)
- **Pedido**: una carpeta en dbt que genere `invoice_std` **con el formato del DWH**
  (las 26 columnas de `purchs_std`), con un modelo por proveedor (`fenix_std`,
  `jetset_std`, `kal_std`, `peniel_std`, `precision_std`, `textron_std`) y `po_std`
  para las órdenes de compra. Los nombres son **`invoices`** (no `intl`). Todo va a
  la cuenta **603301 = CONSUMIBLES** (COSTO DE VENTAS).
- **Dónde**: `src/dbt/models/invoices/` (8 modelos; los 6 `*_std` de proveedor y `po_std`
  son **`ephemeral`** —ver la nota del BUG de `cte_inlining` al inicio de este archivo—,
  `invoice_std` es **tabla** y `po_cost_center` es el apoyo efímero) + 2 macros nuevos:
  - `macros/split_invoice_doc.sql`: parte el Nº de factura en `doc_serie` /
    `doc_number` del contrato ('INVC-18214' → INVC / 18214; sin guion y con letras
    (Textron `IJ17531927`, Peniel `I67995`) el número queda **entero en la serie**
    para no perder la identidad de la factura; si es numérico puro (JetSet `54998`,
    PAG `99214024`) no hay serie).
  - `macros/invoice_po_key.sql`: clave canónica del Nº de PO para cruzar
    factura ↔ orden. Quita el prefijo `PO` y **todo** lo que no sea alfanumérico,
    porque los dos lados lo escriben distinto ('PO 825-2026' vs '825-2026' →
    '8252026'; 'PO. 238 - 2024' vs '238-2024' → '2382024').
- **`po_cost_center.sql`** (ephemeral): el cruce. Una fila por (PO, P/N) con el
  **centro de costo** y la **fecha de la orden**, más una fila general por PO
  (`part_key = '*'`) que **solo se emite si toda la orden apunta a una única
  aeronave**. La aeronave sale de `cc` **o** de `aeronave` con
  `normalize_registration` (los compradores la escriben en cualquiera de las dos, y
  'STOCK'/'NEW' → NULL ✓). Cada factura hace **dos LEFT JOIN** (P/N y general): así
  nunca se duplica una línea de factura (la primera versión con un solo JOIN al P/N
  y sin `GROUP BY` habría duplicado).
- **`invoice_std`** = UNION ALL de las 6 facturas (159 líneas, **USD 626.526,65**);
  entra en `purchs_std.sql` otra vez (`UNION ALL SELECT * FROM ref('invoice_std')`,
  con la cuenta 603301 que deja cada rama). **Rama restaurada** tras haberla quitado
  en la tarea de la ingesta.
- ⚠️ **`po_std` NO se suma** (`move_type = 'Orden de Compra'`): una orden no es una
  compra y su factura ya entra al EERR; sumar las dos **duplicaría** todo el consumo
  exterior. Queda en el DWH como maestro de órdenes (620 ítems, USD 246.225,79).
- **Números**: centro de costo resuelto en **69/159 líneas (43 %)** — y en las POs
  solo 251/620 ítems traen aeronave: el resto son POs escritas con 'STOCK'/'NEW', así
  que el hueco es del **dato de origen**, no del parser. `serv_date` en 145/159.
- **Verificado**: `dbt run` **PASS=20 ERROR=0**; en `moves` las facturas del exterior
  quedan en `account = '603301'` con importe **negativo** (compras) y `partner_doc`
  de Fenix/Textron **no** dispara ninguna regla de `aux_accounts_assignment`.
- **Publicado**: el 2026-10-07 se ejecutó la cadena completa (`static_data_asset`,
  `dbt_run`, `publish_dwh`). OJO: aquel día los 7 modelos secundarios eran **tablas**,
  así que quedaron en el DWH; el 2026-10-08 pasaron a `ephemeral` y esas copias
  (`dwh.fenix_std`…`dwh.textron_std`, `dwh.po_std`) **quedan congeladas** (ver la nota del
  BUG al inicio de este archivo). Lo que sí se refresca en cada publicación: `invoice_std`,
  `moves` y `partners`.


## ✅ FACTURAS DEL EXTERIOR: un parser por proveedor y 14 tablas nuevas (2026-10-07)
- **Pedido**: borrar la tabla única ``invoices_internacionales`` y rehacer la ingesta
  de ``static/INVOICE INTERNACIONALES`` con **un parser por subcarpeta** y **dos
  tablas por carpeta** (``*_header`` = una fila por documento, ``*_details`` = una
  fila por línea), con **todos los campos fieles al PDF** (el cliente lo revisa a
  mano). Las ÓRDENES DE COMPRA llevan **un solo parser** (sus seis subcarpetas
  comparten el formulario de Air Majoro).
- **Lo que hay en la carpeta**: 6 subcarpetas de facturas (``FENIX AEROSPACE``,
  ``JETSET``, ``KAL AIRPARTS``, ``PENIEL``, ``PRECISION HELIPARTS``, ``TEXTRON``) y
  ``ORDEN DE COMPRA`` con 6 subcarpetas (FENIX, JETSET, KAL AIRPARTS, PENIEL,
  PRECISION HELIPARTS (PAG), TEXTRON). Total: **14 tablas** (6×2 + 2), no 12: el
  recuento de 12 supone 5 proveedores, pero hay **6**.
- **Dónde está**:
  - ``parsers/invoices/_common.py``: utilidades (montos US/EU, fechas ISO, lectura
    de PDF, y la **rejilla por coordenadas** ``rejilla``/``alinear_x``/
    ``cabecera_y_datos``/``pares_tabla``/``find_value``/``block_value``).
  - Un módulo por carpeta: ``fenix.py``, ``jetset.py``, ``kal.py``, ``peniel.py``,
    ``precision.py``, ``textron.py`` y ``purchase_order.py`` (más
    ``_quantum.py``, la lógica común de JetSet y Peniel: usan el software Quantum
    Control). Cada uno expone ``parse_pdf(path) -> (header, details)`` y
    ``parse(carpeta) -> {"header": [...], "details": [...]}``.
  - Modelos peewee en ``models/static_invoice_<proveedor>.py`` (2 clases cada uno).
  - ``static_data_asset.py``: lista nueva ``INVOICE_SPECS`` (carpeta + parser +
    ``tablas``) y ``_procesar_facturas`` (reemplaza las DOS tablas de la carpeta).
  - ``resources/db_resource.py``: las 14 tablas registradas.
  - dbt: borrado ``purchs/from_reports/intl_purchs_std.sql`` y su ``UNION ALL`` en
    ``purchs_std.sql``; ``sources.yml`` declara la fuente ``invoices_extranjero``
    con las 14 tablas (para el cruce, que es el paso siguiente).
- **Cómo se leen los PDF** (importante): los formularios de Air Majoro (las POs) y
  las tablas que se envuelven se leen con la **rejilla por coordenadas**, no con el
  texto: pdfplumber devuelve el texto en el orden interno del PDF (las columnas
  numéricas antes que el texto de la izquierda) y las celdas vacías desplazarían un
  mapeo posicional (por eso ``alinear_x`` casa cada dato con su columna **por x**).
  Los montos se normalizan a número plano y las fechas a ISO.
- **Hallazgos que el cruce (siguiente paso) tiene que saber**:
  - En las **POs** la aeronave (``OB2180``/``B200``/``STOCK``) va unas veces en la
    columna ``CC`` y otras en ``AERONAVE``, y la condición (``NEW``/``OH``) en
    ``I/W`` o en ``CC``: hay que mirar las dos columnas.
  - Las tablas de las POs tienen **etiquetas distintas** según cómo se llenó
    (12 columnas fijas; a veces ``CONDITION`` en vez de ``CC``, o
    ``TYPE OF SERVICE``/``SERIAL``/``OBSERVATION``). Se guarda el valor en la
    columna que dice el PDF (``cc``, ``aeronave``, ``serial``, ``maintenance_note``…).
  - **PDFs mal ubicados** (avisar): en ``KAL AIRPARTS`` hay una **orden de compra**
    (``Kal- Aviation USA LLC  PO 702-2026.pdf``) y en ``ORDEN DE COMPRA/PENIEL`` hay
    una **factura** (``2.PENIEL I67568 PO 731.pdf``, es la I67568): sus parsers los
    ignoran (por eso las POs son 81 y no 82).
- **Ingesta verificada**: ``db.sqlite`` → headers 27/6/7/3/6/46/81, details
  61/6/13/5/9/65/620 = **955 filas** en total (76 en los headers de facturas, 158
  detalles de facturas, 81 + 620 de POs). Se **soltó la tabla vieja
  ``invoices_internacionales``** (si no, ``publish_dwh`` la seguiría publicando).
  ``pytest src/tests``: **640 passed, 1 skipped**; ``dbt run``: **PASS=12 ERROR=0**.
- ⚠️ **Efecto en el EERR**: al salir la rama ``intl_purchs_std`` de dbt, las compras
  del exterior (antes en ``603301``/CONSUMIBLES) **dejan de entrar en ``moves``**
  hasta que se haga el cruce con las tablas nuevas (siguiente paso pedido).
- ⚠️ **Lo que el cliente debe revisar** (él lo pidió así): los importes/descripciones
  de TEXTRON (dos precios: *List Price* y *Unit Price* — se guarda el **Unit Price**;
  el mapeo es posicional contando desde el final de la fila) y los ítems envueltos
  de KAL (los dos últimos importes antes del ítem siguiente son unit/amount).


## ✅ Indicador GALONES POR HORA DE VUELO (2026-10-06)
- **Pedido del cliente**: galones consumidos ÷ horas voladas, **por mes y por aeronave**, con el
  cruce hecho en **dbt** en una tabla nueva `gallons_per_flight_hour` (5 columnas: `mes`,
  `aeronave`, `horas`, `galones` y `galones_por_hora`) y mostrada **debajo de "Costo por
  proveedor"** en la página de Combustible.
- **Macro nuevo** `src/dbt/macros/normalize_registration.sql`: la matrícula "pelada"
  ('OB-1919-P' -> '1919', 'OB 2209' -> '2209'). Acepta **solo** 3-4 dígitos pelados (los CC del
  combustible) o `[0O]B` + 3-4 dígitos (matrícula del reporte de vuelos, con sufijo ignorado);
  cualquier otra cosa ('SAETA', '', '20920') -> NULL. Ojo: un `regexp_extract` suelto de los
  primeros dígitos atribuiría mal un centro de costo de 5 cifras.
- **Modelo dbt** `src/dbt/models/gallons_per_flight_hour.sql`: galones de `moves`
  (`account = '603201'`, el CC es la matrícula, fecha `doc_date`) **FULL OUTER JOIN** horas de
  `flight_reports` (fecha `fecha_vuelo`) por (mes × aeronave) + **INNER JOIN** a
  `static_airplanes`: así se cae solo el combustible cuyo CC no es una aeronave (2000, 2190,
  2056, 2222, los vacíos y los anticipos de TERPEL). `galones_por_hora =
  round(galones / nullif(horas, 0), 2)`.
- **Publicado**: `dwh.gallons_per_flight_hour` (**82 filas**, 10 aeronaves × 10 meses, 236.264,8
  galones y 3.852,7 horas). El publish lo coge automáticamente (recorre las tablas del DuckDB);
  los totales cuadran con `dwh.moves` (solo aviones del maestro) y con `dwh.flight_reports`.
- **Página** (`dashboardaim/pages/combustible.md`): sección `## Galones por hora de vuelo` al
  final, **sin** texto explicativo y **sin** gráfico (lo pidió así el cliente): tabla con las
  **aeronaves en filas** (dimensión), los **meses en columnas** (pivot) y **solo
  `galones_por_hora`** como valor. Filtra por año y por el desplegable de centro de costo (en
  combustible son las aeronaves). `evidence validate`: 0 errores, 32 avisos (el baseline).
- **Cómo se lee**: `galones_por_hora` en blanco = la aeronave tuvo facturas pero **0 horas** ese
  mes; `0.00` = voló pero **sin factura** de combustible. Sin columna "Total" a propósito (una
  suma de ratios no significa nada: el ratio de un periodo se saca dividiendo los galones entre
  las horas de ese periodo).
- **Nota**: se escribió un test del modelo y se **borró** a petición del usuario: este indicador
  no tiene test nuevo.


## ✅ Maestro de centros de costo RENOMBRADO: unidades de negocio y CC desde el maestro (2026-10-06)
- **Pedido**: en la página de **Gastos de Personal** la **unidad de negocio** y el **centro de costo**
  deben salir del maestro `dwh_static_cost_centers` por sus campos **`unidad_negocio`** y
  **`descripcion`** (**nada hardcodeado**), y **si el centro de costo de la planilla no está en el
  maestro se ignora** (no entra en la vista). Además: **reparar todo lo que se rompió** por el
  **renombrado de columnas** del maestro.
- **CSV nuevo** (`static/dwh_static_cost_centers.csv`, 29 filas): `cc,code,description` ->
  **`codigo,abreviatura,descripcion,grupo,unidad_negocio`**. `codigo` = el código que traen la planilla y
  `moves` ('101', '200', 'OPE-NAZCA'…); `abreviatura` = la clave corta ('1919' nº de aeronave, 'ADM-PCL',
  'OMA'); `descripcion` = la etiqueta ('OB1919'…); y trae la **`unidad_negocio` ya resuelta** (NAZCA,
  SELVA, MEDEVAC, Costo de Ventas Otros, Gasto de administración/ventas/financiero/operación). Antes los
  `OPE-*`/`INDIRECTOS` tenían `NOAPLICA` en `code` y las aeronaves `COSTO_VENTAS` en `description`.
- **⚠️ El CSV venía en Latin-1** (export de LibreOffice) y `parse_csv` lee `utf-8-sig`: el asset moría con
  `UnicodeDecodeError: 0xf3` ('ó' de 'administración'). **Se convirtió el fichero a UTF-8** (sin BOM, `\n`).
  Si vuelve a pasar: `bytes.decode('cp1252')` + reescritura en UTF-8.
- **dbt** (sin nada hardcodeado):
  - `models/static/static_cost_centers.sql` copia las 5 columnas nuevas.
  - `models/static/static_payroll.sql`: borrado el `CASE` (aeronaves `static_airplanes.business_unit`/
    `base` + códigos de gasto) y los 4 literales ('AEROLINEA VIVE PERU', 'EJERCITO PERUANO', …). Ahora
    `agregado_unidad_de_negocio = c.unidad_negocio` y `agregado_centro_de_costo = c.descripcion` (CTE
    `centros_de_costo` con `min(…) group by codigo`, descartando `NOAPLICA`) y **INNER JOIN** por
    `codigo = ccosto_code`: lo que **no** está en el maestro **no entra** (cayeron las 4 filas del `931`).
    Ya no se cruza `static_airplanes` en la planilla.
- **Efecto** (`static_payroll`: 2.349 -> **2.345** filas). Unidades 2026: Gasto de administración 57 ·
  **Costo de Ventas Otros 48** (antes '(sin asignar)' 51: OMA 45 + OB1921) · MEDEVAC 21 · NAZCA 16 ·
  Gasto de ventas 14 · **SELVA 11** (el ccosto **104 = OB1921** pasó a 'Costo de Ventas Otros') ·
  **NO IDENTIFICADO 6** (ccosto **113**, que el maestro define así). Personas y costo totales
  (147 · 6.021.133) **idénticos**.
- **Roto y reparado por el renombrado**:
  - `src/assets/static_data_asset/models/static_dwh_cost_centers.py` (peewee): campos nuevos. La tabla de
    `db.sqlite` **tenía el esquema viejo** -> se soltó y se re-materializó con la maquinaria del propio
    asset (`parse_csv` + `StaticDataSqliteResource.replace_all`): 29 filas, 5 columnas.
  - **Dashboard** (`cc`->`abreviatura`, `description`->`descripcion`, `code`->`codigo`) en
    `pages/aterrizajes.md`, `pages/ventas.md`, `pages/costos-por-moneda.md` y `pages/estado-resultados.md`.
    Efecto colateral **mejor**: las etiquetas de CC de aeronave pasan de `COSTO_VENTAS · 2092` (el
    `description` viejo era 'COSTO_VENTAS') a **`OB2092 · 2092`**.
  - **`dwh.newview`** (vista creada a mano en el DWH) resolvía `cost_center_codigo` con `scc.code`/`scc.cc`:
    se rehízo con `CREATE OR REPLACE VIEW` -> `scc.codigo`/`scc.abreviatura` (62.216 filas antes y después)
    y, ya sin dependencias, se **soltaron** las columnas viejas `cc`, `code`, `description` que el publish
    había dejado en NULL. `dwh.static_cost_centers` queda con las **5** columnas nuevas.
- **Validado**: `dbt run` **PASS=11**; publish OK (11 tablas, **137.725** filas); las 5 páginas del
  dashboard cargan con **0 errores HTTP** (`/personal`, `/estado-resultados`, `/aterrizajes`, `/ventas`,
  `/costos-por-moneda`); `pytest src/tests` **sin fallos** (**654 passed**). Los **3 tests** que leían el SQL
  del EERR (`docs/estado_resultados*.sql`, borrados del repo a propósito) se **retiraron** (con nota: ese
  SQL usaba `scc.code`/`scc.cc`); sus otros 3 tests (el contrato de las pseudo-cuentas MEDIDA del maestro)
  siguen pasando, ya en `test_estado_resultados_master_accounts.py`.
- **Pendiente/avisos**: (a) `static/dwh_static_airplanes.csv` **también** cambió (1921 `100LL` ->
  `TURBO A1-JET`, fuera `1630`) pero `db.sqlite` **no se re-ingiró** (solo se pidió el de centros de
  costo): el maestro de aeronaves publicado sigue con los valores viejos. (b) DBeaver tenía el DuckDB
  abierto: se **aparcó** el fichero (`analytics_poc.duckdb.dbeaver-lock`) y `dbt run` creó el canónico de
  cero. (c) El ccosto `113` sale como `NO IDENTIFICADO` en Gastos de Personal (así lo define el maestro).


## ✅ `serv_desc` de COMBUSTIBLE estandarizado por DESCRIPCIÓN + `NO IDENTIFICADO` (2026-10-06)
- **Pedido**: en la cuenta de combustibles (**603201**) estandarizar `serv_desc`: si la descripción
  trae `100` -> **`100LL`**; cualquier otra -> **`TURBO JET A1`**. Y los que tengan un **centro de
  costo que NO esté en `static_airplanes`** -> **`NO IDENTIFICADO`**. **Borrar cualquier otra forma
  de asignación** (la anterior, por aeronave) y todo **a nivel de dbt**.
- **Dónde**: `src/dbt/models/moves.sql`. El cuerpo (26 columnas) pasó a ser el CTE `mv_con_cc` y el
  `SELECT` final hace `SELECT mv.* REPLACE (CASE … END AS serv_desc)`. Va en `moves` y **no** en
  `purchs_std` porque la regla necesita el **centro de costo FINAL**: el override del proveedor
  (`aux_cost_centers_override`) se aplica recién en `moves` (9 filas de TERPEL/ÍCARO tenían el CC
  manglado —`OB20…`— y quedan como `2092`/`2104`/`2209`/`2221`: con la regla en `purchs_std` esas 9
  filas caían mal en `NO IDENTIFICADO`).
- **Regla (orden de ramas)**: `account <> '603201'` -> intacto · anticipos de TERPEL
  (`%PAGO ADELANTADO%` / `%PAGOS ADELANTADOS%`, partner `20259880603`) -> intacto · sin descripción
  -> `NO IDENTIFICADO` · CC no vacío y **fuera** del maestro -> `NO IDENTIFICADO` ·
  `instr(serv_desc,'100') > 0` -> `100LL` · resto -> `TURBO JET A1`.
- **⚠️ Por qué los anticipos se conservan**: `dwh.vista_reporte_gerencial` (Power BI) excluye esas
  13 filas de TERPEL por el **texto** (`serv_desc ~~* '%PAGO ADELANTADO%' OR … '%PAGOS ADELANTADOS%'`).
  Reescribirlo con una etiqueta de combustible las haría **reaparecer** en la vista. El override de
  CC también se probó en `vista_reporte_gerencial`: la vista **no se tocó**.
- **Efecto medido** (`dwh.moves`, 603201 = 2.789 filas): `TURBO JET A1` **1.545** · `100LL`
  **1.224** · anticipos **13** · `NO IDENTIFICADO` **7** (`2000` 2, `2190` 2, `2056` 1, `2222` 1 y 1
  sin descripción). Cambios vs. la regla anterior (por aeronave): 7 filas de `OB-1921` (descripción
  `TURBO A-1` de CEP) pasan de `100LL` a `TURBO JET A1` y 2 filas de `2221` (descripción
  `AV GAS 100LL`) pasan de `TURBO A1-JET` a `100LL`: **manda la descripción**, que es lo pedido.
  Nada más cambió: `moves` 92.600 filas, otras cuentas 89.811 filas con la misma suma de longitudes
  de `serv_desc`, `vista_reporte_gerencial` 73.356 filas y los KPI de combustible 2026 idénticos
  (240.655,8 gal · 4.024.197,47 S/ · 4,92 US$/gal).
- **Etiquetas retiradas**: ya NO se usa el `fuel` del maestro (`TURBO A1-JET`, `1921 = 100LL`, etc.)
  ni la lista de aeronaves AVGAS. `extract_cost_center(cc.aeronave)` queda solo para el **centro de
  costo**.
- **Dashboard**: `pages/combustible.md` ya NO deduce `tipo_combustible` con un `CASE centro_de_costo`
  (se borraron los 6 bloques, incluido el `NO CORRESPONDE`); ahora es
  `coalesce(nullif(trim(descripcion_servicio),''), 'NO IDENTIFICADO')`, con el valor **`TURBO JET A1`**
  (antes `TURBO JET A1` solo en el CASE del dashboard y `TURBO A1-JET` en la data).
- **Frontend (2026-10-06, después de publicar)**: las filas `NO IDENTIFICADO` **no se muestran** en la
  página: el filtro `coalesce(descripcion_servicio,'') <> 'NO IDENTIFICADO'` va en las **10 consultas**
  (incluidas las 5 `dim_*`, para que el desplegable de tipo no lo ofrezca). Efecto: las 4 series/KPI de
  la página bajan de 2.776 a **2.769 facturas**, de 240.655,8 a **240.199,8 galones** y de 4.024.197,47
  a **4.012.411,55 S/**. Se quitaron también los indicadores **"Costo promedio ponderado (US$ por
  galón)"** y **"Proveedores"** del Resumen (quedan Galones · Costo (S/) · Facturas) y sus dos medidas
  del `select` de `kpis`. La **sección/gráfico** "Costo promedio ponderado" sigue (solo se pidió el
  indicador). `evidence validate`: errorCount 0, warningCount **32** (2 menos que el baseline de 34).
- **Frontend (2026-10-06, 2)**: en `pages/personal.md` (Gastos de Personal) se quitó el párrafo
  introductorio que explicaba la fuente (el *excel de planilla* de `dwh.static_payroll`) y en su lugar
  quedó, **en cursiva** (texto llano, no título) bajo el `# Gastos de Personal`, la **fórmula del costo**:
  _«Costo = total ingresos + total aportes»_ (sin más explicación: la fuente y el conteo por DNI no se
  mencionan en la página).
- **Frontend (2026-10-06, 3)**: el segmentador de **Oficina** se sustituyó por uno de **Empresa**
  (`dim_empresas`), derivada del **régimen** de la planilla: **`RG` -> Air Majoro**, **`RMT` -> Air Majoro
  Selva** (y `'(sin régimen)'` para las 2 filas de 2026 sin régimen, 1 persona; si se prefiere, se les da
  otra etiqueta o se excluyen). El `CASE` va en el `dim_empresas` y en los **4** filtros de la página (ya
  no existe `dim_oficinas` ni `{{ oficina }}`; la columna `oficina` sigue en la tabla, sin usar).
  Verificado: sin filtro 147 · 6.021.133; `Air Majoro` 117 · 5.467.662; `Air Majoro Selva` 32 · 542.457;
  las dos 147 · 6.010.119 (la diferencia con el total son las 2 filas sin régimen: 11.014).
- **⚠️ Parámetro de URL de un dropdown de texto**: `/personal?empresa=Air Majoro` da **500** (Evidence
  interpola el texto sin comillas); la forma que sí funciona es el **array JSON**:
  `/personal?empresa=["Air Majoro"]`. **No es del cambio**: `?area=MEDICA` se comporta igual (es
  comportamiento de Evidence con parámetros de texto). Desde la UI funciona siempre.
- **Frontend (2026-10-06, 4)**: en `pages/ventas.md` se quitó el gráfico **«Ventas por unidad de negocio
  (S/)»** (el `horizontal_bar_chart` con la query `ventas_unidad`, que se borró: no la usaba nadie más) y
  se deshizo el `{% row %}`: queda solo el **treemap «Ventas por aeropuerto (S/)»**, ahora a todo el
  ancho (se entiende mejor). El resto de la página (Resumen, «Ventas por mes (S/)», «Detalle mensual») no
  cambió.
- **Validado**: `pytest src/tests/test_combustible_serv_desc_model.py` 4 passed (contrato reescrito:
  la regla vive en `moves`, los anticipos se conservan, y `purchs_std` ya no menciona etiquetas de
  combustible); `dbt run` **PASS=11**; `publish_dwh` OK (12 tablas, 137.737 filas) al DWH
  (`51.38.243.200:5447/dwh_aim_db`, esquema `dwh`).
- **⚠️ DuckDB bloqueado por DBeaver**: `dbt run`/publish fallan con
  `IO Error: Could not set lock on file "analytics_poc.duckdb"` mientras DBeaver tenga abierta la
  conexión DuckDB; hay que cerrarla (el propio `publish_resource.py` lo avisa).

## ✅ `serv_desc` estandarizado en compras de COMBUSTIBLE por aeronave (2026-09-30) — ⛔ SUSTITUIDO
- **Pedido**: estandarizar la descripción del servicio de los **combustibles** según el tipo de
  aeronave; si el comprobante **NO trae aeronave**, dejar el `serv_desc` original. Solo afecta a
  combustibles.
- **Cambio (1 bloque)**: `src/dbt/models/purchs/purchs_std.sql`, CTE `purchases_cc` (donde `cc` =
  `cost_centers` está en scope), dentro del `REPLACE (...)`:
  `CASE WHEN NULLIF(cc.aeronave,'') IS NULL THEN p.serv_desc WHEN extract_cost_center(cc.aeronave)
  IN ('1919','1921','2180','1929') THEN '100LL' ELSE 'TURBO A1-JET' END AS serv_desc`.
- **Por qué solo combustibles**: `cost_centers.aeronave` **únicamente** se rellena para los 4
  proveedores de combustible (PETROPERÚ, CEP, ÍCARO, TERPEL → account **603201**), así que la regla
  no puede tocar otra cuenta.
- **Etiquetas**: las del maestro `static/dwh_static_airplanes.csv` (`100LL` para
  1919/2180/1921/1929; `TURBO A1-JET` para el resto). **`1921`** se añadió a `100LL` porque la DATA
  de CEP de ese avión trae `AV GAS 100LL` (y el maestro ya lo daba como `100LL`).
- **⚠️ Mal etiquetado de CEP (no exclusivo de 1921)**: el avión `OB-1921` (CESSNA402C, de pistón)
  tiene 11 facturas CEP de 2026, **cada una con 1 sola aeronave y 1 sola línea**: 4 con
  `AV GAS 100LL` (~11.22/gal) y 7 con `TURBO A-1` (~3.43–5.93/gal, precio de JET). **No es
  artefacto del JOIN**: 0 `id_file` de CEP con más de un cost center y las 1.399 facturas CEP
  tienen 1 detalle. **Cross-check por proveedor de los 4 aviones AVGAS del maestro**
  (solo los 3 SIRÉ comparten `sire_purchs_details`): `1919` CEP `AV GAS 100LL` ×509; `1929` CEP
  `AV GAS 100LL` ×353; `2180` CEP `AV GAS 100LL` ×161 **+ `TURBO A-1` ×1** e ÍCARO
  `AVGAS 100LL -` ×182; `1921` CEP `AV GAS 100LL` ×4 + `TURBO A-1` ×7. ⇒ El `TURBO A-1` de CEP
  es **etiquetado inconsistente del proveedor** (ya ocurre en `2180`, cuyo AVGAS corrobora ÍCARO),
  así que **1921 = `100LL`** queda sustentado. `1921`, `1919` y `1929` compran **solo a CEP**
  (PETROPERÚ/ÍCARO/TERPEL = 0 filas); `2180` a CEP + ÍCARO. No hay colisión de `cost_center`:
  `1921` es el avión en las 522 filas (solo 11 son combustible).
- **Validación**: `dbt parse`/`compile` OK; `dbt run` completo en un DuckDB **desechable**
  (`/tmp/valrun`, sin tocar `analytics_poc.duckdb`) **PASS=9**, `moves` 91.292 filas; en `603201`:
  `100LL` 1.217 / `TURBO A1-JET` 1.434 / 106 sin aeronave (original); **0** filas de otra cuenta con
  etiqueta estandarizada. Test-contrato nuevo `src/tests/test_combustible_serv_desc_model.py`
  (8 passed junto a los de `test_intl_purchs_std_model.py`).


## ✅ Filas MEDIDA del EERR en el maestro de CUENTAS (query sin `UNION`) — 2026-09-28
- **Pedido del usuario**: «pon esas filas en la tabla de account_groups». Aclaración: las 2 filas
  MEDIDA **ya están** en `static/dwh_static_master_account_groups.csv` (`tipo = MEDIDA`: UTILIDAD
  BRUTA orden 3 y RESULTADO OPERATIVO orden 9). Añadirlas ahí **no sirve**: esa tabla es solo
  **etiqueta** (tipo/grupo/orden) y da **una fila por GRUPO**; el reporte es cuenta × mes × CC y el
  importe es un **acumulado**. Lo que faltaba era una **fila-fuente** en el grid, y el grid se
  genera desde el maestro de **CUENTAS** (producto cartesiano con periodos y centros de costo).
- **Hecho**: 2 **pseudo-cuentas** en `static/dwh_static_master_accounts.csv` (99 → **101** filas):
  `codigo_pcge = grupo = cuenta = UTILIDAD BRUTA` / `RESULTADO OPERATIVO`, `cuenta_pcge` vacío y
  `comentario` = «NO es cuenta PCGE: fila-fuente del subtotal MEDIDA…». La `cuenta` es
  **exactamente** el nombre del grupo MEDIDA, así que la descripción del reporte sale idéntica.
- **Query nueva SIN `UNION`**: `docs/estado_resultados_sin_union.sql` → 1 solo `SELECT`
  + 3 subconsultas (periodos, centros de costo, por_cuenta). La fila MEDIDA se reconoce con
  `g.tipo = 'MEDIDA'` (ya no hace falta el `UNION`) y su importe es la ventana acumulada.
- **Validado** (PostgreSQL `dwh_aim_db`): **57.267 filas** y diff fila a fila en las **13 columnas**
  = **0 de más / 0 de menos** contra la oficial; y ~3× más rápida (**1,29 s vs 4,0 s**). Las 3
  variantes (`con UNION`, `sin WITH`, `sin UNION`) dan el MISMO multiconjunto de 57.267 filas
  (comprobado insertando las pseudo-cuentas **dentro de una transacción con ROLLBACK**).
- **⚠️ Ojo / arreglado**: con el maestro nuevo, `docs/estado_resultados.sql` y
  `..._sin_with.sql` **duplicaban** los subtotales (58.401 filas, porque las pseudo-cuentas entraban
  también como filas CUENTA). Se arreglaron los dos: su `catalogo` ahora EXCLUYE las pseudo-cuentas
  (`WHERE gm.tipo IS DISTINCT FROM 'MEDIDA'`), así que funcionan con el maestro viejo **y** con el
  nuevo (comprobado: idénticas).
- **Test de contrato**: `src/tests/test_estado_resultados_master_accounts.py` (hoy 3 tests: los que
  leían el SQL se retiraron con él) fija que **cada** grupo `tipo = 'MEDIDA'` tenga su pseudo-cuenta
  en el maestro.
- **Pendiente del usuario**: re-ejecutar el pipeline (asset `static_data_asset` → `dbt run` →
  `publish_dwh`) para publicar las **101** cuentas en `dwh.static_master_accounts`. Hasta entonces
  la query `sin_union` daría 56.133 filas (sin los 2 subtotales).
- **Descartado**: usar `static_master_account_groups` como fila-fuente (grano de GRUPO, no de
  cuenta). Alternativa «ideal» no hecha: un CSV nuevo p.ej. `dwh_static_eerr_rows.csv` con el
  catálogo de filas (cuentas + subtotales + orden) y así no ensuciar el maestro PCGE.

- **Columna nueva del CC (2026-09-28, pedido «los códigos nada más como una columna más»)**: el
  EERR ya traía `cost_center` = código crudo de `moves` (`2092`, `110`, `003-`, `(SIN CC)`…); se
  añadió **`cost_center_codigo`** = el MISMO CC con el código del maestro `dwh.static_cost_centers`
  (cruce por `code` y, si no, por `cc`, con subconsulta escalar `LIMIT 1` para no duplicar filas; si
  el CC no está en el maestro repite el de origen, **0 NULLs**). En los **3** .sql (oficial, sin
  `WITH`, sin `UNION`); el reporte pasa de 13 a **14 columnas** y las 3 variantes siguen dando
  **0 diferencias** (57.267 filas). Mapeo real: `1919`→`101`, `2092`→`112`, `2200`→`106`,
  `OPE-NAZCA`→`NOAPLICA`, y los que no están en el maestro (`003-`, `0B-2`, `113`, `2000`, `2190`,
  `2201`, `2222`, `2365`, `931`, `(SIN CC)`) repiten su código. La `sin_union` sube a ~2 s por la
  subconsulta (antes 1,3 s). Test extra en `src/tests/test_estado_resultados_master_accounts.py` (6 en
  total entonces). Si algún día se quiere el **nombre** en vez del código, es cambiar `scc.code` por
  `scc.description` en esa subconsulta.

## ✅ EERR como QUERY (sin carpeta `dashboard` ni tabla) — 2026-09-28
- **Decisión del usuario**: se **elimina** el modelo dbt `dashboard/estado_resultados` (y su
  carpeta `src/dbt/models/dashboard/`) y la tabla materializada `dwh.estado_resultados`. En su
  lugar hay **UNA sola query** para ejecutar en el BI:
  `docs/estado_resultados.sql`.
- **Tabla borrada en 2 sitios** (para que `publish_dwh` no la resucite): `DROP TABLE
  dwh.estado_resultados` en PostgreSQL y `DROP TABLE estado_resultados` en
  `analytics_poc.duckdb`. El publish copia TODAS las tablas base del DuckDB, así que si
  quedaba la del DuckDB la volvía a publicar con datos viejos.
- **La query lee solo tablas base ya publicadas** (schema `dwh`): `moves`, `calendar`,
  `static_master_accounts` y `static_master_account_groups`. Es **una sola sentencia SELECT**
  (con CTEs), sin tablas intermedias ni dependencias de dbt.
- **Cambio pedido en el mes**: ahora `mes` sale **con cero a la izquierda** (`LPAD(mes::TEXT, 2,
  '0')`): `'01. Enero'` … `'12. Diciembre'`, para que el BI lo ordene bien por texto.
  `mes_num` sigue siendo el entero (1..12) para ordenar/filtrar por número.
- **Validada contra el DWH real** (PostgreSQL `dwh_aim_db`): **57.267 filas**, 27 centros de
  costo, 11 grupos, 2025-2026; VENTAS 7xxx = **36.022.713,70** (idéntico al modelo dbt);
  meses ordenados correctamente como texto. Diff fila a fila contra la tabla antigua:
  **solo 8 filas con ±0,0001** en el 4.º decimal (redondeo DOUBLE exchange-rate distinto entre
  DuckDB y Postgres); sin impacto.
- **Nota**: la query no es un modelo dbt (`dbt run` ya no la materializa). Si cambia la lógica
  del EERR hay que editar `docs/estado_resultados.sql` y volver a pegarla en el BI.
- **Variante SIN `WITH`** (pregunta del usuario, 2026-09-28): existe también
  `docs/estado_resultados_sin_with.sql`, con las CTEs convertidas en subconsultas
  anidadas. Resultado **idéntico** (57.267 filas, 0 diferencias en ambos sentidos) pero **~50% más
  lenta** (1,39 s vs 0,91 s) porque `dwh.moves` se lee 4 veces en vez de 1. La copia buena/oficial
  sigue siendo la de `WITH`.
- **Variantes "un solo SELECT"** (`docs/estado_resultados_simple.sql`, 2026-09-28): a
  petición del usuario ("una query simple, sin `WITH`"). Se probó y **no es posible reproducir el
  reporte exacto en un único `SELECT`**: el oficial tiene 57.267 filas porque **añade** filas que no
  existen en las tablas base → (a) 2 filas por mes/CC `tipo='MEDIDA'` (UTILIDAD BRUTA, RESULTADO
  OPERATIVO) fabricadas con `UNION` desde `static_master_account_groups`, y (b) **54.810 filas con
  importe 0** (cuentas sin movimiento × periodos × CC) del producto cartesiano. Un `GROUP BY` sólo
  agrega filas existentes; un `LEFT JOIN` no inventa filas (y cruzar `moves` para inventarlas
  multiplica los `SUM`). El archivo nuevo trae 2 opciones ya validadas:
  - **OPCIÓN 1** (detalle por cuenta, sin MEDIDA): **2.381 filas**, 1 solo SELECT, suma idéntica al
    oficial (1 fila difiere 0,0001 por redondeo DOUBLE).
  - **OPCIÓN 2** (por grupo, MEDIDA como columna `acumulado` con ventana sobre `SUM(SUM(...))`):
    **723 filas**; el `acumulado` reproduce **exacto** las filas MEDIDA del oficial (p.ej. CC `110`
    ene-2025: UTILIDAD BRUTA `-109187.6600`, RESULTADO OPERATIVO `-119597.1800`).
  - Datos útiles: `static_master_account_groups.orden` = VENTAS 1, COSTO DE VENTAS 2, UTILIDAD
    BRUTA 3 (MEDIDA), 4..8 gastos, RESULTADO OPERATIVO 9 (MEDIDA), 10-11; sin `orden` duplicados.
    El maestro tiene 99 cuentas + **2 pseudo-cuentas** de subtotales desde 2026-09-28 = 101
    (49 cuentas sin ningún movimiento) y **0 cuentas de `moves` fuera del
    maestro** (el CTE `fuera_maestro` hoy no filtra nada, sirve de red de seguridad).
- **Descartado**: sacar el mes con `LEFT JOIN dwh.calendar` (`month_name`). Motivos: (1)
  `calendar.month_name` está en **inglés** ("January"…"December"); (2) el `calendar` solo cubre
  `2025-10-06`→`2026-09-24` mientras que `moves` tiene datos desde `2025-01-01`, así que los meses
  ene–sep 2025 (14.291 filas) se quedarían **con mes NULL**. Por eso el mes se deriva con
  `EXTRACT(MONTH ...)` + `CASE` en español. **Descartado** también: sacar el orden de cuentas del
  maestro, porque `static_master_accounts` **no tiene columna de orden** (solo `codigo_pcge`,
  `grupo`, `cuenta`, `cuenta_pcge`, `comentario`); el orden de grupo sí viene de
  `static_master_account_groups.orden` (join directo) y el de cuenta se calcula con
  `ROW_NUMBER() ... ORDER BY codigo_pcge`.

## ✅ Facturas de proveedores del EXTERIOR en `moves` (2026-09-25)
- **Objetivo**: que las facturas de `static/INVOICE INTERNACIONALES/` (Fenix, JetSet,
  Kal, Textron y Precision Heliparts/PAG) entren a `moves` como **compras**, con el
  **centro de costo** y la **fecha de servicio** tomados de la **orden de compra**.
- **Formato**: son PDFs con texto nativo (sin OCR). Cada proveedor tiene su layout,
  así que se resolvió con **regex por líneas** (nada de coordenadas X) siguiendo el
  patrón de CORPAC/CEP/Terpel. NO se usó ninguna API de IA.
- **Ingesta** (nueva):
  - Paquete `src/assets/static_data_asset/parsers/invoices/`: un módulo por formato
    (`fenix.py`, `jetset.py`, `kal.py`, `textron.py`, `precision.py`), `_common.py`
    (montos US/EU, fechas, Nº de PO) y `purchase_order.py` (centro de costo de la PO).
    La orquestación está en `parsers/invoices/__init__.py`.
  - Modelo peewee `models/invoices_internacionales.py` (tabla homónima), registrado en
    `resources/db_resource.py`.
  - `static_data_asset.py`: nuevo spec de **CARPETA** (`"patron": "INVOICE
    INTERNACIONALES"`, `"carpeta": True`); `_procesar_spec` ahora soporta specs
    multi-PDF (antes solo cogía `archivos[0]`).
- **Centro de costo**: se cruza por **P/N factura ↔ P/N PO**. Si un ítem de la PO
  resuelve a **varios** CC (p. ej. `OB1919/OB1929`), la línea se parte en **una fila
  por CC** repartiendo `qnt`/`amount` (el total del documento no cambia). Si no hay PO
  o el P/N no está, queda **NULL** (best-effort, no bloquea). El texto original va en
  `cost_center_raw`.
- **Mapeo**: `unit_price` = valor unitario **sin IGV** (en Textron el *Unit Price*, no
  el *List Price*); `qnt` = quantity; `amnt_taxable` = `unit_price × qnt`;
  `amnt_taxes` = 0; `doc_date` = fecha de factura; `serv_date` = **fecha de la PO**;
  `cost_center` = aeronave de la PO; `currency` = USD; `company` = Air Majoro.
- **dbt**: nuevo `src/dbt/models/purchs/from_reports/intl_purchs_std.sql` (efímero) +
  `UNION ALL` en `purchs_std.sql` + source `invoices_intl` en `sources.yml`.
- **Cuenta nueva**: `603303 = INVOICES INTERNACIONALES` (COSTO DE VENTAS) en
  `static/dwh_static_master_accounts.csv`. Se **NO** tocó
  `static/static_aux_accounts_assignment.csv` (decisión del usuario): la cuenta la fija
  la rama dbt.
- **Arreglo del duplicado `684102`**: `REPUESTOS` se **queda** con `684102` (lo usan dos
  proveedores en la aux de repuestos, que NO se tocó) y la fila duplicada de
  **DEPRECIACION MAQUINARIAS Y EQUIPOS DE EXPLOTACION** se movió a `684106` (libre).
  El maestro queda sin códigos duplicados.
- **Validación**: parser sobre la carpeta real → **137 filas**, 43 documentos, 62 con
  centro de costo, 121 con `serv_date`; ingesta idempotente en SQLite de prueba;
  `dbt parse` + `dbt compile --select intl_purchs_std` OK; suite **609 passed**.
- **PUBLICADO (2026-09-25)**: `static_data_asset` (137 filas a `db.sqlite`) → `dbt_run`
  (**PASS=9**, incluido `moves`) → `publish_dwh` (**10 tablas, 142.548 filas** al schema
  `dwh`). En `dwh.moves`: cuenta **603303** con **137 filas / 43 documentos / USD
  545.897,61**; con centro de costo 62 filas (1919, 1929, 2092, 2104, 2180, 2200, 2209,
  2221, 2239) y 75 con `cost_center` NULL (POs sin aeronave o facturas sin PO).
- **Limitaciones conocidas** (best-effort): faltan PDFs de PO para algunas facturas
  (p. ej. PO 830/832) → sin `serv_date`/`cost_center`; POs con `STOCK` en la columna
  AERONAVE → sin centro de costo; algunas líneas de PO sin Nº de ítem recuperadas por
  heurística; en Textron *Description 1/2* llegan concatenadas.

## ✅ Ventas del reporte estático "1.- REPORTE DE VENTAS" en `moves` (2026-09-25)
- **Objetivo**: que las ventas del libro estático `static/1.- REPORTE DE VENTAS AL
  19.092026.xlsx` (44 hojas, una por mes y empresa) entren al pipeline de ventas
  (`sales_std` → `moves` → `publish_dwh`), **sin duplicar documentos** y en una cuenta
  **nueva** «VENTAS SELVA».
- **Ingesta** (ya existía): `parse_sales_selva` + modelo `SalesSelva` (tabla
  `sales_selva`) + entrada en `STATIC_SPECS` del asset `static_data_asset`. Nada de la
  ingesta se cambió: el filtrado es a nivel dbt.
- **dbt**:
  - Nuevo `src/dbt/models/sales/from_reports/selva_sales_std.sql` (efímero): lee
    `sales_selva`, mapea al contrato de 26 columnas y **filtra en dbt** las filas que NO
    son ventas (`COBRANZA`, `PP VENTAS`, `PP CARGA` y filas sin documento). Deduplica
    **1 fila por (doc_serie, doc_number)**.
  - `src/dbt/models/sales/sales_std.sql`: 4.ª vía `selva` con anti-join por documento
    (ambulancia > SISA > SIRE > SELVA).
  - `src/dbt/models/sources.yml`: source `selva` → `sales_selva`.
- **Cuenta nueva**: `704106 = VENTAS SELVA` en `static/dwh_static_master_accounts.csv`
  (no choca con ninguna anterior; SISA usa 704102/704104/704105 y el maestro no los tenía).
- **Detalles de mapeo**: `doc_date`/`serv_date` normalizados (ISO y `DD.MM.YY`);
  `company` = Air Majoro Selva (hojas `SELVA...`) o Air Majoro (hojas `S.A...`);
  `cost_center` = matrícula de `AVION`; `amnt_taxable`/`amnt_taxes` = `TOTAL`/1.18;
  `currency` = `PEN`; `serv_org_airport`/`serv_dest_airport` = NULL (los códigos `DE`/`A`
  son de 2 letras y no están en la seed IATA de 3 letras).
- **Validación**: `sales_selva` ingerida (12.155 filas) + `dbt run` PASS=9. `moves` con
  **2.272** filas en `704106` (1.950 Air Majoro Selva + 322 Air Majoro), **0 documentos
  duplicados**, 0 filas sin documento y `static_master_accounts` con `704106`. Suite
  **588 passed** (se corrigieron los 2 tests obsoletos de `test_static_data_db_resource.py`,
  que usaban los nombres de tabla viejos `ambulancia_ventas_reports`/`lap_reports`/`planilla`).

## ✅ Aeropuertos de los proveedores de combustible en `moves` (2026-09-24)
- **Objetivo**: que las compras de **PETROPERÚ, CEP, ÍCARO y TERPEL** (los 4 proveedores
  con `account = 603201`, COMBUSTIBLES) salgan en `moves` con aeropuerto. Antes
  `serv_org_airport`/`serv_dest_airport` eran **NULL** en todas las compras SIRE.
- **Fuente por proveedor** (todo resuelto a `static_aux_airports.ubicacion`, NUNCA al
  texto "No es nomenclatura" de `obtener_aeropuerto`):
  - **PETROPERÚ** -> `from_sire_petroperu_cost_centers.aeropuerto` (última palabra del
    `DatoAdicional` código 31, p. ej. `Ucayali`); se cruza por `ubicacion` **o**
    `departamento` y gana el aeródromo con IATA (`Ucayali` -> `Pucallpa`).
  - **CEP** -> `from_email_cep_docs_headers.cod_del_cliente` (1ª columna de la factura del
    correo `fe.corporacion.energetico@gmail.com`: `<local>/<ICAO>`, p. ej. `NZA/SPZA`);
    se cruza por factura (`serie` + `correlativo` como entero) y se resuelve el ICAO.
  - **ÍCARO** -> `from_sire_icaro_cost_centers.texto_planta` (`PUCALLPA`, `CHICLAYO`...).
  - **TERPEL** -> `from_email_terpel_tickets_tickets.estacion` (origen, `LIM` -> `Callao`)
    y `destino` (destino del vuelo) como IATA.
- **Piezas**:
  - Nuevo macro `src/dbt/macros/aeropuerto_ubicacion.sql` (`icao` / `iata` / `nombre`).
  - `src/dbt/models/purchs/cost_centers.sql`: cada rama emite `aeropuerto` y
    `aeropuerto_destino` (la rama CEP cruza con las cabeceras del correo).
  - `src/dbt/models/purchs/purchs_std.sql`: `REPLACE` de `serv_org_airport` y
    `serv_dest_airport` con `COALESCE(cc.aeropuerto*, p.serv_*_airport)` (CORPAC/ADP/LAP
    conservan el suyo; ahí `cc` es NULL).
  - `src/assets/from_sire_files_assets/_common/db_resource.py`: **backfill** del aeropuerto
    de PETROPERÚ (el asset es append-only; un ZIP con filas y aeropuerto NULL se
    reprocesa una vez y se **actualiza** la fila, no se duplica).
  - `dbt_run` gana la dep `cep_docs_daily` (dbt lee `from_email_cep_docs_headers`).
- **Datos ya backfilleados en `db.sqlite`** (2026-09-24): columna `aeropuerto` añadida y
  45/45 filas de PETROPERÚ rellenas; `cep_docs_daily` corrido para **210 días** (0 fallos,
  1387 cabeceras). `analytics_poc.duckdb` **NO** se tocó (DBeaver lo tiene con lock): hay
  que relanzar `dbt run`/pipeline para publicar los aeropuertos.
- **Validación** (DuckDB de usar y tirar, `dbt run` PASS=9): `moves` sin duplicar filas
  (97.048, las mismas de antes) y aeropuertos -> PETROPERÚ 45/45, ÍCARO 458/458,
  CEP 1.369/1.376, TERPEL 699/802 org + 696 dest. **Todos** los valores son miembros de
  `static_aux_airports.ubicacion` (comprobado). Pendiente real: TERPEL 103 filas sin
  ticket (`o_entrega` sin match) y CEP 7 sin cabecera en el correo.
- **Tests**: 3 nuevos en `test_cost_centers_db_resource.py` (backfill), `test_dwh_assets.py`
  y `test_jobs.py` a 15 fuentes. Suite: **583 passed**, 2 failed **ajenos** (los de
  `sales_selva`/snapshots de `test_static_data_db_resource.py`).

## ✅ `sync_db.py` absorbido por `DwhPublishResource` (2026-09-23)
- **Una sola pieza**: todo el motor de publicación (mapeo de tipos, `duckdb_connect`,
  `duckdb_tables`/`duckdb_columns`, `pg_tables`/`pg_columns`, `sync_table`, `pg_params` y el
  CLI) vive ahora en
  `src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py`; **`sync_db.py`
  (raíz) se borró** (antes era el motor + CLI y el resource un envoltorio fino).
- **Simplificaciones**: se fue el **global `SCHEMA`** (y el hack `sync_db.SCHEMA = ...`; ahora
  el schema es un parámetro), el **round-trip por `argv`** (`dwh_argv()` + `sync_db.main`) y
  el `sys.path.insert(repo)` + `import sync_db` del resource. `publish()` devuelve **filas
  publicadas** (el asset lo pone en metadata como `rows_published`, en vez de `sync_db_args`).
- **Errores**: `DwhPublishError.codigo_salida` (1 = nada que publicar, 2 = DuckDB no
  disponible) → el CLI los mapea a exit codes y el resource los propaga como fallo del step.
- **CLI nuevo** (desde la raíz; `--schema` es nuevo):
  `python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --dry-run`
  (también `--only`, `--exclude`, `--recreate`, `--duckdb`).
- **Cambio de comportamiento** (1 línea): `PGPORT` por defecto pasa de **5000 a 5432** (el
  puerto estándar de PostgreSQL), que es lo que ya esperaba `test_pg_params_defaults`; el DWH
  real fija `PGPORT=5447` en `env/.env`.
- **Tests**: `src/tests/test_sync_db.py` se fusionó en `src/tests/test_dwh_publish_resource.py`
  (motor + resource) y `test_dwh_assets.py` se adaptó (ya no hay `dwh_argv`).
- **Docs**: README (pasos 6/7/8), `src/dbt/profiles.yml` (se fue un "PENDIENTE" ya obsoleto),
  comentarios de `models/moves.sql`, `models/static/*` y `macros/normalize_date.sql`,
  `run_pipeline.py`, `systemPatterns.md`, `techContext.md`, `projectbrief.md` y `glossary.md`.

## ✅ Reestructura: `definitions.py` a la RAÍZ y tests a `src/tests/` (2026-09-23)
- **Movidos con `git mv`** (historial intacto): `src/definitions.py` → **`definitions.py`**
  (raíz), `src/pyproject.toml` → **`pyproject.toml`** (es el `[tool.dagster]
  module_name = "definitions"`, y así `dagster dev` / el CLI se lanzan **desde la raíz**)
  y `tests/` → **`src/tests/`** (con `fixtures/` y `live_smoke.py`).
- **Código adaptado**: `definitions.py` añade **`src/`** al `sys.path` (antes añadía su propio
  dir) para `import assets...` / `import jobs`; `src/tests/conftest.py` calcula la raíz **3
  niveles** arriba y añade raíz + `src/`; `test_planilla_asset.py` y `test_run_pipeline.py`
  (ruta a `scripts/run_pipeline.py`) pasan a `parents[2]`; `live_smoke.py` añade raíz + `src/`.
- **Comandos** (todos desde la RAÍZ): `python -m dagster definitions validate`, `dagster dev`,
  `python -m dagster asset materialize -m definitions ...`; `dbt` sigue en `cd src/dbt`.
  `scripts/run_pipeline.py` y `scripts/marcar_assets_materializados.py` **no cambian** de uso
  (importan `definitions` con la raíz ya en `sys.path`).
- **Borrado**: `src/tests/test_cpe_details_resource.py` (importaba
  `DETAILS_RETRY_MAX_ATTEMPTS`, que ya no existe en `constants.py`; rompía la colección).
- **Validado 2026-09-23**: `dagster definitions validate` ✅ (19 assets / 7 jobs),
  `pytest` **509 passed** / 3 failed **ajenos al cambio** (los mismos que ya listaba
  `.pytest_cache/lastfailed`), `run_pipeline.py --dry-run` ✅ (5 runs) y
  `marcar_assets_materializados.py --dry-run` ✅ (19 assets).

## ✅ `ingest_emails`: descarga INCREMENTAL de Gmail (2026-09-18)
- **Duda del usuario**: el asset tardaba mucho y sospechaba que la tabla `emails` se
  *reemplazaba* en cada corrida.
- **Hallazgo 1 — el insert ya estaba bien**: `emails`/`email_attachments` se llenaban con
  `_existing_keys` + `_insert_new` (= append-only, **sin** `DELETE`/`UPDATE`; el `_replace`
  de la base no lo usa ningún asset de correo). Lo que engañaba era el **nombre**
  `upsert_emails`, así que se renombró a **`append_emails`** / **`append_email_attachments`**
  (`src/assets/mail_asset/resources/db_resource.py`). Tests que lo blindan:
  `test_append_no_borra_lo_ya_insertado`, `test_append_conserva_la_particion_original_del_correo`,
  `test_append_es_idempotente_con_los_mismos_ids`.
- **Hallazgo 2 — aquí estaba el tiempo**: `GmailResource.fetch_emails` listaba los ids del
  día y descargaba **TODOS** los mensajes en `format="raw"` (cuerpo + todos los adjuntos en
  base64, 1 request por correo) **antes** de consultar la tabla; el filtro por `id` era *a
  posteriori*, en el insert. Cada re-materialización de la misma partición volvía a bajarlo
  todo y no insertaba nada.
- **Fix (3 fases)** en `ingest_emails`:
  1. `GmailResource.list_message_ids(query)` → ids del día **por cuenta** (barato: solo ids);
  2. `DbResource.existing_email_ids(ids)` → subconjunto ya guardado (`id IN (...)`, por lotes);
  3. `GmailResource.fetch_emails(query, ids_by_account=…, skip_ids=…)` → descarga (cuerpo +
     adjuntos) **solo los ids que faltan** y sigue insertando append-only.
  Metadata nueva del asset: `emails_in_window`, `emails_skipped`, `emails_ingested`, y un
  `context.log.info` con el desglose por cuenta.
- **Aviso añadido**: si una cuenta devuelve `_MAX_RESULTS` (500) ids en `messages.list`, se
  emite un `warning` (antes se truncaba en silencio: si un día tenía >500 correos por cuenta,
  se perdían sin avisar).
- **Tests**: `tests/test_mail_api_resource.py` (Gmail doblado, 7 casos: salto de ids, reuso de
  `ids_by_account`, varias bandejas) y `tests/test_mail_asset.py` (asset con stubs: a Gmail solo
  se le piden los que faltan). Suite completa: **506 passed**. `pytest` **no estaba instalado**
  en `.venv` (tampoco está en `requirements.txt`): se instaló `pytest 9.1.1`.
- **Límites conocidos**: la PK de `emails` es solo el `id` de Gmail (sin `mailbox`), así que un
  id ya guardado se salta en **todas** las bandejas (comportamiento previo del insert, solo que
  ahora también se evita la descarga). Y si una corrida murió entre `append_emails` y
  `append_email_attachments`, ese correo ya no se re-descarga: para recuperar sus adjuntos hay
  que borrar su fila de `emails` (o bajar esa partición con la fila ausente).

## ✅ `publish_dwh`: no fallaba, **no se ejecutaba** (2026-09-18)
- **Síntoma**: el usuario preguntaba por qué fallaba la publicación. Evidencia:
  `publish_dwh` **nunca** se ha materializado (`inst.get_latest_materialization_event` → None)
  y los 5 runs de `dwh_publish_job` de la historia solo tenían el step **`dbt_run`**
  (3 `SUCCESS` + 2 `STARTED` colgados **en `dbt_run`**, no en la publicación: era el OOM de
  `moves`, anterior al arreglo de los macros; se mataron a mano).
- **Causa**: la publicación es **opt-in**. `scripts/run_pipeline.py` arranca el paso
  `dbt/publicación` con `solo=("dbt_run",)` y solo añade `publish_dwh` con `--publish` **y**
  `PGHOST` en el entorno; si falta, escribe `AVISO: --publish pero PGHOST no está en el
  entorno` y sigue **sin publicar** (por eso no hay error). Los dry-run de tus logs lo decían:
  `· solo=dbt_run`.
- **Trampa encontrada**: `env/.env` (gitignored) definía `POSTGRES_HOST/PORT/DB/USER/PASSWORD/
  SCHEMA` — nombres que **no existen en ningún fichero del repo** y que **nadie cargaba** (no
  hay `load_dotenv`). Comprobado: cargando ese fichero en el entorno, `sync_db.pg_params()`
  seguía devolviendo `localhost:5432/postgres` con password vacío. Y su `POSTGRES_SCHEMA=dl`
  apuntaba a un esquema que **no existe** en la BD (en el DWH solo hay `dwh`: 6 tablas + la
  vista).
- **Arreglo (opción elegida: una sola fuente de verdad)**:
  - `env/.env` renombrado a las claves que lee `sync_db.py`: `PGHOST`, `PGPORT`, `PGDATABASE`,
    `PGUSER`, `PGPASSWORD`, `PGDWH_SCHEMA` (**`dwh`**, corregido desde el `dl` residual).
  - `scripts/run_pipeline.py`: nueva `cargar_env()` (stdlib, sin dependencias nuevas) que carga
    `ENV_PATH = env/.env` **antes** de `construir_pasos` y **sin pisar** lo ya exportado, así el
    plan resuelve `publish_dwh`. Tests nuevos en `tests/test_run_pipeline.py` (y el test de
    `--dry-run` existente ahora parchea `ENV_PATH` para no depender de la máquina).
  - **Y publica SIEMPRE (decisión del usuario)**: `construir_pasos(publish=True)` por defecto,
    así que el paso `dbt/publicación` arranca con `solo=("dbt_run", "publish_dwh")`. Nuevo flag
    **`--sin-publish`** para saltarla; `--publish` se sigue aceptando (obsoleto, no-op) para no
    romper una línea de cron vieja. Si falta `PGHOST` **no** se deja de publicar en silencio: se
    emite un AVISO y el step `publish_dwh` falla al conectar (visible en el run).
  - **Fix del choque de conexiones DuckDB (mismo día)**: al publicar por defecto saltó un fallo
    real: `dbt_run` y `publish_dwh` corren en el **mismo proceso** (executor in-process) y dbt
    deja el DuckDB abierto en **lectura-escritura**; el `duckdb.connect(path, read_only=True)`
    de la publicación reventaba con *"Can't open a connection to same database file with a
    different configuration than existing connections"* (reproducido: ni `gc.collect()` libera).
    Arreglo: nuevo **`sync_db.duckdb_connect()`** — intenta `read_only=True` y, si el error es
    ese "different configuration", reabre con la configuración existente (lectura-escritura, es
    la misma instancia del proceso; la publicación solo hace `SELECT`). Lo usan `sync_db.main`
    y `DwhPublishResource.tables()`. Cualquier otro error (p. ej. el lock de DBeaver) se propaga
    igual que antes. Tests de regresión en `tests/test_sync_db.py` (3) y
    `tests/test_dwh_publish_resource.py` (1: DuckDB abierto en el mismo proceso).
- **Validación**: `run_pipeline.py --dry-run` (ya sin `--publish`) → `env: 6 variables de .env
  (...)` y `solo=dbt_run,publish_dwh`. Y `sync_db.py --dry-run` contra el DWH real = 6 tablas /
  **64.180 filas** (`moves` 52.099, `partners` 11.614…) mientras `dwh.moves` tiene 45.376 ⇒ el
  DWH está **desactualizado desde el 2026-09-16**. El Postgres responde (15.15). Publicar es
  `python scripts/run_pipeline.py` (sin flags).
- **Ojo, no confundir**: el `fin (1 paso(s) fatal(es) fallido(s))` de los logs **no** es la
  publicación, es SIRE (`sire_proposal_monthly` de Air Majoro Selva con **HTTP 429** de
  `api-sire.../rce/propuesta/202608/exportacioncomprobantepropuesta` tras 3 reintentos, que
  arrastra a details/files y a los 3 `cost_centers`).

## ✅ RESUELTO EL OOM DE `dbt run` (modelo `moves`) — 2026-09-18
- **Síntoma**: `dbt run` se colgaba para siempre en `moves`, llenaba
  `analytics_poc.duckdb.tmp/` con **~8 GB** de `duckdb_temp_storage_*` y agotaba los 11 GB
  de RAM de la máquina (había que matarlo).
- **Causa raíz (probada con `EXPLAIN`)**: NO era volumen — las fuentes suman ~100 k filas
  (`sire_purchs` 15.603, `sire_purchs_details` 26.698, `sire_sales` 18.056, `sisa_sales`
  10.010, `from_email_adp_reports` 4.654, `ambulancia_ventas_reports` 474...). Era la
  **recursión** de los macros `get_by_sep` y `capitalize_words` (ambos `WITH RECURSIVE`
  escalares). DuckDB **no puede decorrelacionar un CTE recursivo**, así que
  `adp_purchs_std` —que mete `get_by_sep` **3 veces dentro de la clave de un JOIN**—
  degradaba a **`LEFT_DELIM_JOIN`** (ejecución dependiente fila por fila):
  4.654 ADP × 15.603 `sire_purchs` ≈ **72,6 M evaluaciones recursivas** ≈ 8 GB de spill.
  El plan antiguo mostraba `DELIM_JOIN + LEFT_DELIM_JOIN + REC_CTE_SCAN` (índice de CTE
  hasta 26); el nuevo, un `HASH_JOIN` plano.
- **Arreglo (solo macros dbt, 0 assets tocados)**:
  - `get_by_sep(text, sep, n)` → `(list_extract(string_split(text, sep), n + 1))`. Se usa
    `list_extract` y **NO** `split_part` porque `split_part` devuelve `''` fuera de rango
    mientras `list_extract` devuelve **NULL**, que es el contrato (lo necesitan
    `get_car`/`adp_purchs_std`: un número inexistente debe ser NULL, no 0).
  - `capitalize_words(col)` → `(SELECT string_agg(upper(substr(w,1,1)) || lower(substr(w,2)),
    ' ' ORDER BY i) FROM unnest(string_split(trim(col), ' ')) WITH ORDINALITY AS t(w, i))`.
    DuckDB **no tiene `initcap` ni `title`** (verificado en 1.5.5), así que no hay función
    de una sola llamada.
  - `get_car` y `cc_filename_to_car_sunat` pasan sus enteros por **`safe_int`** (`TRY_CAST`
    en DuckDB) en vez de `CAST` a pelo: **60 filas de `from_email_adp_reports` con
    `referencia = ''`** (todas con `servicio` no nulo ⇒ pasan el `WHERE`) llegaban al
    `CAST('')` del JOIN de `adp_purchs_std` y tumbaban dbt con
    `Conversion Error: Could not convert string '' to INT64`. Con `TRY_CAST` la clave es
    NULL, el INNER JOIN no casa y la fila se descarta sola. Es la política que ya
    documentaba `moves.sql` ("Siempre TRY_CAST, nunca CAST"). Este bug estaba **oculto**
    por el OOM: hasta arreglar la recursión nunca se llegaba a él.
- **Equivalencia validada (fila a fila, sobre TODOS los datos reales)**:
  - `get_by_sep`: 0 diferencias en 20 casos límite + 4.654 `referencia` × n=0..3 + 474
    `ruta` × n=0..3.
  - `capitalize_words`: 0 diferencias en 30.098 valores reales (`sisa_sales.desorigen` y
    `desdestino` 10.010 cada uno, `static_aux_airports.ubicacion` 78). **Única diferencia**:
    ante espacios CONSECUTIVOS el macro viejo INFLABA los espacios en uno
    (`substr(str,1,1)` tomaba el propio espacio) — 'A  B' → 'A   B'; el nuevo preserva la
    entrada. Es un defecto del viejo y ningún dato real tiene espacios dobles.
  - Claves de JOIN `compras → cost_centers`: 0 diferencias en 15.603 filas. Clave de ADP:
    0 diferencias en las 4.594 filas con referencia. `cc_filename_to_car_sunat`: 0
    diferencias en los 1.358 filenames construidos de Terpel.
- **Prueba de aceptación (en un DuckDB de usar y tirar, NO se tocó `analytics_poc.duckdb`)**:
  `dbt run` completo = **PASS=6, WARN=0, ERROR=0 en 2,44 s y 0 bytes de spill**. `moves`
  sale con sus **26 columnas y los tipos del DWH** (BIGINT/DATE/INTEGER/DECIMAL/TIMESTAMP)
  y **52.098 filas** (el baseline local tenía 45.376: el crecimiento es de los datos
  nuevos del 2026-09-17 — Compras 24.146→29.969, Ventas 18.658→19.557; Planilla 2.098 y
  ambulancias 474 idénticas).
- **Cómo se validó sin arriesgar la máquina**: perfil temporal en `/tmp/dbg/profiles/` con
  `path` a un DuckDB de usar y tirar + `memory_limit: '3GB'` + `temp_directory`; los tests
  de equivalencia cargan los datos con el `sqlite3` de la stdlib y los comparan en una
  DuckDB **en memoria** (nunca se abrió `analytics_poc.duckdb`). Ojo: `/tmp` es **tmpfs**
  (5,6 GB, respaldado por RAM), no sirve como `temp_directory` para cargas grandes.
- **Pendiente de decisión del usuario**: `analytics_poc.duckdb` está en estado *parcial*
  (los runs fallidos de hoy refrescaron `calendar`/`partners`/`static_*` antes de morir en
  `moves`), y quedan **~8 GB de basura** en `analytics_poc.duckdb.tmp/`. Basta relanzar
  `dbt run` (ya termina en segundos) y borrar ese `.tmp` sin procesos abiertos.

## ✅ NIVEL 2 IMPLEMENTADO: dbt Y PUBLICACIÓN DENTRO DEL GRAFO (+ jobs con nombre) — 2026-09-17
- **2 assets nuevos (19 en total)**, en `src/assets/dwh_assets/`, grupo `dwh`, **sin
  particiones** (dbt rehace todas las tablas del DuckDB en cada corrida):
  - `dbt_run` (`dbt_run_asset/`): corre `dbt run` sobre `src/dbt` **en proceso** con
    `dbtRunner` de dbt-core (`resources/dbt_resource.py`, clase `DbtResource`) y con el
    **CWD puesto en `src/dbt`** (el `profiles.yml` usa rutas relativas al CWD). Declara
    `deps` de las **17** fuentes de ingesta (lo que dbt lee de `db.sqlite`) ⇒ el orden
    assets → dbt lo impone el grafo. Devuelve `MaterializeResult` con `models_run`,
    `statuses` (JSON), `elapsed_seconds` y los args de dbt.
  - `publish_dwh` (`dwh_publish_asset/`): envuelve `sync_db.py` (`resources/publish_resource.py`,
    clase `DwhPublishResource`; `deps=[dbt_run]`). **No** duplica lógica: llama a
    `sync_db.main(argv)` (argv desde la config; `schema_name` fija `sync_db.SCHEMA`), lista
    las tablas BASE con `tables()` para la metadata y convierte código≠0/excepción en
    `DwhPublishError`. Las **credenciales PG se leen del entorno** (`PGHOST`...), como a mano.
- **`src/jobs.py` (nuevo)**: 7 `define_asset_job` con nombre (`correo_daily_job`,
  `sire_monthly_job`, `rh_monthly_job`, `sisa_monthly_job`, `estaticos_job`,
  `calendar_weekly_job`, `dwh_publish_job`) importados por `definitions.py` (`jobs=JOBS`).
  Dentro de cada job todos los assets particionados comparten `PartitionsDefinition`.
  **Sigue sin haber `ScheduleDefinition` ni `automation_condition`** (tests que lo fijan:
  `tests/test_jobs.py`, y los 3 que ya lo asserteaban).
- **`dagster job execute` NO acepta `--partition`/`--partition-range`** (van a `None` fijo
  en `_cli/job.py`) ⇒ el cron sigue materializando **por selección de assets**. Además, el
  check del CLI para `--partition-range` exige `BackfillPolicy.single_run()` en **todos**
  los assets seleccionados, así que `dbt_run`/`publish_dwh` (sin política) van en un run
  **aparte y sin particiones** (`--select "dbt_run,publish_dwh"`).
- **Novedad de la versión**: `dagster asset materialize` y `dagster job execute` están
  marcados `@superseded` ("Use `dg launch --assets <selection>`"); `dg` **no** está
  instalado en el venv.
- **`scripts/run_pipeline.py` (NUEVO — punto de entrada ÚNICO del pipeline)**: calcula las
  **ventanas** (`ventana_meses`, `dias_correo`) y lanza los runs **en serie** con
  `JobDefinition.execute_in_process` sobre la instancia persistente (`DAGSTER_HOME`, por
  defecto `dagsterhome/` del repo). 5 runs: RH (rango de 2 meses, **no fatal** = AVISO),
  SIRE (rango de 2 meses), correo (1 run por día) y `dbt_run` (+`publish_dwh` con
  `--publish`). Args: `--dias-correos N` (2), `--sin-rh`, `--sin-dbt`, `--publish`,
  `--dry-run`; log con marca de tiempo en `logs/run_pipeline.log` y por stdout.
  `scripts/pipeline_cron.sh` queda como **wrapper de 1 línea** (compatibilidad con un
  crontab antiguo). Crontab nuevo:
  `10 7 * * * <repo>/.venv/bin/python <repo>/scripts/run_pipeline.py`.
  - Usa los **jobs de `src/jobs.py`** como fuente de verdad de cada cadena (`claves_del_paso`)
    y avisa/falla si un rango incluye un asset sin `single_run()` (`exigir_single_run`, la
    misma condición que el CLI).
  - ⚠️ Diferencia con el CLI: cada run corre **en un solo proceso** (executor in-process), no
    un proceso por step; el efecto sobre los datos es el mismo (`MaterializeResult` sin valor).
  - Tests: `tests/test_run_pipeline.py` (12) con assets de juguete y
    `DagsterInstance.ephemeral()`: plan, partición, selección sin particiones y **rango
    `single_run` = 1 run con las 2 particiones**.

### ⚠️ HALLAZGO IMPORTANTE: `dbt run` (modelo `moves`) HOY NO ES LIGERO
- Validando `dbt_run` **en vivo** (2026-09-17 20:13) con el perfil **real**: dbt 1.9.8 +
  duckdb 1.9.6 arrancan bien, encuentra **24 modelos** y los **5 modelos pequeños**
  (`calendar`, `partners`, `static_airplanes`, `static_cost_centers`,
  `static_master_accounts`) terminan **OK**; al llegar a `moves` (6 de 6) DuckDB se puso a
  escribir **8,9 GB de *spill*** en `analytics_poc.duckdb.tmp/` y **agotó la memoria de la
  máquina** (11 GB), así que **se mató el proceso a mano** y se borró el directorio
  temporal (el `.duckdb` de 4,99 MB quedó intacto; quedó un `analytics_poc.duckdb.wal` de
  456 KB que DuckDB rejugará al abrirlo).
- **Contradice lo medido el 2026-09-16** ("`dbt run` sobre el `analytics_poc.duckdb` REAL:
  PASS=6 en 2,57 s"). Ahora el `db.sqlite` tiene 18,9 GB con todo el SIRE de agosto y
  septiembre cargado y el `UNION ALL` de `purchs_std`/`sales_std`/`labor_std` de `moves`
  revienta memoria/disco. **Implicación para el cron**: si corre `dbt_run` a diario y sin
  nadie mirando, lanza ese pico a las 07:10 (`PIPELINE_DBT=0` lo desactiva). **Pendiente
  real y prioritario**: `moves` (¿`memory_limit`/`temp_directory` en `profiles.yml`,
  materialización incremental, o revisar los joins/`UNION`?), no el asset en sí.
- **NO se ha repetido** la corrida pesada. Lo validado sin riesgo: `dagster definitions
  validate` ✅, **479 tests `pytest` ✅** y el `PIPELINE_DRY_RUN=1` del cron con los 5
  comandos ✅. Con un **perfil temporal en `/tmp`** (DuckDB de `/tmp`, `db.sqlite` real
  adjunto) también arrancó y materializó los 5 modelos pequeños OK antes de que la
  interrupción de la sesión matase el proceso.

## ⚠️ ASSETS CON `single_run()` Y RANGO: `MaterializeResult` **SIN VALOR** — 2026-09-17
- **Bug encontrado al lanzar el cron (y ya arreglado)**: los assets de SIRE (6) y
  `seesol_rh_monthly` devolvían `Output(value=..., metadata=...)`. Con
  `BackfillPolicy.single_run()` y un rango de **2 particiones**
  (`--partition-range 2026-08-01...2026-09-01`, que es lo que hace el cron), el
  IO manager por defecto (`PickledObjectFilesystemIOManager`) **no soporta
  persistir un output asociado a varias particiones**:
  `CheckError: The current IO manager ... does not support persisting an output
  associated with multiple partitions` → **el step escribe los datos y después
  marca FAILURE** (el cron lo reportaba como "FALLO SIRE" y "AVISO RH").
- **Arreglo**: los 7 assets devuelven ahora `MaterializeResult(metadata=...)`
  (**sin `value`**). Dagster solo salta el IO manager si el resultado es un
  `AssetResult` y el valor es `NoValueSentinel`
  (`execute_step.py::_store_output`); el resumen de filas sigue apareciendo como
  metadata del materialization event. Regresión cubierta por
  `tests/test_sire_particiones.py::test_ningun_asset_devuelve_output_con_valor` y
  `tests/test_seesol_rh_asset.py::test_no_devuelve_output_con_valor`
  (assertean la **anotación de retorno**). Los assets de correo que ya van con
  rango (talma/adp/terpel) devuelven `-> None`: el patrón equivalente.
- **Validado en vivo (2026-09-17 18:55)**: `seesol_rh_monthly
  --partition-range "2026-08-01...2026-09-01"` → `RUN_SUCCESS` (328 filas,
  8+6 de agosto y 164+4 de septiembre). `sire_proposal_monthly` del mismo rango
  pasó (RCE+RVIE de 202608 y 202609 de las 2 empresas).
- **Ojo al cambiar un asset de rango**: si vuelve a devolver `Output` con valor,
  el error solo aparece al materializar **más de una partición** (una sola
  partición sí funciona), así que no se ve en las corridas sueltas del UI.
- **Sondeo del ticket SUNAT: `TICKET_POLL_SECONDS` 10 → 2** (2026-09-17). El
  bucle `_wait_for_ticket` es `while True` (sin tope de intentos): bajar el
  intervalo solo acelera el "File ready", no acorta la espera máxima.
  `tests/test_proposal_resource.py` assertea la constante, no un 10 suelto.
- **HTTP 503 (proxy de SUNAT) YA NO TUMBA `sire_files`/`sire_details`
  (2026-09-17)**: bajando los PDF/ZIP, api-cpe contestó **503 Service Unavailable**
  (HTML) en un comprobante y `SireApiUnexpectedStatus` mató el paso entero
  (`sire_files`) y con él el run (los cost centers ni se ejecutaron). Ahora
  `RETRYABLE_HTTP_STATUSES = (500, 502, 503, 504)` en
  `assets/sire_assets/resources/details_and_files_resource.py`: se reintentan como
  el 500 y, agotados los intentos, `SireApiMissing` ⇒ el documento queda en
  `missing_files`/`missing_documents` y **el próximo run lo vuelve a pedir**
  (append-only). El 500-con-body-no-JSON sigue cortando como `SireApiUnauthorized`
  y los demás status siguen siendo fatales. Tests:
  `tests/test_cpe_details_resource.py::test_get_items_503_*`.
- **`calendar_weekly` y `sisa_sales_monthly` SÍ son `single_run()`** (2026-09-23): leían
  `context.partition_key` y con un rango el step caía con `DagsterInvariantViolationError` (visto
  en vivo con `calendar_weekly`). El arreglo fue que **soporten** el rango, **no** bajarles la
  política: la lógica de una partición vive en `procesar_semana`/`procesar_mes` y el asset la
  recorre para cada clave de `partition_days(context)`, devolviendo `MaterializeResult` **sin
  valor** (un `Output` con valor reventaría el run de rango en el IO manager por defecto). Son
  baratos (1-2 consultas por semana, con la caché de meses compartida en todo el run; 3 por mes en
  SISA), así que no compensa planificar un run por partición.
- `static_data_asset` (partición estática) sigue **sin** política; `dbt_run`/`publish_dwh` no
  tienen particiones.
- **422/1070 "periodo sin comprobantes" YA NO TUMBA EL RUN (2026-09-17)**: el
  proceso masivo de SUNAT contesta a veces HTTP 422 / `cod 1070` ("No se ha
  encontrado información de comprobantes de pago en Periodo Seleccionado") en
  `consultaestadotickets` **recién creado el ticket** — y es **mentira
  transitoria**: verificado en vivo, el MISMO libro (RVIE 202608 de Air Majoro)
  devolvió 1070 y bajó con datos al pedir un ticket nuevo. Ahora
  `TicketResource.get_zip` reintenta con un **ticket nuevo** hasta
  `TICKET_EMPTY_PERIOD_MAX_ATTEMPTS = 3` (1 intento + 2 reintentos); si SUNAT
  insiste, **devuelve `None`**, `ProposalResource.get_proposal` devuelve `[]` y
  el asset sigue con el resto (0 filas + WARNING `... periodo SIN comprobantes`).
  `_es_periodo_sin_comprobantes` solo acepta **422 con `errors[].cod == 1070`**
  y un body JSON parseable: cualquier otra cosa (500, otro código, body no JSON)
  se propaga como antes. Constantes y tests en
  `constants.py` / `tests/test_ticket_resource.py`.
- **422/42209 "proceso de propuesta en curso" YA NO TUMBA EL RUN (2026-09-23)**: al
  pedir un **ticket nuevo** (p. ej. tras un 1070) mientras el proceso del ticket
  anterior sigue corriendo, SUNAT contesta **HTTP 422 / `cod 42209`** ("aún tiene un
  proceso de \"Generar archivo exportar propuesta\" en curso con Ticket: ...") y el
  run moría. Verificado en vivo: RVIE **202605 de Air Majoro**, tickets 3381 y 3382
  con 1070 seguidos y el 3er ticket rechazado porque el **3382 seguía en curso**
  (el 1070 era prematuro, no periodo vacío). Ahora
  `TicketResource._request_ticket` reconoce el 42209 con `_es_proceso_en_curso`
  (sobre el helper nuevo `_codigos_error`, que parsea `errors[].cod` del body JSON)
  y **espera `TICKET_IN_PROGRESS_WAIT_SECONDS` (30 s) reintentando hasta
  `TICKET_IN_PROGRESS_MAX_ATTEMPTS` (5)**; agotados, propaga el último error (no es
  periodo vacío). Además `get_zip` espera `TICKET_EMPTY_PERIOD_WAIT_SECONDS` (15 s)
  entre intentos del 1070 para no pedir un ticket nuevo pegado al anterior. **No
  cambia el desenlace del 1070 definitivo** (3 intentos → `None` → 0 filas +
  WARNING → el run sigue). Constantes y tests en
  `constants.py` / `tests/test_ticket_resource.py`.
- **Error de red + timeout en la propuesta (2026-09-23)**: `TicketResource._request`
  no capturaba `requests.exceptions.RequestException`, así que un
  `OSError [Errno 101] Network is unreachable` a mitad del RCE 202603 de Air Majoro
  mató el run. Ahora se reintenta con **presupuesto propio** —
  `HTTP_NETWORK_MAX_ATTEMPTS = 10` × `HTTP_NETWORK_WAIT_SECONDS = 30` —, más largo
  que el del 429 (`HTTP_RETRY_MAX_ATTEMPTS = 5` × `HTTP_RETRY_WAIT_SECONDS = 30`),
  porque comparten el mismo bucle de intentos; agotado, `PropuestaRceError`
  ("Error de red"). Además la petición lleva
  **`timeout=HTTP_REQUEST_TIMEOUT_SECONDS` (60 s)** (como
  `details_and_files_resource.request_timeout_seconds` y
  `token_resource.request_timeout_seconds`; antes no había timeout y un socket
  colgado bloqueaba el run para siempre). Este sí es el único caso de la propuesta
  donde se **reintenta** un `RequestException`; los demás resources de SIRE
  (`details_and_files_resource`, `token_resource`) lo **convierten** en su error de
  dominio sin reintentar. Tests: `tests/test_ticket_resource.py::test_red_*` y
  `test_request_lleva_timeout`.
  **Límite conocido**: el `token()` se resuelve antes del bucle; si el token
  cacheado está caducado y la red está caída, `SireTokenResource` lanza
  `SireTokenError` y ese caso **no** lo cubre este reintento (con token cacheado
  válido, sí).

## TOKENS SIRE: AUTOMÁTICOS EN LOS ASSETS, POR AUDIENCIA Y CACHEADOS EN FICHERO — 2026-09-17
- **Ya NO hay scripts de token**: `scripts/sol_token.py` se eliminó y
  `scripts/sol_token_navegador.py` pasó a **`docs/sol_token_navegador.py`** (plan B
  documentado, Selenium headless, NO lo usa el pipeline). El pipeline (`pipeline_cron.sh`)
  ya **no tiene paso 0**: los tokens los piden los propios `api_resource` de SIRE.
- **Todo el estado de SIRE vive en `env/` (2026-09-23)**: las credenciales en
  `env/sire_credentials.json` y la **caché de tokens en `env/sire_tokens.json`** (antes
  `logs/sire_tokens.json`; `logs/` ya **no** se usa para nada del pipeline). El JSON de
  la caché está en `.gitignore` (`env/sire_tokens.json*`) y el lock entre procesos pasó
  a `env/sire_tokens.json.lock`.

- **Provider único**: `SireTokenResource`
  (`src/assets/sire_assets/resources/token_resource.py`), usado por la propuesta
  (`TicketResource`/`ProposalResource`), los detalles (`DetailsAndFilesResource`) y los
  archivos CPE. `fixed_token_resource.py` (alias `FixedTokenResource`) **se borró**.
- **`token(name, audience, recurso)`** resuelve en este orden:
  1. **Caché en fichero** `env/sire_tokens.json` (**audiencia → empresa → token**; ese
     JSON está en `.gitignore`). Entrada = `{token, exp, recursos, origen, obtenido}`. Se usa si
     existe, no está caducada (margen 60 s, el más restrictivo entre el `exp` del JWT y el
     `exp` guardado) y cubre el `recurso` pedido. **Se consulta por documento** (miles de
     veces por mes) ⇒ el JSON se relee solo si cambia el `mtime`.
  2. **API de seguridad** (`POST
     https://api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/`,
     `application/x-www-form-urlencoded`, **`grant_type=password`**; con
     `client_credentials` SUNAT contesta **HTTP 204 sin body**; `scope` = `sire_scope` del
     JSON; `username` = **RUC+usuario SOL sin espacio**).
  3. **Portal SOL por HTTP puro** (`assets/sire_assets/resources/sol_portal.py`), **solo**
     para la audiencia de comprobantes: login de **1 intento** (aborta si `fallas >= 3`:
     captcha) + `POST MenuInternet.htm {action:'prevApp'}` +
     `GET MenuInternet.htm?action=execute&code=11.38.1.1.1` → el **servidor** del portal
     responde **302** con el JWT de `consultacpe` en el `Location`; se valida en vivo contra
     api-cpe (`probar_consultacpe`: 422/200 = aceptado).
  4. Si nada sirve → **`SireTokenError`** con los motivos y **cae la materialización**.
     **NO hay token manual de respaldo**: el campo `token` de `env/sire_credentials.json`
     ya no se lee.
- **Al guardar**: el token se escribe bajo **todas las audiencias que cubre** (deducidas del
  claim `aud` con `token_coverage`) y, si ya había entrada, gana **la más fresca** (mayor
  `exp`). Escritura **atómica** (tmp + `os.replace`) con `flock` (`<cache>.lock`) porque los
  steps de Dagster corren en procesos distintos. Un fichero ilegible se aparta como `.bad`.
- **Audiencias verificadas en vivo (2026-09-17)**: propuesta/ticket → `AUDIENCE_SIRE`
  (`https://api-sire.sunat.gob.pe`) + `RECURSO_MIGEIGV` (`/v1/contribuyente/migeigv`);
  detalles/archivos → `AUDIENCE_CPE` (`https://api-cpe.sunat.gob.pe`) +
  `RECURSO_CONSULTACPE` (`/v1/contribuyente/consultacpe`). **Air Majoro** (`client_id`
  `00d37468-…`) recibe **ambos** recursos en el token de seguridad (0 logins); **Air Majoro
  Selva** (`42bd5918-…`) **no** recibe `consultacpe` ⇒ sus detalles/archivos van por el
  portal SOL de forma automática (antes había que pegar el token a mano cada hora).
- **Un login como mucho por empresa y proceso**: el intento del portal se memoiza
  (`_portal_fallido`), así que un fallo (p. ej. `fallas >= 3`) no se repite por documento ni
  suma fallos en SUNAT. **La vía de cookies NO es fiable** (WAF F5, cookies `TS*`); el
  `--cookies` de `docs/sol_token_navegador.py` es un atajo best-effort y necesita un
  `logs/sol_sesion.json` hecho a mano.
- **Trampa del claim `aud`**: SUNAT lo emite como **string con el JSON dentro**
  (`'[{"api":…,"recurso":[{"id":…,"indicador":…}]}]'`); `_audience_entries()` acepta lista,
  string-JSON (lista u objeto) y string simple.
- **Pendiente "de libro"**: pedir a SUNAT el permiso `consultacpe` para el `client_id` de
  MSA para que también sea automático sin portal (hoy ya lo es *por HTTP*, no por API de
  seguridad).
- **Plan B documentado**: `docs/sol_token_navegador.py` (Selenium + Firefox `-headless` +
  geckodriver; perfil en `logs/ff_perfil`, **nunca** `/tmp`; ~300 MB ~30 s). Hace el login
  **pulsando `#btnAceptar`** (su `login()` copia `#txtRuc`/`#txtUsuario`/`#txtContrasena` a
  los ocultos `tipo=2`, `custom_ruc`, `j_username`, `j_password`; llamar a
  `LoginForm.submit()` directo manda los ocultos vacíos y SUNAT contesta *"El RUC, Usuario
  SOL, Clave son incorrectos"*), y busca el JWT en la URL de la app y en
  **`sessionStorage["SUNAT.token"]`**. Valida con los helpers del resource y deja el token
  en **la misma caché**. `selenium` está **comentado** en `requirements.txt`.

## REPORTE RH DEL SEE-SOL: ASSET MENSUAL CON LA VÍA HTTP DENTRO — 2026-09-17
- **El reporte RH ya no es un script**: vive en el asset **`seesol_rh_monthly`**
  (`src/assets/seesol_rh_asset/`, **primer nivel** de `assets/`, partición **mensual** con
  `seesol_rh_monthly_partitions_def` = alias de `monthly_partitions_def` de
  `_common/partitions.py` y `BackfillPolicy.single_run()`). El antiguo
  `scripts/sol_rh_seesol.py` **se eliminó** y ya **no** se escriben TXT en `static/RH`
  (queda solo como histórico), así que tampoco hay que re-materializar `static_data_asset`
  para que `seesol_rh` se entere.
- **La vía HTTP está en el resource** `assets/seesol_rh_asset/resources/api_resource/`
  (`rh_resource.py` + `constants.py`): antes reutilizaba el login de `sol_token.py`, ahora
  es **autónoma** (mismo flujo, portado tal cual: login del portal → `action=execute&code=11.5.1.1.14`
  → `cpelec001Alias`, 1 intento, sin reintentos, aborta si `fallas >= 3`). Contrato:
  `get_month(company, period) -> list[dict]` (filas con su `period`; el `empresa` lo estampa el
  asset) y `fetch_report(company, period) -> str` (texto crudo). Credenciales:
  `credentials_path` (por defecto `env/sire_credentials.json`).
- **Verificado en vivo el 2026-09-17** (con el script, misma petición): el `archivo.txt` es
  **byte a byte** idéntico al que el usuario guardaba a mano (`cmp` contra ago-2026 de las 2
  empresas; `fallas` sigue **0**).
- **Flujo (4 pasos)**: login → `POST MenuInternet.htm {action:'prevApp'}` +
  `GET MenuInternet.htm?action=execute&code=11.5.1.1.14` (**302** a
  `https://ww1.sunat.gob.pe/ol-ti-itreciboelectronico/cpelec001Alias?accion=LlamaCriterioConsulatRec1…`,
  la app **"Consulta Receptor"** del SEE) → `POST cpelec001Alias` con
  `accion=CapturaCriterioConsulatRec1` + `fec_desde`/`fec_hasta` (**dd/mm/YYYY**, rango ≤ 1 mes:
  el portal rechaza más con un `alert`) + `tipoestado=00` → `POST cpelec001Alias` con
  `accion=descargaConsultaReceptor` (el "Descargar Reporte") que devuelve `text/plain`
  (`filename="archivo.txt"`), 16 columnas `|`.
- **TRAMPA del POST de criterios**: el campo **oculto** `tipocomprobante` debe ir como
  **`"01;02;03;"`** (los tipos concatenados con `;` final, que es lo que arma el JS del formulario
  a partir de sus 3 checkboxes `tipocomprobante1`). Mandarlo vacío (o solo los checkboxes) hace que
  SUNAT conteste *"No se han encontrado registros"* aunque el mes sí tenga recibos.
  Está cubierto en `criterios_busqueda()` y en su test.
- **Upsert por (mes, empresa)**: `SeesolRhSqliteResource.upsert_month(period, empresa, rows)`
  borra y reinserta **solo esa pareja** (los otros meses/empresas no se tocan; un mes sin recibos
  limpia su pareja). `count_month` da las filas previas y el asset **avisa** si el mes nuevo trae
  menos filas (mes todavía incompleto en SUNAT).
- **1 login por empresa y mes** (el rango del portal no puede pasar de un mes) y el asset pide el
  **mes anterior + el actual** en un solo run; `2 empresas × 2 meses = 4 logins` por ejecución del cron.
- **`scripts/pipeline_cron.sh` paso 0bis** (por defecto activo, `PIPELINE_RH=0` para desactivar):
  materializa `seesol_rh_monthly --partition-range "$MES_ANTERIOR...$MES_ACTUAL"`; si falla
  (p. ej. captcha), AVISA y el pipeline sigue. El borde de enero ya **no** es problema: la
  partición es mensual y `end_offset=1`, así que el mes en curso siempre es válido.
- **La vía navegador para el RH NO se implementa** (decisión del usuario, 2026-09-17). Se llegó a
  comprobar que el menú **no abre las apps en ventana nueva**: su `ejecuta()` hace el `prevApp` y
  carga la app en el **iframe `#iframeApplication`** del propio menú; `sol_token_navegador.py`
  sigue siendo el plan B solo del **token**, no del reporte RH.



## TOKENS SIRE: (histórico) API de seguridad → token manual — 2026-09-17
- Esta sección quedó **superada** por el bloque de arriba: el token manual ya no existe, el
  fallback es el **portal SOL por HTTP** y la caché es **en fichero** (no sólo en memoria).
- Se conserva por dos datos que siguen siendo ciertos: la **trampa del claim `aud`** (SUNAT
  lo emite como string con JSON dentro) y la **sonda en vivo** (una llamada real a api-cpe
  con el token de seguridad de Air Majoro devolvió **422** = token aceptado, frente al
  **500 HTML** de un token inválido; de ahí que el 500 no-JSON se trate como `Unauthorized`).
- Cachés **en memoria** (además de la de fichero): `_security_tokens` (nombre → token de
  seguridad de esta corrida) y `_tokens` (nombre+audiencia+recurso → token elegido), que
  evitan repetir el POST/el login dentro del mismo proceso.

## PORTAL SOL: login HTTP automatizado — 2026-09-17
- El flujo OAuth2 del portal que replicaba `scripts/sol_token.py` (eliminado) vive ahora en
  **`assets/sire_assets/resources/sol_portal.py`** y lo usan el resource de tokens **y** el
  reporte RH (`seesol_rh_asset`, que antes tenía su propia copia del login).
- **El LOGIN funciona** (4 intentos, 4 éxitos, `fallas` sigue en **0**): `GET
  e-menu…/cl-ti-itmenu/MenuInternet.htm` → JS que redirige a
  `api-seguridad…/clientessol/{client_id}/oauth2/authen?…&response_type=code` → pantalla
  `…/oauth2/loginMenuSol` → `POST …/oauth2/j_security_check` con `tipo=2` (RUC), `dni` vacío,
  `custom_ruc`=RUC, `j_username`=usuario SOL, `j_password`=clave SOL, `captcha` **vacío** salvo
  que `fallas>=3`, más los ocultos del form (`state`, `originalUrl`, `lang`, `exe`, `params`) →
  **302** al `originalUrl` con `&code=<JWT de 5 min>`. Pre-chequeo de captcha:
  `POST e-menu…/cl-ti-itmenu/AutenticaMenuInternetPlataforma.htm {action:"fails"}` →
  `{"fallas":"0"}` (en el HTML el AJAX va como ruta relativa, pero el endpoint real está en el
  host de **e-menu**). En `sol_portal`, `descubrir_flujo` reutiliza el HTML de la pantalla de
  login que ya tiene en la mano (no la vuelve a pedir).
- **El token de `consultacpe` lo entrega el servidor** en el 302 del `action=execute` (no hay
  que canjear ningún `code`: el canje manual contra `oauth2/token` daba `400 parametros
  invalidos` / `401 unauthorized_client` y **nunca hizo falta**). El JWT también se ve en la
  URL del loader de la app y en `sessionStorage["SUNAT.token"]`, que es lo que mira el plan B
  documentado.

## Cadena de correo: REDISEÑADA y cargada (sesión 2026-09-17)
- **Los 7 assets de correo son diarios** y comparten UNA sola definición:
  `src/assets/_common/partitions.py` → `correos_daily_partitions_def`
  (`start_date="2026-01-01"`, **sin `end_offset`** ⇒ la última partición válida es **ayer**) y el
  helper `partition_days(context)` (devuelve 1 día, o el trozo de rango del run: completo con
  `single_run`, hasta N días con `multi_run(max_partitions_per_run=N)` — la función se invoca
  **una vez por run**, no una por día; en un run de rango `context.partition_key` **lanza**).
- **Reparto de `BackfillPolicy`** (misma partición + misma política ⇒ pueden compartir run):
  - **`BackfillPolicy.multi_run(max_partitions_per_run=30)`** (2026-09-23: un run por cada trozo de
    hasta 30 días, que la función recorre día a día): `ingest_emails` y `corpac_files_daily`. El
    cron diario sigue siendo 1 día por run (`--partition <ayer>`); el troceado solo aplica a un
    backfill de rango. Ninguna de las dos funciones usa `context.partition_key`: la lógica de un
    día vive en `procesar_dia` y el asset la repite para cada día de `partition_days(context)`,
    devolviendo `MaterializeResult` **sin valor** (un `Output` con valor reventaría el run de
    rango en el IO manager por defecto).
  - **`BackfillPolicy.single_run()`** (un único run para todo un rango, también recorrido con
    `partition_days`): `corpac_data_daily` y los 4 de reportes `talma_reports_daily`,
    `adp_reports_daily`, `terpel_tickets_daily`, `terpel_order_daily` (renombrados desde
    `*_monthly`; sus `select_*` filtran **día exacto** y el upsert pasó a `upsert_day`).
  - **La política del job es la mínima** de sus assets (`unresolved_asset_job_definition.py`):
    `correo_daily_job` resuelve `multi_run(30)` (el aviso de políticas mixtas se silencia en
    `jobs.py`). Ojo: `dagster asset materialize --partition-range` **exige `single_run()` en
    TODOS** los assets seleccionados, así que el rango del grupo `from_email` no se puede lanzar
    por CLI (usa `--partition`, el backfill de la UI o el asset suelto `corpac_data_daily`).
- **CERO condiciones de automatización** (decisión del usuario; ninguna `automation_condition` en
  el repo): el disparo es un **cron externo** que materializa el grupo por día, **sin demonio**:
  `AYER=$(date -d yesterday +%F); cd <repo>/src; DAGSTER_HOME=<repo>/dagsterhome
  .venv/bin/python -m dagster asset materialize -m definitions
  --select "group:from_email" --partition "$AYER"`.
  Ya está escrito el script **`scripts/pipeline_cron.sh`** (2026-09-17; sustituye al borrado
  `correos_cron.sh`): cubre SIRE **y** correo, y **no** toca dbt ni la publicación (van aparte, en
  ese orden). Probado en seco con `PIPELINE_DRY_RUN=1`; log en `logs/pipeline_cron.log`, que está
  en `.gitignore`; sale 1 si algún día falla.
  **PENDIENTE**: registrarlo en el crontab del usuario (hoy no hay ninguna entrada: `crontab -l`
  dice `no crontab for josemi`) con `10 7 * * * <repo>/scripts/pipeline_cron.sh`.
  `dagster dev` (webserver + daemon) ya no dispara nada por sí solo.
- **Índice nuevo** `emails_partition_date`, declarado en ``Email.Meta.indexes`` (lo crea
  ``create_tables`` con ``CREATE INDEX IF NOT EXISTS``): sin él, cada día recorría la tabla
  `emails` completa (~24k filas con `body` en TEXT).
- **Carga inicial del grupo ligero HECHA (2026-09-17)**:
  `--partition-range "2026-01-01...2026-09-16"` sobre los 4 assets `single_run` = **1 run con 4
  steps, RUN_SUCCESS** (~6 min) → `from_email_talma_reports` 839 filas/8 días ·
  `from_email_adp_reports` 4.487/16 · `from_email_terpel_tickets` 748/210 ·
  `from_email_terpel_order` 1.334/97. `pytest`: **353 passed**.
- **PENDIENTE A PROPÓSITO**: la carga inicial de `ingest_emails` + `corpac_files_daily` +
  `corpac_data_daily` (la parte pesada: Gmail + descargas del portal CORPAC + parseo de PDFs).
  Desde el 2026-09-23 `corpac_data_daily` es `single_run()` (su rango sí se puede lanzar por CLI y
  procesa el rango entero de una vez) y `ingest_emails`/`corpac_files_daily` van con
  `multi_run(30)`, así que su carga inicial es **día a día con `--partition <día>`** (o un
  backfill con demonio), nunca con `--partition-range`.
- **Datos a revisar (no tocados)**: `TALMA_SENDERS` sólo cubre 3 direcciones (en `emails` hay ~20
  remitentes `@talma.com.pe`, p. ej. `Romina.Miranda@talma.com.pe` con 63 correos) y `ADP_SENDER`
  sólo `ladyliz.moreno@adp.com.pe`; los 2 assets de Terpel comparan el remitente con `==` exacto
  mientras talma/adp normalizan con `Lower(Trim(...))`.
- **CORPAC: append-only también a nivel de correo (2026-09-23)**: `CorpacSqliteResource.select_corpac_emails`
  excluye los correos que ya tienen **al menos un** archivo en `from_email_corpac_files`
  (subconsulta `id NOT IN (SELECT id_email ...)`), así que re-pasar el día solo descarga los
  correos nuevos y los `id` ya insertados (los que referencia `corpac_header.file_id`) quedan
  estables. `upsert_files` mantiene el dedupe `(id_email, filename)` como red de seguridad del
  re-run. Tests: `test_corpac_db_resource.py` (`test_select_corpac_emails_salta_los_correos_ya_procesados`)
  y el de punta a punta con el resource real en `test_corpac_files_asset.py`.

## SIRE: REDISEÑADA a mensual + append-only (sesión 2026-09-17)
- **Los 6 assets de SIRE son MENSUALES** (clave = primer día del mes; `end_offset=1` ⇒ el mes en
  curso es partición válida), comparten `sire_monthly_partitions_def` de
  `src/assets/_common/partitions.py`, están en el grupo **`from_sire`** y **ninguno** declara
  `automation_condition`. **Reparto de `BackfillPolicy` (decisión del usuario, 2026-09-23)**:
  `sire_proposal_monthly` y los 3 `*_cost_centers_monthly` con `BackfillPolicy.single_run()`;
  **`sire_details_monthly` y `sire_files_monthly` SIN política a propósito** (= `multi_run(1)`: 1
  run por mes, se planifican cómodo mes a mes). Consecuencias: `sire_monthly_job` resuelve
  **`multi_run(1)`** (la política mínima; el aviso `varying BackfillPolicies` sale en cada
  resolución del job) y **`--partition-range` con estos 2 assets está rechazado por el CLI**
  (`_cli/asset.py`: exige `single_run()` en TODOS los seleccionados — un rango en varios runs
  necesita daemon). Por eso el mes anterior + el actual se lanzan **con 2 `--partition`** (o con
  un backfill de la UI/daemon); un `--partition-range "2026-08-01...2026-09-01"` de
  `group:from_sire` **falla antes de lanzar** con `DagsterCheckError`. Renombrados:
  `sire_proposal_monthly`, `sire_details_monthly`, `sire_files_monthly`,
  `{cep,icaro,petroperu}_cost_centers_monthly` (los `*_daily` de la iteración anterior ya no existen).
- **Dependencias identidad** (sin `TimeWindowPartitionMapping`): `details`/`files` →
  `AssetDep(sire_proposal_monthly)`; los 3 cost centers → **solo** `AssetDep(sire_files_monthly)`
  (la propuesta entra por transitividad). Al ser todas mensuales con la misma política, padre e
  hijo caben en el mismo run (`asset_job.py:397` exige misma `partitions_def` **y** misma política).
- **APPEND-ONLY en toda la rama** (integridad referencial; el padre nunca cambia de id):
  - `SireSqliteResource.insert_proposal_new` (`_existing_keys` + `_insert_new`; clave natural
    `empresa + tipo_cp_doc + serie_del_cdp + nro_cp_o_doc_nro_inicial_rango + nro_doc_identidad`;
    **la primera versión gana**, una rectificatoria posterior no actualiza la fila).
  - `insert_details` / `insert_files`: ya eran insert-only; solo piden lo **faltante**
    (`select_missing_documents` / `select_missing_files` por LEFT JOIN al FK).
  - `insert_aeronaves_new` por `(id_file, aeronave)` y `select_zip_files(months)` **salta los ZIP
    que ya tienen filas** ⇒ re-pasar el mes es barato.
  - **Fuera del flujo** las llamadas a `delete_orphan_details`/`delete_orphan_files` (sin ids que
    rotan no puede haber huérfanos; los métodos se conservan para limpiezas puntuales).
- **Una llamada a la API por mes** (no por día): `partition_months(context)` agrupa los meses del
  run y `ProposalResource.get_proposal` se pide 1 vez por mes/empresa/libro; details/files filtran
  por el **libro del periodo** con la ventana del mes (el caso "emitidos antes del mes" lo cubre
  `_rango_documentos`, que ya incluía los anteriores cuando `start_date.day == 1`).
- **Pendiente de datos (heredado)**: **5.370 filas huérfanas** en `db.sqlite`
  (`sire_sales_details` 1.299 · `sire_purchs_details` 1.077 · `sire_sales_files` 1.890 ·
  `sire_purchs_files` 1.104), días **2026-08-01 .. 2026-08-11**, de la época del upsert con ids
  nuevos. Con append-only ya no se generan más, pero hay que **borrarlas una vez** (y/o
  re-materializar agosto) para que `moves` recupere `serv_desc`/`qnt` de esos días.
- **Nota de `period`**: las filas de details/files insertadas antes del rediseño llevan la clave
  **diaria** (`"2026-09-10"`) y las nuevas la **mensual** (`"2026-09-01"`); la detección de
  faltantes es por FK, así que no se duplica nada. Normalizar (`substr(period,1,7)||'-01'`) es
  cosmético y opcional.
- **Ruta del repo**: `/home/josemi/Desktop/ADCOR_PROJECTS/REPOAIMNUEVO`. Ojo: los **console scripts
  de `.venv/bin` están rotos** (shebang con la ruta vieja `/home/josemi/Desktop/REPOAIMNUEVO/...`),
  así que `dagster`, `dagster-daemon` y `dagster-webserver` fallan: usar
  `.venv/bin/python -m dagster ...` o recrear el venv.

---



# Active Context — Estado actual

> Solo estado presente (sin historial). Actualizar al terminar cada sesión.

## Cómo está montado hoy
- **Punto de entrada único**: `definitions.py` (**raíz del repo**, con el `[tool.dagster]`
  de `pyproject.toml`; los assets, `jobs.py` y los tests viven en `src/`) → 19 assets + los
  resources + los 7 jobs de `src/jobs.py`.
- **Capa de integración**: SQLite **`db.sqlite`** (31 tablas) compartida por todos
  los modelos peewee; cada `db_resource` la inicializa con `db.init(...)` +
  `create_tables`.
- **Capa analítica**: dbt en `src/dbt` (24 modelos:
  6 tablas + 18 efímeros, **0 seeds**); materializa en `analytics_poc.duckdb` leyendo
  `db.sqlite`. Se puede correr por CLI (`cd src/dbt && dbt run`) o, desde el 2026-09-17,
  como **asset** `dbt_run` del grupo `dwh` (sin particiones, con `deps` de las 14 fuentes que
  dbt lee: desde el 2026-09-23 **no** `sire_files_monthly` (`sire_*_files`), `ingest_emails`
  (`emails`/`email_attachments`) ni `corpac_files_daily` (`from_email_corpac_files`), cuyas
  tablas no lee ningún modelo).
  El asset Dagster `movimientos` (`datawarehouse_assets/`) se eliminó.
- **Publicación**: el asset `publish_dwh` (grupo `dwh`, `deps=[dbt_run]`; credenciales PG del
  entorno; **el motor entero vive en `DwhPublishResource`**,
  `src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py`, que es también su
  CLI) **lee `analytics_poc.duckdb`** y publica
  **todas** sus tablas en el esquema `dwh` **con el mismo nombre** (`moves`,
  `calendar`, `partners` y los `static_*`);
  crea lo que falte (tipos mapeados desde DuckDB), añade columnas nuevas con
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` y hace `DELETE` + `COPY` (sin `DROP`,
  hay vistas encima). Flags del CLI: `--duckdb`, `--schema`, `--only`, `--exclude`,
  `--dry-run` y
  `--recreate` (DROP+CREATE, para cambios de TIPO: el `CREATE IF NOT EXISTS` no los
  cambia). **Corrida completa del 2026-09-16** (asset estático → `dbt run` → publish):
  `static_data_asset` partición `2026` en verde (ambulancia 474, LAP 1.867, planilla
  2.098, RH 1.615 de 9 meses, maestros 96/11/28 y auxiliares 91/78/9), `dbt run`
  PASS=6 en 2,57 s y `sync_db.py` **6 tablas / 57.135 filas** (`moves` 45.376,
  `partners` 11.292, `calendar` 332, `static_master_accounts` 96,
  `static_cost_centers` 28, `static_airplanes` 11), con los conteos
  `duckdb == postgres` verificados tabla por tabla. El usuario limpió los restos
  (2026-09-16): el
  DuckDB y el `dwh` tienen solo las tablas del pipeline, más la vista
  **`dwh.vista_reporte_gerencial`** que creó él (el script la avisa como "no está en
  el DuckDB" porque `information_schema` también lista vistas: es normal). `dwh.moves`
  con los tipos reales (`date`/`integer`/`bigint`/`numeric`).

## Cambios del 2026-09-23 (desacople de SIRE respecto de la propuesta)
- **`dbt_run` ya no depende de 3 assets de ingesta cuyas tablas no lee ningún modelo, macro ni test
  de dbt**: `sire_files_monthly` (`sire_sales_files`/`sire_purchs_files`), `ingest_emails` (`emails`/
  `email_attachments`) y `corpac_files_daily` (`from_email_corpac_files`). Eran deps de más que
  ataban el DWH a la descarga de PDF/ZIP de SIRE, a Gmail y a las descargas del portal CORPAC (los
  eslabones más lentos y los que venían fallando). `FUENTES_DBT` pasa de 17 a **14** fuentes (de la
  cadena de correo se quedan los assets que **parsean**: `corpac_data_daily`, `adp_reports_daily`,
  `terpel_tickets_daily`, `terpel_order_daily`); lo fijan `tests/test_dwh_assets.py` y
  `tests/test_jobs.py`.
- **Los 3 `*_cost_centers_monthly` ya no consultan `sire_purchs`**: `select_zip_files` identifica los
  ZIP del proveedor por el RUC con el que SUNAT nombra el archivo (`nom_archivo LIKE '<RUC>%'`) y se
  apoya en la integridad referencial (`sire_purchs_files.sire_purch`). Pueden llenar sus tablas con
  los ZIP que ya estén descargados sin volver a mirar la propuesta.
- **Los 3 cost centers dependen SOLO de `sire_files_monthly`** (la propuesta entra por
  transitividad): el orden del run garantiza que los ZIP del mes ya están descargados cuando toca
  extraer las aeronaves. Consecuencias asumidas a propósito (se probó a dejarlos sin deps el
  2026-09-23 y se revirtió el mismo día): (a) si `sire_proposal_monthly` falla (p. ej. el HTTP 429
  de SUNAT), Dagster salta `sire_files_monthly` y con él los cost centers; (b) `sire_files_monthly`
  sigue siendo **ancestro indirecto** de `dbt_run`, porque los cost centers son fuentes de dbt (la
  dep directa `dbt_run -> sire_files_monthly` sí está quitada). Lo fijan
  `tests/test_jobs.py::test_los_cost_centers_dependen_solo_de_los_archivos` y
  `tests/test_jobs.py::test_el_dwh_no_tiene_sire_files_como_dep_directa`.
- **Salud de datos a revisar**: `sire_purchs_files` está **vacía** (0 filas) mientras los cost centers
  tienen 383 filas (cep 214 · icaro 163 · petroperú 6) con su `id_file` colgando: son restos de la
  limpieza de los 5.370 huérfanos. Como la identidad del cost center es `(id_file, aeronave)`, si los
  ZIP entran otra vez con ids nuevos se re-insertarán las mismas aeronaves (y quedarán las filas
  viejas). Decidir: borrar las viejas o convivir con ambas.

## Políticas de backfill: reparto definitivo — 2026-09-23
- **Regla**: la política la fija el **coste** de una partición (no el código): si es barata
  (1 partición por llamada y rápida) ⇒ `single_run()` (rango completo en **un run**, recorrido con
  `partition_days` y `MaterializeResult` sin valor); si es cara (descarga + parseo por día) ⇒
  `multi_run(max_partitions_per_run=30)` (runs de hasta 30 días, recorridos día a día con
  `procesar_dia`).
- **Bug encontrado y arreglado**: `calendar_weekly` y `sisa_sales_monthly` declaraban
  `single_run()` pero leían `context.partition_key` ⇒ al materializar un rango el step caía con
  `DagsterInvariantViolationError`. **NO se les bajó la política** (son baratos y el usuario
  quiere el rango en un solo run): se les hizo **soportar** el rango con
  `procesar_semana`/`procesar_mes` + `partition_days(context)` + `MaterializeResult` sin valor, y
  la caché de meses de `calendar_weekly` se comparte en todo el run.
- **Reparto** (tests: `tests/test_correos_particiones.py`, `tests/test_jobs.py`,
  `tests/test_calendar_asset.py`, `tests/test_sisa_sales_asset.py`,
  `tests/test_corpac_files_asset.py`, `tests/test_corpac_data_asset.py`):
  - `BackfillPolicy.multi_run(max_partitions_per_run=30)`: `ingest_emails` y
    **`corpac_files_daily`** (antes sin política), que iteran `partition_days(context)` con la
    lógica de un día en `procesar_dia` y devuelven `MaterializeResult` sin valor.
  - `BackfillPolicy.single_run()`: **`corpac_data_daily`** (antes `multi_run(30)`), los 4 reportes
    de correo (`talma`/`adp`/`terpel_tickets`/`terpel_order`), **`calendar_weekly`** y
    **`sisa_sales_monthly`** (el rango entero en un run, recorrido con `partition_days`).
  - Sin política: `static_data_asset` (partición estática); `dbt_run`/`publish_dwh` sin particiones.
- **Efecto en el job**: `correo_daily_job` resuelve `multi_run(30)` (Dagster se queda con la
  política mínima; el aviso se silencia en `jobs.py`). Consecuencia heredada del CLI: como **no**
  todos los assets del grupo `from_email` son `single_run`, `--partition-range` sobre el grupo está
  **rechazado** por diseño (usa `--partition`, un `--select` de los assets `single_run` o un
  backfill con demonio). `calendar_weekly` y `sisa_sales_monthly` sí aceptan `--partition-range`
  (van solos en su job).
- **Validado en vivo** (Dagster in-process, recursos stub): `calendar_weekly` con el rango
  `2026-09-14...2026-09-21` y `sisa_sales_monthly` con `2026-08-01...2026-09-01` → **1 run cada uno,
  RUN_SUCCESS**, con un upsert por partición y la metadata agregada del run.
- **Pendiente detectado (decisión del usuario: se queda así)**: `sire_details_monthly` y
  `sire_files_monthly` **no** declaran `backfill_policy` **a propósito** (= `multi_run(1)`: 1 run
  por mes). Efecto: `sire_monthly_job` resuelve `multi_run(1)` (con su `UserWarning` de políticas
  mixtas) y `dagster asset materialize --partition-range` **rechaza** cualquier selección que los
  incluya (también `--select "group:from_sire"`), con
  `DagsterCheckError: Partition ranges with the CLI require all selected assets to have a
  BackfillPolicy.single_run() policy...`. **No rompe nada del pipeline**: se lanza mes a mes con
  `--partition <mes>` (2 runs) o con un backfill de la UI/daemon, que es justo lo que quiere esa
  política. Los otros 4 del grupo sí son `single_run()`.

## Assets presentes (19)
`ingest_emails`, `corpac_files_daily`, `corpac_data_daily`, `sire_proposal_monthly`,
`sire_details_monthly`, `sire_files_monthly`, `sisa_sales_monthly`,
`terpel_tickets_daily`, `terpel_order_daily`, `adp_reports_daily`,
`talma_reports_daily`, `cep_cost_centers_monthly`, `icaro_cost_centers_monthly`,
`petroperu_cost_centers_monthly`, `seesol_rh_monthly`, `static_data_asset`,
`calendar_weekly`, **`dbt_run`** y **`publish_dwh`** (los 2 últimos, grupo `dwh`, **sin
particiones**: ver el bloque de arriba).

## Tablas de `db.sqlite` (31)
`ambulancia_ventas_reports`, `dwh_calendar`, `dwh_proveedores`,
`dwh_static_airplanes`, `dwh_static_cost_centers`, `dwh_static_master_accounts`,
`email_attachments`, `emails`, `from_email_adp_reports`, `from_email_corpac_details`,
`from_email_corpac_files`, `from_email_corpac_headers`, `from_email_talma_reports`,
`from_email_terpel_order`, `from_email_terpel_tickets`, `from_sire_cep_cost_centers`,
`from_sire_icaro_cost_centers`, `from_sire_petroperu_cost_centers`, `lap_reports`,
`planilla`, `seesol_rh`, `sire_purchs`, `sire_purchs_details`, `sire_purchs_files`,
`sire_sales`, `sire_sales_details`, `sire_sales_files`, `sisa_sales`,
`static_aux_accounts_assignment`, `static_aux_airports`,
`static_aux_cost_centers_override`.

## Fuentes de origen
- **Gmail** (`jorge.paredes@airmajoro.com`, `contabilidad@airmajoro.com`) →
  `ingest_emails` → `emails` / `email_attachments` (**append-only y con descarga
  incremental**: lista ids → descarta los ya guardados → baja solo los nuevos).
- **Por correo** (los 7 diarios y en el grupo `from_email`): CORPAC
  (`corpac_files_daily` → `from_email_corpac_files`; `corpac_data_daily` →
  `from_email_corpac_headers`/`_details`), ADP (`adp_reports_daily`), TALMA
  (`talma_reports_daily`) y TERPEL (`terpel_tickets_daily` + `terpel_order_daily` desde ZIP).
  Diseño (particiones compartidas, políticas y cron): ver el bloque de arriba.
- **SUNAT/SIRE**: `sire_proposal_monthly`, `sire_details_monthly` (CPE por API) y
  `sire_files_monthly` (PDF/ZIP); de `sire_purchs_files` salen los `*_cost_centers`
  (CEP / ÍCARO / PETROPERÚ), que **no consultan `sire_purchs`**: el proveedor sale del
  RUC con el que SUNAT nombra el ZIP (`nom_archivo LIKE '<RUC>%'`) y la FK
  `sire_purchs_files.sire_purch` garantiza el vínculo con la compra (2026-09-23).
- **API SISA**: `sisa_sales_monthly` (liquidaciones por empresa/sede).
- **Estáticos** (`static/`, todo al primer nivel): `VENTAS-C X C 2026_ACT 14-09-2026.xlsm` →
  `ambulancia_ventas_reports`; `LAP_Aeronave_20260902_170205.xlsx` → `lap_reports`;
  `Planilla.ods` → `planilla`; y los **6 CSV** → sus 6 tablas homónimas. Los TXT
  `static/RH/<empresa>/0X.txt` (meses 01–09) que alimentaron `seesol_rh` **ya no los lee
  el pipeline**: `seesol_rh` lo llena el asset `seesol_rh_monthly` por HTTP (ver el
  bloque del RH arriba); esos ficheros quedan solo como histórico.
- **Tipo de cambio**: `calendar_weekly` → `dwh_calendar`.

## Estáticos: cómo está hoy
- **Layout**: TODOS los archivos al **primer nivel de `static/`** (`VENTAS*.xlsm`,
  `LAP*.xlsx`, `Planilla.ods` y los 6 CSV); la **única subcarpeta** es
  `static/RH/<empresa>/MM.txt` (histórica: ya no la lee nadie). La subcarpeta
  `static/static_assets/` se eliminó y con ella se actualizaron las rutas del código:
  `STATIC_DIR = <repo>/static` y `seed-paths: ["../../static"]` (dbt). El antiguo
  `STATIC_RH_DIR` desapareció con el `RhResource` de ficheros; el resource HTTP del RH
  no lee disco (solo `env/sire_credentials.json`).
  Re-validado el 2026-09-16 rematerializando el asset (mismos conteos).
- UN asset (`static_data_asset`, partición estática `"2026"`) y UN resource
  (`static_data_db`, clave `static_data_db`); el asset **ya no** recibe el resource del RH
  (antes `rh`; ahora `seesol_rh_monthly` tiene los suyos: `rh` y `seesol_rh_db`).
- Última corrida real (2026-09-16, `dagster asset materialize --partition 2026`,
  6 s): `ambulancia_ventas_reports` 474 · `lap_reports` 1867 · `planilla` 2098 ·
  `dwh_static_master_accounts` 96 · `dwh_static_airplanes` 11 ·
  `dwh_static_cost_centers` 28 · `static_aux_accounts_assignment` 91 ·
  `static_aux_airports` 78 · `static_aux_cost_centers_override` 9 (el `seesol_rh` 1615
  de 2026-01…2026-09 que veía esa corrida venía del paso del RH, hoy ya separado).
  **Ojo**: los CSV los edita el usuario en LibreOffice (a veces hay `.~lock.*` en la
  carpeta), así que los conteos cambian; no fijarlos en el código.
- Comprobado fila a fila que `parse_csv` == `read_csv_auto` (el comportamiento
  anterior de dbt) == tabla de SQLite en las 6 tablas: cambiar de leer el CSV a leer
  la BD no altera ningún dato.

## dbt: estado
- 24 modelos: **6 tablas** (`moves`, `partners`, `calendar`,
  `static_master_accounts`, `static_airplanes`, `static_cost_centers`) y
  **18 `ephemeral`** (los 3 `aux_*`, `ambulance_sales_std` y las ramas de
  compras/ventas/labor).
- `moves` = 26 columnas, alimentado por `purchs_std` ∪ `sales_std` ∪ `labor_std` +
  el override de centro de costo y **con los tipos del DWH ya aplicados**
  (`doc_date`/`doc_due_date`/`serv_date` DATE, `doc_type` INTEGER, `doc_number`
  BIGINT, `qnt` DECIMAL(18,3), `amnt_taxable`/`amnt_taxes` DECIMAL(18,6), `error`
  VARCHAR; todo con `TRY_CAST`, así un valor raro queda NULL en vez de romper dbt).
- **`sales_std`**: solo `UNION ALL`, una fila por documento (`doc_serie` +
  `doc_number`) con prioridad **ambulancia > SISA > SIRE**; **no** asigna `account`
  ni `move_type` (las 474 filas de ambulancia salen con `move_type` NULL). `amb_docs`
  lee **todos** los documentos del array `agregado_factura` (22 vuelos traen 2
  facturas). `ambulance_sales_std` emite las 26 columnas del contrato (las 7 técnicas
  en NULL) + `observaciones`.
- **`models/static/`: el nombre del modelo es el de su tabla** (`dwh_static_*` /
  `static_aux_*`): los `ref()` de `purchs_std`, `moves` y el macro
  `obtener_aeropuerto` dependen de ese nombre. Renombrarlos a nombres cortos
  (`airplanes`, `aux_airports`, `cost_centers`…) **rompe la compilación** (pasó el
  2026-09-16).
- Sin `schema.yml` ni tests de dbt.
- **Validado el 2026-09-16** con un perfil **temporal en `/tmp`** (DuckDB de /tmp con
  `db.sqlite` adjunto, para no pelear con el lock): `dbt run` = **PASS=6, ERROR=0**.
  `moves` 45.376 filas (Compras 24.146 · Ventas 18.658 · Planilla 2.098 · ambulancia
  474); `ambulance_sales_std` es efímera (no materializa tabla); solapamiento SISA/SIRE por
  (serie, número) = **0**; 9.322 documentos de SIRE ya venían por SISA y 319 por el
  array de ambulancia (antes se duplicaban).
- **`dbt run` sobre el `analytics_poc.duckdb` REAL: HECHO el 2026-09-16**
  (`cd src/dbt && dbt run` → PASS=6 en 2,57 s). DBeaver estaba abierto pero **sin el
  fichero adjuntado**, así que no hubo lock: DuckDB solo bloquea si hay una conexión
  viva a `analytics_poc.duckdb`.

## Pendientes conocidos / trampas
- **`public.vw_move_reporte_gerencial` ya NO existe** (el schema `public` se eliminó
  el 2026-09-16). El único objeto no materializado del DWH es la vista
  **`dwh.vista_reporte_gerencial`**, ya reapuntada al pipeline nuevo: `FROM dwh.moves`
  + `LEFT JOIN dwh.static_master_accounts` (por `m.account = codigo_pcge`),
  `dwh.calendar` (por `cal.date = doc_date`) y `dwh.partners` (por `codigo =
  partner_doc`); filtra 2026, calcula `subtotal_base_soles` con el tipo de cambio si
  la moneda es USD y excluye los pagos adelantados de TERPEL. Las tablas antiguas
  (`dwh.movimientos`, `dwh.cuentas`, `dwh.proveedores`, `dwh.centros_de_costo`,
  `dwh.mae_cuentas`) **ya no existen**.
- **Restos del DuckDB/DWH: LIMPIADOS por el usuario (2026-09-16)**. Se borraron las
  tablas viejas del DuckDB (`dwh_movimientos`, `dwh_static_*`, `static_aux_*`,
  `dwh_ambulance_sales_std`, `dwh_master_accounts`) y sus homónimas del DWH. Ya no hay
  que limpiar nada: el DuckDB tiene 6 tablas y el `dwh` esas 6 + la vista.
- **5 valores de `moves.account` NO están en el maestro de cuentas** (pre-existente,
  no vienen del CSV de asignación): `700000` (8.967 filas, literal de
  `sire_sales_std`), `700001` (474, literal de `ambulance_sales_std`), `704104`
  (4.046, de SISA), `704105` (179, de SISA) y **`'Planilla'` (2.098 filas: el literal
  de `payroll_std.sql`, es una ETIQUETA y no un código PCGE)**. El maestro tiene
  704101-704103 y 703201-703206: falta que contabilidad decida si se añaden o se
  reapuntan. **Impacto medido en `dwh.vista_reporte_gerencial` (2026-09-16): 14.093 de
  43.154 filas salen sin `cuenta_contable_descripcion`** (32,6%).
- **Refresco real + publicación hechos el 2026-09-16**: materializado el asset estático
  (partición `2026`, 6,82 s de step) → `dbt run` sobre `analytics_poc.duckdb` (PASS=6)
  → `python sync_db.py` (6 tablas / 57.135 filas), así que `dwh.moves` está con datos
  **y tipos** frescos (`date`/`integer`/`bigint`/`numeric`). La cadena de cuentas del
  CSV auxiliar está viva: **22.531 filas de Compras** (28 códigos distintos) toman su
  `account` de `static_aux_accounts_assignment`.
- **Ningún modelo consume los 3 maestros `dwh_static_*`** todavía.
- Precedencia de cuentas: `length(serv_desc_pattern) DESC` (el CSV ya no trae `orden`).
- `db.sqlite` ~19 GB; DuckDB solo da lock si DBeaver tiene `analytics_poc.duckdb`
  **abierto** (el 2026-09-16 DBeaver estaba corriendo sin el fichero adjuntado y el
  `dbt run` pasó).
- Credenciales Postgres en claro en el README (y por defecto en el código antiguo).
- README.md incluye mucho prompt histórico al final (no es documentación técnica).

## Power BI / Power Query
- `docs/powerquery/formatoeerr.m`: M de **una sola consulta** (`formatoeerr`) que
  cruza `LOCAL_SHARED/FORMATOCUENTAS.csv` (`tipo`,`cuenta`) con
  `dwh.static_master_accounts` por `codigo_pcge` (LEFT JOIN) y devuelve
  `tipo | cuenta | grupo | grupo_orden | descripcion | orden_fila`. La tabla de
  grupos se calcula dentro de la propia consulta (Table.Group + primera aparición
  + AddIndexColumn) y se une con un segundo LEFT JOIN por `grupo`. Las filas
  `tipo = METRICA` no cruzan con el maestro: su grupo es su propio texto y
  **también** consumen número (12 grupos hoy). Es documentación de referencia para
  el reporte, no parte del pipeline de Dagster/dbt.

## Estado de Resultados como modelo dbt (2026-09-25)
- **Nuevo modelo `dashboard/estado_resultados`** (`src/dbt/models/dashboard/`,
  `materialized='table'`): EERR listo para el BI. Trae **todas** las cuentas de
  `static_master_accounts` (aunque tengan importe 0) ordenadas por
  `static_master_account_groups.orden`, con `tipo` CUENTA/MEDIDA. Las filas MEDIDA
  (UTILIDAD BRUTA, RESULTADO OPERATIVO…) traen el **acumulado por `orden`** de las
  cuentas anteriores (con el signo ya volteado, "ventas − conceptos anteriores" sale
  solo). Grano (anio, mes, …); importe = `amnt_taxable` (base, sin IGV) en soles con
  tipo de cambio del `calendar` si es USD. Se publica sola como `dwh.estado_resultados`.
- **La volteada vive en el ORIGEN, en `moves`**: `amnt_taxable` y `amnt_taxes` se
  multiplican por `CASE WHEN move_type ILIKE 'Ventas%' THEN 1 ELSE -1 END`, así que
  todo lo que **no** es venta queda NEGATIVO. Para que sea consistente se quitaron las
  negaciones manuales de las ramas de reportes (**CORPAC, ADP y LAP**): ahora traen
  FACTURA positiva y NOTA DE CRÉDITO (tipo 7) negativa, igual que `sire_purchs_std`
  (CORPAC ya usa `prefer_equal_neg`). Consecuencia: `dwh.vista_reporte_gerencial`
  (Power BI) verá las compras en **negativo** desde ahora.

### `doc_date` sin huecos en `moves` — el EERR ya no pierde filas (2026-09-25)
- **Problema**: el EERR filtra `WHERE m.doc_date IS NOT NULL`, así que toda fila sin
  fecha se caía del reporte. Faltaban **30.741** (30.658 de planilla + 83 de ventas).
- **Planilla** (`labor/payroll_std.sql`): `p.fecha` es poco fiable (formatos mezclados);
  se sustituyó por un `{% set %}` Jinja que arma `YYYY-MM-01` desde `periodo` (año) +
  `mes` (mes) con `safe_int` + `lpad`, usado en `doc_date` **y** `serv_date`.
  ⚠️ **Trampa**: `{% set %}`/`{% endset %}` **sin** guiones; con `{%- endset -%}` se comía
  el salto de línea y el SQL salía `fecha.SELECT`.
- **Ambulancia** (`sales/from_reports/ambulance_sales_std.sql`): `doc_date` venía del SIRE
  por LEFT JOIN; si el vuelo no estaba en SIRE quedaba NULL (**74 filas / ~2,39 M**, las
  más gordas). Ahora `coalesce(CAST(s.fecha_de_emision AS VARCHAR), b.fecha_vlo)`. El
  `CAST` es **obligatorio**: `COALESCE(DATE, VARCHAR)` en DuckDB da *Binder Error*.
- **Selva** (`sales/from_reports/selva_sales_std.sql`): la celda FECHA trae erratas.
  Nuevos CTE `parsed` (tolera coma: `'26,05.25'` → `26.05.25`), `periodo_hoja` (año-mes
  **modal** de la hoja: la hoja *es* el mes, y el modo aguanta erratas de año suelto) y
  `docs` = fecha de la celda si es plausible, si no el día 1 del mes de la hoja. Además
  **guarda de año ±1** vs. el año de la hoja: `SELVA ABR-25` traía un `2029-04-28` que
  metía un periodo **2029 fantasmal** en el EERR (4 filas). Las 2 filas con el Nº de
  documento volcado en la celda FECHA (`SELVA DIC`/`SELVA NOV`) también se rescatan así.
- **Validación** (`dbt run`: **PASS=10**; `moves` = 99.457 filas): `doc_date` NULL = **0**;
  EERR = 57.267 filas, **27 CC**, periodos **2025-01…2026-09** (sin 2029); control
  **VENTAS EERR 36.022.713,70 = suma de `moves` convertida a PEN** (idéntica); 0 medidas
  desviadas; 0 importes NULL; 0 ventas USD sin tipo de cambio; 2026-02: VENTAS
  2.134.700,26 / CARGAS DE PERSONAL −334.607,75 / UTILIDAD BRUTA 459.964,03 / RESULTADO
  OPERATIVO −776.427,12. Las 2 cuentas de gasto con importes positivos son **notas de
  crédito (doc_type 7)**: comportamiento correcto (reducen el gasto).
- **PUBLICADO a `dwh` (2026-09-25)**: `publish_dwh` en 2 pasos → `dwh.estado_resultados`
  **57.267 filas** (13 columnas, 27 CC, 11 grupos, meses "1. Enero"…"12. Diciembre",
  2025-2026) y las otras 10 tablas **142.548 filas** (`moves` 99.457). Verificado **desde
  Postgres**: `moves` 99.457/99.457 con `doc_date` (rango 2025-01-01…2026-09-23, sin 2029);
  EERR VENTAS 70xx = **36.022.713,70** (idéntico al DuckDB); 0 filas en 2029;
  `vista_reporte_gerencial` (Power BI) sigue viva con 78.711 filas.
- ⚠️ **Trampa del publish**: `estado_resultados` cambió de TIPOS (`mes` pasó de INTEGER a
  la etiqueta VARCHAR). El publish normal **falla** con
  `InvalidTextRepresentation: invalid input syntax for type integer: "1. Enero"`, porque
  `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN` no tocan los tipos ya existentes. Hay que
  recrear **solo esa tabla** (nada depende de ella):
  `publish_resource.py --only estado_resultados --recreate` y luego
  `publish_resource.py --exclude estado_resultados`. **No** usar `--recreate` a secas:
  soltaría `moves` y con él la vista `dwh.vista_reporte_gerencial`.
- **Pendiente del usuario**: **re-sincronizar el esquema del BI** para que vea las
  columnas nuevas (`mes` como etiqueta, `mes_num`, `cost_center`).



### Auditoría de duplicados en `moves` — veredicto y causa raíz (2026-09-28)
- **Veredicto**: los **10.170** sobrantes de **Compras** son **duplicación real** de la
  ingesta, no líneas de factura repetidas. Las **Ventas no están infladas** (sus líneas
  repetidas cuadran con el `total_cp` de la cabecera SIRE).
- **Raíz (nivel correo)**: `emails` tiene 27.647 filas con **6.599 grupos repetidos** por
  `(sender, subject, header_date)` y solo 2 buzones (`jorge.paredes@`, `contabilidad@`).
  El asunto CORPAC `F025-00028694 …` existe 2 buzones × **8 mensajes del mismo hilo**
  (mismo `thread_id`, `header_date` 10:45:16→10:45:24, el **mismo PDF** adjunto en cada
  auto-respuesta) = **16 copias**. `append_emails` deduplica por `id` (id de Gmail), así
  que la idempotencia por `id` **no cubre réplicas** del mismo mensaje en hilo/buzón.
- **Propagación CORPAC**:
  - `from_email_corpac_files`: 11.312 filas / 5.756 `filename` (clave `(id_email,
    filename)`: el mismo PDF con otro `id_email` entra).
  - `procesar_dia` parsea **todos** los ficheros del día y concatena: crea **una cabecera
    por copia** y cuelga **todas** las copias de detalles de la **última**
    (`header_ids[(filename, _section)]` se sobreescribe). Ej. medido: factura
    `F0250028694` → 16 cabeceras (6548…6602) y 32 detalles, **los 32 colgando de 6602**.
  - `from_email_corpac_headers`: 3.668 filas vs 1.862 `(filename, matricula)`;
    **1.580 facturas** con >1 cabecera. `from_email_corpac_details`: 14.783 filas,
    **7.235 sobrantes** (clave `(header_id, servicio, fecha_llegada, fecha_salida)`, ×16).
  - `corpac_purchs_std` hace JOIN por `factura` a **todas** las cabeceras → cada línea ×N.
  - **Impacto**: `moves` CORPAC 14.715 filas → 5.935 distintas (**8.780 sobrantes**),
    gasto **−345.748,57** vs **−160.435,95** deduplicado = **185.312,62 duplicado (2,15×)**.
- **Prueba de cuadre** (Σ líneas del reporte ÷ nº de copias = `total_cp` SIRE):
  F0250028694 → 737,92/16 = 46,12 ≈ **46,11**; F0250028693 → 570,56/16 = **35,66**;
  F0510002723 → 1.780,66/14 = **127,19**; F0010157553 → 1.251,12/**2** = **625,55**.
- **Factor por factura** (importe reporte ÷ `total_cp`): **×2 → 1.273 facturas**
  (187.846,99), ×3 → 11, ×7/×12/×14 → 5, **×1 → 253** (correctas), ×0 → 159 (el PDF de
  "detalle de servicios" no cubre toda la factura).
- **Otros focos**: `from_email_adp_reports` 185 filas sobrantes (misma operación 2×; 626
  filas/3.451,76 en `moves` incluyendo repetidas legítimas) y `from_email_talma_reports`
  471 (no alimenta `moves`). `static_payroll` 310 grupos/1.950 es **falso positivo** (faltaba
  `mes` en la clave); `payroll_std` sí tiene **22 duplicados reales**.
- **Falsos positivos descartados (no tocar)**: Ventas (F006-22910 4×350 = 1.400 = `total_cp`;
  1.200; 1.600; 1.550), ADP (54 filas idénticas = 54 `nro_operacion` distintos: `moves` las
  colapsa porque no exporta `nro_operacion`), LAP/ambulancia (importes 0,00 o fechas
  distintas), `cost_centers` (`car_sunat` único por rama → el LEFT JOIN no multiplica).
- **Riesgos latentes**: `ambulance_sales_std` LEFT JOIN a `sire_sales` sin `removedups`
  (0 filas afectadas hoy, pero hay 152 cabeceras SIRE duplicadas); `removedups` **no pierde**
  importe (0 casos con la copia de `MIN(id)` sin detalles).
- **Arreglo aplicado (ingesta) — 2026-09-28**: en vez de parchear el dbt se arregla la
  **ingesta**, que es donde está la duplicación. El criterio nuevo es **un documento =
  un `filename`** (verificado: las 5.556 copias repetidas de `from_email_corpac_files`
  tienen el contenido byte a byte idéntico y **ningún** `filename` cruza particiones):
  - `select_corpac_pdfs` (`corpac_data_asset/resources/db_resource.py`) devuelve **solo la
    copia canónica de cada `filename`** —la de menor `id` **en toda la tabla**, porque
    `corpac_purchs_std` cruza por `factura`— y anota `copies` (nº de copias) en cada fila.
    Solo lee el payload de las canónicas (los días con 16 copias ya no cargan el mismo PDF
    16 veces). El asset reporta `pdfs_duplicados_omitidos` en la metadata.
  - `upsert_day` mantiene su clave `(filename, _section)` pero con guardado: la **primera**
    fila de cada clave es la única que crea cabecera (la tabla `headers` es 1:1 con el
    documento).
  - `upsert_files` pasa a ser **una fila por documento**: deduplica por `filename` (global,
    no solo del día) además de por `(id_email, filename)`. Efecto lateral documentado en el
    docstring: el correo de la 2ª entrega se queda sin filas propias, así que un **re-run**
    de esa partición lo vuelve a descargar y lo vuelve a saltar (no se guarda el documento
    dos veces). **No** se borran las copias históricas: `select_corpac_emails` salta los
    correos con ≥1 fila y borrarlas dejaría 5.319 correos "pendientes" que en un backfill
    se re-descargarían (y el enlace del portal puede estar caducado → partición caída).
- **Rematerialización** (sin tocar la red, `corpac_data_daily` solo lee la BD):
  `python -m dagster asset materialize -m definitions --select corpac_data_daily
  --partition-range "2026-01-01...2026-09-23"` (1 run `single_run`, 3m06s, 263 días con
  cabeceras repetidas) → `from_email_corpac_headers` **3.668 → 1.862** y
  `from_email_corpac_details` **14.783 → 7.548**, exactamente el objetivo calculado a
  priori (Σ detalles actuales ÷ nº de copias = 7.548). 0 pares `(filename, matricula)`
  repetidos, 0 huérfanos, 0 `file_id` inexistentes. Luego `dbt_run` (10 modelos OK) y
  `publish_dwh` (11 tablas / 187.917 filas al schema `dwh`).
- **Resultado en `moves`**: CORPAC (partner `20100004675`) **14.715 → 7.510 filas** y
  **−345.748,57 → −173.678,74** (se eliminan 172.069,83 de gasto duplicado); con `moves`
  total 97.108 → 89.908 filas y Compras 74.399 → 67.199. Por factura: 1.701 facturas
  cruzadas, **0 multiplicadas** y filas de `moves` == detalles de la BD (7.510) en todas.
  Ej.: `F0250028694` pasa de 16 cabeceras/32 detalles (−737,92) a 2 líneas (**−46,12**) y su
  `total_cp` SIRE es 46,11.
- **Residuo (no duplicación)**: cuadre por factura contra `sire_purchs.total_cp`: 1.417 de
  1.701 facturas cuadran a <0,50 y el importe de `moves` (204.941,86) queda 16.878,42 por
  debajo del SIRE (221.820,28). Es el problema **distinto** ya identificado: hay facturas
  cuyo PDF de "detalle de servicios" no cubre el importe completo (`car_sunat IS NULL`
  excluido). No se toca aquí.
- **Descartado tras verificar**: **ADP no necesita arreglo** (los "185 repetidos" son 6
  filas con 3 adjuntos y 5 vuelos distintos para el mismo `nro_operacion`; 0 grupos de
  adjuntos ADP duplicados por `filename`+contenido), y ni talma/cep/terpel ni `cost_centers`
  propagan nada a `moves` (solo `cost_centers.sql`, `adp_purchs_std.sql` y
  `corpac_purchs_std.sql` leen `from_email_*`; los 2 últimos usan `removedups` donde toca).


## CC basura `003-` y `0B-2` de las ventas (matrículas) + corte robusto del Excel de ambulancias

- **De dónde venían** (revisado a fondo): los 2 CC raros de `moves` **no** salían del
  fichero de ambulancias sino de la columna **AVION del libro de ventas**
  (`sales_selva`, se teclea a mano), combinada con la macro `extract_cost_center`, que
  devuelve **los 4 caracteres siguientes al primer dígito**:
  - `'0B-2180'` (cero por la O; `SELVA FEB-26` filas 192/216/297 y `S.A FEB-26` filas
    2/8/21/22) → CC **`0B-2`** (3 filas en `moves`, 13.144).
  - `'003-4560'` (nº de manifiesto volcado en la celda AVION; `SELVA ENERO-2025`
    fila 39) → CC **`003-`** (1 fila, 3.305).
- **Arreglo 1 — matrículas** (`assets/utils.py:normalize_matricula`): las columnas de
  aeronave se normalizan a `'OB-1234'` (`0B-2180` / `ob.2209` / `OB2221` / `OB 1919`).
  Si la celda trae un **nº de documento** (`003-4560`, `007-1731`) se deja en blanco
  para no inventar CC. Se aplica en `parse_sales_selva` (`avion`) y en
  `parse_ambulancia_ventas` (`aeronave`).
- **Arreglo 2 — ambulancias** (`parse_ambulancia_ventas`): **debajo de la tabla la hoja
  trae OTRA tabla** (el COSTO por hora) y sus filas también tienen la columna A con dato
  (`'HORAS'`, 60, 65, 70, 75, 80) → entraban 6 filas basura (con la aeronave y la fecha
  corridas de columna). Ahora una fila solo entra si su **CODIGO tiene la forma de la
  tabla** (`ddmmaaaa`, 8 dígitos). No se corta por el primer hueco: *dentro* de la tabla
  los hay de hasta 11 filas. `static_ambulance_sales_reports`: **437 → 431** filas, sin
  perder ninguna venta (soles/dólares idénticos).
- **Verificado**: `sales_selva` 12.155 filas (mismas), `dbt run` PASS=11, `publish_dwh`
  11 tablas/**137.725 filas** (igual que antes), `dwh.moves` 92.600 filas, 0 CC raros en
  ventas, dropdown de CC de las páginas: **26 CCs** sin `003-` ni `0B-2` (la venta del
  manifiesto `003-4560` queda en **`(SIN CC)`**, lo honesto: la hoja no trae la
  aeronave). Las 5 páginas cargan con 0 errores HTTP. Tests: **660 passed** (6 nuevos).
- **⚠️ PENDIENTE GRAVE (medido, NO tocado)**: `AbstractDbResource._replace` inserta con
  `model.insert_many(batch)` y **peewee toma las columnas de la PRIMERA fila del lote**:
  los valores de las demás filas se descartan **en silencio** (los parsers omiten las
  celdas vacías, así que las filas del lote no comparten claves). Medido en
  `sales_selva`: **`total` de 1.105 filas = S/ 2.663.118,90** que nunca llegan a la
  tabla (y por tanto al EERR), más `deposito` (10.989), `tot_pax` (10.811), `saldo`
  (10.538), `contado` (10.380)... En `static_ambulance_sales_reports` **no** pierde nada
  (agregados idénticos). Arreglo propuesto (completar cada fila del lote con las claves
  del modelo antes del `insert_many`); no aplicado porque **cambia las cifras publicadas**
  del EERR (~+2,26 M neto en ventas 2025-2026): pendiente de decisión del usuario.

## Metabase fuera del proyecto (2026-10-06)

- **Ya no hay ninguna mención a Metabase** en el repo (`src`, `static`, `docs`, `memory-bank`,
  `definitions.py`, `README.md`): el BI es **Evidence** (`dashboardaim/`). Los otros repos de la
  carpeta (`dashboardaim`, `REPO_FRONTEND_AIR_MAJORO`, `REPO_BACKEND_AIR_MAJORO`, `SQL GATEWAY`)
  tampoco tenían referencias.
- **Test**: se **borra** `src/tests/test_estado_resultados_metabase.py`. Sus 3 tests de contrato
  (que **no** son de Metabase: fijan que cada grupo `tipo = 'MEDIDA'` del maestro de grupos tenga
  su pseudo-cuenta en el maestro de cuentas) se conservan, sin nombrar la tecnología, en
  `src/tests/test_estado_resultados_master_accounts.py`. Los 3 tests que leían los ficheros
  `docs/estado_resultados_metabase*.sql` ya se habían retirado antes junto con esos ficheros.
- **Maestro de cuentas** (`static/dwh_static_master_accounts.csv`): el `comentario` de las 2
  pseudo-cuentas (`UTILIDAD BRUTA`, `RESULTADO OPERATIVO`) decía «…La usa el EERR de Metabase…» →
  ahora «…La usa el EERR…». Se re-ingiró a `db.sqlite` + `dbt run` + `publish_dwh` para publicarlo.
- **Recordatorio del mecanismo** (por si vuelve la duda): el `tipo = 'MEDIDA'` **no** está en el
  maestro de cuentas (columnas `codigo_pcge, grupo, cuenta, cuenta_pcge, comentario`) sino en el de
  **grupos** (`static/dwh_static_master_account_groups.csv`: `tipo, grupo, orden`, con
  `UTILIDAD BRUTA = MEDIDA/3` y `RESULTADO OPERATIVO = MEDIDA/9`). El EERR
  (`dashboardaim/pages/estado-resultados.md`) reconoce el subtotal por el **grupo** y lo calcula con
  la regla del `cross join … where tipo = 'MEDIDA'` + `case when m.orden = 3 … / 9 … / 12 …` (el
  orden manda: 3 = VENTAS + COSTO DE VENTAS, 9 = + 4..8, 12 = RESULTADO NETO). La fila del maestro
  de cuentas solo existe para que el grupo tenga su fila-fuente en el grid cuenta × mes × CC.

## Foco activo
> Lo marca el usuario en cada tarea; no inventar el siguiente paso.
