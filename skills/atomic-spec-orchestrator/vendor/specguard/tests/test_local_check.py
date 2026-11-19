"""Local build checks use current bytes and never start services on a failed check."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

from test_detector import write_test_registry

from test_detector import GO_PARSER, MODULES, NODE, P, SPEC


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
# Локальный допуск должен отражать реальные сохранённые изменения, а не подменять их заранее рассчитанным результатом.
class LocalCheckTests(unittest.TestCase):
    def run_local(
        self,
        source,
        previous="",
        status=None,
        changes=None,
        entrypoint=False,
        restart=False,
        merge_base="1" * 40,
        explicit_base=None,
        expected_base="1" * 40,
        modified_at=None,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = "marvel/skillstore/services/skillstore/internal/sample.py"
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            config = root / "marvel/skillstore/services/atomic/atomic-spec-guard.yaml"
            config.parent.mkdir(parents=True)
            config.write_text((P / "tests/fixtures/skillstore-policy.yaml").read_text())
            if modified_at is not None:
                os.utime(target, (modified_at, modified_at))
            doc = root / SPEC.split("#")[0]
            doc.parent.mkdir(parents=True)
            doc.write_text("---\nid: TEST\nstatus: review\n---\n### DR-2. Rule\nMeaning.\n")
            write_test_registry(root, SPEC.split("#")[0])
            bindir = root / "bin"
            bindir.mkdir()
            arc = bindir / "git"
            arc.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "a=sys.argv[1:]\n"
                "if a[:1]==['-c']: a=a[2:]\n"
                "if a[0]=='rev-parse': print(os.environ['TEST_ROOT'])\n"
                "elif a[0]=='merge-base':\n"
                " if not os.environ['TEST_MERGE_BASE']: sys.exit(3)\n"
                " print(os.environ['TEST_MERGE_BASE'])\n"
                "elif a[0]=='diff':\n"
                " assert a[a.index('--name-status')+1]==os.environ['TEST_EXPECTED_BASE'], a\n"
                " sys.stdout.write(os.environ['TEST_DIFF'])\n"
                "elif a[0]=='status':\n"
                " for k,values in json.loads(os.environ['TEST_STATUS'])['status'].items():\n"
                "  for v in values: sys.stdout.write(('?? ' if k=='untracked' else ' M ')+v['path']+chr(0))\n"
                "elif a[0]=='show' and a[1].endswith('sample.py'): print(os.environ['TEST_OLD'],end='')\n"
                "else: sys.exit(3)\n"
            )
            arc.chmod(0o755)
            env = dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                TEST_ROOT=str(root),
                TEST_DIFF=changes if changes is not None else "M\t" + path,
                TEST_STATUS=json.dumps(status or {"status": {}}),
                TEST_OLD=previous,
                TEST_MERGE_BASE=merge_base,
                TEST_EXPECTED_BASE=expected_base,
                SPECGUARD_GO_PARSER=GO_PARSER,
                SPECGUARD_NODE=NODE,
                SPECGUARD_NODE_MODULES=MODULES,
                SPECGUARD_CACHE_DIR=str(root / "cache"),
                SPECGUARD_CONFIG="marvel/skillstore/services/atomic/atomic-spec-guard.yaml",
                SPECGUARD_SCOPE="marvel/skillstore/services/skillstore",
                SPECGUARD_LOCAL_ENTRYPOINT=str(P / "scripts/local-check.sh"),
            )
            env.pop("SPECGUARD_BASE", None)
            if explicit_base is not None:
                env["SPECGUARD_BASE"] = explicit_base
            if restart:
                source = (P / "tests/fixtures/skillstore-local-preflight.sh").read_text()
                body = source.split("restart_backend() {", 1)[1].split("\n}\n", 1)[0]
                env["LOCAL_SPECGUARD"] = str(P / "scripts/local-check.sh")
                env["LOCAL_SKIP_SPECS"] = "0"
                check_body = source.split("check_local_specs() {", 1)[1].split("\n}\n", 1)[0]
                args = [
                    "bash",
                    "-c",
                    "check_local_specs() {" + check_body + "\n}\nrestart_backend() {" + body + "\n}\nrestart_backend",
                ]
            elif entrypoint:
                args = [
                    "bash",
                    str(P / "tests/fixtures/skillstore-local-preflight.sh"),
                    "--check-specs",
                ]
            else:
                args = ["bash", str(P / "scripts/local-check.sh")]
            result = subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, timeout=30)
            return result

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Проверяется изменённый незакоммиченный текст, а не прежняя версия файла.
    def test_current_unstaged_bytes_fail(self):
        old = "# atomic-spec://TEST/DR-2\n# Применяем правило публикации.\ndef work():\n    return 1\n"
        result = self.run_local("def work():\n    return 2\n", old)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("sample.py", result.stdout)
        self.assertIn("SPEC_FILE", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Корректная текущая разметка проходит локальную проверку.
    def test_valid_current_bytes_pass(self):
        source = "# atomic-spec://TEST/DR-2\n# Применяем правило публикации.\ndef work():\n    return 2\n"
        result = self.run_local(source, source.replace("return 2", "return 1"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Новый неотслеживаемый файл участвует в проверке.
    def test_untracked_file_is_checked(self):
        path = "marvel/skillstore/services/skillstore/internal/sample.py"
        result = self.run_local(
            "def work():\n    return 2\n",
            changes="",
            status={"status": {"untracked": [{"path": path, "type": "file", "status": "untracked"}]}},
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("SPEC_FILE", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Предупреждение не останавливает локальный запуск.
    def test_warning_does_not_block(self):
        source = "# atomic-spec://TEST/DR-2\n# Применяем правило публикации.\ndef old():\n    return 1\n"
        result = self.run_local(source + "\nLIMIT_RULE = 12\n", source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertRegex(result.stdout, r"# Specguard: 0 error, [1-9][0-9]* warning")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Пустой diff не создаёт выдуманные нарушения.
    def test_empty_diff_passes(self):
        result = self.run_local("", changes="")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Ошибочная разметка останавливает local-dev до запуска сервисов.
    def test_local_dev_stops_before_services(self):
        result = self.run_local("def work():\n    return 2\n", entrypoint=True)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("SPEC_FILE", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Отказ проверки перед рестартом сохраняет работающий backend.
    def test_restart_failure_preserves_running_backend(self):
        result = self.run_local("def work():\n    return 2\n", restart=True)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("SPEC_FILE", result.stdout)
        self.assertEqual(result.stderr, "")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Удалённый файл не требует чтения отсутствующего исходника.
    def test_deleted_file_does_not_require_reading_missing_source(self):
        path = "marvel/skillstore/services/skillstore/internal/deleted.py"
        result = self.run_local("", changes="D\t" + path)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Невалидная ссылка блокирует локальную сборку.
    def test_invalid_reference_blocks_local_build(self):
        result = self.run_local("# atomic-spec://MADE-UP/DR-999\n# Explanation.\ndef work():\n    return 2\n")
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("SPEC004", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Явное отключение preflight действует и при передаче параметров порта.
    def test_skip_flag_bypasses_preflight_even_with_port_arguments(self):
        source = (P / "tests/fixtures/skillstore-local-preflight.sh").read_text()
        prefix = source.split("# ───── Параметризация портов", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "local-dev.sh"
            script.write_text(prefix + "\nprintf 'START_CONTINUES\\n'\n")
            result = subprocess.run(
                ["bash", str(script), "--port", "8900", "--skip-atomic-spec-guard"],
                cwd=directory,
                text=True,
                capture_output=True,
                timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("START_CONTINUES", result.stdout)
        self.assertIn("отключена", result.stdout)

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
    # Режим только проверки несовместим с явным отключением проверки.
    def test_skip_and_check_only_are_rejected_together(self):
        result = subprocess.run(
            [
                "bash",
                str(P / "tests/fixtures/skillstore-local-preflight.sh"),
                "--skip-atomic-spec-guard",
                "--check-specs",
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn("несовместим", result.stderr)
