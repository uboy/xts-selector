"""
Standalone HTML formatter for xts_compare reports.

Produces a single self-contained HTML document with embedded CSS and JS.
"""

from __future__ import annotations

import html
import json
from io import StringIO

from .format_json import report_to_dict, single_run_to_dict
from .models import ComparisonReport, RunMetadata, TestIdentity, TestResult


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_summary_cards(data: dict) -> str:
    summary = data["summary"]
    cards = [
        ("Total", f"{summary['total_base']} -> {summary['total_target']}"),
        ("Regressions", summary["regression"]),
        ("Improvements", summary["improvement"]),
        ("Health", f"{_average_health(data):.1f}%"),
    ]
    parts = []
    for label, value in cards:
        parts.append(
            '<article class="card">'
            f'<div class="card-label">{_esc(label)}</div>'
            f'<div class="card-value">{_esc(value)}</div>'
            "</article>"
        )
    return '<section class="cards">' + "".join(parts) + "</section>"


def _render_single_run_cards(data: dict) -> str:
    summary = data["summary"]
    cards = [
        ("Total", summary["total_tests"]),
        ("Pass", summary["pass_count"]),
        ("Fail", summary["fail_count"]),
        ("Blocked", summary["blocked_count"]),
    ]
    parts = []
    for label, value in cards:
        parts.append(
            '<article class="card">'
            f'<div class="card-label">{_esc(label)}</div>'
            f'<div class="card-value">{_esc(value)}</div>'
            "</article>"
        )
    return '<section class="cards">' + "".join(parts) + "</section>"


def _average_health(data: dict) -> float:
    modules = data.get("modules", [])
    if not modules:
        return 100.0
    total = sum(float(module.get("health_score", 0.0)) for module in modules)
    return total / len(modules)


def _render_input_order(data: dict) -> str:
    info = data.get("input_order", {})
    if not info or not info.get("mode"):
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write('<h2>Input Order</h2>')
    buf.write('<div class="meta-list">')
    buf.write(f'<div><strong>Mode:</strong> {_esc(info.get("mode") or "-")}</div>')
    buf.write(
        f'<div><strong>Order:</strong> {_esc(info.get("source") or "-")} '
        f'({_esc("auto" if info.get("auto_detected") else "explicit")})</div>'
    )
    if info.get("origin"):
        buf.write(f'<div><strong>Origin:</strong> {_esc(info["origin"])}</div>')
    if info.get("ordered_paths"):
        names = " -> ".join(_esc(path.rsplit("/", 1)[-1]) for path in info["ordered_paths"])
        buf.write(f'<div><strong>Paths:</strong> {names}</div>')
    buf.write("</div></section>")
    return buf.getvalue()


def _render_run_provenance(meta: dict, title: str) -> str:
    timestamp_source = meta.get("timestamp_source")
    archive = meta.get("archive_diagnostics", {})
    skipped = archive.get("skipped_entries", [])
    if not timestamp_source and not skipped:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write(f"<h2>{_esc(title)}</h2>")
    buf.write('<div class="meta-list">')
    if timestamp_source:
        buf.write(f'<div><strong>Timestamp source:</strong> {_esc(timestamp_source)}</div>')
    if skipped:
        items = ", ".join(f"{item['reason']}:{item['path']}" for item in skipped[:5])
        if len(skipped) > 5:
            items += ", ..."
        buf.write(f'<div><strong>Archive notices:</strong> {_esc(items)}</div>')
    buf.write("</div></section>")
    return buf.getvalue()


def _render_root_causes(data: dict) -> str:
    rows = data.get("root_causes", [])
    if not rows:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write('<div class="panel-head"><h2>Root Cause Analysis</h2><input class="table-filter" data-target="root-cause-table" placeholder="Filter root causes"></div>')
    buf.write('<table id="root-cause-table"><thead><tr>')
    for heading in ("Failure Type", "Message", "Count", "Modules"):
        buf.write(f'<th>{_esc(heading)}</th>')
    buf.write('</tr></thead><tbody>')
    for row in rows:
        buf.write("<tr>")
        buf.write(f"<td>{_esc(row['failure_type'])}</td>")
        buf.write(f"<td>{_esc(row['canonical_message'])}</td>")
        buf.write(f"<td>{_esc(row['count'])}</td>")
        buf.write(f"<td>{_esc(', '.join(row['modules_affected']))}</td>")
        buf.write("</tr>")
    buf.write("</tbody></table></section>")
    return buf.getvalue()


def _render_regressions(data: dict) -> str:
    regressions = data.get("regressions", [])
    if not regressions:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write('<div class="panel-head"><h2>Regressions</h2><input class="table-filter" data-target="regressions-table" placeholder="Filter regressions"></div>')
    buf.write('<table id="regressions-table"><thead><tr>')
    for heading in ("Module", "Suite", "Case", "Transition", "Failure Type", "Message"):
        buf.write(f'<th>{_esc(heading)}</th>')
    buf.write('</tr></thead><tbody>')
    for row in regressions:
        identity = row["identity"]
        transition = f"{row['base_outcome'] or '(absent)'} -> {row['target_outcome'] or '(absent)'}"
        buf.write("<tr>")
        buf.write(f"<td>{_esc(identity['module'])}</td>")
        buf.write(f"<td>{_esc(identity['suite'])}</td>")
        buf.write(f"<td>{_esc(identity['case'])}</td>")
        buf.write(f"<td>{_esc(transition)}</td>")
        buf.write(f"<td>{_esc(row['target_failure_type'])}</td>")
        buf.write(f"<td>{_esc(row['target_message'])}</td>")
        buf.write("</tr>")
    buf.write("</tbody></table></section>")
    return buf.getvalue()


def _render_module_health(data: dict) -> str:
    modules = data.get("modules", [])
    if not modules:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write("<h2>Module Health</h2>")
    buf.write('<div class="health-list">')
    for module in modules:
        score = float(module.get("health_score", 0.0))
        buf.write('<div class="health-item">')
        buf.write(f'<div class="health-meta"><strong>{_esc(module["module"])}</strong><span>{score:.1f}%</span></div>')
        buf.write(f'<div class="health-bar"><span style="width:{max(0.0, min(100.0, score)):.1f}%"></span></div>')
        buf.write("</div>")
    buf.write("</div></section>")
    return buf.getvalue()


def _render_performance(data: dict) -> str:
    rows = data.get("performance_changes", [])
    if not rows:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write('<div class="panel-head"><h2>Performance Changes</h2><input class="table-filter" data-target="performance-table" placeholder="Filter performance"></div>')
    buf.write('<table id="performance-table"><thead><tr>')
    for heading in ("Module", "Suite", "Case", "Base ms", "Target ms", "Delta ms", "Ratio"):
        buf.write(f'<th>{_esc(heading)}</th>')
    buf.write('</tr></thead><tbody>')
    for row in rows:
        identity = row["identity"]
        buf.write("<tr>")
        buf.write(f"<td>{_esc(identity['module'])}</td>")
        buf.write(f"<td>{_esc(identity['suite'])}</td>")
        buf.write(f"<td>{_esc(identity['case'])}</td>")
        buf.write(f"<td>{_esc(row['base_time_ms'])}</td>")
        buf.write(f"<td>{_esc(row['target_time_ms'])}</td>")
        buf.write(f"<td>{_esc(row['delta_ms'])}</td>")
        buf.write(f"<td>{_esc(row['ratio'])}</td>")
        buf.write("</tr>")
    buf.write("</tbody></table></section>")
    return buf.getvalue()


def _render_selector_correlation(data: dict) -> str:
    rows = data.get("selector_correlations", [])
    if not rows:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write("<h2>Selector Correlation</h2>")
    for entry in rows:
        buf.write('<article class="selector-entry">')
        buf.write(f'<h3>{_esc(entry["changed_file"])}</h3>')
        for project in entry.get("predicted_projects", []):
            buf.write('<div class="selector-project">')
            buf.write(
                f'<div><strong>{_esc(project["project"])}</strong> '
                f'<span class="muted">score={_esc(project["score"])}, '
                f'bucket={_esc(project["bucket"])}, confidence={_esc(project["confidence"])}</span></div>'
            )
            matched_modules = ", ".join(project.get("matched_modules", [])) or "no compared module match"
            buf.write(f'<div class="muted">Modules: {_esc(matched_modules)}</div>')
            if project.get("regressions"):
                names = ", ".join(item["case"] for item in project["regressions"])
                buf.write(f'<div>Regressions: {_esc(names)}</div>')
            if project.get("improvements"):
                names = ", ".join(item["case"] for item in project["improvements"])
                buf.write(f'<div>Improvements: {_esc(names)}</div>')
            if project.get("predicted_but_no_change"):
                buf.write("<div>No changes in matched modules</div>")
            buf.write("</div>")
        if entry.get("regression_not_predicted"):
            names = ", ".join(item["key"] for item in entry["regression_not_predicted"])
            buf.write(f'<div class="selector-missed">Not predicted regressions: {_esc(names)}</div>')
        buf.write("</article>")
    buf.write("</section>")
    return buf.getvalue()


def _render_single_run_results(data: dict) -> str:
    rows = data.get("results", [])
    if not rows:
        return ""
    buf = StringIO()
    buf.write('<section class="panel">')
    buf.write('<div class="panel-head"><h2>Results</h2><input class="table-filter" data-target="single-run-results" placeholder="Filter results"></div>')
    buf.write('<table id="single-run-results"><thead><tr>')
    for heading in ("Module", "Suite", "Case", "Outcome", "Failure Type", "Time ms", "Message"):
        buf.write(f'<th>{_esc(heading)}</th>')
    buf.write('</tr></thead><tbody>')
    for row in rows:
        identity = row["identity"]
        buf.write("<tr>")
        buf.write(f"<td>{_esc(identity['module'])}</td>")
        buf.write(f"<td>{_esc(identity['suite'])}</td>")
        buf.write(f"<td>{_esc(identity['case'])}</td>")
        buf.write(f"<td>{_esc(row['outcome'])}</td>")
        buf.write(f"<td>{_esc(row['failure_type'])}</td>")
        buf.write(f"<td>{_esc(row['time_ms'])}</td>")
        buf.write(f"<td>{_esc(row['message'])}</td>")
        buf.write("</tr>")
    buf.write("</tbody></table></section>")
    return buf.getvalue()


def _render_full_transitions(data: dict) -> str:
    modules = data.get("modules", [])
    if not modules:
        return ""
    buf = StringIO()
    buf.write('<section class="panel"><h2>Full Transition List</h2>')
    for module in modules:
        buf.write(f'<details><summary>{_esc(module["module"])}</summary>')
        for suite, transitions in module.get("suites", {}).items():
            buf.write(f'<h4>{_esc(suite)}</h4><ul>')
            for transition in transitions:
                identity = transition["identity"]
                transition_text = f'{transition["base_outcome"] or "(absent)"} -> {transition["target_outcome"] or "(absent)"}'
                buf.write(
                    "<li>"
                    f"{_esc(identity['case'])} | {_esc(transition['kind'])} | {_esc(transition_text)}"
                    "</li>"
                )
            buf.write("</ul>")
        buf.write("</details>")
    buf.write("</section>")
    return buf.getvalue()


def format_html(report: ComparisonReport) -> str:
    """Render a standalone HTML report for one ComparisonReport."""
    data = report_to_dict(report)
    base = data["base"]
    target = data["target"]
    title = f"XTS Compare: {base['label'] or base['source_path'] or 'base'} vs {target['label'] or target['source_path'] or 'target'}"
    # Keep the embedded payload valid for both JavaScript string parsing and raw
    # HTML script contents.
    data_blob = json.dumps(json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))

    sections = [
        _render_summary_cards(data),
        _render_input_order(data),
        _render_run_provenance(base, "Base Provenance"),
        _render_run_provenance(target, "Target Provenance"),
        _render_root_causes(data),
        _render_regressions(data),
        _render_module_health(data),
        _render_performance(data),
        _render_selector_correlation(data),
        _render_full_transitions(data),
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffaf2;
      --ink: #1f1b16;
      --muted: #6f665c;
      --accent: #a3472f;
      --line: #d8c8b4;
      --good: #2c7a52;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, #fff7ec, var(--bg));
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      background: linear-gradient(135deg, #1f1b16, #4f2a1d);
      color: #fff7ec;
      padding: 24px;
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(31, 27, 22, 0.15);
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: 2rem; }}
    .hero p {{ margin: 0; color: #ead9c7; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 16px;
      margin: 20px 0;
    }}
    .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(111, 102, 92, 0.08);
    }}
    .card-label {{
      color: var(--muted);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .card-value {{
      margin-top: 8px;
      font-size: 1.6rem;
      font-weight: bold;
    }}
    .panel {{
      margin-top: 18px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    h2, h3, h4 {{ margin: 0 0 12px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .table-filter {{
      min-width: 220px;
      padding: 10px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: white;
    }}
    .health-list {{
      display: grid;
      gap: 14px;
    }}
    .health-meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }}
    .health-bar {{
      height: 12px;
      background: #eadfce;
      border-radius: 999px;
      overflow: hidden;
    }}
    .health-bar span {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--good));
    }}
    .muted {{ color: var(--muted); }}
    .selector-entry + .selector-entry {{
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .selector-project {{
      margin: 10px 0 0 14px;
      padding-left: 14px;
      border-left: 3px solid var(--line);
    }}
    .meta-list {{
      display: grid;
      gap: 10px;
    }}
    .selector-missed {{
      margin-top: 12px;
      color: var(--accent);
    }}
    details {{
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: white;
    }}
    summary {{
      cursor: pointer;
      font-weight: bold;
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 16px; }}
      .hero h1 {{ font-size: 1.5rem; }}
      table {{ font-size: 0.88rem; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <h1>{_esc(title)}</h1>
      <p>Base: {_esc(base.get("timestamp") or base.get("source_path") or "-")} | Target: {_esc(target.get("timestamp") or target.get("source_path") or "-")}</p>
    </header>
    {''.join(section for section in sections if section)}
  </main>
  <script>
    document.querySelectorAll('.table-filter').forEach(function(input) {{
      input.addEventListener('input', function() {{
        const target = document.getElementById(input.dataset.target);
        if (!target) return;
        const needle = input.value.trim().toLowerCase();
        target.querySelectorAll('tbody tr').forEach(function(row) {{
          row.style.display = row.textContent.toLowerCase().includes(needle) ? '' : 'none';
        }});
      }});
    }});
    window.__xtsCompareReport = JSON.parse({data_blob});
  </script>
</body>
</html>
"""


def format_single_run_html(meta: RunMetadata, results: dict[TestIdentity, TestResult]) -> str:
    """Render a standalone HTML summary for one run."""
    data = single_run_to_dict(meta, results)
    run = data["run"]
    title = f"XTS Run Summary: {run['label'] or run['source_path'] or 'run'}"
    sections = [
        _render_single_run_cards(data),
        _render_run_provenance(run, "Run Provenance"),
        _render_single_run_results(data),
    ]
    data_blob = json.dumps(json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffaf2;
      --ink: #1f1b16;
      --muted: #6f665c;
      --accent: #a3472f;
      --line: #d8c8b4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, #fff7ec, var(--bg));
    }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      background: linear-gradient(135deg, #1f1b16, #4f2a1d);
      color: #fff7ec;
      padding: 24px;
      border-radius: 18px;
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: 2rem; }}
    .hero p {{ margin: 0; color: #ead9c7; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 16px;
      margin: 20px 0;
    }}
    .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(111, 102, 92, 0.08);
    }}
    .card-label {{
      color: var(--muted);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .card-value {{
      margin-top: 8px;
      font-size: 1.6rem;
      font-weight: bold;
    }}
    .panel {{ margin-top: 18px; }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .meta-list {{
      display: grid;
      gap: 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .table-filter {{
      min-width: 220px;
      padding: 10px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: white;
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 16px; }}
      .hero h1 {{ font-size: 1.5rem; }}
      table {{ font-size: 0.88rem; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <h1>{_esc(title)}</h1>
      <p>Timestamp: {_esc(run.get("timestamp") or run.get("source_path") or "-")}</p>
    </header>
    {''.join(section for section in sections if section)}
  </main>
  <script>
    document.querySelectorAll('.table-filter').forEach(function(input) {{
      input.addEventListener('input', function() {{
        const target = document.getElementById(input.dataset.target);
        if (!target) return;
        const needle = input.value.trim().toLowerCase();
        target.querySelectorAll('tbody tr').forEach(function(row) {{
          row.style.display = row.textContent.toLowerCase().includes(needle) ? '' : 'none';
        }});
      }});
    }});
    window.__xtsCompareSingleRun = JSON.parse({data_blob});
  </script>
</body>
</html>
"""
