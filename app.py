import streamlit as st
import re
import graphviz
import datetime
import io
import subprocess
import os
import json

# ─────────────────────────────────────────────
# HELPER: LOC METRICS
# ─────────────────────────────────────────────
def calculate_loc_metrics(code_string, total_cost, total_bugs):
    lines = code_string.split('\n')
    total_raw_lines = len(lines)
    blank_lines = 0
    comment_lines = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
        elif stripped.startswith(('//','#','/*','*','<!--','-->')):
            comment_lines += 1

    loc = total_raw_lines - blank_lines - comment_lines
    kloc = loc / 1000 if loc > 0 else 0
    error_per_kloc = (total_bugs / kloc) if kloc > 0 else 0
    cost_per_loc   = (total_cost / total_raw_lines) if total_raw_lines > 0 else 0

    return {
        "Total Baris Kasar": total_raw_lines,
        "Baris Kosong": blank_lines,
        "Baris Komentar": comment_lines,
        "Nilai LOC": loc,
        "Nilai KLOC": round(kloc, 4),
        "Kesalahan per KLOC": round(error_per_kloc, 2),
        "Biaya per LOC": round(cost_per_loc, 2),
    }

# ─────────────────────────────────────────────
# HELPER: NODE / BLOCK SEGMENTATION
# ─────────────────────────────────────────────
PREDICATE_RE = re.compile(r'\b(if|else\s*if|elseif|elif|else|while|for|foreach|switch|case|default|catch|finally|try|do)\b', re.IGNORECASE)
FUNCTION_RE  = re.compile(r'\b(def |function |public |private |protected |static |async )\s*\w+\s*\(', re.IGNORECASE)

def segment_code_into_nodes(code_string):
    """
    Segment code into logical nodes for CFG.
    Returns list of dicts:
      { node_id, label, node_type, start_line, end_line, lines_preview }
    """
    raw_lines = code_string.split('\n')
    nodes = []
    current_block_lines = []
    current_start = 1
    node_id = 1

    def flush_block(end_line):
        nonlocal node_id, current_block_lines, current_start
        if not current_block_lines:
            return
        preview = '; '.join(l.strip() for l in current_block_lines[:3] if l.strip())
        if len(current_block_lines) > 3:
            preview += ' ...'
        nodes.append({
            "node_id": node_id,
            "label": f"Node {node_id}",
            "node_type": "process",
            "start_line": current_start,
            "end_line": end_line,
            "lines_preview": preview or "(blank/comment)",
            "raw_lines": list(current_block_lines),
        })
        node_id += 1
        current_block_lines = []
        current_start = end_line + 1

    for i, raw_line in enumerate(raw_lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(('//','#','/*','*','<!--')):
            current_block_lines.append(raw_line)
            continue

        is_decision = bool(PREDICATE_RE.search(stripped))
        is_function = bool(FUNCTION_RE.search(stripped))

        if is_function and node_id > 1:
            flush_block(i - 1)

        if is_decision:
            # flush whatever came before
            if current_block_lines:
                flush_block(i - 1)
            # create decision node
            preview = stripped[:80] + ('...' if len(stripped) > 80 else '')
            nodes.append({
                "node_id": node_id,
                "label": f"Node {node_id}",
                "node_type": "decision",
                "start_line": i,
                "end_line": i,
                "lines_preview": preview,
                "raw_lines": [raw_line],
            })
            node_id += 1
            current_start = i + 1
        else:
            current_block_lines.append(raw_line)

    flush_block(len(raw_lines))
    return nodes

# ─────────────────────────────────────────────
# HELPER: CYCLOMATIC COMPLEXITY
# ─────────────────────────────────────────────
def calculate_cyclomatic_complexity(nodes):
    """V(G) = E - N + 2P  (simplified: P + 1 where P = decision nodes)"""
    p = sum(1 for n in nodes if n["node_type"] == "decision")
    cc = p + 1

    n_count = len(nodes)
    # Edges: sequential (n-1) + each decision adds 1 extra branch
    e_count = (n_count - 1) + p
    cc_full = e_count - n_count + 2  # standard formula

    if cc <= 10:
        risk_level = "Rendah (Low Risk)"
        risk_color = "#28a745"
        desc = "Program sederhana dan mudah diuji. Semua jalur dapat diverifikasi dengan mudah."
    elif cc <= 20:
        risk_level = "Sedang (Moderate Complexity)"
        risk_color = "#ffc107"
        desc = "Kompleksitas masih terkelola. Disarankan memecah fungsi yang terlalu panjang."
    elif cc <= 50:
        risk_level = "Tinggi (High Risk)"
        risk_color = "#fd7e14"
        desc = "Algoritma padat dan rawan bug. Sangat disarankan refactoring ke fungsi terpisah."
    else:
        risk_level = "Sangat Tinggi (Untestable)"
        risk_color = "#dc3545"
        desc = "Kode tidak dapat diuji dengan baik. Wajib dilakukan refactoring menyeluruh."

    return {
        "P": p,
        "N": n_count,
        "E": e_count,
        "CC": cc,
        "CC_formula": cc_full,
        "risk_level": risk_level,
        "risk_color": risk_color,
        "desc": desc,
    }

# ─────────────────────────────────────────────
# HELPER: CFG GRAPHVIZ (numbered circles)
# ─────────────────────────────────────────────
def generate_cfg(nodes):
    dot = graphviz.Digraph("CFG")
    dot.attr(rankdir='TB', bgcolor='transparent', fontname='Arial')
    dot.attr('node', fontname='Arial', fontsize='13')
    dot.attr('edge', fontname='Arial', fontsize='11', color='#444444')

    # START node
    dot.node('START', 'START', shape='oval', style='filled,bold',
             fillcolor='#1a472a', fontcolor='white', color='#1a472a', width='1')

    for n in nodes:
        nid = str(n["node_id"])
        if n["node_type"] == "decision":
            dot.node(nid, nid, shape='circle', style='filled',
                     fillcolor='#e8c547', fontcolor='#1a1a1a',
                     color='#c8a020', width='0.8', fixedsize='true',
                     penwidth='2')
        else:
            dot.node(nid, nid, shape='circle', style='filled',
                     fillcolor='#2c5f8a', fontcolor='white',
                     color='#1a3f5f', width='0.8', fixedsize='true')

    # END node
    dot.node('END', 'END', shape='oval', style='filled,bold',
             fillcolor='#6b1a1a', fontcolor='white', color='#6b1a1a', width='1')

    # Edges
    if nodes:
        dot.edge('START', str(nodes[0]["node_id"]))

    for i, n in enumerate(nodes):
        nid = str(n["node_id"])
        if n["node_type"] == "decision":
            next_nid = str(nodes[i+1]["node_id"]) if i+1 < len(nodes) else 'END'
            after_nid = str(nodes[i+2]["node_id"]) if i+2 < len(nodes) else 'END'
            dot.edge(nid, next_nid, label='True', color='#28a745', fontcolor='#28a745')
            dot.edge(nid, after_nid, label='False', color='#dc3545', fontcolor='#dc3545', style='dashed')
        else:
            next_nid = str(nodes[i+1]["node_id"]) if i+1 < len(nodes) else 'END'
            dot.edge(nid, next_nid)

    if nodes:
        dot.edge(str(nodes[-1]["node_id"]), 'END')

    return dot

# ─────────────────────────────────────────────
# HELPER: INDEPENDENT PATHS
# ─────────────────────────────────────────────
def generate_independent_paths(nodes, cc):
    paths = []
    node_ids = [n["node_id"] for n in nodes]
    decision_ids = [n["node_id"] for n in nodes if n["node_type"] == "decision"]

    if not node_ids:
        return paths

    # Path 1: straight through
    paths.append({"path_no": 1, "description": "Jalur normal (semua kondisi False)", "sequence": ["START"] + [str(i) for i in node_ids] + ["END"]})

    # Additional paths: each decision branching True
    for idx, did in enumerate(decision_ids):
        if len(paths) >= cc:
            break
        path_seq = ["START"]
        for n in nodes:
            path_seq.append(str(n["node_id"]))
            if n["node_id"] == did:
                path_seq.append(f"({str(did)}→True branch)")
                break
        path_seq.append("END")
        paths.append({
            "path_no": len(paths) + 1,
            "description": f"Jalur dengan Node {did} = True",
            "sequence": path_seq,
        })

    return paths[:cc]

# ─────────────────────────────────────────────
# REPORT EXPORT (HTML → print-friendly)
# ─────────────────────────────────────────────
def build_html_report(project_name, analyst_name, loc_metrics, cc_data, nodes, paths, code_input, cfg_svg_str):
    today = datetime.date.today().strftime("%d %B %Y")
    node_rows = ""
    for n in nodes:
        badge = "🔶 Decision" if n["node_type"] == "decision" else "🔵 Process"
        node_rows += f"""
        <tr>
            <td class="center bold">{n['node_id']}</td>
            <td class="center">{badge}</td>
            <td class="center">{n['start_line']}</td>
            <td class="center">{n['end_line']}</td>
            <td>{n['lines_preview']}</td>
        </tr>"""

    path_rows = ""
    for p in paths:
        path_rows += f"""
        <tr>
            <td class="center bold">P{p['path_no']}</td>
            <td>{p['description']}</td>
            <td class="mono">{' → '.join(p['sequence'])}</td>
        </tr>"""

    cfg_block = cfg_svg_str if cfg_svg_str else "<p><em>CFG tidak dapat dirender.</em></p>"

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<title>Laporan White Box Testing – {project_name}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',sans-serif;font-size:10.5pt;color:#1a1a2e;background:#fff;line-height:1.6}}
  .cover{{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background:linear-gradient(160deg,#0f2027,#203a43,#2c5364);color:white;text-align:center;padding:60px 40px;page-break-after:always}}
  .cover .logo{{font-size:48pt;margin-bottom:20px}}
  .cover h1{{font-family:'Source Serif 4',serif;font-size:22pt;font-weight:700;margin-bottom:8px;line-height:1.3}}
  .cover h2{{font-family:'Source Serif 4',serif;font-size:14pt;font-weight:400;opacity:.8;margin-bottom:40px}}
  .cover .meta{{border-top:1px solid rgba(255,255,255,.3);padding-top:24px;margin-top:24px;opacity:.85;font-size:10pt;line-height:2}}
  .content{{max-width:900px;margin:0 auto;padding:40px 48px}}
  h2{{font-family:'Source Serif 4',serif;font-size:14pt;font-weight:700;color:#0f2027;border-bottom:2px solid #2c5364;padding-bottom:6px;margin:32px 0 16px}}
  h3{{font-size:11pt;font-weight:600;color:#203a43;margin:20px 0 10px}}
  .card-row{{display:grid;gap:16px;margin-bottom:24px}}
  .card-row.four{{grid-template-columns:repeat(4,1fr)}}
  .card-row.three{{grid-template-columns:repeat(3,1fr)}}
  .card{{background:#f0f4f8;border-radius:8px;padding:16px;text-align:center;border-left:4px solid #2c5364}}
  .card .val{{font-size:18pt;font-weight:700;color:#0f2027}}
  .card .lbl{{font-size:8.5pt;color:#555;margin-top:4px}}
  .risk-badge{{display:inline-block;background:{cc_data['risk_color']};color:white;padding:6px 18px;border-radius:20px;font-weight:600;font-size:10.5pt}}
  table{{width:100%;border-collapse:collapse;margin:12px 0 24px;font-size:9.5pt}}
  th{{background:#0f2027;color:white;padding:9px 12px;text-align:left;font-weight:600}}
  td{{padding:8px 12px;border-bottom:1px solid #e0e6ed}}
  tr:nth-child(even) td{{background:#f7f9fc}}
  .center{{text-align:center}}
  .bold{{font-weight:600}}
  .mono{{font-family:'JetBrains Mono',monospace;font-size:8.5pt}}
  pre{{background:#0f1923;color:#a8d8ea;padding:20px;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:8pt;overflow-x:auto;white-space:pre-wrap;word-break:break-all;margin:12px 0 24px}}
  .cfg-wrap{{background:#f7f9fc;border:1px solid #dde3ea;border-radius:8px;padding:20px;text-align:center;margin:12px 0 24px}}
  .cfg-wrap svg{{max-width:100%;height:auto}}
  .formula-box{{background:#fff8e1;border-left:4px solid #ffc107;border-radius:6px;padding:14px 18px;margin:12px 0;font-family:'JetBrains Mono',monospace;font-size:10pt}}
  .conclusion{{background:#e8f4fd;border-radius:8px;padding:20px 24px;margin-top:16px;border-left:5px solid #2c5364;line-height:1.8}}
  .footer{{text-align:center;color:#999;font-size:8pt;margin-top:48px;padding-top:16px;border-top:1px solid #e0e6ed}}
  @media print{{
    .cover{{min-height:auto;padding:40px}}
    .content{{padding:20px 32px}}
    pre{{font-size:7pt}}
  }}
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover">
  <div class="logo">🧪</div>
  <h1>LAPORAN MANAJEMEN KUALITAS PERANGKAT LUNAK</h1>
  <h2>White Box Testing — LOC Metrics &amp; Basis Path Analysis</h2>
  <div class="meta">
    <div><strong>Nama Proyek:</strong> {project_name}</div>
    <div><strong>Analis:</strong> {analyst_name}</div>
    <div><strong>Tanggal:</strong> {today}</div>
    <div><strong>Metode:</strong> McCabe Cyclomatic Complexity + LOC Analysis</div>
  </div>
</div>

<!-- CONTENT -->
<div class="content">

  <!-- 1. LOC -->
  <h2>I. Pengujian Metrik LOC (Lines of Code)</h2>
  <p>Analisis LOC mengukur ukuran dan kepadatan kode secara kuantitatif dengan memisahkan baris aktif, baris kosong, dan baris komentar.</p>
  <h3>Rumus</h3>
  <div class="formula-box">
    LOC  = Total Baris Kasar − Baris Kosong − Baris Komentar<br>
    KLOC = LOC / 1000<br>
    Kesalahan/KLOC = Total Bug / KLOC<br>
    Biaya/LOC      = Total Biaya / Total Baris Kasar
  </div>
  <h3>Hasil Perhitungan</h3>
  <div class="card-row four">
    <div class="card"><div class="val">{loc_metrics['Total Baris Kasar']}</div><div class="lbl">Total Baris Kasar</div></div>
    <div class="card"><div class="val">{loc_metrics['Baris Kosong']}</div><div class="lbl">Baris Kosong</div></div>
    <div class="card"><div class="val">{loc_metrics['Baris Komentar']}</div><div class="lbl">Baris Komentar</div></div>
    <div class="card"><div class="val">{loc_metrics['Nilai LOC']}</div><div class="lbl">Nilai LOC Bersih</div></div>
  </div>
  <div class="card-row three">
    <div class="card"><div class="val">{loc_metrics['Nilai KLOC']}</div><div class="lbl">Nilai KLOC</div></div>
    <div class="card"><div class="val">{loc_metrics['Kesalahan per KLOC']}</div><div class="lbl">Kesalahan / KLOC</div></div>
    <div class="card"><div class="val">Rp {loc_metrics['Biaya per LOC']:,.0f}</div><div class="lbl">Biaya / LOC</div></div>
  </div>

  <!-- 2. CFG & CC -->
  <h2>II. Control Flow Graph (CFG) &amp; Cyclomatic Complexity</h2>
  <h3>Rumus McCabe</h3>
  <div class="formula-box">
    V(G) = P + 1&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(P = jumlah predikat / simpul keputusan)<br>
    V(G) = E − N + 2 &nbsp;(E = edges, N = nodes)
  </div>
  <div class="card-row four">
    <div class="card"><div class="val">{cc_data['N']}</div><div class="lbl">Total Node (N)</div></div>
    <div class="card"><div class="val">{cc_data['E']}</div><div class="lbl">Total Edge (E)</div></div>
    <div class="card"><div class="val">{cc_data['P']}</div><div class="lbl">Predikat (P)</div></div>
    <div class="card"><div class="val">{cc_data['CC']}</div><div class="lbl">Cyclomatic Complexity V(G)</div></div>
  </div>
  <p>Status Risiko: <span class="risk-badge">{cc_data['risk_level']}</span></p>
  <p style="margin-top:10px">{cc_data['desc']}</p>

  <h3>Visualisasi CFG</h3>
  <div class="cfg-wrap">
    {cfg_block}
  </div>
  <p style="font-size:9pt;color:#555;text-align:center">🟡 = Decision Node (simpul keputusan/predikat) &nbsp;|&nbsp; 🔵 = Process Node (simpul proses)</p>

  <!-- 3. NODE TABLE -->
  <h2>III. Tabel Penjabaran Node</h2>
  <p>Setiap node merepresentasikan satu blok logika atau satu titik keputusan dalam alur program.</p>
  <table>
    <thead>
      <tr><th>No. Node</th><th>Tipe</th><th>Baris Mulai</th><th>Baris Akhir</th><th>Keterangan Kode</th></tr>
    </thead>
    <tbody>{node_rows}</tbody>
  </table>

  <!-- 4. INDEPENDENT PATHS -->
  <h2>IV. Jalur Independen (Basis Path)</h2>
  <p>Jumlah jalur independen = V(G) = <strong>{cc_data['CC']}</strong>. Berikut daftar jalur yang harus diuji:</p>
  <table>
    <thead>
      <tr><th style="width:60px">Jalur</th><th>Deskripsi</th><th>Urutan Node</th></tr>
    </thead>
    <tbody>{path_rows}</tbody>
  </table>

  <!-- 5. KODE SUMBER -->
  <h2>V. Kode Sumber yang Dianalisis</h2>
  <pre>{code_input}</pre>

  <!-- 6. KESIMPULAN -->
  <h2>VI. Kesimpulan &amp; Rekomendasi</h2>
  <div class="conclusion">
    <p><strong>Ukuran Kode (LOC):</strong> Program memiliki <strong>{loc_metrics['Nilai LOC']} LOC bersih</strong> dari total {loc_metrics['Total Baris Kasar']} baris kasar. KLOC sebesar <strong>{loc_metrics['Nilai KLOC']}</strong>, dengan estimasi kesalahan <strong>{loc_metrics['Kesalahan per KLOC']} bug/KLOC</strong> dan biaya produksi <strong>Rp {loc_metrics['Biaya per LOC']:,.0f}/baris</strong>.</p>
    <br>
    <p><strong>Kompleksitas (CFG):</strong> Berdasarkan analisis McCabe, kode memiliki <strong>{cc_data['P']} simpul keputusan</strong>, menghasilkan nilai <em>Cyclomatic Complexity</em> <strong>V(G) = {cc_data['CC']}</strong>. Sistem tergolong <strong>{cc_data['risk_level']}</strong>. {cc_data['desc']}</p>
    <br>
    <p><strong>Basis Path:</strong> Terdapat <strong>{cc_data['CC']} jalur independen</strong> yang harus dicakup dalam test case untuk memastikan pengujian white box yang komprehensif.</p>
    <br>
    <p><strong>Rekomendasi:</strong> {"Lanjutkan ke tahap pengujian unit untuk setiap jalur independen. Dokumentasikan test case berdasarkan setiap basis path yang teridentifikasi." if cc_data['CC'] <= 10 else "Pertimbangkan pemisahan fungsi/modul sebelum melanjutkan ke production. Prioritaskan refactoring pada decision node yang paling kompleks."}</p>
  </div>

  <div class="footer">
    Laporan dibuat otomatis oleh White Box Testing Analyzer &nbsp;|&nbsp; {today} &nbsp;|&nbsp; Analis: {analyst_name}
  </div>
</div>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="White Box Testing Analyzer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;700&family=JetBrains+Mono&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

.main-header {
    background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
    color: white;
    padding: 40px 48px;
    border-radius: 16px;
    margin-bottom: 32px;
    text-align: center;
}
.main-header h1 { font-family: 'Source Serif 4', serif; font-size: 2rem; font-weight: 700; margin-bottom: 6px; }
.main-header p  { opacity: .75; font-size: 1rem; }

.metric-card {
    background: linear-gradient(135deg, #f0f4f8, #e8edf2);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    border-top: 4px solid #2c5364;
    margin-bottom: 12px;
}
.metric-card .val { font-size: 1.9rem; font-weight: 700; color: #0f2027; }
.metric-card .lbl { font-size: .8rem; color: #666; margin-top: 4px; }

.risk-card {
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    text-align: center;
    border: 2px solid;
}

.node-badge-decision { background:#fff3cd; color:#856404; padding:3px 10px; border-radius:12px; font-size:.8rem; font-weight:600; }
.node-badge-process   { background:#cce5ff; color:#004085; padding:3px 10px; border-radius:12px; font-size:.8rem; font-weight:600; }

.formula-box {
    background: #fff8e1;
    border-left: 4px solid #ffc107;
    border-radius: 8px;
    padding: 14px 18px;
    font-family: 'JetBrains Mono', monospace;
    font-size: .9rem;
    margin: 12px 0;
}

.section-label {
    font-size:.75rem;
    font-weight:600;
    letter-spacing:.1em;
    text-transform:uppercase;
    color:#2c5364;
    margin-bottom:8px;
}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
  <h1>⚗️ White Box Testing Analyzer</h1>
  <p>Analisis LOC Metrics • Cyclomatic Complexity • Control Flow Graph • Basis Path</p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR: Project Info ────────────────────
with st.sidebar:
    st.markdown("### 📋 Informasi Proyek")
    project_name = st.text_input("Nama Proyek", value="Proyek Software A")
    analyst_name = st.text_input("Nama Analis", value="Tim QA")
    st.divider()
    st.markdown("### ⚙️ Parameter Analisis")
    input_biaya = st.number_input("Total Biaya Proyek (Rp)", min_value=0, value=4_000_000, step=100_000, format="%d")
    input_bug   = st.number_input("Asumsi Jumlah Bug", min_value=0, value=2)
    st.divider()
    st.caption("📄 White Box Testing Analyzer v2.0\nBerbasis McCabe Cyclomatic Complexity")

# ── MAIN: Code Input ────────────────────────
st.markdown('<div class="section-label">Input Kode Program</div>', unsafe_allow_html=True)
code_input = st.text_area(
    "Tempel kode program di sini (PHP, Python, JavaScript, dll.):",
    height=280,
    placeholder="// Tempel kode Anda di sini...\nfunction contoh() {\n    if (x > 0) {\n        return x;\n    } else {\n        return -x;\n    }\n}",
    label_visibility="collapsed",
)

col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])
with col_btn1:
    run_btn = st.button("▶ Jalankan Analisis", type="primary", use_container_width=True)
with col_btn2:
    clear_btn = st.button("🗑 Bersihkan", use_container_width=True)

if clear_btn:
    st.rerun()

st.divider()

# ── ANALYSIS ────────────────────────────────
if run_btn:
    if not code_input.strip():
        st.warning("⚠️ Silakan masukkan kode program terlebih dahulu.")
        st.stop()

    with st.spinner("Menganalisis kode..."):
        loc_metrics = calculate_loc_metrics(code_input, input_biaya, input_bug)
        nodes       = segment_code_into_nodes(code_input)
        cc_data     = calculate_cyclomatic_complexity(nodes)
        paths       = generate_independent_paths(nodes, cc_data["CC"])
        cfg_graph   = generate_cfg(nodes)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Metrik LOC",
        "🔷 CFG & Node Table",
        "🧠 Cyclomatic Complexity",
        "🛤️ Basis Path",
        "📄 Export Laporan",
    ])

    # ── TAB 1: LOC ──────────────────────────
    with tab1:
        st.markdown("### I. Pengujian Metrik LOC")
        st.markdown('<div class="formula-box">LOC = Total Baris Kasar − Baris Kosong − Baris Komentar<br>KLOC = LOC / 1000<br>Kesalahan/KLOC = Total Bug / KLOC<br>Biaya/LOC = Total Biaya / Total Baris Kasar</div>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        for col, key, lbl in [
            (c1, "Total Baris Kasar", "Total Baris Kasar"),
            (c2, "Baris Kosong",      "Baris Kosong"),
            (c3, "Baris Komentar",    "Baris Komentar"),
            (c4, "Nilai LOC",         "LOC Bersih"),
        ]:
            with col:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics[key]}</div><div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)

        c5, c6, c7 = st.columns(3)
        for col, key, lbl, fmt in [
            (c5, "Nilai KLOC",          "Nilai KLOC",        f"{loc_metrics['Nilai KLOC']:.4f}"),
            (c6, "Kesalahan per KLOC",  "Kesalahan / KLOC",  f"{loc_metrics['Kesalahan per KLOC']} bug"),
            (c7, "Biaya per LOC",       "Biaya / LOC",       f"Rp {loc_metrics['Biaya per LOC']:,.0f}"),
        ]:
            with col:
                st.markdown(f'<div class="metric-card"><div class="val">{fmt}</div><div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)

    # ── TAB 2: CFG ──────────────────────────
    with tab2:
        st.markdown("### II. Control Flow Graph (CFG)")
        col_cfg, col_tbl = st.columns([1, 1])

        with col_cfg:
            st.graphviz_chart(cfg_graph, use_container_width=True)
            st.caption("🟡 Node kuning = Decision (percabangan) · 🔵 Node biru = Process · ⬛ START/END")

        with col_tbl:
            st.markdown("#### Tabel Penjabaran Node")
            if nodes:
                import pandas as pd
                df = pd.DataFrame([{
                    "Node": n["node_id"],
                    "Tipe": "🔶 Decision" if n["node_type"] == "decision" else "🔵 Process",
                    "Baris Mulai": n["start_line"],
                    "Baris Akhir": n["end_line"],
                    "Keterangan Kode": n["lines_preview"],
                } for n in nodes])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("Tidak ada node terdeteksi.")

    # ── TAB 3: CC ───────────────────────────
    with tab3:
        st.markdown("### III. Cyclomatic Complexity (McCabe)")
        st.markdown('<div class="formula-box">V(G) = P + 1 &nbsp;(P = jumlah predikat)<br>V(G) = E − N + 2 &nbsp;(E = edges, N = nodes)</div>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        for col, val, lbl in [
            (c1, cc_data["N"], "Total Node (N)"),
            (c2, cc_data["E"], "Total Edge (E)"),
            (c3, cc_data["P"], "Predikat (P)"),
            (c4, cc_data["CC"], "V(G) / CC"),
        ]:
            with col:
                st.markdown(f'<div class="metric-card"><div class="val">{val}</div><div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background:{cc_data['risk_color']}18;border:2px solid {cc_data['risk_color']};
                    border-radius:12px;padding:20px 24px;margin-top:16px;">
            <div style="font-size:1.1rem;font-weight:700;color:{cc_data['risk_color']}">
                Status: {cc_data['risk_level']}
            </div>
            <div style="margin-top:8px;color:#333">{cc_data['desc']}</div>
            <div style="margin-top:10px;font-size:.9rem;color:#555">
                Nilai V(G) = <strong>{cc_data['CC']}</strong> berarti terdapat 
                <strong>{cc_data['CC']} jalur independen</strong> yang harus diuji.
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### Tabel Skala Risiko McCabe")
        risk_df_data = {
            "Nilai CC": ["1 – 10", "11 – 20", "21 – 50", "> 50"],
            "Tingkat Risiko": ["🟢 Rendah (Low Risk)", "🟡 Sedang (Moderate)", "🟠 Tinggi (High Risk)", "🔴 Sangat Tinggi (Untestable)"],
            "Keterangan": [
                "Sederhana, mudah diuji",
                "Dapat dikelola, mulai pisahkan fungsi",
                "Padat & rawan bug, perlu refactoring",
                "Tidak dapat diuji, wajib refactoring",
            ],
        }
        import pandas as pd
        st.dataframe(pd.DataFrame(risk_df_data), use_container_width=True, hide_index=True)

    # ── TAB 4: BASIS PATH ───────────────────
    with tab4:
        st.markdown("### IV. Jalur Independen (Basis Path Testing)")
        st.info(f"Terdapat **{cc_data['CC']} jalur independen** yang harus dicakup test case berdasarkan V(G) = {cc_data['CC']}.")
        if paths:
            import pandas as pd
            df_paths = pd.DataFrame([{
                "Jalur": f"P{p['path_no']}",
                "Deskripsi": p["description"],
                "Urutan Node": " → ".join(p["sequence"]),
            } for p in paths])
            st.dataframe(df_paths, use_container_width=True, hide_index=True)
        else:
            st.warning("Jalur independen tidak dapat diidentifikasi. Pastikan kode memiliki struktur yang valid.")

    # ── TAB 5: EXPORT ───────────────────────
    with tab5:
        st.markdown("### 📄 Export Laporan")
        st.info("Laporan akan diekspor sebagai file HTML yang dapat langsung dicetak sebagai PDF dari browser (Ctrl+P → Save as PDF).")

        # Render CFG to SVG string
        try:
            cfg_svg_bytes = cfg_graph.pipe(format='svg')
            cfg_svg_str   = cfg_svg_bytes.decode('utf-8')
        except Exception:
            cfg_svg_str   = ""

        html_report = build_html_report(
            project_name, analyst_name,
            loc_metrics, cc_data, nodes, paths,
            code_input, cfg_svg_str,
        )

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="⬇️ Download Laporan HTML",
                data=html_report.encode("utf-8"),
                file_name=f"laporan_wbt_{project_name.replace(' ','_')}.html",
                mime="text/html",
                use_container_width=True,
                type="primary",
            )
        with col_dl2:
            st.download_button(
                label="⬇️ Download Laporan JSON (Raw Data)",
                data=json.dumps({
                    "project": project_name,
                    "analyst": analyst_name,
                    "loc_metrics": loc_metrics,
                    "cc_data": {k: v for k, v in cc_data.items() if k != "risk_color"},
                    "nodes": [{k: v for k, v in n.items() if k != "raw_lines"} for n in nodes],
                    "paths": paths,
                }, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name=f"data_wbt_{project_name.replace(' ','_')}.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("#### Preview Laporan")
        st.markdown(html_report, unsafe_allow_html=True)