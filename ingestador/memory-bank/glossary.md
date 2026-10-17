# Glossary — Terminología del dominio

## Contabilidad / cuentas
- **PCGE** = Plan Contable General Empresarial (Perú). Las cuentas se identifican por
  códigos de 4+ dígitos (p. ej. `6391`).
- **EERR** = Estado de Resultados (Ganancias y Pérdidas) gerencial de **Air Majoro
  S.A.** Fuente: `docs/EERR.xlsx` (hoja `EERR AIR MAJORO S.A.`).
- **Maestro de cuentas** = CSV `dwh_static_master_accounts.csv` (→ tabla
  `dwh_static_master_accounts`): `codigo_pcge` (**único**, 6 dígitos = base PCGE de 4
  + subdivisión propia `01..NN`), `grupo`, `cuenta`, `cuenta_pcge` y `comentario`
  (marca las cuentas AGREGADAS que no están en el EERR original). El CSV lo mantiene
  el usuario (puede cambiar de tamaño entre corridas).
- **`account`** = cuenta contable que dbt deja en cada movimiento; **su valor es el
  `codigo_pcge` del maestro** (FK lógica). Se resuelve con la regla de compras (**el
  CSV de asignación ya guarda códigos, no nombres**, en su columna `account`, desde el
  2026-09-16), la cuenta de origen o el default por dominio. Ojo: hay valores que **no
  están en el maestro**: `700000`, `700001`, `704104`, `704105` y el literal
  `'Planilla'` (etiqueta, no código) de `payroll_std`.
- **`cost_center`** = centro de costo (matrícula de aeronave o centro
  administrativo). Se resuelve por override → origen → `cost_center_from_serv_desc`.
- **`move_type`** = tipo de movimiento (`Compras`, `Ventas ambulancia aérea`,
  `Ventas nazca`, `Ventas selva`, `Planilla`, `RECIBOS POR HONORARIOS`, ...).
- **`company`** = empresa (`Air Majoro S.A.` / `Air Majoro Selva`).

## SUNAT / SIRE
- **SIRE** = Registro de Ventas/Compras de SUNAT; `sire_sales` / `sire_purchs` (y sus
  `_details`, `_files`).
- **API de seguridad (token OAuth2)** = `api-seguridad.sunat.gob.pe/v1/clientessol/
  {client_id}/oauth2/token/`; emite el JWT de 1 h con `grant_type=password` y el usuario
  SOL. En el proyecto lo pide `SireTokenResource` (primera vía).
- **Token manual (sesión SOL)** = el JWT que da el menú de SUNAT Operaciones en Línea para la
  **app de comprobantes**. **Ya NO se usa**: el campo `token` de `env/sire_credentials.json` se
  ignora desde el 2026-09-17 y ese token lo pide ahora el resource **automáticamente y sin
  navegador** (portal SOL por HTTP, ver `action=execute`).
- **App de comprobantes (`11.38.1.1.1`)** = entrada del menú SOL "Nueva Consulta de
  comprobantes de pago" (`/app/contribuyentems/servicio/consultacpe/...`): su apertura es la que
  entrega el token de `consultacpe`.
- **`action=execute`** = `MenuInternet.htm?action=execute&code=<item del menú>`; abre una app y
  el **servidor** del portal hace el intercambio OAuth2, respondiendo **302** al loader con
  `?token=<JWT>`. Por eso el token de `consultacpe` se consigue con HTTP puro (lo hace
  `assets/sire_assets/resources/sol_portal.py` desde el resource de tokens) y **no** hace falta
  navegador ni canjear el `code` a mano.
- **Caché de tokens** = `env/sire_tokens.json` (gitignored), dict **audiencia → empresa →
  token** con `{token, exp, recursos, origen, obtenido}`. El token obtenido se guarda bajo
  **todas las audiencias que cubre** y gana el **más fresco** (mayor `exp`); antes de pedir otro
  se consulta aquí, así que una corrida no repite logins.
- **Audiencia (`aud`)** = claim del JWT con las APIs/recursos que ese token puede
  consumir: en SUNAT llega como **string con JSON dentro** con entradas
  `{"api": "https://api-sire.sunat.gob.pe"|"https://api-cpe.sunat.gob.pe", "recurso":
  [{"id": "/v1/contribuyente/migeigv"|"/v1/contribuyente/consultacpe", ...}]}`.
  `token(name, audience, recurso)` exige que el token cubra ambos.
- **`consultacpe`** = recurso de `api-cpe` que usan los **detalles** y los **archivos**
  (`sire_details_monthly`, `sire_files_monthly`). Air Majoro lo recibe en el token de
  seguridad; **Air Majoro Selva no** ⇒ su token lo da el **portal SOL por HTTP** (`sol_portal`),
  ya sin intervención manual.
- **`migeigv`** = recurso de `api-sire` que usa la **propuesta** (`sire_proposal_monthly`,
  vía ticket/CSV).
- **CPE** = Comprobante de Pago Electrónico (factura, boleta, notas). El endpoint
  `/01` devuelve el PDF y `/02` el ZIP.
- **Tipos de documento**: `01` factura, `03` boleta, `07` nota de crédito, `08` nota
  de débito. Para NC/ND el tipo del PDF/ZIP depende del documento modificado
  (`F7`/`B7`, `F8`/`B8`).
- **`car_sunat`** = clave que combina RUC + tipo + serie + número (macro `get_car`).
  El `cost_centers` de CEP/ÍCARO/PETROPERÚ lo resuelve por su `id_file` (FK a
  `sire_purchs_files` → `sire_purchs`), **no** por el `filename` (dato inestable);
  solo TERPEL lo reconstruye desde el nombre del PDF con `cc_filename_to_car_sunat`
  (es el único sin `id_file`).
- **`doc_number`** en planilla es texto (p. ej. `'1-0059'`), de ahí que los joins con
  overrides sean TEXT.

## Fuentes y proveedores
- **SISA** = sistema de liquidaciones (API SQL Server) → `sisa_sales`.
- **CORPAC** = Corporación Peruana de Aeropuertos; facturas por su portal Mercurio.
- **ADP** = Aeropuertos del Perú; **TALMA** = servicios de aeropuerto;
  **TERPEL** = combustible (tickets + órdenes de compra);
  **LAP** = Lima Airport Partners; **ÍCARO** y **CEP** y **PETROPERÚ** = proveedores
  cuyos XML de compras traen la matrícula de la aeronave.
- **RH / seesol** = reportes de comprobantes de renta (`seesol_rh`, con `period` mensual
  por fila y `empresa`) que **descarga el asset `seesol_rh_monthly`** del SEE-SOL por HTTP
  (recibos por honorarios; ya no hay ficheros intermedios).
- **SEE-SOL** = sistema de Comprobantes de Pago Electrónicos del menú SOL (pestaña 11 →
  `11.5`). El reporte RH sale de su app **"Consulta Receptor"** (`11.5.1.1.14`,
  `cpelec001Alias?accion=LlamaCriterioConsulatRec1`), que lista los recibos por honorarios
  **recibidos** (el emisor es el profesional, el receptor la empresa) y los exporta con
  `accion=descargaConsultaReceptor` (el botón "Descargar Reporte").
- **`descargaConsultaReceptor`** = acción del POST que devuelve el `archivo.txt` del reporte
  RH (16 columnas `|`, `text/plain`). Lo pide el `api_resource` del asset
  `seesol_rh_monthly` (`assets/seesol_rh_asset/resources/api_resource/rh_resource.py`).

## Estáticos y almacenamiento
- **`static/`** = carpeta única de archivos fuente estáticos, con **todos los
  archivos al primer nivel** (no hay subcarpeta de assets: `static/static_assets/`
  se eliminó). Ahí conviven los **operativos**
  (`VENTAS*.xlsm`, `LAP*.xlsx`, `Planilla.ods`) y los **6 CSV de referencia**
  (maestros `dwh_static_*` y auxiliares `static_aux_*`). Su única subcarpeta es
  **`static/RH/<empresa>/MM.txt`** (agrupa los TXT de comprobantes de renta), que
  desde el 2026-09-17 es **histórica**: el asset `seesol_rh_monthly` descarga el
  reporte por HTTP y ya no lee esos ficheros.
- **CSV de referencia** = tablas de configuración/maestros que **el asset ingiere en
  `db.sqlite`** (`CSV_SPECS` + `replace_all`) y que **dbt lee de la BD** (ya no con
  `read_csv_auto`). Los auxiliares son: `static_aux_accounts_assignment` (RUC +
  patrón de servicio → **código PCGE**; el CSV guarda CÓDIGOS en su columna `account`
  (91 filas) desde el 2026-09-16, antes nombres), `static_aux_airports` (catálogo
  ICAO/IATA, lo usa el
  macro `obtener_aeropuerto`) y `static_aux_cost_centers_override` (override de
  centro de costo por proveedor+serie+correlativo).
- **`db.sqlite`** = capa de integración (SQLite, raíz, ~19 GB, no versionada).
- **`analytics_poc.duckdb`** = destino de dbt (no versionado).
- **`dwh_movimientos` / `moves`**: el consolidado de 26 columnas se llamaba
  `dwh_movimientos` en la época del motor SQLite; en el DWH actual esas tablas
  antiguas **ya no existen** (`dwh.movimientos`, `dwh.cuentas`, `dwh.proveedores`
  se limpiaron el 2026-09-16). Hoy el modelo dbt materializa **`moves`** en DuckDB y
  el asset `publish_dwh` lo publica como **`dwh.moves`**.
- **DWH** = destino PostgreSQL: **solo** el schema `dwh`, con las 6 tablas del
  pipeline (`moves`, `partners`, `calendar`, `static_master_accounts`,
  `static_airplanes`, `static_cost_centers`) y la vista
  `dwh.vista_reporte_gerencial` (el schema `public` ya no existe).
