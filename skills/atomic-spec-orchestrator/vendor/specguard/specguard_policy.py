"""Versioned declarative policy engine; consumes parser facts without executing source."""

from bisect import bisect_left, bisect_right
from functools import lru_cache
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from string import Formatter
import json
import re

from local_enforcement import validate as validate_local_enforcement

# atomic-spec://ATOMIC-GUARD-001/DR-14
# Закрытая схема отвергает опечатки и неподдерживаемую семантику до анализа исходников.
LEVELS = {"error", "warning", "notice"}
NODES = {
    "function",
    "type",
    "decision",
    "declaration",
    "config",
    "sql",
    "scenario",
    "fixture",
    "call",
    "comment",
    "other",
}
FIELDS = {
    "path",
    "language",
    "node",
    "kind",
    "role",
    "name",
    "symbol",
    "operator",
    "config_path",
}
METRICS = {
    "span_lines",
    "code_lines",
    "unit_count",
    "decision_depth",
    "depth",
    "ast_nodes",
}
PARAMETERS = (
    FIELDS
    | METRICS
    | {
        "rule",
        "reason",
        "actual_annotations",
        "required_annotations",
        "expected_language",
        "actual_language",
        "duplicate_count",
        "duplicate_origin",
        "requirement",
    }
)
FUNCTIONS = {
    "*ast.FuncDecl",
    "*ast.FuncLit",
    "FunctionDef",
    "AsyncFunctionDef",
    "FunctionDeclaration",
    "FunctionExpression",
    "ArrowFunction",
    "MethodDeclaration",
    "Constructor",
}
TYPES = {
    "*ast.TypeSpec",
    "ClassDef",
    "ClassDeclaration",
    "InterfaceDeclaration",
    "TypeAliasDeclaration",
    "EnumDeclaration",
}
DECISIONS = {
    "*ast.IfStmt",
    "*ast.ForStmt",
    "*ast.RangeStmt",
    "*ast.SwitchStmt",
    "*ast.TypeSwitchStmt",
    "*ast.SelectStmt",
    "*ast.CaseClause",
    "*ast.CommClause",
    "If",
    "For",
    "AsyncFor",
    "While",
    "Match",
    "ExceptHandler",
}


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Опечатка или пропуск обязательного поля не может молча менять действующую политику проверки.
def keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"invalid configuration fields; expected {sorted(allowed)}, required {sorted(required)}")


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Связи между настройками должны быть заданы явно; пустое или выведенное из кода имя не определяет правило политики.
def strings(value):
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ValueError("expected a list of nonempty strings")
    return value


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Идентификатор настройки не должен позволять подменить структуру шаблона или смысл ссылки между правилами.
def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", value):
        raise ValueError(f"invalid configuration identifier: {value!r}")


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Пользовательский шаблон поиска не должен превращать быструю проверку в неограниченное вычисление.
@lru_cache(maxsize=512)
def pattern(value):
    if (
        not isinstance(value, str)
        or len(value) > 256
        or any(c in value for c in "(){}")
        or re.search(r"\\[1-9]", value)
    ):
        raise ValueError("regex must be <=256 characters without groups, braces or backreferences")
    if any(len(re.findall(r"(?<!\\)[*+?]", branch)) > 1 for branch in value.replace("[^.]+", "X").split("|")):
        raise ValueError("regex permits at most one repetition per alternative; use glob for paths")
    try:
        return re.compile(value)
    except re.error as error:
        raise ValueError(f"invalid regex: {error}") from error


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Политика может требовать только поддерживаемые предикаты и измерения; неизвестное условие не означает успешное совпадение.
def selector(value, depth=0):
    keys(value, FIELDS | {"metrics", "all", "any", "not", "ancestor", "descendant"})
    if depth > 8:
        raise ValueError("selector nesting exceeds 8")
    for name, condition in value.items():
        if name in {"all", "any"}:
            if not isinstance(condition, list) or not condition:
                raise ValueError(f"{name} requires a nonempty selector list")
            for child in condition:
                selector(child, depth + 1)
        elif name in {"not", "ancestor", "descendant"}:
            selector(condition, depth + 1)
        elif name == "metrics":
            keys(condition, METRICS)
            for limits in condition.values():
                keys(limits, {"gt", "gte", "lt", "lte", "eq"})
                if not limits or any(type(n) is not int or n < 0 for n in limits.values()):
                    raise ValueError("metric bounds must be nonnegative integers")
        else:
            keys(condition, {"eq", "in", "glob", "regex"})
            if len(condition) != 1:
                raise ValueError("field selector requires exactly one operator")
            op, argument = next(iter(condition.items()))
            values = strings(argument) if op == "in" else [argument]
            if not all(isinstance(v, str) and len(v) <= 512 for v in values):
                raise ValueError("selector values must be bounded strings")
            if name == "node" and op in {"eq", "in"} and set(values) - NODES:
                raise ValueError("unknown normalized node type")
            if op == "regex":
                pattern(argument)


# atomic-spec://ATOMIC-GUARD-001/DR-15
# Одинаковые обязательства покрытия должны применяться к сопоставимым конструкциям разных языков без выдумывания их бизнес-смысла.
def node_type(unit):
    kind, role = unit["kind"], unit.get("role", "")
    if kind == "CommentGroup":
        return "comment"
    if role == "scenario":
        return "scenario"
    if role in {
        "fixture",
        "test_container",
        "test_infrastructure",
        "test_case",
        "oracle",
        "micro_callback",
    }:
        return "fixture"
    if kind in FUNCTIONS:
        return "function"
    if kind in TYPES:
        return "type"
    if role == "sql":
        return "sql"
    if kind == "PolicyCall":
        return "call"
    if kind in DECISIONS or role == "decision":
        return "decision"
    if role == "config":
        return "config"
    if role in {"declaration", "local_declaration"} or kind in {
        "PolicyMutation",
        "VariableStatement",
        "*ast.GenDecl",
        "*ast.ValueSpec",
    }:
        return "declaration"
    return "other"


# atomic-spec://ATOMIC-GUARD-001/DR-15
# Порог покрытия опирается на измеримый синтаксис; размер и вложенность не являются доказательством отдельного бизнес-правила.
class Facts:
    # atomic-spec://ATOMIC-GUARD-001/DR-15
    # Метрики и владельцы должны описывать один и тот же исходный блок: иначе порог или наследование покрытия применятся к чужому коду.
    def __init__(self, path, parsed):
        self.path = path
        self.units = []
        ext = PurePosixPath(path).suffix
        language = {".py": "python", ".go": "go", ".yaml": "yaml", ".yml": "yaml"}.get(
            ext, "typescript" if ext in {".ts", ".tsx"} else "javascript"
        )
        code_lines = sorted(set((parsed.get("code_lines") or [])))
        seen = set()
        for original in parsed["units"] + (parsed.get("policy_units") or []):
            unit = dict(original)
            signature = (
                unit["kind"],
                unit["start"],
                unit.get("column", 1),
                unit["end"],
                unit.get("end_column", 1),
            )
            if signature in seen:
                continue
            seen.add(signature)
            unit.update(
                path=path,
                language=language,
                node=node_type(unit),
                parent=None,
                children=[],
            )
            unit["span_lines"] = unit["end"] - unit["start"] + 1
            unit["code_lines"] = bisect_right(code_lines, unit["end"]) - bisect_left(code_lines, unit["start"])
            unit["unit_count"] = 1
            unit["decision_depth"] = int(unit["node"] == "decision")
            self.units.append(unit)
        self.units.sort(
            key=lambda u: (
                u["start"],
                u.get("column", 1),
                -u["end"],
                -u.get("end_column", 1),
            )
        )
        stack = []
        for unit in self.units:
            while stack and not self.contains(stack[-1], unit):
                stack.pop()
            if stack:
                unit["parent"] = stack[-1]
                stack[-1]["children"].append(unit)
            unit["depth"] = len(stack)
            stack.append(unit)
        for unit in reversed(self.units):
            parent = unit["parent"]
            if parent:
                parent["unit_count"] += unit["unit_count"]
                parent["decision_depth"] = max(
                    parent["decision_depth"],
                    int(parent["node"] == "decision") + unit["decision_depth"],
                )
        self.match_cache = {}

    # atomic-spec://ATOMIC-GUARD-001/DR-15
    # Соседний узел на той же строке не является родителем и не даёт права наследовать его разметку.
    @staticmethod
    def contains(parent, child):
        a = (parent["start"], parent.get("column", 1))
        b = (parent["end"], parent.get("end_column", 1))
        c = (child["start"], child.get("column", 1))
        d = (child["end"], child.get("end_column", 1))
        # atomic-spec://ATOMIC-GUARD-001/DR-15
        # Secondary Call того же вызова сценария сохраняет его владельца; соседний равный по строке код сюда не попадает.
        registration_call = a == c and b == d and parent["node"] == "scenario" and child["node"] == "call"
        return a <= c and b >= d and (a != c or b != d or registration_call)

    # atomic-spec://ATOMIC-GUARD-001/DR-14
    # Повторная оценка одного условия на неизменном блоке обязана давать тот же результат; ускорение не может менять решение политики.
    def matches(self, select, unit):
        key = (id(select), id(unit))
        if key in self.match_cache:
            return self.match_cache[key]
        result = self._matches(select, unit)
        self.match_cache[key] = result
        return result

    # atomic-spec://ATOMIC-GUARD-001/DR-14
    # Решение политики зависит только от объявленных предикатов и фактов кода, а не от исполнения произвольной логики из конфига.
    def _matches(self, select, unit):
        for field, condition in select.items():
            if field == "all":
                ok = all(self.matches(s, unit) for s in condition)
            elif field == "any":
                ok = any(self.matches(s, unit) for s in condition)
            elif field == "not":
                ok = not self.matches(condition, unit)
            elif field == "ancestor":
                parent, ok = unit["parent"], False
                while parent:
                    if self.matches(condition, parent):
                        ok = True
                        break
                    parent = parent["parent"]
            elif field == "descendant":
                pending, ok = list(unit["children"]), False
                while pending:
                    child = pending.pop()
                    if self.matches(condition, child):
                        ok = True
                        break
                    pending.extend(child["children"])
            elif field == "metrics":
                operators = {
                    "gt": lambda a, b: a > b,
                    "gte": lambda a, b: a >= b,
                    "lt": lambda a, b: a < b,
                    "lte": lambda a, b: a <= b,
                    "eq": lambda a, b: a == b,
                }
                ok = all(
                    operators[op](unit.get(metric, 0), n)
                    for metric, limits in condition.items()
                    for op, n in limits.items()
                )
            else:
                actual = str(unit.get(field, ""))
                op, argument = next(iter(condition.items()))
                if op == "eq":
                    ok = actual == argument
                elif op == "in":
                    ok = actual in argument
                elif op == "glob":
                    ok = fnmatchcase(actual, argument)
                else:
                    if len(actual) > 4096:
                        raise ValueError("regex input exceeds 4096 characters")
                    ok = bool(pattern(argument).search(actual))
            if not ok:
                return False
        return True


# atomic-spec://ATOMIC-GUARD-001/DR-14
# Политика является данными с явными профилями, сообщениями и исключениями конкретных правил.
class Policy:
    # atomic-spec://ATOMIC-GUARD-001/DR-14
    # Рабочая политика должна иметь однозначные правила, параметры и выбранные профили; некорректные настройки не дают допустимого результата проверки.
    def __init__(self, text, profiles=None):
        if len(text.encode()) > 256 * 1024:
            raise ValueError("policy exceeds 256 KiB")

        # atomic-spec://ATOMIC-GUARD-001/DR-14
        # Дубли JSON-ключей вызывают отказ, а не молча перезаписывают предыдущие правила.
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError(f"duplicate configuration key {key}")
                result[key] = value
            return result

        try:
            self.config = json.loads(text, object_pairs_hook=pairs)
        except RecursionError as error:
            raise ValueError("configuration nesting exceeds decoder limit") from error
        c = self.config
        keys(
            c,
            {
                "version",
                "files",
                "diagnostics",
                "rules",
                "profiles",
                "default_profiles",
                "exclusions",
                "parameters",
                "annotation_language",
                "annotation_uniqueness",
                "local_enforcement",
            },
            {
                "version",
                "files",
                "diagnostics",
                "rules",
                "profiles",
                "default_profiles",
                "exclusions",
            },
        )
        parameters = c.get("parameters", {})
        if not isinstance(parameters, dict) or not all(
            isinstance(k, str) and type(v) in {str, int, bool} for k, v in parameters.items()
        ):
            raise ValueError("policy parameters must be named scalar values")
        for name in parameters:
            identity(name)

        # atomic-spec://ATOMIC-GUARD-001/DR-14
        # Порог правила и его объяснение должны использовать одно объявленное значение; иначе диагностика вводит автора в заблуждение.
        def expand(value):
            if isinstance(value, dict):
                if set(value) == {"parameter"}:
                    if not isinstance(value["parameter"], str) or value["parameter"] not in parameters:
                        raise ValueError("unknown parameter reference")
                    return parameters[value["parameter"]]
                return {k: expand(v) for k, v in value.items()}
            if isinstance(value, list):
                return [expand(v) for v in value]
            return value

        c = self.config = expand(c)
        if type(c["version"]) is not int or c["version"] != 1:
            raise ValueError("unsupported policy version")
        keys(
            c["files"],
            {"minimum_annotations", "diagnostic", "exclusions"},
            {"minimum_annotations", "diagnostic", "exclusions"},
        )
        if type(c["files"]["minimum_annotations"]) is not int or c["files"]["minimum_annotations"] < 1:
            raise ValueError("minimum_annotations must be >=1")
        if not all(isinstance(c[k], dict) for k in ["diagnostics", "rules", "profiles", "exclusions"]):
            raise ValueError("policy catalogs must be objects")
        if len(c["profiles"]) > 64:
            raise ValueError("policy exceeds 64 profiles")
        if len(c["rules"]) > 128:
            raise ValueError("policy exceeds 128 rules")
        for code, diagnostic in c["diagnostics"].items():
            identity(code)
            keys(
                diagnostic,
                {"severity", "title", "message", "hint", "params", "group_by"},
                {"severity", "title", "message", "hint", "params", "group_by"},
            )
            if not isinstance(diagnostic["severity"], str) or diagnostic["severity"] not in LEVELS:
                raise ValueError("unknown diagnostic severity")
            if not isinstance(diagnostic["params"], dict) or not all(
                type(v) in {str, int, bool} for v in diagnostic["params"].values()
            ):
                raise ValueError("diagnostic params must be scalar values")
            for name in diagnostic["params"]:
                identity(name)
            if set(diagnostic["params"]) & PARAMETERS:
                raise ValueError("static parameters cannot override measured fields")
            if set(strings(diagnostic["group_by"])) - {"code", "file", "rule"}:
                raise ValueError("unsupported diagnostic grouping")
            for field in ["title", "message", "hint"]:
                if not isinstance(diagnostic[field], str) or len(diagnostic[field]) > 2000:
                    raise ValueError("diagnostic text must be a bounded string")
                try:
                    for _, name, fmt, conversion in Formatter().parse(diagnostic[field]):
                        if name is not None and (
                            name not in PARAMETERS | set(diagnostic["params"]) or fmt or conversion
                        ):
                            raise ValueError(f"unknown or unsafe diagnostic placeholder {name}")
                except ValueError as error:
                    raise ValueError(f"{code}: {error}") from error
        self.diagnostics = c["diagnostics"]
        for code in ["SPEC002", "SPEC004", "SPEC008", "SPEC_NOTICE"]:
            if code not in self.diagnostics or self.diagnostics[code]["severity"] != (
                "notice" if code == "SPEC_NOTICE" else "error"
            ):
                raise ValueError(f"{code}: integrity severity cannot be overridden")
        # atomic-spec://ATOMIC-GUARD-001/DR-22
        # Языковая проверка бинарна по наличию кириллицы; проценты и вероятностная трактовка не принимаются.
        self.annotation_language = c.get("annotation_language")
        if self.annotation_language is not None:
            language = self.annotation_language
            fields = {"language", "diagnostic"}
            keys(language, fields, fields)
            if not isinstance(language["language"], str) or language["language"] not in {"auto", "ru", "en"}:
                raise ValueError("annotation language must be auto, ru or en")
            if not isinstance(language["diagnostic"], str):
                raise ValueError("annotation language diagnostic must be a string")
            self.require_diagnostic(language["diagnostic"])
        # atomic-spec://ATOMIC-GUARD-001/DR-23
        # Необязательный запрет повторов использует отдельную диагностику и действует строго внутри файла.
        self.annotation_uniqueness = c.get("annotation_uniqueness")
        if self.annotation_uniqueness is not None:
            keys(self.annotation_uniqueness, {"diagnostic"}, {"diagnostic"})
            if not isinstance(self.annotation_uniqueness["diagnostic"], str):
                raise ValueError("annotation uniqueness diagnostic must be a string")
            self.require_diagnostic(self.annotation_uniqueness["diagnostic"])
        # atomic-spec://ATOMIC-GUARD-001/DR-25
        # Локальная база ограничивает выбор изменений, но не понижает ошибки выбранного кода до предупреждений.
        self.local_enforcement = c.get("local_enforcement")
        if self.local_enforcement is not None:
            validate_local_enforcement(self.local_enforcement)
        for rule_id, rule in c["rules"].items():
            identity(rule_id)
            keys(
                rule,
                {"match", "check", "coverage", "priority", "diagnostic"},
                {"match", "check", "coverage", "priority", "diagnostic"},
            )
            selector(rule["match"])
            if (
                not isinstance(rule["check"], str)
                or not isinstance(rule["coverage"], str)
                or rule["check"] not in {"annotation", "report"}
                or rule["coverage"] not in {"self", "function", "ancestor"}
                or type(rule["priority"]) is not int
            ):
                raise ValueError("invalid rule check, coverage or priority")
            self.require_diagnostic(rule["diagnostic"])
        self.require_diagnostic(c["files"]["diagnostic"])
        if self.diagnostics[c["files"]["diagnostic"]]["severity"] != "error":
            raise ValueError("file annotation minimum must be an error")
        for exc_id, exclusion in c["exclusions"].items():
            identity(exc_id)
            keys(exclusion, {"match", "rules", "reason"}, {"match", "rules", "reason"})
            selector(exclusion["match"])
            if not exclusion["reason"] or not isinstance(exclusion["reason"], str):
                raise ValueError("exclusion needs a reason")
            if set(strings(exclusion["rules"])) - set(c["rules"]):
                raise ValueError("exclusion names unknown rules")
        if not isinstance(c["files"]["exclusions"], list):
            raise ValueError("file exclusions must be a list")
        for exclusion in c["files"]["exclusions"]:
            keys(exclusion, {"id", "path", "reason"}, {"id", "path", "reason"})
            identity(exclusion["id"])
            if not all(isinstance(exclusion[k], str) and exclusion[k] for k in ["path", "reason"]):
                raise ValueError("file exclusion requires path and reason")
        for name, profile in c["profiles"].items():
            identity(name)
            keys(
                profile,
                {"extends", "rules", "exclusions"},
                {"extends", "rules", "exclusions"},
            )
            for field in profile:
                strings(profile[field])
            if set(profile["rules"]) - set(c["rules"]) or set(profile["exclusions"]) - set(c["exclusions"]):
                raise ValueError("profile references unknown rule or exclusion")
        active_rules, active_exclusions, selected = [], [], []

        # atomic-spec://ATOMIC-GUARD-001/DR-14
        # Неизвестный или циклический профиль не определяет рабочую политику и должен быть отклонён вместо частичного применения.
        def visit(name, stack):
            if name not in c["profiles"] or name in stack:
                raise ValueError(f"unknown or cyclic profile {name}")
            if name in selected:
                return
            for parent in c["profiles"][name]["extends"]:
                visit(parent, stack + [name])
            selected.append(name)
            active_rules.extend(c["profiles"][name]["rules"])
            active_exclusions.extend(c["profiles"][name]["exclusions"])

        # Validate unused profiles too, so a typo cannot be hidden by selection.
        for name in c["profiles"]:
            visit(name, [])
        active_rules.clear()
        active_exclusions.clear()
        selected.clear()
        for name in profiles or strings(c["default_profiles"]):
            visit(name, [])
        self.profiles = selected
        self.rules = [(name, c["rules"][name]) for name in dict.fromkeys(active_rules)]
        self.exclusions = [(name, c["exclusions"][name]) for name in dict.fromkeys(active_exclusions)]

    # atomic-spec://ATOMIC-GUARD-001/DR-14
    # Правила ссылаются только на известные диагностики и не подменяют проверки целостности.
    def require_diagnostic(self, code):
        identity(code)
        if code not in self.config["diagnostics"] or code in {
            "SPEC002",
            "SPEC004",
            "SPEC008",
            "SPEC900",
        }:
            raise ValueError(f"unknown or reserved diagnostic {code}")

    # atomic-spec://ATOMIC-GUARD-001/DR-16
    # Полное исключение файла сохраняет явно заданные причину и область.
    def exclude_file(self, path):
        return next(
            (e for e in self.config["files"]["exclusions"] if fnmatchcase(path, e["path"])),
            None,
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-14
    # Сообщение обязано объяснять фактическое нарушение выбранного правила; несуществующие параметры не могут подставлять выдуманный контекст.
    def emit(self, code, unit, rule="", reason=""):
        template = self.diagnostics[code]
        values = {
            **{key: unit.get(key, "") for key in PARAMETERS},
            **template["params"],
            "rule": rule,
            "reason": reason,
        }
        return dict(
            file=unit["path"],
            line=unit["start"],
            end_line=unit["end"],
            block=unit.get("name", ""),
            node_kind=unit.get("kind", ""),
            code=code,
            severity=template["severity"],
            rule=rule,
            title=template["title"].format_map(values),
            message=template["message"].format_map(values),
            hint=template["hint"].format_map(values),
            group_by=template["group_by"],
        )

    # atomic-spec://ATOMIC-GUARD-001/DR-15
    # Покрытие останавливается на границе функции; вложенная функция не заимствует чужие требования.
    @staticmethod
    def owner(unit, coverage):
        if coverage == "self":
            return unit
        current = unit
        outer = unit
        while current:
            if current["node"] in {"function", "scenario"} or (coverage == "ancestor" and current.get("refs")):
                return current
            outer = current
            current = current["parent"]
        return outer

    # atomic-spec://ATOMIC-GUARD-001/DR-16
    # Исключение или группировка обязаны оставаться объяснимыми; они не освобождают от проверки целостности явно написанной ссылки.
    def evaluate(self, facts, changed, valid, explain=False):
        output, trace, pending = [], [], {}
        self.context_keys = set()
        for unit in facts.units:
            if changed is not None and not any(
                unit.get("comment_start", unit["start"]) <= n <= unit["end"] for n in changed
            ):
                continue
            matches = [(name, r) for name, r in self.rules if facts.matches(r["match"], unit)]
            excluded_matches = [
                (n, r)
                for n, r in matches
                if any(n in ex["rules"] and facts.matches(ex["match"], unit) for _, ex in self.exclusions)
            ]
            active_matches = [(n, r) for n, r in matches if (n, r) not in excluded_matches]
            annotation_rules = [(name, r) for name, r in active_matches if r["check"] == "annotation"]
            if annotation_rules:
                highest = max(r["priority"] for _, r in annotation_rules)
                winners = [(n, r) for n, r in annotation_rules if r["priority"] == highest]
                if len(winners) > 1:
                    raise ValueError(
                        f"ambiguous coverage rules at {unit['path']}:{unit['start']}: {[n for n, _ in winners]}"
                    )
                matches = winners + [(n, r) for n, r in active_matches if r["check"] == "report"] + excluded_matches
            for name, rule in matches:
                exception = next(
                    (
                        (key, ex)
                        for key, ex in self.exclusions
                        if name in ex["rules"] and facts.matches(ex["match"], unit)
                    ),
                    None,
                )
                owner = self.owner(unit, rule["coverage"])
                covered = annotation_key(owner) in valid
                if covered:
                    self.context_keys.add(annotation_key(owner))
                status = (
                    "excluded" if exception else "covered" if covered and rule["check"] == "annotation" else "reported"
                )
                event = dict(
                    file=unit["path"],
                    line=unit["start"],
                    block=unit.get("name", ""),
                    rule=name,
                    status=status,
                    owner_line=owner["start"],
                )
                if exception:
                    event.update(exclusion=exception[0], reason=exception[1]["reason"])
                    output.append(
                        dict(
                            code="SPEC_NOTICE",
                            severity="notice",
                            message=exception[1]["reason"],
                            file=unit["path"],
                            line=unit["start"],
                            block=unit.get("name", ""),
                            rule=name,
                            exclusion=exception[0],
                        )
                    )
                elif rule["check"] == "report" or not covered:
                    key = (
                        rule["check"],
                        annotation_key(owner),
                        name if rule["check"] == "report" else "",
                    )
                    previous = pending.get(key)
                    rank = (
                        {"notice": 0, "warning": 1, "error": 2}[self.diagnostics[rule["diagnostic"]]["severity"]],
                        rule["priority"],
                    )
                    if previous is None or rank > previous[0]:
                        if previous is not None:
                            previous[2]["status"] = "grouped"
                        pending[key] = (
                            rank,
                            self.emit(rule["diagnostic"], owner, name),
                            event,
                        )
                    else:
                        event["status"] = "grouped"
                if explain:
                    trace.append(event)
        output.extend(item[1] for item in pending.values())
        if len(valid) < self.config["files"]["minimum_annotations"]:
            output.append(
                self.emit(
                    self.config["files"]["diagnostic"],
                    dict(
                        path=facts.path,
                        start=1,
                        end=1,
                        name=PurePosixPath(facts.path).name,
                        kind="file",
                        node="file",
                        actual_annotations=len(valid),
                        required_annotations=self.config["files"]["minimum_annotations"],
                    ),
                )
            )
        return output, trace


# atomic-spec://ATOMIC-GUARD-001/DR-15
# Одна группа не создаёт повторных обязательств, но разные неразмеченные узлы нельзя сливать в одно покрытие.
def annotation_key(unit):
    if unit.get("refs"):
        return (unit.get("comment_start", unit["start"]), tuple(unit["refs"]))
    return (
        "node",
        unit["start"],
        unit.get("column", 1),
        unit["end"],
        unit.get("end_column", 1),
        unit.get("kind"),
        unit.get("name"),
    )
