#!/usr/bin/env python3
"""Validate and build the independently extractable Atomic Spec distribution."""

from pathlib import Path
import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP = {
    ".git",
    ".local",
    ".venv",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
}


# atomic-spec://ARCH-RELEASE-001/DR-1
# Архив содержит только переносимые исходники, без установленных зависимостей, бинарников и локальных данных.
def source_files(root):
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and not any(s in SKIP for s in p.relative_to(root).parts)
        and p.name not in {".DS_Store", "goparser"}
        and p.suffix not in {".pyc", ".bak"}
    )


# atomic-spec://ARCH-RELEASE-001/DR-4
# Публикационная политика применяется к содержимому и путям всех поставляемых файлов, включая вложенный комплект.
def validate_distribution_names(root):
    policy = json.loads((root / "distribution-policy.json").read_text())
    names = ["".join(map(chr, value)) for value in policy["excluded_names"]]
    tokens = ["".join(map(chr, value)) for value in policy["excluded_tokens"]]
    for path in source_files(root):
        name = path.relative_to(root).as_posix()
        text = name + "\n" + path.read_bytes().decode("utf-8", errors="replace")
        lowered = text.casefold()
        if any(value in lowered for value in names) or any(
            re.search(r"(?<![a-z0-9])" + re.escape(value) + r"(?![a-z0-9])", lowered)
            for value in tokens
        ):
            raise ValueError(f"excluded distribution reference: {name}")


# atomic-spec://ARCH-RELEASE-001/DR-2
# Изменённый поставляемый исходник не может сохранять доказательство происхождения прежней версии Guard.
def validate(root=ROOT):
    validate_distribution_names(root)
    release = json.loads((root / "release.json").read_text())
    version = release["version"]
    if json.loads((root / "plugin.json").read_text())["version"] != version:
        raise ValueError("plugin version mismatch")
    if yaml.safe_load((root / "apm.yml").read_text())["version"] != version:
        raise ValueError("APM version mismatch")
    skill = root / release["skill_path"]
    if json.loads((skill / "version.json").read_text())["version"] != version:
        raise ValueError("skill version mismatch")
    origin = json.loads((skill / "vendor/specguard/ORIGIN.json").read_text())
    if origin["revision"] != release["guard_revision"]:
        raise ValueError("Guard revision mismatch")
    manifest = json.loads((root / "guard-source.json").read_text())
    actual = {
        p.relative_to(skill / "vendor/specguard").as_posix()
        for p in source_files(skill / "vendor/specguard")
        if p.name != "ORIGIN.json"
    }
    if actual != set(manifest):
        raise ValueError("Guard source file set mismatch")
    for name, expected in manifest.items():
        if (
            hashlib.sha256((skill / "vendor/specguard" / name).read_bytes()).hexdigest()
            != expected
        ):
            raise ValueError(f"Guard source mismatch: {name}")
    registry = json.loads((root / "specs/registry.json").read_text())
    for identity, name in registry.items():
        path = (root / name).resolve()
        if not path.is_relative_to((root / "specs").resolve()):
            raise ValueError("registry escapes specs")
        frontmatter = yaml.safe_load(path.read_text().split("---", 2)[1])
        if frontmatter["id"] != identity:
            raise ValueError(f"registry ID mismatch: {name}")
    for name in ["atom-template.spec.md", "architecture-template.spec.md"]:
        if (root / "templates" / name).read_bytes() != (
            skill / "assets" / name
        ).read_bytes():
            raise ValueError(f"template mismatch: {name}")
    for path in source_files(root):
        if path.suffix != ".md" or "vendor" in path.relative_to(root).parts:
            continue
        text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            if target.startswith(
                ("https://", "http://", "#", "mailto:", "atomic-spec://")
            ):
                continue
            local = (path.parent / target.split("#")[0]).resolve()
            if not local.is_relative_to(root.resolve()) or not local.exists():
                raise ValueError(
                    f"broken local link: {path.relative_to(root)} -> {target}"
                )
    for name in ["index.html", "ru.html", "orchestrator.html", "site.css"]:
        if (root / "docs" / name).read_bytes() != (
            root / "website" / name
        ).read_bytes():
            raise ValueError(f"published site differs: {name}")
    return release


# atomic-spec://ARCH-RELEASE-001/DR-1
# Версионный архив должен восстанавливаться в отдельном каталоге без файлов рабочей машины автора.
def build(output, root=ROOT):
    release = validate(root)
    version = release["version"]
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"atomic-spec-{version}.tar.gz"
    with (
        archive.open("wb") as stream,
        gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as compressed,
    ):
        with tarfile.open(fileobj=compressed, mode="w") as target:
            for path in source_files(root):
                data = path.read_bytes()
                info = tarfile.TarInfo(
                    f"atomic-spec-{version}/" + path.relative_to(root).as_posix()
                )
                info.size = len(data)
                info.mode = 0o755 if path.suffix == ".sh" else 0o644
                target.addfile(info, io.BytesIO(data))
    skill = root / release["skill_path"]
    bundle = output / f"atomic-spec-orchestrator-{version}.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in source_files(skill):
            info = zipfile.ZipInfo(
                "atomic-spec-orchestrator/" + path.relative_to(skill).as_posix()
            )
            info.external_attr = (0o755 if path.suffix == ".sh" else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, path.read_bytes())
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in [archive, bundle]
        )
    )
    return archive, bundle


# atomic-spec://METH-GATE-010/DR-2
# Падение проверки или отсутствие зависимости не разрешает считать комплект готовым к публикации.
def check():
    validate()
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "tools", "tests"], cwd=ROOT, check=True
    )
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "tools", "tests"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=True,
    )
    output = ROOT / ".local/acceptance"
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/atomic-spec-orchestrator/vendor/specguard/specguard.py"),
            "audit",
            "--root",
            str(ROOT),
            "--spec-root",
            "specs",
            "--config",
            "specs/guard.json",
            "--files",
            "tools/release.py",
            "tests/test_release.py",
            "--json",
            "--output",
            str(output / "guard.json"),
        ],
        check=True,
    )


# atomic-spec://ARCH-RELEASE-001/DR-3
# Подготовка артефактов не должна сама выполнять публикацию или менять удалённый репозиторий.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "build"])
    parser.add_argument("--output", type=Path, default=ROOT / ".local/release")
    args = parser.parse_args()
    if args.command == "check":
        check()
    else:
        for path in build(args.output):
            print(path)


# atomic-spec://METH-GATE-010/DR-3
# Неуспешная локальная операция возвращает вызывающему процессу ненулевой результат.
if __name__ == "__main__":
    main()
