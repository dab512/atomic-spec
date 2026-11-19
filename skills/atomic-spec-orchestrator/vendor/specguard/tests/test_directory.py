"""Explicit directory input stays bounded and uses the selected specification namespace."""

from pathlib import Path
from unittest.mock import patch
import contextlib
import io
import json
import tempfile
import unittest

from test_detector import write_test_registry

from test_detector import guard, SPEC, NODE, MODULES


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
# Выбор каталога детерминирован, ограничен и не следует по symlink или кешам.
class DirectoryTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Результат для каталога должен определяться его действительными файлами и требованиями, а не заранее заданным ответом адаптера.
    def invoke(self, root, command="audit", *extra):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = guard.main(
                [
                    command,
                    "--root",
                    str(root),
                    "--node",
                    NODE,
                    "--node-modules",
                    MODULES,
                    "--json",
                    *extra,
                ]
            )
        return (
            code,
            json.loads(output.getvalue()) if output.getvalue() else {},
            errors.getvalue(),
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-13
    # Каталог проверяемого кода не ограничивает каталог авторитетных требований: источник выбирается отдельно и явно.
    def fixture(self, root):
        spec = root / SPEC.split("#")[0]
        spec.parent.mkdir(parents=True)
        spec.write_text("---\nid: TEST\nstatus: review\n---\n### DR-2. Rule\nMeaning.\n")
        write_test_registry(root, SPEC.split("#")[0])
        return "# atomic-spec://TEST/DR-2\n# Meaning.\ndef work():\n    return 1\n"

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Вложенные поддерживаемые файлы включаются и явно перечисляются в отчёте.
    def test_recursive_directory_collects_nested_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = self.fixture(root)
            (root / "src/nested").mkdir(parents=True)
            (root / "src/a.py").write_text(source)
            (root / "src/nested/b.py").write_text(source)
            code, report, error = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(code, 0, error)
            self.assertEqual(report["input_files"], ["src/a.py", "src/nested/b.py"])
            self.assertEqual(report["scope_kind"], "directory")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Внешняя ссылка и деревья зависимостей либо кешей отмечаются пропусками и не разбираются.
    def test_symlinks_and_caches_are_not_followed(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(folder)
            source = self.fixture(root)
            (root / "src/node_modules").mkdir(parents=True)
            (root / "src/.venv").mkdir()
            (root / "src/a.py").write_text(source)
            (root / "src/node_modules/bad.py").write_text("broken !!!")
            (root / "src/.venv/bad.py").write_text("broken !!!")
            (Path(outside) / "bad.py").write_text("broken !!!")
            (root / "src/link").symlink_to(outside, target_is_directory=True)
            code, report, error = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(code, 0, error)
            self.assertEqual(report["input_files"], ["src/a.py"])
            self.assertTrue(any("symlink" in x["reason"] for x in report["excluded"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Превышение файлового бюджета не позволяет выдать частичный обход за полный успешный аудит.
    def test_file_limit_is_failure_not_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src").mkdir()
            for i in range(3):
                (root / f"src/{i}.py").write_text("value=1\n")
            with patch.object(guard, "DIRECTORY_MAX_FILES", 2):
                code, _, error = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(code, 2)
            self.assertIn("file limit", error)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Обход рабочей папки не выдаётся за неизменяемый ревизионный diff.
    def test_directory_is_exclusive_with_file_or_revision_input(self):
        with tempfile.TemporaryDirectory() as folder:
            for extra in [
                ["--files", "a.py"],
                ["--base", "HEAD"],
                ["--revision", "rev"],
            ]:
                code, _, error = self.invoke(Path(folder), "audit", "--directory", "src", *extra)
                self.assertEqual(code, 2)
                self.assertIn("--directory", error)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-13
    # Один ID разрешается только в выбранном spec-root; другой каталог не восполняет отсутствующий пункт.
    def test_explicit_spec_root_selects_independent_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, number, meaning in [
                ("alpha", 1, "Alpha requirement"),
                ("beta", 2, "Beta requirement"),
            ]:
                directory = root / "requirements" / name
                directory.mkdir(parents=True)
                relative = f"requirements/{name}/rule.spec.md"
                (directory / "rule.spec.md").write_text(
                    f"---\nid: ROOT-TEST-001\nstatus: review\n---\n### DR-{number}. Rule\n{meaning}.\n"
                )
                (directory / "registry.json").write_text(json.dumps({"ROOT-TEST-001": relative}))
            (root / "src").mkdir()
            (root / "src/a.py").write_text(
                "# atomic-spec://ROOT-TEST-001/DR-1\n# Apply the selected requirement.\ndef work(): pass\n"
            )
            code, report, error = self.invoke(
                root,
                "getcontext",
                "--directory",
                "src",
                "--spec-root",
                "requirements/alpha",
            )
            self.assertEqual(code, 0, error)
            self.assertIn("Alpha requirement", report["requirements"][0]["text"])
            code, _, _ = self.invoke(
                root,
                "getcontext",
                "--directory",
                "src",
                "--spec-root",
                "requirements/beta",
            )
            self.assertEqual(code, 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Лимиты записей и байтов прерывают работу до выдачи полного результата.
    def test_entry_and_source_budgets_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src/a.py").write_text("value=1\n")
            for field, limit, expected in [
                ("DIRECTORY_MAX_ENTRIES", 0, "entry limit"),
                ("DIRECTORY_MAX_BYTES", 1, "byte limit"),
            ]:
                with patch.object(guard, field, limit):
                    code, _, error = self.invoke(root, "audit", "--directory", "src")
                self.assertEqual(code, 2)
                self.assertIn(expected, error)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-21
    # Каталог без поддерживаемых исходников образует явную пустую выборку.
    def test_empty_directory_has_empty_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            code, report, error = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(code, 0, error)
            self.assertEqual(report["input_files"], [])
