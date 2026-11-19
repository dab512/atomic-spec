"""Локальный допуск зависит от общей базы ветки, а не календаря или mtime."""

import json
import unittest

import test_local_check
from specguard_policy import Policy
import test_policy


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
# Старый код не блокирует запуск, но вся новая логика ветки проверяется независимо от времени изменения.
class LocalEnforcementTests(unittest.TestCase):
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Ошибка новой правки не становится допустимой из-за старого mtime или часов машины.
    def test_old_mtime_does_not_exempt_branch_change(self):
        result = test_local_check.LocalCheckTests.run_local(self, "def work(): return 1\n", modified_at=0)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("SPEC_FILE", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Общая база включает коммиты ветки в проверку; HEAD не должен незаметно сузить область до рабочей правки.
    def test_branch_diff_uses_merge_base(self):
        result = test_local_check.LocalCheckTests.run_local(
            self, "def work(): return 1\n", merge_base="2" * 40, expected_base="2" * 40
        )
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("SPEC_FILE", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Изменения trunk, не затрагивающие свою ветку, не создают обязанностей покрытия этой ветки.
    def test_no_branch_or_working_changes_pass(self):
        result = test_local_check.LocalCheckTests.run_local(self, "def work(): return 1\n", changes="")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # После обновления базы та же рабочая копия должна сравниваться с новой общей ревизией.
    def test_rebased_branch_uses_new_merge_base(self):
        for base in ["3" * 40, "4" * 40]:
            result = test_local_check.LocalCheckTests.run_local(
                self, "", changes="", merge_base=base, expected_base=base
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Без достоверной базы нельзя разрешать запуск по пустому или угаданному diff.
    def test_missing_or_invalid_merge_base_fails_closed(self):
        for value in ["", "unknown", "1" * 40 + "\n" + "2" * 40]:
            result = test_local_check.LocalCheckTests.run_local(self, "", changes="", merge_base=value)
            self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Явная база может осознанно сузить проверку, но выбор должен оставаться видимым и не зависеть от даты.
    def test_explicit_base_is_respected(self):
        result = test_local_check.LocalCheckTests.run_local(
            self,
            "",
            changes="",
            explicit_base="HEAD",
            expected_base="HEAD",
            merge_base="",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
    # Устаревшая календарная политика должна давать явную ошибку вместо молчаливого ослабления покрытия.
    def test_date_setting_is_rejected(self):
        config = json.loads(json.dumps(test_policy.CONFIG))
        config["local_enforcement"] = {"modified_since": "2026-10-23T00:00:00+03:00"}
        with self.assertRaises(ValueError):
            Policy(json.dumps(config))
