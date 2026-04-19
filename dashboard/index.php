<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

try {
    $pdo = pdo_from_env();
} catch (Throwable $e) {
    http_response_code(500);
    echo "<h1>DB connection failed</h1><pre>" . h($e->getMessage()) . "</pre>";
    exit;
}

// Latest run
$latest = $pdo->query(
    "SELECT run_id, started_at, ended_at, status, tables_loaded, rows_loaded, error_message,
            EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at)) AS duration_s
     FROM ops.ingest_runs ORDER BY run_id DESC LIMIT 1"
)->fetch();

// Recent runs (10)
$recent = $pdo->query(
    "SELECT run_id, started_at, status, tables_loaded, rows_loaded,
            EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at)) AS duration_s
     FROM ops.ingest_runs ORDER BY run_id DESC LIMIT 10"
)->fetchAll();

// Per-table stats for latest run
$table_stats = [];
if ($latest) {
    $stmt = $pdo->prepare(
        "SELECT table_name, rows_loaded, bytes_loaded, duration_s, status, error_message
         FROM ops.ingest_table_stats WHERE run_id = :rid ORDER BY bytes_loaded DESC"
    );
    $stmt->execute([':rid' => $latest['run_id']]);
    $table_stats = $stmt->fetchAll();
}

// DQ test results for latest run
$test_results = [];
$test_summary = ['pass' => 0, 'fail' => 0, 'other' => 0];
if ($latest) {
    $stmt = $pdo->prepare(
        "SELECT test_name, status, failures, message
         FROM ops.dbt_test_results WHERE run_id = :rid ORDER BY status DESC, test_name"
    );
    $stmt->execute([':rid' => $latest['run_id']]);
    $test_results = $stmt->fetchAll();
    foreach ($test_results as $t) {
        if ($t['status'] === 'pass') $test_summary['pass']++;
        elseif (in_array($t['status'], ['fail', 'error'], true)) $test_summary['fail']++;
        else $test_summary['other']++;
    }
}

// Silver table stats (approximate, from pg_class after ANALYZE)
$silver_raw = $pdo->query(
    "SELECT c.relname,
            GREATEST(c.reltuples::bigint, 0) AS approx_rows,
            pg_total_relation_size(c.oid) AS bytes
     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'silver' AND c.relkind = 'r'
     ORDER BY c.relname"
)->fetchAll();
$silver_by_name = [];
foreach ($silver_raw as $r) {
    $silver_by_name[$r['relname']] = $r;
}
$silver_rows = [];
$silver_total_rows = 0;
$silver_total_anom = 0;
foreach ($silver_by_name as $name => $r) {
    if (str_ends_with($name, '__anomalies')) continue;
    $anom = $silver_by_name[$name . '__anomalies'] ?? null;
    $rows = (int) $r['approx_rows'];
    $anom_rows = $anom ? (int) $anom['approx_rows'] : 0;
    $silver_total_rows += $rows;
    $silver_total_anom += $anom_rows;
    $silver_rows[] = [
        'table' => $name,
        'rows' => $rows,
        'bytes' => (int) $r['bytes'],
        'anom_rows' => $anom_rows,
    ];
}

// Gold marts
$gold_rows = $pdo->query(
    "SELECT c.relname,
            GREATEST(c.reltuples::bigint, 0) AS approx_rows,
            pg_total_relation_size(c.oid) AS bytes
     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'gold' AND c.relkind = 'r'
     ORDER BY c.relname"
)->fetchAll();
$gold_total_rows = array_sum(array_map(fn($r) => (int) $r['approx_rows'], $gold_rows));
$gold_count = count($gold_rows);

// Gold KPIs (only if marts exist)
$kpis = null;
if ($gold_count > 0) {
    try {
        $kpis = $pdo->query("
            SELECT
              (SELECT COUNT(*) FROM gold.mart_customer_360 WHERE segment = 'Champions') AS champions,
              (SELECT COUNT(*) FROM gold.mart_customer_360 WHERE segment = 'At risk high-value') AS at_risk,
              (SELECT MAX(total_net_sales) FROM gold.mart_product_analytics) AS top_item_sales,
              (SELECT SUM(total_net_sales) FROM gold.mart_channel_comparison) AS lifetime_net_sales
        ")->fetch();
    } catch (Throwable $_) { $kpis = null; }
}

// Pipeline perf: top slowest nodes this run + per-run wall clock history
$slowest = [];
$run_history = [];
if ($latest) {
    $stmt = $pdo->prepare(
        "SELECT node_id, node_type, execution_time_s, status
         FROM ops.dbt_node_timings WHERE run_id = :rid
         ORDER BY execution_time_s DESC LIMIT 10"
    );
    $stmt->execute([':rid' => $latest['run_id']]);
    $slowest = $stmt->fetchAll();

    $run_history = $pdo->query(
        "SELECT r.run_id,
                EXTRACT(EPOCH FROM (r.ended_at - r.started_at)) AS wall_s,
                COALESCE((SELECT SUM(execution_time_s)
                          FROM ops.dbt_node_timings WHERE run_id = r.run_id), 0) AS dbt_node_s,
                COALESCE((SELECT SUM(duration_s)
                          FROM ops.ingest_table_stats WHERE run_id = r.run_id), 0) AS bronze_s
         FROM ops.ingest_runs r
         WHERE r.status = 'success'
         ORDER BY r.run_id DESC LIMIT 8"
    )->fetchAll();
}

// DB tuning visibility
$db_tuning = $pdo->query(
    "SELECT name, setting, unit
     FROM pg_settings
     WHERE name IN ('work_mem', 'max_parallel_workers_per_gather', 'shared_buffers')
     ORDER BY name"
)->fetchAll();

$status_class = fn($s) => match ($s) {
    'success', 'pass'   => 'ok',
    'running'           => 'warn',
    'failed', 'fail', 'error' => 'bad',
    default             => 'muted',
};
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>DW Pipeline — Phase 0 Dashboard</title>
<style>
:root {
  --bg: #0f172a; --card: #1e293b; --ink: #e2e8f0; --muted: #94a3b8;
  --ok: #22c55e; --warn: #eab308; --bad: #ef4444; --border: #334155;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--ink); margin: 0; padding: 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 24px 0 8px; }
h3 { font-weight: 600; }
.sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
.card .value { font-size: 26px; font-weight: 600; margin-top: 6px; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.pill.ok    { background: rgba(34,197,94,0.15);  color: var(--ok); }
.pill.warn  { background: rgba(234,179,8,0.15);  color: var(--warn); }
.pill.bad   { background: rgba(239,68,68,0.15);  color: var(--bad); }
.pill.muted { background: rgba(148,163,184,0.15); color: var(--muted); }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
th { background: rgba(255,255,255,0.03); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-size: 11px; font-weight: 600; }
tr:last-child td { border-bottom: none; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.err { color: var(--bad); font-family: monospace; font-size: 12px; }
.muted { color: var(--muted); }
</style>
</head>
<body>

<h1>DW Pipeline — Phase 0</h1>
<p class="sub">Auto-refresh every 30s · Last loaded <?= h(date('Y-m-d H:i:s')) ?></p>

<?php if (!$latest): ?>
  <div class="card"><strong>No runs yet.</strong> Trigger one with <code>scripts/run_daily_ingest.bat</code> or <code>python -m ingestion.run_pipeline</code>.</div>
<?php else: ?>

<div class="grid">
  <div class="card">
    <div class="label">Latest run</div>
    <div class="value">#<?= h((string)$latest['run_id']) ?></div>
    <div class="muted" style="font-size:12px;margin-top:4px"><?= h($latest['started_at']) ?></div>
  </div>
  <div class="card">
    <div class="label">Status</div>
    <div class="value"><span class="pill <?= $status_class($latest['status']) ?>"><?= h($latest['status']) ?></span></div>
  </div>
  <div class="card">
    <div class="label">Duration</div>
    <div class="value"><?= h(fmt_duration($latest['duration_s'])) ?></div>
  </div>
  <div class="card">
    <div class="label">Tables loaded</div>
    <div class="value"><?= h(fmt_num($latest['tables_loaded'])) ?></div>
  </div>
  <div class="card">
    <div class="label">Rows loaded</div>
    <div class="value"><?= h(fmt_num($latest['rows_loaded'])) ?></div>
  </div>
  <div class="card">
    <div class="label">DQ tests</div>
    <div class="value">
      <span class="pill ok"><?= $test_summary['pass'] ?> pass</span>
      <?php if ($test_summary['fail'] > 0): ?>
        <span class="pill bad"><?= $test_summary['fail'] ?> fail</span>
      <?php endif; ?>
    </div>
  </div>
  <div class="card">
    <div class="label">Silver rows (approx)</div>
    <div class="value"><?= h(fmt_num($silver_total_rows)) ?></div>
  </div>
  <div class="card">
    <div class="label">Silver anomalies</div>
    <div class="value">
      <span class="pill <?= $silver_total_anom > 0 ? 'bad' : 'ok' ?>">
        <?= h(fmt_num($silver_total_anom)) ?>
      </span>
    </div>
  </div>
  <div class="card">
    <div class="label">Gold marts</div>
    <div class="value"><?= h(fmt_num($gold_count)) ?></div>
    <div class="muted" style="font-size:12px;margin-top:4px"><?= h(fmt_num($gold_total_rows)) ?> rows</div>
  </div>
</div>

<?php if ($kpis): ?>
<h2>Business KPIs (from Gold)</h2>
<div class="grid">
  <div class="card">
    <div class="label">Lifetime net sales</div>
    <div class="value">$<?= h(fmt_num($kpis['lifetime_net_sales'])) ?></div>
  </div>
  <div class="card">
    <div class="label">Champion customers</div>
    <div class="value"><?= h(fmt_num($kpis['champions'])) ?></div>
  </div>
  <div class="card">
    <div class="label">At-risk high-value</div>
    <div class="value"><span class="pill warn"><?= h(fmt_num($kpis['at_risk'])) ?></span></div>
  </div>
  <div class="card">
    <div class="label">Top item net sales</div>
    <div class="value">$<?= h(fmt_num($kpis['top_item_sales'])) ?></div>
  </div>
</div>
<?php endif; ?>

<?php if ($latest['error_message']): ?>
  <h2>Latest run error</h2>
  <div class="card err"><?= h($latest['error_message']) ?></div>
<?php endif; ?>

<h2>Per-table stats (run #<?= h((string)$latest['run_id']) ?>)</h2>
<table>
  <thead><tr><th>Table</th><th class="num">Rows</th><th class="num">Bytes</th><th class="num">Duration</th><th>Status</th></tr></thead>
  <tbody>
  <?php foreach ($table_stats as $t): ?>
    <tr>
      <td><code>bronze.<?= h($t['table_name']) ?></code></td>
      <td class="num"><?= h(fmt_num($t['rows_loaded'])) ?></td>
      <td class="num"><?= h(fmt_bytes($t['bytes_loaded'])) ?></td>
      <td class="num"><?= h(fmt_duration($t['duration_s'])) ?></td>
      <td><span class="pill <?= $status_class($t['status']) ?>"><?= h($t['status']) ?></span></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>

<h2>Silver tables</h2>
<?php if (!$silver_rows): ?>
  <div class="card muted">Silver layer not built yet. Run <code>python -m ingestion.run_pipeline</code>.</div>
<?php else: ?>
<table>
  <thead><tr><th>Table</th><th class="num">Rows (approx)</th><th class="num">Anomalies</th><th class="num">Size</th></tr></thead>
  <tbody>
  <?php foreach ($silver_rows as $s): ?>
    <tr>
      <td><code>silver.<?= h($s['table']) ?></code></td>
      <td class="num"><?= h(fmt_num($s['rows'])) ?></td>
      <td class="num">
        <?php if ($s['anom_rows'] > 0): ?>
          <span class="pill bad"><?= h(fmt_num($s['anom_rows'])) ?></span>
        <?php else: ?>
          <span class="muted">0</span>
        <?php endif; ?>
      </td>
      <td class="num"><?= h(fmt_bytes($s['bytes'])) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>

<h2>Pipeline performance</h2>
<?php if (!$run_history): ?>
  <div class="card muted">No run history yet.</div>
<?php else: ?>
<div class="grid">
  <?php foreach ($db_tuning as $t): ?>
    <div class="card">
      <div class="label">pg.<?= h($t['name']) ?></div>
      <div class="value" style="font-size:18px"><?= h($t['setting']) ?><?= $t['unit'] ? ' ' . h($t['unit']) : '' ?></div>
    </div>
  <?php endforeach; ?>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
  <div>
    <h3 style="color:var(--muted);font-size:13px;margin:0 0 6px">Run history (wall clock)</h3>
    <table>
      <thead><tr><th>Run</th><th class="num">Bronze</th><th class="num">dbt nodes</th><th class="num">Total wall</th></tr></thead>
      <tbody>
      <?php foreach ($run_history as $rh): ?>
        <tr>
          <td>#<?= h((string)$rh['run_id']) ?></td>
          <td class="num"><?= h(fmt_duration($rh['bronze_s'])) ?></td>
          <td class="num"><?= h(fmt_duration($rh['dbt_node_s'])) ?></td>
          <td class="num"><strong><?= h(fmt_duration($rh['wall_s'])) ?></strong></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <div>
    <h3 style="color:var(--muted);font-size:13px;margin:0 0 6px">Top 10 slowest nodes (run #<?= h((string)$latest['run_id']) ?>)</h3>
    <table>
      <thead><tr><th>Node</th><th>Type</th><th class="num">Time</th></tr></thead>
      <tbody>
      <?php foreach ($slowest as $s): ?>
        <tr>
          <td><code><?= h(str_replace('model.tpcds_dw.', '', $s['node_id'])) ?></code></td>
          <td class="muted"><?= h($s['node_type']) ?></td>
          <td class="num"><?= h(fmt_duration($s['execution_time_s'])) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
<?php endif; ?>

<h2>Gold marts</h2>
<?php if (!$gold_rows): ?>
  <div class="card muted">Gold layer not built yet.</div>
<?php else: ?>
<table>
  <thead><tr><th>Mart</th><th class="num">Rows (approx)</th><th class="num">Size</th></tr></thead>
  <tbody>
  <?php foreach ($gold_rows as $g): ?>
    <tr>
      <td><code>gold.<?= h($g['relname']) ?></code></td>
      <td class="num"><?= h(fmt_num($g['approx_rows'])) ?></td>
      <td class="num"><?= h(fmt_bytes($g['bytes'])) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>

<h2>Recent runs</h2>
<table>
  <thead><tr><th>Run</th><th>Started</th><th>Status</th><th class="num">Tables</th><th class="num">Rows</th><th class="num">Duration</th></tr></thead>
  <tbody>
  <?php foreach ($recent as $r): ?>
    <tr>
      <td>#<?= h((string)$r['run_id']) ?></td>
      <td><?= h($r['started_at']) ?></td>
      <td><span class="pill <?= $status_class($r['status']) ?>"><?= h($r['status']) ?></span></td>
      <td class="num"><?= h(fmt_num($r['tables_loaded'])) ?></td>
      <td class="num"><?= h(fmt_num($r['rows_loaded'])) ?></td>
      <td class="num"><?= h(fmt_duration($r['duration_s'])) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>

<h2>Data quality tests (run #<?= h((string)$latest['run_id']) ?>)</h2>
<?php if (!$test_results): ?>
  <div class="card muted">No test results recorded for this run.</div>
<?php else: ?>
<table>
  <thead><tr><th>Test</th><th>Status</th><th class="num">Failures</th><th>Message</th></tr></thead>
  <tbody>
  <?php foreach ($test_results as $t): ?>
    <tr>
      <td><code><?= h($t['test_name']) ?></code></td>
      <td><span class="pill <?= $status_class($t['status']) ?>"><?= h($t['status']) ?></span></td>
      <td class="num"><?= h(fmt_num($t['failures'])) ?></td>
      <td class="err"><?= h($t['message']) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>

<?php endif; ?>

</body>
</html>
