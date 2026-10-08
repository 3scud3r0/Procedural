"""Rebuild source ZIP, consolidated TXT and SHA-256 receipt without recursion."""

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "downloads"


def package():
    OUT.mkdir(exist_ok=True)
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    paths = sorted(
        {
            name
            for name in paths
            if name and not name.startswith("downloads/") and (ROOT / name).is_file()
        }
    )
    source_paths = [p for p in paths if Path(p).suffix in (".py", ".proc")]
    records = []
    for name in paths:
        data = (ROOT / name).read_bytes()
        records.append(
            {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    receipt = {
        "schema": "procedural.distribution/1",
        "platform_version": "0.1.0",
        "core_version": "1.0.0",
        "source_lines": sum(len((ROOT / p).read_text().splitlines()) for p in source_paths),
        "source_files": len(source_paths),
        "files": records,
    }
    text = OUT / "codigo_completo.txt"
    with text.open("w") as stream:
        stream.write("PROCEDURAL LAB 0.1.0 — SOURCES AND DOCUMENTATION\n")
        for name in paths:
            if Path(name).suffix in (".py", ".proc", ".md", ".json", ".toml", ".yml"):
                stream.write("\n" + "=" * 72 + "\nFILE: " + name + "\n" + "=" * 72 + "\n")
                stream.write((ROOT / name).read_text() + "\n")
    text.write_text(text.read_text().rstrip() + "\n")
    archive = OUT / "Procedural_Lab_0.1.0.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zip:
        for name in paths:
            zip.write(ROOT / name, "Procedural/" + name)
        zip.write(text, "Procedural/codigo_completo.txt")
        zip.writestr("Procedural/distribution.json", json.dumps(receipt, indent=2))
    with zipfile.ZipFile(archive) as zip:
        assert zip.testzip() is None
        for record in records:
            assert (
                hashlib.sha256(zip.read("Procedural/" + record["path"])).hexdigest()
                == record["sha256"]
            )
    for name in [archive, text]:
        data = name.read_bytes()
        receipt.setdefault("downloads", []).append(
            {"path": name.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    (OUT / "distribution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {key: receipt[key] for key in ("source_lines", "source_files", "downloads")}, indent=2
        )
    )


if __name__ == "__main__":
    package()
