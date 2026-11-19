"""Общая база ветки задаёт область локальной проверки без календарных исключений."""

import re


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
# Настройка должна однозначно называть базовую ветку; произвольный текст не определяет область проверки.
def validate(settings):
    if not isinstance(settings, dict) or set(settings) != {"base_ref"}:
        raise ValueError("local_enforcement requires only base_ref, not a date")
    value = settings["base_ref"]
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}", value):
        raise ValueError("local_enforcement.base_ref must name a branch")
    return value


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-25
# Проверке подлежат изменения своей ветки от общей базы с trunk; неизвестная база не даёт права пропустить проверку.
def baseline(args, repo, settings, run):
    base_ref = validate(settings)
    if args.base:
        return dict(base_ref=base_ref, base_revision=args.base, source="explicit")
    value = run(["git", "merge-base", "--all", "HEAD", base_ref], repo.root).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("cannot determine a single full merge-base revision")
    args.base = value
    return dict(base_ref=base_ref, base_revision=value, source="merge-base")
