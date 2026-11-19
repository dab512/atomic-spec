"""Dogfood the real checker on its explicit source manifest and private specification root."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

from test_detector import GO_PARSER, MODULES, NODE, P


# atomic-spec://ATOMIC-GUARD-001/DR-20
# Самопроверка должна отклонять испорченную аннотацию и сохранять все места использования требований.
class SelfGuardTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-27
    # Распакованная поставка проверяет себя без родительского Git-репозитория и без путей приложения.
    def test_unpacked_distribution_selfcheck_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            env = dict(os.environ, SPECGUARD_GO_PARSER=GO_PARSER, SPECGUARD_NODE=NODE, SPECGUARD_NODE_MODULES=MODULES)
            result = subprocess.run(
                [os.environ.get("SPECGUARD_PYTHON", "python3"), str(root / "selfcheck.py"), "--json"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(json.loads(result.stdout)["complete"])

    # atomic-spec://ATOMIC-GUARD-001/DR-20
    # Самопроверка ограничена объявленными исходниками; изолированная проверка дефекта не должна менять рабочую копию проекта.
    def fixture(self, directory):
        root = Path(directory)
        files = json.loads((P / "spec/source-files.json").read_text())
        files += [
            "spec/guard.spec.md",
            "spec/registry.json",
            "spec/source-files.json",
        ]
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((P / name).read_bytes())
        return root

    # atomic-spec://ATOMIC-GUARD-001/DR-20
    # Связи собственного кода с требованиями должны проверяться через публичный интерфейс без подмены результата.
    def invoke(self, root, *args):
        env = dict(
            os.environ,
            SPECGUARD_GO_PARSER=GO_PARSER,
            SPECGUARD_NODE=NODE,
            SPECGUARD_NODE_MODULES=MODULES,
        )
        result = subprocess.run(
            [
                os.environ.get("SPECGUARD_PYTHON", "python3"),
                str(P / "selfcheck.py"),
                "--root",
                str(root),
                *args,
                "--json",
            ],
            env=env,
            text=True,
            capture_output=True,
            timeout=40,
        )
        return (
            result.returncode,
            json.loads(result.stdout) if result.stdout else {},
            result.stderr,
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-20
    # Отсутствующий пункт вызывает отказ в изоляции; восстановление исходных байтов возвращает успешную проверку.
    def test_selfcheck_rejects_mutation_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            target = root / "policy.cjs"
            original = target.read_text()
            target.write_text(
                original.replace(
                    "atomic-spec://ATOMIC-GUARD-001/DR-19",
                    "atomic-spec://ATOMIC-GUARD-001/DR-99999",
                    1,
                )
            )
            code, report, error = self.invoke(root)
            self.assertEqual(code, 1, error)
            self.assertTrue(any(x["code"] == "SPEC004" for x in report["diagnostics"]))
            target.write_text(original)
            code, report, error = self.invoke(root)
            self.assertEqual(code, 0, error + str(report.get("summary")))
            self.assertEqual(report["summary"]["error"], 0)
            self.assertTrue(any("unsupported" in x["reason"] for x in report["excluded"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # Собственный реестр разрешает требование и возвращает его настоящие реализации и регрессии.
    def test_self_reverse_trace_includes_implementation_and_regressions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            code, report, error = self.invoke(
                root,
                "whereused",
                "--spec",
                "atomic-spec://ATOMIC-GUARD-001/DR-19",
            )
            self.assertEqual(code, 0, error + str(report.get("summary")))
            locations = {item["file"] for requirement in report["requirements"] for item in requirement["locations"]}
            self.assertIn("policy.cjs", locations)
            self.assertIn(
                "tests/test_yaml_policy.py",
                locations,
            )
