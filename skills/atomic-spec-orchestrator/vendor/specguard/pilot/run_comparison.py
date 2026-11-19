#!/usr/bin/env python3
"""Reproduce the v2 comparison on the frozen 20-file corpus, without changing it."""

import hashlib
import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
module_spec = importlib.util.spec_from_file_location("specguard", HERE.parent / "specguard.py")
guard = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(guard)


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
# Достоверность сравнения ограничена явно выбранным неизменным корпусом; соседние файлы не могут незаметно менять эталон.
def snapshot(root, files):
    items = []
    for name in dict.fromkeys(files):
        name = guard.safe_path(name)
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("source escapes repository")
        data = path.read_bytes()
        items.append(
            {
                "file": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return items


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
# Независимая выборка должна оставаться неизменной и не пересекаться с первой; её результаты не подтверждают выводы о случаях из другого корпуса.
def fresh_summary(args, manifest, reports):
    old = {item["file"] for item in json.loads((HERE / "source-manifest.json").read_text())}
    overlap = old & {item["file"] for item in manifest}
    if overlap:
        raise ValueError(f"new corpus overlaps the first batch: {sorted(overlap)}")
    if snapshot(args.root, [item["file"] for item in manifest]) != manifest:
        raise ValueError("source bytes changed during audit")
    summary = {
        "files": len(manifest),
        "source_bytes_unchanged": True,
        "overlap_with_first_batch": [],
        "profiles": {
            name: {
                "severity": report["summary"],
                "seconds": report["analysis_seconds"],
                "codes": dict(Counter(d["code"] for d in report["diagnostics"])),
            }
            for name, report in reports.items()
        },
    }
    (args.output_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Вторая независимая пачка",
        "",
        f"Файлов: {len(manifest)}. Пересечений с первой пачкой нет; контрольные суммы после прогона совпали. CI не включён.",
        "",
        "| Файл | Строк | Error tuned | Warning tuned |",
        "|---|---:|---:|---:|",
    ]
    for entry in reports["tuned"]["files"]:
        local = [d for d in reports["tuned"]["diagnostics"] if d["file"] == entry["file"]]
        counts = guard.diagnostic_summary(local)
        lines.append(f"| {entry['file']} | {entry['lines']} | {counts['error']} | {counts['warning']} |")
    for item in reports["tuned"]["excluded"]:
        lines.append(f"Excluded: {item['file']} — {item['reason']}")
    lines += ["", "| Профиль | Error | Warning | Анализ, с |", "|---|---:|---:|---:|"]
    for name, entry in summary["profiles"].items():
        counts = entry["severity"]
        lines.append(f"| {name} | {counts['error']} | {counts['warning']} | {entry['seconds']:.3f} |")
    lines += [
        "",
        "Это количество сигналов, не precision/recall. Разные размеры и состав пачек не позволяют сравнивать суммы как качество.",
        "[Все диагностики с местами](diagnostics.md). [JSON](comparison.json). Ручная проверка примеров — отдельный артефакт review.md.",
    ]
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
# Сравнение настроек достоверно только на неизменившемся корпусе; изменённые исходники нельзя оценивать по прежнему эталону.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--go-parser", required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--node-modules", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--benchmark-files", type=int, default=0)
    parser.add_argument("--manifest", type=Path, default=HERE / "source-manifest.json")
    parser.add_argument("--new-corpus", action="store_true")
    parser.add_argument("--record-files", nargs="+")
    parser.add_argument("--config", help="configured policy pilot")
    parser.add_argument(
        "--review-labels",
        type=Path,
        help="frozen expert sample for before/after checks",
    )
    parser.add_argument("--baseline", type=Path, help="saved audit JSON for comparison")
    args = parser.parse_args()
    if args.record_files:
        if not args.new_corpus or args.manifest.exists():
            raise ValueError("record-files requires new-corpus and a new manifest path")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(snapshot(args.root, args.record_files), indent=2) + "\n")
    manifest = json.loads(args.manifest.read_text())
    for item in manifest:
        actual = hashlib.sha256((args.root / item["file"]).read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise ValueError(f"pilot input changed: {item['file']}; create a new reviewed baseline")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = [item["file"] for item in manifest]
    if args.config:
        return configured_pilot(args, manifest, files)
    reports = {}
    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    # Сокращение числа кандидатов не доказывает улучшения точности: сравнение профилей должно сохранять различие между сигналом и бизнес-правилом.
    for profile in ("strict", "grouped", "tuned"):
        output = args.output_dir / f"audit-{profile}.json"
        status = guard.main(
            [
                "audit",
                "--granularity",
                profile,
                "--root",
                str(args.root),
                "--go-parser",
                args.go_parser,
                "--node",
                args.node,
                "--node-modules",
                args.node_modules,
                "--json",
                "--output",
                str(output),
                "--files",
                *files,
            ]
        )
        if status not in (0, 1):
            raise RuntimeError(f"{profile} infrastructure failure, exit {status}")
        reports[profile] = json.loads(output.read_text())
    (args.output_dir / "diagnostics.md").write_text(guard.markdown(reports["tuned"], "brief"))
    if args.new_corpus:
        fresh_summary(args, manifest, reports)
        return 0
    baseline = json.loads((HERE / "audit-strict.json").read_text())
    before = Counter(d["file"] for d in baseline["diagnostics"])
    after = {name: Counter(d["file"] for d in report["diagnostics"]) for name, report in reports.items()}
    cases = json.loads((HERE / "reviewed-critical-cases.json").read_text())["cases"]
    updated = []
    for case in cases:
        entry = next(item for item in reports["strict"]["files"] if item["file"] == case["file"])
        local = [u for u in entry["syntax_units"] if case["start"] <= u["start"] <= case["end"]]
        selected = guard.select_units({"units": entry["syntax_units"]}, {case["start"]})
        updated.append(
            {
                "id": case["id"],
                "label": case["label"],
                "file": case["file"],
                "line": case["start"],
                "before_no_owner": not case["strict_local_candidates"] and not case["strict_enclosing"],
                "now_local_candidates": [{"kind": u["kind"], "line": u["start"], "block": u["name"]} for u in local],
                "now_selected": [{"kind": u["kind"], "line": u["start"], "block": u["name"]} for u in selected],
            }
        )
    # Replay the previously green permission mutation against the real engine in memory.
    proof_file = "marvel/skillstore/services/skillstore/internal/access/actions/actions.go"
    old = (args.root / proof_file).read_text()
    needle = "HandoverAllPresets:    {idm.RoleAdmin},"
    if old.count(needle) != 1:
        raise ValueError("permission replay fixture changed")
    new = old.replace(needle, "HandoverAllPresets:    {idm.RoleAdmin, idm.RoleUser},")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-7
    # Проверка чувствительности к изменению прав не должна менять замороженные исходники и тем самым разрушать сравнимость прогонов.
    class ReplayRepository:
        root = args.root

        # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
        # Базовое и изменённое состояния должны оставаться различимыми: иначе опыт не доказывает обнаружение нового нарушения.
        def read(self, path, revision=None):
            if path == proof_file:
                return new if revision == "review" else old
            return (args.root / path).read_text()

    check_args = SimpleNamespace(
        **vars(args),
        command="check",
        mode="brief",
        spec_root=guard.DEFAULT_SPEC_ROOT,
        added_files=set(),
        density_lines=100,
        granularity="strict",
    )
    proof = guard.analyze(check_args, ReplayRepository(), [proof_file], "review", "base")
    summary = {
        "same_20_sources": True,
        "files": len(files),
        "baseline_diagnostics": len(baseline["diagnostics"]),
        "profiles": {
            key: {
                "diagnostics": len(value["diagnostics"]),
                "seconds": value["analysis_seconds"],
                "severity": value["summary"],
                "codes": dict(Counter(d["code"] for d in value["diagnostics"])),
            }
            for key, value in reports.items()
        },
        "critical_cases": updated,
        "permission_change_complete": proof["complete"],
        "permission_change_severity": proof["summary"],
        "permission_change_diagnostics": proof["diagnostics"],
    }
    (args.output_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Повторный пилот: кандидаты и уровни error/warning",
        "",
        "Все 20 исходников совпали по SHA256 с первым пилотом; CI не включён.",
        "",
        "| Файл | Было strict | Стало strict | Стало grouped | Стало tuned |",
        "|---|---:|---:|---:|---:|",
    ]
    for file in files:
        lines.append(
            f"| `{file.removeprefix('marvel/skillstore/')}` | {before[file]} | {after['strict'][file]} | {after['grouped'][file]} | {after['tuned'][file]} |"
        )
    lines += [
        "",
        "## Проверка реальных пропусков",
        "",
        "| Участок | Раньше вообще не было owner | Теперь локальные кандидаты |",
        "|---|---|---|",
    ]
    for case in updated:
        labels = ", ".join(f"{u['kind']}:{u['line']}" for u in case["now_local_candidates"][:6]) or "нет"
        lines.append(f"| {case['id']}: {case['label']} | {case['before_no_owner']} | {labels} |")
    lines += [
        "",
        f"Изменение матрицы прав: complete={proof['complete']}; severity={proof['summary']}; diagnostics={len(proof['diagnostics'])}. Warning-only не блокирует; это не пропуск детекции.",
        "",
        "Количество кандидатов не является точностью. Tuned — объяснимый экспериментальный профиль. Фазы линейных side effects, динамический SQL и подробная семантика тестовых assertions не считаются полностью решёнными.",
    ]
    (args.output_dir / "comparison.md").write_text("\n".join(lines) + "\n")
    if args.benchmark_files:
        if not 1 <= args.benchmark_files <= 100:
            raise ValueError("benchmark-files must be between 1 and 100")
        originals = [
            {"path": f["file"], "source": (args.root / f["file"]).read_text()} for f in reports["tuned"]["files"]
        ]
        inputs = [
            dict(
                originals[i % len(originals)],
                path=f"benchmark/{i}/" + originals[i % len(originals)]["path"],
            )
            for i in range(args.benchmark_files)
        ]
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            parsed = guard.parse_sources(args, inputs)
            for item in inputs:
                if parsed[item["path"]].get("error"):
                    raise ValueError(parsed[item["path"]]["error"])
                guard.tuned_units(item["path"], parsed[item["path"]]["units"])
            timings.append(round(time.perf_counter() - start, 6))
        benchmark = {
            "files": len(inputs),
            "bytes": sum(len(item["source"].encode()) for item in inputs),
            "seconds": timings,
            "scope": "parsers and tuned grouping, process startup included; excludes VCS, source reads and spec validation",
        }
        (args.output_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2) + "\n")
        print(json.dumps(benchmark))
    print(json.dumps(summary["profiles"], ensure_ascii=False))
    if not proof["diagnostics"] or proof["summary"] != {"error": 0, "warning": 1} or not proof["complete"]:
        raise AssertionError("permission mutation must remain visible as one nonblocking warning")
    return 0


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
# Пилот должен проверять публичный контракт настроенной политики; успешная изолированная демонстрация не заменяет её результат.
def configured_pilot(args, manifest, files):
    output = args.output_dir / "audit-configured.json"
    command = [
        "audit",
        "--config",
        args.config,
        "--explain",
        "--root",
        str(args.root),
        "--go-parser",
        args.go_parser,
        "--node",
        args.node,
        "--node-modules",
        args.node_modules,
        "--json",
        "--output",
        str(output),
        "--files",
        *files,
    ]
    status = guard.main(command)
    if status not in (0, 1):
        raise ValueError("configured pilot did not complete")
    report = json.loads(output.read_text())
    if any(d["code"] == "SPEC008" for d in report["diagnostics"]):
        raise ValueError("configured pilot parser failure")
    if snapshot(args.root, files) != manifest:
        raise ValueError("pilot sources changed")
    (args.output_dir / "diagnostics.md").write_text(guard.markdown(report, "brief"))
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    summary = dict(
        files=len(files),
        source_bytes_unchanged=True,
        configured=report["summary"],
        seconds=report["analysis_seconds"],
        baseline=baseline.get("summary", {"diagnostics": len(baseline["diagnostics"])}) if baseline else None,
        policy=report["policy"],
    )
    # This is the same real mutation used by tune-v2, applied only to an in-memory revision.
    target = "marvel/skillstore/services/skillstore/internal/access/actions/actions.go"
    old = (args.root / target).read_text()
    needle = "HandoverAllPresets:    {idm.RoleAdmin},"
    if old.count(needle) != 1:
        raise ValueError("permission mutation fixture changed")
    new = old.replace(needle, "HandoverAllPresets:    {idm.RoleAdmin, idm.RoleUser},")

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    # Ослабления вспомогательного кода не должны разрешать незадокументированное изменение матрицы прав.
    class ReplayRepository(guard.Repository):
        # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
        # Сравнение должно использовать заявленные базовые и изменённые байты; подмена их одним состоянием скрыла бы регрессию доступа.
        def read(self, path, revision=None):
            if path == target:
                return new if revision == "review" else old
            return super().read(path)

    settings = SimpleNamespace(
        **vars(args),
        command="check",
        mode="brief",
        spec_root=guard.DEFAULT_SPEC_ROOT,
        added_files=set(),
        explain=True,
    )
    proof = guard.analyze(settings, ReplayRepository(args.root), [target], "review", "base")
    if not any(d["code"] == "SPEC_ACCESS" and d["severity"] == "error" for d in proof["diagnostics"]):
        raise ValueError("configured access mutation was not blocked")
    legacy_settings = SimpleNamespace(
        **{
            **vars(settings),
            "config": None,
            "granularity": "strict",
            "density_lines": 100,
        }
    )
    legacy_proof = guard.analyze(legacy_settings, ReplayRepository(args.root), [target], "review", "base")
    summary["legacy_permission_mutation"] = legacy_proof["summary"]
    if not legacy_proof["complete"]:
        raise ValueError("legacy mutation baseline changed; review comparison")
    summary["permission_mutation"] = proof["summary"]
    if args.review_labels:
        summary["review_replay"] = replay_review(args.root, report, args.review_labels)
        (args.output_dir / "review-replay.json").write_text(
            json.dumps(summary["review_replay"], ensure_ascii=False, indent=2) + "\n"
        )
        if summary["review_replay"]["lost_useful"] or summary["review_replay"]["remaining_excess"]:
            raise ValueError(
                "review replay found lost useful errors or retained excess errors; inspect review-replay.json"
            )
    (args.output_dir / "permission-mutation.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Конфигурационный пилот",
        "",
        "Исходные файлы совпали с зафиксированными SHA256. Сигналы не являются измерением precision/recall.",
        "",
        "| Файл | Error | Warning | Notice |",
        "|---|---:|---:|---:|",
    ]
    for path in files:
        issues = [d for d in report["diagnostics"] if d["file"] == path]
        counts = [sum(d["severity"] == level for d in issues) for level in ["error", "warning", "notice"]]
        lines.append(f"| {path} | {counts[0]} | {counts[1]} | {counts[2]} |")
    lines += [
        "",
        f"Итого: {report['summary']}; время: {report['analysis_seconds']} с.",
        f"Предыдущий сохранённый прогон: {summary['baseline']}.",
        "",
        "Мутация реальной матрицы прав блокируется SPEC_ACCESS. Источники не изменялись.",
        "",
        "[Диагностики и объяснения](diagnostics.md)",
    ]
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n")
    if args.benchmark_files:
        if not 1 <= args.benchmark_files <= 100:
            raise ValueError("benchmark-files must be between 1 and 100")
        from specguard_policy import Policy, Facts

        policy = Policy((args.root / args.config).read_text())
        originals = [(entry["file"], (args.root / entry["file"]).read_text()) for entry in report["files"]]
        inputs = [
            dict(
                path=f"benchmark/{i}/" + originals[i % len(originals)][0],
                source=originals[i % len(originals)][1],
            )
            for i in range(args.benchmark_files)
        ]
        timings = []
        for _ in range(3):
            started = time.perf_counter()
            parsed = guard.parse_sources(args, inputs)
            for item in inputs:
                data = parsed[item["path"]]
                if data.get("error"):
                    raise ValueError(f"{item['path']}: {data['error']}")
                policy.evaluate(Facts(item["path"], data), None, set())
            timings.append(round(time.perf_counter() - started, 6))
        benchmark = dict(
            files=len(inputs),
            seconds=timings,
            scope="parsers, normalized facts and configured rules; process startup included, excludes VCS/spec validation and report formatting",
        )
        (args.output_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2) + "\n")
        summary["benchmark"] = benchmark
        (args.output_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    compact = dict(summary)
    if "review_replay" in compact:
        compact["review_replay"] = {key: value for key, value in compact["review_replay"].items() if key != "rows"}
    print(json.dumps(compact, ensure_ascii=False))
    return 0


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
# Настройка шума недопустима, если вместе с лишними ошибками исчезают ранее подтверждённые обязательства покрытия.
def replay_review(root, report, manifest):
    sample = json.loads(manifest.read_text())
    scope = set(report["input_files"])
    rows = []
    for before in sample["sample"]:
        if before["file"] not in scope:
            continue
        data = (root / before["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != before["source_sha256"]:
            raise ValueError(f"review input changed: {before['file']}")
        same = [d for d in report["diagnostics"] if all(d.get(k) == before.get(k) for k in ["file", "line", "block"])]
        blocking = any(d["severity"] == "error" for d in same)
        rows.append(
            dict(
                review_id=before["review_id"],
                category=before["category"],
                file=before["file"],
                line=before["line"],
                block=before["block"],
                error_retained=blocking,
                levels=sorted({d["severity"] for d in same}),
            )
        )
    return dict(
        reviewed=len(rows),
        lost_useful=[r["review_id"] for r in rows if r["category"] == "useful" and not r["error_retained"]],
        remaining_excess=[
            r["review_id"] for r in rows if r["category"] in {"config_noise", "core_bug"} and r["error_retained"]
        ],
        rows=rows,
    )


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-6
# Неуспешный или неполный пилот не должен сообщать вызывающему процессу об успешной проверке.
if __name__ == "__main__":
    sys.exit(main())
