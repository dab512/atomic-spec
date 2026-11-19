"""Файловый кеш проверенных результатов с явной инвалидизацией политики и зависимостей."""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile
import time


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Эквивалентные служебные данные имеют один ключ; изменения исходных байтов политики всё равно обязаны сбрасывать прежний результат.
def digest(value):
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(data.encode()).hexdigest()


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Повторное использование результата допустимо только для неизменившегося содержимого зависимости; отсутствие файла не подтверждает его прежнюю версию.
def file_hash(path):
    if not path or not Path(path).is_file():
        return None
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Изменившийся проверяющий инструмент не может полагаться на прежний PASS: новые правила могли обнаружить ранее пропущенное нарушение.
def implementation(args):
    module = Path(__file__).resolve().parent
    names = [
        "specguard.py",
        "specguard_policy.py",
        "annotation_language.py",
        "annotation_uniqueness.py",
        "result_cache.py",
        "local_enforcement.py",
        "parser.cjs",
        "policy.cjs",
        "goparser/main.go",
        "goparser/policy.go",
        "package-lock.json",
    ]
    node = shutil.which(args.node)
    node_stat = Path(node).stat() if node else None
    modules = Path(args.node_modules) if args.node_modules else module / "node_modules"
    return digest(
        {
            "source": {name: file_hash(module / name) for name in names},
            "go_parser": file_hash(args.go_parser or module / "goparser/goparser"),
            "node": [node, node_stat.st_size, node_stat.st_mtime_ns] if node_stat else None,
            "packages": {name: file_hash(modules / name / "package.json") for name in ["typescript", "yaml"]},
        }
    )


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Сохранённый PASS действителен только при целостности записи и актуальности всех требований, на которых он основан.
def load(path, key, repo):
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return None
        entry = json.loads(path.read_text())
        report = entry["report"]
        if entry["version"] != 1 or entry["key"] != key or entry["checksum"] != digest(report):
            return None
        if not isinstance(report, dict) or not all(
            isinstance(report[name], list)
            for name in [
                "files",
                "diagnostics",
                "excluded",
                "requirements",
                "documents",
                "explanations",
            ]
        ):
            return None
        for dependency in entry["dependencies"]:
            text = repo.read(dependency["path"], dependency["revision"])
            if hashlib.sha256(text.encode()).hexdigest() != dependency["sha256"]:
                return None
        return report
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return None


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Недоступность кеша не освобождает от проверки и не должна блокировать корректный код; незавершённая запись не является результатом проверки.
def store(path, key, report, dependencies):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry = dict(
            version=1,
            key=key,
            checksum=digest(report),
            report=report,
            dependencies=dependencies,
        )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(entry, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
        return None
    except (OSError, ValueError) as error:
        return str(error)
    finally:
        if temporary and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Повторное использование результата одного файла не должно терять его связи с требованиями или приписывать ему локации других файлов.
def part(report, path):
    result = {
        name: [item for item in report[name] if item.get("file") == path]
        for name in ["files", "diagnostics", "excluded", "explanations"]
    }
    result["requirements"] = []
    for requirement in report["requirements"]:
        locations = [location for location in requirement["locations"] if location["file"] == path]
        if locations:
            result["requirements"].append(dict(requirement, locations=locations))
    documents = {item["spec"] for item in result["requirements"]}
    result["documents"] = [item for item in report["documents"] if item["path"] in documents]
    for name in ["schema_version", "policy", "revision", "base"]:
        result[name] = report[name]
    return result


# atomic-spec://ATOMIC-GUARD-001/DR-24
# Изменение любого входа проверки отменяет прежний допуск файла; неизменившиеся файлы могут переиспользовать результат независимо от остальных.
def cached_report(args, repo, files, revision, base_revision, analyzer, cacheable):
    started = time.perf_counter()
    if not files:
        result = analyzer(args, repo, [], revision, base_revision)
        result["cache"] = dict(hits=0, misses=0, stored=0, errors=[])
        return result
    policy_text = repo.read(args.config, revision)
    signature = implementation(args)
    selected, misses, keys, skipped = {}, [], {}, []
    for path in dict.fromkeys(files):
        if not cacheable(path):
            skipped.append(path)
            continue
        source = repo.read(path, revision)
        previous = None
        if base_revision:
            try:
                previous = repo.read(path, base_revision)
            except (ValueError, FileNotFoundError):
                if path not in args.added_files:
                    raise
                previous = ""
        options = [
            str(repo.root),
            path,
            args.command,
            args.mode,
            base_revision,
            revision,
            args.spec_root,
            getattr(args, "profile", None),
            bool(getattr(args, "explain", False)),
        ]
        filename = Path(args.cache_dir) / (digest(options) + ".json")
        key = digest([source, previous, policy_text, signature, args.config])
        keys[path] = (filename, key)
        result = load(filename, key, repo)
        if result is None:
            misses.append(path)
        else:
            selected[path] = result
    hits = len(selected)
    errors, stored = [], 0
    fresh = analyzer(args, repo, misses + skipped, revision, base_revision) if misses or skipped else None
    if fresh:
        dependencies = [
            dict(
                path=path,
                revision=rev,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
            )
            for (rev, path), text in repo.cache.items()
            if path.startswith(args.spec_root.rstrip("/") + "/")
        ]
        for path in skipped:
            selected[path] = part(fresh, path)
        for path in misses:
            selected[path] = part(fresh, path)
            if any(issue["code"] in {"SPEC004", "SPEC008"} for issue in selected[path]["diagnostics"]):
                continue
            filename, key = keys[path]
            error = store(filename, key, selected[path], dependencies)
            if error:
                errors.append(error)
            else:
                stored += 1
    template = fresh or next(iter(selected.values()))
    result = {key: deepcopy(template[key]) for key in ["schema_version", "policy", "revision", "base"]}
    for name in ["files", "diagnostics", "excluded", "explanations"]:
        result[name] = [item for path in dict.fromkeys(files) for item in selected[path][name]]
    requirements, documents = {}, {}
    for path in dict.fromkeys(files):
        for item in selected[path]["requirements"]:
            key = (item["spec"], item["requirement"])
            target = requirements.setdefault(key, dict(item, locations=[]))
            for location in item["locations"]:
                if location not in target["locations"]:
                    target["locations"].append(location)
        documents.update({item["path"]: item for item in selected[path]["documents"]})
    result["requirements"] = [requirements[key] for key in sorted(requirements)]
    result["documents"] = [documents[key] for key in sorted(documents)]
    result["summary"] = {
        level: sum(item["severity"] == level for item in result["diagnostics"])
        for level in ["error", "warning", "notice"]
    }
    result.update(
        complete=result["summary"]["error"] == 0,
        has_warnings=bool(result["summary"]["warning"]),
        analysis_seconds=round(time.perf_counter() - started, 6),
        cache=dict(
            hits=hits,
            misses=len(misses),
            stored=stored,
            errors=list(dict.fromkeys(errors)),
        ),
    )
    return result
