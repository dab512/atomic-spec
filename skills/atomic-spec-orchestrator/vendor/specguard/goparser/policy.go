package main

import (
	"go/ast"
	"go/token"
	"path"
	"strconv"
	"strings"
)

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
// Обязательства для известных гейтов доступа нельзя переносить на одноимённый локальный код: ложное совпадение не доказывает правило доступа.
func policyFacts(file *ast.File, fs *token.FileSet, out *Result, sizes map[ast.Node]int) {
	imports := map[string]string{}
	for _, imp := range file.Imports {
		value, _ := strconv.Unquote(imp.Path.Value)
		name := path.Base(value)
		if imp.Name != nil {
			name = imp.Name.Name
		}
		if name != "." && name != "_" {
			imports[name] = value
		}
	}
	makeUnit := func(n ast.Node, kind, name, symbol string) Unit {
		p, e := fs.Position(n.Pos()), fs.Position(n.End())
		cs, refs, desc := annotation(file.Comments, fs, p.Line)
		return Unit{ASTNodes: sizes[n], Kind: kind, Name: name, Symbol: symbol, Start: p.Line, End: e.Line, Column: p.Column, EndColumn: e.Column, HeaderEnd: p.Line, CommentStart: cs, Refs: refs, Description: desc}
	}
	var symbol func(ast.Expr) string
	symbol = func(expr ast.Expr) string {
		switch v := expr.(type) {
		case *ast.IndexExpr:
			return symbol(v.X)
		case *ast.Ident:
			if v.Obj == nil {
				return "local:" + v.Name
			}
			switch d := v.Obj.Decl.(type) {
			case *ast.FuncDecl:
				return "local:" + v.Name
			case *ast.ValueSpec:
				for _, decl := range file.Decls {
					if gen, ok := decl.(*ast.GenDecl); ok {
						for _, spec := range gen.Specs {
							if spec == d {
								return "local:" + v.Name
							}
						}
					}
				}
			}
		case *ast.SelectorExpr:
			if id, ok := v.X.(*ast.Ident); ok && id.Obj == nil && imports[id.Name] != "" {
				return imports[id.Name] + "#" + v.Sel.Name
			}
		}
		return ""
	}
	ast.Inspect(file, func(n ast.Node) bool {
		switch v := n.(type) {
		case *ast.CallExpr:
			name := "call"
			switch f := v.Fun.(type) {
			case *ast.Ident:
				name = f.Name
			case *ast.SelectorExpr:
				name = f.Sel.Name
			}
			out.PolicyUnits = append(out.PolicyUnits, makeUnit(v, "PolicyCall", name, symbol(v.Fun)))
		case *ast.AssignStmt:
			for _, lhs := range v.Lhs {
				if s := symbol(lhs); s != "" && !strings.HasPrefix(s, "local:_") {
					out.PolicyUnits = append(out.PolicyUnits, makeUnit(v, "PolicyMutation", s, s))
				}
			}
		}
		return true
	})
	for _, group := range file.Comments {
		for _, c := range group.List {
			text := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(c.Text, "//")))
			if strings.HasPrefix(text, "@generated") || (strings.HasPrefix(text, "code generated ") && strings.Contains(text, "do not edit.")) {
				out.Generated = true
			}
		}
		end := fs.Position(group.End()).Line
		_, refs, desc := annotation([]*ast.CommentGroup{group}, fs, end+1)
		if len(refs) > 0 {
			u := makeUnit(group, "CommentGroup", "file annotation", "")
			u.CommentStart = u.Start
			u.Refs = refs
			u.Description = desc
			out.Annotations = append(out.Annotations, u)
		}
	}
}
