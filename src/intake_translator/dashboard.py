"""Generate an offline, read-only screen-share dashboard from fictional cases."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import tempfile

from .demo import walkthrough

CASES = (
    ("good-agreement", "Agreement", "Three sources agree after normalization."),
    ("bad-conflict", "Conflicting launch dates", "Hold the decision and retain each source."),
    ("bad-missing-required", "Missing launch date", "A required fact cannot be guessed."),
    ("bad-invalid-date", "Invalid calendar date", "Reject February 30 before storage."),
    ("bad-unknown-field", "Unmapped field", "Reject a field outside the intake contract."),
    ("bad-unsupported-version", "Schema drift", "Reject a version the translator cannot read."),
)
STYLE = """
:root{color-scheme:light;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#172b35;background:#f3f6f4}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1240px;margin:auto;padding:0 30px 72px}
header{background:#102f38;color:#effbf5;padding:56px 0 72px}.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;color:#6ee7b7}.hero{max-width:1240px;margin:auto;padding:0 30px}h1{font-size:clamp(32px,5vw,60px);line-height:1.04;letter-spacing:-.045em;margin:14px 0 18px}header p{max-width:720px;line-height:1.58;color:#c8dfdb;font-size:17px;margin:0}.hero strong{color:#fff}
.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:-38px;position:relative}.metric,.panel,.case{background:#fff;border:1px solid #dce7e2;border-radius:16px;box-shadow:0 9px 25px #17322a0b}.metric{padding:21px 23px}.metric b{display:block;font-size:27px;letter-spacing:-.04em;color:#123a38}.metric span{font-size:12px;color:#57706f;text-transform:uppercase;letter-spacing:.08em;font-weight:750}
h2{font-size:27px;letter-spacing:-.03em;margin:49px 0 8px}.intro{color:#5c7174;line-height:1.6;margin:0 0 22px}.steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.panel{padding:22px;min-height:167px}.step-number{display:inline-flex;align-items:center;justify-content:center;width:29px;height:29px;border-radius:9px;background:#d8f5e8;color:#075d44;font-size:13px;font-weight:800}.panel h3{margin:13px 0 7px;font-size:17px}.panel p{font-size:14px;line-height:1.55;color:#536b6c;margin:0}
.case-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.case{padding:23px;min-height:218px}.case-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.case h3{font-size:18px;letter-spacing:-.02em;margin:0 0 6px}.case .desc{font-size:14px;color:#64787a;line-height:1.5;margin:0 0 17px}.pill{font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;padding:7px 9px;border-radius:99px;white-space:nowrap}.review{background:#fff0cf;color:#8a5700}.reject{background:#ffe4e1;color:#a4352f}.agree{background:#dff5e8;color:#126644}.details{background:#f5f8f7;border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.55;color:#304b51;overflow-wrap:anywhere}.details p{margin:0 0 5px}.details p:last-child{margin:0}.source{display:inline-block;font-weight:750;min-width:43px}.rule{border-top:1px solid #e0eae7;margin:12px 0}.decision{margin-top:18px;padding:20px 24px;background:#e4f5ed;border:1px solid #b6e3ca;border-radius:14px;color:#195242;line-height:1.6}.decision b{color:#123f36}footer{color:#718280;font-size:12px;line-height:1.6;margin-top:36px}
@media(max-width:800px){.summary{grid-template-columns:repeat(2,1fr)}.steps{grid-template-columns:1fr}.case-grid{grid-template-columns:1fr}.shell,.hero{padding-left:18px;padding-right:18px}header{padding:43px 0 65px}.metric{padding:17px}}
@media print{header{padding:25px 0 55px}.shell{padding-bottom:5px}.metric,.panel,.case{box-shadow:none;break-inside:avoid}h2{margin-top:22px}}
"""


def _case_html(name: str, title: str, description: str, result: dict[str, object]) -> str:
    if "error" in result:
        badge, cls = "Rejected", "reject"
        detail = f'<p><b>{escape(str(result["error"]))}</b>: {escape(str(result["detail"]))}</p><p>No packet was stored. Fix the input and retry.</p>'
    else:
        conflicts = result["conflicts"]
        questions = result["questions"]
        badge, cls = ("Review", "review") if questions else ("Agreement", "agree")
        if conflicts:
            candidates = next(iter(conflicts.values()))
            lines = ''.join(f'<p><span class="source">{escape(str(c["source"]))}</span> {escape(str(c["value"]))}</p>' for c in candidates)
            detail = f'{lines}<div class="rule"></div><p>{escape(str(questions[0]))}</p>'
        elif questions:
            detail = f'<p>{escape(str(questions[0]))}</p><p>Required field missing from every source.</p>'
        else:
            detail = '<p>Resolved launch date: 2026-12-01 · Seats: 40</p><p>No conflicts, but still <b>needs_review</b>.</p>'
    return f'<article class="case"><div class="case-top"><div><h3>{escape(title)}</h3><p class="desc">{escape(description)}</p></div><span class="pill {cls}">{badge}</span></div><div class="details">{detail}</div></article>'


def render_dashboard(results: dict[str, object]) -> str:
    """Return self-contained HTML. Escape every dynamic value from sample data."""
    samples = results["samples"]
    cards = ''.join(_case_html(name, title, desc, samples[name]) for name, title, desc in CASES)
    project = results["mock_project"]
    project_name = escape(str(project["customer_name"]))
    launch = escape(str(project["launch_date"]))
    source = escape(str(results["selected_source"]))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>Intake Translator | Local demo</title><style>{STYLE}</style></head>
<body><header><div class="hero"><div class="eyebrow">Implementation engineering · fictional data</div><h1>Turn messy intake into<br>an explicit decision.</h1><p>Three sample sources disagree. The translator keeps the evidence, stops an unreviewed write, and shows exactly what a reviewer selected. <strong>Offline demo, not a live CRM.</strong></p></div></header>
<main class="shell"><section class="summary" aria-label="Demo summary"><div class="metric"><b>3</b><span>sample sources</span></div><div class="metric"><b>6</b><span>test scenarios</span></div><div class="metric"><b>1</b><span>explicit review gate</span></div><div class="metric"><b>0</b><span>external writes</span></div></section>
<section><h2>The path from input to project</h2><p class="intro">This snapshot was generated from the same Python logic as the CLI demo. It is read-only; refreshing it cannot approve or write anything.</p><div class="steps"><div class="panel"><span class="step-number">1</span><h3>Collect and compare</h3><p>Normalize form, CRM and meeting notes. Keep competing launch dates and their source labels instead of picking a winner.</p></div><div class="panel"><span class="step-number">2</span><h3>Require a human choice</h3><p>Before review, the local mock write returns <b>{escape(str(results['before_review']))}</b>. The fictional review chooses <b>{source}</b> for the launch date.</p></div><div class="panel"><span class="step-number">3</span><h3>Write only to the mock</h3><p>One local SQLite mock project is created. Replaying the same decision returns the stored project without a duplicate.</p></div></div></section>
<section><h2>Inputs and outcomes</h2><p class="intro">Agreement does not mean automatic approval. Conflicts and missing facts become review questions; invalid payloads fail validation.</p><div class="case-grid">{cards}</div><div class="decision"><b>Final local mock project:</b> {project_name} · Launch {launch} · Chosen from {source}. The repeat returned <b>replayed: {str(bool(results['mock_project_replayed'])).lower()}</b>. Temporary database: <b>{escape(str(results['state']))}</b>.</div></section>
<footer>Fictional examples only. Source-shaped examples are illustrative, not captured vendor payloads. No trial account, API key, external CRM connection or real customer approval is involved. Open docs/SAMPLE_GALLERY.md for the exact input files and expected output.</footer></main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, default=Path(__file__).resolve().parents[2] / "examples")
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "intake-dashboard.html")
    args = parser.parse_args()
    results = walkthrough(args.examples)
    output = args.output.expanduser().resolve()
    output.write_text(render_dashboard(results), encoding="utf-8")
    print(f"Open in your browser: {output.as_uri()}")


if __name__ == "__main__":
    main()
