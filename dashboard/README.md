# Dashboard AIM · Air Majoro

Informe interactivo de **Evidence Studio** (Markdoc + SQL) sobre el DWH `dwh_aim_db`.
Proyecto migrado desde Evidence legacy (SvelteKit + npm) al **Evidence Studio CLI**.

## 1. Requisitos: instalar el CLI

Evidence Studio **no se distribuye por npm**, así que `npx evidence ...` **no** es válido
(el paquete `evidence` de npm es un paquete antiguo sin relación). El CLI es un binario que
se instala una sola vez:

**macOS / Linux**

```shell
curl -fsSL https://evidence.studio/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://evidence.studio/install.ps1 | iex
```

Comprueba la versión (este proyecto está validado con `0.10.1`):

```shell
evidence --version
```

## 2. Cómo se ejecuta el proyecto

En Evidence Studio **no existe un paso de build**: las consultas se ejecutan en vivo contra
la base de datos cada vez que se carga una página. Por eso no hay `evidence build`
ni `npx evidence build`.

| Flujo anterior (Evidence legacy + npm) | Flujo actual (Evidence Studio CLI)                | Para qué sirve                                            |
| -------------------------------------- | ------------------------------------------------- | --------------------------------------------------------- |
| `npm run dev`                          | `npm run dev` → `evidence dev`                    | Servidor de desarrollo en http://localhost:4001           |
| `npm run build`                        | — (no existe)                                     | No hay build: los datos se consultan en vivo              |
| `npm run preview`                      | `npm run serve` → `evidence serve`                | Servidor de producción self-hosted (solo localhost)       |
| —                                      | `npm run validate` → `evidence validate`           | Valida la sintaxis Markdoc y el SQL de todas las páginas  |
| —                                      | `npm run deploy` → `evidence launch`               | Publica el proyecto en Evidence Studio vía GitHub         |

Comandos que puedes ejecutar directamente (sin npm):

```shell
evidence dev --port 4001  # desarrollo, http://localhost:4001  (--port para cambiar el puerto)
evidence validate       # valida páginas (usa --json para salida legible por máquinas)
evidence serve --port 4001 # producción self-hosted en 127.0.0.1:4001
evidence tables         # lista las tablas disponibles del DWH
evidence query "select 1"   # prueba la conexión al warehouse
```

### Servirlo en red (no solo localhost)

`evidence serve` se niega a escuchar fuera de localhost sin autenticación. Para exponerlo
en la red hay que proteger la web con Basic Auth:

```shell
EVIDENCE_BASIC_USER=admin EVIDENCE_BASIC_PASSWORD='una-clave-fuerte' \
  npm run serve:network      # 0.0.0.0:3080
```

En una red privada de confianza (VPN, Tailscale, VPC interna) se puede desactivar la
autenticación con `EVIDENCE_AUTH_DISABLED=true`.

## 3. Estructura del proyecto

```
evidence.config.yaml   # nombre del proyecto y carpeta de páginas (./pages)
connection.yaml        # credenciales del warehouse (gitignored) → conector directo postgres
theme.yaml             # colores, paletas y tipografías del informe
access.yaml            # permisos de las páginas publicadas en Evidence Studio
pages/                 # las páginas del informe en Markdoc
  estado-resultados.md # Estado de Resultados (ER): cuentas × meses
  horas-de-vuelo.md    # Horas de Vuelo: total diario por aeronave y sede de operación
```

### Estado de Resultados (`pages/estado-resultados.md`)

Una única vista que reproduce el estado de resultados mensual en soles:

- **Filas**: las cuentas del plan contable en su orden oficial. El orden sale de
  `dwh.static_master_account_groups.orden` (1 VENTAS … 3 UTILIDAD BRUTA … 9 RESULTADO
  OPERATIVO … 11 OTROS INGRESOS DIVERSOS) y de `dwh.newview.orden_fila` dentro de cada
  grupo.
- **Columnas**: los meses del año elegido (pivote sobre `mes` con `date_grain="month"`)
  más una columna `Total`.
- **Medidas calculadas**: `UTILIDAD BRUTA` (ventas + costo de ventas), `RESULTADO
  OPERATIVO` (grupos 1-2 y 4-8) y `RESULTADO NETO` (todos los grupos, incluidos cargas
  financieras y otros ingresos). Se generan en SQL con los grupos de tipo `MEDIDA` de
  `dwh.static_master_account_groups`.
- **Filtros**: `Año` (dropdown simple, por defecto el último año con datos) y `Centro de
  costo` (dropdown múltiple; sin selección = todos). Ambos se interpolan en el SQL con
  `[[ and ... {{ filtro }} ]]`.

Tablas del DWH usadas por la vista: `dwh.newview` (saldos mensuales por cuenta, centro de
costo y moneda), `dwh.static_master_account_groups` (orden y tipo de cada grupo) y
`dwh.static_cost_centers` (nombre legible de cada centro de costo).

Detalles de la migración ya aplicada:

- Las páginas usan sintaxis **Markdoc** (`{% bar_chart /%}`) y bloques SQL en la propia
  página (```` ```sql nombre ... ````) con filtros `{{ dropdown }}` y bloques `[[ ... ]]`.
- El SQL se ejecuta en el dialecto nativo del warehouse (PostgreSQL aquí), no en DuckDB.
- Las dependencias npm del Evidence legacy (`@evidence-dev/evidence`, `core-components`,
  `tailwind`) y el `node_modules` se han eliminado; `package.json` solo contiene scripts
  de conveniencia que llaman al CLI.

## 4. Volver atrás (rollback)

Si necesitas el toolchain legacy por algún motivo, puedes reinstalarlo con las versiones
que tenía el proyecto antes de la migración:

```shell
npm i -D @evidence-dev/evidence@40.1.8 @evidence-dev/core-components@5.4.2 \
         @evidence-dev/tailwind@3.1.4 typescript@^5.3.3
```

## 5. Más información

- Documentación: https://docs.evidence.dev
- CLI y migración: `evidence docs read cli/commands`, `evidence docs read migration-guide`
- Ayuda del proyecto para agentes de IA: `AGENTS.md`
