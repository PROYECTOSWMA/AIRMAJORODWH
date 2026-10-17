"""Parsers de las fuentes estáticas, uno por archivo.

    * ``factura.py`` -> ``parse_factura`` / ``parse_factura_list`` /
      ``parse_factura_fields`` / ``split_documento`` (campo ``factura`` de la hoja
      "VUELOS B200 2026");
    * ``ambulancia_ventas.py`` -> ``parse_ambulancia_ventas`` (hoja
      "VUELOS B200 2026" del libro VENTAS);
    * ``lap_aeronave.py`` -> ``parse_lap_aeronave`` (hoja "Aeronave" del Excel LAP);
    * ``planilla.py`` -> ``parse_planilla`` (hoja ``PLANILLA`` del libro ODS);
    * ``sales_selva.py`` -> ``parse_sales_selva`` (todas las hojas del libro de ventas
      "REPORTE DE VENTAS"; cada fila se etiqueta con su ``sheet_name``);
    * ``rh.py`` -> ``parse_rh_text`` (comprobantes de renta pipe-delimited);
    * ``invoices/`` -> el paquete de **facturas y órdenes de compra del exterior**
      (``static/INVOICE INTERNACIONALES``): un módulo por proveedor (``fenix``,
      ``jetset``, ``kal``, ``peniel``, ``precision``, ``textron``) y
      ``purchase_order`` para las órdenes de compra (un solo parser para sus seis
      subcarpetas). Cada carpeta llena DOS tablas (``*_header`` y ``*_details``).

Todos los parsers de archivo comparten el contrato ``parser(path) -> list[dict]``
(``parse_rh_text`` recibe el **texto** del reporte) y los consume el asset
``static_data_asset``. Los de ``invoices/`` devuelven
``{"header": [...], "details": [...]}`` y su ``parse(carpeta)`` recorre los PDFs.
"""
