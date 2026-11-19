"""Real-parser duplicate-prose checks ignore source strings and shared AST ownership."""

from copy import deepcopy
import unittest

from test_detector import SPEC
import test_policy


# atomic-spec://ATOMIC-GUARD-001/DR-23
# Самостоятельные группы поясняют своё поведение, а не повторяют универсальный комментарий.
class AnnotationUniquenessTests(unittest.TestCase):
    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Предупреждение о повторе не должно блокировать корректное покрытие; строгость этого нарушения настраивается независимо.
    def configured(self, severity="error"):
        config = deepcopy(test_policy.CONFIG)
        config["annotation_uniqueness"] = {"diagnostic": "SPEC_DUPLICATE"}
        config["diagnostics"]["SPEC_DUPLICATE"] = {
            "severity": severity,
            "title": "Повторное пояснение",
            "message": "Пояснение повторяется в {duplicate_count} блоках; пример: {duplicate_origin}.",
            "hint": "Опишите смысл именно этого блока.",
            "params": {},
            "group_by": ["code", "file"],
        }
        return config

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Уникальность относится к реальным группам разметки; похожий текст внутри данных не создаёт конкурирующего пояснения.
    def annotated(self, description, name="work"):
        return "# atomic-spec://TEST/DR-2\n# " + description + "\ndef " + name + "(): return 1\n"

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Одинаковая проза в разных файлах разрешена: требование уникальности намеренно ограничено одним файлом.
    def test_duplicate_prose_across_files_is_allowed(self):
        files = {
            "a.py": self.annotated("Reserve the queue slot."),
            "b.py": self.annotated("Reserve the queue slot."),
        }
        code, report = test_policy.PolicyTests.run_policy(self, files, self.configured())
        self.assertEqual(code, 0, report["diagnostics"])
        self.assertFalse(any(d["code"] == "SPEC_DUPLICATE" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Регистр и повторяющиеся пробелы не маскируют скопированное пояснение.
    def test_normalized_duplicates_inside_one_file(self):
        source = self.annotated("Reserve   the slot.", "first") + "\n" + self.annotated("reserve the SLOT.", "second")
        code, report = test_policy.PolicyTests.run_policy(self, {"a.py": source}, self.configured())
        self.assertEqual(code, 1)
        self.assertEqual(sum(d["code"] == "SPEC_DUPLICATE" for d in report["diagnostics"]), 2)

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Разные пояснения могут ссылаться на один пункт; общая для нескольких владельцев группа считается один раз.
    def test_distinct_prose_and_one_shared_group_pass(self):
        files = {
            "a.py": self.annotated("Reserve the publication slot."),
            "b.py": self.annotated("Release the completed slot."),
        }
        code, report = test_policy.PolicyTests.run_policy(self, files, self.configured())
        self.assertEqual(code, 0, report["diagnostics"])
        self.assertFalse(any(d["code"] == "SPEC_DUPLICATE" for d in report["diagnostics"]))

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Строковый литерал с похожим пояснением не создаёт второго комментария.
    def test_string_lookalike_is_not_a_duplicate(self):
        source = self.annotated("Reserve the slot.") + '\nFAKE = "# Spec: ' + SPEC + '\\n# Reserve the slot."\n'
        code, report = test_policy.PolicyTests.run_policy(self, {"a.py": source}, self.configured())
        self.assertEqual(code, 0, report["diagnostics"])

    # atomic-spec://ATOMIC-GUARD-001/DR-23
    # Рекомендательный повтор виден, но не ломает покрытие корректными ссылками.
    def test_warning_does_not_create_hidden_file_errors(self):
        files = {
            "a.py": self.annotated("Reserve a slot.", "first") + "\n" + self.annotated("Reserve a slot.", "second")
        }
        code, report = test_policy.PolicyTests.run_policy(self, files, self.configured("warning"))
        self.assertEqual(code, 0, report["diagnostics"])
        self.assertEqual(report["summary"]["error"], 0)
        self.assertEqual(sum(d["code"] == "SPEC_DUPLICATE" for d in report["diagnostics"]), 2)
