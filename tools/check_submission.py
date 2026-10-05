"""Check a mod sent to the list ("Add my mod" form) before anyone reviews it: what's in it, and whether it keeps to
GUIDELINES.md. It only READS the file: nothing in a mod is unpacked to disk or run.

    python tools/check_submission.py <mod file> [--index index.toml] [--report report.md]

The file can be a RUSE Studio mod (.rusemod, or the same file renamed .zip), a RUSE Mod Manager mod (.rmod), or a .zip
holding one of those. Exit code: 0 = keeps to the rules, 1 = keeps to them but needs a person's look first (it changes
the game's own scripts), 2 = against the rules (the report says why). Standard library only (Python 3.11+).

The rules mirror RUSE Studio's and RUSE Launcher's own (the Launcher refuses the same files when it installs a mod):
no programs and nothing that runs on the PC; the game's own scripts only inside a .rmod, said in the form; a mod
changes the game's data in a modded copy, never the game's install or its program.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tomllib
import zipfile
from pathlib import PurePosixPath

# Files that would run on the PC or inside the game. The same list as the apps' (RUSE Studio's NOT_IN_MODS).
RUNNABLE = {".py", ".pyc", ".pyo", ".pyw", ".pyd", ".xyz", ".ipk", ".exe", ".dll", ".com", ".scr", ".msi", ".bat",
            ".cmd", ".ps1", ".vbs", ".js", ".jar"}
GAME_SCRIPTS = {".xyz", ".ipk"}          # the game's own scripts: allowed in a .rmod, said in the form, reviewed
MAX_FILE = 200 * 1024 * 1024             # the biggest mod file we take
MAX_UNPACKED = 1024 * 1024 * 1024        # what its contents may add up to (a zip that grows past this is refused)
MAX_FILES = 20000
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+([.+-][0-9A-Za-z.+-]*)?$")


class Report:
    def __init__(self):
        self.refused: list[str] = []     # against the rules
        self.review: list[str] = []      # allowed, a person looks first
        self.notes: list[str] = []       # what's in it
        self.facts: dict[str, str] = {}

    def code(self) -> int:
        return 2 if self.refused else 1 if self.review else 0

    def markdown(self, name: str) -> str:
        verdict = {0: "✅ **Keeps to the guidelines.** A maintainer still reads the form before it's listed.",
                   1: "🟡 **Needs a maintainer's look first** (it changes the game's own scripts; the form must say "
                      "what each change does).",
                   2: "❌ **Against the guidelines**: it can't go on the list as it is. See below, fix it, then edit "
                      "the issue with the new file."}[self.code()]
        out = [f"### Automatic check: `{name}`", "", verdict, ""]
        if self.facts:
            out += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in self.facts.items()] + [""]
        for title, items in (("Against the guidelines", self.refused), ("For the maintainer to look at", self.review),
                             ("What's in it", self.notes)):
            if items:
                out += [f"**{title}:**", ""] + [f"- {i}" for i in items] + [""]
        out += ["<sub>This check only reads the file; nothing in it is run. The rules: "
                "[GUIDELINES.md](../blob/main/GUIDELINES.md).</sub>"]
        return "\n".join(out)


def suffixes(path: str) -> set[str]:
    """Every extension along a path (folder names included), lowercase."""
    return {PurePosixPath(p).suffix.lower() for p in path.replace("\\", "/").split("/") if p}


def unsafe_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return p.startswith("/") or re.match(r"^[A-Za-z]:", p) is not None or ".." in p.split("/")


def check_rmod(raw: bytes, where: str, rep: Report) -> None:
    """A RUSE Mod Manager mod: JSON. Its patches change the game's data; its file patches replace files inside the
    game's archives (never outside them)."""
    try:
        mod = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        rep.refused.append(f"`{where}` isn't a readable .rmod ({exc.__class__.__name__}).")
        return
    if not isinstance(mod, dict):
        rep.refused.append(f"`{where}` isn't a .rmod (not a JSON object).")
        return
    for key in ("id", "name", "version"):
        if mod.get(key):
            rep.facts.setdefault(f".rmod {key}", f"`{mod.get(key)}`")
    patches = mod.get("patches") or []
    files = [(g.get("dat", ""), f.get("container", ""), f.get("path", ""))
             for g in (mod.get("file_patches") or []) if isinstance(g, dict)
             for f in (g.get("files") or []) if isinstance(f, dict)]
    texts = sum(len(g.get("entries") or []) for g in (mod.get("loc_patches") or []) if isinstance(g, dict))
    data_files = sorted({str(p.get("ndf", "")) for p in patches if isinstance(p, dict)})
    changes = sum(len(p.get("changes") or []) for p in patches if isinstance(p, dict))
    rep.notes.append(f"`{where}`: {changes} data change(s) in {len(data_files)} game data file(s), {texts} text(s), "
                     f"{len(files)} file(s) replaced or added inside the game's archives.")
    scripts: dict[str, int] = {}
    for dat, container, path in files:
        full = "/".join(p for p in (dat, container, path) if p)
        name = full.replace("\\", "/").rsplit("/", 1)[-1]
        kinds = suffixes(container) | suffixes(path)
        if not str(dat).lower().endswith(".dat"):
            rep.refused.append(f"`{where}` writes `{name}` outside the game's data archives: a mod changes the "
                               f"game's data, never its install or its program.")
        elif kinds & GAME_SCRIPTS:
            scripts[name] = scripts.get(name, 0) + 1
        elif kinds & RUNNABLE:
            rep.refused.append(f"`{where}` brings something that would run on the PC: `{name}`.")
        if unsafe_path(str(path)) or unsafe_path(str(container)) or unsafe_path(str(dat)):
            rep.refused.append(f"`{where}` has a path that leaves the game's folder (`{name}`).")
    if scripts:
        shown = ", ".join(f"`{n}`" + (f" ×{c}" if c > 1 else "") for n, c in sorted(scripts.items())[:4])
        rep.review.append(f"`{where}` changes {sum(scripts.values())} of the game's scripts ({shown}"
                          f"{', …' if len(scripts) > 4 else ''}). The form must say what each change does.")
    if data_files:
        shown = ", ".join(f"`{d.rsplit('/', 1)[-1]}`" for d in data_files[:6])
        rep.notes.append(f"Game data it changes: {shown}{', …' if len(data_files) > 6 else ''}.")


def check_package(z: zipfile.ZipFile, where: str, rep: Report) -> None:
    """A RUSE Studio mod: a zip with mod.toml at the top or in one folder."""
    names = [i.filename for i in z.infolist() if not i.is_dir()]
    tomls = [n for n in names if PurePosixPath(n).name == "mod.toml" and n.count("/") <= 1]
    if len(tomls) != 1:
        rep.refused.append(f"`{where}` has {len(tomls)} mod.toml files at its top; a mod has exactly one.")
        return
    top = tomls[0].rsplit("/", 1)[0] + "/" if "/" in tomls[0] else ""
    try:
        meta = tomllib.loads(z.read(tomls[0]).decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        rep.refused.append(f"`{tomls[0]}` can't be read ({exc}).")
        return
    m = meta.get("mod", {}) if isinstance(meta.get("mod"), dict) else {}
    game = meta.get("game", {}) if isinstance(meta.get("game"), dict) else {}
    made = meta.get("made_with", {}) if isinstance(meta.get("made_with"), dict) else {}
    for key in ("id", "name", "version"):
        if not m.get(key):
            rep.refused.append(f"mod.toml has no `{key}`.")
    if m.get("id") and not ID.match(str(m["id"])):
        rep.refused.append(f"The mod's id `{m['id']}` isn't lowercase letters, digits and `-`.")
    if m.get("version") and not VERSION.match(str(m["version"])):
        rep.refused.append(f"The version `{m['version']}` isn't like 1.0.0.")
    rep.facts.update({"Mod": f"{m.get('name', '?')} `{m.get('id', '?')}` {m.get('version', '?')}",
                      "By": ", ".join(map(str, m.get("authors") or [])) or "(not given)",
                      "Game build": ", ".join(map(str, game.get("builds") or [])) or "(not given)",
                      "Made with": f"{made.get('tool', '')} {made.get('version', '')}".strip() or "(not said)"})
    by_folder: dict[str, int] = {}
    for n in names:
        rel = n[len(top):] if n.startswith(top) else n
        by_folder[rel.split("/", 1)[0] if "/" in rel else "(top)"] = by_folder.get(
            rel.split("/", 1)[0] if "/" in rel else "(top)", 0) + 1
    rep.notes.append("Files by folder: " + ", ".join(f"`{k}` {v}" for k, v in sorted(by_folder.items())) + ".")
    rmods = [n for n in names if n.lower().endswith(".rmod")]
    for n in names:
        kinds = suffixes(n)
        if n.lower().endswith(".rmod"):
            continue
        if kinds & RUNNABLE:
            rep.refused.append(f"`{n}` would run on the PC or in the game; RUSE Studio mods can't bring scripts or "
                               f"programs (a .rmod may change the game's own scripts, said in the form).")
        elif kinds & {".zip", ".rusemod", ".7z", ".rar"}:
            rep.refused.append(f"`{n}` is an archive inside the mod; send its contents instead.")
    for n in rmods:
        check_rmod(z.read(n), n, rep)


def check_file(name: str, raw: bytes, rep: Report, index_text: str | None = None) -> None:
    if len(raw) > MAX_FILE:
        rep.refused.append(f"The file is {len(raw) // 1_000_000} MB; the list takes up to {MAX_FILE // 1_000_000} MB.")
        return
    if name.lower().endswith(".rmod"):
        check_rmod(raw, name, rep)
    elif raw[:4] == b"PK\x03\x04":
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            rep.refused.append(f"`{name}` isn't a readable zip.")
            return
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
            rep.refused.append(f"`{name}` holds more than the list takes ({len(infos)} files).")
            return
        bad = [i.filename for i in infos if unsafe_path(i.filename)]
        if bad:
            rep.refused.append(f"`{name}` has a path that leaves its folder: `{bad[0]}`.")
            return
        top_rmods = [i.filename for i in infos if i.filename.lower().endswith(".rmod") and "/" not in i.filename]
        has_toml = any(PurePosixPath(i.filename).name == "mod.toml" for i in infos)
        if not has_toml and len(top_rmods) == 1 and len(infos) == 1:
            check_rmod(z.read(top_rmods[0]), top_rmods[0], rep)
        else:
            check_package(z, name, rep)
    else:
        rep.refused.append(f"`{name}` is neither a RUSE Studio mod (.rusemod / .zip) nor a .rmod.")
        return
    if index_text is not None:
        listed = {str(e.get("id")): str(e.get("version")) for e in tomllib.loads(index_text).get("mod", [])}
        mid = rep.facts.get("Mod", "").split("`")
        mod_id = mid[1] if len(mid) > 2 else None
        if mod_id and mod_id in listed:
            rep.notes.append(f"`{mod_id}` is already on the list (version {listed[mod_id]}): this would be an update.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--index", help="the list (index.toml), to say whether this id is already on it")
    ap.add_argument("--report", help="write the report (Markdown) here too")
    args = ap.parse_args(argv)
    with open(args.file, "rb") as f:
        raw = f.read(MAX_FILE + 1)
    rep = Report()
    index_text = open(args.index, encoding="utf-8").read() if args.index else None
    check_file(args.file.replace("\\", "/").rsplit("/", 1)[-1], raw, rep, index_text)
    text = rep.markdown(args.file.replace("\\", "/").rsplit("/", 1)[-1])
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return rep.code()


if __name__ == "__main__":
    sys.exit(main())
