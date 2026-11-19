"""DR-10: deterministic errors block; advisory candidates remain visible."""

import contextlib
import io
import json
import tempfile
import unittest

from test_detector import write_test_registry
from pathlib import Path
from unittest.mock import patch

from test_detector import guard, GO_PARSER, NODE, MODULES, SPEC


# atomic-spec://ATOMIC-GUARD-001/DR-10
# Степень нарушения определяет допуск: предупреждения разрешены, ошибки покрытия или достоверности результата блокируют.
class SeverityTests(unittest.TestCase):
    def run_cli(
        self,
        files,
        command="audit",
        density=100,
        granularity="strict",
        mode="brief",
        raw=False,
    ):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / SPEC.split("#")[0]
            document.parent.mkdir(parents=True)
            document.write_text("---\nid: TEST\nstatus: review\n---\n### DR-2. Actual rule\nMeaning.\n")
            write_test_registry(root, SPEC.split("#")[0])
            for name, text in files.items():
                (root / name).write_text(text)
            output = io.StringIO()
            arguments = [
                command,
                mode,
                "--root",
                str(root),
                "--go-parser",
                GO_PARSER,
                "--node",
                NODE,
                "--node-modules",
                MODULES,
                "--density-lines",
                str(density),
                "--granularity",
                granularity,
                "--files",
                *files,
            ]
            if not raw:
                arguments.append("--json")
            # atomic-spec://ATOMIC-GUARD-001/DR-10
            # Вывод о допуске изменения должен относиться к его действительным байтам; внешний статус VCS не заменяет проверку кода.
            original = guard.Repository.read

            def read(repo, name, revision=None):
                return "" if revision == "base" else original(repo, name)

            with (
                patch.object(
                    guard,
                    "resolve_inputs",
                    return_value=(
                        list(files),
                        None,
                        "base" if command == "check" else None,
                    ),
                ),
                patch.object(guard.Repository, "read", read),
                contextlib.redirect_stdout(output),
            ):
                status = guard.main(arguments)
            return status, output.getvalue() if raw else json.loads(output.getvalue())

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Проверка только с предупреждениями завершается успешно.
    def test_warning_only_check_passes(self):
        status, report = self.run_cli({"a.py": "RETRY_LIMIT = 6\n"}, command="check")
        self.assertEqual(status, 0)
        self.assertTrue(report["complete"])
        self.assertTrue(report["has_warnings"])
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["summary"], {"error": 0, "warning": 1})

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Функция без обязательной аннотации блокирует результат.
    def test_missing_function_blocks(self):
        status, report = self.run_cli({"a.py": "def work():\n    return 1\n"}, command="check")
        self.assertEqual(status, 1)
        self.assertFalse(report["complete"])
        self.assertEqual(report["summary"], {"error": 1, "warning": 0})

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Смешанный отчёт сохраняет ошибки и предупреждения одновременно.
    def test_mixed_diagnostics_keep_both_levels(self):
        status, report = self.run_cli({"a.py": "LIMIT = 6\ndef work():\n    return 1\n"})
        self.assertEqual(status, 1)
        self.assertEqual(report["summary"], {"error": 1, "warning": 1})
        self.assertEqual({d["severity"] for d in report["diagnostics"]}, {"error", "warning"})

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # SQL-кандидат в размеченной функции остаётся предупреждением.
    def test_sql_in_annotated_function_is_warning(self):
        text = '# atomic-spec://TEST/DR-2\n# Execute the selected query.\ndef work(db):\n    db.execute("SELECT 1")\n'
        status, report = self.run_cli({"a.py": text}, command="check")
        self.assertEqual(status, 0)
        self.assertEqual(report["summary"], {"error": 0, "warning": 1})
        self.assertEqual(report["diagnostics"][0]["node_kind"], "SQLQuery")

    # atomic-spec://ATOMIC-GUARD-001/DR-4
    # Невалидная ссылка константы сохраняет уровень ошибки.
    def test_invalid_reference_on_constant_is_error(self):
        text = "# atomic-spec://TEST/DR-99\n# Upper retry bound.\nLIMIT = 6\n"
        status, report = self.run_cli({"a.py": text})
        self.assertEqual(status, 1)
        self.assertEqual(report["diagnostics"][0]["code"], "SPEC004")
        self.assertEqual(report["diagnostics"][0]["severity"], "error")

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # Отсутствие пояснения у ссылки константы не понижается до предупреждения.
    def test_missing_prose_on_constant_is_error(self):
        status, report = self.run_cli({"a.py": "# atomic-spec://TEST/DR-2\nLIMIT = 6\n"})
        self.assertEqual(status, 1)
        self.assertEqual(report["diagnostics"][0]["code"], "SPEC002")
        self.assertEqual(report["diagnostics"][0]["severity"], "error")

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Синтаксический сбой является ошибкой анализа.
    def test_syntax_failure_is_error(self):
        status, report = self.run_cli({"a.py": "def work(:\n"})
        self.assertEqual(status, 1)
        self.assertEqual(report["diagnostics"][0]["code"], "SPEC008")
        self.assertEqual(report["diagnostics"][0]["severity"], "error")

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Сигнал плотности не блокирует даже при корректной аннотации блока.
    def test_density_is_nonblocking_even_with_valid_annotation(self):
        text = "# atomic-spec://TEST/DR-2\n# Execute three phases.\ndef work():\n    prepare()\n    reserve()\n    persist()\n"
        status, report = self.run_cli({"a.py": text}, density=3)
        self.assertEqual(status, 0)
        self.assertEqual(report["summary"], {"error": 0, "warning": 1})
        self.assertEqual(report["diagnostics"][0]["code"], "SPEC010")

    # atomic-spec://ATOMIC-GUARD-001/DR-11
    # Markdown явно показывает уровень диагностики.
    def test_markdown_prints_severity(self):
        _, text = self.run_cli({"a.py": "LIMIT = 6\ndef work():\n    return 1\n"}, raw=True)
        self.assertIn("warning SPEC001 · 1", text)
        self.assertIn("a.py:1", text)
        self.assertIn("error SPEC001 · 1", text)
        self.assertIn("a.py:2", text)

    # atomic-spec://ATOMIC-GUARD-001/DR-4
    # Невалидная ссылка оставляет контекст неполным.
    def test_getcontext_invalid_reference_stays_incomplete(self):
        text = "# atomic-spec://TEST/DR-99\n# Upper retry bound.\nLIMIT = 6\n"
        for mode in ("brief", "full"):
            with self.subTest(mode=mode):
                status, report = self.run_cli({"a.py": text}, command="getcontext", mode=mode)
                self.assertEqual(status, 1)
                self.assertFalse(report["complete"])
                self.assertEqual(report["summary"]["error"], 1)

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Выбор языка исходника не должен сам по себе менять рекомендательный характер одинакового синтаксического кандидата.
    def test_real_adapters_are_consistent_for_advisory_candidates(self):
        for name, text in [
            ("a.go", "package a\nconst Limit = 6\n"),
            ("a.ts", "export const retryLimit = 6;\n"),
            ("a.yaml", "policy:\n  limit: 6\n"),
        ]:
            with self.subTest(name=name):
                status, report = self.run_cli({name: text})
                self.assertEqual(status, 0)
                self.assertGreater(report["summary"]["warning"], 0)
                self.assertEqual(report["summary"]["error"], 0)

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Ключевое слово в имени не понижает структурное обязательство.
    def test_structural_obligation_not_downgraded_by_keyword(self):
        for kind, role in [
            ("FunctionDef", ""),
            ("*ast.TypeSpec", "syntax"),
            ("TypeAliasDeclaration", "declaration"),
            ("Constructor", ""),
            ("ExceptHandler", ""),
            ("EnumDeclaration", ""),
            ("BinaryExpression", "decision"),
            ("TestScenario", "scenario"),
        ]:
            with self.subTest(kind=kind):
                self.assertEqual(
                    guard.annotation_severity({"kind": kind, "role": role, "hints": ["policy"]}),
                    "error",
                )
        self.assertEqual(
            guard.annotation_severity({"kind": "CapabilityGate", "role": "decision"}),
            "warning",
        )
        self.assertEqual(
            guard.annotation_severity({"kind": "*ast.IfStmt", "role": "fixture"}),
            "warning",
        )
        self.assertEqual(guard.annotation_severity({"kind": "FutureCandidate"}), "warning")

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Профиль не меняет тяжесть уже выбранного legacy-кандидата.
    def test_profile_does_not_change_selected_candidate_severity(self):
        for profile in ("strict", "grouped", "tuned"):
            status, report = self.run_cli({"a.py": "LIMIT = 6\n"}, granularity=profile)
            self.assertEqual(status, 0)
            self.assertEqual(report["summary"], {"error": 0, "warning": 1})
