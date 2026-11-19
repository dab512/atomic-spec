"""Spec explanations remain reviewable with their authoritative requirement context."""

from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import patch

from test_detector import guard
import test_policy

import test_reverse_and_links as reverse

URI = reverse.URI


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
# Ревью должно видеть каждую физическую разметку, включая ошибочную, без строковых имитаций.
class CommentsTests(unittest.TestCase):
    fixture = reverse.ReverseTests.fixture
    invoke = reverse.ReverseTests.invoke

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Несколько владельцев не размножают один комментарий, а файловое пояснение не теряется.
    def test_comments_all_adapters_and_file_group(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            (root / "a.py").write_text(
                f"# {URI}\n# File obligation.\n\n# ordinary comment\n"
                f"# {URI}\n# Business invariant.\ndef first():\n    return 1\n"
                f'fake = "{URI}"\n'
            )
            (root / "settings.yaml").write_text(f"# {URI}\n# Configuration invariant.\nlimit: 3\n")
            files.append("settings.yaml")
            code, report = self.invoke(root, "comments", files=files)
            self.assertEqual(code, 0)
            self.assertEqual(len(report["comments"]), 5)
            first = report["comments"][0]
            self.assertEqual((first["file"], first["line"], first["end_line"]), ("a.py", 1, 2))
            self.assertEqual(first["description"], "File obligation.")
            self.assertIn("Actual rule.", report["requirements"][0]["text"])
            self.assertEqual(report["comments"][1]["owners"][0]["block"], "first")
            self.assertEqual(report["comments"][1]["refs"], [URI])
            self.assertIn("Business invariant.", report["comments"][1]["source"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Ошибочная разметка остаётся доступной для исправления и не превращается в успешную выгрузку.
    def test_invalid_and_empty_explanations_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text(
                f"# {URI}\ndef first():\n    pass\n\n"
                "# atomic-spec://SKSTORE-TRACE-001/DR-999\n# Unknown rule.\ndef second():\n    pass\n"
            )
            code, report = self.invoke(root, "comments", files=["a.py"])
            self.assertEqual(code, 1)
            self.assertEqual(len(report["comments"]), 2)
            self.assertEqual(report["comments"][0]["description"], "")
            self.assertTrue(any(d["code"] == "SPEC004" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Пакет для агента сохраняет текст пояснения и требования вместе с точной локацией.
    def test_directory_and_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "src/nested").mkdir(parents=True)
            (root / "src/nested/a.py").write_text(
                f"# {URI}\n# Publication must not duplicate PRs.\ndef work():\n    pass\n"
            )
            code, report = self.invoke(root, "comments", "--directory", "src")
            self.assertEqual(code, 0)
            self.assertEqual(report["scope_kind"], "directory")
            self.assertEqual(len(report["comments"]), 1)
            code, text = self.invoke(root, "comments", "--directory", "src", raw=True)
            self.assertEqual(code, 0)
            self.assertIn("Publication must not duplicate PRs.", text)
            self.assertIn("Actual rule.", text)
            self.assertIn("src/nested/a.py:1", text)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Невалидное файловое пояснение нельзя скрыть отсутствием владельца или исполнением только успешных блоков.
    def test_file_group_failure_and_partial_parse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text("# atomic-spec://SKSTORE-TRACE-001/DR-999\n# Unknown obligation.\n\nvalue = 1\n")
            (root / "broken.py").write_text("def broken(:\n")
            code, report = self.invoke(root, "comments", files=["a.py", "broken.py"])
            self.assertEqual(code, 1)
            self.assertFalse(report["complete"])
            self.assertEqual(len(report["comments"]), 1)
            self.assertEqual({d["code"] for d in report["diagnostics"]}, {"SPEC004", "SPEC008"})

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Ревизионная выгрузка ограничена изменённым правилом, а full сохраняет целый авторитетный документ.
    def test_diff_and_full_document(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            old = f"# {URI}\n# First invariant.\ndef first():\n    return 1\n\n# {URI}\n# Second invariant.\ndef second():\n    return 2\n"
            new = old.replace("return 1", "return 3")
            original_read = guard.Repository.read

            def read(repo, path, revision=None):
                if path == "a.py":
                    return old if revision == "base" else new
                return original_read(repo, path, None)

            with (
                patch.object(guard.Repository, "read", read),
                patch.object(guard, "command", return_value="M\ta.py\n"),
            ):
                code, report = self.invoke(root, "comments", "full", "--base", "base", "--revision", "review")
            self.assertEqual(code, 0)
            self.assertEqual(report["revision"], "review")
            self.assertEqual([c["description"] for c in report["comments"]], ["First invariant."])
            self.assertIn("Other rule.", report["documents"][0]["text"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-26
    # Конфиг не должен исключать ошибочные пояснения из пакета ревью; файл с явным исключением отмечается отдельно.
    def test_configured_export_and_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            config = root / "policy.json"
            policy = test_policy.CONFIG
            config.write_text(json.dumps(policy))
            (root / "a.py").write_text(f"# {URI}\n# Business invariant.\ndef first():\n    return 1\n")
            (root / "note.txt").write_text("unsupported")
            code, report = self.invoke(root, "comments", "--config", "policy.json", files=["a.py", "note.txt"])
            self.assertEqual(code, 0)
            self.assertEqual(len(report["comments"]), 1)
            self.assertTrue(any(x["file"] == "note.txt" for x in report["excluded"]))
