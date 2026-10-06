#!/usr/bin/env python3
"""wiring_scan.py — escaneo ESTÁTICO de cableado para DianaV2.

No prueba nada por sí solo: genera pistas para el Rastreador de cableado.
Uso:  python audit/tools/wiring_scan.py [ruta_repo] > audit/WIRING_SCAN.md
"""
import ast, pathlib, re, sys
from collections import Counter

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
src = root / "src" / "diana"
texts = {p: p.read_text(errors="ignore") for p in src.rglob("*.py")}
alltxt = "\n".join(texts.values())
rel = lambda p: str(p.relative_to(src))

print("# Escaneo de cableado (estático)\n")

# 1. Funciones definidas pero nunca llamadas en src
print("## 1. Funciones sin ningún llamador en src (candidatas a 'no conectadas')\n")
rows = []
for p, t in texts.items():
    try:
        tree = ast.parse(t)
    except SyntaxError:
        continue
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_") \
           and n.name not in ("main",) and not n.decorator_list:
            if len(re.findall(rf"\b{re.escape(n.name)}\b", alltxt)) == 1:
                rows.append((rel(p), n.name, n.lineno))
for f, n, l in sorted(rows):
    print(f"- `{f}:{l}` — `{n}`")
print(f"\nTotal: {len(rows)}\n")

# 2. Errores tragados
print("## 2. Errores tragados por archivo (`except Exception` / `log_swallowed`)\n")
c = Counter(); s = Counter()
for p, t in texts.items():
    c[rel(p)] = len(re.findall(r"except Exception", t))
    s[rel(p)] = len(re.findall(r"log_swallowed\(", t))
print("| Archivo | except Exception | log_swallowed |\n|---|---|---|")
for f, n in c.most_common(15):
    print(f"| {f} | {n} | {s[f]} |")
print(f"\nTotal except Exception: {sum(c.values())} · log_swallowed: {sum(s.values())}")
used = [rel(p) for p, t in texts.items()
        if "get_swallowed_counts" in t and not rel(p).endswith("observability.py")]
print(f"Archivos de producción que leen `get_swallowed_counts`: {len(used)} "
      f"{'(NADIE expone los contadores)' if not used else used}\n")

# 3. Cableado condicionado por bandera en composition.py
print("## 3. Dependencias que composition.py entrega solo si hay bandera\n")
comp = (src / "composition.py").read_text()
for m in re.finditer(r"(\w+)=\(?\s*\n?\s*(\w+) if settings\.(feature_\w+)[^\n]*else None", comp):
    print(f"- `{m.group(1)}` ← `{m.group(2)}` solo si `{m.group(3)}`")
for m in re.finditer(r"(\w+)\s*=\s*(\w+)\s+if\s+settings\.(feature_\w+)\s+else\s+None", comp):
    print(f"- `{m.group(1)}` ← `{m.group(2)}` solo si `{m.group(3)}`")
print()

# 4. Apagados/omisiones silenciosas (solo log, sin alerta)
print("## 4. Rutas que se desactivan u omiten solo con un log\n")
pat = re.compile(r'logger\.(info|warning|debug)\(\s*\n?\s*"([^"]*(disabled|no_embedder|skipped|embed_failed|missing)[^"]*)"')
for p, t in sorted(texts.items(), key=lambda x: rel(x[0])):
    for m in pat.finditer(t):
        line = t[:m.start()].count("\n") + 1
        print(f"- `{rel(p)}:{line}` — `{m.group(2)}` ({m.group(1)})")
