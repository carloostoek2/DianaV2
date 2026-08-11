#!/usr/bin/env python3
"""Genera el dashboard interactivo de la wiki de DianaV2 (Telegram Mini App + navegador).

Uso: python3 render-dashboard.py <knowledge-graph.json> [manifest.json] [salida.html]

Características:
- Telegram WebApp: tema claro/oscuro nativo, expand(), ready()
- Grafo force-directed (vis.js) con búsqueda, filtros por tipo y capa
- Panel lateral con detalle del nodo: summary, tags, wikilinks y contenido markdown
"""
import html
import json
import os
import re
import sys


def md_to_html(text: str) -> str:
    """Render minimalista de markdown (headers, listas, negritas, codigo, links)."""
    if not text:
        return "<i>Sin contenido.</i>"
    lines = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            lines.append("<pre>" if in_code else "</pre>")
            continue
        if in_code:
            lines.append(html.escape(line))
            continue
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if s.startswith("###"):
            lines.append(f"<h4>{html.escape(s[3:].strip())}</h4>")
        elif s.startswith("##"):
            lines.append(f"<h3>{html.escape(s[2:].strip())}</h3>")
        elif s.startswith("#"):
            lines.append(f"<h2>{html.escape(s[1:].strip())}</h2>")
        elif re.match(r"^[-*] ", s):
            lines.append(f"<li>{html.escape(s[2:])}</li>")
        elif re.match(r"^\d+\. ", s):
            cleaned = re.sub(r"^\d+\. ", "", s)
            lines.append(f"<li>{html.escape(cleaned)}</li>")
        elif s.startswith("|"):
            lines.append(f"<div class='tbl'>{html.escape(s)}</div>")
        elif s.startswith("^["):
            lines.append(f"<div class='prov'>{html.escape(s)}</div>")
        else:
            body = html.escape(s)
            body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
            body = re.sub(r"`(.+?)`", r"<code>\1</code>", body)
            lines.append(f"<p>{body}</p>")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: render-dashboard.py <knowledge-graph.json> [manifest.json] [salida.html]", file=sys.stderr)
        sys.exit(1)
    graph_path = sys.argv[1]
    manifest_path = sys.argv[2] if len(sys.argv) > 2 else None
    out_path = sys.argv[3] if len(sys.argv) > 3 else "dashboard.html"

    graph = json.load(open(graph_path, encoding="utf-8"))
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    # Contenido y wikilinks por artículo desde el manifest (si existe)
    content_map: dict[str, dict] = {}
    if manifest_path and os.path.exists(manifest_path):
        m = json.load(open(manifest_path, encoding="utf-8"))
        for n in m.get("nodes", []):
            if n.get("type") == "article":
                km = n.get("knowledgeMeta", {})
                content_map[n["id"]] = {
                    "content": km.get("content", ""),
                    "wikilinks": km.get("wikilinks", []),
                }

    color_map = {
        "article": "#4f8ef7", "entity": "#e8a33d", "claim": "#8e5bd9",
        "topic": "#2bb673", "source": "#999999", "layer": "#2bb673",
        "module": "#4f8ef7", "table": "#e86f4f", "concept": "#e8a33d",
        "default": "#888888",
    }
    type_label = {
        "article": "Artículo", "entity": "Entidad", "claim": "Claim",
        "topic": "Tema", "source": "Fuente", "layer": "Capa",
        "module": "Módulo", "table": "Tabla", "concept": "Concepto",
        "default": "Nodo",
    }

    vis_nodes = []
    layers = set()
    for n in nodes:
        ntype = n.get("type", "default")
        layers.add(ntype)
        summary = (n.get("summary") or n.get("name") or "")[:220]
        tags = ", ".join(n.get("tags", []) or [])
        meta = content_map.get(n.get("id"), {})
        detail = {
            "name": n.get("name", n.get("id")),
            "type": ntype,
            "typeLabel": type_label.get(ntype, ntype),
            "summary": n.get("summary", ""),
            "tags": tags,
            "content": md_to_html(meta.get("content", "")),
            "wikilinks": meta.get("wikilinks", []),
        }
        vis_nodes.append({
            "id": n.get("id"),
            "label": n.get("name", n.get("id")),
            "color": color_map.get(ntype, color_map["default"]),
            "group": ntype,
            "detail": detail,
        })
    vis_edges = []
    for e in edges:
        vis_edges.append({
            "from": e.get("source"), "to": e.get("target"),
            "label": e.get("type", ""),
            "arrows": "to" if e.get("direction", "forward") == "forward" else "",
            "width": max(0.5, float(e.get("weight", 0.5)) * 2.0),
        })

    data_nodes = json.dumps(vis_nodes, ensure_ascii=False)
    data_edges = json.dumps(vis_edges, ensure_ascii=False)
    title = "DianaV2 · Grafo de conocimiento"

    html_doc = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>%TITLE%</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --bg:#10151c; --panel:#161d27; --border:#26303d; --text:#dde3ea;
    --muted:#8fa3b8; --accent:#4f8ef7; --chip:#1c2634;
  }
  [data-theme="light"] {
    --bg:#f3f5f8; --panel:#ffffff; --border:#d9e0e8; --text:#1a2330;
    --muted:#5c6b7e; --accent:#2f6fe4; --chip:#e8edf4;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
         background:var(--bg); color:var(--text); }
  #toolbar { position:fixed; top:0; left:0; right:0; z-index:20; background:var(--panel);
             padding:10px 14px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;
             border-bottom:1px solid var(--border); }
  #toolbar h1 { font-size:15px; margin:0; font-weight:650; white-space:nowrap; }
  #search { flex:1; min-width:160px; max-width:320px; padding:7px 10px; border-radius:8px;
            border:1px solid var(--border); background:var(--bg); color:var(--text); font-size:13px; }
  #stats { font-size:12px; color:var(--muted); white-space:nowrap; }
  #filters { position:fixed; top:52px; left:0; right:0; z-index:15; background:var(--bg);
             padding:8px 14px; display:flex; gap:6px; flex-wrap:wrap; border-bottom:1px solid var(--border); }
  .chip { padding:4px 11px; border-radius:20px; font-size:12px; cursor:pointer; user-select:none;
          background:var(--chip); border:1px solid var(--border); color:var(--muted); }
  .chip.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  #graph { position:fixed; top:100px; left:0; right:0; bottom:0; }
  #side { position:fixed; top:100px; right:0; bottom:0; width:min(380px, 92vw); z-index:18;
          background:var(--panel); border-left:1px solid var(--border); overflow-y:auto;
          transform:translateX(100%); transition:transform .22s ease; padding:14px 16px; }
  #side.open { transform:translateX(0); }
  #side h2 { font-size:15px; margin:0 0 4px; }
  .badge { display:inline-block; font-size:10.5px; padding:2px 8px; border-radius:10px;
           color:#fff; margin-bottom:8px; }
  .tags { font-size:11.5px; color:var(--muted); margin-bottom:10px; }
  .wl { font-size:11.5px; margin-bottom:10px; }
  .wl a { color:var(--accent); text-decoration:none; cursor:pointer; }
  #side h2, #side h3, #side h4 { color:var(--text); }
  #side p { font-size:12.5px; line-height:1.55; margin:4px 0; }
  #side li { font-size:12.5px; margin:1px 0; }
  #side code, #side pre { background:var(--bg); border-radius:4px; font-size:11px;
                          padding:1px 4px; white-space:pre-wrap; }
  #side pre { padding:8px; }
  #side .tbl { font-size:11px; color:var(--muted); white-space:nowrap; overflow-x:auto; }
  #side .prov { font-size:10px; color:var(--muted); margin-top:6px; }
  #closeSide { position:sticky; top:0; float:right; background:none; border:none; color:var(--muted);
               font-size:18px; cursor:pointer; }
  #legend { position:fixed; bottom:14px; left:14px; z-index:12; background:var(--panel);
            padding:9px 12px; border-radius:10px; font-size:11px; line-height:1.75;
            border:1px solid var(--border); }
  #legend span { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }
  .hint { position:fixed; bottom:14px; right:14px; z-index:12; font-size:11px; color:var(--muted);
          background:var(--panel); padding:6px 10px; border-radius:8px; border:1px solid var(--border); }
</style>
</head>
<body data-theme="dark">
<div id="toolbar">
  <h1>🧠 %TITLE%</h1>
  <input id="search" type="text" placeholder="Buscar nodo…"/>
  <div id="stats"></div>
</div>
<div id="filters"></div>
<div id="graph"></div>
<div id="side"><button id="closeSide">✕</button><div id="sideBody"></div></div>
<div id="legend">
  <div><span style="background:#4f8ef7"></span>Artículo / módulo</div>
  <div><span style="background:#e8a33d"></span>Entidad / concepto</div>
  <div><span style="background:#8e5bd9"></span>Claim</div>
  <div><span style="background:#2bb673"></span>Tema / capa</div>
  <div><span style="background:#e86f4f"></span>Tabla</div>
</div>
<div class="hint" id="hint"></div>
<script>
const NODES = %DATA_NODES%;
const EDGES = %DATA_EDGES%;
const TYPE_ORDER = ["article","entity","claim","topic","table","source"];
const ACTIVE = new Set(TYPE_ORDER);

const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); if (tg.colorScheme === "light") { document.body.dataset.theme = "light"; } }
const nodes = new vis.DataSet(NODES.map(n => ({...n, title: n.label})));
const edges = new vis.DataSet(EDGES);
const container = document.getElementById('graph');
const network = new vis.Network(container, {nodes, edges}, {
  physics: { stabilization: {iterations: 350}, barnesHut: {gravitationalConstant: -3200, springLength: 135, springConstant: 0.045}},
  nodes: { shape: 'dot', size: 15, font: {color: '#dde3ea', size: 11}, borderWidth: 1, borderWidthSelected: 2.5 },
  edges: { color: {color: '#4a5a6e', highlight: '#7ab8ff'}, font: {color: '#8fa3b8', size: 9, strokeWidth: 0}, smooth: {enabled: true} },
  interaction: { hover: true, tooltipDelay: 150, navigationButtons: true, keyboard: true, selectConnectedEdges: true }
});

// stats
document.getElementById('stats').textContent = NODES.length + ' nodos · ' + EDGES.length + ' relaciones';

// filtros por tipo
const filterBar = document.getElementById('filters');
TYPE_ORDER.forEach(t => {
  const c = document.createElement('div');
  c.className = 'chip on'; c.textContent = t;
  c.onclick = () => {
    if (ACTIVE.has(t)) { ACTIVE.delete(t); c.classList.remove('on'); }
    else { ACTIVE.add(t); c.classList.add('on'); }
    applyFilters();
  };
  filterBar.appendChild(c);
});
function applyFilters() {
  const ids = new Set(NODES.filter(n => ACTIVE.has(n.type)).map(n => n.id));
  nodes.forEach(n => nodes.update({id: n.id, hidden: !ids.has(n.id)}));
  edges.forEach(e => {
    const vis = ids.has(e.from) && ids.has(e.to);
    edges.update({id: e.id, hidden: !vis});
  });
}

// panel lateral
const side = document.getElementById('side');
const sideBody = document.getElementById('sideBody');
function showDetail(d) {
  if (!d) return;
  const wl = (d.wikilinks || []).map(w => `<a data-wl="${w.replace(/"/g,'&quot;')}">[[${w}]]</a>`).join(' ');
  sideBody.innerHTML = `
    <h2>${d.name}</h2>
    <span class="badge" style="background:${({article:'#4f8ef7',entity:'#e8a33d',claim:'#8e5bd9',topic:'#2bb673',table:'#e86f4f',source:'#999999',module:'#4f8ef7',concept:'#e8a33d'})[d.type] || '#888'}">${d.typeLabel}</span>
    ${d.tags ? `<div class="tags">🏷️ ${d.tags}</div>` : ''}
    ${d.summary ? `<p><b>${d.summary}</b></p>` : ''}
    ${wl ? `<div class="wl">Enlaza a: ${wl}</div>` : ''}
    <hr style="border:none;border-top:1px solid var(--border);margin:10px 0"/>
    ${d.content}
  `;
  side.classList.add('open');
  sideBody.querySelectorAll('a[data-wl]').forEach(a => {
    a.onclick = () => {
      const target = NODES.find(n => String(n.label).toLowerCase() === a.dataset.wl.toLowerCase());
      if (target) { network.selectNodes([target.id]); network.focus(target.id, {scale: 1.1}); showDetail(target.detail); }
    };
  });
}
document.getElementById('closeSide').onclick = () => side.classList.remove('open');
network.on('selectNode', p => { showDetail(p.nodes[0] && nodes.get(p.nodes[0]).detail); });
network.on('deselectNode', () => side.classList.remove('open'));

// busqueda
const search = document.getElementById('search');
const hint = document.getElementById('hint');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  if (!q) { network.selectNodes([]); hint.textContent = 'Clic en un nodo para ver detalle'; return; }
  const hits = NODES.filter(n => String(n.label).toLowerCase().includes(q) ||
                                String(n.detail.summary).toLowerCase().includes(q)).slice(0, 8);
  if (hits.length === 0) { hint.textContent = 'Sin resultados'; return; }
  const h = hits[0];
  network.selectNodes([h.id]); network.focus(h.id, {scale: 1.15});
  hint.textContent = hits.length > 1 ? `${hits.length} coincidencias — mostrando la primera` : '1 coincidencia';
});
window.addEventListener('resize', () => network.redraw());
setTimeout(() => { document.body.dataset.theme = (tg && tg.colorScheme === 'light') ? 'light' : 'dark'; }, 50);
</script>
</body>
</html>"""
    html_doc = (html_doc
                .replace("%TITLE%", title)
                .replace("%DATA_NODES%", data_nodes)
                .replace("%DATA_EDGES%", data_edges))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"[render] {len(vis_nodes)} nodos, {len(vis_edges)} edges, "
          f"{len(content_map)} con contenido -> {out_path} ({os.path.getsize(out_path)//1024} KB)")


if __name__ == "__main__":
    main()
