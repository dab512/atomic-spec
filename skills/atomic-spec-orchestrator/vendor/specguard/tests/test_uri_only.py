"""Только голый atomic-spec URI начинает допустимую аннотацию."""

from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest

from test_detector import guard, GO_PARSER, NODE, MODULES, P


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
# Старые префиксы и пути не удовлетворяют разметке ни в одном поддерживаемом адаптере.
class UriOnlyTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Допустимость аннотации определяется форматом URI, реальным пояснением и существующим требованием; окружение не может подменять эти условия.
    def invoke(self, path, marker, configured=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = guard.DEFAULT_SPEC_ROOT + "/only.spec.md"
            target = root / spec
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\nid: ONLY-URI-001\nstatus: review\n---\n### DR-1. Правило\nЯвно связываем реализацию с требованием.\n"
            )
            (target.parent / "registry.json").write_text(json.dumps({"ONLY-URI-001": spec}))
            marker = marker.replace("SPEC_PATH", spec)
            prefix = "#" if path.endswith((".py", ".yaml")) else "//"
            note = f"{prefix} {marker}\n{prefix} Связываем этот блок с существующим правилом.\n"
            source = (
                "package a\n" + note + "func Work() {}\n"
                if path.endswith(".go")
                else note
                + (
                    "def work(): pass\n"
                    if path.endswith(".py")
                    else "jobs:\n  check: ready\n"
                    if path.endswith(".yaml")
                    else "function work() {}\n"
                )
            )
            (root / path).write_text(source)
            config_args = []
            if configured:
                (root / "policy.yaml").write_bytes((P / "tests/fixtures/skillstore-policy.yaml").read_bytes())
                config_args = ["--config", "policy.yaml"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = guard.main(
                    [
                        "audit",
                        "--root",
                        str(root),
                        "--go-parser",
                        GO_PARSER,
                        "--node",
                        NODE,
                        "--node-modules",
                        MODULES,
                        "--json",
                        *config_args,
                        "--files",
                        path,
                    ]
                )
            return code, json.loads(output.getvalue())

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Bare URI с последующим пояснением принимается в Go, Python, TypeScript и YAML.
    def test_only_bare_uri_is_accepted(self):
        for path in ["a.py", "a.go", "a.ts", "a.yaml"]:
            code, report = self.invoke(path, "atomic-spec://ONLY-URI-001/DR-1")
            self.assertEqual(code, 0, (path, report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # И путь с Spec:, и префикс Spec: перед URI должны давать явный отказ вместо старой совместимости.
    def test_legacy_markers_are_rejected(self):
        for path in ["a.py", "a.go", "a.ts", "a.yaml"]:
            for marker in [
                "Spec: SPEC_PATH#dr-1",
                "Spec: atomic-spec://ONLY-URI-001/DR-1",
            ]:
                code, report = self.invoke(path, marker)
                self.assertEqual(code, 1, (path, marker, report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
    # Проектная политика не возвращает совместимость файловых маркеров поверх строгих адаптеров.
    def test_configured_policy_is_uri_only(self):
        for path in ["a.py", "a.go", "a.ts", "a.yaml"]:
            for marker, expected in [
                ("atomic-spec://ONLY-URI-001/DR-1", 0),
                ("Spec: SPEC_PATH#dr-1", 1),
                ("Spec: atomic-spec://ONLY-URI-001/DR-1", 1),
            ]:
                code, report = self.invoke(path, marker, configured=True)
                self.assertEqual(code, expected, (path, marker, report["diagnostics"]))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Устаревший адаптер не может молча вернуть поддержку прежнего формата и пустой успешный отчёт.
    def test_stale_adapter_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.go").write_text("package a\nfunc Work() {}\n")
            adapter = root / "old-parser"
            adapter.write_text(
                "#!/usr/bin/env python3\nimport json,sys\nitems=json.load(sys.stdin)\nprint(json.dumps([dict(path=i['path'],facts_version=1,units=[],tokens=[],annotations=[]) for i in items]))\n"
            )
            adapter.chmod(0o755)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = guard.main(
                    [
                        "audit",
                        "--root",
                        str(root),
                        "--go-parser",
                        str(adapter),
                        "--json",
                        "--files",
                        "a.go",
                    ]
                )
            self.assertEqual(code, 1, output.getvalue())
            self.assertTrue(any(d["code"] == "SPEC008" for d in json.loads(output.getvalue())["diagnostics"]))
