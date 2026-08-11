#!/usr/bin/env bash
# make-graph.sh — Regenera el grafo de conocimiento de la wiki (DianaV2)
#
# Uso:
#   ./make-graph.sh                 # parse + merge determinístico + dashboard
#   ./make-graph.sh --with-llm      # además, re-copla analysis-batch-*.json si existen
#
# Salidas (en wiki/.ua/):
#   knowledge-graph.json   -> grafo final (SE commitea, docs-as-code)
#   dashboard.html         -> HTML estático vis.js (enviable por Telegram / servir local)
#
# Nota: el análisis LLM (article-analyzer) lo ejecuta el agente mantenedor
# (Hermes) con delegación; este script solo consume analysis-batch-*.json
# si ya están en wiki/.ua/intermediate/.

set -euo pipefail
cd "$(dirname "$0")/../.."   # repos/DianaV2
WIKI="wiki"
SCRIPTS="scripts/wiki_graph"
UA_DIR="$WIKI/.ua"

echo "[make-graph] 1/4 parse determinístico..."
# Respaldar batches LLM si existen (el parse limpia intermediate/)
if ls "$UA_DIR"/intermediate/analysis-batch-*.json >/dev/null 2>&1; then
  mkdir -p "$UA_DIR/.batches"
  cp "$UA_DIR"/intermediate/analysis-batch-*.json "$UA_DIR/.batches/"
fi
rm -rf "$UA_DIR/intermediate"
python3 "$SCRIPTS/parse-knowledge-base.py" "$WIKI" >/dev/null
if ls "$UA_DIR"/.batches/analysis-batch-*.json >/dev/null 2>&1; then
  mkdir -p "$UA_DIR/intermediate"
  cp "$UA_DIR"/.batches/analysis-batch-*.json "$UA_DIR/intermediate/"
  rm -rf "$UA_DIR/.batches"
fi

echo "[make-graph] 2/4 merge (scan + batches LLM si existen)..."
python3 "$SCRIPTS/merge-knowledge-graph.py" "$WIKI" 2>&1 | tail -3

echo "[make-graph] 3/4 validar y copiar a knowledge-graph.json..."
python3 - "$UA_DIR/intermediate/assembled-graph.json" "$UA_DIR/knowledge-graph.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
g = json.load(open(src))
nodes = {n["id"]: n for n in g.get("nodes", [])}
edges = []
for e in g.get("edges", []):
    if e.get("source") in nodes and e.get("target") in nodes:
        edges.append(e)
g["edges"] = edges
for n in g.get("nodes", []):
    for k in ("id", "type", "name", "summary", "tags", "complexity"):
        n.setdefault(k, "")
    n.setdefault("tags", [])
json.dump(g, open(dst, "w"), ensure_ascii=False, indent=1)
print(f"[make-graph] knowledge-graph.json: {len(nodes)} nodos, {len(edges)} edges")
PY

echo "[make-graph] 4/4 dashboard..."
python3 "$SCRIPTS/render-dashboard.py" "$UA_DIR/knowledge-graph.json" "$UA_DIR/intermediate/scan-manifest.json" "$UA_DIR/dashboard.html"

echo "[make-graph] listo. viewer oficial:"
echo "  npx https://github.com/Egonex-AI/Understand-Anything/releases/latest/download/understand-anything-viewer.tgz wiki/"
echo "  o abre $UA_DIR/dashboard.html en un navegador."
