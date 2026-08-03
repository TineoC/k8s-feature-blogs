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


STATUS_DOT = {
    "Merged": "#22C55E",
    "Ready for review": "#22C55E",
    "Review in progress": "#F59E0B",
    "Draft": "#A78BFA",
    "No content": "#EF4444",
    "Placeholder": "#94A3B8",
}


def status_dot_color(status):
    return STATUS_DOT.get(status.replace(" (closed)", ""), "#94A3B8")


def render_html(data):
    rows_sorted = sorted(data["rows"], key=lambda r: (status_sort_key(r["status"]), r["pr_number"]))

    statuses_present = sorted(data["summary"].keys(), key=status_sort_key)

    filter_buttons = '<button class="chip is-active" data-filter="all" type="button">All ({})</button>'.format(
        len(rows_sorted)
    ) + "".join(
        f'<button class="chip" data-filter="{slugify(status)}" type="button">'
        f'<span class="dot" style="background:{status_dot_color(status)}"></span>{status} ({data["summary"][status]})</button>'
        for status in statuses_present
    )

    summary_cells = "".join(
        f'<div class="stat"><div class="stat-num">{count}</div><div class="stat-label">'
        f'<span class="dot" style="background:{status_dot_color(status)}"></span>{status}</div></div>'
        for status, count in sorted(data["summary"].items(), key=lambda kv: status_sort_key(kv[0]))
    )

    table_rows = "".join(
        f'''<tr class="status-{slugify(r["status"])}" data-status="{slugify(r["status"])}" data-search="{(r['pr_title'] + ' ' + ' '.join(r['keps'])).lower().replace('"', '&quot;')}">
      <td class="mono"><a href="{r['pr_url']}" target="_blank" rel="noopener">#{r['pr_number']}</a></td>
      <td>{"; ".join(r['keps'])}</td>
      <td><span class="status-badge"><span class="dot" style="background:{status_dot_color(r['status'])}"></span>{r['status']}</span></td>
      <td class="mono num">{r['additions']}</td>
      <td class="mono num">{r['review_count']} / {r['comment_count']}</td>
    </tr>'''
        for r in rows_sorted
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kubernetes v1.37 Feature Blog Status</title>
<meta name="description" content="Live status of Kubernetes v1.37 Feature Blog PRs, sourced from the Release Tracking project board.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme: dark;
    --color-primary: #1E293B;
    --color-on-primary: #FFFFFF;
    --color-secondary: #334155;
    --color-accent: #22C55E;
    --color-background: #0F172A;
    --color-foreground: #F8FAFC;
    --color-muted: #272F42;
    --color-border: #475569;
    --color-destructive: #EF4444;
    --color-ring: #22C55E;
    --space-1: 8px; --space-2: 12px; --space-3: 16px; --space-4: 24px; --space-5: 32px;
    --font-sans: "Fira Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --font-mono: "Fira Code", ui-monospace, SFMono-Regular, monospace;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      color-scheme: light;
      --color-background: #F8FAFC;
      --color-foreground: #0F172A;
      --color-muted: #E7ECF3;
      --color-border: #CBD5E1;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: var(--font-sans);
    background: var(--color-background);
    color: var(--color-foreground);
    max-width: 1100px;
    margin: 0 auto;
    padding: var(--space-4) var(--space-3) var(--space-5);
    line-height: 1.5;
  }}
  h1 {{ font-size: clamp(1.3rem, 2.5vw, 1.75rem); font-weight: 700; letter-spacing: -0.02em; margin: 0 0 var(--space-1); }}
  .meta {{ color: var(--color-border); font-size: 0.8rem; margin-bottom: var(--space-4); }}
  .meta a {{ color: var(--color-accent); }}
  .mono {{ font-family: var(--font-mono); }}
  .num {{ text-align: right; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }}

  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--space-2); margin-bottom: var(--space-4); }}
  .stat {{ background: var(--color-muted); border: 1px solid var(--color-border); border-radius: 10px; padding: var(--space-2) var(--space-3); }}
  .stat-num {{ font-family: var(--font-mono); font-size: 1.5rem; font-weight: 600; }}
  .stat-label {{ font-size: 0.75rem; color: var(--color-foreground); opacity: 0.75; display: flex; align-items: center; margin-top: 4px; }}

  .controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .chip {{
    display: inline-flex; align-items: center; font: inherit; font-size: 0.8rem;
    background: var(--color-muted); color: var(--color-foreground); border: 1px solid var(--color-border);
    border-radius: 999px; padding: 6px 12px; cursor: pointer; transition: background 150ms ease, border-color 150ms ease;
    min-height: 32px;
  }}
  .chip:hover {{ border-color: var(--color-accent); }}
  .chip:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}
  .chip.is-active {{ background: var(--color-accent); color: #05220f; border-color: var(--color-accent); font-weight: 600; }}

  .search {{
    margin-left: auto; font: inherit; font-size: 0.85rem; min-width: 220px;
    background: var(--color-muted); color: var(--color-foreground); border: 1px solid var(--color-border);
    border-radius: 8px; padding: 8px 12px; min-height: 40px;
  }}
  .search:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}
  .search::placeholder {{ color: var(--color-foreground); opacity: 0.5; }}

  .table-wrap {{ overflow-x: auto; border: 1px solid var(--color-border); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; min-width: 640px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--color-border); vertical-align: top; }}
  th {{ background: var(--color-muted); position: sticky; top: 0; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-foreground); opacity: 0.8; }}
  tbody tr:hover {{ background: var(--color-muted); }}
  tbody tr[hidden] {{ display: none; }}
  .status-badge {{ display: inline-flex; align-items: center; font-weight: 600; white-space: nowrap; }}
  a {{ color: var(--color-accent); text-decoration: none; }}
  a:hover, a:focus-visible {{ text-decoration: underline; }}
  a:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}

  .empty-state {{ display: none; padding: var(--space-4); text-align: center; color: var(--color-foreground); opacity: 0.6; font-size: 0.85rem; }}

  @media (prefers-reduced-motion: reduce) {{
    * {{ transition: none !important; }}
  }}
  @media (max-width: 640px) {{
    .search {{ margin-left: 0; width: 100%; }}
  }}
</style>
</head>
<body>
<h1>Kubernetes v1.37 Feature Blog Status</h1>
<div class="meta">Last run: <strong>{data['generated_at']}</strong> &middot; source: <a href="{data['project_url']}" target="_blank" rel="noopener">Release Tracking board, view 5</a> &middot; rebuilds every 6h via GitHub Actions</div>

<div class="stats">{summary_cells}</div>

<div class="controls">
  <div class="chips" role="group" aria-label="Filter by status">{filter_buttons}</div>
  <input class="search" type="search" placeholder="Filter by KEP or PR title..." aria-label="Filter by KEP or PR title" id="search-input">
</div>

<div class="table-wrap">
<table id="pr-table">
  <thead><tr><th>PR</th><th>KEP(s)</th><th>Status</th><th class="num">Lines added</th><th class="num">Reviews / Comments</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>
</div>
<p class="empty-state" id="empty-state">No PRs match this filter.</p>

<script>
(function () {{
  var chips = document.querySelectorAll('.chip');
  var searchInput = document.getElementById('search-input');
  var rows = document.querySelectorAll('#pr-table tbody tr');
  var emptyState = document.getElementById('empty-state');
  var activeFilter = 'all';

  function applyFilters() {{
    var term = searchInput.value.trim().toLowerCase();
    var visibleCount = 0;
    rows.forEach(function (row) {{
      var matchesStatus = activeFilter === 'all' || row.dataset.status === activeFilter;
      var matchesSearch = !term || row.dataset.search.indexOf(term) !== -1;
      var visible = matchesStatus && matchesSearch;
      row.hidden = !visible;
      if (visible) visibleCount++;
    }});
    emptyState.style.display = visibleCount === 0 ? 'block' : 'none';
  }}

  chips.forEach(function (chip) {{
    chip.addEventListener('click', function () {{
      chips.forEach(function (c) {{ c.classList.remove('is-active'); }});
      chip.classList.add('is-active');
      activeFilter = chip.dataset.filter;
      applyFilters();
    }});
  }});

  searchInput.addEventListener('input', applyFilters);
}})();
</script>
</body>
</html>
"""


def slugify(status):
    return re.sub(r"[^a-z0-9]+", "-", status.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
