package main

import (
	"strings"
	"testing"
)

// atomic-spec://ATOMIC-GUARD-001/DR-7
// Проверка синтаксиса не требует выполнения проверяемой программы; тест парсера не должен зависеть от её внешнего окружения.
func parseFixture(t *testing.T, path, source string) []Unit {
	t.Helper()
	result := inspect(Input{Path: path, Source: source})
	if result.Error != "" {
		t.Fatal(result.Error)
	}
	seen := map[string]bool{}
	for _, unit := range result.Units {
		if seen[unit.ID] || unit.ID == "" || unit.Column < 1 || unit.EndOffset <= unit.Offset || unit.EndOffset > len(source) {
			t.Fatalf("invalid identity/span: %+v", unit)
		}
		seen[unit.ID] = true
	}
	return result.Units
}

// atomic-spec://ATOMIC-GUARD-001/DR-9
// Декларативные таблицы правил, лимиты и regex не теряют статус кандидатов из-за отсутствия ветвлений.
func TestGlobalDeclarations(t *testing.T) {
	source := `package sample
// atomic-spec://TEST/DR-2
// Role policy controls access.
var ActionRoles = map[string][]string{
 "hide": {"admin", "sib"},
 "upload": {"developer"},
}
var anyAuthenticated = map[string]bool{"comment": true}
var All = []string{"hide", "upload"}
var slugRule = regexp.MustCompile("^[a-z]+$")
const maxLimit = 12
func f() { local := []int{1, 2}; _ = local }
var initialized = func() int { scratch := []int{3}; return scratch[0] }()
`
	units := parseFixture(t, "policy.go", source)
	want := map[string]bool{"ActionRoles": false, "anyAuthenticated": false, "All": false, "slugRule": false, "maxLimit": false}
	mapRow := false
	for _, u := range units {
		if _, ok := want[u.Name]; ok && u.Kind == "*ast.ValueSpec" {
			want[u.Name] = true
			if u.Role != "declaration" {
				t.Fatalf("wrong global role: %+v", u)
			}
		}
		if u.Kind == "DeclarativeRule" && strings.HasPrefix(source[u.Offset:u.EndOffset], `"hide":`) {
			mapRow = true
		}
		if u.Kind == "DeclarativeRule" && (u.Start == 12 || u.Start == 13) {
			t.Fatalf("local scratch became rule: %+v", u)
		}
		if u.Kind == "*ast.GenDecl" && u.Start == 4 && (len(u.Refs) != 1 || u.Description != "Role policy controls access.") {
			t.Fatalf("annotation lost: %+v", u)
		}
	}
	for name, found := range want {
		if !found {
			t.Errorf("missing declaration %s", name)
		}
	}
	if !mapRow {
		t.Fatal("policy map row not selected locally")
	}
}

// atomic-spec://ATOMIC-GUARD-001/DR-17
// Вспомогательные данные не создают отдельного сценария; использованные табличные случаи остаются видимыми для политики покрытия.
func TestConsumedTables(t *testing.T) {
	source := `package sample
import "testing"
func TestCases(t *testing.T) {
 cases := []struct{name string; value string}{{"first", "a"}, {"second", "b"}}
 _ = []map[string]any{{"nested": map[string]any{"x": 1}}}
 for _, c := range cases { t.Run(c.name, func(t *testing.T) { if c.value == "" { t.Fatal(c.name) } }) }
 for _, e := range []error{context.Canceled, errors.New("bad")} { if retry(e) { t.Error(e) } }
 for _, s := range []string{"bad", "worse"} { if valid(s) { t.Fatal(s) } }
}
`
	units := parseFixture(t, "cases_test.go", source)
	rows, runs, callbacks := 0, 0, 0
	for _, u := range units {
		if u.Role == "test_case" {
			if u.HeaderEnd != u.End {
				t.Fatalf("table row body can inherit broad parent: %+v", u)
			}
			rows++
			if u.Start == 5 {
				t.Fatal("JSON fixture classified as case")
			}
		}
		if u.Name == "subtest t.Run" {
			runs++
			if u.Priority != "high" {
				t.Fatalf("unverified testing receiver: %+v", u)
			}
		}
		if u.Kind == "*ast.FuncLit" {
			callbacks++
		}
	}
	if rows != 6 || runs != 1 || callbacks != 0 {
		t.Fatalf("rows/runs/callbacks=%d/%d/%d", rows, runs, callbacks)
	}
}

// atomic-spec://ATOMIC-GUARD-001/DR-2
// Решение внутри вложенного подтеста принадлежит ближайшему сценарию; неподтверждённый Run не получает строгость доказанного сценария.
func TestRunOwnership(t *testing.T) {
	source := `package sample
import tst "testing"
func TestNested(t *tst.T) {
 t.Run("outer", func(t *tst.T) {
  t.Run("inner", func(t *tst.T) { if failed { t.Fatal("bad") } })
 })
 legacy.Run("fixture", func() { if bad { panic("bad") } })
}
`
	units := parseFixture(t, "nested_test.go", source)
	var inner string
	for _, u := range units {
		if u.Name == "subtest t.Run" && u.Start == 5 {
			inner = u.ID
		}
	}
	if inner == "" {
		t.Fatal("missing inner Run")
	}
	for _, u := range units {
		if u.Kind == "*ast.FuncLit" {
			t.Fatalf("duplicate Run callback: %+v", u)
		}
		if u.Kind == "*ast.IfStmt" && u.Start == 5 && u.Owner != inner {
			t.Fatalf("not nearest owner: %+v", u)
		}
		if u.Name == "subtest t.Run" && u.Start == 7 && u.Priority != "low" {
			t.Fatalf("legacy Run must remain low confidence: %+v", u)
		}
	}
}

// atomic-spec://ATOMIC-GUARD-001/DR-9
// Статический запрос к базе остаётся кандидатом, а похожий текст вне операции с базой не создаёт ложного обязательства.
func TestSQLQueries(t *testing.T) {
	source := `package sample
const table = "publication_queue"
const update = "UPDATE " + table + " SET state = $1"
func f() {
 db.ExecContext(ctx, update, state)
 db.Query("SELECT id FROM publication_queue")
 db.QueryRowContext(ctx, "DELETE FROM " + table + " RETURNING id")
 db.Exec("INSERT INTO publication_queue(id) VALUES (1)")
 db.QueryContext(ctx, "SELECT id FROM publication_queue")
 db.QueryRow("SELECT id FROM publication_queue")
 println("UPDATE publication_queue SET state=1")
 db.Exec(dynamic)
 db.Query("not SQL")
 value := "UPDATE publication_queue SET state=1"
 db.Exec(value)
}
`
	units := parseFixture(t, "queries.go", source)
	queries, update := 0, false
	for _, u := range units {
		if u.Kind != "SQLQuery" {
			continue
		}
		queries++
		if u.Role != "sql" || u.Priority != "high" {
			t.Fatalf("invalid SQL metadata: %+v", u)
		}
		if u.Name == "SQL UPDATE publication_queue" {
			update = true
		}
	}
	if queries != 6 || !update {
		t.Fatalf("SQL queries=%d, named UPDATE=%v", queries, update)
	}
}

// atomic-spec://ATOMIC-GUARD-001/DR-17
// Обработка HTTP-ответа внутри фикстуры не является таблицей самостоятельных сценариев и не требует покрытия каждой строки ответа.
func TestFixtureOwnership(t *testing.T) {
	source := `package sample
import "testing"
func TestHTTP(t *testing.T) {
 _ = http.HandlerFunc(func(w Writer, r Request) {
  for _, entry := range []string{"response"} { if entry == "" { t.Fatal(entry) } }
 })
}
`
	for _, u := range parseFixture(t, "http_test.go", source) {
		if u.Role == "test_case" {
			t.Fatalf("HTTP fixture became table: %+v", u)
		}
		if u.Kind == "*ast.RangeStmt" && (u.Role != "fixture" || u.Owner == "") {
			t.Fatalf("missing fixture owner: %+v", u)
		}
		if u.Owner == u.ID {
			t.Fatalf("self owner: %+v", u)
		}
	}
}

// atomic-spec://ATOMIC-GUARD-001/DR-3
// URI задаёт ссылку, но не заменяет пояснение; тот же URI в строковом значении не выполняет обязательство разметки.
func TestBareAtomicURI(t *testing.T) {
	source := `package sample
// atomic-spec://DEMO-PUBLICATION-001/DR-5
// Reserve before creating a PR.
func reserve() {}
var fake = "atomic-spec://DEMO-PUBLICATION-001/DR-5"
`
	units := parseFixture(t, "uri.go", source)
	for _, unit := range units {
		if unit.Name == "reserve" {
			if len(unit.Refs) != 1 || unit.Refs[0] != "atomic-spec://DEMO-PUBLICATION-001/DR-5" || unit.Description != "Reserve before creating a PR." {
				t.Fatalf("wrong bare URI annotation: %+v", unit)
			}
		} else if len(unit.Refs) != 0 {
			t.Fatalf("string literal became an annotation: %+v", unit)
		}
	}
}
