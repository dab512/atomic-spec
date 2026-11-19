"""Noise fixes preserve real scenarios and access/publication constraints."""

import unittest

from test_detector import parse
import test_policy

NOTE = test_policy.NOTE
PYNOTE = test_policy.PYNOTE
PREFIX = test_policy.PREFIX


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
# Ослабление технического шума обязано сохранять обнаружение самостоятельных сценариев и чувствительных правил доступа.
class NoisePolicyTests(unittest.TestCase):
    run_policy = test_policy.PolicyTests.run_policy

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Фабрика each не создаёт второй самостоятельный тест.
    def test_each_factory_is_not_a_second_test(self):
        for expression in [
            'it.each([1,2])("case %s", x => expect(x).toBeTruthy());',
            'test.each`value\n${1}`("case", () => {});',
        ]:
            with self.subTest(expression=expression):
                result = parse("a.test.ts", expression)
                scenarios = [u for u in result["units"] if u.get("role") == "scenario"]
                self.assertEqual(len(scenarios), 1, scenarios)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
    # Secondary Call факт регистрации не должен вытеснить annotated сценарий как владельца его внутренних ветвлений.
    def test_scenario_registration_call_cannot_shadow_its_annotated_owner(self):
        source = (
            "import {test} from 'node:test';\n"
            + NOTE
            + "test('logout',async()=>{for(const value of [true]){if(value) clear();}});\n"
        )
        _, report = self.run_policy({"logout.test.js": source})
        self.assertFalse(any(d["severity"] == "error" for d in report["diagnostics"]), report["diagnostics"])
        unannotated = source + "test('another independent scenario',()=>{if(ready) write();});\n"
        _, denied = self.run_policy({"logout.test.js": unannotated})
        self.assertTrue(
            any(
                d["code"] == "SPEC_COVER" and d["severity"] == "error" and "another independent scenario" in d["block"]
                for d in denied["diagnostics"]
            ),
            denied["diagnostics"],
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Фикстуры распознаются с учётом импорта, alias и параметров декоратора.
    def test_fixture_imports_aliases_and_options(self):
        examples = [
            "import pytest\n@pytest.fixture\ndef seed(): return 1",
            'import pytest as p\n@p.fixture(scope="module")\ndef seed(): return 1',
            "from pytest import fixture as fx\n@fx\ndef seed(): return 1",
            "from pytest_asyncio import fixture\n@fixture()\nasync def seed(): return 1",
        ]
        for source in examples:
            with self.subTest(source=source):
                data = test_policy.guard.python_source({"path": "test_a.py", "source": source})
                unit = next(u for u in data["units"] if u["name"] == "seed")
                self.assertEqual(unit["role"], "fixture")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Затенённый декоратор не считается подтверждённой фикстурой.
    def test_shadowed_fixture_is_not_proven(self):
        source = "import pytest\npytest = service\n@pytest.fixture\ndef work(): return 1"
        data = test_policy.guard.python_source({"path": "a.py", "source": source})
        self.assertNotEqual(next(u for u in data["units"] if u["name"] == "work")["role"], "fixture")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Обычное решение callback остаётся рекомендательным сигналом.
    def test_callback_decision_stays_advisory(self):
        source = NOTE + "function Screen(){return <Button onClick={() => {if (ready) select();}}/>;}"
        _, report = self.run_policy({"a.tsx": source})
        self.assertFalse(
            any(d["severity"] == "error" for d in report["diagnostics"]),
            report["diagnostics"],
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Вызов контроля доступа внутри callback сохраняет строгое обязательство.
    def test_access_inside_callback_still_blocks(self):
        path = PREFIX + "skillstore-frontend/src/routes/example.tsx"
        source = (
            'import {canDo} from "../api/backend";\n'
            + NOTE
            + 'function Screen(){return <Button onClick={() => {if(canDo(user,"manage.all.sync")) save();}}/>;}'
        )
        _, report = self.run_policy({path: source})
        self.assertTrue(any(d["code"] == "SPEC_ACCESS" and d["severity"] == "error" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Вспомогательная Go-функция и табличный случай могут быть рекомендательными.
    def test_go_helper_and_table_case_are_advisory(self):
        path = PREFIX + "skillstore/internal/example/a_test.go"
        source = (
            'package example\nimport "testing"\n'
            + NOTE
            + 'func TestPolicy(t *testing.T) {\nfor _, row := range []bool{true,false} { t.Run("case",func(t *testing.T){if row {t.Fatal("bad")}}) }\n}\nfunc setup(t *testing.T) { t.Helper(); if true {println(1)} }'
        )
        _, report = self.run_policy({path: source})
        self.assertFalse(
            any(d["severity"] == "error" for d in report["diagnostics"]),
            report["diagnostics"],
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Самостоятельный тестовый сценарий не теряет обязательную аннотацию.
    def test_independent_test_scenario_stays_mandatory(self):
        path = PREFIX + "skillstore/internal/example/a_test.go"
        source = (
            'package example\nimport "testing"\n'
            + NOTE
            + '\nvar data=1\nfunc TestSecurity(t *testing.T) {if true {t.Fatal("bad")}}'
        )
        _, report = self.run_policy({path: source})
        self.assertTrue(any(d["severity"] == "error" and d["block"] == "TestSecurity" for d in report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Вложенные helpers и локальные типы тестов остаются рекомендательными.
    def test_nested_test_helpers_and_local_types_are_advisory(self):
        py = PYNOTE + "def test_policy():\n    def walk(value):\n        if value: return 1\n    assert walk(True)==1\n"
        _, report = self.run_policy({PREFIX + "skillstore/testsuite/tests/test_sample.py": py})
        self.assertFalse(
            any(d["severity"] == "error" for d in report["diagnostics"]),
            report["diagnostics"],
        )
        go = (
            'package example\nimport "testing"\n'
            + NOTE
            + "func TestPolicy(t *testing.T) {type fixtureKey struct {id int}; println(fixtureKey{})}"
        )
        _, report = self.run_policy({PREFIX + "skillstore/internal/example/a_test.go": go})
        self.assertFalse(
            any(d["severity"] == "error" for d in report["diagnostics"]),
            report["diagnostics"],
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Регистрация технического getter не исключает бизнес-запрос к очереди.
    def test_registered_getter_does_not_exempt_business_query(self):
        path = PREFIX + "skillstore/internal/arcadia/syncrepo/publication_queue.go"
        source = (
            "package syncrepo\n"
            + NOTE
            + '\nvar data=1\nfunc publicationQueueList() {}\nfunc PublicationQueueActive(){query("finished_at IS NULL AND state=create_unknown")} '
        )
        _, report = self.run_policy({path: source})
        self.assertFalse(
            any(d["severity"] == "error" and d["block"] == "publicationQueueList" for d in report["diagnostics"])
        )
        self.assertTrue(
            any(d["severity"] == "error" and d["block"] == "PublicationQueueActive" for d in report["diagnostics"])
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Новое имя тестового helper распознаётся профилем без персонального allowlist.
    def test_unseen_test_helper_names_use_profile_not_allowlist(self):
        path = PREFIX + "skillstore/internal/example/unseen_test.go"
        source = (
            "package example\n"
            + NOTE
            + "\nvar anchor=1\ntype inMemoryScenarioData struct {id int}\nfunc arbitraryPreparation(){if true {println(1)}}"
        )
        _, report = self.run_policy({path: source})
        self.assertFalse(
            any(d["severity"] == "error" for d in report["diagnostics"]),
            report["diagnostics"],
        )
        ts = (
            NOTE
            + '\nconst anchor=1;\nfunction arbitrarySetup(){if(ready){return 1;}return 0;}\ntest("real domain behavior",()=>{});'
        )
        _, report = self.run_policy({PREFIX + "skillstore-frontend/src/example.spec.ts": ts})
        self.assertFalse(
            any(d["severity"] == "error" and d["block"] == "arbitrarySetup" for d in report["diagnostics"])
        )
        self.assertTrue(
            any(d["severity"] == "error" and d["block"].startswith("test(real domain") for d in report["diagnostics"])
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Невалидные ссылки и файловый минимум остаются строгими ошибками.
    def test_invalid_reference_and_file_minimum_stay_errors(self):
        _, report = self.run_policy({"a.py": "import pytest\n@pytest.fixture\ndef seed(): return 1"})
        self.assertTrue(any(d["code"] == "SPEC_FILE" and d["severity"] == "error" for d in report["diagnostics"]))
        _, report = self.run_policy({"a.py": PYNOTE.replace("/DR-2", "/DR-999") + "def test_case(): pass"})
        self.assertTrue(any(d["code"] == "SPEC004" and d["severity"] == "error" for d in report["diagnostics"]))
