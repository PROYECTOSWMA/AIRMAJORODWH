1. 
Python 3.13 instalado https://www.python.org/downloads/release/python-31315/
python --version

2. 
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\.venv\Scripts\Activate.ps1 

3. pip install -r requirements.txt

4. $env:DAGSTER_HOME="C:\Users\Josemi\Desktop\REPOAIMNUEVO\dagsterhome"
   (DAGSTER_HOME / dagsterhome sigue en la raíz del repo)
export DAGSTER_HOME="$PWD/dagsterhome"; export SIRE_VERBOSE=1

5. dagster dev
   (desde la RAÍZ del repo: definitions.py y pyproject.toml —el [tool.dagster]— están
   ahí, y el código —assets/, jobs.py— y los tests viven en src/.)

6. cd src/dbt; dbt run
   (target `dev` = DuckDB: lee db.sqlite con la extensión `sqlite` y materializa
   en analytics_poc.duckdb. El antiguo target SQLite ya no existe.)
   YA NO HAY `dbt seed` ni dbt lee los CSV: los CSV están al PRIMER NIVEL de
   static/ (carpeta ÚNICA de estáticos; las antiguas static/static_assets/ y
   static/dbt_seeds/ se eliminaron, así que NO hay subcarpeta de assets: deja
   VENTAS*.xlsm, LAP*.xlsx, Planilla.ods y los *.csv directamente en static/,
   siendo RH/<empresa>/ la única subcarpeta: esos TXT del reporte RH del SEE-SOL
   ya NO los lee el pipeline (los baja el asset seesol_rh_monthly por HTTP);
   quedan solo como histórico). Los
   ingiere el asset Dagster static_data_asset en las tablas homónimas de db.sqlite
   (maestros dwh_static_* y auxiliares static_aux_*), y los modelos de
   models/static/ leen ESAS tablas (search_path = src.main) y las copian a DuckDB.
   ORDEN OBLIGATORIO: primero materializa static_data_asset en Dagster (crea esas
   tablas en db.sqlite) y DESPUÉS dbt run; si no están, los 6 modelos fallan.
   OJO: `dbt run` ya NO actualiza las tablas dwh_* de db.sqlite; la publicación al
   DWH la hace el asset `publish_dwh` (grupo `dwh`) leyendo ESTE DuckDB (todas sus
   tablas, mismo nombre).
   Cierra DBeaver antes de correr dbt: DuckDB abre analytics_poc.duckdb con lock
   exclusivo y el run falla si otro proceso lo tiene abierto.

7. Credenciales del DWH: viven en `env/.env` (copia `env/.env.example`, rellénalo;
   `env/.env` NO se versiona). Linux/macOS: `set -a; source env/.env; set +a`
   Windows: `$env:PGHOST="<host>"; $env:PGPORT="<puerto>"; $env:PGDATABASE="<db>"; $env:PGUSER="<usuario>"; $env:PGPASSWORD="<password>"`

set -a; source env/.env; set +a
python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py


8. python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py
   (o, en Dagster, el asset `publish_dwh`: `python -m dagster asset materialize -m definitions --select publish_dwh`;
   `--dry-run` publica sin escribir y `--only`/`--exclude`/`--recreate` acotan)

   (Desde el 2026-09-17 los pasos 6 y 8 son **también** assets de Dagster, grupo `dwh`:
   `dbt_run` (dbt en proceso, CWD en src/dbt, con `deps` de las **14** fuentes que dbt lee: todas
   menos `sire_files_monthly` (`sire_*_files`), `ingest_emails` (`emails`/`email_attachments`) y
   `corpac_files_daily` (`from_email_corpac_files`), cuyas tablas no lee ningún modelo) y `publish_dwh`
   (`deps=[dbt_run]`; la publicación entera vive en `DwhPublishResource`). Equivalen a
   `python -m dagster asset materialize -m definitions --select "dbt_run,publish_dwh"`,
   y el pipeline completo (`scripts/run_pipeline.py`) los corre al final. OJO: con el
   db.sqlite actual (~19 GB) el modelo `moves`
   consume mucha memoria/disco; ver memory-bank/activeContext.md.)


## Tokens de SUNAT/SIRE (automáticos, por audiencia y cacheados)

Los tokens los resuelve **el propio pipeline**, desde los `api_resource` de SIRE: el
resource `src/assets/sire_assets/resources/token_resource.py` (`SireTokenResource`)
responde a `token(empresa, audience, recurso)` con un token que **cubre la
audiencia/recurso pedidos** y **no está caducado** (`exp`, margen 60 s). El orden es:

1. **Caché en fichero** (`env/sire_tokens.json`, junto a `sire_credentials.json`; ese
   JSON está en `.gitignore`): un
   diccionario **audiencia → empresa → token**. Si hay un token de esa empresa para
   esa audiencia, sin caducar y que cubre el recurso, se usa **sin tocar la red**.
   Cada vez que se obtiene uno, se guarda la **misma** entrada bajo **todas las
   audiencias que ese JWT cubre** (deducidas del claim `aud`) y, si ya había una, se
   conserva la **más fresca** (mayor `exp`). El fichero se escribe de forma atómica
   (tmp + `os.replace`) y con `flock`, porque los steps de Dagster corren en procesos
   distintos.
2. **API de seguridad** de SUNAT:
   `POST https://api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/`
   con `Content-Type: application/x-www-form-urlencoded` y estos campos:
   - `grant_type`: `password`  ← **ojo**: con `client_credentials` SUNAT responde
     **HTTP 204 sin body** y no hay token.
   - `scope`: el `sire_scope` de la empresa en `env/sire_credentials.json`
     (`https://api-sire.sunat.gob.pe`).
   - `client_id` y `client_secret`: de "Credenciales de API SUNAT".
   - `username`: **RUC + usuario SOL, sin espacio** (`20494626978FLYMAJOR`).
   - `password`: la clave SOL.
3. **Portal SOL por HTTP puro, sin navegador** (`resources/sol_portal.py`): sólo para
   la audiencia de comprobantes. Hace el **login del portal** (1 intento, sin
   reintentos y abortando si SUNAT ya pide captcha, `fallas >= 3`) y pide la apertura
   de la app `11.38.1.1.1`: `POST MenuInternet.htm {action:'prevApp'}` +
   `GET MenuInternet.htm?action=execute&code=11.38.1.1.1` → el portal responde **302**
   con el JWT de `consultacpe` en el `Location`. El token se comprueba en vivo contra
   api-cpe (422/200 = aceptado) y se cachea. **Sin token manual de respaldo**: el
   campo `token` de `env/sire_credentials.json` ya no se lee.
4. Si nada sirve, la materialización cae con `SireTokenError` diciendo exactamente
   por qué (no cubre la audiencia / caducado / captcha / sin credenciales).

**Qué pide cada consumidor** (claim `aud` del JWT + `recurso`):

| Consumidor | audiencia | recurso | vía |
|---|---|---|---|
| `sire_proposal_monthly` (ticket/CSV) | `https://api-sire.sunat.gob.pe` | `/v1/contribuyente/migeigv` | API de seguridad |
| `sire_details_monthly` y `sire_files_monthly` | `https://api-cpe.sunat.gob.pe` | `/v1/contribuyente/consultacpe` | API de seguridad y, si no lo concede, portal SOL |

Verificado en vivo el 2026-09-17: **Air Majoro** recibe ambos recursos en el token de
seguridad; **Air Majoro Selva NO recibe `consultacpe`**, así que sus
detalles/archivos van por el **portal SOL** de forma automática (antes había que
pegar el token a mano cada hora). La vía "de libro" sigue siendo pedir a SUNAT el
permiso `consultacpe` para el `client_id` de MSA.

**Cómo comprobarlo** (script de humo en `docs/`, sin tocar el pipeline):

```bash
# pide el token de la propuesta a la API de seguridad (no hace login) y muestra la caché
.venv/bin/python docs/smoke_token_sire.py "Air Majoro" sire
# los detalles/archivos de Air Majoro salen de la caché; OJO: con MSA y `cpe` hace
# UN login real en el portal (no lo repitas en bucle: SUNAT pide captcha con 3 fallos)
.venv/bin/python docs/smoke_token_sire.py "Air Majoro Selva" cpe
```

### Plan B documentado: `docs/sol_token_navegador.py` (Selenium headless)

**No lo usa el pipeline** (ni siquiera hace falta `selenium`: está comentado en
`requirements.txt`). Se guarda en `docs/` sólo por si algún día cambiara el flujo del
portal y la vía HTTP dejara de funcionar. Replica al navegador con Selenium + Firefox
en `-headless`: hace el login en el portal (1 intento; aborta si `fallas >= 3`), pide al
menú la app `11.38.1.1.1` igual que su propio JS (`ejecuta(...)`) y lee el JWT de la
URL o de `sessionStorage["SUNAT.token"]`. Lo valida igual que el resource (audiencia
`consultacpe` + caducidad + api-cpe) y lo deja en la **misma caché**
(`env/sire_tokens.json`), así que el pipeline lo reutiliza sin volver a pedirlo.

```bash
# comprobar el entorno SIN mandar credenciales (arranca Firefox, llega al login, mira `fallas`)
python docs/sol_token_navegador.py --dry-run
# conseguir el token de una empresa (1 login real; aborta si SUNAT ya pide captcha)
python docs/sol_token_navegador.py --empresa "Air Majoro Selva"
# validarlo sin escribir la caché, o viendo la ventana para depurar
python docs/sol_token_navegador.py --empresa "Air Majoro Selva" --sin-guardar
python docs/sol_token_navegador.py --empresa "Air Majoro Selva" --visible
```

Verificado en vivo el **2026-09-17** (~30 s, token de Air Majoro Selva aceptado por
api-cpe con HTTP 422). En el **servidor** haría falta `selenium`, **`firefox`** y
**`geckodriver`** visibles para el usuario del cron (`GECKODRIVER` / `FIREFOX_BIN` o
`--driver` / `--binario`; el perfil va a `logs/ff_perfil` y **nunca** a `/tmp`, porque el
`/tmp` de los snaps es privado).

**Pipeline (solo con Dagster)**: ya **no existen scripts** (`scripts/` se eliminó). Todo se
lanza con el CLI de Dagster desde la raíz del repo; los runs van **en serie** (RH → SIRE →
cadena de correo → `dbt_run` + `publish_dwh`, que **publica**):

```bash
# ver los assets/jobs disponibles
.venv/bin/python -m dagster definitions validate

# pasos concretos (ejemplos)
.venv/bin/python -m dagster asset materialize -m definitions --select static_data_asset
.venv/bin/python -m dagster asset materialize -m definitions --select dbt_run
# dbt + publicación al DWH (exporta antes las PG* de env/.env)
.venv/bin/python -m dagster asset materialize -m definitions --select "dbt_run,publish_dwh"
```

> **Credenciales del DWH**: la publicación es el comportamiento **por defecto** (`dbt_run` +
> `publish_dwh`; `--sin-publish` la salta). `run_pipeline.py` carga `env/.env` al arrancar
> (sin pisar lo que ya esté exportado) y de ahí salen `PGHOST`, `PGPORT`, `PGDATABASE`,
> `PGUSER`, `PGPASSWORD` y `PGDWH_SCHEMA` (esquema destino, `dwh`). La publicación
> **no** leen nombres `POSTGRES_*`. Si lanzas `publish_dwh` desde la UI de Dagster (y no con
> este runner), exporta esas `PG*` en el entorno del proceso de Dagster.

> OJO: con el `db.sqlite` actual (~19 GB) el modelo `moves` de `dbt run` consume mucha
> memoria/disco (8,9 GB de *spill* medidos el 2026-09-17). Mientras no se optimice, lanza el
> pipeline con `--sin-dbt` (o quita el paso de `dbt_run` de la línea del cron) y corre
> `dbt run` a mano cuando la máquina esté libre. Detalle en `memory-bank/activeContext.md`.


### Reporte RH (recibos por honorarios) del SEE-SOL: asset `seesol_rh_monthly`

El reporte que alimenta `seesol_rh` (16 columnas separadas por `|`) se descargaba **a mano**
(Comprobantes de pago → SEE-SOL → Recibo por Honorarios Electrónicos → Consulta Receptor →
fecha inicio/fin → Buscar → "Descargar Reporte") y luego lo ingería `static_data_asset` desde
`static/RH/<empresa>/MM.txt`. Ahora es un **asset propio al primer nivel**
(`src/assets/seesol_rh_asset/`, partición **mensual**) cuya `resources/api_resource/rh_resource.py`
implementa la vía **HTTP pura** (sin navegador; el antiguo `scripts/sol_rh_seesol.py` se eliminó):

| Paso | Petición |
|---|---|
| 1 | login del portal (`descubrir_flujo` + `hacer_login`, 1 intento y aborta si `fallas >= 3`) |
| 2 | `POST MenuInternet.htm {action:'prevApp'}` + `GET MenuInternet.htm?action=execute&code=11.5.1.1.14` → **302** a la app "Consulta Receptor" |
| 3 | `POST /ol-ti-itreciboelectronico/cpelec001Alias` con `accion=CapturaCriterioConsulatRec1`, `fec_desde`, `fec_hasta` (**dd/mm/YYYY**), `tipocomprobante="01;02;03;"`, `tipoestado=00` |
| 4 | `POST .../cpelec001Alias` con `accion=descargaConsultaReceptor` → `text/plain`, `filename="archivo.txt"` |

```bash
# el asset lo hace todo: descarga el mes (1 login por empresa y mes) y upserta seesol_rh
python -m dagster asset materialize -m definitions \
  --select seesol_rh_monthly --partition 2026-08-01
# mes anterior + mes actual en un solo run (single_run), como el resto de mensuales
python -m dagster asset materialize -m definitions \
  --select seesol_rh_monthly --partition-range 2026-08-01...2026-09-01
```

El **upsert es por (mes, empresa)**: re-materializar un mes reemplaza lo que SUNAT devuelve hoy
(los recibos nuevos entran, los anulados salen) sin tocar la otra empresa ni los otros meses. Si el
mes nuevo trae menos filas que el anterior se avisa por log (mes todavía incompleto en SUNAT). Ya
**no** se escriben ficheros en `static/RH` (queda solo como histórico) ni hace falta re-materializar
`static_data_asset` para que `seesol_rh` se entere.

Verificado en vivo el **2026-09-17**: el `archivo.txt` que baja el flujo es **byte a byte**
idéntico al que se descargaba a mano (`cmp` contra ago-2026 de Air Majoro y Air Majoro Selva).
**Trampa importante**: el POST de criterios debe llevar el campo oculto
`tipocomprobante="01;02;03;"` (los tipos concatenados con `;` final, que es lo que arma el JS del
formulario a partir de sus 3 checkboxes); si se manda vacío o solo los checkboxes, SUNAT contesta
*"No se han encontrado registros"* aunque el mes sí tenga recibos.

El **cron** lo materializa para el **mes anterior y el actual** (se desactiva con `PIPELINE_RH=0`):

```bash
./scripts/pipeline_cron.sh          # incluye el reporte RH (PIPELINE_RH=1 por defecto)
PIPELINE_RH=0 ./scripts/pipeline_cron.sh
```


# PROMPT Y DESIGN DE sire_details_asset


# PROMPT Y DESIGN DE sire_details_asset 

Hola ya tenemos algunos assets ahora vamos a crear el assets\sire_assets\sire_details_asset
Para eso se llama la ruta https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes/{{senderruc}}-{{tipo}}-{{serie}}-{{numero}}-{{rol}} 
con los headers
User-Agent:Mozilla
authorization:Bearer {{token}}
Una vez por cada registro de sire_purchs y de sire_sales
La serie y el número son datos del documento que están en la tablas de sire en serie_del_cdp, nro_cp_o_doc_nro_inicial_rango tanto en purchs como en sales,
Los demás campos se llenan así
DOCUMENTOS EMITIDOS (DE SIRE_SALES) (VENTAS)
Siempre el senderruc es el ruc de la empresa (Air Majoro o Air Majoro Selva)
Siempre el rol es 1 (emisor)

Factura emitida (venta para producción). tipo_cp_doc = 1
tipo: 01 (table 10)

Boleta de venta emitida (venta para consumo). tipo_cp_doc = 3
tipo: 03 (table 10)

NC Emitida (anulación o reducción del saldo de una venta). tipo_cp_doc = 7
tipo: Si es sobre factura (tipo_cp_modificado = 1) entonces F7 si es sobre boleta (tipo_cp_modificado = 3) B7, si es otro caso dar excepcion. Siempre son esos tipos.

ND Emitida (aumento del saldo de una venta, no presente en la data). tipo_cp_doc = 8
tipo: Si es sobre factura (tipo_cp_modificado = 1) entonces F8 si es sobre boleta (tipo_cp_modificado = 3) B8, si es otro caso dar excepcion. Siempre son esos tipos.



DOCUMENTOS RECIBIDOS (DE SIRE_PURCHS) (COMPRAS)
Siempre el senderruc es el ruc del proveedor (no de la empresa), campo nro_doc_identidad
Siempre el rol es 2 (receptor)

Factura recibida (compra para producción). tipo_cp_doc = 1
tipo: 01 (table 10)

Boleta de venta recibida (compra para consumo, no presente en la data). tipo_cp_doc = 3
tipo: 03 (table 10)

NC Recibida (anulación o disminución del saldo de una compra). tipo_cp_doc = 7
tipo: Si es sobre factura (tipo_cp_modificado = 1) entonces F7 si es sobre boleta (tipo_cp_modificado = 3) B7, si es otro caso dar excepcion. Siempre son esos tipos.

ND Recibida (aumento del saldo de una compra). tipo_cp_doc = 8
tipo: Si es sobre factura (tipo_cp_modificado = 1) entonces F8 si es sobre boleta (tipo_cp_modificado = 3) B8, si es otro caso dar excepcion. Siempre son esos tipos.

Una vez que se llame devolverá un json con este formato
{
  "cntTotalReg": 1,
  "numPag": 1,
  "numRegPag": 1,
  "numeroPaginas": [
    {
      "numPagFront": 20
    },
    {
      "numPagFront": 50
    },
    {
      "numPagFront": 100
    }
  ],
  "comprobantes": [
    {
      "datosEmisor": {
        "numRuc": "20514513172",
        "desRazonSocialEmis": "AEROPUERTOS DEL PERU S.A.",
        "desNomComercialEmis": "AEROPUERTOS DEL PERU",
        "desDirEmis": "JR. DOMENICO MORELLI NRO. 110 INT. 501 (OF.501 QUINTO PISO - LA RAMBLA)",
        "ubigeoEmis": "LIMA-LIMA-SAN BORJA"
      },
      "datosReceptor": {
        "codDocIdeRecep": "6",
        "numDocIdeRecep": "20494626978",
        "desRazonSocialRecep": "AIR MAJORO S.A.",
        "dirDetCliente": "LOS CEDROS DE CORPAC AV. AEROPUERTO MZA. C LOTE. 11 A.H.    UCAYALI - CORONEL PORTILLO - YARINACOCHA . PERÚ",
        "dirDetRecepFactura": "-"
      },
      "codCpe": "F8",
      "numSerie": "F040",
      "numCpe": 399,
      "numCpeHasta": 0,
      "codMoneda": "PEN",
      "fecEmision": "19/01/2026",
      "fecRegistro": "19/01/2026",
      "codTipTransaccion": "",
      "indEstadoCpe": "0",
      "indProcedencia": "3",
      "indTituloGratuito": "0",
      "mtoVentaOpGratuita": 0,
      "desMtoTotalLetras": " NOVENTA Y TRES Y 75/100  SOLES",
      "desObservacion": "",
      "desTipoNota": "Intereses por mora",
      "informacionItems": [
        {
          "cntItems": 1.00,
          "codUnidadMedida": "ZZ",
          "desUnidadMedida": "UNIDAD",
          "desCodigo": "3300000106        ",
          "desItem": "RENDIMIENTO GANADO POR  CXC",
          "mtoValUnitario": 30.96,
          "mtoICBPER": 0,
          "mtoDesc": 0,
          "mtoImpTotal": 36.5300
        },
        {
          "cntItems": 1.00,
          "codUnidadMedida": "ZZ",
          "desUnidadMedida": "UNIDAD",
          "desCodigo": "3300000082        ",
          "desItem": "MORAS Y RECARGOS",
          "mtoValUnitario": 37.16,
          "mtoICBPER": 0,
          "mtoDesc": 0,
          "mtoImpTotal": 37.1600
        },
        {
          "cntItems": 1.00,
          "codUnidadMedida": "ZZ",
          "desUnidadMedida": "UNIDAD",
          "desCodigo": "3300000106        ",
          "desItem": "GASTO DE COBRANZA",
          "mtoValUnitario": 17.0,
          "mtoICBPER": 0,
          "mtoDesc": 0,
          "mtoImpTotal": 20.0600
        }
      ],
      "procedenciaMasiva": {
        "mtoDtoGlobalAfecBI": 0,
        "mtoTotalValVentaGrabado": 47.96,
        "mtoTotalValVentaInafecto": 37.16,
        "mtoTotalValVentaExonerado": 0,
        "mtoTotalValVentaGratuito": 0,
        "mtoTotalValVentaExportacion": 0,
        "mtoDtoGlobalNoAfecBI": 0,
        "mtoTotalDtos": 0,
        "mtoSumOtrosTributos": 0,
        "mtoSumOtrosCargos": 0,
        "mtoSumISC": 0,
        "mtoSumIGV": 8.63,
        "mtoSumICBPER": 0,
        "mtoTotalAnticipo": 0,
        "mtoImporteTotal": 93.75,
        "mtoRedondeo": 0
      },
      "numCpeRel": 0,
      "datoRelacionado": {
        "codTipNota": "01",
        "desMotivo": "",
        "documentosModificaList": [
          {
            "codCpeRelac": "01",
            "numSerieRelac": "F001",
            "numCpeRelac": "111230"
          }
        ]
      },
      "contratoEmpresarial": {
        "num_ruc": "20514513172",
        "cod_cpe": "08",
        "num_serie_cpe": "F040",
        "num_cpe": 399,
        "por_participa": "0",
        "ind_contrato": "",
        "num_contrato": "",
        "des_contrato": "",
        "cod_usuregis": null,
        "fec_regis": null,
        "cod_usumodif": null,
        "fec_modif": null
      }
    }
  ]
}

De lo cuál lo único que interesa es lo que está en informacionItems que es una lista con varios elementos, hay que crear una tabla con la estructura de esa lista que son los campos.
cntItems: entero
codUnidadMedida: char
desUnidadMedida: char
desCodigo: char
desItem: char
mtoValUnitario: decimal
mtoICBPER: decimal
mtoICBPER: decimal
mtoDesc: decimal
mtoImpTotal: decimal

Todos los decimales son a dos decimales como en otros modelos, ninguno es anulable.
En realidad serán 2 tablas sire_sales_details y sire_purchs_details. Cada una de ellas tendrá respectivamente una relación 1 a N con las tablas sire_sales y sire_purchs.
El token es el mismo que resuelve el assets\sire_assets\resources\token_resource.py (por audiencia: API de seguridad o portal SOL, y cacheado en env\sire_tokens.json)
Igualmente debe tener un api_resource que consulte la ruta y que analice y devuelva una lista de diccionarios y un modelo de bd que haga upsert para guardar y de pydantic para validar. 
Sobre los fallos esa API puede devolver a veces código 500 con el siguiente body
{
  "code": 500,
  "message": "There was an error processing your request. It has been logged (ID 4d8cccb87075125f)."
}
En ese caso se debe esperar 3 segundos y reintentar y así por 4 veces (eso debe estar en el resource) en un archivo constants. Si no responde la API entonces se debe pasar al siguiente, se debe llevar un registro de todos los que fallaron (en el asset porque el asset va a iterar en la tabla de sire) y como metadata del asset se debe colocar missing_documents con una lista con esos documentos con su emisor, tipo, serie y número.
El otro caso es si el token está mal o está vencido datá 401 con el body
{
  "status": 401,
  "message": "Unauthorized"
}
En ese caso debe dar exception y caer la materialización
El otro caso es que da 200 y da el body que te dije.
En cualquier otro código dar exception por caso no manejado.

Igual que el anterior asset debe hacer para compras y para ventas y todas las empresas de credentials (ambas empresas)

La partición de este asset estoy pensando que me gustaría que sea quicenal para tenerlo más desagregado que el otro que es el asset de sire en sus particiones. Pero por otro lado técnicamente no sé si sea posible hacerlo creo que se puede hacer con un partitionmapping, ahí es el único punto que no tengo claro a ver dime, sino tomamos la opción más clara que es que sea igualmente de partición mensual (misma partición).

Me comentas si está claro


# sire_files_asset PROMP/DESIGN
Hola, mira he creado otro asset que es el sire_files_asset en assets\sire_assets\sire_files_asset. Mira ese asset tiene la misma lógica que los demás. En este caso es más fácil porque la ruta es exactamente la misma que el sire_details_asset así como la configuración de los parámetros. Solamente que agregando un /01 al final o un /02.
En ambos casos devolverá una estructura así
{
  "nomArchivo": "20514513172-08-F040-399-XML.zip",
  "valArchivo": "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"
}

Igualmente este es un asset hijo de sire_purchs y sire_sales e igualmente habrá sire_purchs_files y sire_sales_files.
Igualmente debe en cada matrilización borrar los huerfanos y consultar los nuevos.
Las tablas hijas tendrán solamente los campos de la partición osea el día, el id del padre, el campo nomArchivo y el campo valArchivo.
Igualmente con modelo de pewee y pydantic.
Igualmente puede devolver 500, 200 o 401. Otros no (exception)
Cómo no quiero duplicar tanto código del api_resource me gustaría hacer un api_resource abstracto en los resources del sire_asset donde está el token_resource que sea details_and_files_resource que implemente el método que actualmente es 
def get_items(
        self,
        senderruc: str,
        tipo: str,
        serie: str,
        numero: int | str,
        rol: int = ROLE_EMISOR,
        *,
        empresa: str,
    ) -> list[dict[str, Any]]:
Manejando la lógica de espera todo eso.
Pero que lo haga en diferente ruta base en la cuál para los files es 01 y 02 al final.
Luego que en cada api_resource herede de ahí e implemente la demás lógica.
En cada materialización debe hacer compras y ventas, ambas empresas y para cada registro de sire tanto 01 (PDF) como 02 (ZIP) ah y una columna más que sea tipo de documento PDF o ZIP y otra que sea la empresa.

Me dices si está claro

https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes/{{senderruc}}-{{tipo}}-{{serie}}-{{numero}}-{{rol}}/01

https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes/{{senderruc}}-{{tipo}}-{{serie}}-{{numero}}-{{rol}}/02


# sisa_sales_asset PROMPT/DESIGN
He creado la carpeta assets\sisa_sales_asset
Es un nuevo asset que no tiene que ver con los anteriores, su partición es mensual y es simple porque en cada mes lo que se hace es consultar a un endpoint en la siguiente ruta
http://38.187.7.111:5500/query,
sin headers, con el siguiente body.
{
  "sql": "EXECUTE [dbo].[USP_UVW_LIQUIDACION_CONTA] @CODORGDOREF='01', @CODEMPDOREF='02', @CODSEDDOREF='06', @RAZONSOCIAL=NULL, @CODNVEDOREF=NULL, @T01TIPOPAGO=NULL, @NUMERODERUC=NULL, @FECHAINICIO='01/08/2026', @FECHATERMIN='31/08/2026'"
}
En el cuál solamente hay que variar @FECHAINICIO='01/08/2026', @FECHATERMIN='31/08/2026' y 
@CODEMPDOREF='02', @CODSEDDOREF='06'
En ese caso ese ejemplo es la partición de agosto para majoro selva sede pucallpa. Si fuera la partición de julio sería majoro sede Lima sería
@FECHAINICIO='01/07/2026', @FECHATERMIN='31/07/2026'
@CODEMPDOREF='01', @CODSEDDOREF='01'

@CODEMPDOREF='02', @CODSEDDOREF='06' varía así
Air Majoro Selva (MSA) → Empresa: '02' | Sede: '06' (Pucallpa).
Air Majoro S.A. (AM) → Empresa: '01' | Sede: '01' (Lima).
Air Majoro S.A. (AM) → Empresa: '01' | Sede: '02' (Nazca).


Ese asset debe alimentar a una tabla al igual que los demás.
Esa tabla se debe llamar sisa_sales
Sus columnas son las de columns normalizadas así como hicimos en el asset de los proposals y más bien esa función ponla en un utils al primer nivel (al nivel de assets) y sus tipos infiérelos del ejemplo que se muestra.
Igualmente pydantic y peewee, en este caso si totalmente upsert (borrar registros anteriores de la partición). No tiene padre este asset.

{
  "ok": true,
  "error": null,
  "columns": [
    "NUMEROFILA",
    "CODORGDOREF",
    "CODPERDOREF",
    "CODSEDDOREF",
    "CODEMPDOREF",
    "CODREGDOREF",
    "CODNVEDOREF",
    "NOMTIPMONED",
    "T01TIPDOREF",
    "NRO_DOCUMENTO",
    "FECHAEMISIO",
    "FECHAVUELO",
    "NUMERODERUC",
    "ruc_cliente20",
    "RAZONSOCIAL",
    "DOREFSUBTOT",
    "DOREFIMPIMP",
    "DOREFTOTNUM",
    "CUENTA_CONTABLE",
    "NOMTIPOPAGO",
    "AENAVMATRIC",
    "NOMSITDOREF",
    "T01LUGORIGE",
    "DESORIGEN",
    "T01LUGDESTI",
    "DESDESTINO",
    "TIPCAMMONED",
    "CANTIDAD",
    "OBSERVACION"
  ],
  "rows": [
    [
      1,
      "01",
      "2026",
      "06",
      "02",
      "001882",
      "00",
      "MN",
      "FT",
      "F006-24684",
      "01/08/2026",
      "01/08/2026",
      "20547960051",
      "943815211",
      "PROGRAMA NACIONAL DE ASISTENCIA SOLIDARIA PENSION 65",
      30.0000,
      0.0000,
      30.0000,
      "704104",
      "TARJETA CREDITO",
      "OB2200",
      "106",
      "001",
      "PUCALLPA",
      "011",
      "ATALAYA",
      3.3910,
      1.0000,
      "PASAJE AEREO EN LA RUTA PUCALLPA ATALAYA*\nPAX:ANDY ERICK SAAVEDRA RIOS*\nF/V:05/04/2023"
    ],
    [
      2,
      "01",
      "2026",
      "06",
      "02",
      "001883",
      "00",
      "MN",
      "FT",
      "F006-24685",
      "01/08/2026",
      null,
      "20615110001",
      "958810798",
      "CONSORCIO CG SARAYACU",
      60.0000,
      0.0000,
      60.0000,
      "704104",
      "TARJETA CREDITO",
      null,
      null,
      "",
      null,
      "",
      null,
      3.3910,
      1.0000,
      "PASAJE AEREO EN LA RUTA PUCALLPA-CONTAMANA*\nPAX: YOVANY CELSO  BERNILLA TANTARICO*\nF/V: 08/04/2023*"
    ],
	....
    [
      490,
      "01",
      "2026",
      "06",
      "02",
      "004019",
      "00",
      "MN",
      "BV",
      "B006-49141",
      "12/08/2026",
      null,
      "46276775",
      "956554227",
      "NAVAS RUIZ MANUEL FERNANDO",
      20.0000,
      0.0000,
      20.0000,
      "704104",
      "TARJETA CREDITO",
      null,
      null,
      "",
      null,
      "",
      null,
      3.3640,
      1.0000,
      "PAQUETE CON ROPA EN LA RUTA CL-AY N15576"
    ]
  ],
  "rowCount": 490,
  "rowsAffected": null,
  "truncated": false
}

En una materialización debe llenar todas las sedes de ambas empresas, las empresas bueno no las tomes de sire_credentials sino ponlas en un archivo de constantes con ese código y también su nombre que son Air Majoro y Air Majoro Selva y ese nombre mejor también ponlo en la tabla y también el nombre de la sede para tenerlo ahí también.
El asset no tiene padre

Me dices si está claro

# corpac_files PROMPT/DESIGN
Mira en cada correo de corpac (del remitente servicio.facturacion@pegasus.com.pe) se envía body de la siguiente forma
<html><head></head><body style=3D"font-family:verdana,arial,sans-serif; fon=
t-size:9pt; "><br/><table cellspacing=3D"4" style=3D"width:100%"><tbody><tr=
><td colspan=3D"2" style=3D"width:100%;"><img src=3D"https://www.fedtt-peru=
=2Ecom/MercurioCorpacPortal/images/co=
rpac.png" alt=3D"Corpac" style=3D"height=
: 60px;" /></td></tr><tr><td id=3D"pFooterAddress" style=3D"width:100%; pad=
ding: 10px 6px 6px 10px; line-height:20px; border-top: 1px dashed #ccc; col=
or: #555; font-family: Verdana,sans-serif; font-size: 10px;" colspan=3D"2">=
<span style=3D"color:#000;">CORPAC&nbsp;S.A.</span><br/>Av. Elmer Faucett 3=
400 - Aeropuerto Internacional &quot;Jorge Ch=C3=A1vez&quot; - Callao 1 - L=
ima-Per=C3=BA<br/>Central telef=C3=B3nica: (511) 414-1000<br/>Ministerio de=
 Transportes y Comunicaciones </td></tr></tbody></table><div id=3D"cuerpo" =
class=3D"mailFont" style=3D"background-color: #F6F6F6; border: 1px solid #F=
0F0F0; padding-left: 20px; padding-top: 20px;"><div id=3D"pMain"><h3><b>SIS=
TEMA DE COMUNICACIONES DE FACTURA ELECTR=C3=93NICA</b></h3><p>Estimado clie=
nte, cumplimos con remitir el comprobante electr=C3=B3nico de su empresa, a=
 trav=C3=A9s del sistema de comunicaciones de Mercurio</p></div><div id=3D"=
pOthers"><p>Para acceder al contenido de la comunicaci=C3=B3n, siga el sigu=
iente enlace:<br/>&nbsp;&nbsp;&nbsp;&nbsp; <a href=3D"https://www.fedtt-per=
u.com/MercurioCorpacPortal/Paginas/Comunicaciones?accessCode=3DbWZ1dzFsczEr=
Y2s90&action=3D1" style=3D"line-height: 40px;">https://www.fedtt-peru.com/M=
ercurioCorpacPortal/Paginas/Comunicaciones?accessCode=3DbWZ1dzFsczErY2s90&a=
ction=3D1</a></p><p>Gracias por utilizar nuestros servicios.</p></div><br/>=
</div><div id=3D"pFooter" style=3D"border-top: 1px dashed #ccc; border-bott=
om: 1px dashed #ccc; color: #555; font-family: Verdana,sans-serif; font-siz=
e: 12px; padding: 6px; padding-left: 30px;"><p>Este correo ha sido enviado =
autom=C3=A1ticamente. Por favor, no responda a este correo.</p></div><img w=
idth=3D"1" height=3D"1" alt=3D"" src=3D"http://email.pegasus.com.pe/o/eJwUy=
kGuhCAMANDTyJK0pSgsuMC_RW2r30kMBjJz_snsnzUWqVqDN9zKmihRLeG_IQgntQxymOK2J614=
kK7ZGEnoCFcjoBUKAkDmXKLjXlj2zVS0JMKF4fFT5ntG7Xd8PIz218fp8ZHh5nNhkGvc8uqj_0j=
4NPoGAAD__wh4KiY"></body></html>

Que en texto plano es
Corpac
CORPAC S.A.
Av. Elmer Faucett 3400 - Aeropuerto Internacional "Jorge Chávez" - Callao 1 - Lima-Perú
Central telefónica: (511) 414-1000
Ministerio de Transportes y Comunicaciones
SISTEMA DE COMUNICACIONES DE FACTURA ELECTRÓNICA

Estimado cliente, cumplimos con remitir el comprobante electrónico de su empresa, a través del sistema de comunicaciones de Mercurio

Para acceder al contenido de la comunicación, siga el siguiente enlace:
     https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones?accessCode=bWZ1dzFsczErY2s90&action=1

Gracias por utilizar nuestros servicios.

Este correo ha sido enviado automáticamente. Por favor, no responda a este correo.


Cómo ves hay un link https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones?accessCode=bWZ1dzFsczErY2s90&action=1

Al acceder a ese hay un botón
<input type="submit" name="btnAdjuntos" value="Descargar Documentos" id="btnAdjuntos" class="styleDescarga" style="width:180px;">
Con el id btnAdjuntos. Al dar clic en ese botón obtenemos un zip, en ese zip hay 3 o 2 archivos.
Esos archivos tenenos que ponerlos en una tabla, como hijos del email. Es así que las columnas son id_padre, partición, filename y data.

Donde un padre puede tener 2 o 3 hijos. El id padre debe ser el id del correo que es único por cada correo (campo id)

No interesa email_attachments en este caso.
No hay empresa en este caso.

Igualmente como el estilo de los otros assets, el resource es solamente db_resource que lee una tabla y llena otra tabla. Y el apiresource que consulta a la url de corpac y habría un parser que también debe ir en otro archive para que analice el body, yo creo que ese no debería ser resource porque no tiene conexión con data fuera del programa.

Respecto al apiresource me gustaría que sea solo con requests, no con ningun navegador headless, si es possible hacerlo creo que con session, que sea lo más ligero possible por favor esa parte no la tengo clara al 100%, tengo una implementación antigua que es esta.

    def download_zip_bytes(self, url: str) -> bytes:
        """POST al portal y retorna el ZIP de documentos (factura + OC)."""
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = [("User-Agent", self._user_agent)]
        with opener.open(url, timeout=30) as respuesta:
            html = respuesta.read().decode("utf-8", errors="replace")
        ocultos: dict[str, str] = {}
        for match in re.finditer(r'<input[^>]*type="hidden"[^>]*>', html, re.IGNORECASE):
            nombre = re.search(r'name="([^"]+)"', match.group(0))
            valor = re.search(r'value="([^"]*)"', match.group(0))
            if nombre:
                ocultos[nombre.group(1)] = valor.group(1) if valor else ""
        datos = dict(ocultos)
        datos["btnAdjuntos"] = "Descargar Documentos"
        cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
        solicitud = urllib.request.Request(url, data=cuerpo, method="POST")
        solicitud.add_header("Content-Type", "application/x-www-form-urlencoded")
        solicitud.add_header("Referer", url)
        with opener.open(solicitud, timeout=90) as respuesta:
            contenido = respuesta.read()
        if contenido[:2] != b"PK":
            raise ValueError("La respuesta del portal no es un ZIP de documentos")
        return contenido

Puedes usarla o sino hacer una más ligera, creo que no es necesario el regex porque puedo parsear todo el html con html de stdlib y sacarlo por id. Pero tal vez sea más pesado. Bueno ahí revísalo.

Me comentas si tienes alguna duda.


