import os
import json
import sqlite3
import datetime
import html
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "jobs.db"
DEFAULT_DASHBOARD_PATH = PROJECT_ROOT / "data" / "dashboard.html"

def load_data_readonly(db_path: Path) -> Dict[str, Any]:
    """
    Connects to SQLite using URI read-only mode (mode=ro).
    Any attempt to write will raise sqlite3.OperationalError.
    """
    db_uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # All jobs
        cursor.execute("""
            SELECT platform, job_id, title, company, location, url, match_score,
                   match_reason, status, failure_reason, pending_question,
                   applied_at, updated_at, created_at
            FROM jobs
            ORDER BY updated_at DESC, id DESC
        """)
        jobs = [dict(row) for row in cursor.fetchall()]

        # Job events timeline
        events = []
        try:
            cursor.execute("""
                SELECT id, platform, job_id, event, old_status, new_status, note, created_at
                FROM job_events
                ORDER BY created_at DESC, id DESC
                LIMIT 200
            """)
            events = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass  # If table does not exist in an older DB

        # Companies summary
        cursor.execute("""
            SELECT company,
                   COUNT(*) as total_apps,
                   GROUP_CONCAT(DISTINCT platform) as platforms,
                   MAX(updated_at) as last_date,
                   GROUP_CONCAT(status) as statuses
            FROM jobs
            WHERE company != ''
            GROUP BY company
            ORDER BY total_apps DESC, last_date DESC
        """)
        companies = [dict(row) for row in cursor.fetchall()]

        # Daily counts (last 7 days)
        today = datetime.date.today()
        daily = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            d_str = d.isoformat()
            cursor.execute("""
                SELECT platform, COUNT(*) FROM jobs
                WHERE status = 'APPLIED' AND DATE(applied_at) = DATE(?)
                GROUP BY platform
            """, (d_str,))
            counts = {row[0]: row[1] for row in cursor.fetchall()}
            daily.append({
                "date": d_str,
                "linkedin": counts.get("linkedin", 0),
                "naukri": counts.get("naukri", 0),
                "indeed": counts.get("indeed", 0),
                "total": sum(counts.values())
            })

    finally:
        conn.close()

    # Calculate summary metrics
    total_applied = sum(1 for j in jobs if j["status"] == "APPLIED")
    applied_today = sum(1 for j in jobs if j["status"] == "APPLIED" and str(j.get("applied_at", ""))[:10] == today.isoformat())
    applied_this_week = daily[-1]["total"] + sum(d["total"] for d in daily[:-1])
    unverified_count = sum(1 for j in jobs if j["status"] == "UNVERIFIED")
    needs_input_count = sum(1 for j in jobs if j["status"] == "NEEDS_INPUT")
    external_site_count = sum(1 for j in jobs if j["status"] == "EXTERNAL_SITE")
    skipped_count = sum(1 for j in jobs if j["status"] == "SKIPPED")

    by_platform = {}
    for j in jobs:
        p = j["platform"]
        by_platform[p] = by_platform.get(p, 0) + 1

    applied_by_platform = {}
    for j in jobs:
        if j["status"] == "APPLIED":
            p = j["platform"]
            applied_by_platform[p] = applied_by_platform.get(p, 0) + 1

    summary = {
        "total_jobs": len(jobs),
        "total_applied": total_applied,
        "applied_today": applied_today,
        "applied_this_week": applied_this_week,
        "unverified": unverified_count,
        "needs_input": needs_input_count,
        "external_site": external_site_count,
        "skipped": skipped_count,
        "by_platform": by_platform,
        "applied_by_platform": applied_by_platform,
    }

    return {
        "summary": summary,
        "jobs": jobs,
        "events": events,
        "companies": companies,
        "daily": daily,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def render_dashboard_html(data: Dict[str, Any]) -> str:
    """
    Renders pure, self-contained HTML with inline CSS and vanilla JS.
    Zero external fonts, CDN, or network calls.
    Never includes personal profile PII or sensitive form answers.
    All job fields (title, company, location, notes, reasons) are HTML-escaped.
    Embedded JSON is strictly escaped against '</script>'.
    """
    def sanitize_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        return {k: (html.escape(v) if isinstance(v, str) else v) for k, v in d.items()}

    safe_jobs = [sanitize_dict(j) for j in data.get("jobs", [])]
    safe_events = [sanitize_dict(e) for e in data.get("events", [])]
    safe_companies = [sanitize_dict(c) for c in data.get("companies", [])]

    safe_payload = {
        "summary": data.get("summary", {}),
        "jobs": safe_jobs,
        "events": safe_events,
        "companies": safe_companies,
        "daily": data.get("daily", []),
        "generated_at": data.get("generated_at", "")
    }

    # Make embedded JSON safe against </script> tag breakout
    data_json = json.dumps(safe_payload).replace("</", "<\\/")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Autopilot - Application History Dashboard</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --purple: #a855f7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 24px;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
    h1 {{ font-size: 24px; font-weight: 700; display: flex; align-items: center; gap: 8px; }}
    .badge-ro {{ background: #0369a1; color: #e0f2fe; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
    .timestamp {{ color: var(--text-muted); font-size: 13px; }}
    
    /* Summary Cards */
    .grid-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
    .card-title {{ font-size: 13px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; margin-bottom: 6px; }}
    .card-val {{ font-size: 28px; font-weight: 700; }}
    .card-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}
    .val-applied {{ color: var(--success); }}
    .val-unverified {{ color: var(--danger); }}
    .val-needs {{ color: var(--warning); }}
    .val-ext {{ color: var(--accent); }}

    /* Daily Caps Visualizer */
    .caps-section {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
    .caps-title {{ font-size: 14px; font-weight: 600; margin-bottom: 12px; }}
    .bar-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; font-size: 13px; }}
    .bar-date {{ width: 90px; color: var(--text-muted); font-mono; }}
    .bar-track {{ flex: 1; background: #334155; height: 16px; border-radius: 4px; overflow: hidden; display: flex; }}
    .bar-fill-li {{ background: #0a66c2; height: 100%; }}
    .bar-fill-nk {{ background: #2563eb; height: 100%; }}
    .bar-label {{ width: 140px; text-align: right; color: var(--text-muted); font-size: 12px; }}

    /* Tabs */
    .tabs {{ display: flex; gap: 8px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }}
    .tab-btn {{ background: none; border: none; color: var(--text-muted); padding: 8px 16px; font-size: 14px; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; }}
    .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}

    /* Controls & Table */
    .controls {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; align-items: center; }}
    .search-input {{ background: #0f172a; border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 13px; min-width: 240px; }}
    .select-filter {{ background: #0f172a; border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 13px; }}
    .btn-csv {{ background: #334155; border: 1px solid #475569; color: var(--text); padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; margin-left: auto; }}
    .btn-csv:hover {{ background: #475569; }}

    .table-container {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
    th {{ background: #1e293b; padding: 12px 14px; color: var(--text-muted); font-weight: 600; border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; white-space: nowrap; }}
    th:hover {{ color: var(--text); }}
    td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    tr:hover {{ background: rgba(255, 255, 255, 0.02); }}

    /* Badges */
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
    .badge-applied {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; }}
    .badge-unverified {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }}
    .badge-needs {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; }}
    .badge-ext {{ background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid #0284c7; }}
    .badge-skip {{ background: rgba(148, 163, 184, 0.2); color: #94a3b8; border: 1px solid #64748b; }}
    .badge-found {{ background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid #9333ea; }}
    .score-badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 12px; }}
    .score-high {{ background: #14532d; color: #86efac; }}
    .score-mid {{ background: #713f12; color: #fde047; }}
    .score-low {{ background: #450a0a; color: #fca5a5; }}

    a.job-link {{ color: var(--accent); text-decoration: none; word-break: break-all; }}
    a.job-link:hover {{ text-decoration: underline; }}
    .empty-state {{ padding: 32px; text-align: center; color: var(--text-muted); font-style: italic; }}
    .unverified-alert {{ color: #f87171; font-size: 11px; display: block; margin-top: 4px; font-weight: 600; }}

    /* Timeline */
    .timeline {{ padding: 16px; }}
    .timeline-item {{ display: flex; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--border); }}
    .timeline-time {{ width: 140px; color: var(--text-muted); font-size: 12px; flex-shrink: 0; }}
    .timeline-body {{ flex: 1; }}
    .timeline-tag {{ font-weight: 600; font-size: 12px; margin-right: 8px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Job Autopilot History <span class="badge-ro">Read-Only</span></h1>
        <p class="timestamp">Generated on {html.escape(data["generated_at"])} | SQLite URI: mode=ro</p>
      </div>
      <div>
        <span style="font-size: 13px; color: var(--text-muted);">Privacy Guard: Zero Form Answers / PII Stored</span>
      </div>
    </header>

    <!-- Top Summary Cards -->
    <div class="grid-cards">
      <div class="card">
        <div class="card-title">Total Applied</div>
        <div class="card-val val-applied">{data["summary"]["total_applied"]}</div>
        <div class="card-sub">Today: {data["summary"]["applied_today"]} | This Week: {data["summary"]["applied_this_week"]}</div>
      </div>
      <div class="card">
        <div class="card-title">Unverified Submits</div>
        <div class="card-val val-unverified">{data["summary"]["unverified"]}</div>
        <div class="card-sub">Check on platform directly</div>
      </div>
      <div class="card">
        <div class="card-title">Needs Input</div>
        <div class="card-val val-needs">{data["summary"]["needs_input"]}</div>
        <div class="card-sub">Awaiting answers.yaml update</div>
      </div>
      <div class="card">
        <div class="card-title">External Site</div>
        <div class="card-val val-ext">{data["summary"]["external_site"]}</div>
        <div class="card-sub">Saved for manual application</div>
      </div>
      <div class="card">
        <div class="card-title">Skipped / Filtered</div>
        <div class="card-val">{data["summary"]["skipped"]}</div>
        <div class="card-sub">Hard filters & low fit</div>
      </div>
      <div class="card">
        <div class="card-title">By Platform</div>
        <div class="card-val" style="font-size: 18px; margin-top: 4px;">
          LI: {data["summary"]["by_platform"].get("linkedin", 0)} | NK: {data["summary"]["by_platform"].get("naukri", 0)}
        </div>
        <div class="card-sub">Applied LI: {data["summary"]["applied_by_platform"].get("linkedin", 0)} | NK: {data["summary"]["applied_by_platform"].get("naukri", 0)}</div>
      </div>
    </div>

    <!-- Daily Applied Visualizer vs Caps -->
    <div class="caps-section">
      <div class="caps-title">Daily Applications vs Platform Caps (Past 7 Days)</div>
      <div id="capsBars"></div>
    </div>

    <!-- Tab Navigation -->
    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('jobs')">All Applications & Jobs ({len(data["jobs"])})</button>
      <button class="tab-btn" onclick="switchTab('companies')">Companies Summary ({len(data["companies"])})</button>
      <button class="tab-btn" onclick="switchTab('timeline')">Audit Timeline Events ({len(data["events"])})</button>
      <button class="tab-btn" onclick="switchTab('needsInput')">Needs Input List ({data["summary"]["needs_input"]})</button>
      <button class="tab-btn" onclick="switchTab('externalSite')">External Site Jobs ({data["summary"]["external_site"]})</button>
    </div>

    <!-- Tab 1: Jobs Table -->
    <div id="tab-jobs" class="tab-content active">
      <div class="controls">
        <input type="text" id="searchInput" class="search-input" placeholder="Search company, title, location, or reason..." oninput="filterJobs()">
        <select id="platformFilter" class="select-filter" onchange="filterJobs()">
          <option value="">All Platforms</option>
          <option value="linkedin">LinkedIn</option>
          <option value="naukri">Naukri</option>
          <option value="indeed">Indeed</option>
        </select>
        <select id="statusFilter" class="select-filter" onchange="filterJobs()">
          <option value="">All Statuses</option>
          <option value="APPLIED">APPLIED</option>
          <option value="UNVERIFIED">UNVERIFIED</option>
          <option value="FOUND">FOUND</option>
          <option value="SKIPPED">SKIPPED</option>
          <option value="NEEDS_INPUT">NEEDS_INPUT</option>
          <option value="EXTERNAL_SITE">EXTERNAL_SITE</option>
          <option value="RESUME_NOT_FOUND">RESUME_NOT_FOUND</option>
        </select>
        <button class="btn-csv" onclick="downloadCSV()">Download Table as CSV</button>
      </div>

      <div class="table-container">
        <table id="jobsTable">
          <thead>
            <tr>
              <th onclick="sortJobs('company')">Company ⇕</th>
              <th onclick="sortJobs('title')">Job Title ⇕</th>
              <th onclick="sortJobs('platform')">Platform ⇕</th>
              <th onclick="sortJobs('location')">Location ⇕</th>
              <th onclick="sortJobs('match_score')">Score ⇕</th>
              <th>Match Reason</th>
              <th onclick="sortJobs('status')">Status ⇕</th>
              <th onclick="sortJobs('updated_at')">Date / Time ⇕</th>
              <th>Job Link</th>
            </tr>
          </thead>
          <tbody id="jobsTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 2: Companies Summary -->
    <div id="tab-companies" class="tab-content">
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
        Distinct companies tracked in database. Sourced to avoid repeat applications.
      </p>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Total Jobs Encountered</th>
              <th>Platforms</th>
              <th>Statuses</th>
              <th>Last Seen</th>
            </tr>
          </thead>
          <tbody id="companiesTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 3: Timeline Events -->
    <div id="tab-timeline" class="tab-content">
      <div class="table-container timeline" id="timelineContainer"></div>
    </div>

    <!-- Tab 4: Needs Input List -->
    <div id="tab-needsInput" class="tab-content">
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
        Pending screening questions encountered during execution that require your confirmed answer in answers.yaml.
      </p>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Job Title</th>
              <th>Platform</th>
              <th>Pending Question</th>
              <th>Action Required</th>
            </tr>
          </thead>
          <tbody id="needsInputTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 5: External Site List -->
    <div id="tab-externalSite" class="tab-content">
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
        Jobs that redirect to third-party company websites (policy blocks automated clicks on external sites). Use these links to apply manually.
      </p>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Job Title</th>
              <th>Location</th>
              <th>Date Detected</th>
              <th>Manual Application Link</th>
            </tr>
          </thead>
          <tbody id="externalSiteTbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    const DATA = {data_json};
    let currentJobs = [...DATA.jobs];
    let sortKey = 'updated_at';
    let sortAsc = false;

    // Daily caps rendering
    function renderCaps() {{
      const container = document.getElementById('capsBars');
      container.innerHTML = '';
      DATA.daily.forEach(d => {{
        const row = document.createElement('div');
        row.className = 'bar-row';
        // 35 total cap guideline (LI 15 + NK 20)
        const pctLi = Math.min(100, (d.linkedin / 35) * 100);
        const pctNk = Math.min(100, (d.naukri / 35) * 100);
        row.innerHTML = `
          <div class="bar-date">${{d.date}}</div>
          <div class="bar-track">
            <div class="bar-fill-li" style="width: ${{pctLi}}%" title="LinkedIn: ${{d.linkedin}} / 15"></div>
            <div class="bar-fill-nk" style="width: ${{pctNk}}%" title="Naukri: ${{d.naukri}} / 20"></div>
          </div>
          <div class="bar-label">LI: ${{d.linkedin}}/15 | NK: ${{d.naukri}}/20 (Total ${{d.total}})</div>
        `;
        container.appendChild(row);
      }});
    }}

    // Status badge class
    function getStatusBadge(status) {{
      const s = (status || '').toUpperCase();
      if (s === 'APPLIED') return '<span class="badge badge-applied">APPLIED</span>';
      if (s === 'UNVERIFIED') return '<span class="badge badge-unverified">UNVERIFIED</span><span class="unverified-alert">Check on platform directly</span>';
      if (s === 'NEEDS_INPUT') return '<span class="badge badge-needs">NEEDS_INPUT</span>';
      if (s === 'EXTERNAL_SITE') return '<span class="badge badge-ext">EXTERNAL_SITE</span>';
      if (s === 'FOUND') return '<span class="badge badge-found">FOUND</span>';
      return `<span class="badge badge-skip">${{s || 'SKIPPED'}}</span>`;
    }}

    function getScoreBadge(score) {{
      if (score === null || score === undefined || score === 0) return '<span style="color:var(--text-muted);">-</span>';
      let cls = 'score-mid';
      if (score >= 65) cls = 'score-high';
      else if (score < 50) cls = 'score-low';
      return `<span class="score-badge ${{cls}}">${{score}}</span>`;
    }}

    function renderJobsTable() {{
      const tbody = document.getElementById('jobsTbody');
      tbody.innerHTML = '';
      if (currentJobs.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No matching jobs found.</td></tr>';
        return;
      }}
      currentJobs.forEach(j => {{
        const tr = document.createElement('tr');
        const linkHtml = j.url ? `<a href="${{escapeHtml(j.url)}}" target="_blank" rel="noopener noreferrer" class="job-link">View Job ↗</a>` : '-';
        tr.innerHTML = `
          <td><strong>${{escapeHtml(j.company || 'Unknown')}}</strong></td>
          <td>${{escapeHtml(j.title || '')}}</td>
          <td><span style="text-transform: capitalize;">${{escapeHtml(j.platform)}}</span></td>
          <td>${{escapeHtml(j.location || '-')}}</td>
          <td>${{getScoreBadge(j.match_score)}}</td>
          <td style="max-width: 320px; font-size: 12px; color: var(--text-muted);">${{escapeHtml(j.match_reason || j.failure_reason || '-')}}</td>
          <td>${{getStatusBadge(j.status)}}</td>
          <td style="white-space: nowrap; font-size: 12px; color: var(--text-muted);">${{escapeHtml((j.applied_at || j.updated_at || '').replace('T', ' ').substring(0, 19))}}</td>
          <td>${{linkHtml}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderCompanies() {{
      const tbody = document.getElementById('companiesTbody');
      tbody.innerHTML = '';
      if (DATA.companies.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No companies recorded.</td></tr>';
        return;
      }}
      DATA.companies.forEach(c => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${{escapeHtml(c.company)}}</strong></td>
          <td>${{c.total_apps}}</td>
          <td>${{escapeHtml(c.platforms || '-')}}</td>
          <td><span style="font-size: 11px; color: var(--text-muted);">${{escapeHtml(c.statuses || '-')}}</span></td>
          <td style="font-size: 12px; color: var(--text-muted);">${{escapeHtml((c.last_date || '').replace('T', ' ').substring(0, 19))}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderTimeline() {{
      const container = document.getElementById('timelineContainer');
      container.innerHTML = '';
      if (DATA.events.length === 0) {{
        container.innerHTML = '<div class="empty-state">No timeline events recorded yet.</div>';
        return;
      }}
      DATA.events.forEach(e => {{
        const item = document.createElement('div');
        item.className = 'timeline-item';
        item.innerHTML = `
          <div class="timeline-time">${{escapeHtml((e.created_at || '').replace('T', ' ').substring(0, 19))}}</div>
          <div class="timeline-body">
            <span class="timeline-tag">${{getStatusBadge(e.event)}}</span>
            <strong>[${{escapeHtml(e.platform)}}]</strong> Job ID: <code>${{escapeHtml(e.job_id)}}</code>
            ${{e.old_status ? `<span style="color:var(--text-muted); font-size:12px;"> (${{e.old_status}} → ${{e.new_status}})</span>` : ''}}
            ${{e.note ? `<div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">${{escapeHtml(e.note)}}</div>` : ''}}
          </div>
        `;
        container.appendChild(item);
      }});
    }}

    function renderNeedsInput() {{
      const tbody = document.getElementById('needsInputTbody');
      tbody.innerHTML = '';
      const items = DATA.jobs.filter(j => j.status === 'NEEDS_INPUT');
      if (items.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No pending questions. All questions resolved!</td></tr>';
        return;
      }}
      items.forEach(j => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${{escapeHtml(j.company)}}</strong></td>
          <td>${{escapeHtml(j.title)}}</td>
          <td>${{escapeHtml(j.platform)}}</td>
          <td style="color: #fbbf24; font-weight: 500;">${{escapeHtml(j.pending_question || j.failure_reason || 'Unknown question')}}</td>
          <td><code style="font-size: 11px; background: #334155; padding: 2px 6px; border-radius: 4px;">Add to config/answers.yaml</code></td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderExternalSite() {{
      const tbody = document.getElementById('externalSiteTbody');
      tbody.innerHTML = '';
      const items = DATA.jobs.filter(j => j.status === 'EXTERNAL_SITE');
      if (items.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No external site jobs detected.</td></tr>';
        return;
      }}
      items.forEach(j => {{
        const tr = document.createElement('tr');
        const link = j.url ? `<a href="${{escapeHtml(j.url)}}" target="_blank" rel="noopener noreferrer" class="job-link">Open Third-Party Job Site ↗</a>` : '-';
        tr.innerHTML = `
          <td><strong>${{escapeHtml(j.company)}}</strong></td>
          <td>${{escapeHtml(j.title)}}</td>
          <td>${{escapeHtml(j.location || '-')}}</td>
          <td style="font-size: 12px; color: var(--text-muted);">${{escapeHtml((j.updated_at || '').replace('T', ' ').substring(0, 19))}}</td>
          <td>${{link}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function filterJobs() {{
      const query = document.getElementById('searchInput').value.toLowerCase().trim();
      const platform = document.getElementById('platformFilter').value;
      const status = document.getElementById('statusFilter').value;

      currentJobs = DATA.jobs.filter(j => {{
        if (platform && j.platform !== platform) return false;
        if (status && j.status !== status) return false;
        if (query) {{
          const target = `${{j.company || ''}} ${{j.title || ''}} ${{j.location || ''}} ${{j.match_reason || ''}} ${{j.failure_reason || ''}}`.toLowerCase();
          if (!target.includes(query)) return false;
        }}
        return true;
      }});
      sortJobs(sortKey, true);
    }}

    function sortJobs(key, keepDir) {{
      if (!keepDir) {{
        if (sortKey === key) sortAsc = !sortAsc;
        else {{ sortKey = key; sortAsc = true; }}
      }}
      currentJobs.sort((a, b) => {{
        let valA = a[key] ?? '';
        let valB = b[key] ?? '';
        if (typeof valA === 'number' && typeof valB === 'number') {{
          return sortAsc ? valA - valB : valB - valA;
        }}
        return sortAsc ? String(valA).localeCompare(String(valB)) : String(valB).localeCompare(String(valA));
      }});
      renderJobsTable();
    }}

    function switchTab(name) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      const target = document.getElementById('tab-' + name);
      if (target) target.classList.add('active');
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    function downloadCSV() {{
      const headers = ['Company', 'Job Title', 'Platform', 'Location', 'Match Score', 'Status', 'Date', 'URL'];
      const rows = currentJobs.map(j => [
        `"${{(j.company || '').replace(/"/g, '""')}}"`,
        `"${{(j.title || '').replace(/"/g, '""')}}"`,
        `"${{(j.platform || '').replace(/"/g, '""')}}"`,
        `"${{(j.location || '').replace(/"/g, '""')}}"`,
        j.match_score ?? '',
        `"${{(j.status || '').replace(/"/g, '""')}}"`,
        `"${{(j.applied_at || j.updated_at || '').replace(/"/g, '""')}}"`,
        `"${{(j.url || '').replace(/"/g, '""')}}"`
      ]);
      const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\\n');
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement('a');
      link.setAttribute('href', encodedUri);
      link.setAttribute('download', `job_autopilot_applications_${{new Date().toISOString().slice(0, 10)}}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }}

    // Init
    renderCaps();
    renderJobsTable();
    renderCompanies();
    renderTimeline();
    renderNeedsInput();
    renderExternalSite();
  </script>
</body>
</html>"""
    return html_content


def generate_dashboard(db_path: Optional[Path] = None, output_path: Optional[Path] = None) -> Path:
    """
    Generates data/dashboard.html from SQLite database in read-only mode.
    """
    db_file = db_path or DEFAULT_DB_PATH
    out_file = output_path or DEFAULT_DASHBOARD_PATH
    out_file.parent.mkdir(parents=True, exist_ok=True)

    data = load_data_readonly(db_file)
    content = render_dashboard_html(data)

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[Dashboard] Generated self-contained dashboard at: {out_file.resolve()}")
    return out_file


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Serves the generated dashboard.html safely bound to 127.0.0.1 only."""
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/dashboard.html"
        return super().do_GET()


def serve_dashboard(output_file: Optional[Path] = None, port: int = 8080, host: str = "127.0.0.1") -> None:
    """
    Starts standard library HTTP server strictly bound to 127.0.0.1.
    """
    target = output_file or DEFAULT_DASHBOARD_PATH
    if not target.exists():
        generate_dashboard(output_path=target)

    directory = str(target.parent.resolve())
    handler = lambda *args, **kwargs: DashboardRequestHandler(*args, directory=directory, **kwargs)
    
    server = HTTPServer((host, port), handler)
    print(f"[Dashboard Server] Serving read-only dashboard at http://{host}:{port}/")
    print(f"[Dashboard Server] Bound strictly to {host}. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Dashboard Server] Stopped.")
        server.server_close()
