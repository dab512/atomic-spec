"""DR-11/12/13: readable diagnostics, URI validation and exact reverse-reference sets."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_detector import guard, GO_PARSER, NODE, MODULES
import test_severity

ROOT = guard.DEFAULT_SPEC_ROOT
SPEC = ROOT + "/trace.spec.md"
URI = "atomic-spec://DEMO-TRACE-001/DR-2"
DOCUMENT = (
    "---\nid: DEMO-TRACE-001\nstatus: review\n---\n### DR-2. Meaning\nActual rule.\n### DR-3. Other\nOther rule.\n"
)


# atomic-spec://ATOMIC-GUARD-001/DR-12
# Список мест использования требования должен содержать действительные ссылки на него в выбранных файлах.
class ReverseTests(unittest.TestCase):
    def invoke(self, root, command, *extra, files=None, raw=False):
        output = io.StringIO()
        args = [
            command,
            "--root",
            str(root),
            "--go-parser",
            GO_PARSER,
            "--node",
            NODE,
            "--node-modules",
            MODULES,
            *extra,
        ]
        if files:
            args += ["--files", *files]
        if not raw:
            args.append("--json")
        with contextlib.redirect_stdout(output):
            status = guard.main(args)
        return status, output.getvalue() if raw else json.loads(output.getvalue())

    def fixture(self, root):
        spec = root / SPEC
        spec.parent.mkdir(parents=True)
        spec.write_text(DOCUMENT)
        (spec.parent / "registry.json").write_text(json.dumps({"DEMO-TRACE-001": SPEC}))
        (root / "a.py").write_text(
            "# atomic-spec://DEMO-TRACE-001/DR-2\n# Apply the rule.\ndef first():\n    return 1\n"
        )
        (root / "b.go").write_text(
            "package a\n// atomic-spec://DEMO-TRACE-001/DR-2\n// @spec-note Apply the rule.\nfunc Second() {}\n"
        )
        (root / "c.ts").write_text(
            '// atomic-spec://DEMO-TRACE-001/DR-2\n// atomic-spec://DEMO-TRACE-001/DR-2\n// Apply the rule.\nfunction third() {}\nconst fake = "Spec: atomic-spec://DEMO-TRACE-001/DR-2";\n'
        )
        return ["a.py", "b.go", "c.ts"]

    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # Поиск от кода к требованиям и от требования к коду должен показывать одни и те же места для всех трёх адаптеров и эквивалентных ссылок.
    def test_round_trip_exact_locations_across_three_adapters_and_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            status, context = self.invoke(root, "getcontext", files=files)
            self.assertEqual(status, 0)
            expected = {("a.py", 3), ("b.go", 4), ("c.ts", 4)}
            self.assertEqual(
                {(x["file"], x["line"]) for x in context["requirements"][0]["locations"]},
                expected,
            )
            for target in [
                URI,
                SPEC + "#dr-2",
                SPEC,
                "atomic-spec://DEMO-TRACE-001",
            ]:
                with self.subTest(target=target):
                    status, result = self.invoke(root, "whereused", "--spec", target, files=files)
                    self.assertEqual(status, 0)
                    self.assertEqual(result["matches"], 3)
                    self.assertEqual(result["scope_kind"], "selected-files")
                    self.assertEqual(result["input_files"], files)
                    actual = {(x["file"], x["line"]) for item in result["requirements"] for x in item["locations"]}
                    self.assertEqual(actual, expected)

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # Голый URI допустим в настоящем комментарии; строковый литерал с тем же URI не считается местом применения требования.
    def test_bare_uri_round_trip_all_comment_adapters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            (root / "b.go").write_text(f"package a\n// {URI}\n// Apply the rule.\nfunc Second() {{}}\n")
            (root / "c.ts").write_text(f"// {URI}\n// Apply the rule.\nfunction third() {{}}\n")
            (root / "a.yaml").write_text(f"# {URI}\n# Limit the operation.\nlimit: 6\n")
            files.append("a.yaml")
            status, report = self.invoke(root, "whereused", "--spec", URI, files=files)
            self.assertEqual(status, 0)
            actual = {(loc["file"], loc["line"]) for item in report["requirements"] for loc in item["locations"]}
            self.assertEqual(actual, {("a.py", 3), ("b.go", 4), ("c.ts", 3), ("a.yaml", 3)})

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # URI без пояснения не заменяет человеческий текст.
    def test_bare_uri_alone_is_not_prose(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text(f"# {URI}\ndef work():\n    return 1\n")
            status, report = self.invoke(root, "getcontext", files=["a.py"])
            self.assertEqual(status, 1)
            self.assertTrue(any(d["code"] == "SPEC002" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # URI начинает владение пояснением; обычные комментарии после него относятся к этой ссылке.
    def test_uri_starts_comment_group_all_adapters(self):
        cases = [
            ([URI, "Explain the invariant."], True),
            ([URI, "First explanation.", "Second explanation."], True),
            ([URI + " //Explain the invariant."], True),
            ([URI + " // Explain the invariant."], True),
            ([URI + " — Explain the invariant."], True),
            (["Unrelated preceding code comment.", URI], False),
            ([URI], False),
            ([URI, ""], False),
            ([URI, URI], False),
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            for name, prefix, header, body in [
                ("a.py", "# ", "", "def work():\n    return 1\n"),
                ("b.go", "// ", "package a\n", "func Work() {}\n"),
                ("c.ts", "// ", "", "function work() {}\n"),
                ("a.yaml", "# ", "", "limit: 6\n"),
            ]:
                for lines, valid in cases:
                    with self.subTest(name=name, lines=lines):
                        (root / name).write_text(header + "".join(prefix + line + "\n" for line in lines) + body)
                        status, report = self.invoke(root, "getcontext", files=[name])
                        self.assertEqual(status, 0 if valid else 1)
                        if valid:
                            self.assertEqual(len(report["requirements"]), 1)
                        else:
                            self.assertTrue(any(d["code"] == "SPEC002" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # Пробел после синтаксического маркера комментария не обязателен.
    def test_uri_comment_introducer_without_space(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            for name, header, prefix, body in [
                ("a.py", "", "#", "def work():\n    return 1\n"),
                ("b.go", "package a\n", "//", "func Work() {}\n"),
                ("c.ts", "", "//", "function work() {}\n"),
                ("a.yaml", "", "#", "limit: 6\n"),
            ]:
                with self.subTest(name=name):
                    (root / name).write_text(
                        header + prefix + URI + "\n" + prefix + " Meaning of the invariant.\n" + body
                    )
                    status, report = self.invoke(root, "getcontext", files=[name])
                    self.assertEqual(status, 0)
                    self.assertEqual(len(report["requirements"]), 1)

    # atomic-spec://ATOMIC-GUARD-001/DR-3
    # Ссылка не заимствует пояснение у следующего кодового блока.
    def test_uri_does_not_borrow_description_from_next_code_block(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "a.py").write_text(
                f"# {URI}\ndef first():\n    return 1\n\n# Unrelated comment on another function.\ndef second():\n    return 2\n"
            )
            status, report = self.invoke(root, "getcontext", files=["a.py"])
            self.assertEqual(status, 1)
            self.assertEqual(report["diagnostics"][0]["code"], "SPEC002")
            self.assertEqual(report["diagnostics"][0]["block"], "first")

    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # Ограниченная выборка сохраняется в отчёте и не выдаётся за остальные файлы.
    def test_scope_subset_is_explicit_and_does_not_claim_other_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            status, result = self.invoke(root, "whereused", "--spec", URI, files=["a.py"])
            self.assertEqual(status, 0)
            self.assertEqual(result["matches"], 1)
            self.assertEqual(result["input_files"], ["a.py"])

    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # Даже при нуле совпадений проверяется валидность целевого требования.
    def test_zero_matches_validates_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            status, result = self.invoke(root, "whereused", "--spec", SPEC + "#dr-3", files=files)
            self.assertEqual(status, 0)
            self.assertEqual(result["matches"], 0)
            status, result = self.invoke(root, "whereused", "--spec", SPEC + "#dr-99", files=files)
            self.assertEqual(status, 1)
            self.assertFalse(result["complete"])
            self.assertEqual(result["diagnostics"][0]["code"], "SPEC004")

    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # При сбое парсера найденные места использования требования сохраняются, но список помечается неполным.
    def test_parser_failure_keeps_valid_partial_reverse_result_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            (root / "broken.py").write_text("def broken(:\n")
            status, result = self.invoke(root, "whereused", "--spec", URI, files=files + ["broken.py"])
            self.assertEqual(status, 1)
            self.assertFalse(result["complete"])
            self.assertEqual(result["matches"], 3)
            self.assertTrue(any(d["code"] == "SPEC008" for d in result["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-13
    # Неизвестный или несовпадающий ID реестра блокирует разрешение URI.
    def test_unknown_or_mismatched_registry_id_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            registry = root / ROOT / "registry.json"
            for content in [
                "{}",
                json.dumps({"DEMO-TRACE-001": SPEC}).replace("TRACE", "WRONG"),
                '{"DEMO-TRACE-001":"' + SPEC + '","DEMO-TRACE-001":"' + SPEC + '"}',
                '{"DEMO-TRACE-001":"../../outside.spec.md"}',
            ]:
                with self.subTest(content=content):
                    registry.write_text(content)
                    status, result = self.invoke(root, "getcontext", files=["a.py"])
                    self.assertEqual(status, 1)
                    self.assertEqual(result["diagnostics"][0]["severity"], "error")
            registry.write_text(json.dumps({"DEMO-TRACE-001": SPEC}))
            (root / SPEC).write_text(DOCUMENT.replace("id: DEMO-TRACE-001", "id: DEMO-OTHER-001"))
            status, result = self.invoke(root, "getcontext", files=["a.py"])
            self.assertEqual(status, 1)
            self.assertIn("disagrees", result["diagnostics"][0]["message"])

    # atomic-spec://ATOMIC-GUARD-001/DR-13
    # Неправильная структура URI отклоняется без угадывания.
    def test_malformed_uris_are_rejected(self):
        registry = {"DEMO-TRACE-001": SPEC}
        for uri in [
            "atomic-spec://DEMO-TRACE-001/DR-0",
            "atomic-spec://DEMO-TRACE-001/dr-2",
            "atomic-spec://DEMO-TRACE-001/DR-2?rev=abc",
            "atomic-spec://DEMO-TRACE-001/DR-2#dr-2",
            "atomic-spec://user@DEMO-TRACE-001/DR-2",
            "atomic-spec://DEMO-TRACE-001/../DR-2",
            "atomic-spec://DEMO-TRACE-001/%44R-2",
        ]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                guard.reference(uri, ROOT, registry)

    # atomic-spec://ATOMIC-GUARD-001/DR-13
    # Реестр читается один раз и строго из выбранной ревизии.
    def test_registry_read_once_and_from_selected_revision(self):
        class Repo:
            root = Path.cwd()
            reads = []

            def read(self, path, revision=None):
                self.reads.append((path, revision))
                if path == ROOT + "/registry.json":
                    return json.dumps({"DEMO-TRACE-001": SPEC}) if revision == "review" else "{}"
                if path == SPEC:
                    return DOCUMENT
                return "# atomic-spec://DEMO-TRACE-001/DR-2\n# Apply the rule.\ndef work():\n    return 1\n"

        repo = Repo()
        args = SimpleNamespace(
            command="getcontext",
            mode="brief",
            granularity="strict",
            density_lines=100,
            node=NODE,
            node_modules=MODULES,
            go_parser=GO_PARSER,
            spec_root=ROOT,
        )
        report = guard.analyze(args, repo, ["a.py", "b.py"], "review", None)
        self.assertTrue(report["complete"])
        self.assertEqual(repo.reads.count((ROOT + "/registry.json", "review")), 1)
        self.assertEqual(repo.reads.count((SPEC, "review")), 1)
        self.assertFalse(any(revision is None for _, revision in repo.reads))

    # atomic-spec://ATOMIC-GUARD-001/DR-11
    # Компактная группировка сохраняет все кликабельные исходные локации.
    def test_compact_groups_keep_all_clickable_locations(self):
        with tempfile.TemporaryDirectory(prefix="spec links ") as folder:
            root = Path(folder)
            (root / "a.py").write_text("def first():\n    return 1\ndef second():\n    return 2\n")
            (root / "b.py").write_text("def third():\n    return 3\n")
            status, text = self.invoke(root, "audit", files=["a.py", "b.py"], raw=True)
            self.assertEqual(status, 1)
            self.assertEqual(text.count("### error SPEC001"), 1)
            self.assertIn("SPEC001 · 3", text)
            for file, line in [("a.py", 1), ("a.py", 3), ("b.py", 1)]:
                self.assertIn(f"[{file}:{line}](<{root.resolve() / file}:{line}>)", text)
            self.assertIn("`second`", text)

    # atomic-spec://ATOMIC-GUARD-001/DR-11
    # Ссылки неизменяемого отчёта используют точную ревизию.
    def test_immutable_report_links_use_exact_revision(self):
        revision = "a" * 40
        report = {
            "revision": revision,
            "source_root": "/local/checkout",
            "repository_url": "https://github.com/example/project",
        }
        link = guard.location_link(report, {"file": "src/a b.go", "line": 42})
        self.assertIn("https://github.com/example/project/blob/" + revision + "/src/a%20b.go#L42", link)
        self.assertNotIn("/local/checkout", link)


# atomic-spec://ATOMIC-GUARD-001/DR-12
# Проверка списка мест использования должна обнаруживать пропущенную ссылку на требование, а не только подтверждать формат отчёта.
class MutationProofTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-12
    # Пропуск даже одного места использования требования должен обнаруживаться регрессионным тестом.
    def test_reverse_acceptance_detects_a_dropped_location(self):
        original = guard.whereused

        def omit_one(*args):
            report = original(*args)
            if report["requirements"] and report["requirements"][0]["locations"]:
                report["requirements"][0]["locations"].pop()
            return report

        with patch.object(guard, "whereused", omit_one):
            result = unittest.TestResult()
            ReverseTests("test_round_trip_exact_locations_across_three_adapters_and_aliases").run(result)
        self.assertTrue(
            result.failures,
            "acceptance must detect missing reference locations",
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-10
    # Невалидная явная ссылка обязана оставаться ошибкой; понижение до предупреждения не может давать успешную проверку.
    def test_acceptance_detects_an_invalid_link_being_silently_downgraded(self):
        original = guard.analyze

        def downgrade(*args):
            report = original(*args)
            for item in report["diagnostics"]:
                if item["code"] == "SPEC004":
                    item["severity"] = "warning"
            report["summary"] = guard.diagnostic_summary(report["diagnostics"])
            report["complete"] = report["summary"]["error"] == 0
            return report

        with patch.object(guard, "analyze", downgrade):
            result = unittest.TestResult()
            test_severity.SeverityTests("test_invalid_reference_on_constant_is_error").run(result)
        self.assertTrue(
            result.failures,
            "invalid reference regression must be red under downgrade mutation",
        )
