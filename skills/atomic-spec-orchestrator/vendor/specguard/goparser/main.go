// atomic-spec://ATOMIC-GUARD-001/DR-7
// Проверка разметки не должна требовать сборки проверяемого проекта или исполнения его кода.
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/scanner"
	"go/token"
	"os"
	"sort"
	"strconv"
	"strings"
)

// atomic-spec://ATOMIC-GUARD-001/DR-1
// Проверке подлежит только выбранный исходник; соседние файлы не расширяют область проверки.
type Input struct {
	Path   string `json:"path"`
	Source string `json:"source"`
}

// atomic-spec://ATOMIC-GUARD-001/DR-8
// Для каждого обязательства покрытия должна быть известна точная область кода и принадлежащая ей разметка.
type Unit struct {
	ASTNodes     int      `json:"ast_nodes"`
	Symbol       string   `json:"symbol,omitempty"`
	Kind         string   `json:"kind"`
	Start        int      `json:"start"`
	End          int      `json:"end"`
	HeaderEnd    int      `json:"header_end"`
	CommentStart int      `json:"comment_start"`
	Name         string   `json:"name"`
	Refs         []string `json:"refs"`
	Description  string   `json:"description"`
	ID           string   `json:"id"`
	Offset       int      `json:"offset"`
	EndOffset    int      `json:"end_offset"`
	Column       int      `json:"column"`
	EndColumn    int      `json:"end_column"`
	Role         string   `json:"role"`
	Priority     string   `json:"priority"`
	Owner        string   `json:"owner,omitempty"`
}

// atomic-spec://ATOMIC-GUARD-001/DR-8
// Неудачный разбор нельзя выдавать за отсутствие нарушений: потребитель должен отличать ошибку от пустого файла.
type Result struct {
	FactsVersion int      `json:"facts_version"`
	Generated    bool     `json:"generated"`
	Path         string   `json:"path"`
	Units        []Unit   `json:"units"`
	Tokens       []string `json:"tokens"`
	Error        string   `json:"error,omitempty"`
	PolicyUnits  []Unit   `json:"policy_units"`
	Annotations  []Unit   `json:"annotations"`
	CodeLines    []int    `json:"code_lines"`
}

// atomic-spec://ATOMIC-GUARD-001/DR-3
// Ссылка в данных не выполняет обязательство разметки; пояснение относится только к соседнему блоку кода.
func annotation(groups []*ast.CommentGroup, fs *token.FileSet, start int) (int, []string, string) {
	var refs []string
	var notes []string
	atomic := false
	commentStart := start
	for _, g := range groups {
		if fs.Position(g.End()).Line != start-1 {
			continue
		}
		commentStart = fs.Position(g.Pos()).Line
		for _, c := range g.List {
			text := strings.TrimSpace(strings.TrimSuffix(strings.TrimPrefix(strings.TrimPrefix(c.Text, "//"), "/*"), "*/"))
			for _, line := range strings.Split(text, "\n") {
				line = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), "*"))
				if strings.HasPrefix(line, "Spec:") {
					refs = append(refs, "legacy-spec:"+strings.TrimSpace(strings.TrimPrefix(line, "Spec:")))
					continue
				}
				value := line
				if strings.HasPrefix(value, "atomic-spec://") {
					atomic = true
					uri, note := value, ""
					for _, separator := range []string{" //", " — ", " - "} {
						if left, right, found := strings.Cut(value, separator); found {
							uri, note = left, strings.TrimSpace(right)
							break
						}
					}
					refs = append(refs, uri)
					if note != "" {
						notes = append(notes, note)
					}
				} else if atomic && line != "" && !strings.HasPrefix(line, "http") {
					notes = append(notes, line)
				}
			}
		}
	}
	validNotes := []string{}
	for _, note := range notes {
		if note != "" && !strings.HasPrefix(note, "atomic-spec://") && !strings.HasPrefix(note, "http://") && !strings.HasPrefix(note, "https://") && !strings.HasPrefix(note, "Spec:") {
			validNotes = append(validNotes, note)
		}
	}
	return commentStart, refs, strings.Join(validNotes, "\n")
}

// atomic-spec://ATOMIC-GUARD-001/DR-2
// Самостоятельный сценарий требует покрытия; одного имени Test недостаточно, чтобы считать функцию сценарием.
func testingParameter(params *ast.FieldList, aliases map[string]bool) bool {
	if params == nil {
		return false
	}
	for _, field := range params.List {
		ptr, ok := field.Type.(*ast.StarExpr)
		if !ok {
			continue
		}
		sel, ok := ptr.X.(*ast.SelectorExpr)
		if !ok || sel.Sel.Name != "T" {
			continue
		}
		pkg, ok := sel.X.(*ast.Ident)
		if ok && aliases[pkg.Name] {
			return true
		}
	}
	return false
}

// atomic-spec://ATOMIC-GUARD-001/DR-17
// Ослабление для табличных случаев допустимо только для данных этой таблицы; совпадение имён не освобождает посторонний код от покрытия.
func tableLiteral(expr ast.Expr) *ast.CompositeLit {
	if id, ok := expr.(*ast.Ident); ok && id.Obj != nil {
		switch decl := id.Obj.Decl.(type) {
		case *ast.AssignStmt:
			for i, lhs := range decl.Lhs {
				if name, ok := lhs.(*ast.Ident); ok && name.Obj == id.Obj && i < len(decl.Rhs) {
					expr = decl.Rhs[i]
					break
				}
			}
		case *ast.ValueSpec:
			for i, name := range decl.Names {
				if name.Obj == id.Obj && i < len(decl.Values) {
					expr = decl.Values[i]
					break
				}
			}
		}
	}
	lit, _ := expr.(*ast.CompositeLit)
	return lit
}

// atomic-spec://ATOMIC-GUARD-001/DR-17
// Сценарии и их входные данные имеют разные обязательства покрытия: вспомогательные данные не должны скрывать самостоятельный сценарий.
func testSyntax(file *ast.File) (map[*ast.FuncLit]*ast.CallExpr, map[ast.Node]bool, []*ast.FuncLit, map[string]bool) {
	aliases := map[string]bool{}
	for _, imp := range file.Imports {
		if imp.Path.Value == `"testing"` {
			name := "testing"
			if imp.Name != nil {
				name = imp.Name.Name
			}
			aliases[name] = true
		}
	}
	runs := map[*ast.FuncLit]*ast.CallExpr{}
	rows := map[ast.Node]bool{}
	var fixtures []*ast.FuncLit
	ast.Inspect(file, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		if sel.Sel.Name == "HandlerFunc" {
			for _, arg := range call.Args {
				if fn, ok := arg.(*ast.FuncLit); ok {
					fixtures = append(fixtures, fn)
				}
			}
		}
		// Retain legacy permissive Run fixtures; verified callbacks get scenario priority.
		if sel.Sel.Name == "Run" && len(call.Args) >= 2 {
			if fn, ok := call.Args[1].(*ast.FuncLit); ok {
				runs[fn] = call
			}
		}
		return true
	})
	ast.Inspect(file, func(n ast.Node) bool {
		rangeStmt, ok := n.(*ast.RangeStmt)
		if !ok {
			return true
		}
		for _, fixture := range fixtures {
			if fixture.Pos() <= rangeStmt.Pos() && rangeStmt.End() <= fixture.End() {
				return true
			}
		}
		lit := tableLiteral(rangeStmt.X)
		if lit == nil {
			return true
		}
		// Collection records are cases when a row is consumed by Run or a test assertion.
		objects := map[*ast.Object]bool{}
		for _, expr := range []ast.Expr{rangeStmt.Key, rangeStmt.Value} {
			if id, ok := expr.(*ast.Ident); ok && id.Obj != nil && id.Name != "_" {
				objects[id.Obj] = true
			}
		}
		consumed, assertion := false, false
		ast.Inspect(rangeStmt.Body, func(child ast.Node) bool {
			if id, ok := child.(*ast.Ident); ok && id.Obj != nil && objects[id.Obj] {
				consumed = true
			}
			if call, ok := child.(*ast.CallExpr); ok {
				if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
					switch sel.Sel.Name {
					case "Run", "Fatal", "Fatalf", "Error", "Errorf", "Fail", "FailNow":
						assertion = true
					}
				}
			}
			return true
		})
		if consumed && assertion {
			for _, elt := range lit.Elts {
				rows[elt] = true
			}
		}
		return true
	})
	return runs, rows, fixtures, aliases
}

// atomic-spec://ATOMIC-GUARD-001/DR-9
// Статически известный SQL остаётся кандидатом при составной записи; неизвестный запрос нельзя представлять как разобранный.
func constantSQL(expr ast.Expr, depth int) (string, bool) {
	if depth > 16 {
		return "", false
	}
	switch v := expr.(type) {
	case *ast.BasicLit:
		if v.Kind != token.STRING {
			return "", false
		}
		value, err := strconv.Unquote(v.Value)
		return value, err == nil
	case *ast.ParenExpr:
		return constantSQL(v.X, depth+1)
	case *ast.BinaryExpr:
		if v.Op != token.ADD {
			return "", false
		}
		left, lok := constantSQL(v.X, depth+1)
		right, rok := constantSQL(v.Y, depth+1)
		return left + right, lok && rok
	case *ast.Ident:
		if v.Obj == nil || v.Obj.Kind != ast.Con {
			return "", false
		}
		if spec, ok := v.Obj.Decl.(*ast.ValueSpec); ok {
			for i, name := range spec.Names {
				if name.Obj == v.Obj && i < len(spec.Values) {
					return constantSQL(spec.Values[i], depth+1)
				}
			}
		}
	}
	return "", false
}

// atomic-spec://ATOMIC-GUARD-001/DR-9
// Операции с данными остаются кандидатами бизнес-правил; обычный текст с SQL-словами не доказывает наличие такой операции.
func sqlQuery(call *ast.CallExpr) string {
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok {
		return ""
	}
	arg := 0
	switch sel.Sel.Name {
	case "Exec", "Query", "QueryRow":
	case "ExecContext", "QueryContext", "QueryRowContext":
		arg = 1
	default:
		return ""
	}
	if arg >= len(call.Args) {
		return ""
	}
	query, ok := constantSQL(call.Args[arg], 0)
	if !ok {
		return ""
	}
	words := strings.Fields(query)
	if len(words) == 0 {
		return ""
	}
	op := strings.ToUpper(words[0])
	switch op {
	case "SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "CREATE", "ALTER", "DROP", "TRUNCATE", "MERGE":
	default:
		return ""
	}
	name := "SQL " + op
	index := 1
	if (op == "INSERT" || op == "DELETE") && len(words) > 1 {
		index = 2
	}
	if op != "SELECT" && op != "WITH" && index < len(words) {
		name += " " + words[index]
	}
	return name
}

// atomic-spec://ATOMIC-GUARD-001/DR-2
// Изменение блока сохраняет его обязательство покрытия; разметка другого блока не должна случайно засчитываться за него.
func inspect(input Input) Result {
	fs := token.NewFileSet()
	out := Result{FactsVersion: 2, Path: input.Path, Units: []Unit{}, Tokens: []string{}}
	file, err := parser.ParseFile(fs, input.Path, input.Source, parser.ParseComments|parser.AllErrors)
	if err != nil {
		out.Error = err.Error()
		return out
	}
	sizes := map[ast.Node]int{}
	var stack []ast.Node
	ast.Inspect(file, func(n ast.Node) bool {
		if n != nil {
			sizes[n] = 1
			stack = append(stack, n)
		} else {
			child := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if len(stack) > 0 {
				sizes[stack[len(stack)-1]] += sizes[child]
			}
		}
		return true
	})
	policyFacts(file, fs, &out, sizes)
	isTest := strings.HasSuffix(input.Path, "_test.go")
	runs, rows, fixtures, aliases := testSyntax(file)
	globals := map[ast.Node]bool{}
	rules := map[ast.Node]bool{}
	for _, decl := range file.Decls {
		if gen, ok := decl.(*ast.GenDecl); ok && (gen.Tok == token.CONST || gen.Tok == token.VAR) {
			globals[gen] = true
			for _, spec := range gen.Specs {
				globals[spec] = true
				if value, ok := spec.(*ast.ValueSpec); ok {
					for _, expr := range value.Values {
						ast.Inspect(expr, func(n ast.Node) bool {
							if _, closure := n.(*ast.FuncLit); closure {
								return false
							}
							if lit, ok := n.(*ast.CompositeLit); ok {
								for _, elt := range lit.Elts {
									rules[elt] = true
								}
							}
							return true
						})
					}
				}
			}
		}
	}
	unitID := func(node ast.Node, kind string) string {
		return fmt.Sprintf("%s:%d:%d:%s", input.Path, fs.Position(node.Pos()).Offset, fs.Position(node.End()).Offset, kind)
	}
	add := func(node ast.Node, name string, header token.Pos) {
		start := fs.Position(node.Pos()).Line
		cs, refs, desc := annotation(file.Comments, fs, start)
		kind := fmt.Sprintf("%T", node)
		role, priority := "syntax", "normal"
		if globals[node] {
			role, priority = "declaration", "high"
			if isTest {
				role, priority = "fixture", "low"
			}
		}
		if rules[node] && !isTest {
			kind, role, priority = "DeclarativeRule", "declaration", "high"
		}
		if rows[node] && isTest {
			role, priority = "test_case", "high"
		}
		if fn, ok := node.(*ast.FuncDecl); ok && isTest {
			role, priority = "helper", "normal"
			if fn.Recv != nil {
				role, priority = "fixture", "low"
			}
			if strings.HasPrefix(fn.Name.Name, "Test") && testingParameter(fn.Type.Params, aliases) {
				role, priority = "scenario", "high"
			}
		}
		if name == "subtest t.Run" {
			role, priority = "scenario", "low"
		}
		if strings.HasPrefix(name, "SQL ") {
			kind, role, priority = "SQLQuery", "sql", "high"
		}
		owner := ""
		if isTest {
			var nearest *ast.CallExpr
			for fn, call := range runs {
				if call.Pos() < node.Pos() && node.End() <= call.End() && (nearest == nil || call.End()-call.Pos() < nearest.End()-nearest.Pos()) {
					nearest = call
					owner = unitID(call, "*ast.CallExpr")
				}
				if node == call {
					if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
						if id, ok := sel.X.(*ast.Ident); ok && id.Obj != nil {
							if field, ok := id.Obj.Decl.(*ast.Field); ok && testingParameter(&ast.FieldList{List: []*ast.Field{field}}, aliases) && testingParameter(fn.Type.Params, aliases) {
								priority = "high"
							}
						}
					}
				}
			}
		}
		for _, fixture := range fixtures {
			if fixture.Pos() <= node.Pos() && node.End() <= fixture.End() {
				role, priority = "fixture", "low"
				if node != fixture {
					owner = unitID(fixture, "*ast.FuncLit")
				}
			}
		}
		pos, end := fs.Position(node.Pos()), fs.Position(node.End())
		out.Units = append(out.Units, Unit{ASTNodes: sizes[node], Kind: kind, Start: start, End: end.Line, HeaderEnd: fs.Position(header).Line, CommentStart: cs, Name: name, Refs: refs, Description: desc,
			ID: unitID(node, kind), Offset: pos.Offset, EndOffset: end.Offset, Column: pos.Column, EndColumn: end.Column, Role: role, Priority: priority, Owner: owner})
	}
	ast.Inspect(file, func(n ast.Node) bool {
		if n == nil {
			return true
		}
		if (rules[n] && !isTest) || (rows[n] && isTest) {
			name := "declarative rule"
			if isTest {
				name = "test table element"
			}
			add(n, name, n.End())
			return true
		}
		switch v := n.(type) {
		case *ast.GenDecl:
			if globals[v] {
				add(v, v.Tok.String()+" declaration", v.Pos())
			}
		case *ast.ValueSpec:
			if globals[v] {
				names := make([]string, len(v.Names))
				for i, name := range v.Names {
					names[i] = name.Name
				}
				add(v, strings.Join(names, ", "), v.End())
			}
		case *ast.FuncDecl:
			head := v.End()
			if v.Body != nil {
				head = v.Body.Lbrace
			}
			name := v.Name.Name
			if v.Recv != nil && len(v.Recv.List) > 0 {
				name = fmt.Sprintf("method %s", name)
			}
			add(v, name, head)
		case *ast.FuncLit:
			if isTest && runs[v] != nil {
				break
			}
			add(v, "function literal", v.Body.Lbrace)
		case *ast.TypeSpec:
			add(v, "type "+v.Name.Name, v.Type.Pos())
		case *ast.IfStmt:
			add(v, "if", v.Body.Lbrace)
		case *ast.ForStmt:
			add(v, "for", v.Body.Lbrace)
		case *ast.RangeStmt:
			add(v, "range", v.Body.Lbrace)
		case *ast.SwitchStmt:
			add(v, "switch", v.Body.Lbrace)
		case *ast.TypeSwitchStmt:
			add(v, "type switch", v.Body.Lbrace)
		case *ast.SelectStmt:
			add(v, "select", v.Body.Lbrace)
		case *ast.CaseClause:
			add(v, "case", v.Colon)
		case *ast.CommClause:
			add(v, "communication case", v.Colon)
		case *ast.CallExpr:
			if name := sqlQuery(v); name != "" {
				add(v, name, v.Lparen)
			}
			if isTest {
				for _, call := range runs {
					if call == v {
						add(v, "subtest t.Run", v.Lparen)
						break
					}
				}
			}
		}
		return true
	})
	// atomic-spec://ATOMIC-GUARD-001/DR-2
	// Соседние и вложенные блоки на одной строке сохраняют самостоятельные границы покрытия.
	sort.SliceStable(out.Units, func(i, j int) bool {
		a, b := out.Units[i], out.Units[j]
		if a.Start != b.Start {
			return a.Start < b.Start
		}
		if a.End != b.End {
			return a.End < b.End
		}
		return a.EndOffset-a.Offset < b.EndOffset-b.Offset
	})
	var scan scanner.Scanner
	sf := token.NewFileSet().AddFile(input.Path, -1, len(input.Source))
	scan.Init(sf, []byte(input.Source), nil, 0)
	for {
		pos, tok, lit := scan.Scan()
		if tok == token.EOF {
			break
		}
		if tok == token.SEMICOLON && lit == "\n" {
			continue
		}
		out.Tokens = append(out.Tokens, fmt.Sprintf("%d:%s", tok, lit))
		first := sf.Position(pos).Line
		last := first + strings.Count(lit, "\n")
		for line := first; line <= last; line++ {
			out.CodeLines = append(out.CodeLines, line)
		}
	}
	return out
}

// atomic-spec://ATOMIC-GUARD-001/DR-7
// Выбранная пачка не должна требовать отдельного запуска парсера для каждой ссылки: это ограничивает стоимость проверки.
func main() {
	var inputs []Input
	if err := json.NewDecoder(os.Stdin).Decode(&inputs); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	results := make([]Result, 0, len(inputs))
	for _, input := range inputs {
		results = append(results, inspect(input))
	}
	if err := json.NewEncoder(os.Stdout).Encode(results); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
