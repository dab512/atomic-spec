"""Configured policy acceptance uses real parsers, source locations and requirement validation."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import contextlib
import io
import json
import tempfile
import unittest

from test_detector import write_test_registry

from test_detector import guard, GO_PARSER, NODE, MODULES, SPEC
from specguard_policy import Policy

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(
    guard.policy_document(
        SimpleNamespace(node=NODE, node_modules=MODULES),
        "policy.yaml",
        (ROOT / "tests/fixtures/skillstore-policy.yaml").read_text(),
    )
)
# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
# Языковая конвенция виртуальной фикстуры не меняет русскую политику проекта и не должна скрывать нарушения других правил.
CONFIG["annotation_language"]["language"] = "en"
NOTE = "// atomic-spec://TEST/DR-2\n// Meaning of the rule.\n"
PYNOTE = "# atomic-spec://TEST/DR-2\n# Meaning of the rule.\n"
PREFIX = "marvel/skillstore/services/"


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
# Покрытие кода и список мест использования требований должны согласованно описывать один исходник при выбранной политике.
class PolicyTests(unittest.TestCase):
    def run_policy(
        self,
        files,
        config=None,
        base=None,
        explain=True,
        command="audit",
        spec_text=None,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = root / SPEC.split("#")[0]
            doc.parent.mkdir(parents=True)
            doc.write_text(spec_text or "---\nid: TEST\nstatus: review\n---\n### DR-2. Actual rule\nMeaning.\n")
            write_test_registry(root, SPEC.split("#")[0])
            for path, source in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
            (root / "policy.json").write_text(json.dumps(config or CONFIG))
            args = [
                command,
                "--root",
                str(root),
                "--config",
                "policy.json",
                "--go-parser",
                GO_PARSER,
                "--node",
                NODE,
                "--node-modules",
                MODULES,
                "--json",
                "--files",
                *files,
            ]
            if explain:
                args.append("--explain")
            original = guard.Repository.read

            def read(repo, path, revision=None):
                return base.get(path, "") if revision == "base" else original(repo, path)

            output = io.StringIO()
            with (
                patch.object(
                    guard,
                    "resolve_inputs",
                    return_value=(
                        list(files),
                        None,
                        "base" if base is not None else None,
                    ),
                ),
                patch.object(guard.Repository, "read", read),
                contextlib.redirect_stdout(output),
            ):
                code = guard.main(args)
            return code, json.loads(output.getvalue())

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
    # Файловый минимум отражается в настроенной схеме отчёта.
    def test_file_minimum_and_schema(self):
        code, report = self.run_policy({"a.py": "value = 1\n"})
        self.assertEqual(code, 1)
        self.assertEqual(report["schema_version"], 3)
        self.assertTrue(any(d["code"] == "SPEC_FILE" for d in report["diagnostics"]))
        self.assertIn("notice", report["summary"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
    # Заголовочная аннотация выполняет файловый минимум, но не освобождает самостоятельные функции от покрытия.
    def test_file_header_counts_but_does_not_cover_functions(self):
        code, report = self.run_policy({"a.py": PYNOTE + "\nvalue = 1\ndef work():\n    return 1\n"})
        self.assertFalse(any(d["code"] == "SPEC_FILE" for d in report["diagnostics"]))
        self.assertTrue(any(d["code"] == "SPEC_COVER" and d["block"] == "work" for d in report["diagnostics"]))
        self.assertEqual(code, 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Файл только с корректным комментарием не получает лишнюю ошибку покрытия.
    def test_comment_only_file(self):
        code, report = self.run_policy({"a.py": PYNOTE})
        self.assertEqual(code, 0)
        self.assertEqual(report["files"][0]["annotations"], 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Вложенные решения могут наследовать требование родителя только в пределах разрешённых границ покрытия.
    def test_parent_annotation_covers_decisions(self):
        for path, source in [
            ("a.py", PYNOTE + "def work(x):\n    if x:\n        return 1\n"),
            (
                "a.go",
                "package a\n" + NOTE + "func work(x bool) { if x { println(1) } }",
            ),
            ("a.ts", NOTE + "function work(x:boolean) {if(x) return 1;}"),
        ]:
            with self.subTest(path=path):
                code, report = self.run_policy({path: source})
                self.assertEqual(code, 0, report["diagnostics"])
                self.assertTrue(any(e["status"] == "covered" for e in report["explanations"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Самостоятельная вложенная функция обязана иметь собственное покрытие и не заимствует требование внешней функции.
    def test_nested_function_cannot_borrow_outer_reference(self):
        code, report = self.run_policy({"a.py": PYNOTE + "def outer():\n    def inner():\n        return 1\n"})
        self.assertEqual(code, 1)
        self.assertTrue(any(d["block"] == "inner" and d["severity"] == "error" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Исключение синтаксического правила не отменяет валидацию явной ссылки.
    def test_invalid_reference_survives_exclusion(self):
        config = deepcopy(CONFIG)
        config["exclusions"]["omit"] = {
            "match": {},
            "rules": ["structural", "decisions"],
            "reason": "test exception",
        }
        config["profiles"]["base"]["exclusions"].append("omit")
        code, report = self.run_policy(
            {"a.py": PYNOTE.replace("/DR-2", "/DR-999") + "def work():\n    return 1\n"},
            config,
        )
        self.assertEqual(code, 1)
        self.assertTrue(any(d["code"] == "SPEC004" for d in report["diagnostics"]))
        self.assertTrue(any(d.get("exclusion") == "omit" for d in report["diagnostics"]))
        self.assertTrue(any(e.get("exclusion") == "omit" for e in report["explanations"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
    # Полное исключение файла сохраняет причину в отчёте.
    def test_explicit_file_exclusion_reported(self):
        code, report = self.run_policy({"pkg/node_modules/a.ts": "broken { not source"})
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["notice"], 1)
        self.assertEqual(report["excluded"][0]["exclusion"], "vendor")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-1
    # Строковое значение не может исключить исходник из проверки под видом generated-маркера.
    def test_generated_marker_inside_string_does_not_exclude(self):
        for path, source in [
            ("a.py", 'x = """\n# @generated\n"""'),
            ("a.ts", "const x = `\n// @generated\n`;"),
        ]:
            with self.subTest(path=path):
                code, report = self.run_policy({path: source})
                self.assertEqual(code, 1)
                self.assertEqual(report["excluded"], [])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-1
    # Подтверждённый сгенерированный файл исключается явно и не выдаётся за проверенный вручную исходник.
    def test_actual_generated_comment_excludes(self):
        for path, source in [
            ("a.py", "# @generated\nx=1"),
            ("a.go", "// Code generated test. DO NOT EDIT.\npackage a"),
            ("a.ts", "// @generated\nconst x=1;"),
        ]:
            with self.subTest(path=path):
                code, report = self.run_policy({path: source})
                self.assertEqual(code, 0, report)
                self.assertEqual(report["summary"]["notice"], 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Группа настроек не требует отдельного блокирующего сообщения для каждого скалярного значения.
    def test_yaml_groups_do_not_report_each_scalar(self):
        source = PYNOTE + "vars:\n" + "".join(f"  value{i}: {i}\n" for i in range(50))
        code, report = self.run_policy({"config.yaml": source})
        self.assertEqual(code, 0, report["diagnostics"])
        self.assertLess(len(report["diagnostics"]), 3)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Условие представления остаётся кандидатом, если политика не устанавливает для него отдельного строгого обязательства.
    def test_presentation_conditions_are_advisory(self):
        code, report = self.run_policy(
            {"a.tsx": NOTE + '\nconst header=1;\nfunction Card(){return <div>{name || "missing"}</div>}'}
        )
        self.assertTrue(any(d["code"] == "SPEC_COVER" and d["block"] == "Card" for d in report["diagnostics"]))
        self.assertFalse(
            any(d["severity"] == "error" and d["node_kind"] == "BinaryExpression" for d in report["diagnostics"])
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Импортированный alias гейта доступа сохраняет строгое правило.
    def test_named_import_alias_is_access_rule(self):
        path = PREFIX + "skillstore-frontend/src/routes/example.tsx"
        source = (
            NOTE
            + '\nimport {canDo as allowed} from "../api/backend";\nfunction Card(user){return allowed(user,"manage.all.badges") ? <div/> : null;}'
        )
        code, report = self.run_policy({path: source})
        self.assertEqual(code, 1)
        self.assertTrue(any(d["code"] == "SPEC_ACCESS" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Совпадение имени с затенённым импортом не подтверждает известный гейт доступа.
    def test_shadowed_import_is_not_proven_access(self):
        path = PREFIX + "skillstore-frontend/src/routes/example.tsx"
        source = (
            NOTE
            + '\nimport {canDo} from "../api/backend";\nfunction Card(canDo){return canDo(user,"manage.all.badges");}'
        )
        _, report = self.run_policy({path: source})
        self.assertFalse(any(d["code"] == "SPEC_ACCESS" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Переименование прямого импорта не снимает обязательство описать гейт или изменение матрицы прав.
    def test_go_import_alias_and_matrix_mutation(self):
        path = PREFIX + "skillstore/internal/handlers/test.go"
        source = (
            'package handlers\nimport rights "a.yandex-team.ru/marvel/skillstore/services/skillstore/internal/access/actions"\n'
            + NOTE
            + "\nfunc work(){rights.ActionRoles[0]=nil;rights.Can(nil,0)}"
        )
        _, report = self.run_policy({path: source})
        self.assertTrue(any(d["code"] == "SPEC_ACCESS" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Изменение матрицы прав требует относящегося к ней покрытия; аннотация несвязанной функции его не заменяет.
    def test_matrix_cell_diff_is_not_hidden_by_unrelated_annotation(self):
        path = PREFIX + "skillstore/internal/access/actions/actions.go"
        before = "package actions\n" + NOTE + 'func unrelated(){}\nvar ActionRoles=map[string]bool{"admin":false}\n'
        after = before.replace('"admin":false', '"admin":true')
        _, report = self.run_policy({path: after}, base={path: before}, command="check")
        self.assertTrue(any(d["code"] == "SPEC_ACCESS" and "ActionRoles" in d["block"] for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Пояснение диагностики должно использовать объявленные параметры и соответствовать проверяемому правилу.
    def test_custom_message_parameters(self):
        config = deepcopy(CONFIG)
        config["diagnostics"]["SPEC_COVER"]["params"] = {"team": "SkillStore"}
        config["diagnostics"]["SPEC_COVER"]["message"] = "{team}: {name}"
        _, report = self.run_policy({"a.py": PYNOTE + "\nvalue=1\ndef work(): pass"}, config)
        self.assertTrue(any(d["message"] == "SkillStore: work" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Пустые строки и комментарии не увеличивают число кодовых строк.
    def test_metrics_ignore_blank_and_comment_lines(self):
        config = deepcopy(CONFIG)
        config["rules"]["large-block"]["match"] = {
            "node": {"eq": "function"},
            "metrics": {"code_lines": {"gt": 4}},
        }
        source = PYNOTE + "def work():\n" + "".join("    # comment\n\n" for _ in range(15)) + "    return 1\n"
        _, report = self.run_policy({"a.py": source}, config)
        self.assertFalse(any(d["code"] == "SPEC_SIZE" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Равноприоритетные конфликтующие правила отклоняются явно.
    def test_conflicting_matching_rules_fail(self):
        config = deepcopy(CONFIG)
        config["rules"]["duplicate"] = deepcopy(config["rules"]["structural"])
        config["profiles"]["base"]["rules"].append("duplicate")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            from specguard_policy import Facts

            policy = Policy(json.dumps(config))
            facts = Facts(
                "a.py",
                guard.python_source({"path": "a.py", "source": "def work(): pass"}),
            )
            policy.evaluate(facts, None, set())

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Некорректная структура конфигурации не принимается за рабочую политику.
    def test_config_validation(self):
        mutations = [
            lambda c: c.update(version=99),
            lambda c: c.update(typo=True),
            lambda c: c["profiles"]["base"]["extends"].append("skillstore"),
            lambda c: c["diagnostics"]["SPEC_COVER"].update(message="{name.__class__}"),
            lambda c: c["rules"]["structural"].update(match={"node": {"eq": "invented"}}),
            lambda c: c["rules"]["structural"].update(match={"name": {"regex": "(a+)+"}}),
            lambda c: c["diagnostics"]["SPEC004"].update(severity="warning"),
            lambda c: c["exclusions"]["test-decisions"].update(reason=""),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                config = deepcopy(CONFIG)
                mutate(config)
                with self.assertRaises(ValueError):
                    Policy(json.dumps(config))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Один именованный порог должен одинаково определять срабатывание правила и текст подсказки.
    def test_named_parameter_controls_threshold_and_hint(self):
        config = deepcopy(CONFIG)
        config["parameters"]["large_block_lines"] = 1
        _, report = self.run_policy({"a.py": PYNOTE + "def work():\n    return 1\n"}, config)
        warning = next(d for d in report["diagnostics"] if d["code"] == "SPEC_SIZE")
        self.assertIn("1 строк", warning["hint"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-10
    # Информационный notice не блокирует результат.
    def test_notice_does_not_block(self):
        config = deepcopy(CONFIG)
        config["diagnostics"]["SPEC_SIZE"]["severity"] = "notice"
        config["parameters"]["large_block_lines"] = 1
        status, report = self.run_policy({"a.py": PYNOTE + "def work():\n    return 1\n"}, config)
        self.assertEqual(status, 0)
        self.assertEqual(report["summary"]["notice"], 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Исключение одного правила не снимает другие обязательства блока.
    def test_rule_exclusion_does_not_remove_other_obligations(self):
        config = deepcopy(CONFIG)
        config["exclusions"]["only-access"] = {
            "match": {},
            "rules": ["access-helpers"],
            "reason": "Only this rule is exempt",
        }
        config["profiles"]["skillstore"]["exclusions"].append("only-access")
        path = PREFIX + "skillstore/internal/handlers/types.go"
        _, report = self.run_policy({path: "package handlers\n" + NOTE + "\nfunc userCan() {}"}, config)
        self.assertTrue(any(d["code"] == "SPEC_COVER" for d in report["diagnostics"]))
        self.assertTrue(any(d.get("exclusion") == "only-access" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Все поддерживаемые адаптеры возвращают измерение AST.
    def test_all_supported_parsers_provide_ast_metric(self):
        from specguard_policy import Facts
        from test_detector import parse

        examples = [
            ("a.go", "package a\nfunc work(){if true {println(1)}}"),
            ("a.ts", "function work(){if(true){return 1;}}"),
            ("a.yaml", "jobs:\n  test:\n    command: hello\n"),
        ]
        for path, source in examples:
            with self.subTest(path=path):
                facts = Facts(path, parse(path, source))
                self.assertTrue(any(u.get("ast_nodes", 0) > 2 for u in facts.units))
        facts = Facts(
            "a.py",
            guard.python_source({"path": "a.py", "source": "def work():\n    return 1"}),
        )
        self.assertTrue(any(u.get("ast_nodes", 0) > 2 for u in facts.units))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Контекст diff не включает неизменённую соседнюю функцию.
    def test_diff_context_omits_unmodified_function(self):
        before = (
            PYNOTE
            + "def first():\n    return 1\n"
            + PYNOTE.replace("Meaning of the rule.", "Apply the second operation independently.")
            + "def second():\n    return 2\n"
        )
        after = before.replace("return 2", "return 3")
        status, report = self.run_policy({"a.py": after}, base={"a.py": before}, command="getcontext")
        self.assertEqual(status, 0)
        self.assertEqual([x["block"] for x in report["requirements"][0]["locations"]], ["second"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Похожие на комментарии строки не выполняют файловый минимум.
    def test_comment_lookalikes_never_satisfy_file_minimum(self):
        for path, source in [
            ("a.py", 'value = """' + PYNOTE + '"""'),
            ("a.ts", "const value = `" + NOTE + "`;"),
            ("a.go", "package a\nvar value = `" + NOTE + "`"),
        ]:
            with self.subTest(path=path):
                _, report = self.run_policy({path: source})
                self.assertTrue(any(d["code"] == "SPEC_FILE" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
    # Check и audit применяют одну настроенную политику.
    def test_check_and_audit_apply_same_policy(self):
        source = PYNOTE + "def work(x):\n    if x:\n        return 1\n"
        audit, a = self.run_policy({"a.py": source})
        check, c = self.run_policy({"a.py": source}, base={"a.py": ""}, command="check")
        self.assertEqual((audit, a["summary"]), (check, c["summary"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Удалённая функция не создаёт ошибку у следующего объявления.
    def test_deleted_function_does_not_require_annotation_on_next_function(self):
        before = PYNOTE + "\nvalue=1\ndef gone():\n    return 1\ndef keep():\n    return 2\n"
        after = before.replace("def gone():\n    return 1\n", "")
        code, report = self.run_policy({"a.py": after}, base={"a.py": before}, command="check")
        self.assertEqual(code, 0, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Удаление аннотации не снимает проверку сохранившегося владельца.
    def test_removed_annotation_still_checks_its_surviving_owner(self):
        before = PYNOTE + "def first():\n    return 1\n" + PYNOTE + "def second():\n    return 2\n"
        after = before[len(PYNOTE) :]
        code, report = self.run_policy({"a.py": after}, base={"a.py": before}, command="check")
        self.assertEqual(code, 1)
        self.assertTrue(any(d["code"] == "SPEC_COVER" and d["block"] == "first" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Неверные типы каталогов дают ошибку конфигурации.
    def test_wrong_catalog_types_are_configuration_errors(self):
        for field, value in [("diagnostic", []), ("check", []), ("coverage", [])]:
            with self.subTest(field=field):
                config = deepcopy(CONFIG)
                config["rules"]["structural"][field] = value
                with self.assertRaises(ValueError):
                    Policy(json.dumps(config))
        config = deepcopy(CONFIG)
        config["diagnostics"]["SPEC_COVER"]["severity"] = []
        with self.assertRaises(ValueError):
            Policy(json.dumps(config))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Диагностика файлового порога использует измеренное число аннотаций.
    def test_file_threshold_is_measured_in_diagnostic(self):
        config = deepcopy(CONFIG)
        config["files"]["minimum_annotations"] = 2
        _, report = self.run_policy({"a.py": PYNOTE + "value=1"}, config)
        issue = next(d for d in report["diagnostics"] if d["code"] == "SPEC_FILE")
        self.assertIn("1 валидных", issue["message"])
        self.assertIn("требуется 2", issue["message"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-14
    # Повторяющиеся ключи конфигурации отклоняются.
    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            Policy('{"version":1,"version":1}')
