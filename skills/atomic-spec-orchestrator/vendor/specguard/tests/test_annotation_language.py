"""Real CLI regressions for binary Cyrillic-presence matching and explicit overrides."""

from copy import deepcopy
import json
import unittest

from specguard_policy import Policy
import test_policy


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
# Сравниваем настоящее пояснение с требуемым бинарным классом алфавита, не ослабляя валидность ссылки.
class AnnotationLanguageTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Явная настройка языка должна переопределять язык требования без изменения прочих обязательств проверки.
    def configured(self, severity="error", language="auto"):
        config = deepcopy(test_policy.CONFIG)
        config["annotation_language"] = {
            "language": language,
            "diagnostic": "SPEC_LANGUAGE",
        }
        config["diagnostics"]["SPEC_LANGUAGE"] = {
            "severity": severity,
            "title": "Язык пояснения",
            "message": "{requirement}: требуется {expected_language}, получено {actual_language}.",
            "hint": "Проверьте наличие кириллицы и настройку language.",
            "params": {},
            "group_by": ["code", "file"],
        }
        return config

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Оценка языка должна зависеть от пояснения и его требования; строковая имитация разметки не может выполнять это обязательство.
    def run_case(self, requirement, comment, severity="error", enabled=True, language="auto"):
        config = self.configured(severity, language)
        if not enabled:
            config.pop("annotation_language")
        return test_policy.PolicyTests.run_policy(
            self,
            {"a.py": "# atomic-spec://TEST/DR-2\n# " + comment + "\ndef work(): return 1\n"},
            config=config,
            spec_text="---\nid: TEST\nstatus: review\n---\n### DR-2. Rule\n" + requirement + "\n",
        )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Один символ кириллицы достаточен независимо от его доли в пояснении или требовании.
    def test_auto_uses_any_cyrillic_without_percentages(self):
        for comment, expected in [
            ("Reserve a publication slot.", 1),
            ("я", 0),
            ("English prose " * 100 + "я", 0),
        ]:
            code, report = self.run_case("English requirement " * 100 + "я", comment)
            self.assertEqual(code, expected, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Явный режим переопределяет язык требования и выполняет заданную семантику ru/en.
    def test_explicit_mode_overrides_requirement(self):
        for requirement, comment, language, expected in [
            ("The rule is formal.", "Комментарий.", "ru", 0),
            ("The rule is formal.", "English explanation.", "ru", 1),
            ("Русское требование.", "English explanation.", "en", 0),
            ("Русское требование.", "English explanation with я.", "en", 1),
        ]:
            code, report = self.run_case(requirement, comment, language=language)
            self.assertEqual(code, expected, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Метка en означает отсутствие кириллицы; она не различает греческий и английский как естественные языки.
    def test_non_cyrillic_text_counts_as_en(self):
        for comment in ["English text.", "Ελληνικό κείμενο", "中文说明"]:
            code, report = self.run_case("The requirement is formal.", comment)
            self.assertEqual(code, 0, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Расширенные и нерусские кириллические буквы удовлетворяют простой проверке наличия.
    def test_unicode_cyrillic_is_recognized(self):
        for comment in ["Ї", "і", "Ӂ", "Ꙁ"]:
            code, report = self.run_case("The requirement.", comment, language="ru")
            self.assertEqual(code, 0, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # В auto проверяем весь исходный блок требования с примерами, не удаляя из него кириллицу.
    def test_requirement_examples_are_not_filtered(self):
        code, report = self.run_case("The rule.\n```text\nпример\n```", "English explanation.")
        self.assertEqual(code, 1, report["diagnostics"])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Предупреждение не инвалидирует ссылку; отсутствие настройки отключает только проверку языка.
    def test_warning_and_disabled_policy_do_not_block(self):
        for severity, enabled in [("warning", True), ("error", False)]:
            code, report = self.run_case("Русское требование.", "English explanation.", severity, enabled)
            self.assertEqual(code, 0, report["diagnostics"])
            self.assertEqual(report["summary"]["error"], 0)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-22
    # Неверные режимы и устаревшие поля порогов отклоняются, а не меняют политику молча.
    def test_configuration_rejects_modes_and_old_percentages(self):
        for value in ["de", [], False, None]:
            config = self.configured()
            config["annotation_language"]["language"] = value
            with self.assertRaises(ValueError):
                Policy(json.dumps(config))
        config = self.configured()
        config["annotation_language"]["minimum_percent"] = 30
        with self.assertRaises(ValueError):
            Policy(json.dumps(config))
