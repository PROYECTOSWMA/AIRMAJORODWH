{#
    invoice_po_key(column)

    Clave **canónica** del número de orden de compra para cruzar la factura con su
    PO. Los dos lados lo escriben distinto:

      * la PO (``static_invoice_po_header.po_number``) imprime el prefijo y el
        formato del documento: 'PO 825-2026', 'PO. 238 - 2024', 'LOG-RO- 0133-2025';
      * la factura (``static_invoice_*_header.po_number``) pone solo el número:
        '825-2026', '238-2024', 'LOG-RO- 0133-2025'.

    Se quita el prefijo 'PO' del inicio y **todo** lo que no sea letra o dígito:
    'PO 825-2026' -> '8252026' y '825-2026' -> '8252026' (misma clave).

    Ojo: no basta con quitar el guion, porque una PO sin prefijo ('238-2024') y su
    versión con prefijo y puntos ('PO. 238 - 2024') tienen que caer en la misma
    clave; por eso se normaliza a solo alfanuméricos.
#}
{% macro invoice_po_key(column) -%}
    regexp_replace(
        regexp_replace(upper(trim({{ column }})), '^PO', ''),
        '[^A-Z0-9]', '', 'g'
    )
{%- endmacro %}
