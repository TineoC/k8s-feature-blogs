#!/usr/bin/env python3
"""Fetch k8s v1.37 Feature Blog PR status from GitHub Project 264 and render docs/index.html + docs/data.json."""
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_NUMBER = "264"
PROJECT_OWNER = "kubernetes"
WEBSITE_REPO = "kubernetes/website"


def gh_json(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def gh_text(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True, check=True)
    return result.stdout


def classify(pr):
    state = pr["state"]
    additions = pr.get("additions", 0)
    is_draft = pr.get("isDraft", False)
    review_count = pr.get("reviewCount", 0)
    title = pr.get("title", "")

    if state == "MERGED":
        base = "Merged"
    elif additions <= 15:
        base = "Placeholder" if "[placeholder]" in title.lower() else "No content"
    elif is_draft or "[wip]" in title.lower():
        base = "Draft"
    elif review_count > 0:
        base = "Review in progress"
    else:
        base = "Ready for review"

    if state == "CLOSED" and base != "Merged":
        base += " (closed)"
    return base


def main():
    items = gh_json([
        "project", "item-list", PROJECT_NUMBER, "--owner", PROJECT_OWNER,
        "--format", "json", "--limit", "200",
    ])["items"]

    pr_to_keps = defaultdict(list)
    for item in items:
        pr_url = item.get("blog PR")
        if pr_url:
            pr_to_keps[pr_url].append(item.get("title", "untitled"))

    rows = []
    for pr_url, keps in sorted(pr_to_keps.items(), key=lambda kv: int(re.search(r"/pull/(\d+)", kv[0]).group(1))):
        number = re.search(r"/pull/(\d+)", pr_url).group(1)
        detail = gh_json([
            "pr", "view", number, "--repo", WEBSITE_REPO,
            "--json", "number,title,state,isDraft,mergedAt,additions,deletions,reviews,comments,url",
        ])
        detail["reviewCount"] = len(detail.get("reviews", []))
        detail["commentCount"] = len(detail.get("comments", []))
        status = classify(detail)
        rows.append({
            "pr_number": int(number),
            "pr_url": pr_url,
            "pr_title": detail["title"],
            "keps": keps,
            "additions": detail.get("additions", 0),
            "review_count": detail["reviewCount"],
            "comment_count": detail["commentCount"],
            "status": status,
        })

    summary = defaultdict(int)
    for row in rows:
        summary[row["status"]] += 1

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    data = {
        "generated_at": generated_at,
        "project_url": f"https://github.com/orgs/{PROJECT_OWNER}/projects/{PROJECT_NUMBER}/views/5",
        "summary": dict(summary),
        "rows": rows,
    }

    with open("docs/data.json", "w") as f:
        json.dump(data, f, indent=2)

    with open("docs/index.html", "w") as f:
        f.write(render_html(data))

    print(f"Built {len(rows)} PR rows, summary: {dict(summary)}")


STATUS_ORDER = [
    "Merged", "Ready for review", "Review in progress", "Draft",
    "No content", "Placeholder",
]


def status_sort_key(status):
    base = status.replace(" (closed)", "")
    try:
        return STATUS_ORDER.index(base)
    except ValueError:
        return len(STATUS_ORDER)


def render_html(data):
    rows_sorted = sorted(data["rows"], key=lambda r: (status_sort_key(r["status"]), r["pr_number"]))

    summary_cells = "".join(
        f'<div class="stat"><div class="stat-num">{count}</div><div class="stat-label">{status}</div></div>'
        for status, count in sorted(data["summary"].items(), key=lambda kv: status_sort_key(kv[0]))
    )

    table_rows = "".join(
        f'''<tr class="status-{slugify(r["status"])}">
      <td><a href="{r['pr_url']}" target="_blank" rel="noopener">#{r['pr_number']}</a></td>
      <td>{"; ".join(r['keps'])}</td>
      <td class="status-badge">{r['status']}</td>
      <td>{r['additions']}</td>
      <td>{r['review_count']} / {r['comment_count']}</td>
    </tr>'''
        for r in rows_sorted
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kubernetes v1.37 Feature Blog Status</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.5rem; }}
  .stat {{ border: 1px solid #ddd; border-radius: 8px; padding: 0.5rem 1rem; text-align: center; min-width: 90px; }}
  .stat-num {{ font-size: 1.3rem; font-weight: 600; }}
  .stat-label {{ font-size: 0.75rem; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid #eee; vertical-align: top; }}
  th {{ background: #fafafa; position: sticky; top: 0; }}
  .status-badge {{ font-weight: 600; white-space: nowrap; }}
  .status-merged .status-badge {{ color: #1a7f37; }}
  .status-ready-for-review .status-badge {{ color: #0969da; }}
  .status-review-in-progress .status-badge {{ color: #9a6700; }}
  .status-draft .status-badge {{ color: #8250df; }}
  .status-no-content .status-badge, .status-no-content-closed .status-badge {{ color: #cf222e; }}
  .status-placeholder .status-badge, .status-placeholder-closed .status-badge {{ color: #57606a; }}
  a {{ color: inherit; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #c9d1d9; }}
    .stat {{ border-color: #30363d; }}
    th {{ background: #161b22; }}
    th, td {{ border-color: #21262d; }}
    .meta, .stat-label {{ color: #8b949e; }}
  }}
</style>
</head>
<body>
<h1>Kubernetes v1.37 Feature Blog Status</h1>
<div class="meta">Generated {data['generated_at']} &middot; source: <a href="{data['project_url']}" target="_blank" rel="noopener">Release Tracking board, view 5</a> &middot; rebuilt automatically every 6h via GitHub Actions</div>
<div class="stats">{summary_cells}</div>
<table>
  <thead><tr><th>PR</th><th>KEP(s)</th><th>Status</th><th>Lines added</th><th>Reviews / Comments</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>
</body>
</html>
"""


def slugify(status):
    return re.sub(r"[^a-z0-9]+", "-", status.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
