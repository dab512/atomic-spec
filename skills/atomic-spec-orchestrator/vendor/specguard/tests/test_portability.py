"""Exercise the public CLI in an unrelated Git checkout, without application services."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_detector import GO_PARSER, MODULES, NODE, P, guard


# atomic-spec://ATOMIC-GUARD-001/DR-13
# Независимый проект выбирает свой реестр и исходники без скрытого пути приложения-донора.
class PortabilityTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-13
    # Проверка рабочего снимка должна разрешать требования в стандартном каталоге нового проекта.
    def test_default_spec_root_in_unrelated_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "specs").mkdir()
            (root / "specs/registry.json").write_text(json.dumps({"DEMO": "specs/demo.spec.md"}))
            (root / "specs/demo.spec.md").write_text(
                "---\nid: DEMO\nstatus: review\n---\n### DR-1. Rule\nReturn a stable value.\n"
            )
            (root / "sample.py").write_text(
                "# atomic-spec://DEMO/DR-1\n# Return the agreed value.\ndef sample():\n    return 1\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(P / "specguard.py"),
                    "audit",
                    "--root",
                    str(root),
                    "--files",
                    "sample.py",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)["spec_root"], "specs")

    # atomic-spec://ATOMIC-GUARD-001/DR-5
    # Полный контекст не зависит от порядка именованных аргументов на поддерживаемых версиях Python.
    def test_full_mode_after_named_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "specs").mkdir()
            (root / "specs/registry.json").write_text(json.dumps({"DEMO": "specs/demo.spec.md"}))
            (root / "specs/demo.spec.md").write_text(
                "---\nid: DEMO\nstatus: review\n---\n### DR-1. Rule\nReturn a stable value.\n"
            )
            (root / "sample.py").write_text(
                "# atomic-spec://DEMO/DR-1\n# Return the agreed value.\ndef sample():\n    return 1\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(P / "specguard.py"),
                    "getcontext",
                    "--root",
                    str(root),
                    "full",
                    "--files",
                    "sample.py",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)["documents"][0]["path"], "specs/demo.spec.md")

    # atomic-spec://ATOMIC-GUARD-001/DR-18
    # Общий diff должен находить изменённый исходник за пределами каталогов прежнего приложения.
    def test_default_diff_scope_catches_unannotated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            env = dict(
                os.environ,
                GIT_AUTHOR_NAME="Test",
                GIT_AUTHOR_EMAIL="test@example.invalid",
                GIT_COMMITTER_NAME="Test",
                GIT_COMMITTER_EMAIL="test@example.invalid",
            )
            subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "fixture"], cwd=root, env=env, check=True)
            (root / "sample.py").write_text("def sample():\n    return 1\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(P / "specguard.py"),
                    "check",
                    "--root",
                    str(root),
                    "--base",
                    "HEAD",
                    "--working-tree",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)["input_files"], ["sample.py"])

    # atomic-spec://ATOMIC-GUARD-001/DR-11
    # Исторические локации принадлежат выбранному репозиторию, а не фиксированному проекту-донору.
    def test_revision_links_use_explicit_repository(self):
        revision = "a" * 40
        report = {
            "revision": revision,
            "source_root": "/checkout",
            "repository_url": "https://github.com/example/project",
        }
        link = guard.location_link(report, {"file": "src/a b.py", "line": 4})
        self.assertIn(f"https://github.com/example/project/blob/{revision}/src/a%20b.py#L4", link)

    # atomic-spec://ATOMIC-GUARD-001/DR-11
    # Без адреса хранилища отчёт не должен придумывать удалённую ссылку на чужой код.
    def test_revision_without_repository_never_invents_remote(self):
        report = {"revision": "a" * 40, "source_root": "/checkout"}
        link = guard.location_link(report, {"file": "src/a.py", "line": 4})
        self.assertNotIn("https://", link)
        self.assertIn(report["revision"], link)


# atomic-spec://ATOMIC-GUARD-001/DR-27
# Публичный пример обязан работать вне дерева Guard и обнаруживать повреждение требований.
class ExampleTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-16
    # Каждый публичный режим использует настоящие парсеры и одну политику нового проекта.
    def invoke(self, root, command, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(P / "specguard.py"),
                command,
                "--root",
                str(root),
                "--config",
                "specs/atomic-spec-guard.yaml",
                "--go-parser",
                GO_PARSER,
                "--node",
                NODE,
                "--node-modules",
                MODULES,
                "--json",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-27
    # Установка не требует сервисов донора: четыре языка анализируются в изолированной копии примера.
    def test_documented_commands_and_invalid_reference_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(P / "examples/minimal", root)
            for command in ["audit", "getcontext", "comments", "whereused"]:
                with self.subTest(command=command):
                    extra = ["--spec", "atomic-spec://DEMO-FARE/DR-1"] if command == "whereused" else []
                    result = self.invoke(root, command, "--directory", "src", *extra)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    report = json.loads(result.stdout)
                    self.assertTrue(report["complete"])
                    self.assertEqual(
                        set(report["input_files"]), {"src/fare.py", "src/fare.go", "src/fare.ts", "src/fare.yaml"}
                    )
                    if command == "whereused":
                        locations = {loc["file"] for req in report["requirements"] for loc in req["locations"]}
                        self.assertEqual(locations, set(report["input_files"]))
            path = root / "src/fare.py"
            original = path.read_text()
            path.write_text(original.replace("/DR-1", "/DR-99999"))
            result = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertTrue(any(d["code"] == "SPEC004" for d in json.loads(result.stdout)["diagnostics"]))
            path.write_text(original)
            result = self.invoke(root, "audit", "--directory", "src")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://ATOMIC-GUARD-001/DR-8
    # Отсутствующий YAML-парсер и повреждённый конфиг должны завершать пример ошибкой, а не частичным PASS.
    def test_missing_dependency_and_invalid_policy_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(P / "examples/minimal", root)
            missing = self.invoke(root, "audit", "--files", "src/fare.py", "--node", str(root / "missing-node"))
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
            policy = root / "specs/atomic-spec-guard.yaml"
            policy.write_text(policy.read_text() + "\nunknown_setting: true\n")
            invalid = self.invoke(root, "audit", "--files", "src/fare.py")
            self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)

    # atomic-spec://ATOMIC-GUARD-001/DR-5
    # Зафиксированный Git diff читает исходник, требования и политику из указанной ревизии вопреки новым рабочим байтам.
    def test_real_git_revision_uses_its_own_policy_and_specification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(P / "examples/minimal", root)
            env = dict(
                os.environ,
                GIT_AUTHOR_NAME="Test",
                GIT_AUTHOR_EMAIL="test@example.invalid",
                GIT_COMMITTER_NAME="Test",
                GIT_COMMITTER_EMAIL="test@example.invalid",
            )
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=root, env=env, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source = root / "src/fare.py"
            source.write_text(source.read_text().replace("/DR-1", "/DR-99999"))
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "invalid reference"], cwd=root, env=env, check=True)
            source.write_text(source.read_text().replace("/DR-99999", "/DR-1"))
            (root / "specs/registry.json").write_text("{}")
            result = self.invoke(root, "check", "--base", base, "--revision", "HEAD")
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["input_files"], ["src/fare.py"])
            self.assertTrue(any(d["code"] == "SPEC004" for d in report["diagnostics"]))


# atomic-spec://ATOMIC-GUARD-001/DR-6
# Прямой запуск регрессии обязан вернуть ненулевой статус при любом нарушении переносимости.
if __name__ == "__main__":
    unittest.main()
