"""Tests for check_submission.py: good mods pass, script mods get a look, anything against the rules is refused.
Run: python -m unittest discover -s tools"""
import io
import json
import unittest
import zipfile

import check_submission as cs

TOML = b'[mod]\nid = "test-mod"\nname = "Test"\nversion = "1.0.0"\nauthors = ["me"]\n'


def zipped(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def rmod(*files, patches=()) -> bytes:
    return json.dumps({"id": "x", "name": "X", "version": "1.0.0", "patches": list(patches),
                       "file_patches": [{"dat": d, "files": [{"container": c, "path": p, "data": ""}]}
                                        for d, c, p in files]}).encode()


def verdict(name: str, raw: bytes) -> cs.Report:
    rep = cs.Report()
    cs.check_file(name, raw, rep)
    return rep


class Passes(unittest.TestCase):
    def test_data_mod(self):
        rep = verdict("m.rusemod", zipped({"test-mod/mod.toml": TOML, "test-mod/src/a.rndf": b"x"}))
        self.assertEqual(rep.code(), 0, rep.refused + rep.review)

    def test_rmod_data_only(self):
        r = rmod(patches=[{"ndf": "a/everything.cpp.gladndfbin", "changes": [{}]}])
        self.assertEqual(verdict("m.rmod", r).code(), 0)

    def test_rmod_in_a_zip(self):
        self.assertEqual(verdict("m.zip", zipped({"m.rmod": rmod()})).code(), 0)


class NeedsALook(unittest.TestCase):
    def test_game_script(self):
        r = rmod(("Data/PC/1/ZZ_Win.dat", "genpython/eugen.ipk", "a/b/input.xyz"))
        rep = verdict("m.rmod", r)
        self.assertEqual(rep.code(), 1)
        self.assertIn("1 of the game's scripts", rep.review[0])


class Refused(unittest.TestCase):
    def test_program_in_package(self):
        rep = verdict("m.zip", zipped({"mod.toml": TOML, "files/tool.exe": b"MZ"}))
        self.assertEqual(rep.code(), 2)

    def test_python_in_package(self):
        self.assertEqual(verdict("m.zip", zipped({"mod.toml": TOML, "x.py": b"print(1)"})).code(), 2)

    def test_game_script_in_studio_mod(self):
        self.assertEqual(verdict("m.zip", zipped({"mod.toml": TOML, "files/a.xyz": b"x"})).code(), 2)

    def test_rmod_writes_the_program(self):
        self.assertEqual(verdict("m.rmod", rmod(("RUSE.exe", "", "RUSE.exe"))).code(), 2)

    def test_rmod_outside_the_archives(self):
        self.assertEqual(verdict("m.rmod", rmod(("Data/PC/1/notes.txt", "", "x.txt"))).code(), 2)

    def test_rmod_program_in_archive(self):
        self.assertEqual(verdict("m.rmod", rmod(("Data/PC/1/ZZ_Win.dat", "", "hack.dll"))).code(), 2)

    def test_path_out_of_folder(self):
        self.assertEqual(verdict("m.zip", zipped({"mod.toml": TOML, "../../evil.txt": b"x"})).code(), 2)
        self.assertEqual(verdict("m.rmod", rmod(("Data/PC/1/ZZ_Win.dat", "", "../../../x.txt"))).code(), 2)

    def test_archive_inside(self):
        self.assertEqual(verdict("m.zip", zipped({"mod.toml": TOML, "more.zip": b"PK"})).code(), 2)

    def test_no_manifest(self):
        self.assertEqual(verdict("m.zip", zipped({"readme.txt": b"hi"})).code(), 2)

    def test_bad_id_and_version(self):
        bad = b'[mod]\nid = "Bad Id"\nname = "x"\nversion = "one"\n'
        rep = verdict("m.zip", zipped({"mod.toml": bad}))
        self.assertEqual(rep.code(), 2)
        self.assertEqual(len(rep.refused), 2)

    def test_not_a_mod(self):
        self.assertEqual(verdict("m.exe", b"MZ\x90\x00").code(), 2)

    def test_too_big_unpacked(self):
        z = zipped({"mod.toml": TOML})
        old = cs.MAX_UNPACKED
        cs.MAX_UNPACKED = 10
        try:
            self.assertEqual(verdict("m.zip", z).code(), 2)
        finally:
            cs.MAX_UNPACKED = old


if __name__ == "__main__":
    unittest.main()
