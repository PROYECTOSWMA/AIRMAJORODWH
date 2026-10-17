"""Config de pytest: asegura que la raíz del repo y `src/` estén en sys.path.

Los tests viven en `<repo>/src/tests`, así que la raíz del repo queda **3 niveles** arriba:
`definitions.py` (el entry point de Dagster) está en la raíz y `assets/`/`jobs.py` en `src/`.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# El código (assets, jobs.py) vive en <repo>/src.
_SRC = os.path.join(_REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _make_pdf(lines):
    """Construye un PDF mínimo de 1 página con las líneas de texto dadas.

    Es un PDF válido con xref correcto (offsets byte a byte) para que
    pdfplumber pueda extraer el texto; se usa en los tests en lugar de un
    fixture binario.
    """
    content_lines = []
    for i, line in enumerate(lines):
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_lines.append(
            f"BT /F1 12 Tf 72 {720 - i * 16} Td ({escaped}) Tj ET"
        )
    content = "\n".join(content_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        (
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i).encode("ascii") + b" 0 obj\n" + obj + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += b"xref\n0 " + str(n).encode("ascii") + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        b"trailer\n<< /Size "
        + str(n).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    return bytes(out)


@pytest.fixture
def make_pdf():
    """Devuelve un constructor de PDF mínimo de 1 página (fixtures en memoria)."""
    return _make_pdf

