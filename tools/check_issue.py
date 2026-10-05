"""Run by .github/workflows/check-submission.yml when an "Add my mod" issue is opened or edited: find the mod file in
the form, download it (GitHub attachments and GitHub release files only, size-capped), run check_submission on it, and
write report.md and the verdict for the workflow. The issue's text comes in through the BODY environment variable and
is only ever read as text.

    BODY=... python tools/check_issue.py   ->  report.md, and "verdict=<keeps|look|against|nofile>" in $GITHUB_OUTPUT
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_submission as cs  # noqa: E402

# Where a mod file may come from: a file attached to the issue, or a release on GitHub.
ALLOWED = re.compile(r"https://github\.com/(?:user-attachments/files/\d+/[^\s)\]>\"']+"
                     r"|[\w.-]+/[\w.-]+/(?:files/\d+/|releases/download/)[^\s)\]>\"']+)")
VERDICT = {0: "keeps", 1: "look", 2: "against"}


def find_url(body: str) -> str | None:
    """The first mod file link in the form's "The mod file" section (or anywhere, if the section isn't found)."""
    part = body.split("### The mod file", 1)[-1].split("\n### ", 1)[0] if "### The mod file" in body else body
    m = ALLOWED.search(part) or ALLOWED.search(body)
    return m.group(0) if m else None


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Ruse-Mods submission check"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (https only: ALLOWED)
        data = r.read(cs.MAX_FILE + 1)
    return data


def run(body: str, out_dir: Path, fetch=download) -> str:
    url = find_url(body)
    report = out_dir / "report.md"
    if url is None:
        report.write_text("### Automatic check\n\nNo mod file found in the form. Drag your mod's **.zip** into "
                          "\"The mod file\" (edit the issue), or link a file on a GitHub release.\n", encoding="utf-8")
        return "nofile"
    name = url.rsplit("/", 1)[-1]
    try:
        raw = fetch(url)
    except Exception as exc:  # noqa: BLE001 (any failure to fetch is reported, never raised)
        report.write_text(f"### Automatic check\n\nThe mod file couldn't be downloaded ({exc.__class__.__name__}). "
                          f"Check the link, or attach the .zip again.\n", encoding="utf-8")
        return "nofile"
    rep = cs.Report()
    index = Path(__file__).parent.parent / "index.toml"
    cs.check_file(name, raw, rep, index.read_text(encoding="utf-8") if index.is_file() else None)
    report.write_text(rep.markdown(name) + "\n", encoding="utf-8")
    return VERDICT[rep.code()]


def main() -> int:
    verdict = run(os.environ.get("BODY", ""), Path.cwd())
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict}\n")
    print(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
