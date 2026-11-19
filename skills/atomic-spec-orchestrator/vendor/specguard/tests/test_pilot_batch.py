"""Independent corpus runs preserve input bytes and do not reuse the first pilot's claims."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_detector import GO_PARSER, MODULES, NODE, P


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
# Выводы пилота относятся только к явно выбранным исходникам; соседнее дерево не расширяет доказательства качества.
class PilotBatchTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Новый корпус воспроизводим и не изменяет исходные файлы.
    def test_new_corpus_is_reproducible_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = {"a.py": "LIMIT = 6\n", "b.py": "def work():\n    return 1\n"}
            for name, text in inputs.items():
                (root / name).write_text(text)
            manifest, output = root / "manifest.json", root / "report"
            args = [
                sys.executable,
                str(P / "pilot/run_comparison.py"),
                "--root",
                str(root),
                "--go-parser",
                GO_PARSER,
                "--node",
                NODE,
                "--node-modules",
                MODULES,
                "--manifest",
                str(manifest),
                "--output-dir",
                str(output),
                "--new-corpus",
            ]
            result = subprocess.run(
                args + ["--record-files", *inputs],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "comparison.json").read_text())
            self.assertEqual(report["files"], 2)
            self.assertTrue(report["source_bytes_unchanged"])
            self.assertEqual(report["overlap_with_first_batch"], [])
            self.assertEqual(report["profiles"]["strict"]["severity"], {"error": 1, "warning": 1})
            for name, text in inputs.items():
                self.assertEqual((root / name).read_text(), text)
            repeated = subprocess.run(args, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertTrue((output / "diagnostics.md").exists())

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Изменённый замороженный корпус не может подтверждать прежние результаты и не даёт права перезаписать эталон.
    def test_changed_frozen_input_is_rejected_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "a.py"
            source.write_text("LIMIT = 6\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([{"file": "a.py", "bytes": 10, "sha256": "0" * 64}]))
            result = subprocess.run(
                [
                    sys.executable,
                    str(P / "pilot/run_comparison.py"),
                    "--root",
                    str(root),
                    "--go-parser",
                    GO_PARSER,
                    "--node",
                    NODE,
                    "--node-modules",
                    MODULES,
                    "--manifest",
                    str(manifest),
                    "--output-dir",
                    str(root / "report"),
                    "--new-corpus",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pilot input changed", result.stderr)
            self.assertEqual(source.read_text(), "LIMIT = 6\n")
