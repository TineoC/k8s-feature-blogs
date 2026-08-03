#!/usr/bin/env python3
"""Fetch k8s v1.37 Feature Blog PR status from GitHub Project 264 and render docs/index.html + docs/data.json."""
import html
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_NUMBER = "264"
PROJECT_OWNER = "kubernetes"
WEBSITE_REPO = "kubernetes/website"

# Statuses meaning the KEP is no longer tracked for this milestone -- mirrors
# the -status: exclusion on the project's "Comms - Feature Blogs" view.
UNTRACKED_STATUSES = {"Removed from Milestone", "Deferred"}

# Blog Status values meaning the KEP owner opted out of a feature blog --
# mirrors the -blog-status: exclusion on that same view.
OPTED_OUT_BLOG_STATUSES = {
    "Opted-Out",
    "Opted-Out (done before)",
    "Opted-Out (no answer)",
    "Opted-out (Removed or Deferred)",
}


def run_gh(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh {' '.join(args)} failed:\n{result.stderr}", file=sys.stderr)
        result.check_returncode()
    return result


def gh_json(args):
    return json.loads(run_gh(args).stdout)


def gh_text(args):
    return run_gh(args).stdout


FRONT_MATTER_RE = re.compile(r"^\+---\n((?:\+.*\n)*?)\+---\n", re.MULTILINE)


def parse_front_matter(diff_text):
    """Pull date: / draft: out of the first added front-matter block in a PR diff."""
    match = FRONT_MATTER_RE.search(diff_text)
    if not match:
        return {"date": "", "draft": False}
    block = match.group(1)
    date_match = re.search(r"^\+date:[ \t]*(\S+)[ \t]*$", block, re.MULTILINE)
    draft_match = re.search(r"^\+draft:[ \t]*(true|false)[ \t]*$", block, re.MULTILINE | re.IGNORECASE)
    return {
        "date": date_match.group(1) if date_match else "",
        "draft": bool(draft_match and draft_match.group(1).lower() == "true"),
    }


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
    pr_to_sigs = defaultdict(list)
    pr_to_editors = defaultdict(list)
    pr_to_stages = defaultdict(list)
    for item in items:
        pr_url = item.get("blog PR")
        if not pr_url:
            continue
        if item.get("status") in UNTRACKED_STATUSES:
            continue
        if item.get("blog Status") in OPTED_OUT_BLOG_STATUSES:
            continue
        content = item.get("content") or {}
        pr_to_keps[pr_url].append({
            "number": item.get("issue Number", ""),
            "title": item.get("title", "untitled"),
            "tracking_url": content.get("url", ""),
            "docs_pr": item.get("docs PR", ""),
        })
        for bucket, key in ((pr_to_sigs, "sIG"), (pr_to_editors, "comms Editor"), (pr_to_stages, "stage")):
            value = item.get(key)
            if value and value not in bucket[pr_url]:
                bucket[pr_url].append(value)

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

        front_matter = parse_front_matter(gh_text(["pr", "diff", number, "--repo", WEBSITE_REPO]))
        if detail["state"] == "MERGED":
            published = "Published"
        elif front_matter["draft"] or detail.get("isDraft"):
            published = "Draft"
        else:
            published = "Not yet published"

        rows.append({
            "pr_number": int(number),
            "pr_url": pr_url,
            "pr_title": detail["title"],
            "keps": keps,
            "sig": "; ".join(pr_to_sigs.get(pr_url, [])),
            "comms_editor": "; ".join(pr_to_editors.get(pr_url, [])),
            "stage": "; ".join(pr_to_stages.get(pr_url, [])),
            "publish_date": front_matter["date"],
            "published": published,
            "additions": detail.get("additions", 0),
            "review_count": detail["reviewCount"],
            "comment_count": detail["commentCount"],
            "status": status,
            "is_closed": detail["state"] == "CLOSED",
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


STAGE_ORDER = ["Alpha", "Beta", "Stable", "Deprecation/Removal"]

STAGE_COLOR = {
    "Alpha": "#A78BFA",
    "Beta": "#38BDF8",
    "Stable": "#22C55E",
    "Deprecation/Removal": "#F97316",
}


def stage_color(stage):
    return STAGE_COLOR.get(stage, "#94A3B8")


def stage_sort_key(stage):
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return len(STAGE_ORDER)


def split_multi(value):
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def chip_group_html(dimension, label, values):
    if not values:
        return ""
    buttons = "".join(
        f'<button class="chip" data-dim="{dimension}" data-value="{html.escape(v)}" type="button">{html.escape(v)}</button>'
        for v in values
    )
    return (
        f'<div class="chip-group" role="group" aria-label="Filter by {html.escape(label)}">'
        f'<span class="chip-group-label">{html.escape(label)}</span>{buttons}</div>'
    )


KEP_BASE_URL = "https://k8s.dev/resources/keps/"

ICON_ENHANCEMENT = (
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" '
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M1.5 4a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v2.4a1.35 1.35 0 0 0 0 2.6V11.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V9a1.35 1.35 0 0 0 0-2.6z"/>'
    '<path d="M6 3.2v9.6" stroke-dasharray="1.6 1.6"/>'
    "</svg>"
)

ICON_DOCS = (
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" '
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 1.5h5L12 4.5v9a.5.5 0 0 1-.5.5h-7A.5.5 0 0 1 4 13z"/>'
    '<path d="M9 1.5V4a.5.5 0 0 0 .5.5H12"/>'
    '<path d="M5.8 7.2h4.4M5.8 9.4h4.4M5.8 11.6h2.8"/>'
    "</svg>"
)

ICON_BLOG = (
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" '
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M1.8 6.2 12.5 2v12L1.8 9.8z"/>'
    '<path d="M1.8 6.2v3.6l1.4.6v3.1a.9.9 0 0 0 .9.9h1"/>'
    "</svg>"
)


def render_html(data):
    all_rows = sorted(data["rows"], key=lambda r: (status_sort_key(r["status"]), r["pr_number"]))
    open_rows = [r for r in all_rows if not r.get("is_closed")]
    closed_count = len(all_rows) - len(open_rows)

    # Status chips/summary reflect only open PRs — closed ones don't count for status tracking.
    open_summary = defaultdict(int)
    for r in open_rows:
        open_summary[r["status"]] += 1
    statuses_present = sorted(open_summary.keys(), key=status_sort_key)

    status_chips = "".join(
        f'<button class="chip" data-dim="status" data-value="{slugify(status)}" type="button">'
        f'<span class="dot" style="background:{status_dot_color(status)}"></span>{status} ({open_summary[status]})</button>'
        for status in statuses_present
    )
    status_group = (
        '<div class="chip-group" role="group" aria-label="Filter by status">'
        f'<span class="chip-group-label">Status</span>{status_chips}</div>'
    )

    closed_chip = (
        f'<button class="chip chip-closed" data-filter="__closed__" type="button">'
        f'Show closed ({closed_count})</button>' if closed_count else ""
    )

    sig_values = sorted({v for r in all_rows for v in split_multi(r["sig"])})
    stage_values = sorted({v for r in all_rows for v in split_multi(r["stage"])}, key=stage_sort_key)
    editor_values = sorted({v for r in all_rows for v in split_multi(r["comms_editor"])})

    sig_group = chip_group_html("sig", "SIG", sig_values)
    stage_group = chip_group_html("stage", "Stage", stage_values)
    editor_group = chip_group_html("editor", "Comms Editor", editor_values)

    summary_cells = (
        f'<div class="stat stat-total"><div class="stat-num">{len(open_rows)}</div>'
        '<div class="stat-label">Total blogs</div></div>'
    ) + "".join(
        f'<div class="stat"><div class="stat-num">{count}</div><div class="stat-label">'
        f'<span class="dot" style="background:{status_dot_color(status)}"></span>{status}</div></div>'
        for status, count in sorted(open_summary.items(), key=lambda kv: status_sort_key(kv[0]))
    )

    # Table body is rendered client-side (see <script> below) from ROWS_JSON so the
    # group-by control can re-layout rows without a server round trip.
    rows_json = json.dumps([
        {
            "pr_number": r["pr_number"],
            "pr_url": r["pr_url"],
            "pr_title": r["pr_title"],
            "keps": r["keps"],
            "sig": r["sig"],
            "comms_editor": r["comms_editor"],
            "stage": r["stage"],
            "status": r["status"],
            "status_slug": slugify(r["status"]),
            "dot_color": status_dot_color(r["status"]),
            "publish_date": r["publish_date"],
            "published": r["published"],
            "is_closed": bool(r.get("is_closed")),
        }
        for r in all_rows
    ])

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
  .stat-total {{ border-color: var(--color-accent); }}
  .stat-total .stat-num {{ color: var(--color-accent); }}
  .stat-num {{ font-family: var(--font-mono); font-size: 1.5rem; font-weight: 600; }}
  .stat-label {{ font-size: 0.75rem; color: var(--color-foreground); opacity: 0.75; display: flex; align-items: center; margin-top: 4px; }}

  .controls {{ display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-3); }}
  .controls-top {{ display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }}
  .filter-groups {{ display: flex; flex-direction: column; gap: 6px; }}
  .chip-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }}
  .chip-group-label {{
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.6;
    min-width: 92px; flex-shrink: 0;
  }}
  .chip {{
    display: inline-flex; align-items: center; font: inherit; font-size: 0.78rem;
    background: var(--color-muted); color: var(--color-foreground); border: 1px solid var(--color-border);
    border-radius: 999px; padding: 5px 11px; cursor: pointer; transition: background 150ms ease, border-color 150ms ease;
    min-height: 30px;
  }}
  .chip:hover {{ border-color: var(--color-accent); }}
  .chip:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}
  .chip.is-active {{ background: var(--color-accent); color: #05220f; border-color: var(--color-accent); font-weight: 600; }}
  .chip-closed {{ opacity: 0.75; }}
  .chip-closed.is-active {{ background: var(--color-destructive); border-color: var(--color-destructive); color: #fff; opacity: 1; }}
  .chip-clear {{ background: var(--color-destructive); border-color: var(--color-destructive); color: #fff; display: none; }}
  .chip-clear.is-visible {{ display: inline-flex; }}
  tr.is-closed {{ opacity: 0.7; }}

  .search, .group-select {{
    font: inherit; font-size: 0.85rem;
    background: var(--color-muted); color: var(--color-foreground); border: 1px solid var(--color-border);
    border-radius: 8px; padding: 8px 12px; min-height: 40px;
  }}
  .search {{ margin-left: auto; min-width: 220px; }}
  .group-by {{ display: inline-flex; align-items: center; gap: 8px; }}
  .group-select {{ cursor: pointer; }}
  .search:focus-visible, .group-select:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}
  .search::placeholder {{ color: var(--color-foreground); opacity: 0.5; }}
  .group-label {{ font-size: 0.8rem; opacity: 0.75; white-space: nowrap; }}

  .table-wrap {{ overflow-x: auto; border: 1px solid var(--color-border); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; min-width: 560px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--color-border); vertical-align: top; }}
  th {{ background: var(--color-muted); position: sticky; top: 0; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-foreground); opacity: 0.8; white-space: nowrap; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ color: var(--color-accent); }}
  th .sort-indicator {{ margin-left: 4px; opacity: 0.7; }}
  th[title] {{ cursor: help; }}
  tbody tr:hover {{ background: var(--color-muted); }}
  tbody tr[hidden] {{ display: none; }}
  tr.group-header td {{ background: var(--color-primary); font-weight: 600; font-size: 0.8rem; padding: 8px 12px; border-bottom: 1px solid var(--color-border); }}
  .status-badge {{ display: inline-flex; align-items: center; font-weight: 600; white-space: nowrap; }}
  .kep-link {{ display: block; }}
  .kep-link + .kep-link {{ margin-top: 4px; }}
  .icon-link {{ display: flex; align-items: center; justify-content: center; width: 22px; height: 22px; color: var(--color-accent); }}
  .icon-link + .icon-link {{ margin-top: 4px; }}
  .icon-link.icon-muted {{ color: var(--color-foreground); opacity: 0.3; }}
  .pill {{
    display: inline-flex; align-items: center; font-size: 0.75rem; line-height: 1;
    background: var(--color-muted); border: 1px solid var(--color-border); border-radius: 999px;
    padding: 4px 9px; margin: 2px 4px 2px 0; white-space: nowrap;
  }}
  a {{ color: var(--color-accent); text-decoration: none; }}
  a:hover, a:focus-visible {{ text-decoration: underline; }}
  a:focus-visible {{ outline: 2px solid var(--color-ring); outline-offset: 2px; }}

  .empty-state {{ display: none; padding: var(--space-4); text-align: center; color: var(--color-foreground); opacity: 0.6; font-size: 0.85rem; }}

  @media (prefers-reduced-motion: reduce) {{
    * {{ transition: none !important; }}
  }}
  @media (max-width: 640px) {{
    .controls-top {{ flex-direction: column; align-items: stretch; }}
    .search {{ margin-left: 0; width: 100%; }}
    .group-by {{ width: 100%; justify-content: space-between; }}
    .group-select {{ flex: 1; }}
    .chip-group-label {{ min-width: 0; width: 100%; }}
  }}
</style>
</head>
<body>
<h1>Kubernetes v1.37 Feature Blog Status</h1>
<div class="meta">Last run: <strong>{data['generated_at']}</strong> &middot; source: <a href="{data['project_url']}" target="_blank" rel="noopener">Release Tracking board, view 5</a> &middot; rebuilds every 6h via GitHub Actions</div>

<div class="stats">{summary_cells}</div>

<div class="controls">
  <div class="controls-top">
    <div class="group-by">
      <label class="group-label" for="group-select">Group by</label>
      <select class="group-select" id="group-select">
        <option value="none">None</option>
        <option value="pr_number">Blog PR</option>
        <option value="status">Status</option>
        <option value="sig">SIG</option>
        <option value="stage">Stage</option>
        <option value="comms_editor">Comms Editor</option>
        <option value="published">Published</option>
      </select>
    </div>
    <button class="chip chip-clear" id="clear-filters-chip" type="button">Clear filters</button>
    <input class="search" type="search" placeholder="Filter by KEP or PR title..." aria-label="Filter by KEP or PR title" id="search-input">
  </div>
  <div class="filter-groups">
    {status_group}
    {sig_group}
    {stage_group}
    {editor_group}
    {closed_chip}
  </div>
</div>

<div class="table-wrap">
<table id="pr-table">
  <thead><tr>
    <th title="k/enhancements tracking issue">Enh</th>
    <th title="k/website docs PR">Docs</th>
    <th title="k/website blog PR">Blog</th>
    <th class="sortable" data-sort-key="kep">KEP(s)<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="sig">SIG<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="editor">Comms Editor<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="stage">Stage<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="status">Status<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="publish_date">Publish date<span class="sort-indicator"></span></th>
    <th class="sortable" data-sort-key="published">Published<span class="sort-indicator"></span></th>
  </tr></thead>
  <tbody id="pr-tbody"></tbody>
</table>
</div>
<p class="empty-state" id="empty-state">No PRs match this filter.</p>

<script>
(function () {{
  var ROWS = {rows_json};
  var KEP_BASE_URL = {json.dumps(KEP_BASE_URL)};
  var STATUS_ORDER = {json.dumps(STATUS_ORDER)};
  var ICON_ENHANCEMENT = {json.dumps(ICON_ENHANCEMENT)};
  var ICON_DOCS = {json.dumps(ICON_DOCS)};
  var ICON_BLOG = {json.dumps(ICON_BLOG)};
  var STAGE_COLOR = {json.dumps(STAGE_COLOR)};

  var searchInput = document.getElementById('search-input');
  var groupSelect = document.getElementById('group-select');
  var tbody = document.getElementById('pr-tbody');
  var emptyState = document.getElementById('empty-state');
  var clearChip = document.getElementById('clear-filters-chip');
  var closedChip = document.querySelector('.chip-closed');
  var dimChips = document.querySelectorAll('.chip[data-dim]');
  var sortableHeaders = document.querySelectorAll('th.sortable');

  var activeFilters = {{ status: new Set(), sig: new Set(), stage: new Set(), editor: new Set() }};
  var showClosed = false;
  var sortState = {{ key: null, dir: 0 }};

  function escapeHtml(s) {{
    return String(s).replace(/[&<>"']/g, function (c) {{
      return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[c];
    }});
  }}

  function splitMulti(value) {{
    return (value || '').split(';').map(function (s) {{ return s.trim(); }}).filter(Boolean);
  }}

  function kepLinks(keps) {{
    return keps.map(function (k) {{
      var href = k.number ? KEP_BASE_URL + k.number : '#';
      return '<a class="kep-link" href="' + href + '" target="_blank" rel="noopener">' + escapeHtml(k.title) + '</a>';
    }}).join('');
  }}

  function iconLinks(keps, field, iconSvg, label) {{
    return keps.map(function (k) {{
      var url = k[field];
      var num = url ? url.split('/').pop() : '';
      var title = label + (num ? ' #' + num : ' — none');
      if (!url) {{
        return '<span class="icon-link icon-muted" title="' + escapeHtml(title) + '">' + iconSvg + '</span>';
      }}
      return '<a class="icon-link" href="' + url + '" target="_blank" rel="noopener" title="' + escapeHtml(title) + '" aria-label="' + escapeHtml(title) + '">' + iconSvg + '</a>';
    }}).join('');
  }}

  function pillList(value) {{
    var values = splitMulti(value);
    if (!values.length) return '&mdash;';
    return values.map(function (v) {{
      return '<span class="pill">' + escapeHtml(v) + '</span>';
    }}).join('');
  }}

  function stagePills(value) {{
    var values = splitMulti(value);
    if (!values.length) return '&mdash;';
    return values.map(function (v) {{
      var color = STAGE_COLOR[v] || '#94A3B8';
      return '<span class="pill" style="border-color:' + color + ';color:' + color + '">' + escapeHtml(v) + '</span>';
    }}).join('');
  }}

  function rowHtml(r) {{
    return '<tr class="status-' + r.status_slug + (r.is_closed ? ' is-closed' : '') + '">' +
      '<td>' + iconLinks(r.keps, 'tracking_url', ICON_ENHANCEMENT, 'k/enhancements') + '</td>' +
      '<td>' + iconLinks(r.keps, 'docs_pr', ICON_DOCS, 'k/website docs') + '</td>' +
      '<td><a class="icon-link" href="' + r.pr_url + '" target="_blank" rel="noopener" title="k/website blog #' + r.pr_number + '" aria-label="k/website blog #' + r.pr_number + '">' + ICON_BLOG + '</a></td>' +
      '<td>' + kepLinks(r.keps) + '</td>' +
      '<td>' + pillList(r.sig) + '</td>' +
      '<td>' + pillList(r.comms_editor) + '</td>' +
      '<td>' + stagePills(r.stage) + '</td>' +
      '<td><span class="status-badge"><span class="dot" style="background:' + r.dot_color + '"></span>' + escapeHtml(r.status) + '</span></td>' +
      '<td class="mono">' + (escapeHtml(r.publish_date) || '&mdash;') + '</td>' +
      '<td>' + escapeHtml(r.published) + '</td>' +
    '</tr>';
  }}

  function groupHeaderHtml(label, count) {{
    return '<tr class="group-header"><td colspan="10">' + escapeHtml(label || '(none)') + ' (' + count + ')</td></tr>';
  }}

  function matchesRow(r, term) {{
    if (r.is_closed && !showClosed) return false;
    if (activeFilters.status.size && !activeFilters.status.has(r.status_slug)) return false;
    if (activeFilters.sig.size && !splitMulti(r.sig).some(function (v) {{ return activeFilters.sig.has(v); }})) return false;
    if (activeFilters.stage.size && !splitMulti(r.stage).some(function (v) {{ return activeFilters.stage.has(v); }})) return false;
    if (activeFilters.editor.size && !splitMulti(r.comms_editor).some(function (v) {{ return activeFilters.editor.has(v); }})) return false;
    if (!term) return true;
    var blob = [r.pr_title, r.sig, r.comms_editor].concat(r.keps.map(function (k) {{ return k.title; }})).join(' ').toLowerCase();
    return blob.indexOf(term) !== -1;
  }}

  var SORT_KEYS = {{
    kep: function (r) {{ return ((r.keps[0] && r.keps[0].title) || '').toLowerCase(); }},
    sig: function (r) {{ return (r.sig || '').toLowerCase(); }},
    editor: function (r) {{ return (r.comms_editor || '').toLowerCase(); }},
    stage: function (r) {{ return (r.stage || '').toLowerCase(); }},
    status: function (r) {{
      var idx = STATUS_ORDER.indexOf(r.status.replace(' (closed)', ''));
      return idx === -1 ? STATUS_ORDER.length : idx;
    }},
    publish_date: function (r) {{ return r.publish_date || '￿'; }},
    published: function (r) {{ return (r.published || '').toLowerCase(); }},
  }};

  function applySort(rows) {{
    if (!sortState.key || !sortState.dir) return rows;
    var keyFn = SORT_KEYS[sortState.key];
    return rows.slice().sort(function (a, b) {{
      var av = keyFn(a), bv = keyFn(b);
      if (av < bv) return -1 * sortState.dir;
      if (av > bv) return 1 * sortState.dir;
      return 0;
    }});
  }}

  function updateSortIndicators() {{
    sortableHeaders.forEach(function (th) {{
      var ind = th.querySelector('.sort-indicator');
      if (th.dataset.sortKey === sortState.key && sortState.dir) {{
        ind.textContent = sortState.dir === 1 ? '▲' : '▼';
      }} else {{
        ind.textContent = '';
      }}
    }});
  }}

  function updateClearChip() {{
    var any = Object.keys(activeFilters).some(function (d) {{ return activeFilters[d].size > 0; }});
    clearChip.classList.toggle('is-visible', any);
  }}

  function render() {{
    var term = searchInput.value.trim().toLowerCase();
    var visible = applySort(ROWS.filter(function (r) {{ return matchesRow(r, term); }}));
    var groupBy = groupSelect.value;
    var html;

    if (groupBy === 'none') {{
      html = visible.map(rowHtml).join('');
    }} else {{
      var groups = {{}};
      var order = [];
      visible.forEach(function (r) {{
        var key = r[groupBy] || '(none)';
        if (!groups[key]) {{ groups[key] = []; order.push(key); }}
        groups[key].push(r);
      }});
      if (!sortState.key) {{
        order.sort(groupBy === 'pr_number' ? function (a, b) {{ return a - b; }} : undefined);
      }}
      html = order.map(function (key) {{
        var label = groupBy === 'pr_number' ? '#' + key : key;
        return groupHeaderHtml(label, groups[key].length) + groups[key].map(rowHtml).join('');
      }}).join('');
    }}

    tbody.innerHTML = html;
    emptyState.style.display = visible.length === 0 ? 'block' : 'none';
  }}

  dimChips.forEach(function (chip) {{
    chip.addEventListener('click', function () {{
      var dim = chip.dataset.dim, val = chip.dataset.value;
      var set = activeFilters[dim];
      if (set.has(val)) {{
        set.delete(val);
        chip.classList.remove('is-active');
      }} else {{
        set.add(val);
        chip.classList.add('is-active');
      }}
      updateClearChip();
      render();
    }});
  }});

  clearChip.addEventListener('click', function () {{
    Object.keys(activeFilters).forEach(function (d) {{ activeFilters[d].clear(); }});
    dimChips.forEach(function (c) {{ c.classList.remove('is-active'); }});
    updateClearChip();
    render();
  }});

  if (closedChip) {{
    closedChip.addEventListener('click', function () {{
      showClosed = !showClosed;
      closedChip.classList.toggle('is-active', showClosed);
      render();
    }});
  }}

  sortableHeaders.forEach(function (th) {{
    th.addEventListener('click', function () {{
      var key = th.dataset.sortKey;
      if (sortState.key !== key) {{
        sortState.key = key;
        sortState.dir = 1;
      }} else if (sortState.dir === 1) {{
        sortState.dir = -1;
      }} else {{
        sortState.key = null;
        sortState.dir = 0;
      }}
      updateSortIndicators();
      render();
    }});
  }});

  searchInput.addEventListener('input', render);
  groupSelect.addEventListener('change', render);
  render();
}})();
</script>
</body>
</html>
"""


def slugify(status):
    return re.sub(r"[^a-z0-9]+", "-", status.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
