"""Tests for check_issue.py: which links it takes from the form, and what it reports. Nothing is downloaded."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import check_issue as ci

GOOD = "https://github.com/user-attachments/files/123456/formations-0.3.0.zip"
BODY = ("### Mod name\n\nFormations\n\n### What its code does\n\nSee https://example.com/x.zip\n\n"
        f"### The mod file\n\n[formations-0.3.0.zip]({GOOD})\n\n### Before you send it\n\n- [X] ok\n")


def package() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mod.toml", '[mod]\nid = "f"\nname = "F"\nversion = "1.0.0"\n')
    return buf.getvalue()


class FindUrl(unittest.TestCase):
    def test_attachment_in_its_section(self):
        self.assertEqual(ci.find_url(BODY), GOOD)

    def test_release_link(self):
        url = "https://github.com/someone/mods/releases/download/v1/my-mod.zip"
        self.assertEqual(ci.find_url(f"### The mod file\n\n{url}\n"), url)

    def test_other_sites_ignored(self):
        self.assertIsNone(ci.find_url("### The mod file\n\nhttps://example.com/mod.zip\nhttp://github.com/a/b.zip"))


class Run(unittest.TestCase):
    def test_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ci.run(BODY, Path(tmp), fetch=lambda url: package()), "keeps")
            self.assertIn("Keeps to the guidelines", (Path(tmp) / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(ci.run("no link here", Path(tmp)), "nofile")

            def broken(url):
                raise OSError("404")
            self.assertEqual(ci.run(BODY, Path(tmp), fetch=broken), "nofile")


if __name__ == "__main__":
    unittest.main()
