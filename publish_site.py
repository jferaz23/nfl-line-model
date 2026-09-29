#!/usr/bin/env python
"""Assemble the GitHub Pages site from the weekly line sheets.

Copies the newest reports/line_sheet_*.html into site_archive/ (kept in git so past weeks stay
online), then writes public/: index.html = the newest week, weeks/<stem>.html = every week, and
archive.html listing them all. GitHub Actions uploads public/ to Pages.

    python publish_site.py
"""
from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
ARCHIVE = ROOT / "site_archive"
PUBLIC = ROOT / "public"
STEM = re.compile(r"line_sheet_(\d{4})_week(\d{2})\.html$")


def main() -> int:
    ARCHIVE.mkdir(exist_ok=True)
    for f in REPORTS.glob("line_sheet_*.html"):          # top level only: skips reports/demo/
        if STEM.search(f.name):
            shutil.copy2(f, ARCHIVE / f.name)
    weeks = sorted((f for f in ARCHIVE.glob("line_sheet_*.html") if STEM.search(f.name)),
                   key=lambda f: STEM.search(f.name).groups(), reverse=True)
    if not weeks:
        print("No line sheets found in reports/ or site_archive/; run run_week.py first.")
        return 1

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    (PUBLIC / "weeks").mkdir(parents=True)
    for f in weeks:
        shutil.copy2(f, PUBLIC / "weeks" / f.name)
    shutil.copy2(weeks[0], PUBLIC / "index.html")
    (PUBLIC / ".nojekyll").write_text("")

    items = "".join(
        f'<li><a href="weeks/{html.escape(f.name)}">{s} season, week {int(w)}</a></li>'
        for f in weeks for s, w in [STEM.search(f.name).groups()])
    (PUBLIC / "archive.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL line sheets</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1b1d1f; --muted:#5d6166; --link:#1f5fbf; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141619; --fg:#e8e9ea; --muted:#9aa0a6; --link:#7fb0ff; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; margin:0; padding:32px 16px; }}
main {{ max-width:640px; margin:0 auto; }} a {{ color:var(--link); }} p {{ color:var(--muted); }}
</style></head><body><main>
<h1>NFL line sheets</h1><p><a href="index.html">Latest week</a></p><ul>{items}</ul>
<p>For information only, not financial advice. If betting stops being fun, call 1-800-GAMBLER.</p>
</main></body></html>""", encoding="utf-8")
    print(f"public/ built: latest = {weeks[0].name}, {len(weeks)} week(s) archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
