"""Проверяем устойчивый файловый кеш и обязательную инвалидизацию через настоящий CLI."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import contextlib
import io
import json
import tempfile
import unittest

from test_detector import guard, NODE, MODULES, P


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Кеш не должен скрывать новые нарушения исходника, политики, реестра или текста требования.
class ResultCacheTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Сохранённый результат можно использовать лишь для тех же исходников, политики и авторитетного источника требований.
    def fixture(self, root):
        config = P / "tests/fixtures/sample-policy.yaml"
        (root / "policy.yaml").write_bytes(config.read_bytes())
        directory = root / guard.DEFAULT_SPEC_ROOT
        directory.mkdir(parents=True)
        path = guard.DEFAULT_SPEC_ROOT + "/cache.spec.md"
        (directory / "cache.spec.md").write_text(
            "---\nid: CACHE-TEST-001\nstatus: review\n---\n### DR-1. Публикация\nПеред публикацией требуется свободное место.\n"
        )
        (directory / "registry.json").write_text(json.dumps({"CACHE-TEST-001": path}))
        for name in ["a.py", "b.py"]:
            (root / name).write_text(
                "# atomic-spec://CACHE-TEST-001/DR-1\n# Резервируем место перед публикацией.\ndef work(): return 1\n"
            )
        return directory

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Переиспользованный результат обязан сохранять область и диагностики действительной проверки, а не подменять их прежним окружением.
    def invoke(self, root, *extra, files=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = guard.main(
                [
                    "audit",
                    "--root",
                    str(root),
                    "--config",
                    "policy.yaml",
                    "--node",
                    NODE,
                    "--node-modules",
                    MODULES,
                    "--cache-dir",
                    str(root / "cache"),
                    "--json",
                    *extra,
                    "--files",
                    *(files if files is not None else ["a.py", "b.py"]),
                ]
            )
        return code, json.loads(output.getvalue())

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # После первого расчёта оба файла попадают в кеш; изменение одного не сбрасывает независимый второй.
    def test_hits_and_one_changed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            code, report = self.invoke(root)
            self.assertEqual(code, 0)
            self.assertEqual(report["cache"]["misses"], 2)
            code, report = self.invoke(root)
            self.assertEqual(code, 0)
            self.assertEqual(report["cache"]["hits"], 2)
            with (root / "a.py").open("a") as stream:
                stream.write("\ndef unannotated(): pass\n")
            code, report = self.invoke(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["cache"]["hits"], 1)
            self.assertEqual(report["cache"]["misses"], 1)
            self.assertTrue(any(d["code"] == "SPEC_COVER" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Даже изменение комментария YAML сбрасывает прежние записи, а не только смена семантики правил.
    def test_any_yaml_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.invoke(root)
            policy = root / "policy.yaml"
            policy.write_text("# обновлён конфиг\n" + policy.read_text())
            code, report = self.invoke(root)
            self.assertEqual(code, 0)
            self.assertEqual(report["cache"]["hits"], 0)
            self.assertEqual(report["cache"]["misses"], 2)

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Изменение спеки или реестра заставляет заново проверить существование пункта и не сохраняет старый PASS.
    def test_specification_and_registry_invalidate_results(self):
        for target in ["cache.spec.md", "registry.json"]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                directory = self.fixture(root)
                self.invoke(root)
                path = directory / target
                if target.endswith(".md"):
                    path.write_text(path.read_text().replace("### DR-1.", "### DR-2."))
                else:
                    path.write_text("{}")
                code, report = self.invoke(root)
                self.assertEqual(code, 1)
                self.assertEqual(report["cache"]["hits"], 0)
                self.assertTrue(any(d["code"] == "SPEC004" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Повреждённая запись пересчитывается, а явный no-cache обходит даже исправные сохранённые результаты.
    def test_corruption_and_explicit_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.invoke(root)
            for path in (root / "cache").iterdir():
                if path.suffix == ".json":
                    path.write_text("{}")
            code, report = self.invoke(root)
            self.assertEqual(code, 0)
            self.assertEqual(report["cache"]["hits"], 0)
            code, report = self.invoke(root, "--no-cache")
            self.assertEqual(code, 0)
            self.assertNotIn("cache", report)

    # atomic-spec://ATOMIC-GUARD-001/DR-1
    # Неподдерживаемые и исключённые файлы не могут блокировать допуск из-за своих байтов, независимо от кеша.
    def test_binary_and_policy_exclusions_are_never_read(self):
        for name in ["image.png", "pnpm-lock.yaml", "excluded.py"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root)
                (root / name).write_bytes(b"\x89PNG\r\n\x1a\n\xff")
                if name == "excluded.py":
                    policy = root / "policy.yaml"
                    config = json.loads(
                        guard.policy_document(
                            SimpleNamespace(node=NODE, node_modules=MODULES), "policy.yaml", policy.read_text()
                        )
                    )
                    config["files"]["exclusions"].append(dict(id="review-binary", path=name, reason="excluded fixture"))
                    policy.write_text(json.dumps(config))
                original = guard.Repository.read

                def read(repo, path, revision=None):
                    self.assertNotEqual(path, name, "excluded file reached text reader")
                    return original(repo, path, revision)

                with patch.object(guard.Repository, "read", read):
                    for files in [[name], ["a.py", name, "b.py"]]:
                        plain_code, plain = self.invoke(root, "--no-cache", files=files)
                        for _ in range(2):
                            code, cached = self.invoke(root, files=files)
                            self.assertEqual(code, plain_code)
                            self.assertEqual(code, 0)
                            for field in ["excluded", "diagnostics", "requirements", "files"]:
                                self.assertEqual(cached[field], plain[field], field)
                            self.assertNotIn(name, {x["file"] for x in cached["files"]})

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Изменение исключений отменяет прежний допуск и не позволяет кешу скрыть ставший обязательным исходник.
    def test_exclusion_change_rechecks_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text("def missing(): pass\n")
            policy = root / "policy.yaml"
            original = policy.read_text()
            config = json.loads(
                guard.policy_document(SimpleNamespace(node=NODE, node_modules=MODULES), "policy.yaml", original)
            )
            config["files"]["exclusions"].append(
                dict(id="review-ignore", path="a.py", reason="temporary fixture exclusion")
            )
            policy.write_text(json.dumps(config))
            code, report = self.invoke(root)
            self.assertEqual(code, 0)
            self.assertTrue(any(x["file"] == "a.py" for x in report["excluded"]))
            policy.write_text(original)
            code, report = self.invoke(root)
            self.assertEqual(code, 1)
            self.assertTrue(any(x["file"] == "a.py" for x in report["diagnostics"] if x["severity"] == "error"))

    # atomic-spec://ATOMIC-GUARD-001/DR-1
    # Настоящие бинарные данные вне области анализа не должны менять код завершения при включении кеша.
    def test_real_binary_png_matches_uncached_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff")
            expected_code, expected = self.invoke(root, "--no-cache", files=["image.png"])
            code, actual = self.invoke(root, files=["image.png"])
            self.assertEqual(expected_code, 0)
            self.assertEqual(code, expected_code)
            self.assertEqual(actual["excluded"], expected["excluded"])
            self.assertEqual(actual["diagnostics"], expected["diagnostics"])
            self.assertEqual(actual["cache"]["stored"], 0)

    # atomic-spec://ATOMIC-GUARD-001/DR-1
    # Исключённый файл не требует чтения ни текущей, ни базовой ревизии, даже если сам файл недоступен.
    def test_excluded_base_revision_and_missing_file_are_not_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            original = guard.Repository.read
            original_command = guard.command

            def read(repo, path, revision=None):
                self.assertNotEqual(path, "missing.png")
                return original(repo, path, None)

            def command(args, cwd, data=None):
                if args[:4] == ["git", "-c", "core.quotePath=false", "diff"]:
                    return "M\tmissing.png\n"
                return original_command(args, cwd, data)

            with patch.object(guard.Repository, "read", read), patch.object(guard, "command", command):
                code, report = self.invoke(root, "--base", "base", "--revision", "review", files=["missing.png"])
            self.assertEqual(code, 0)
            self.assertEqual(report["excluded"][0]["file"], "missing.png")
            self.assertEqual(report["cache"]["misses"], 0)

    # atomic-spec://ATOMIC-GUARD-001/DR-24
    # Разные записи пути к одному исходнику не должны скрывать его нарушения при сборке кешированного отчёта.
    def test_path_alias_cannot_drop_source_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text("def missing(): pass\n")
            expected_code, expected = self.invoke(root, "--no-cache", files=["./a.py", "b.py"])
            for _ in range(2):
                code, report = self.invoke(root, files=["./a.py", "b.py"])
                self.assertEqual(expected_code, 1)
                self.assertEqual(code, expected_code)
                self.assertEqual(report["diagnostics"], expected["diagnostics"])
