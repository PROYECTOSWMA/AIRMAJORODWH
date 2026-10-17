"""Asset diario de documentos (PDF) de CEP desde el correo.

Un asset (``cep_docs_daily``), una carpeta ``parser.py`` (PDF -> cabecera +
detalles), un modelo peewee por tabla en ``models/`` (``from_email_cep_docs_headers``
y ``from_email_cep_docs_details``) y un ``resources/db_resource.py`` que hace el
upsert total del día desde ``email_attachments``.
"""
