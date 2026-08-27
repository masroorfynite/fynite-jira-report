#!/usr/bin/env python3
"""
Regenerates index.html — a live FBR report — from Jira data.
Run on a schedule by .github/workflows/update-report.yml

Required environment variables (set as GitHub Actions secrets):
  JIRA_BASE_URL   e.g. https://fynite.atlassian.net
  JIRA_EMAIL      the Atlassian account email used to generate the API token
  JIRA_API_TOKEN  an API token from https://id.atlassian.com/manage-profile/security/api-tokens
"""
import os
import sys
import base64
import datetime
import requests

BASE_URL = os.environ["JIRA_BASE_URL"].rstrip("/")
EMAIL = os.environ["JIRA_EMAIL"]
TOKEN = os.environ["JIRA_API_TOKEN"]
PROJECT = "FBR"

auth_header = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
HEADERS = {
    "Authorization": f"Basic {auth_header}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def jql_search(jql, fields=None, max_results=200):
    url = f"{BASE_URL}/rest/api/3/search/jql"
    payload = {"jql": jql, "maxResults": max_results}
    if fields:
        payload["fields"] = fields
    issues = []
    next_token = None
    while True:
        if next_token:
            payload["nextPageToken"] = next_token
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        issues.extend(data.get("issues", []))
        next_token = data.get("nextPageToken")
        if not next_token or data.get("isLast", True):
            break
    return issues


def jql_count(jql):
    url = f"{BASE_URL}/rest/api/3/search/approximate-count"
    resp = requests.post(url, headers=HEADERS, json={"jql": jql}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("count", 0)


def days_open(created_str):
    created = datetime.datetime.fromisoformat(created_str[:19])
    return (datetime.datetime.utcnow() - created).days


def parse_jira_ts(ts_str):
    """Parse a Jira timestamp (e.g. 2026-08-26T16:04:09.493-0500) into an
    aware UTC datetime, honoring its actual offset."""
    dt = datetime.datetime.strptime(ts_str[:23], "%Y-%m-%dT%H:%M:%S.%f")
    sign = 1 if ts_str[23] == "+" else -1
    offset_h, offset_m = int(ts_str[24:26]), int(ts_str[26:28])
    tz = datetime.timezone(sign * datetime.timedelta(hours=offset_h, minutes=offset_m))
    return dt.replace(tzinfo=tz).astimezone(datetime.timezone.utc)


def count_created_today(project):
    """Count tickets created today in UTC.

    JQL's startOfDay() (and any un-suffixed date literal) resolves against
    the *querying account's* Jira profile timezone, not UTC — so
    `created >= startOfDay()` silently disagrees with this report's UTC
    clock (and with whatever timezone a human happens to be querying from).
    Fetch a safe 2-day window instead and count in Python against a UTC
    midnight boundary, using each ticket's real creation offset.
    """
    issues = jql_search(f"project = {project} AND created >= -2d", fields=["created"])
    today = datetime.datetime.utcnow().date()
    return sum(1 for i in issues if parse_jira_ts(i["fields"]["created"]).date() == today)


def count_done_today(project):
    """Count tickets marked Done today (UTC).

    Same class of bug as count_created_today(), confirmed directly: running
    `status changed to Done after startOfDay()` against the live API
    returns 12 (matching the real count), but jql_count() — which sends the
    identical JQL to the approximate-count endpoint — returned 0. Rather
    than trust startOfDay()'s day-boundary resolution (or approximate-count)
    for a changelog-based condition, use the unambiguous relative window
    `-2d`, fetch full issues (not approximate-count), and count client-side
    against each ticket's actual resolutiondate offset.
    """
    issues = jql_search(
        f"project = {project} AND status changed to Done after -2d",
        fields=["resolutiondate"],
    )
    today = datetime.datetime.utcnow().date()
    return sum(
        1
        for i in issues
        if i["fields"].get("resolutiondate") and parse_jira_ts(i["fields"]["resolutiondate"]).date() == today
    )


def count_resolved_last_days(project, days):
    """Count tickets marked Done in the last `days` days (UTC).

    resolved_7d used the same jql_count()-over-approximate-count pattern as
    the confirmed-broken count_done_today() (same "status changed to Done
    after ..." changelog clause), just not reported as visibly wrong yet.
    Fixed defensively with the same client-side-count approach, with a
    1-day pad on the fetch window to be safe against boundary rounding.
    """
    issues = jql_search(
        f"project = {project} AND status changed to Done after -{days + 1}d",
        fields=["resolutiondate"],
    )
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return sum(
        1
        for i in issues
        if i["fields"].get("resolutiondate") and parse_jira_ts(i["fields"]["resolutiondate"]) >= cutoff
    )


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_ticket_table_rows(issues):
    rows = ""
    for issue in sorted(issues, key=lambda i: i["fields"]["created"]):
        key = issue["key"]
        f = issue["fields"]
        rows += f"""
      <tr>
        <td><a href="{BASE_URL}/browse/{key}">{key}</a></td>
        <td>{esc(f['summary'])}</td>
        <td>{esc((f.get('assignee') or {}).get('displayName', 'Unassigned'))}</td>
        <td>{esc(f.get('priority', {}).get('name', ''))}</td>
        <td>{esc(f['status']['name'])}</td>
        <td>{days_open(f['created'])}</td>
      </tr>"""
    return rows


def build_bar_rows(issues):
    """Percentage bar chart of ticket count by assignee, same style for any issue set."""
    counts = {}
    for issue in issues:
        name = (issue["fields"].get("assignee") or {}).get("displayName", "Unassigned")
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    max_count = ranked[0][1] if ranked else 1

    bar_rows = ""
    colors = ["#c0392b", "#d97706", "#6b7280"]
    for name, count in ranked:
        pct = round(count / len(issues) * 100) if issues else 0
        color = colors[0] if count == max_count else (colors[1] if pct >= 15 else colors[2])
        bar_rows += f"""
    <div class="bar-row">
      <div class="bar-label">{esc(name)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color};">{pct}%</div></div>
      <div class="bar-count">{count}</div>
    </div>"""
    return bar_rows


def build_html(stale, all_open, total_open, in_progress, created_today, done_today, resolved_7d):
    stale_bar_rows = build_bar_rows(stale)
    all_open_bar_rows = build_bar_rows(all_open)
    stale_table_rows = build_ticket_table_rows(stale)
    now = datetime.datetime.utcnow().strftime("%B %d, %Y %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3600">
<title>FBR Daily Report — live</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; background: #fff; }}
  h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .date {{ color: #666; font-size: 14px; margin-bottom: 28px; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; }}
  .stat {{ background: #f5f5f4; border-radius: 8px; padding: 14px; }}
  .stat-label {{ font-size: 12px; color: #666; margin-bottom: 4px; }}
  .stat-value {{ font-size: 22px; font-weight: 600; }}
  .stat-value.alert {{ color: #c0392b; }}
  .stat-value.ok {{ color: #1e7e34; }}
  h2 {{ font-size: 16px; font-weight: 600; margin: 32px 0 14px; border-bottom: 1px solid #e5e5e3; padding-bottom: 6px; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 10px; font-size: 13px; }}
  .bar-label {{ width: 150px; flex-shrink: 0; color: #333; }}
  .bar-track {{ flex: 1; background: #eeeeec; border-radius: 4px; height: 20px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 8px; box-sizing: border-box; color: #fff; font-size: 11px; font-weight: 600; }}
  .bar-count {{ width: 40px; text-align: right; color: #666; font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }}
  th {{ color: #666; text-transform: uppercase; font-size: 11px; }}
  a {{ color: #1a56db; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .section-note {{ font-size: 13px; color: #666; margin-top: -4px; margin-bottom: 8px; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e5e3; font-size: 12px; color: #999; }}
</style>
</head>
<body>
  <h1>Daily Jira report — Fynite Bug Report (FBR)</h1>
  <div class="date">Live, auto-refreshing hourly &middot; Last updated {now} &middot; Excludes project FSV</div>

  <div class="stats">
    <div class="stat"><div class="stat-label">Open 14+ days</div><div class="stat-value alert">{len(stale)}</div></div>
    <div class="stat"><div class="stat-label">Total open backlog</div><div class="stat-value">{total_open}</div></div>
    <div class="stat"><div class="stat-label">In Progress (all)</div><div class="stat-value">{in_progress}</div></div>
    <div class="stat"><div class="stat-label">Created today</div><div class="stat-value">{created_today}</div></div>
    <div class="stat"><div class="stat-label">Marked Done today</div><div class="stat-value ok">{done_today}</div></div>
    <div class="stat"><div class="stat-label">Resolved last 7 days</div><div class="stat-value ok">{resolved_7d}</div></div>
  </div>

  <h2>Stale backlog by assignee ({len(stale)} total, 14+ days open)</h2>
  {stale_bar_rows}

  <h2>All open tickets by assignee ({len(all_open)} total)</h2>
  <div class="section-note">Every currently open FBR ticket, regardless of age — not just the 14+ day stale ones above.</div>
  {all_open_bar_rows}

  <h2>Stale ticket detail (14+ days open)</h2>
  <table>
    <thead><tr><th>Key</th><th>Summary</th><th>Assignee</th><th>Priority</th><th>Status</th><th>Days Open</th></tr></thead>
    <tbody>{stale_table_rows}
    </tbody>
  </table>

  <div class="footer">Fynite QA daily report &middot; Auto-regenerated hourly via GitHub Actions &middot; Data source: Jira project FBR</div>
</body>
</html>"""


def main():
    stale = jql_search(
        f'project = {PROJECT} AND statusCategory != Done AND created <= -14d ORDER BY created ASC',
        fields=["summary", "status", "assignee", "created", "priority"],
    )
    all_open = jql_search(
        f'project = {PROJECT} AND statusCategory != Done ORDER BY created ASC',
        fields=["summary", "status", "assignee", "created", "priority"],
    )
    total_open = jql_count(f'project = {PROJECT} AND statusCategory != Done')
    in_progress = jql_count(f'project = {PROJECT} AND status = "In Progress"')
    created_today = count_created_today(PROJECT)
    done_today = count_done_today(PROJECT)
    resolved_7d = count_resolved_last_days(PROJECT, 7)

    html = build_html(stale, all_open, total_open, in_progress, created_today, done_today, resolved_7d)
    with open("index.html", "w") as f:
        f.write(html)
    print(f"Wrote index.html — {len(stale)} stale tickets, {len(all_open)} total open tickets.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"Jira API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        sys.exit(1)
