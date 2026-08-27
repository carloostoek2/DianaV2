"""Prueba REAL del enmascarado local de imágenes (sin fakes, sin Gemini).

Usa tesseract real (OCR local) sobre imágenes generadas con PIL y verifica,
contra el comportamiento documentado del flujo 4.22:

  - tarjeta  → dato fuerte → ENMASCARADO local (líneas tapadas en negro) y la
               imagen tapada es la que "viajaría"; la verificación post-tapado
               (re-OCR fail-closed) no vuelve a leer el dato.
  - identidad → NUNCA sale del servidor, ni tapada (revisión manual).
  - factura  → viaja tal cual (el importe queda visible).
  - clave    → dato fuerte → ENMASCARADO (usuario/contraseña tapados).

El describer es un "espía" que solo registra qué bytes recibiría Gemini, para
comprobar que lo que viaja es la imagen tapada y no la original.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diana.application.image_vision_service import (  # noqa: E402
    ImageVisionService,
    scan_sensitive,
)
from diana.infrastructure.vision.ocr import OcrEngine  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)

FONT_SIZE = 44
LINE_H = round(FONT_SIZE * 1.45)
PAD = 40


def make_image(lines: list[str], name: str) -> bytes:
    """Render text lines as a clean PNG (black on white) and save a copy."""
    font = ImageFont.load_default(size=FONT_SIZE)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    widths = [probe.textbbox((0, 0), ln, font=font)[2] for ln in lines]
    width = max(widths) + 2 * PAD
    height = len(lines) * LINE_H + 2 * PAD
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        draw.text((PAD, PAD + i * LINE_H), ln, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    (OUT / f"{name}.png").write_bytes(buf.getvalue())
    return buf.getvalue()


class SpyDescriber:
    """Fake Gemini: only records which bytes it was asked to describe."""

    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def describe(self, image_bytes: bytes, *, mime_type: str) -> str:
        self.received.append(image_bytes)
        return "descripcion-de-prueba"


def real_ocr() -> OcrEngine:
    return OcrEngine()  # tesseract real, langs spa+eng con respaldo eng


def pixel_center_of(original: bytes, needle: str, ocr: OcrEngine):
    """Pixel en el centro de la caja OCR de la línea que contiene `needle`."""
    for line in ocr.extract_lines(original):
        if needle.lower() in line.text.lower():
            return (line.left + line.width // 2, line.top + line.height // 2)
    return None


async def main() -> int:
    ocr = real_ocr()
    checks: list[str] = []

    def ok(cond: bool, msg: str) -> None:
        checks.append(("OK " if cond else "FAIL") + " | " + msg)

    # ---------- Caso 1: tarjeta de crédito (dato fuerte → enmascarar) --------
    card_bytes = make_image(
        [
            "Tarjeta de credito",
            "TITULAR: JUAN PEREZ",
            "4532 0151 1283 0366",
            "VENCIMIENTO 12/28",
            "CVV 123",
        ],
        "1_tarjeta_original",
    )
    card_ocr_text = ocr.extract_text(card_bytes)
    print("=== CASO 1: tarjeta ===\nOCR real lee:\n" + card_ocr_text + "\n")
    ok(scan_sensitive(card_ocr_text).strong, "el OCR real detecta dato fuerte (tarjeta)")

    spy = SpyDescriber()
    svc = ImageVisionService(ocr=ocr, describer=spy, enabled=True)
    res = await svc.analyze(card_bytes, mime_type="image/png")
    ok(res.enabled and not res.sensitive and res.masked,
       f"resultado: sensitive={res.sensitive} masked={res.masked} "
       f"(esperado: sensitive=False, masked=True)")
    ok(len(spy.received) == 1, "el describer fue llamado una vez")
    if spy.received:
        masked = spy.received[0]
        (OUT / "1_tarjeta_enmascarada.png").write_bytes(masked)
        ok(masked != card_bytes, "los bytes que viajan son DIFERENTES de la imagen original")
        # Verificación fail-closed: re-OCR de la imagen tapada
        verify_text = ocr.extract_text(masked)
        print("Re-OCR de la imagen tapada lee:\n" + verify_text + "\n")
        ok(not scan_sensitive(verify_text).strong,
           "la verificación post-tapado NO vuelve a leer ningún dato fuerte")
        ok("4532" not in verify_text.replace(" ", "") and "0366" not in verify_text.replace(" ", ""),
           "el número de tarjeta ya no es legible en la imagen tapada")
        pt = pixel_center_of(card_bytes, "4532", ocr)
        if pt:
            img = Image.open(io.BytesIO(masked)).convert("RGB")
            px = img.getpixel(pt)
            ok(px == (0, 0, 0), f"la línea de la tarjeta quedó pintada de negro (pixel {pt} = {px})")
        else:
            ok(False, "no se encontró la caja OCR de la línea de la tarjeta")
    # ¿La línea del CVV también se tapa? (cvv es keyword fuerte)
    if spy.received:
        pt_cvv = pixel_center_of(card_bytes, "CVV", ocr)
        if pt_cvv:
            img = Image.open(io.BytesIO(spy.received[0])).convert("RGB")
            ok(img.getpixel(pt_cvv) == (0, 0, 0), "la línea del CVV también quedó tapada")

    # ---------- Caso 2: documento de identidad (nunca sale, ni tapado) -------
    id_bytes = make_image(
        ["DOCUMENTO NACIONAL DE IDENTIDAD", "DNI 30.123.456", "Nombre: MARIA LOPEZ"],
        "2_identidad_original",
    )
    id_text = ocr.extract_text(id_bytes)
    print("=== CASO 2: identidad ===\nOCR real lee:\n" + id_text + "\n")
    spy2 = SpyDescriber()
    svc2 = ImageVisionService(ocr=ocr, describer=spy2, enabled=True)
    res2 = await svc2.analyze(id_bytes, mime_type="image/png")
    ok(res2.sensitive and res2.reason == "identidad",
       f"identidad → sensitive=True, reason={res2.reason} (esperado: identidad)")
    ok(len(spy2.received) == 0, "con identidad el describer NUNCA es llamado (la imagen no sale)")

    # ---------- Caso 3: factura (viaja tal cual, importe visible) ------------
    inv_bytes = make_image(
        ["FACTURA N 001234", "Importe: $1.234,56", "IVA 21%", "TOTAL A PAGAR: $1.494,82"],
        "3_factura_original",
    )
    inv_text = ocr.extract_text(inv_bytes)
    print("=== CASO 3: factura ===\nOCR real lee:\n" + inv_text + "\n")
    spy3 = SpyDescriber()
    svc3 = ImageVisionService(ocr=ocr, describer=spy3, enabled=True)
    res3 = await svc3.analyze(inv_bytes, mime_type="image/png")
    ok(not res3.sensitive and not res3.masked,
       f"factura → sensitive={res3.sensitive} masked={res3.masked} (esperado: False/False)")
    ok(len(spy3.received) == 1 and spy3.received[0] == inv_bytes,
       "la factura viaja tal cual (los bytes que recibe el describer son los originales)")

    # ---------- Caso 4: credenciales (usuario/contraseña → enmascarar) -------
    cred_bytes = make_image(
        ["Acceso a la cuenta", "Usuario: admin", "Contrasena: MiClaveSegura123"],
        "4_claves_original",
    )
    cred_text = ocr.extract_text(cred_bytes)
    print("=== CASO 4: claves ===\nOCR real lee:\n" + cred_text + "\n")
    spy4 = SpyDescriber()
    svc4 = ImageVisionService(ocr=ocr, describer=spy4, enabled=True)
    res4 = await svc4.analyze(cred_bytes, mime_type="image/png")
    ok(not res4.sensitive and res4.masked,
       f"claves → sensitive={res4.sensitive} masked={res4.masked} (esperado: False/True)")
    if spy4.received:
        (OUT / "4_claves_enmascarada.png").write_bytes(spy4.received[0])
        v4 = ocr.extract_text(spy4.received[0])
        ok("MiClaveSegura123" not in v4.replace(" ", ""),
           "la contraseña ya no es legible en la imagen tapada")

    # ---------- Resumen ----------
    print("\n" + "=" * 60 + "\nRESULTADO DE LA PRUEBA REAL\n" + "=" * 60)
    failed = 0
    for c in checks:
        print(c)
        if c.startswith("FAIL"):
            failed += 1
    print(f"\n{len(checks) - failed}/{len(checks)} verificaciones OK — {'PRUEBA REAL SUPERADA' if failed == 0 else 'FALLÓ LA PRUEBA'}")
    print(f"Imágenes guardadas en: {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
