#!/usr/bin/env python3
"""
Regenerates tests.html — a live daily test-run history report — from
test-history.json, which fynite-playwright-automation's daily GitHub
Action pushes a new entry to after every run.

test-history.json shape (one entry appended per day):
[
  {
    "date": "2026-08-12T14:00:00Z",
    "runUrl": "https://github.com/vb-fynite/fynite-playwright-automation/actions/runs/123",
    "total": 65,
    "passed": 60,
    "failed": 5,
    "failures": [{"name": "...", "tags": ["@fts-64", "@e2e"]}],
    "knownBugs": [
      {"name": "FTS-66: ...", "tags": ["@known-bug", "@fts-66"], "passed": false},
      {"name": "FTS-79: ...", "tags": ["@known-bug", "@fts-79"], "passed": false}
    ]
  },
  ...
]

No external dependencies — pure stdlib.
"""
import json
import sys
import datetime
import html as htmllib

HISTORY_FILE = "test-history.json"
OUTPUT_FILE = "tests.html"
MAX_HISTORY_SHOWN = 30  # most recent N days shown in the trend table


def esc(s):
    return htmllib.escape(str(s), quote=True)


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def build_html(history):
    if not history:
        latest = None
    else:
        latest = history[-1]

    now = datetime.datetime.utcnow().strftime("%B %d, %Y %H:%M UTC")

    # --- latest run summary ---
    if latest:
        pct = round(latest["passed"] / latest["total"] * 100) if latest["total"] else 0
        latest_date = latest["date"][:10]
        latest_summary = f"""
    <div class="stats">
      <div class="stat"><div class="stat-label">Latest run</div><div class="stat-value">{esc(latest_date)}</div></div>
      <div class="stat"><div class="stat-label">Passed</div><div class="stat-value ok">{latest['passed']} / {latest['total']}</div></div>
      <div class="stat"><div class="stat-label">Pass rate</div><div class="stat-value {'ok' if pct >= 90 else 'alert'}">{pct}%</div></div>
      <div class="stat"><div class="stat-label">Failed</div><div class="stat-value {'alert' if latest['failed'] else 'ok'}">{latest['failed']}</div></div>
    </div>
    <p class="section-note"><a href="{esc(latest.get('runUrl', '#'))}">View this run on GitHub Actions &rarr;</a></p>
"""
    else:
        latest_summary = "<p>No runs recorded yet.</p>"

    # --- trend table (most recent N days) ---
    trend_rows = ""
    for entry in reversed(history[-MAX_HISTORY_SHOWN:]):
        pct = round(entry["passed"] / entry["total"] * 100) if entry["total"] else 0
        status_class = "ok" if entry["failed"] == 0 else "alert"
        trend_rows += f"""
      <tr>
        <td>{esc(entry['date'][:10])}</td>
        <td>{entry['passed']} / {entry['total']}</td>
        <td class="{status_class}">{pct}%</td>
        <td>{entry['failed']}</td>
        <td><a href="{esc(entry.get('runUrl', '#'))}">View run</a></td>
      </tr>"""

    # --- known-bug tracker (from the latest run) ---
    known_bug_rows = ""
    unexpected_pass = []
    if latest:
        for kb in latest.get("knownBugs", []):
            if kb["passed"]:
                unexpected_pass.append(kb["name"])
            status_label = "PASSING &mdash; check if fix landed!" if kb["passed"] else "Failing as expected"
            status_class = "unexpected" if kb["passed"] else "expected"
            known_bug_rows += f"""
      <tr class="{status_class}">
        <td>{esc(kb['name'])}</td>
        <td>{' '.join(esc(t) for t in kb.get('tags', []))}</td>
        <td>{status_label}</td>
      </tr>"""

    alert_banner = ""
    if unexpected_pass:
        names = ", ".join(esc(n) for n in unexpected_pass)
        alert_banner = f"""
    <div class="highlight alert-highlight">
      <strong>Action needed:</strong> {len(unexpected_pass)} known-bug scenario(s) passed in the latest run: {names}.
      This usually means the underlying product bug was fixed &mdash; worth confirming and removing the
      <code>@known-bug</code> tag so it moves into the default daily suite.
    </div>"""

    # --- latest failures detail ---
    failure_rows = ""
    if latest:
        for f in latest.get("failures", []):
            failure_rows += f"""
      <tr>
        <td>{esc(f['name'])}</td>
        <td>{' '.join(esc(t) for t in f.get('tags', []))}</td>
      </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3600">
<title>Fynite QA — Daily Test Run History</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; background: #fff; }}
  h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .date {{ color: #666; font-size: 14px; margin-bottom: 28px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 8px; }}
  .stat {{ background: #f5f5f4; border-radius: 8px; padding: 14px; }}
  .stat-label {{ font-size: 12px; color: #666; margin-bottom: 4px; }}
  .stat-value {{ font-size: 22px; font-weight: 600; }}
  .stat-value.alert {{ color: #c0392b; }}
  .stat-value.ok {{ color: #1e7e34; }}
  h2 {{ font-size: 16px; font-weight: 600; margin: 32px 0 14px; border-bottom: 1px solid #e5e5e3; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }}
  th {{ color: #666; text-transform: uppercase; font-size: 11px; }}
  a {{ color: #1a56db; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .ok {{ color: #1e7e34; font-weight: 600; }}
  .alert {{ color: #c0392b; font-weight: 600; }}
  tr.unexpected {{ background: #fff4e5; }}
  tr.expected {{ color: #666; }}
  .highlight {{ border-radius: 8px; padding: 12px 14px; font-size: 13px; margin: 16px 0; }}
  .alert-highlight {{ background: #fdecea; border: 1px solid #f5c2c0; }}
  .section-note {{ font-size: 13px; color: #666; margin-top: -4px; }}
  code {{ background: #f5f5f4; padding: 1px 5px; border-radius: 4px; font-family: monospace; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e5e3; font-size: 12px; color: #999; }}
</style>
</head>
<body>
  <h1>Fynite QA &mdash; Daily Test Run History</h1>
  <div class="date">Auto-updated after each daily run &middot; Last regenerated {now}</div>

  {latest_summary}
  {alert_banner}

  <h2>Known-bug tracker (latest run)</h2>
  <div class="section-note">Scenarios intentionally excluded from the default suite until their underlying product bug is fixed. A row turning green here is a real signal.</div>
  <table>
    <thead><tr><th>Scenario</th><th>Tags</th><th>Status</th></tr></thead>
    <tbody>{known_bug_rows if known_bug_rows else '<tr><td colspan="3">No known-bug scenarios recorded.</td></tr>'}
    </tbody>
  </table>

  <h2>Latest run &mdash; failures</h2>
  <table>
    <thead><tr><th>Scenario</th><th>Tags</th></tr></thead>
    <tbody>{failure_rows if failure_rows else '<tr><td colspan="2">No failures in the latest run.</td></tr>'}
    </tbody>
  </table>

  <h2>Run history (last {MAX_HISTORY_SHOWN} days)</h2>
  <table>
    <thead><tr><th>Date</th><th>Passed</th><th>Pass rate</th><th>Failed</th><th></th></tr></thead>
    <tbody>{trend_rows if trend_rows else '<tr><td colspan="5">No history yet.</td></tr>'}
    </tbody>
  </table>

  <div class="footer">Fynite QA &middot; Auto-regenerated after each daily test run via GitHub Actions &middot; Source: fynite-playwright-automation</div>
</body>
</html>"""


def main():
    history = load_history()
    html_out = build_html(history)
    with open(OUTPUT_FILE, "w") as f:
        f.write(html_out)
    print(f"Wrote {OUTPUT_FILE} — {len(history)} historical entries.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error generating test report: {e}", file=sys.stderr)
        sys.exit(1)
