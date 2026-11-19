"""Behavioral acceptance of the published templates, skill, archives and website."""

from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler
from http.server import ThreadingHTTPServer
import hashlib
import json
import re
import shutil
import tarfile
import threading
import zipfile

from playwright.sync_api import sync_playwright
from tools import release
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = Path(
    os.environ.get(
        "ATOMIC_SPEC_TEST_GUARD",
        str(ROOT / "skills/atomic-spec-orchestrator/vendor/specguard/specguard.py"),
    )
)


# atomic-spec://METH-TRACE-010/DR-2
# Шаблон должен создавать критерий, на который реально ссылаются исходники через публичный CLI.
class TemplateTests(unittest.TestCase):
    # atomic-spec://METH-TRACE-010/DR-2
    # Объявленный критерий бизнес-шаблона разрешается независимо от расположения сгенерированного проекта.
    def test_template_acceptance_criterion_is_resolvable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "specs").mkdir()
            template = (ROOT / "templates/atom-template.spec.md").read_text()
            template = re.sub(
                r"^id:.*$", "id: EXAMPLE-001", template, count=1, flags=re.M
            )
            (root / "specs/example.spec.md").write_text(template)
            (root / "specs/registry.json").write_text(
                json.dumps({"EXAMPLE-001": "specs/example.spec.md"})
            )
            (root / "sample.py").write_text(
                "# atomic-spec://EXAMPLE-001/AC-1\n# Сценарий проверяет согласованный результат.\ndef sample():\n    return True\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(GUARD),
                    "audit",
                    "--root",
                    str(root),
                    "--spec-root",
                    "specs",
                    "--files",
                    "sample.py",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["complete"])


# atomic-spec://ARCH-RELEASE-001/DR-1
# Самостоятельный архив сохраняет работоспособность вне исходного репозитория и не содержит окружения автора.
class ArchiveTests(unittest.TestCase):
    # atomic-spec://ARCH-RELEASE-001/DR-1
    # Приёмка использует реально собранный и извлечённый пакет, а не исходники вместо архива.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source, self.bundle = release.build(self.folder / "assets")
        with zipfile.ZipFile(self.bundle) as archive:
            archive.extractall(self.folder / "installed")
        self.skill = self.folder / "installed/atomic-spec-orchestrator"

    # atomic-spec://METH-TRACE-010/DR-3
    # Все команды контекста и проверки должны наблюдать один и тот же контракт извлечённого проекта.
    def test_extracted_skill_commands_and_reference_mutation(self):
        project = self.folder / "project"
        (project / "specs").mkdir(parents=True)
        (project / "specs/example.spec.md").write_bytes(
            (self.skill / "assets/atom-template.spec.md").read_bytes()
        )
        (project / "specs/registry.json").write_text(
            json.dumps({"DOMAIN-USECASE-001": "specs/example.spec.md"})
        )
        (project / "specs/guard.json").write_bytes(
            (self.skill / "assets/guard-policy.example.json").read_bytes()
        )
        source = project / "app.py"
        original = "# atomic-spec://DOMAIN-USECASE-001/AC-1\n# Сценарий гарантирует согласованный результат.\ndef apply():\n    return True\n"
        source.write_text(original)
        env = dict(
            os.environ,
            ATOMIC_SPEC_CACHE_DIR=str(self.folder / "empty-cache"),
            SPECGUARD_PYTHON=sys.executable,
        )
        for command in ["audit", "getcontext", "whereused", "comments"]:
            extra = (
                ["--spec", "atomic-spec://DOMAIN-USECASE-001/AC-1"]
                if command == "whereused"
                else []
            )
            result = subprocess.run(
                [
                    "bash",
                    str(self.skill / "scripts/specguard.sh"),
                    command,
                    "--root",
                    str(project),
                    "--spec-root",
                    "specs",
                    "--config",
                    "specs/guard.json",
                    "--files",
                    "app.py",
                    "--json",
                    *extra,
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["complete"])
        source.write_text(original.replace("/AC-1", "/AC-99999"))
        result = subprocess.run(
            [
                "bash",
                str(self.skill / "scripts/specguard.sh"),
                "audit",
                "--root",
                str(project),
                "--spec-root",
                "specs",
                "--config",
                "specs/guard.json",
                "--files",
                "app.py",
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any(
                d["code"] == "SPEC004" for d in json.loads(result.stdout)["diagnostics"]
            )
        )
        self.assertFalse((self.folder / "empty-cache").exists())

    # atomic-spec://ARCH-RELEASE-001/DR-1
    # Повторная сборка одних входов даёт идентичные байты архивов и верные контрольные суммы.
    def test_archives_are_reproducible_and_hashes_match(self):
        second = release.build(self.folder / "again")
        for old, new in zip((self.source, self.bundle), second):
            self.assertEqual(old.read_bytes(), new.read_bytes())
        for line in (self.source.parent / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(
                hashlib.sha256((self.source.parent / name).read_bytes()).hexdigest(),
                digest,
            )
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertFalse(
                any(
                    any(s in name.split("/") for s in release.SKIP)
                    for name in archive.namelist()
                )
            )

    # atomic-spec://ARCH-GUARD-001/DR-2
    # Явно подготовленные зависимости позволяют извлечённой поставке разбирать все заявленные языки.
    def test_extracted_bundle_with_prepared_four_language_parsers(self):
        cache = Path(
            os.environ.get("ATOMIC_SPEC_TEST_CACHE", str(ROOT / ".local/guard-cache"))
        )
        self.assertTrue(
            (cache / "goparser").is_file(),
            "Run the documented explicit Guard setup first",
        )
        self.assertTrue(
            (cache / "node/node_modules/typescript").is_dir(),
            "Missing prepared Node parser",
        )
        project = self.folder / "four-languages"
        shutil.copytree(self.skill / "vendor/specguard/examples/minimal", project)
        env = dict(
            os.environ,
            ATOMIC_SPEC_CACHE_DIR=str(cache),
            SPECGUARD_PYTHON=sys.executable,
        )
        result = subprocess.run(
            [
                "bash",
                str(self.skill / "scripts/specguard.sh"),
                "audit",
                "--root",
                str(project),
                "--spec-root",
                "specs",
                "--config",
                "specs/atomic-spec-guard.yaml",
                "--directory",
                "src",
                "--json",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["complete"])
        self.assertEqual(
            set(report["input_files"]),
            {"src/fare.py", "src/fare.go", "src/fare.ts", "src/fare.yaml"},
        )

    # atomic-spec://ARCH-RELEASE-001/DR-2
    # Повреждение поставляемого Guard и сломанная документационная ссылка должны остановить сборку.
    def test_corrupted_source_and_broken_link_reject_build(self):
        root = self.folder / "source"
        with tarfile.open(self.source) as archive:
            archive.extractall(root, filter="data")
        root = root / "atomic-spec-2.0.1"
        target = root / "skills/atomic-spec-orchestrator/vendor/specguard/specguard.py"
        original = target.read_bytes()
        target.write_bytes(original + b"\n# changed\n")
        with self.assertRaisesRegex(ValueError, "Guard source mismatch"):
            release.build(self.folder / "bad", root)
        self.assertFalse((self.folder / "bad").exists())
        target.write_bytes(original)
        (root / "README.md").write_text("[Broken](missing-file.md)")
        with self.assertRaisesRegex(ValueError, "broken local link"):
            release.build(self.folder / "bad", root)


# atomic-spec://ARCH-RELEASE-001/DR-2
# Документационный сервер предоставляет тот же статический каталог, который публикуется GitHub Pages.
class QuietHandler(SimpleHTTPRequestHandler):
    # atomic-spec://ARCH-RELEASE-001/DR-2
    # Проверка HTTP-результатов не должна зависеть от диагностических строк access log.
    def log_message(self, *args):
        pass


# atomic-spec://METH-GATE-010/DR-2
# Приёмка интерфейса должна наблюдать геометрию и переходы реальной страницы, а не совпадения исходных строк.
class WebsiteTests(unittest.TestCase):
    # atomic-spec://ARCH-RELEASE-001/DR-2
    # Обе языковые страницы и прежний маршрут скилла должны работать на мобильном и настольном экране.
    def test_responsive_pages_language_navigation_and_gate_details(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT / "docs"))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            options = (
                {"executable_path": os.environ["ATOMIC_SPEC_BROWSER"]}
                if os.environ.get("ATOMIC_SPEC_BROWSER")
                else {}
            )
            browser = playwright.chromium.launch(**options)
            try:
                for width, height in [(375, 812), (1440, 900)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    for name in ["index.html", "ru.html", "orchestrator.html"]:
                        response = page.goto(
                            f"http://127.0.0.1:{server.server_port}/{name}"
                        )
                        self.assertEqual(response.status, 200)
                        self.assertEqual(page.locator("h1").count(), 1)
                        self.assertTrue(page.locator("h1").is_visible())
                        self.assertTrue(
                            page.evaluate(
                                "document.documentElement.scrollWidth <= innerWidth"
                            )
                        )
                        self.assertEqual(page.locator(".step").count(), 4)
                        if name == "ru.html":
                            evidence = ROOT / ".local/acceptance"
                            evidence.mkdir(parents=True, exist_ok=True)
                            page.screenshot(
                                path=str(evidence / f"site-{width}.png"), full_page=True
                            )
                        page.locator("summary").nth(2).click()
                        self.assertTrue(
                            page.locator("details").nth(2).evaluate("(el)=>el.open")
                        )
                        self.assertTrue(
                            page.locator("details").nth(2).locator("p").is_visible()
                        )
                        links = page.locator("nav a").all()
                        for link in links:
                            box = link.bounding_box()
                            self.assertGreaterEqual(box["x"], 0)
                            self.assertLessEqual(box["x"] + box["width"], width)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.get_by_role("link", name="Русский", exact=True).click()
                    self.assertEqual(page.locator("html").get_attribute("lang"), "ru")
                    page.close()
            finally:
                browser.close()


# atomic-spec://METH-GATE-010/DR-3
# Проверка публикационного комплекта должна завершаться ошибкой при провале любого приёмочного сценария.
if __name__ == "__main__":
    unittest.main()
