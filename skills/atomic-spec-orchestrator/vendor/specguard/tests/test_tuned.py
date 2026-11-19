"""Finite v2 regressions from the 20-file review, not a semantic coverage claim."""

import unittest
from pathlib import Path
from types import SimpleNamespace

from test_detector import guard, parse, GO_PARSER, NODE, MODULES, SPEC


# atomic-spec://ATOMIC-GUARD-001/DR-9
# Настройка группировки должна сохранять проверенные классы кандидатов и не выдавать их число за доказательство смысловой полноты.
class TunedTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-8
    # Допустимый обработчик исключения без имени не должен срывать проверку остального файла или терять своё обязательство покрытия.
    def test_unaliased_exception_handler_has_string_owner(self):
        parsed = guard.python_source(
            {
                "path": "a.py",
                "source": "def work():\n    try:\n        run()\n    except ValueError:\n        pass\n",
            }
        )
        handler = next(unit for unit in parsed["units"] if unit["kind"] == "ExceptHandler")
        self.assertIsInstance(handler["name"], str)
        self.assertTrue(guard.tuned_units("a.py", parsed["units"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Подсказки идентификаторов учитывают границы слов.
    def test_identifier_word_boundaries(self):
        self.assertEqual(guard.identifier_hints("publicationRules"), ["rules"])
        self.assertEqual(guard.identifier_hints("permissionMatrix"), ["permission"])
        self.assertEqual(guard.identifier_hints("ruler"), [])

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Таблица правил остаётся кандидатом независимо от того, объявлена ли она на уровне модуля.
    def test_go_module_tables_are_selected(self):
        source = 'package a\nvar ActionRoles = map[string][]string{\n"handover": {"admin"},\n}\n'
        result = parse("a.go", source)
        self.assertTrue(guard.select_units(result, {3}))
        self.assertTrue(any("ActionRoles" in u["name"] for u in result["units"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Константа с признаком политики остаётся видимой подсказкой для ревью, а не исчезает вне функции.
    def test_go_const_policy_exists(self):
        result = parse("a.go", "package a\nconst (\nmaxRetries = 6\npollInterval = 30\n)\n")
        self.assertTrue(guard.select_units(result, {3}))
        self.assertTrue(guard.select_units(result, {4}))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Условие доступа в JSX остаётся кандидатом решения, даже если оно записано внутри представления.
    def test_tsx_access_decision_exists(self):
        result = parse("a.tsx", "function App() {\nreturn <div>{canEdit && <Button />}</div>;\n}")
        self.assertTrue(
            any(
                u.get("role") == "decision" or u["kind"] in {"BinaryExpression", "JSXDecision"} for u in result["units"]
            )
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Краткая форма условия или выбора значения не должна скрывать кандидат решения из ревью.
    def test_ts_conditional_and_coalesce(self):
        result = parse("a.ts", 'function f(x) {\nreturn x ? (x.value ?? "default") : null;\n}')
        self.assertTrue(any(u["kind"] == "ConditionalExpression" for u in result["units"]))
        self.assertTrue(
            any(u["kind"] == "BinaryExpression" or "coalesce" in u["name"].lower() for u in result["units"])
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Вызов на уровне модуля не исчезает из анализа.
    def test_module_call_not_lost(self):
        result = parse("a.ts", 'configureNavigation({lang: "ru"});\nexport function App() {}\n')
        self.assertTrue(guard.select_units(result, {1}))

    # atomic-spec://ATOMIC-GUARD-001/DR-8
    # Настройка YAML сохраняет собственную область применения требования и не растворяется в соседних значениях.
    def test_yaml_record_exists(self):
        result = parse("a.yaml", "rules:\n  - id: admin\n    required: true\n")
        self.assertTrue(any("Item" in u["kind"] or "Record" in u["kind"] for u in result["units"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Глобальное объявление Python остаётся кандидатом.
    def test_python_declaration_exists(self):
        result = guard.python_source({"path": "a.py", "source": "MAX_RETRIES = 6\n"})
        self.assertTrue(guard.select_units(result, {1}))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Статическая операция с данными остаётся кандидатом бизнес-правила и при записи на Python.
    def test_python_sql_candidate(self):
        result = guard.python_source(
            {
                "path": "a.py",
                "source": 'def f(db):\n    db.execute("UPDATE queue SET state=%s", ("ready",))\n',
            }
        )
        self.assertEqual(sum(u.get("role") == "sql" for u in result["units"]), 1)

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Похожий на SQL текст вне операции с данными не создаёт ложного кандидата запроса.
    def test_sql_lookalike_is_not_query(self):
        result = guard.python_source(
            {
                "path": "a.py",
                "source": 'def f():\n    print("UPDATE queue SET state=1")\n',
            }
        )
        self.assertFalse(any(u.get("role") == "sql" for u in result["units"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # Текст SQL не выполняет обязанность описать правило запроса настоящим spec-комментарием.
    def test_sql_text_is_not_annotation(self):
        result = guard.python_source(
            {
                "path": "a.py",
                "source": f'def f(db):\n    db.execute("SELECT 1 -- Spec: {SPEC}")\n',
            }
        )
        sql = next(u for u in result["units"] if u.get("role") == "sql")
        self.assertFalse(sql["refs"])

    # atomic-spec://ATOMIC-GUARD-001/DR-17
    # Параметризованные входы теста не должны ошибочно становиться самостоятельными сценариями покрытия.
    def test_python_parametrize_cases(self):
        result = guard.python_source(
            {
                "path": "test_a.py",
                "source": '@pytest.mark.parametrize("value", [0, 1, -1])\ndef test_a(value):\n    assert value >= 0\n',
            }
        )
        self.assertEqual(sum(u["kind"] == "PytestCase" for u in result["units"]), 3)

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Связанные проверки результата могут рассматриваться вместе; это группировка кандидатов, а не доказательство единственного бизнес-правила.
    def test_assertions_cluster(self):
        result = guard.python_source(
            {
                "path": "test_a.py",
                "source": "def test_a():\n    assert True\n    assert 1\n    act()\n    assert 2\n",
            }
        )
        self.assertEqual(sum(u["kind"] == "AssertionGroup" for u in result["units"]), 2)

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Настроенная выборка сохраняет SQL внутри функции.
    def test_tuned_retains_sql_inside_function(self):
        result = guard.python_source({"path": "a.py", "source": 'def f(db):\n    db.execute("SELECT 1")\n'})
        tuned = guard.tuned_units("a.py", result["units"])
        self.assertTrue(any(u.get("role") == "sql" for u in tuned))

    # atomic-spec://ATOMIC-GUARD-001/DR-15
    # Локальный capability-гейт остаётся видимым кандидатом.
    def test_local_capability_gate(self):
        result = parse(
            "a.ts",
            'function Layout(user) {\nconst canEdit = canDo(user, "manage.all.sync");\nreturn canEdit;\n}',
        )
        self.assertTrue(any(u["kind"] == "CapabilityGate" and u["start"] == 2 for u in result["units"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Имя с признаком rule остаётся синтаксической подсказкой.
    def test_local_rule_name_remains_candidate(self):
        result = parse(
            "a.ts",
            "function f() {\nconst retryPolicy = {attempts: 6};\nreturn retryPolicy;\n}",
        )
        self.assertTrue(any(u["name"] == "retryPolicy" for u in guard.tuned_units("a.ts", result["units"])))

    # atomic-spec://ATOMIC-GUARD-001/DR-15
    # Чувствительное изменение прав не должно исчезать из диагностики при применении группировки кандидатов.
    def test_permission_regression_real_analyzer(self):
        file = "a.go"
        old = 'package a\nvar ActionRoles = map[string][]string{\n"handover": {"admin"},\n}\n'
        new = old.replace('{"admin"}', '{"admin", "user"}')

        class Repo:
            root = Path.cwd()

            def read(self, path, revision=None):
                return old if revision == "base" else new

        args = SimpleNamespace(
            root=Path.cwd(),
            go_parser=GO_PARSER,
            node=NODE,
            node_modules=MODULES,
            command="check",
            mode="brief",
            spec_root=guard.DEFAULT_SPEC_ROOT,
            added_files=set(),
            density_lines=100,
            granularity="strict",
        )
        report = guard.analyze(args, Repo(), [file], "review", "base")
        self.assertTrue(report["complete"])
        self.assertEqual(report["summary"], {"error": 0, "warning": 1})
        self.assertEqual(report["diagnostics"][0]["severity"], "warning")
