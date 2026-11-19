"""Regression corpus for the detector pilot; no project sources are modified."""

import importlib.util
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
import tempfile
from argparse import Namespace
from pathlib import Path

P = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location("guard", P / "specguard.py")
guard = importlib.util.module_from_spec(module)
module.loader.exec_module(guard)
NODE = os.environ.get("SPECGUARD_NODE", "node")
URI = "atomic-spec://TEST/DR-2"
MODULES = os.environ.get(
    "SPECGUARD_NODE_MODULES",
    str(P / "node_modules"),
)
GO_PARSER = os.environ.get("SPECGUARD_GO_PARSER", str(P / "goparser/goparser"))
SPEC = guard.DEFAULT_SPEC_ROOT + "/development/spec-traceability.spec.md#dr-2"


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-13
# Короткая ссылка тестового исходника должна иметь явный авторитетный источник, а не разрешаться по случайному совпадению пути.
def write_test_registry(root, path):
    registry = root / guard.DEFAULT_SPEC_ROOT / "registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"TEST": path}))


def parse(path, source):
    executable = [GO_PARSER] if path.endswith(".go") else [NODE, str(P / "parser.cjs"), MODULES]
    return json.loads(
        subprocess.check_output(executable, input=json.dumps([{"path": path, "source": source}]), text=True)
    )[0]


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
# Проверка синтаксиса должна обнаруживать реальное покрытие без исполнения проверяемого кода.
class DetectorTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Допустимый YAML не теряет последние узлы, когда полный нормализованный AST превышает бюджет исходного текста.
    def test_large_yaml_facts_preserve_complete_single_file(self):
        source = "paths:\n" + "".join(
            f"  /representative/long/resource/{index}:\n"
            f"    post:\n      operationId: operation_{index}\n      description: Full source declaration\n"
            for index in range(3000)
        )
        self.assertLess(len(source.encode()), guard.LIMIT)
        args = Namespace(root=P, go_parser=GO_PARSER, node=NODE, node_modules=MODULES)
        facts = guard.parse_sources(args, [{"path": "large.yaml", "source": source}])["large.yaml"]
        self.assertGreater(len(json.dumps(facts).encode()), guard.LIMIT)
        self.assertEqual(facts["facts_version"], 2)
        self.assertFalse(facts.get("error"))
        self.assertEqual(len(facts["units"]), 18002)
        self.assertEqual(facts["units"][-1]["config_path"], "paths./representative/long/resource/2999.post.description")
        self.assertEqual(facts["code_lines"][-1], len(source.splitlines()))
        self.assertIn("operation_2999", facts["tokens"][0])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Дополнительный бюджет AST не расширяет лимит обычного вывода VCS и других команд.
    def test_ordinary_command_keeps_eight_mib_budget(self):
        with self.assertRaisesRegex(ValueError, "command output exceeds 8 MiB"):
            guard.command([sys.executable, "-c", f"print('x' * {guard.LIMIT})"], P)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Превышение отдельного бюджета фактов не обрезается до синтаксически успешного ответа.
    def test_parser_output_still_has_finite_budget(self):
        with self.assertRaisesRegex(ValueError, "command output exceeds 32 MiB"):
            guard.command(
                [sys.executable, "-c", f"print('x' * {guard.PARSER_OUTPUT_LIMIT})"],
                P,
                output_limit=guard.PARSER_OUTPUT_LIMIT,
            )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Соседний комментарий Go привязывается к объявленному типу.
    def test_go_type_comment_attaches(self):
        r = parse(
            "a.go",
            "package a\n// atomic-spec://TEST/DR-2\n// Business type.\ntype A struct {}\n",
        )
        self.assertEqual(r["units"][0]["refs"], [URI])
        self.assertEqual(r["units"][0]["start"], 4)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Файловая разметка не освобождает самостоятельную функцию от её собственного обязательства покрытия.
    def test_go_header_cannot_inherit_function(self):
        r = parse(
            "a.go",
            "package a\n// atomic-spec://TEST/DR-2\n// Rule.\nfunc A() {\nif true {\nprintln(1)\n}\n}",
        )
        unit = guard.select_units(r, {5})[0]
        self.assertEqual(unit["name"], "if")
        self.assertFalse(unit["refs"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Вложенный оператор тела может использовать требование своей функции в пределах разрешённого наследования покрытия.
    def test_go_body_inherits_function(self):
        r = parse(
            "a.go",
            "package a\n// atomic-spec://TEST/DR-2\n// Rule.\nfunc A() {\nif true {\nprintln(1)\n}\n}",
        )
        self.assertEqual(guard.select_units(r, {6})[0]["name"], "A")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Строка Go не считается spec-комментарием.
    def test_go_string_not_comment(self):
        r = parse("a.go", f'package a\nfunc A() {{ println("// Spec: {SPEC}") }}')
        self.assertFalse(r["units"][0]["refs"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Пустая физическая строка разрывает соседство Go-комментария с объявлением.
    def test_go_blank_line_detaches(self):
        r = parse("a.go", "package a\n// atomic-spec://TEST/DR-2\n// Rule.\n\nfunc A() {}")
        self.assertFalse(r["units"][0]["refs"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-12
    # Одна общая аннотация подтеста не должна размножать места применения требования в отчёте.
    def test_go_subtest_deduplicates(self):
        r = parse(
            "a_test.go",
            'package a\nfunc TestA() {\nt.Run("x",func() {\nprintln(1)\n})\n}',
        )
        units = guard.select_units(r, None, True)
        self.assertEqual(sum(u["start"] == 3 for u in units), 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Чистое переформатирование не создаёт нового бизнес-решения и не должно порождать новое обязательство разметки.
    def test_go_formatting_has_same_tokens(self):
        self.assertEqual(
            parse("a.go", "package a\nfunc A() { println(1) }")["tokens"],
            parse("a.go", "package a\n// comment\nfunc A() {\n println(1)\n}")["tokens"],
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Многострочное условие Go получает корректную границу заголовка.
    def test_go_multiline_condition(self):
        r = parse("a.go", "package a\nfunc A() {\nif true &&\nfalse {\nprintln(1)\n}\n}")
        self.assertEqual(guard.select_units(r, {4})[0]["name"], "if")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # У класса, метода и условия TypeScript сохраняются разные синтаксические владельцы.
    def test_ts_class_method_if(self):
        r = parse("a.ts", "class A {\nf() {\nif (true) {return 1;}\n}\n}")
        self.assertEqual([u["name"] for u in r["units"]], ["A", "f", "IfStatement"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Соседний комментарий привязывается к стрелочной функции TypeScript.
    def test_ts_arrow_comment(self):
        r = parse("a.ts", "// atomic-spec://TEST/DR-2\n// Rule.\nexport const f = () => 1;")
        self.assertTrue(any(u["refs"] == [URI] for u in r["units"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # TypeScript-строка с текстом ссылки не становится аннотацией.
    def test_ts_string_not_comment(self):
        r = parse("a.ts", f'function f() {{return "// Spec: {SPEC}";}}')
        self.assertTrue(all(not u["refs"] for u in r["units"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Вызов тестового API TypeScript распознаётся как сценарий, а не обычный callback.
    def test_ts_test_call_not_callback(self):
        r = parse("a.test.ts", 'it("example", () => {\nexpect(1).toBe(1);\n});')
        self.assertEqual(len(r["units"]), 1)
        self.assertIn("example", r["units"][0]["name"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Настройки в конфигурационном вызове не должны исчезать из кандидатов только из-за формы объявления.
    def test_cjs_config_detected(self):
        result = parse("a.cjs", "module.exports = {rules: {}};")
        self.assertEqual(sum(u["kind"] == "CommonJSExport" for u in result["units"]), 1)
        self.assertTrue(any(u.get("role") == "config" for u in result["units"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # JSX/TSX разбирается с сохранением исходных узлов.
    def test_tsx_parses(self):
        self.assertFalse(parse("a.tsx", "function A() { return <div />; }").get("error"))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Выполнить обязанность разметки YAML можно только настоящим комментарием, а не похожим значением настройки.
    def test_yaml_real_comments(self):
        r = parse("a.yaml", "# atomic-spec://TEST/DR-2\n# Rule.\nqueue:\n  limit: 1\n")
        self.assertEqual(r["units"][0]["refs"], [URI])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Текст ссылки в строковом значении YAML не является комментарием.
    def test_yaml_literal_string_not_comment(self):
        r = parse("a.yaml", "value: |\n  # atomic-spec://TEST/DR-2\n")
        self.assertFalse(r["units"][0]["refs"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Неоднозначный исходный YAML не допускает достоверного покрытия и должен давать ошибку разбора.
    def test_yaml_duplicate_keys_error(self):
        self.assertTrue(parse("a.yaml", "a: 1\na: 2\n").get("error"))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Синтаксический сбой поддерживаемого языка остаётся явной ошибкой.
    def test_parser_syntax_errors(self):
        for name, source in [
            ("a.go", "package"),
            ("a.ts", "function () {"),
            ("a.yaml", "a: ["),
        ]:
            with self.subTest(name=name):
                self.assertTrue(parse(name, source).get("error"))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Ссылка без якоря требования отклоняется.
    def test_reference_missing_fragment(self):
        with self.assertRaises(ValueError):
            guard.reference(SPEC.split("#")[0], guard.DEFAULT_SPEC_ROOT)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Переход за корень через компоненты пути не разрешается.
    def test_reference_traversal(self):
        with self.assertRaises(ValueError):
            guard.reference(
                "marvel/skillstore/services/atomic/spec/../x.spec.md#dr-1",
                guard.DEFAULT_SPEC_ROOT,
            )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Внешний хост не принимается за канонический источник требования.
    def test_reference_foreign_host(self):
        with self.assertRaises(ValueError):
            guard.reference("https://evil.invalid/arcadia/" + SPEC, guard.DEFAULT_SPEC_ROOT)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Существование пункта определяется объявлением, а не упоминанием его ID в тексте.
    def test_spec_declared_not_mentioned(self):
        r = guard.Specification(
            "---\nid: TEST\nstatus: implemented\n---\n## Rules\nMention DR-99.\n### DR-1. Real\nText\n"
        )
        self.assertIn("dr-1", r.rules)
        self.assertNotIn("dr-99", r.rules)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Повторное объявление одного требования является ошибкой спеки.
    def test_spec_duplicate_error(self):
        with self.assertRaises(ValueError):
            guard.Specification("---\nid: TEST\nstatus: implemented\n---\n### DR-1. A\n### DR-1. B\n")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Псевдотребование внутри fenced-примера не попадает в индекс.
    def test_spec_fenced_fake_ignored(self):
        r = guard.Specification(
            "---\nid: TEST\nstatus: implemented\n---\n```md\n### DR-99. Fake\n```\n### DR-1. Real\n"
        )
        self.assertEqual(list(r.rules), ["dr-1"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Ссылка на выведенную из действия спеку отклоняется.
    def test_retired_spec_error(self):
        with self.assertRaises(ValueError):
            guard.Specification("---\nid: TEST\nstatus: deprecated\n---\n### DR-1. A\n")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Явный якорь перед заголовком связывается с нужным требованием.
    def test_anchor_before_bullet(self):
        r = guard.Specification(
            '---\nid: TEST\nstatus: implemented\n---\n<a name="dr-1"></a>\n- **DR-1 — Rule.** Text\n'
        )
        self.assertIn("dr-1", r.rules)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Общий кандидат функции не должен исчезать из-за наличия вложенного условия: группировка сохраняет исходные обязательства.
    def test_grouped_go_keeps_function_not_nested_if(self):
        r = parse("a.go", "package a\nfunc A() {\nif true {\nprintln(1)\n}\n}")
        self.assertEqual([u["name"] for u in guard.grouped_units("a.go", r["units"])], ["A"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Настройки одного раздела YAML сохраняют общий контекст при группировке кандидатов.
    def test_grouped_yaml_keeps_section(self):
        r = parse("a.yaml", "queue:\n  limit: 1\n  mode: normal\n")
        self.assertEqual([u["name"] for u in guard.grouped_units("a.yaml", r["units"])], ["queue"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Самостоятельные тестовые сценарии остаются видимыми при сокращении вспомогательных кандидатов.
    def test_grouped_tests_keep_each_scenario(self):
        r = parse(
            "a.test.ts",
            'describe("group",()=>{\nit("one",()=>{});\nit("two",()=>{});\n});',
        )
        self.assertEqual(len(guard.grouped_units("a.test.ts", r["units"])), 2)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Вложенные решения допускают совместное ревью, но группа остаётся кандидатом, а не доказанным бизнес-правилом.
    def test_nested_branches_collapse(self):
        r = parse("a.go", "package a\nfunc A() {\nif true {\nif false {}\n}\n}")
        self.assertEqual(
            len(guard.branch_clusters("package a\nfunc A() {\nif true {\nif false {}\n}\n}", r["units"])),
            1,
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Последовательные ветви могут требовать общего пояснения и рассматриваться вместе без потери исходных фактов.
    def test_consecutive_branches_collapse(self):
        text = "package a\nfunc A() {\nif true {}\nif false {}\n}"
        self.assertEqual(len(guard.branch_clusters(text, parse("a.go", text)["units"])), 1)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Несвязанный код между ветвями не даёт оснований считать их одним кандидатом бизнес-правила.
    def test_code_between_branches_is_boundary(self):
        text = "package a\nfunc A() {\nif true {}\nprintln(1)\nif false {}\n}"
        self.assertEqual(len(guard.branch_clusters(text, parse("a.go", text)["units"])), 2)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Самостоятельная явная аннотация сохраняет собственную границу и не должна поглощаться соседней группой кандидатов.
    def test_explicit_reference_starts_new_cluster(self):
        text = "package a\nfunc A() {\nif true {}\n// atomic-spec://TEST/DR-2\n// Different rule.\nif false {}\n}"
        self.assertEqual(len(guard.branch_clusters(text, parse("a.go", text)["units"])), 2)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Python-комментарии корректно связываются с объявлениями и декораторами.
    def test_python_comments_and_decorators(self):
        text = "# atomic-spec://TEST/DR-2\n# Rule.\n@decorate\ndef work():\n    return 1\n"
        r = guard.python_source({"path": "a.py", "source": text})
        self.assertEqual(r["units"][0]["start"], 3)
        self.assertEqual(r["units"][0]["refs"], [URI])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Python docstring не выполняет обязательство spec-аннотации.
    def test_python_docstring_is_not_annotation(self):
        r = guard.python_source(
            {
                "path": "a.py",
                "source": f'def work():\n    "Spec: {SPEC}"\n    return 1\n',
            }
        )
        self.assertFalse(r["units"][0]["refs"])

    def context_fixture(self, mode="brief", target=URI, missing_file=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec = root / SPEC.split("#")[0]
            spec.parent.mkdir(parents=True)
            spec.write_text(
                "---\nid: TEST\nstatus: implemented\n---\n### DR-2. Rule\nActual requirement.\n### DR-3. Other\nUnrelated requirement.\n"
            )
            write_test_registry(root, SPEC.split("#")[0])
            if missing_file:
                write_test_registry(
                    root,
                    SPEC.split("#")[0].replace("spec-traceability.spec.md", "invented.spec.md"),
                )
            for name in ("a.go", "b.go"):
                (root / name).write_text(f"package a\n// {target}\n// Meaning.\nfunc Work() {{}}\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = guard.main(
                    [
                        "getcontext",
                        mode,
                        "--root",
                        str(root),
                        "--go-parser",
                        GO_PARSER,
                        "--files",
                        "a.go",
                        "b.go",
                        "--json",
                    ]
                )
            return status, json.loads(stdout.getvalue())

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-5
    # Краткий контекст убирает дубли требований, сохраняя все локации.
    def test_brief_deduplicates_and_keeps_locations(self):
        status, result = self.context_fixture()
        self.assertEqual(status, 0)
        self.assertEqual(len(result["requirements"]), 1)
        self.assertEqual(len(result["requirements"][0]["locations"]), 2)
        self.assertEqual(result["documents"], [])
        self.assertNotIn("Unrelated requirement", result["requirements"][0]["text"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-5
    # Полный контекст выводит каждый документ только один раз.
    def test_full_document_once(self):
        status, result = self.context_fixture("full")
        self.assertEqual(status, 0)
        self.assertEqual(len(result["documents"]), 1)
        self.assertIn("Unrelated requirement", result["documents"][0]["text"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-5
    # Совместимый вариант breef даёт тот же результат, что brief.
    def test_breef_alias(self):
        status, result = self.context_fixture("breef")
        self.assertEqual(status, 0)
        self.assertEqual(result["documents"], [])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Выдуманный пункт делает контекст неполным.
    def test_invented_requirement_is_incomplete(self):
        status, result = self.context_fixture(target=URI.replace("/DR-2", "/DR-99"))
        self.assertEqual(status, 1)
        self.assertFalse(result["complete"])
        self.assertEqual(result["requirements"], [])
        self.assertIn("does not exist", result["diagnostics"][0]["message"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-4
    # Выдуманный документ не подменяется придуманным содержимым.
    def test_invented_file_is_incomplete(self):
        status, result = self.context_fixture(missing_file=True)
        self.assertEqual(status, 1)
        self.assertEqual(result["requirements"], [])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Удаление строки сохраняет выбор затронутого владельца.
    def test_deleted_line_still_selects(self):
        self.assertEqual(guard.changed_lines("a\nb\nc", "a\nc"), {2})


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
# Прямой запуск регрессионного файла должен проверять те же обязательства, что и общий запуск самотестов.
if __name__ == "__main__":
    unittest.main()
