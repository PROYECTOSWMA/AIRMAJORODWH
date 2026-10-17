"""Asset único de las fuentes estáticas de la carpeta ``static`` del repo.

En vez de una carpeta por fuente (``ambulancia_ventas_asset``, ``lap_asset``,
``planilla_asset``), todo se consolida en ``assets/static_data_asset`` (primer nivel
de ``assets/``): un solo asset (partición estática ``"2026"``), una carpeta
``parsers/`` con **un archivo por parser** (``factura.py``, ``ambulancia_ventas.py``,
``lap_aeronave.py``, ``planilla.py``, ``sales_selva.py``), un modelo peewee **por
archivo** en ``models/`` (``base.py`` + ``ambulancia_venta.py``, ``lap_aeronave.py``,
``planilla.py``, ``sales_selva.py``) y un solo ``resources/db_resource.py`` con el
resource que upserta las tablas operativas y los 7 CSV de referencia.

El libro ``1.- REPORTE DE VENTAS*.xlsx`` se ingiere con ``parse_sales_selva`` en la
tabla ``sales_selva``: se consolidan todas sus hojas (una por mes y empresa) y cada
fila queda etiquetada con ``sheet_name`` y ``row_number``.

Las **facturas de proveedores del exterior y las órdenes de compra**
(``static/INVOICE INTERNACIONALES/``) se ingieren con el paquete
``parsers/invoices``: **una subcarpeta por proveedor** (Fenix, JetSet, Kal,
Peniel, Precision y Textron) con **su propio parser**, y una carpeta
``ORDEN DE COMPRA`` (con una subcarpeta por proveedor) que procesa **un solo
parser** porque las seis comparten el mismo formulario. Cada subcarpeta llena
**DOS tablas**: ``static_invoice_<proveedor>_header`` (una fila por documento) y
``static_invoice_<proveedor>_details`` (una fila por línea); las órdenes de compra
van a ``static_invoice_po_header`` / ``static_invoice_po_details``. El cruce
factura ↔ PO se hace en dbt (siguiente paso).

El reporte RH del SEE-SOL (``seesol_rh``) ya no vive aquí: tiene su propio asset
mensual (``assets/seesol_rh_asset/``) con la vía HTTP en su ``api_resource``.
"""
