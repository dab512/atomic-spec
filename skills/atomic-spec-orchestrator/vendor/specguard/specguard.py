#!/usr/bin/env python3
"""atomic-spec-guard: deterministic requirement checker and context CLI."""

from __future__ import annotations

import hashlib
import argparse
import ast
import difflib
import json
import os
import re
import subprocess
import sys
import time
import tokenize
import io
from pathlib import Path, PurePosixPath
from collections import Counter
from copy import copy

from annotation_language import assess
from annotation_uniqueness import duplicate_diagnostics
from result_cache import cached_report
from local_enforcement import baseline as local_baseline
from urllib.parse import parse_qs, quote, urlparse

DEFAULT_SPEC_ROOT = "specs"
EXTENSIONS = {
    ".py",
    ".go",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
LIMIT = 8 * 1024 * 1024
# atomic-spec://ATOMIC-GUARD-001/DR-7
# Развёрнутые факты одного допустимого исходника могут быть больше текста; их отдельный бюджет остаётся конечным.
PARSER_OUTPUT_LIMIT = 32 * 1024 * 1024
RULE = re.compile(r"^(?:#{2,6}\s+|\s*[-*]\s+\*\*)(DR|BR|AC)-(\d+)\b", re.I)
ANCHOR = re.compile(r'^\s*<a\s+(?:id|name)=["\']([^"\']+)["\']\s*>\s*</a>\s*$')


# atomic-spec://ATOMIC-GUARD-001/DR-4
# Выбор пути не даёт права выйти за корень репозитория или сослаться на подставленный внешний источник.
def safe_path(path: str) -> str:
    parts = PurePosixPath(path)
    if parts.is_absolute() or ".." in parts.parts or "\\" in path or not parts.parts:
        raise ValueError("path must be repository-relative without traversal")
    return parts.as_posix()


# atomic-spec://ATOMIC-GUARD-001/DR-6
# Текст репозитория является данными и не должен получать возможность выполнить команды при проверке.
# atomic-spec://ATOMIC-GUARD-001/DR-7
# Полный вывод сверх бюджета отклоняется явно, а не превращается в усечённый успешный результат.
def command(args: list[str], cwd: Path, data: str | None = None, *, output_limit: int = LIMIT) -> str:
    result = subprocess.run(args, cwd=cwd, input=data, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError(f"{args[0]} failed (exit {result.returncode}): {result.stderr[:600]}")
    if len(result.stdout.encode()) > output_limit:
        raise ValueError(f"command output exceeds {output_limit / (1024 * 1024):g} MiB; narrow the selection")
    return result.stdout


# atomic-spec://ATOMIC-GUARD-001/DR-5
# Код, требования и контекст должны относиться к одной выбранной ревизии; смешение снимков делает вывод недостоверным.
class Repository:
    # atomic-spec://ATOMIC-GUARD-001/DR-5
    # Результат чтения из другого репозитория или ревизии не может подтверждать проверяемое состояние.
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cache: dict[tuple[str | None, str], str] = {}

    # atomic-spec://ATOMIC-GUARD-001/DR-4
    # Отсутствие доступного авторитетного файла означает отказ, а не разрешение выдумать или подставить его содержимое.
    def read(self, path: str, revision: str | None = None) -> str:
        path = safe_path(path)
        key = (revision, path)
        if key not in self.cache:
            if revision:
                if not re.fullmatch(r"[A-Za-z0-9_./-]+", revision) or revision.startswith("-"):
                    raise ValueError("invalid revision")
                value = command(["git", "show", f"{revision}:{path}"], self.root)
                # Git can return symlink blob text; it cannot be followed across revisions.
            else:
                file = (self.root / path).resolve()
                if not file.is_relative_to(self.root):
                    raise ValueError("symlink escapes repository")
                if file.stat().st_size > LIMIT:
                    raise ValueError("source exceeds 8 MiB")
                value = file.read_text(encoding="utf-8")
            self.cache[key] = value
        return self.cache[key]


# atomic-spec://ATOMIC-GUARD-001/DR-4
# Только объявленное требование подтверждает ссылку; упоминание ID или учебный пример не создают обязательства спецификации.
class Specification:
    # atomic-spec://ATOMIC-GUARD-001/DR-4
    # Документ с неполными метаданными или неоднозначными пунктами не может быть авторитетным источником покрытия.
    def __init__(self, text: str):
        self.text = text
        self.rules: dict[str, str] = {}
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise ValueError("specification requires frontmatter")
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration as error:
            raise ValueError("unterminated frontmatter") from error
        metadata = "".join(lines[1:end])
        if not re.search(r"^id:\s*\S+", metadata, re.M) or not re.search(r"^status:\s*\S+", metadata, re.M):
            raise ValueError("specification requires id and status")
        identity = re.search(r'^id:\s*["\']?([A-Za-z0-9_-]+)["\']?\s*$', metadata, re.M)
        if identity is None:
            raise ValueError("specification requires a simple explicit ID")
        self.id = identity.group(1)
        status = re.search(r'^status:\s*["\']?([\w-]+)', metadata, re.M).group(1)
        if status.lower() in {
            "deprecated",
            "superseded",
            "retired",
            "obsolete",
            "archived",
        }:
            raise ValueError(f"specification status is {status}")
        declarations: list[tuple[str, int]] = []
        boundaries: list[int] = []
        fence = ""
        pending: tuple[str, int] | None = None
        for i in range(end + 1, len(lines)):
            line = lines[i]
            marker = re.match(r"^\s*(`{3,}|~{3,})", line)
            if marker:
                token = marker.group(1)
                if not fence:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = ""
                continue
            if fence:
                continue
            anchor = ANCHOR.match(line)
            if anchor:
                pending = (anchor.group(1), i)
                continue
            match = RULE.match(line)
            if match:
                key = f"{match.group(1).lower()}-{match.group(2)}"
                start = i
                if pending:
                    if pending[0] != key:
                        raise ValueError(f"anchor {pending[0]} disagrees with declaration {key}")
                    start = pending[1]
                declarations.append((key, start))
                boundaries.append(start)
                pending = None
            elif re.match(r"^#{1,6}\s", line):
                boundaries.append(i)
                # A matching anchor immediately after a requirement heading is allowed.
                pending = None
            elif line.strip():
                pending = None
        for key, start in declarations:
            if key in self.rules:
                raise ValueError(f"duplicate requirement {key}")
            stop = min((b for b in boundaries if b > start), default=len(lines))
            self.rules[key] = "".join(lines[start:stop]).strip()


# atomic-spec://ATOMIC-GUARD-001/DR-4
# Ссылка подтверждает только существующий пункт допустимого источника; закреплённая ревизия не освобождает от проверки его актуальности.
def reference(value: str, spec_root: str, registry=None) -> tuple[str, str, str | None]:
    value = value.strip()
    parsed = urlparse(value)
    revision = None
    if parsed.scheme == "atomic-spec":
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9-]+", parsed.netloc)
            or not re.fullmatch(r"/(DR|BR|AC)-[1-9][0-9]*", parsed.path)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("atomic-spec reference must be atomic-spec://SPEC-ID/DR-N (or BR-N/AC-N)")
        if registry is None or parsed.netloc not in registry:
            raise ValueError(f"unregistered specification ID {parsed.netloc}")
        return reference(registry[parsed.netloc] + "#" + parsed.path[1:].lower(), spec_root)
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme != "https"
            or parsed.netloc != "code.example.invalid"
            or not parsed.path.startswith("/repository/")
        ):
            raise ValueError("only canonical repository viewer specification URLs are supported")
        path = parsed.path[len("/repository/") :]
        query = parse_qs(parsed.query, keep_blank_values=True)
        if set(query) != {"rev"} or len(query["rev"]) != 1 or not re.fullmatch(r"[0-9a-f]{40}", query["rev"][0]):
            raise ValueError("pinned link requires exactly one full commit rev")
        revision = query["rev"][0]
    else:
        if parsed.query:
            raise ValueError("local references cannot contain a query")
        path = parsed.path
    path = safe_path(path)
    if not path.startswith(spec_root.rstrip("/") + "/") or not path.endswith(".spec.md"):
        raise ValueError("reference is outside the configured specification root")
    if not re.fullmatch(r"(dr|br|ac)-[1-9][0-9]*", parsed.fragment):
        raise ValueError("reference requires an explicit dr-N, br-N or ac-N identifier")
    return path, parsed.fragment, revision


# atomic-spec://ATOMIC-GUARD-001/DR-13
# ID требования должен однозначно выбирать документ внутри заданного каталога; порядок записей не может разрешать неоднозначность.
def registry_for(repo, spec_root, revision):
    key = (revision, spec_root)
    cache = getattr(repo, "_registries", {})
    if key not in cache:
        # atomic-spec://ATOMIC-GUARD-001/DR-13
        # Два определения одного ID не дают права молча выбрать последнее: такая ссылка не имеет однозначного источника.
        def pairs(items):
            result = {}
            for name, value in items:
                if name in result:
                    raise ValueError(f"duplicate registry ID {name}")
                result[name] = value
            return result

        registry = json.loads(repo.read(spec_root + "/registry.json", revision), object_pairs_hook=pairs)
        if not isinstance(registry, dict):
            raise ValueError("specification registry must be an ID-to-path object")
        for name, path in registry.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9-]+", name) or not isinstance(path, str):
                raise ValueError("invalid registry ID or path")
            reference(safe_path(path) + "#dr-1", spec_root)
        cache[key] = registry
        repo._registries = cache
    return cache[key]


# atomic-spec://ATOMIC-GUARD-001/DR-13
# ID из URI должен совпасть с метаданными документа, а не просто указывать на существующий путь.
def validate_uri_identity(value, specification):
    parsed = urlparse(value)
    if parsed.scheme == "atomic-spec" and parsed.netloc != specification.id:
        raise ValueError(f"registry ID {parsed.netloc} disagrees with document ID {specification.id}")


# atomic-spec://ATOMIC-GUARD-001/DR-9
# Слова-подсказки являются лексическими токенами идентификаторов, а не доказательством важности бизнес-логики.
HINT_WORDS = frozenset(
    {
        "rule",
        "rules",
        "policy",
        "policies",
        "limit",
        "limits",
        "permission",
        "permissions",
        "capability",
        "capabilities",
        "auth",
        "authorization",
        "validation",
        "retry",
        "retries",
        "timeout",
        "backoff",
        "allow",
        "allowed",
        "deny",
        "denied",
        "gate",
        "readonly",
        "concurrency",
        "throttle",
        "throttling",
    }
)


# atomic-spec://ATOMIC-GUARD-001/DR-9
# Случайное совпадение части имени не является сигналом отдельного правила; кандидату требуется самостоятельное слово-подсказка.
def identifier_hints(name):
    # atomic-spec://ATOMIC-GUARD-001/DR-9
    # Составное имя может содержать сигнал правила, но ruler не означает rule: ложное сходство не должно порождать лишнюю диагностику.
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return sorted(set(re.findall(r"[a-z]+", name.lower())) & HINT_WORDS)


# atomic-spec://ATOMIC-GUARD-001/DR-3
# URI требует связанного с ним пояснения; произвольный соседний комментарий это условие не выполняет.
def annotation_lines(lines):
    refs, notes = [], []
    atomic = False
    for line in lines:
        if line.startswith("Spec:"):
            refs.append("legacy-spec:" + line[5:].strip())
            continue
        if line.startswith("atomic-spec://"):
            atomic = True
            parts = re.split(r"\s+(?://|—|-)\s*", line, maxsplit=1)
            refs.append(parts[0])
            if len(parts) == 2:
                notes.append(parts[1].strip())
        elif atomic and line and not line.startswith("http"):
            notes.append(line)
    notes = [note for note in notes if note and not note.startswith(("atomic-spec://", "http://", "https://", "Spec:"))]
    return refs, "\n".join(notes)


# atomic-spec://ATOMIC-GUARD-001/DR-8
# Покрытие Python должно относиться к реальным объявлениям и решениям, а не к похожему тексту внутри данных программы.
def python_source(item):
    path, source = item["path"], item["source"]
    try:
        tree = ast.parse(source, filename=path)
        lines = source.splitlines()
        comments = {
            token.start[0]: token.string[1:].strip()
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT and not lines[token.start[0] - 1][: token.start[1]].strip()
        }
        units = []
        ast_sizes = {}

        # atomic-spec://ATOMIC-GUARD-001/DR-15
        # Синтаксический размер служит воспроизводимой метрикой для политики; он не доказывает смысловую сложность блока.
        def measure(node):
            count = 1 + sum(measure(child) for child in ast.iter_child_nodes(node))
            ast_sizes[id(node)] = count
            return count

        measure(tree)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        # atomic-spec://ATOMIC-GUARD-001/DR-17
        # Ослабление для фикстуры допустимо только при подтверждённом происхождении её декоратора в соответствующей области кода.
        scope_bindings = {}

        # atomic-spec://ATOMIC-GUARD-001/DR-17
        # Локальное переопределение имени не должно давать постороннему коду льготу, предназначенную для настоящей фикстуры.
        def bindings(scope):
            key = id(scope)
            if key in scope_bindings:
                return scope_bindings[key]
            imported, assigned = {}, set()
            pending = list(getattr(scope, "body", []))
            for argument in ast.walk(scope.args) if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else []:
                if isinstance(argument, ast.arg):
                    assigned.add(argument.arg)
            while pending:
                child = pending.pop()
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    assigned.add(child.name)
                    continue
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        imported[alias.asname or alias.name.split(".")[0]] = alias.name
                elif isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        if alias.name != "*":
                            imported[alias.asname or alias.name] = (child.module or "") + "." + alias.name
                elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    assigned.add(child.id)
                pending.extend(ast.iter_child_nodes(child))
            scope_bindings[key] = (imported, assigned)
            return imported, assigned

        # atomic-spec://ATOMIC-GUARD-001/DR-17
        # Одного имени fixture недостаточно для ослабления покрытия: нужна подтверждённая связь с поддерживаемым тестовым API.
        def fixture(node):
            for decorator in node.decorator_list:
                expression = decorator.func if isinstance(decorator, ast.Call) else decorator
                parts = []
                while isinstance(expression, ast.Attribute):
                    parts.insert(0, expression.attr)
                    expression = expression.value
                if not isinstance(expression, ast.Name):
                    continue
                name = expression.id
                current = parents.get(node)
                while current:
                    if isinstance(
                        current,
                        (
                            ast.Module,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                            ast.ClassDef,
                        ),
                    ):
                        imported, assigned = bindings(current)
                        if name in assigned:
                            break
                        if name in imported:
                            target = ".".join([imported[name], *parts])
                            if target in {"pytest.fixture", "pytest_asyncio.fixture"}:
                                return True
                            break
                    current = parents.get(current)
            return False

        # atomic-spec://ATOMIC-GUARD-001/DR-8
        # Каждое обязательство Python-кода должно сохранять свою локацию и владельца; соседний блок не может ошибочно получить его пояснение.
        def emit(node, name, role="", kind=None, start=None, end=None):
            first = start or min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            last = end or node.end_lineno
            comment_start = first
            while comment_start - 1 in comments:
                comment_start -= 1
            text = [comments[n] for n in range(comment_start, first)]
            refs, prose = annotation_lines(text)
            header_end = (
                node.body[0].lineno - 1 if isinstance(getattr(node, "body", None), list) and node.body else first
            )
            unit_kind = kind or type(node).__name__
            column = node.col_offset + 1
            units.append(
                {
                    "id": f"{path}:{unit_kind}:{first}:{column}:{last}:{node.end_col_offset}",
                    "kind": unit_kind,
                    "ast_nodes": ast_sizes.get(id(node), 1),
                    "role": role,
                    "start": first,
                    "column": column,
                    "end": last,
                    "end_column": node.end_col_offset + 1,
                    "header_end": max(first, header_end),
                    "comment_start": comment_start,
                    "name": name,
                    "refs": refs,
                    "description": prose,
                }
            )

        # atomic-spec://ATOMIC-GUARD-001/DR-9
        # SQL может содержать важное правило работы с данными, но текст запроса не выполняет обязанность документировать это правило.
        def sql_text(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                return sql_text(node.left) + sql_text(node.right)
            if isinstance(node, ast.JoinedStr):
                return "".join(
                    part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "?"
                    for part in node.values
                )
            return ""

        kinds = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Match,
            ast.ExceptHandler,
        )
        for node in ast.walk(tree):
            if isinstance(node, kinds):
                role = (
                    "scenario"
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
                    else ""
                )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and fixture(node):
                    role = "fixture"
                if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Match)):
                    role = "decision"
                emit(node, (getattr(node, "name", None) or type(node).__name__), role)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                name = ", ".join(ast.unparse(t) for t in targets)
                if isinstance(parents.get(node), ast.Module) or identifier_hints(name):
                    emit(
                        node,
                        name,
                        "declaration" if isinstance(parents.get(node), ast.Module) else "local_declaration",
                    )
            if isinstance(node, ast.IfExp):
                emit(node, "conditional expression", "decision")
            if isinstance(node, ast.Call):
                callee = ast.unparse(node.func)
                if callee.endswith((".execute", ".executemany", ".query", ".executescript")) and node.args:
                    text = sql_text(node.args[0]).lstrip()
                    match = re.match(
                        r"(SELECT|INSERT|UPDATE|DELETE|WITH|ALTER|CREATE|DROP|TRUNCATE|MERGE)\b",
                        text,
                        re.I,
                    )
                    if match:
                        emit(
                            node,
                            "SQL " + match.group(1).upper() + " via " + callee,
                            "sql",
                            "SQLQuery",
                        )
                if (
                    callee == "pytest.mark.parametrize"
                    and len(node.args) > 1
                    and isinstance(node.args[1], (ast.List, ast.Tuple))
                ):
                    for index, case in enumerate(node.args[1].elts):
                        emit(case, f"pytest case {index + 1}", "test_case", "PytestCase")
            # Consecutive assertions are one oracle group, not N new requirements.
            for field in ("body", "orelse", "finalbody"):
                body = getattr(node, field, None)
                if not isinstance(body, list):
                    continue
                cluster = []
                for statement in body + [None]:
                    if isinstance(statement, ast.Assert):
                        cluster.append(statement)
                    elif cluster:
                        emit(
                            cluster[0],
                            f"assertion group ({len(cluster)})",
                            "oracle",
                            "AssertionGroup",
                            start=cluster[0].lineno,
                            end=cluster[-1].end_lineno,
                        )
                        cluster = []
        annotations = []
        pending = []
        for line in sorted(comments):
            if pending and line != pending[-1] + 1:
                refs, prose = annotation_lines([comments[n] for n in pending])
                if refs:
                    annotations.append(
                        dict(
                            kind="CommentGroup",
                            name="file annotation",
                            start=pending[0],
                            end=pending[-1],
                            comment_start=pending[0],
                            header_end=pending[0],
                            refs=refs,
                            description=prose,
                        )
                    )
                pending = []
            pending.append(line)
        if pending:
            refs, prose = annotation_lines([comments[n] for n in pending])
            if refs:
                annotations.append(
                    dict(
                        kind="CommentGroup",
                        name="file annotation",
                        start=pending[0],
                        end=pending[-1],
                        comment_start=pending[0],
                        header_end=pending[0],
                        refs=refs,
                        description=prose,
                    )
                )
        code_lines = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in {
                tokenize.COMMENT,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENDMARKER,
            }:
                code_lines.update(range(token.start[0], token.end[0] + 1))
        return {
            "path": path,
            "facts_version": 2,
            "units": units,
            "tokens": [ast.dump(tree)],
            "annotations": annotations,
            "generated": any(
                re.match(r"(?:Code generated .* DO NOT EDIT\.|@generated\b)", text, re.I) for text in comments.values()
            ),
            "code_lines": sorted(code_lines),
        }
    except (SyntaxError, tokenize.TokenError) as error:
        return {"path": path, "units": [], "error": str(error)}


# atomic-spec://ATOMIC-GUARD-001/DR-8
# Отсутствие подходящего парсера не должно превращать выбранный исходник в успешно проверенный файл.
def parse_sources(args, sources: list[dict]) -> dict[str, dict]:
    result = {item["path"]: python_source(item) for item in sources if item["path"].endswith(".py")}
    go = [item for item in sources if item["path"].endswith(".go")]
    other = [item for item in sources if not item["path"].endswith((".go", ".py"))]
    base = Path(__file__).resolve().parent
    if go:
        parser = args.go_parser or str(base / "goparser" / "goparser")
        parsed = json.loads(command([parser], args.root, json.dumps(go), output_limit=PARSER_OUTPUT_LIMIT))
        result.update({item["path"]: item for item in parsed})
    if other:
        modules = args.node_modules or str(base / "node_modules")
        parsed = json.loads(
            command(
                [args.node, str(base / "parser.cjs"), modules],
                args.root,
                json.dumps(other),
                output_limit=PARSER_OUTPUT_LIMIT,
            )
        )
        result.update({item["path"]: item for item in parsed})
    for path, data in result.items():
        if not data.get("error") and data.get("facts_version") != 2:
            data["error"] = "parser lacks URI-only facts v2; rebuild/update adapter"
            data["units"] = []
    return result


# atomic-spec://ATOMIC-GUARD-001/DR-2
# Учитываем границы удалений, чтобы удаление оператора не исключало проверку сохранившегося владельца.
def changed_lines(old: str, new: str) -> set[int]:
    changed = set()
    for tag, _, _, start, end in difflib.SequenceMatcher(
        None, old.splitlines(), new.splitlines(), autojunk=False
    ).get_opcodes():
        if tag != "equal":
            changed.update(range(start + 1, max(start + 2, end + 1)))
    return changed


# atomic-spec://ATOMIC-GUARD-001/DR-2
# В строгом режиме заголовок условия не наследует аннотацию родителя; операторы тела могут её наследовать.
def select_units(parsed: dict, changed: set[int] | None, audit=False) -> list[dict]:
    units = parsed["units"]
    if changed is None:
        return list({unit_key(unit): unit for unit in units if audit or unit.get("refs")}.values())
    selected = {}
    for line in changed:
        candidates = [u for u in units if u["start"] <= line <= u["end"]]
        if not candidates:
            continue
        candidates.sort(key=lambda u: (u["end"] - u["start"], -u["start"]))
        strict = [
            u
            for u in candidates
            if line <= u["header_end"]
            or u.get("role") == "sql"
            or u["kind"] in {"ConditionalExpression", "BinaryExpression", "JSXDecision", "SQLQuery"}
        ]
        if strict:
            owner = strict[0]
        else:
            owner = next((u for u in candidates if u.get("refs")), candidates[-1])
        selected[unit_key(owner)] = owner
    # Modified annotations must be validated even without changed executable tokens.
    for unit in units:
        if unit.get("refs") and any(
            unit.get("comment_start", unit["start"]) <= line < unit["start"] for line in changed
        ):
            selected[unit_key(unit)] = unit
    return list(selected.values())


# atomic-spec://ATOMIC-GUARD-001/DR-8
# Два самостоятельных узла не становятся одним обязательством только потому, что используют общее пояснение.
def unit_key(unit):
    return unit.get("id") or (
        unit["kind"],
        unit["start"],
        unit.get("column", 1),
        unit["end"],
        unit.get("end_column", 1),
    )


# atomic-spec://ATOMIC-GUARD-001/DR-9
# Группировка не должна скрывать вложенные запросы, сценарии и явные аннотации за общим крупным блоком.
def tuned_units(path, units, budget=100, roots=None):
    unique = list({unit_key(u): u for u in units}.values())
    roots = grouped_units(path, unique) if roots is None else roots
    yaml_paths = {u.get("config_path") for u in unique if u["kind"] in {"YAMLMapping", "YAMLSequence"}}
    chosen = {
        unit_key(u): u
        for u in roots
        if u.get("role") not in {"fixture", "test_container", "test_infrastructure", "micro_callback"}
    }
    for unit in unique:
        role = unit.get("role", "")
        hint_name = (unit.get("config_path") or unit.get("name") or "").rsplit(".", 1)[-1]
        hints = [] if unit["kind"] == "DeclarativeRule" else identifier_hints(hint_name)
        unit["hints"] = hints
        if unit.get("refs") or role in {"sql", "scenario"}:
            chosen[unit_key(unit)] = unit
        elif role == "config":
            # Record/map groups retain locality. Individual scalar facts remain in inventory.
            collection_shadow = (
                unit["kind"] in {"YAMLMappingGroup", "YAMLSequenceGroup"} and unit.get("config_path") in yaml_paths
            )
            if not collection_shadow and (
                unit["kind"]
                not in {
                    "YAMLScalar",
                    "YAMLSequenceScalar",
                    "PropertyAssignment",
                    "ShorthandPropertyAssignment",
                    "ConfigProperty",
                }
                or hints
            ):
                chosen[unit_key(unit)] = unit
        elif role == "decision" or unit["kind"] in {
            "ConditionalExpression",
            "BinaryExpression",
            "JSXDecision",
        }:
            ancestors = [v for v in roots if v["start"] <= unit["start"] and v["end"] >= unit["end"]]
            if (
                not ancestors
                or any(v["end"] - v["start"] + 1 > budget for v in ancestors)
                or unit.get("jsx")
                or unit.get("jsx_gate")
            ):
                # Adjacent/nested expressions of one decision tree share their outer context.
                if not any(
                    v.get("role") == "decision"
                    and v["start"] <= unit["start"]
                    and v["end"] >= unit["end"]
                    and unit_key(v) != unit_key(unit)
                    for v in chosen.values()
                ):
                    chosen[unit_key(unit)] = unit
        elif hints and role not in {"fixture", "micro_callback", "test_case", "oracle"}:
            chosen[unit_key(unit)] = unit
    return list(chosen.values())


# atomic-spec://ATOMIC-GUARD-001/DR-9
# Объединение синтаксиса сокращает шум, но не подтверждает, что вложенные решения реализуют одно бизнес-правило.
def grouped_units(path, units):
    by_range = {}
    for unit in units:
        key = (unit["start"], unit["end"])
        previous = by_range.get(key)
        if previous is None or unit.get("refs") or previous["kind"] == "*ast.GenDecl":
            by_range[key] = unit
    unique = list(by_range.values())
    # Interval ordering computes the same containment roots in O(n log n),
    # instead of comparing every pair of syntax nodes.
    root_keys = set()
    maximum_end = -1
    for unit in sorted(unique, key=lambda u: (u["start"], -u["end"])):
        if unit["end"] > maximum_end:
            root_keys.add(unit_key(unit))
            maximum_end = unit["end"]
    roots = [u for u in unique if unit_key(u) in root_keys]
    if path.endswith((".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx")):
        scenarios = [u for u in unique if u["name"].startswith(("it(", "test(", "it.", "test."))]
        helpers = [u for u in roots if not u["name"].startswith(("describe(", "describe."))]
        return list({unit_key(u): u for u in scenarios + helpers}.values())
    return roots


# atomic-spec://ATOMIC-GUARD-001/DR-2
# Последовательные и вложенные ветви образуют кандидатов для ревью, но не выдуманные бизнес-правила.
def branch_clusters(source, units, budget=80):
    kinds = {
        "*ast.IfStmt",
        "*ast.ForStmt",
        "*ast.RangeStmt",
        "*ast.SwitchStmt",
        "*ast.TypeSwitchStmt",
        "*ast.SelectStmt",
        "*ast.CaseClause",
        "*ast.CommClause",
        "IfStatement",
        "SwitchStatement",
        "CaseClause",
        "DefaultClause",
        "ForStatement",
        "ForInStatement",
        "ForOfStatement",
        "WhileStatement",
        "DoStatement",
        "If",
        "For",
        "AsyncFor",
        "While",
        "Match",
    }
    ordered = sorted(
        (u for u in units if u.get("kind") in kinds),
        key=lambda u: (u["start"], -u["end"]),
    )
    selected = []
    for unit in ordered:
        if not unit.get("refs") and any(p["start"] <= unit["start"] and p["end"] >= unit["end"] for p in selected):
            continue
        selected.append(unit)
    lines = source.splitlines()
    clusters = []
    for unit in selected:
        previous = clusters[-1] if clusters else None
        gap = lines[previous["end_line"] : unit["start"] - 1] if previous else []
        # Only directly adjacent siblings (blank/comment gap) merge. Calls/assignments
        # are hard boundaries: no lexical guess that they are mere plumbing.
        adjacent = previous and all(
            not line.strip() or line.lstrip().startswith(("//", "#", "/*", "*")) for line in gap
        )
        same_rule = not unit.get("refs")
        if adjacent and same_rule and unit["end"] - previous["line"] + 1 <= budget:
            previous["end_line"] = unit["end"]
            previous["members"].append(unit["name"])
        else:
            clusters.append(
                {
                    "line": unit["start"],
                    "end_line": unit["end"],
                    "members": [unit["name"]],
                    "over_budget": unit["end"] - unit["start"] + 1 > budget,
                }
            )
    return clusters


# atomic-spec://ATOMIC-GUARD-001/DR-10
# Уровень следует закрытому синтаксическому контракту, а не важности имени или уверенности модели.
def annotation_severity(unit):
    advisory_roles = {
        "config",
        "declaration",
        "local_declaration",
        "sql",
        "fixture",
        "test_container",
        "test_infrastructure",
        "micro_callback",
        "test_case",
        "oracle",
    }
    if unit.get("role") in advisory_roles and not (
        unit.get("role") == "declaration" and unit["kind"] == "TypeAliasDeclaration"
    ):
        return "warning"
    if unit["kind"] == "CapabilityGate":
        return "warning"
    structural = {
        "*ast.FuncDecl",
        "*ast.FuncLit",
        "*ast.TypeSpec",
        "*ast.IfStmt",
        "*ast.ForStmt",
        "*ast.RangeStmt",
        "*ast.SwitchStmt",
        "*ast.TypeSwitchStmt",
        "*ast.SelectStmt",
        "*ast.CaseClause",
        "*ast.CommClause",
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "FunctionDeclaration",
        "FunctionExpression",
        "ArrowFunction",
        "MethodDeclaration",
        "Constructor",
        "ClassDeclaration",
        "InterfaceDeclaration",
        "TypeAliasDeclaration",
        "EnumDeclaration",
        "ExceptHandler",
    }
    return "error" if unit["kind"] in structural or unit.get("role") in {"decision", "scenario"} else "warning"


# atomic-spec://ATOMIC-GUARD-001/DR-10
# Блокируют только определённые ошибки; рекомендательные кандидаты остаются видимыми и учитываются отдельно.
def diagnostic_summary(diagnostics):
    return {level: sum(d["severity"] == level for d in diagnostics) for level in ("error", "warning")}


# atomic-spec://ATOMIC-GUARD-001/DR-26
# Смысловое ревью должно видеть физические пояснения, а не повторные представления их владельцев.
def comment_entries(path, source, parsed, changed):
    entries, seen = [], set()
    lines = source.splitlines()
    for group in parsed.get("annotations") or []:
        if not group.get("refs"):
            continue
        first, last = group["start"], group["end"]
        span = (first, group.get("column", 1), last, group.get("end_column", 1))
        if span in seen:
            continue
        seen.add(span)
        owners = [
            dict(line=u["start"], end_line=u["end"], block=u["name"], node_kind=u["kind"])
            for u in parsed["units"]
            if u.get("refs") and u.get("comment_start", u["start"]) == first
        ]
        if changed is not None and not any(
            first <= line <= last or any(owner["line"] <= line <= owner["end_line"] for owner in owners)
            for line in changed
        ):
            continue
        entries.append(
            dict(
                file=path,
                line=first,
                end_line=last,
                column=span[1],
                end_column=span[3],
                refs=list(dict.fromkeys(group["refs"])),
                description=group.get("description", ""),
                owners=owners,
                source="\n".join(lines[first - 1 : last]),
            )
        )
    return sorted(entries, key=lambda item: (item["line"], item["column"]))


# atomic-spec://ATOMIC-GUARD-001/DR-5
# Контекст должен сохранять все места применения требования; устранение повторов самого требования не разрешает терять локации.
def analyze(
    args,
    repo: Repository,
    files: list[str],
    revision: str | None,
    base_revision: str | None,
):
    if getattr(args, "config", None):
        return analyze_configured(args, repo, files, revision, base_revision)
    start_time = time.perf_counter()
    excluded, sources, old_sources = [], [], {}
    for path in dict.fromkeys(files):
        path = safe_path(path)
        if PurePosixPath(path).suffix not in EXTENSIONS or PurePosixPath(path).name in {
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        }:
            excluded.append({"file": path, "reason": "unsupported or dependency lock"})
            continue
        source = repo.read(path, revision)
        if re.search(
            r"(?mi)^(?://|#)\s*(?:Code generated .* DO NOT EDIT\.|@generated\b)",
            source[:2000],
        ):
            excluded.append({"file": path, "reason": "generated"})
            continue
        if base_revision:
            try:
                old_sources[path] = repo.read(path, base_revision)
            except (ValueError, FileNotFoundError):
                # A missing base file is new only when Git confirms this in the diff.
                if path not in args.added_files:
                    raise
                old_sources[path] = ""
        sources.append({"path": path, "source": source})
    parsed = parse_sources(args, sources)
    old_parsed = (
        parse_sources(
            args,
            [{"path": p, "source": text} for p, text in old_sources.items() if text],
        )
        if old_sources
        else {}
    )
    diagnostics, specs, blocks, locations, file_stats = [], {}, {}, {}, []
    comments = []
    for item in sources:
        path, source = item["path"], item["source"]
        data = parsed[path]
        groups = grouped_units(path, data["units"])
        file_stats.append(
            {
                "file": path,
                "lines": len(source.splitlines()),
                "units": len(data["units"]),
                "grouped_units": len(groups),
                "large_groups": [
                    {"line": u["start"], "end_line": u["end"], "block": u["name"]}
                    for u in groups
                    if u["end"] - u["start"] + 1 > args.density_lines
                ],
                "parse_error": data.get("error"),
                "syntax_units": data["units"] if args.command == "audit" else [],
                "branch_clusters": (
                    branch_clusters(source, data["units"], args.density_lines) if args.command == "audit" else []
                ),
            }
        )
        tuned = tuned_units(path, data["units"], args.density_lines, roots=groups)
        file_stats[-1]["tuned_units"] = len(tuned)
        file_stats[-1]["type_counts"] = dict(Counter(u["kind"] for u in data["units"]))
        if args.command == "audit" and args.granularity in {"grouped", "tuned"}:
            data = dict(data, units=groups if args.granularity == "grouped" else tuned)
        if data.get("error"):
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "SPEC008",
                    "file": path,
                    "line": 1,
                    "block": "",
                    "message": data["error"],
                }
            )
            continue
        changed = None
        if base_revision:
            old = old_sources[path]
            # Token fingerprints ignore formatting/comments, but annotations remain checked.
            previous = old_parsed.get(path, {})
            if previous.get("error"):
                raise ValueError(f"cannot parse base revision of {path}: {previous['error']}")
            changed = changed_lines(old, source)
            if data.get("tokens") == previous.get("tokens"):
                changed = {
                    line
                    for line in changed
                    if any(
                        u.get("refs") and u.get("comment_start", u["start"]) <= line < u["start"] for u in data["units"]
                    )
                }
        if args.command == "comments":
            comments.extend(comment_entries(path, source, data, changed))
        # atomic-spec://ATOMIC-GUARD-001/DR-10
        # Размер остаётся подсказкой для ревью даже у полностью размеченного блока, а не новым обязательством.
        if args.command in {"audit", "check"}:
            for group in groups:
                if group["end"] - group["start"] + 1 > args.density_lines and (
                    changed is None or any(group["start"] <= n <= group["end"] for n in changed)
                ):
                    diagnostics.append(
                        {
                            "severity": "warning",
                            "code": "SPEC010",
                            "file": path,
                            "line": group["start"],
                            "end_line": group["end"],
                            "block": group["name"],
                            "node_kind": group["kind"],
                            "message": "long group: review annotation density; no separate requirement is inferred",
                        }
                    )
        selected = select_units(data, changed, args.command == "audit")
        if args.command == "comments":
            selected_starts = {u.get("comment_start", u["start"]) for u in selected if u.get("refs")}
            exported_starts = {c["line"] for c in comments if c["file"] == path}
            selected += [
                g
                for g in data.get("annotations") or []
                if g["start"] in exported_starts and g["start"] not in selected_starts
            ]
        for unit in selected:
            location = {
                "file": path,
                "line": unit["start"],
                "end_line": unit["end"],
                "block": unit["name"],
                "node_kind": unit.get("kind", "unknown"),
            }
            refs = unit.get("refs", [])
            if not refs:
                diagnostics.append(
                    dict(
                        location,
                        severity=annotation_severity(unit),
                        code="SPEC001",
                        message=(
                            "missing adjacent description and Spec reference"
                            if annotation_severity(unit) == "error"
                            else "review candidate: adjacent description and Spec reference not found"
                        ),
                    )
                )
                continue
            if not unit.get("description", "").strip():
                diagnostics.append(
                    dict(
                        location,
                        severity="error",
                        code="SPEC002",
                        message="Spec reference requires a separate nonempty description",
                    )
                )
            for value in refs:
                try:
                    if not value.startswith("atomic-spec://"):
                        raise ValueError(
                            "only bare atomic-spec:// annotations are supported; remove Spec: and repository-path markers"
                        )
                    registry = (
                        registry_for(repo, args.spec_root, revision) if value.startswith("atomic-spec:") else None
                    )
                    spec_path, identifier, pinned = reference(value, args.spec_root, registry)
                    spec_key = (revision, spec_path)
                    if spec_key not in specs:
                        specs[spec_key] = Specification(repo.read(spec_path, revision))
                    spec = specs[spec_key]
                    validate_uri_identity(value, spec)
                    if identifier not in spec.rules:
                        raise ValueError(f"requirement {identifier} does not exist")
                    if pinned:
                        pin_key = (pinned, spec_path)
                        if pin_key not in specs:
                            specs[pin_key] = Specification(repo.read(spec_path, pinned))
                        if specs[pin_key].rules.get(identifier) != spec.rules[identifier]:
                            raise ValueError(f"pinned requirement {identifier} differs from the reviewed revision")
                    key = (spec_path, identifier)
                    blocks[key] = spec.rules[identifier]
                    if location not in locations.setdefault(key, []):
                        locations[key].append(location)
                except (ValueError, OSError) as error:
                    diagnostics.append(
                        dict(
                            location,
                            severity="error",
                            code="SPEC004",
                            message=f"{value}: {error}",
                        )
                    )
    requirements = [
        {
            "spec": p,
            "requirement": rule,
            "text": text,
            "locations": locations[(p, rule)],
        }
        for (p, rule), text in sorted(blocks.items())
    ]
    documents = [{"path": path, "text": specs[(revision, path)].text} for path in sorted({p for p, _ in blocks})]
    summary = diagnostic_summary(diagnostics)
    return {
        "schema_version": 2,
        "complete": summary["error"] == 0,
        "summary": summary,
        "has_warnings": summary["warning"] > 0,
        "revision": revision or "working-tree",
        "base": base_revision,
        "requirements": requirements,
        "documents": documents if args.mode == "full" else [],
        "excluded": excluded,
        "files": file_stats,
        "comments": comments,
        "diagnostics": diagnostics,
        "analysis_seconds": round(time.perf_counter() - start_time, 6),
    }


# atomic-spec://ATOMIC-GUARD-001/DR-2
# Удаление блока целиком не создаёт обязанность у соседа; удаление аннотации сохраняет обязанность её владельца.
def configured_changes(old, new, previous, current):
    operations = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes()
    changed = set()
    for tag, first, last, start, end in operations:
        if tag == "equal":
            continue
        if tag != "delete":
            changed.update(range(start + 1, end + 1))
        else:
            for owner in previous.get("units", []):
                if (
                    owner["start"] <= first + 1
                    and owner["end"] >= last
                    and (owner["start"] < first + 1 or owner["end"] > last)
                ):
                    if any(
                        u["kind"] == owner["kind"]
                        and u["name"] == owner["name"]
                        and u["start"] <= start + 1 <= u["end"]
                        for u in current["units"]
                    ):
                        changed.add(start + 1)
                        break
    if current.get("tokens") == previous.get("tokens"):
        changed = {
            line
            for line in changed
            if any(u.get("comment_start", u["start"]) <= line <= u["end"] for u in (current.get("annotations") or []))
        }
        for owner in previous.get("units", []):
            if not owner.get("refs"):
                continue
            comment = owner.get("comment_start", owner["start"])
            if not any(
                tag != "equal" and first < owner["start"] - 1 and last >= comment
                for tag, first, last, _, _ in operations
            ):
                continue
            for tag, first, last, start, _ in operations:
                if tag == "equal" and first <= owner["start"] - 1 < last:
                    target = start + owner["start"] - first
                    if any(
                        u["kind"] == owner["kind"] and u["name"] == owner["name"] and u["start"] == target
                        for u in current["units"]
                    ):
                        changed.add(target)
                    break
    return changed


# atomic-spec://ATOMIC-GUARD-001/DR-19
# Выбор YAML или JSON не меняет обязательства политики; происхождение результата должно отражать именно исходную конфигурацию.
def policy_document(args, path, text):
    if len(text.encode()) > 256 * 1024:
        raise ValueError("policy exceeds 256 KiB")
    if PurePosixPath(path).suffix not in {".yaml", ".yml"}:
        return text
    base = Path(__file__).resolve().parent
    modules = args.node_modules or str(base / "node_modules")
    return command([args.node, str(base / "policy.cjs"), modules], base, text)


# atomic-spec://ATOMIC-GUARD-001/DR-1
# Исключённый путь не требует чтения исходника: его байты не должны влиять на допуск или результат кеша.
def source_exclusion(path, policy):
    exclusion = policy.exclude_file(path)
    if exclusion:
        return exclusion
    if PurePosixPath(path).suffix not in EXTENSIONS or PurePosixPath(path).name in {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
    }:
        return dict(id="unsupported", reason="unsupported or dependency lock")
    return None


# atomic-spec://ATOMIC-GUARD-001/DR-16
# Одна выбранная политика определяет обязательства всех команд; ослабление кандидата не разрешает принимать невалидную явную ссылку.
def analyze_configured(args, repo, files, revision, base_revision):
    # Optional configured mode: legacy standalone callers do not load policy code.
    from specguard_policy import Policy, Facts, annotation_key

    start_time = time.perf_counter()
    config_path = safe_path(args.config)
    config_text = repo.read(config_path, revision)
    policy = Policy(policy_document(args, config_path, config_text), getattr(args, "profile", None))
    if (
        getattr(args, "cache_dir", None)
        and not getattr(args, "no_cache", False)
        and not getattr(args, "cache_worker", False)
    ):
        worker = copy(args)
        worker.cache_worker = True
        return cached_report(
            worker,
            repo,
            files,
            revision,
            base_revision,
            analyze_configured,
            cacheable=lambda path: source_exclusion(safe_path(path), policy) is None,
        )
    sources, old_sources, excluded, diagnostics = [], {}, [], []
    for path in dict.fromkeys(files):
        path = safe_path(path)
        exclusion = source_exclusion(path, policy)
        if exclusion:
            reason = exclusion["reason"]
            excluded.append(dict(file=path, reason=reason, exclusion=exclusion["id"]))
            diagnostics.append(
                dict(
                    code="SPEC_NOTICE",
                    severity="notice",
                    file=path,
                    line=1,
                    block="",
                    message=reason,
                )
            )
            continue
        source = repo.read(path, revision)
        sources.append(dict(path=path, source=source))
        if base_revision:
            try:
                old_sources[path] = repo.read(path, base_revision)
            except (ValueError, FileNotFoundError):
                if path not in args.added_files:
                    raise
                old_sources[path] = ""
    parsed = parse_sources(args, sources)
    old_parsed = (
        parse_sources(args, [dict(path=p, source=s) for p, s in old_sources.items() if s]) if old_sources else {}
    )
    specs, blocks, locations, statistics, traces = {}, {}, {}, [], []
    comments = []
    language_seen = set()
    for item in sources:
        path, source = item["path"], item["source"]
        data = parsed[path]
        if data.get("error"):
            diagnostics.append(
                dict(
                    code="SPEC008",
                    severity="error",
                    file=path,
                    line=1,
                    block="",
                    message=data["error"],
                )
            )
            continue
        if data.get("facts_version") != 2:
            diagnostics.append(
                dict(
                    code="SPEC008",
                    severity="error",
                    file=path,
                    line=1,
                    block="",
                    message="parser lacks URI-only facts v2; rebuild/update adapter",
                )
            )
            continue
        if data.get("generated"):
            excluded.append(dict(file=path, reason="generated parser comment", exclusion="generated"))
            diagnostics.append(
                dict(
                    code="SPEC_NOTICE",
                    severity="notice",
                    file=path,
                    line=1,
                    block="",
                    message="generated parser comment",
                )
            )
            continue
        # atomic-spec://ATOMIC-GUARD-001/DR-23
        # Файловая уникальность пояснений проверяется отдельно от валидности ссылок и обязательств покрытия.
        diagnostics.extend(duplicate_diagnostics(policy, data, path))
        facts = Facts(path, data)
        if base_revision and old_parsed.get(path, {}).get("error"):
            raise ValueError(f"cannot parse base revision of {path}")
        changed = (
            configured_changes(old_sources[path], source, old_parsed.get(path, {}), data) if base_revision else None
        )
        if args.command == "comments":
            comments.extend(comment_entries(path, source, data, changed))
        valid, seen, annotation_locations = set(), set(), {}
        annotated = [u for u in data["units"] + (data.get("policy_units") or []) if u.get("refs")]
        annotated += data.get("annotations") or []
        for unit in annotated:
            key = annotation_key(unit)
            if key in seen:
                continue
            seen.add(key)
            location = dict(
                file=path,
                line=unit["start"],
                end_line=unit["end"],
                block=unit["name"],
                node_kind=unit["kind"],
            )
            annotation_locations[key] = location
            good = bool(unit.get("description", "").strip())
            if not good:
                diagnostics.append(
                    dict(
                        location,
                        code="SPEC002",
                        severity="error",
                        message="Spec reference requires nonempty explanation",
                    )
                )
            for value in unit["refs"]:
                try:
                    if not value.startswith("atomic-spec://"):
                        raise ValueError(
                            "only bare atomic-spec:// annotations are supported; remove Spec: and repository-path markers"
                        )
                    registry = (
                        registry_for(repo, args.spec_root, revision) if value.startswith("atomic-spec:") else None
                    )
                    spec_path, identifier, pinned = reference(value, args.spec_root, registry)
                    spec_key = (revision, spec_path)
                    if spec_key not in specs:
                        specs[spec_key] = Specification(repo.read(spec_path, revision))
                    spec = specs[spec_key]
                    validate_uri_identity(value, spec)
                    if identifier not in spec.rules:
                        raise ValueError(f"requirement {identifier} does not exist")
                    if pinned:
                        pin_key = (pinned, spec_path)
                        if pin_key not in specs:
                            specs[pin_key] = Specification(repo.read(spec_path, pinned))
                        if specs[pin_key].rules.get(identifier) != spec.rules[identifier]:
                            raise ValueError(f"pinned requirement {identifier} differs from reviewed revision")
                    target = (spec_path, identifier)
                    # atomic-spec://ATOMIC-GUARD-001/DR-22
                    # Язык пояснения не определяет валидность ссылки: рекомендательное нарушение не ломает её покрытие.
                    if policy.annotation_language and unit.get("description", "").strip():
                        result = assess(
                            unit["description"],
                            spec.rules[identifier],
                            policy.annotation_language,
                        )
                        language_key = (path, key, result["expected_language"])
                        if result["status"] != "pass" and language_key not in language_seen:
                            language_seen.add(language_key)
                            diagnostic = policy.annotation_language["diagnostic"]
                            measured = dict(
                                path=path,
                                start=unit["start"],
                                end=unit["end"],
                                name=unit["name"],
                                kind=unit["kind"],
                                requirement=f"{spec_path}#{identifier}",
                                **result,
                            )
                            issue = policy.emit(diagnostic, measured, "annotation-language", "")
                            issue.update(result, requirement=measured["requirement"])
                            diagnostics.append(issue)
                    blocks[target] = spec.rules[identifier]
                    if location not in locations.setdefault(target, []):
                        locations[target].append(location)
                except (ValueError, OSError) as error:
                    good = False
                    diagnostics.append(
                        dict(
                            location,
                            code="SPEC004",
                            severity="error",
                            message=f"{value}: {error}",
                        )
                    )
            if good:
                valid.add(key)
        issues, explanation = policy.evaluate(facts, changed, valid, getattr(args, "explain", False))
        if base_revision:
            selected_keys = policy.context_keys | {key for key in annotation_locations if key[0] in (changed or set())}
            allowed_locations = [annotation_locations[key] for key in selected_keys if key in annotation_locations]
            for target in list(locations):
                locations[target] = [
                    loc for loc in locations[target] if loc["file"] != path or loc in allowed_locations
                ]
                if not locations[target]:
                    del locations[target]
                    blocks.pop(target, None)
        diagnostics.extend(issues)
        traces.extend(explanation)
        statistics.append(
            dict(
                file=path,
                lines=len(source.splitlines()),
                units=len(facts.units),
                annotations=len(valid),
                type_counts=dict(Counter(u["node"] for u in facts.units)),
            )
        )
    for issue in diagnostics:
        if issue["code"] in policy.diagnostics and "title" not in issue:
            rendered = policy.emit(
                issue["code"],
                dict(
                    path=issue["file"],
                    start=issue["line"],
                    end=issue.get("end_line", issue["line"]),
                    name=issue.get("block", ""),
                    kind=issue.get("node_kind", ""),
                ),
                issue.get("rule", ""),
                issue["message"],
            )
            issue.update({key: rendered[key] for key in ["title", "message", "hint", "group_by"]})
    summary = {level: sum(d["severity"] == level for d in diagnostics) for level in ["error", "warning", "notice"]}
    return dict(
        schema_version=3,
        complete=summary["error"] == 0,
        summary=summary,
        has_warnings=summary["warning"] > 0,
        revision=revision or "working-tree",
        base=base_revision,
        policy=dict(
            path=config_path,
            sha256=hashlib.sha256(config_text.encode()).hexdigest(),
            profiles=policy.profiles,
            version=1,
            local_enforcement=policy.local_enforcement,
        ),
        requirements=[
            dict(spec=p, requirement=r, text=t, locations=locations[(p, r)]) for (p, r), t in sorted(blocks.items())
        ],
        documents=(
            [dict(path=p, text=specs[(revision, p)].text) for p in sorted({p for p, _ in blocks})]
            if args.mode == "full"
            else []
        ),
        excluded=excluded,
        files=statistics,
        comments=comments,
        diagnostics=diagnostics,
        explanations=traces,
        analysis_seconds=round(time.perf_counter() - start_time, 6),
    )


# atomic-spec://ATOMIC-GUARD-001/DR-21
# Явный выбор каталога ограничен бюджетами; зависимости, кеши и symlink не обходятся.
DIRECTORY_MAX_FILES = 1000
DIRECTORY_MAX_ENTRIES = 20000
DIRECTORY_MAX_BYTES = 16 * 1024 * 1024
DIRECTORY_SKIP = {
    "node_modules",
    "vendor",
    ".git",
    ".vcs",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    ".run",
}


# atomic-spec://ATOMIC-GUARD-001/DR-21
# Пользователь должен знать все пропуски выбранного поддерева; превышение бюджета не даёт права выдать усечённый результат за полный.
def directory_files(repo, value):
    relative = safe_path(value)
    origin = repo.root / relative
    if origin == repo.root or not origin.is_dir():
        raise ValueError("--directory must name an existing project subdirectory")
    for parent in [origin, *origin.parents]:
        if parent == repo.root:
            break
        if parent.is_symlink():
            raise ValueError("--directory cannot traverse a symlink")
    stack, files, excluded = [origin], [], []
    visited, total = 0, 0
    while stack:
        current = stack.pop()
        entries = []
        with os.scandir(current) as iterator:
            for entry in iterator:
                visited += 1
                if visited > DIRECTORY_MAX_ENTRIES:
                    raise ValueError("--directory entry limit exceeded; narrow the directory")
                entries.append(entry)
        for entry in sorted(entries, key=lambda e: e.name, reverse=True):
            path = Path(entry.path)
            name = path.relative_to(repo.root).as_posix()
            reason = ""
            if entry.is_symlink():
                reason = "directory selection: symlink not followed"
            elif entry.is_dir(follow_symlinks=False):
                if entry.name in DIRECTORY_SKIP or entry.name.startswith(".run-"):
                    reason = "directory selection: dependency/cache/build directory skipped"
                else:
                    stack.append(path)
                    continue
            elif entry.is_file(follow_symlinks=False):
                if path.suffix not in EXTENSIONS or entry.name in {
                    "package-lock.json",
                    "yarn.lock",
                    "pnpm-lock.yaml",
                }:
                    reason = "directory selection: unsupported format or dependency lock"
                else:
                    files.append(name)
                    total += entry.stat(follow_symlinks=False).st_size
                    if len(files) > DIRECTORY_MAX_FILES:
                        raise ValueError("--directory file limit exceeded; narrow the directory")
                    if total > DIRECTORY_MAX_BYTES:
                        raise ValueError("--directory source byte limit exceeded; narrow the directory")
                    continue
            else:
                reason = "directory selection: non-regular entry skipped"
            excluded.append(dict(file=name, reason=reason, exclusion="directory-discovery"))
    return sorted(files), sorted(excluded, key=lambda item: item["file"])


# atomic-spec://ATOMIC-GUARD-001/DR-18
# Все сохранённые Git-изменения читаются без строкового угадывания путей и без запуска проверяемого кода.
def git_status(root, scope):
    raw = command(
        ["git", "-c", "status.renames=false", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", scope],
        root,
    )
    groups = {"changed": [], "untracked": []}
    for record in raw.split("\0"):
        if not record:
            continue
        state, path = record[:2], record[3:]
        if "\n" in path or "\t" in path or state.startswith(("R", "C")):
            raise ValueError("Unsupported ambiguous Git path or rename")
        safe_path(path)
        groups["untracked" if state == "??" else "changed"].append({"type": "file", "path": path})
    return {"status": groups}


# atomic-spec://ATOMIC-GUARD-001/DR-5
# Контекст PR обязан соответствовать авторитетным base/merge; локальное состояние не может подменять проверяемую ревизию.
def resolve_inputs(args, repo):
    revision, base_revision = args.revision, args.base
    args.directory_excluded = []
    args.local_changed_files = set()
    args.untracked_files = set()
    if getattr(args, "directory", None):
        if args.files or args.pr or revision or base_revision:
            raise ValueError(
                "--directory is exclusive with --files/--pr/--base/--revision; use audit for whole directories"
            )
        files, args.directory_excluded = directory_files(repo, args.directory)
        args.added_files = set()
        return files, None, None
    working_tree = getattr(args, "working_tree", False)
    if working_tree and (revision or args.pr or not base_revision):
        raise ValueError("--working-tree requires --base and excludes --revision/--pr")
    if args.pr:
        if args.files or revision or base_revision:
            raise ValueError("--pr is exclusive with --files/--base/--revision")
        raise ValueError("Use explicit Git --base/--revision; --pr is not supported by the Git adapter")
    # atomic-spec://ATOMIC-GUARD-001/DR-1
    # Одна область анализа не меняется от записи пути: алиасы не должны терять ошибки исходника или обходить выбор diff.
    files = list(dict.fromkeys(safe_path(path) for path in (args.files or [])))
    args.added_files = set()
    if base_revision:
        target = revision or "HEAD"
        # Name-status identifies additions/deletions without guessing from a failed read.
        output = command(
            [
                "git",
                "-c",
                "core.quotePath=false",
                "diff",
                "--no-ext-diff",
                "--no-renames",
                "--name-status",
                base_revision,
            ]
            + ([] if working_tree else [target])
            + ["--", args.scope],
            repo.root,
        )
        changes = []
        for line in output.splitlines():
            status, sep, path = line.partition("\t")
            if not sep:
                fields = line.split(maxsplit=1)
                if len(fields) != 2:
                    raise ValueError("unrecognized Git name-status output")
                status, path = fields
            if status.startswith("D"):
                continue
            if status.startswith("R") or status.startswith("C"):
                raise ValueError("rename/copy diff needs explicit normalization; not silently skipped")
            if status not in {"A", "M"}:
                raise ValueError(f"unsupported diff status {status}")
            changes.append(path)
            if status == "A":
                args.added_files.add(path)
        # atomic-spec://ATOMIC-GUARD-001/DR-18
        # Локальный допуск относится к сохранённой рабочей правке, включая новые файлы; прежний коммит не подтверждает её корректность.
        if working_tree:
            status = git_status(repo.root, args.scope)
            if base_revision == "HEAD":
                args.local_changed_files.update(changes)
            for entries in status.get("status", {}).values():
                if isinstance(entries, list):
                    args.local_changed_files.update(
                        item["path"]
                        for item in entries
                        if isinstance(item, dict) and item.get("type") == "file" and "path" in item
                    )
            for item in status.get("status", {}).get("untracked", []):
                if item.get("type") != "file":
                    raise ValueError("unexpanded untracked path in local status")
                path = safe_path(item["path"])
                changes.append(path)
                args.added_files.add(path)
                args.untracked_files.add(path)
        files = list(dict.fromkeys(p for p in changes if not files or p in files))
        revision = None if working_tree else target
    if not files and not base_revision:
        raise ValueError("pass --files FILE... or --pr ID or --base REV")
    return files, revision, base_revision


# atomic-spec://ATOMIC-GUARD-001/DR-11
# Локации ведут в точный неизменяемый снимок либо локальный файл, а не в угаданный HEAD.
def location_link(report, location):
    path, line = location["file"], location["line"]
    label = f"{path}:{line}".replace("[", r"\[").replace("]", r"\]")
    revision = report["revision"]
    if re.fullmatch(r"[0-9a-f]{40}", revision):
        if not report.get("repository_url"):
            return f"{label} (revision {revision})"
        target = f"{report['repository_url']}/blob/{revision}/{quote(path, safe='/')}#L{line}"
    else:
        target = f"{Path(report['source_root']) / path}:{line}"
        target = "<" + target.replace(">", "%3E").replace("<", "%3C") + ">"
    return f"[{label}]({target})"


# atomic-spec://ATOMIC-GUARD-001/DR-11
# Компактность отчёта не оправдывает потерю нарушений: общая подсказка обязана сохранять каждую точную локацию.
def diagnostic_groups(report):
    actions = {
        "SPEC001": "Добавьте пояснение и Spec-ссылку",
        "SPEC002": "Добавьте отдельную строку о смысле требования",
        "SPEC004": "Исправьте ссылку на существующее актуальное требование",
        "SPEC008": "Исправьте синтаксис или настройку парсера",
        "SPEC010": "Проверьте разбиение длинного блока; отдельная ссылка не обязательна",
    }
    grouped = {}
    for item in report["diagnostics"]:
        extra = tuple((field, item.get(field)) for field in item.get("group_by", []) if field not in {"code"})
        grouped.setdefault((item["severity"], item["code"], extra), []).append(item)
    lines = []
    for (level, code, _extra), items in sorted(
        grouped.items(),
        key=lambda pair: (
            {"error": 0, "warning": 1, "notice": 2}[pair[0][0]],
            pair[0][1],
            str(pair[0][2]),
        ),
    ):
        action = (
            "Проверьте, нужна ли кандидату отдельная разметка"
            if level == "warning" and code == "SPEC001"
            else actions.get(code, "Проверьте диагностику")
        )
        action = items[0].get("title", action)
        if level == "notice":
            lines += [
                "<details>",
                f"<summary>notice {code} · {len(items)} — {action}</summary>",
                "",
            ]
        lines += [f"### {level} {code} · {len(items)} — {action}", ""]
        if items[0].get("hint"):
            lines += [items[0]["hint"], ""]
        by_file = {}
        for item in items:
            by_file.setdefault(item["file"], []).append(item)
        for file_items in by_file.values():
            references = []
            for item in sorted(file_items, key=lambda d: (d["line"], d.get("block", ""))):
                block = item.get("block", "").replace("`", "'").replace("\n", " ")
                if len(block) > 120:
                    block = block[:117] + "..."
                detail = (
                    f" — {item['message']}" if code in {"SPEC004", "SPEC008", "SPEC_NOTICE"} or item.get("rule") else ""
                )
                references.append(f"{location_link(report, item)} `{block}`{detail}")
            lines.append("- " + "; ".join(references))
        lines.append("")
        if level == "notice":
            lines += ["</details>", ""]
    if report.get("explanations"):
        lines += ["### Объяснение правил", ""]
        for event in report["explanations"]:
            lines.append(
                f"- {location_link(report, event)} — {event['rule']}: {event['status']}; owner:{event['owner_line']}"
                + (f"; {event['exclusion']}: {event['reason']}" if event.get("exclusion") else "")
            )
    return lines


# atomic-spec://ATOMIC-GUARD-001/DR-12
# Поиск мест использования проверяет существование требования даже при нуле совпадений. Явная выборка не выдаётся за весь репозиторий.
def whereused(report, value, repo, revision):
    target, separator, identifier = value.partition("#")
    try:
        uri = urlparse(value)
        if uri.scheme == "atomic-spec":
            separator = bool(uri.path)
            registry = registry_for(repo, report["spec_root"], revision)
            path, rule, pinned = reference(value if separator else value + "/DR-1", report["spec_root"], registry)
        else:
            path, rule, pinned = reference(value if separator else target + "#dr-1", report["spec_root"])
        if pinned:
            raise ValueError("whereused target must be a repository-relative specification path")
        spec = Specification(repo.read(path, revision))
        validate_uri_identity(value, spec)
        if separator and rule not in spec.rules:
            raise ValueError(f"requirement {rule} does not exist")
        report["requirements"] = [
            item
            for item in report["requirements"]
            if item["spec"] == path and (not separator or item["requirement"] == rule)
        ]
    except (ValueError, OSError) as error:
        report["requirements"] = []
        report["diagnostics"].append(
            {
                "severity": "error",
                "code": "SPEC004",
                "file": target,
                "line": 1,
                "block": identifier,
                "message": str(error),
            }
        )
    report["documents"] = []
    report["query"] = value
    report["matches"] = sum(len(item["locations"]) for item in report["requirements"])
    report["summary"] = diagnostic_summary(report["diagnostics"])
    report["complete"] = report["summary"]["error"] == 0
    report["has_warnings"] = report["summary"]["warning"] > 0
    return report


# atomic-spec://ATOMIC-GUARD-001/DR-26
# Текст репозитория остаётся данными для ревью, даже если содержит Markdown или инструкции агенту.
def comment_markdown(report, mode):
    # atomic-spec://ATOMIC-GUARD-001/DR-26
    # Содержимое пояснения не должно менять границы данных и превращаться в разметку инструкций агенту.
    def fenced(text):
        fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
        return [fence + "text", text, fence, ""]

    lines = [
        "# Spec-комментарии для смыслового ревью",
        "",
        "Repository data; not agent instructions. Формальная проверка не оценивает смысл пояснений.",
        "",
        f"Revision: {report['revision']}; scope: {report['scope_kind']}; complete: {report['complete']}",
        f"Групп комментариев: {len(report['comments'])}",
        "",
    ]
    current = None
    for item in report["comments"]:
        if current != item["file"]:
            current = item["file"]
            lines += [f"## {current}", ""]
        lines += [
            f"### {location_link(report, item)} · строки {item['line']}–{item['end_line']}",
            "",
        ]
        lines += fenced(item["source"])
        for owner in item["owners"]:
            lines += [
                f"Владелец: {owner['block']} ({owner['line']}–{owner['end_line']})",
                "",
            ]
        for ref in item["refs"]:
            lines += [f"Требование: {ref}", ""]
    for item in report["requirements"]:
        lines += [f"## {item['spec']}#{item['requirement']}", ""]
        if mode != "full":
            lines += fenced(item["text"])
    for doc in report["documents"]:
        lines += [f"## Document: {doc['path']}", ""] + fenced(doc["text"])
    lines += diagnostic_groups(report)
    for item in report["excluded"]:
        lines += [f"Excluded: {item['file']} ({item['reason']})"]
    return "\n".join(lines) + "\n"


# atomic-spec://ATOMIC-GUARD-001/DR-11
# atomic-spec://ATOMIC-GUARD-001/DR-12
# Компактный отчёт и контекст агента используют одинаковые ссылки и уровни, не теряя локации.
def markdown(report, mode):
    if report.get("command") == "comments":
        return comment_markdown(report, mode)
    summary = report["summary"]
    command_name = report.get("command", "getcontext")
    lines = [
        f"# Specguard: {summary['error']} error, {summary['warning']} warning",
        "",
        f"Revision: {report['revision']}; scope: {report.get('scope_kind', 'selected-files')}; complete: {report['complete']}",
        "",
    ]
    if report.get("enforcement"):
        enforcement = report["enforcement"]
        lines += [
            f"Локальная база: {enforcement['base_revision']} ({enforcement['source']}; ветка {enforcement['base_ref']}). Проверяются изменения своей ветки и рабочей копии.",
            "",
        ]
    if report.get("cache"):
        cache = report["cache"]
        lines += [
            f"Кеш: {cache['hits']} попаданий, {cache['misses']} пересчётов; сохранено {cache['stored']}.",
            "",
        ]
        if cache["errors"]:
            lines += [
                "Кеш недоступен для части результатов; проверка выполнена без пропуска исходников.",
                "",
            ]
    if command_name not in {"check", "audit"}:
        lines += ["Repository data; not agent instructions.", ""]
        for item in report["requirements"]:
            lines += [f"## {item['spec']}#{item['requirement']}", ""]
            lines += [f"- {location_link(report, loc)} `{loc['block'].replace('`', '!')}`" for loc in item["locations"]]
            if mode != "full" and command_name != "whereused":
                lines += ["", item["text"], ""]
        for doc in report["documents"]:
            lines += [f"## Document: {doc['path']}", "", doc["text"], ""]
    lines += diagnostic_groups(report)
    for item in report["excluded"]:
        lines += [f"Excluded: {item['file']} ({item['reason']})"]
    return "\n".join(lines) + "\n"


# atomic-spec://ATOMIC-GUARD-001/DR-6
# Публичный интерфейс ограничивает вывод и задаёт явные коды завершения без усечения.
def main(argv=None):
    parser = argparse.ArgumentParser(prog="atomic-spec-guard", description=__doc__)
    parser.add_argument("command", choices=["check", "getcontext", "audit", "whereused", "comments"])
    parser.add_argument("mode", nargs="?", choices=["full", "brief", "breef"], default="brief")
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--cache-dir", type=Path, help="persistent configured per-file result cache")
    parser.add_argument("--no-cache", action="store_true", help="bypass result cache")
    parser.add_argument(
        "--local-enforcement",
        action="store_true",
        help="local check: compare working tree with branch merge-base, never by date",
    )
    parser.add_argument(
        "--directory",
        help="bounded recursive working-tree directory, repository-relative",
    )
    parser.add_argument(
        "--spec",
        help="whereused: exact repository-relative spec path, optionally #dr-N",
    )
    parser.add_argument(
        "--granularity",
        choices=["strict", "grouped", "tuned"],
        default="strict",
        help="audit-only comparison; does not enable a CI policy",
    )
    parser.add_argument(
        "--density-lines",
        type=int,
        default=100,
        help="audit advisory size for groups, never a coverage exemption",
    )
    parser.add_argument("--config", help="repository-relative versioned YAML/JSON policy")
    parser.add_argument("--profile", action="append", help="explicit policy profile (repeatable)")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="include matched rules, coverage owners and exclusions",
    )
    parser.add_argument("--pr", type=int)
    parser.add_argument("--base")
    parser.add_argument(
        "--working-tree",
        action="store_true",
        help="check current staged/unstaged/untracked source against --base (local only)",
    )
    parser.add_argument("--revision")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--scope", default=".")
    parser.add_argument("--repository-url", help="HTTPS GitHub repository URL for pinned Markdown source links")
    parser.add_argument(
        "--spec-root",
        default=DEFAULT_SPEC_ROOT,
        help="repository-relative specification directory containing registry.json",
    )
    parser.add_argument("--node", default="node")
    parser.add_argument("--node-modules")
    parser.add_argument("--go-parser")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_intermixed_args(argv)
    args.mode = "brief" if args.mode == "breef" else args.mode
    try:
        if args.repository_url:
            if not re.fullmatch(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", args.repository_url):
                raise ValueError("--repository-url requires an HTTPS GitHub-style owner/repository URL")
            args.repository_url = args.repository_url.rstrip("/").removesuffix(".git")
        if args.local_enforcement and (args.command != "check" or not args.working_tree or not args.config):
            raise ValueError("--local-enforcement requires configured check --working-tree")
        if args.cache_dir and not args.config:
            raise ValueError("--cache-dir requires --config")
        if (args.profile or args.explain) and not args.config:
            raise ValueError("--profile/--explain require --config")
        if args.density_lines < 1:
            raise ValueError("--density-lines must be positive")
        if (args.command == "whereused") != bool(args.spec):
            raise ValueError("--spec is required only for whereused")
        args.root = args.root or Path(command(["git", "rev-parse", "--show-toplevel"], Path.cwd()).strip())
        repo = Repository(args.root)
        args.spec_root = safe_path(args.spec_root)
        enforcement = None
        if args.local_enforcement:
            from specguard_policy import Policy

            config_path = safe_path(args.config)
            policy = Policy(
                policy_document(args, config_path, repo.read(config_path, None)),
                args.profile,
            )
            if policy.local_enforcement is None:
                raise ValueError("local check requires local_enforcement.base_ref in policy")
            enforcement = local_baseline(args, repo, policy.local_enforcement, command)
        files, revision, base_revision = resolve_inputs(args, repo)
        if args.command == "check" and not base_revision:
            raise ValueError("check requires --base or --pr; getcontext supports whole files")
        if args.command == "comments":
            args.no_cache = True
        report = analyze(args, repo, files, revision, base_revision)
        if enforcement:
            report["enforcement"] = enforcement
        for item in getattr(args, "directory_excluded", []):
            report["excluded"].append(item)
            report["diagnostics"].append(
                dict(
                    code="SPEC_NOTICE",
                    severity="notice",
                    file=item["file"],
                    line=1,
                    block="",
                    message=item["reason"],
                )
            )
        if getattr(args, "directory_excluded", []):
            report["summary"] = diagnostic_summary(report["diagnostics"])
        report.update(
            command=args.command,
            source_root=str(repo.root),
            repository_url=args.repository_url,
            spec_root=args.spec_root,
            scope_kind=(
                "directory"
                if args.directory
                else (
                    "working-tree-diff"
                    if args.working_tree
                    else "pr-diff"
                    if args.pr
                    else "changed-files"
                    if base_revision
                    else "selected-files"
                )
            ),
            input_files=files,
        )
        if args.command == "comments":
            report["comments"].sort(key=lambda item: (item["file"], item["line"], item["column"]))
        if args.command == "whereused":
            report = whereused(report, args.spec, repo, revision)
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.json else markdown(report, args.mode)
        if len(output.encode()) > LIMIT:
            raise ValueError("context exceeds 8 MiB; narrow the selection (nothing was truncated)")
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0 if report["complete"] else 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"error SPEC900: {error}", file=sys.stderr)
        return 2


# atomic-spec://ATOMIC-GUARD-001/DR-6
# Неполная проверка не должна выглядеть успешной для вызывающей системы и разрешать зависящие от неё действия.
if __name__ == "__main__":
    sys.exit(main())
