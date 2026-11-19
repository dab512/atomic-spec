"""File-local duplicate explanation checks over parser-proven annotation groups."""

import unicodedata


# atomic-spec://ATOMIC-GUARD-001/DR-23
# Каноническая форма Unicode, регистр и лишние пробелы не превращают скопированное пояснение в новое.
def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


# atomic-spec://ATOMIC-GUARD-001/DR-23
# Разные группы одного файла обязаны иметь разные пояснения; повторное представление одной группы не является нарушением уникальности.
def duplicate_diagnostics(policy, parsed, path):
    if policy.annotation_uniqueness is None:
        return []
    groups, seen, owners = {}, set(), {}
    for unit in parsed["units"]:
        if unit.get("refs"):
            owners.setdefault(unit.get("comment_start", unit["start"]), unit["name"])
    for group in parsed.get("annotations") or []:
        if not group.get("refs") or not group.get("description", "").strip():
            continue
        span = (
            group["start"],
            group.get("column", 1),
            group["end"],
            group.get("end_column", 1),
        )
        if span in seen:
            continue
        seen.add(span)
        key = normalized(group["description"])
        owner = owners.get(group["start"], group["name"])
        groups.setdefault(key, []).append(
            dict(
                path=path,
                start=group["start"],
                end=group["end"],
                name=owner,
                kind=group["kind"],
            )
        )
    diagnostics = []
    for occurrences in groups.values():
        if len(occurrences) < 2:
            continue
        for index, location in enumerate(occurrences):
            origin = occurrences[1 if index == 0 else 0]
            measured = dict(
                location,
                duplicate_count=len(occurrences),
                duplicate_origin=f"{origin['path']}:{origin['start']}",
            )
            issue = policy.emit(
                policy.annotation_uniqueness["diagnostic"],
                measured,
                "annotation-uniqueness",
                "",
            )
            issue.update(
                duplicate_count=len(occurrences),
                duplicate_origin=dict(file=origin["path"], line=origin["start"]),
            )
            diagnostics.append(issue)
    return diagnostics
