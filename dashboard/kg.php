<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

$env = load_env(__DIR__ . '/../.env');
$kg_api_url = $env['KG_API_URL'] ?? getenv('KG_API_URL') ?: 'http://127.0.0.1:8089';

// Ontology summary (static view — does not require the API to be up).
$ontology_summary = null;
try {
    $pdo = pdo_from_env();
    $ontology_summary = [
        'classes' => $pdo->query("SELECT class_name, description, source_table FROM graph.ontology_class ORDER BY class_name")->fetchAll(),
        'relationships' => $pdo->query("SELECT name, description, from_class, to_class, kind FROM graph.ontology_relationship ORDER BY name")->fetchAll(),
        'node_counts' => $pdo->query("SELECT class_name, COUNT(*) AS n FROM graph.node GROUP BY class_name ORDER BY n DESC")->fetchAll(),
        'edge_counts' => $pdo->query("SELECT relationship_name, COUNT(*) AS n FROM graph.edge GROUP BY relationship_name ORDER BY n DESC")->fetchAll(),
    ];
} catch (Throwable $e) {
    $ontology_summary = ['error' => $e->getMessage()];
}

// Handle an AJAX POST: proxy to the Python API and return JSON. Keeps the
// Ollama call off the public PHP process and centralizes auth if added later.
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_SERVER['CONTENT_TYPE'] ?? '') === 'application/json') {
    $raw = file_get_contents('php://input');
    $ctx = stream_context_create([
        'http' => [
            'method'  => 'POST',
            'header'  => "Content-Type: application/json\r\n",
            'content' => $raw,
            'timeout' => 180,
            'ignore_errors' => true,
        ],
    ]);
    $resp = @file_get_contents($kg_api_url . '/ask', false, $ctx);
    header('Content-Type: application/json');
    if ($resp === false) {
        http_response_code(502);
        echo json_encode(['error' => "KG API unreachable at $kg_api_url"]);
        exit;
    }
    echo $resp;
    exit;
}
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DW Knowledge Graph — Phase 4</title>
<style>
:root {
  --bg: #0f172a; --card: #1e293b; --ink: #e2e8f0; --muted: #94a3b8;
  --accent: #38bdf8; --ok: #22c55e; --warn: #eab308; --bad: #ef4444; --border: #334155;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--ink); margin: 0; padding: 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 24px 0 8px; }
.sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.grid { display: grid; grid-template-columns: 1fr 360px; gap: 16px; }
@media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.chat-log { height: 480px; overflow-y: auto; background: #0b1222; border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-size: 14px; }
.msg { margin-bottom: 14px; padding: 10px 12px; border-radius: 8px; }
.msg.user { background: #1e3a8a; color: #dbeafe; }
.msg.bot  { background: #0f172a; border: 1px solid var(--border); }
.msg.err  { background: rgba(239,68,68,0.15); color: var(--bad); border: 1px solid rgba(239,68,68,0.4); }
.msg .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; }
.msg pre { margin: 8px 0 0; padding: 8px 10px; background: #020617; border-radius: 6px; overflow-x: auto; font-size: 12px; color: #a5f3fc; }
.msg table { margin-top: 8px; border-collapse: collapse; width: 100%; font-size: 12px; }
.msg th, .msg td { padding: 4px 8px; border-bottom: 1px solid var(--border); text-align: left; }
.input-row { display: flex; gap: 8px; margin-top: 12px; }
.input-row input[type=text] { flex: 1; background: #0b1222; color: var(--ink); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; font-size: 14px; }
.input-row button { background: var(--accent); color: #0b1222; border: 0; border-radius: 6px; padding: 10px 18px; font-weight: 600; cursor: pointer; }
.input-row button:disabled { opacity: 0.6; cursor: wait; }
.side h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 0 0 8px; }
.side ul { list-style: none; padding: 0; margin: 0 0 16px; font-size: 12px; }
.side ul li { padding: 4px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; }
.side ul li span.count { color: var(--accent); font-variant-numeric: tabular-nums; }
.sample { display: inline-block; margin: 2px 4px 0 0; padding: 4px 8px; background: #0b1222; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; cursor: pointer; color: var(--accent); }
.sample:hover { background: #1e293b; }
.status { font-size: 11px; color: var(--muted); }
</style>
</head>
<body>
  <h1>Knowledge Graph Q&amp;A <span class="status">(Phase 4)</span></h1>
  <div class="sub">Ask natural-language questions about the retail knowledge graph. Powered by an Ollama LLM generating SQL over <code>graph.node</code> / <code>graph.edge</code>.</div>

  <div class="grid">
    <div>
      <div class="card">
        <div id="log" class="chat-log">
          <div class="msg bot">
            <div class="label">Assistant</div>
            <div>Hello. Try a sample question on the right, or ask your own.</div>
          </div>
        </div>
        <div class="input-row">
          <input type="text" id="q" placeholder="e.g. Which top 5 customers have the highest total net paid?" autofocus />
          <button id="send">Ask</button>
        </div>
        <div class="status" id="status">API: <?= h($kg_api_url) ?></div>
      </div>
    </div>

    <aside class="side">
      <div class="card">
        <h3>Samples</h3>
        <div>
          <span class="sample">How many customers are in the graph?</span>
          <span class="sample">List 5 items in the 'Sports' category with their brand.</span>
          <span class="sample">Which stores are located in CA?</span>
          <span class="sample">Top 5 customers by total net paid (PURCHASED edges).</span>
          <span class="sample">How many customers live in addresses in NY?</span>
          <span class="sample">What are the most common return reasons?</span>
        </div>
      </div>

      <div class="card" style="margin-top: 16px;">
        <h3>Graph — classes</h3>
        <ul>
          <?php foreach (($ontology_summary['node_counts'] ?? []) as $row): ?>
            <li><span><?= h($row['class_name']) ?></span> <span class="count"><?= fmt_num($row['n']) ?></span></li>
          <?php endforeach; ?>
        </ul>
        <h3>Graph — relationships</h3>
        <ul>
          <?php foreach (($ontology_summary['edge_counts'] ?? []) as $row): ?>
            <li><span><?= h($row['relationship_name']) ?></span> <span class="count"><?= fmt_num($row['n']) ?></span></li>
          <?php endforeach; ?>
        </ul>
      </div>
    </aside>
  </div>

<script>
const logEl = document.getElementById('log');
const qEl   = document.getElementById('q');
const btn   = document.getElementById('send');
const statusEl = document.getElementById('status');

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function append(cls, title, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.innerHTML = `<div class="label">${escapeHtml(title)}</div>${html}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}
function renderTable(cols, rows) {
  if (!rows || !rows.length) return '<div><em>No rows.</em></div>';
  const head = '<tr>' + cols.map(c => `<th>${escapeHtml(c)}</th>`).join('') + '</tr>';
  const body = rows.slice(0, 20).map(r =>
    '<tr>' + r.map(v => `<td>${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : v)}</td>`).join('') + '</tr>'
  ).join('');
  const more = rows.length > 20 ? `<div class="status">showing 20 of ${rows.length} rows</div>` : '';
  return `<table>${head}${body}</table>${more}`;
}
async function ask(question) {
  append('user', 'You', escapeHtml(question));
  btn.disabled = true; statusEl.textContent = 'Thinking…';
  try {
    const resp = await fetch(window.location.pathname, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      append('err', 'Error', escapeHtml(data.error || ('HTTP ' + resp.status)));
    } else {
      const html =
        `<div>${escapeHtml(data.answer || '(no narrative)')}</div>` +
        (data.sql ? `<pre>${escapeHtml(data.sql)}</pre>` : '') +
        renderTable(data.columns || [], data.rows || []);
      append('bot', 'Assistant', html);
    }
  } catch (e) {
    append('err', 'Error', escapeHtml(e.message));
  } finally {
    btn.disabled = false; statusEl.textContent = 'API: <?= h($kg_api_url) ?>';
    qEl.value = ''; qEl.focus();
  }
}
btn.addEventListener('click', () => { if (qEl.value.trim()) ask(qEl.value.trim()); });
qEl.addEventListener('keydown', (e) => { if (e.key === 'Enter' && qEl.value.trim()) ask(qEl.value.trim()); });
document.querySelectorAll('.sample').forEach(el => {
  el.addEventListener('click', () => ask(el.textContent.trim()));
});
</script>
</body>
</html>
