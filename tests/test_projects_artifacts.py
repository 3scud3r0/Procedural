from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from procedural_lab.project import Project
from procedural_lab.artifacts import ArtifactStore, verify_run
from procedural_lab.geometry import Scene, svg, png
from procedural_lab.runner import execute_project, run_isolated
from procedural_lab.vm import Limits

ROOT = Path(__file__).resolve().parents[1]


class ProjectArtifactTests(unittest.TestCase):
    def test_project_validation_rejects_traversal_ambiguous_modules_and_reserved_names(self):
        for files in [
            {"../main.proc": "pass"},
            {"main.proc": "pass", "main.py": "pass"},
            {"main.proc": "pass", "math.proc": "pass"},
            {"/main.proc": "pass"},
            {},
        ]:
            with self.assertRaises(ValueError):
                Project(files).validate()
        project = Project(
            {
                "main.proc": "from tools.maths import value\nprint(value)",
                "tools/maths.proc": "value=42",
            }
        )
        self.assertTrue(execute_project(project, preview=False)["ok"])

    def test_json_project_and_sibling_modules_load_without_external_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "main.proc").write_text("from helper import answer\nprint(answer)")
            (root / "helper.proc").write_text("answer=42")
            p = Project.load(root / "main.proc")
            self.assertEqual(len(p.files), 2)
            (root / "project.json").write_text(json.dumps(p.to_dict()))
            self.assertEqual(Project.load(root / "project.json").to_dict(), p.to_dict())

    def test_source_symlink_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "project").mkdir()
            (root / "external.proc").write_text("pass")
            (root / "project" / "main.proc").write_text("pass")
            (root / "project" / "helper.proc").symlink_to(root / "external.proc")
            with self.assertRaises(ValueError):
                Project.load(root / "project" / "main.proc")

    def test_atomic_publication_manifest_tamper_detection_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "run"
            store = ArtifactStore()
            store.emit("nested/result.json", {"answer": 42})
            store.emit("binary.bin", b"\x00\xff")
            store.publish(target, {"seed": 42})
            self.assertEqual(len(verify_run(target)["artifacts"]), 2)
            with self.assertRaises(FileExistsError):
                store.publish(target, {})
            (target / "binary.bin").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_run(target)

    def test_bad_artifacts_are_rejected_without_writing(self):
        store = ArtifactStore(max_files=2, max_bytes=10)
        for name in ("../outside", "/tmp/outside", "."):
            with self.assertRaises(ValueError):
                store.emit(name, "x")
        store.emit("valid", "x")
        with self.assertRaises(ValueError):
            store.emit("valid", "y")
        with self.assertRaises(ValueError):
            store.emit("huge", "x" * 20)
        self.assertEqual(store.files, {"valid": b"x"})

    def test_png_has_valid_chunks_crc_dimensions_and_pixel_data(self):
        scene = Scene()
        scene.box(size=[1, 3, 1], name="<script>")
        scene.sphere(position=[2, 1, 0])
        scene.line([[0, 0, 0], [3, 0, 0]])
        data = png(scene.to_dict(), 128, 96)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        cursor = 8
        compressed = b""
        while cursor < len(data):
            length = struct.unpack(">I", data[cursor : cursor + 4])[0]
            kind = data[cursor + 4 : cursor + 8]
            chunk = data[cursor + 8 : cursor + 8 + length]
            crc = struct.unpack(">I", data[cursor + 8 + length : cursor + 12 + length])[0]
            self.assertEqual(zlib.crc32(kind + chunk) & 0xFFFFFFFF, crc)
            if kind == b"IHDR":
                self.assertEqual(struct.unpack(">II", chunk[:8]), (128, 96))
            if kind == b"IDAT":
                compressed += chunk
            cursor += length + 12
        self.assertEqual(len(zlib.decompress(compressed)), 96 * (1 + 128 * 3))
        self.assertIn(b"&lt;script&gt;", svg(scene.to_dict()))
        self.assertNotIn(b"<script>", svg(scene.to_dict()))

    def test_all_pcl_examples_compile_and_execute(self):
        for path in sorted((ROOT / "examples").glob("*/main.proc")):
            with self.subTest(example=path.parent.name):
                result = execute_project(Project.load(path), preview=False)
                self.assertTrue(result["ok"], result)

    def test_worker_success_and_instruction_failure(self):
        result = run_isolated(Project({"main.proc": "print(42)"}), preview=False)
        self.assertTrue(result["ok"], result)
        result = run_isolated(
            Project({"main.proc": "while True:\n    pass"}), Limits(steps=20), preview=False
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "STEP_LIMIT")

    def test_wall_limit_terminates_worker_before_it_can_publish(self):
        result = run_isolated(
            Project({"main.proc": "while True:\n    pass"}),
            Limits(steps=10**12, seconds=10),
            preview=False,
            wall_seconds=0.05,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "WALL_LIMIT")
        self.assertEqual(result["files"], {})

    def test_cli_exit_codes_and_artifact_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "main.proc"
            source.write_text('print(42)\nemit("answer.txt","42")')
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "procedural_lab",
                    "run",
                    str(source),
                    "--output",
                    str(root / "out"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("42", result.stdout)
            verify_run(root / "out")
            source.write_text("1/0")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "procedural_lab",
                    "run",
                    str(source),
                    "--output",
                    str(root / "bad"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / "bad").exists())
