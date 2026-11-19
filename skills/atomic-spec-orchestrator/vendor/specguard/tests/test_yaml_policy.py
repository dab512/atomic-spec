"""Real YAML decoding preserves policy validation and rejects ambiguous documents."""

from pathlib import Path
from types import SimpleNamespace
import contextlib
import hashlib
import io
import json
import tempfile
import unittest

from test_detector import write_test_registry

from test_detector import guard, NODE, MODULES, SPEC
from specguard_policy import Policy

ROOT = Path(__file__).resolve().parents[1]


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
# YAML является только данными; неоднозначный или исполняемый синтаксис не подменяет строгую схему.
class YamlPolicyTests(unittest.TestCase):
    def load(self, text, path="policy.yaml"):
        return guard.policy_document(SimpleNamespace(node=NODE, node_modules=MODULES), path, text)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Комментарии в YAML не должны менять тип и смысл объявленных значений политики.
    def test_yaml_comments_and_scalar_types(self):
        result = json.loads(self.load("# policy\nversion: 1\nflag: false\nname: skillstore\nitems: [base, frontend]\n"))
        self.assertEqual(
            result,
            {
                "version": 1,
                "flag": False,
                "name": "skillstore",
                "items": ["base", "frontend"],
            },
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Проектный YAML проходит действующую схему политики.
    def test_project_yaml_passes_existing_schema(self):
        source = (ROOT / "tests/fixtures/skillstore-policy.yaml").read_text()
        policy = Policy(self.load(source))
        self.assertIn("skillstore", policy.profiles)
        self.assertEqual(policy.diagnostics["SPEC_ACCESS"]["severity"], "error")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Совместимость JSON сохраняет проверку дублирующихся ключей.
    def test_json_compatibility_retains_duplicate_validation(self):
        text = '{"version":1,"version":2}'
        with self.assertRaisesRegex(ValueError, "duplicate"):
            Policy(self.load(text, "policy.json"))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Неоднозначный или исполняемый YAML отклоняется.
    def test_ambiguous_or_executable_yaml_is_rejected(self):
        cases = [
            "version: 1\nversion: 2\n",
            "a: &rule 1\nb: *rule\n",
            "a: !custom value\n",
            "a: !!str value\n",
            "version: 1\n---\nversion: 2\n",
            "1: first\n'1': second\n",
            "a: .nan\n",
            "a: .inf\n",
            "a: 9007199254740993\n",
            "%YAML 1.1\n---\nversion: 1\n",
            "version: [broken\n",
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Неизвестные поля YAML по-прежнему являются ошибкой схемы.
    def test_unknown_yaml_schema_keys_still_fail(self):
        with self.assertRaisesRegex(ValueError, "configuration fields"):
            Policy(self.load("version: 1\ntyppo: 2\n"))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # Чрезмерно большая политика должна быть отвергнута до её применения, не создавая видимость успешной проверки.
    def test_yaml_size_limit_precedes_decoding(self):
        with self.assertRaisesRegex(ValueError, "256 KiB"):
            self.load("#" + "x" * (256 * 1024))

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-19
    # CLI хеширует исходные YAML-байты с комментариями, а не промежуточный JSON.
    def test_cli_preserves_raw_yaml_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = "# provenance comment\n" + (ROOT / "tests/fixtures/skillstore-policy.yaml").read_text()
            (root / "policy.yaml").write_text(source)
            doc = root / SPEC.split("#")[0]
            doc.parent.mkdir(parents=True)
            doc.write_text("---\nid: TEST\nstatus: review\n---\n### DR-2. Rule\nMeaning.\n")
            write_test_registry(root, SPEC.split("#")[0])
            (root / "a.py").write_text("# atomic-spec://TEST/DR-2\n# Применяем правило.\ndef work():\n    return 1\n")
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
                        "--json",
                        "--files",
                        "a.py",
                    ]
                )
            self.assertEqual(code, 0, output.getvalue())
            report = json.loads(output.getvalue())
            self.assertEqual(report["policy"]["sha256"], hashlib.sha256(source.encode()).hexdigest())
