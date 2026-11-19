// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
// Покрытие JS/TS и YAML определяется грамматикой языка: похожая на комментарий строка не подтверждает выполнение требования.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const modules = path.resolve(process.argv[2]);
let ts, yaml;

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-3
// URI начинает аннотацию; только последующий текст группы считается её пояснением.
function annotation(text) {
    const lines = text.split('\n').map(s => s.replace(/^\s*(?:\/\/|\/\*|\*\/?|#)\s?/, '').replace(/\*\/$/, '').trim());
    const refs = [], notes = [];
    let atomic = false;
    for (const line of lines) {
        if (line.startsWith('Spec:')) { refs.push('legacy-spec:' + line.slice(5).trim()); continue; }
        if (line.startsWith('atomic-spec://')) {
            atomic = true;
            const boundary = /\s+(?:\/\/|—|-)\s*/.exec(line);
            refs.push(boundary ? line.slice(0, boundary.index) : line);
            if (boundary) notes.push(line.slice(boundary.index + boundary[0].length).trim());
        } else if (atomic && line && !line.startsWith('http')) notes.push(line);
    }
    const validNotes = notes.filter(note => note && !/^(atomic-spec:\/\/|https?:\/\/|Spec:)/.test(note));
    return {refs, description: validNotes.join('\n')};
}

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
// Каждый блок должен сохранять собственную исходную локацию, даже если его покрывает аннотация другого владельца.
function location(input, position, kind, start, end, ownerStart = start, ownerEnd = end) {
    const first = position(start);
    const last = position(Math.max(start, end - 1));
    return {
        id: `${input.path}:${kind}:${start}:${end}`,
        start: first.line, end: last.line, column: first.column, end_column: last.column,
        start_offset: start, end_offset: end, offset_encoding: 'utf-16',
        annotation_owner: {start: position(ownerStart).line, end: position(Math.max(ownerStart, ownerEnd - 1)).line,
            column: position(ownerStart).column, start_offset: ownerStart, end_offset: ownerEnd},
    };
}

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-15
// Известный гейт доступа требует подтверждённого происхождения; совпадение с затенённым именем не доказывает применение правила доступа.
function policyFacts(input, source, position) {
    const imports = new Map(), shadowed = new Set(), calls = [], comments = new Map(), sizes = new Map();
    for (const statement of source.statements) {
        if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
        const module = statement.moduleSpecifier.text;
        const origin = module.startsWith('.') ? path.posix.normalize(path.posix.join(path.posix.dirname(input.path), module)) : module;
        const binding = statement.importClause?.namedBindings;
        if (binding && ts.isNamedImports(binding)) for (const item of binding.elements) imports.set(item.name.text, `${origin}#${item.propertyName?.text || item.name.text}`);
        if (binding && ts.isNamespaceImport(binding)) imports.set(binding.name.text, `${origin}#`);
    }
    const bindings = node => {
        if ((ts.isParameter(node) || ts.isVariableDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.name) {
            const collect = n => { if (ts.isIdentifier(n)) shadowed.add(n.text); else ts.forEachChild(n, collect); };
            collect(node.name);
        }
        ts.forEachChild(node, bindings);
    };
    bindings(source);
    const visit = node => {
        const ranges = [...(ts.getLeadingCommentRanges(input.source, node.pos) || []), ...(ts.getTrailingCommentRanges(input.source, node.end) || [])];
        if (ts.isJsxExpression(node) && !node.expression) ranges.push(...(ts.getTrailingCommentRanges(input.source, node.getStart(source) + 1) || []));
        for (const c of ranges) comments.set(c.pos, c);
        if (ts.isCallExpression(node)) {
            let symbol = '', name = node.expression.getText(source);
            if (ts.isIdentifier(node.expression) && !shadowed.has(node.expression.text)) symbol = imports.get(node.expression.text) || '';
            if (ts.isPropertyAccessExpression(node.expression) && ts.isIdentifier(node.expression.expression)) {
                const base = node.expression.expression.text;
                if (!shadowed.has(base) && imports.get(base)?.endsWith('#')) symbol = imports.get(base) + node.expression.name.text;
            }
            const start = node.getStart(source);
            calls.push({kind:'PolicyCall', name: name.slice(0,120), symbol, ...location(input,position,'PolicyCall',start,node.end), header_end:position(start).line, comment_start:position(start).line, refs:[], description:''});
        }
        let count=1;
        ts.forEachChild(node, child=>{count+=visit(child);});
        sizes.set(`${node.getStart(source)}:${node.end}`,count);
        return count;
    };
    visit(source);
    for (const call of calls) call.ast_nodes=sizes.get(`${call.start_offset}:${call.end_offset}`) || 1;
    for (const c of ts.getLeadingCommentRanges(input.source, source.endOfFileToken.pos) || []) comments.set(c.pos,c);
    return {sizes, policy_units:calls, comments:[...comments.values()].sort((a,b)=>a.pos-b.pos)};
}

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-16
// Файловое обязательство можно выполнить реальной аннотацией без владельца; такую группу нельзя терять при проверке покрытия.
function commentFacts(input, position, comments) {
    const groups=[];
    for(const c of comments) {
        const last=groups.at(-1);
        if(last && !input.source.slice(last.at(-1).end,c.pos).trim() && position(c.pos).line-position(last.at(-1).end).line<=1) last.push(c);
        else groups.push([c]);
    }
    return groups.map(group=>{
        const start=group[0].pos,end=group.at(-1).end;
        return {kind:'CommentGroup', name:'file annotation', ...location(input,position,'CommentGroup',start,end), header_end:position(start).line, comment_start:position(start).line, ...annotation(group.map(c=>input.source.slice(c.pos,c.end)).join('\n'))};
    }).filter(u=>u.refs.length);
}

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
// Решения и конфигурации должны оставаться видимыми кандидатами; наличие свойства само по себе не доказывает отдельного бизнес-правила.
function typescript(input) {
    ts ??= require(path.join(modules, 'typescript'));
    const source = ts.createSourceFile(input.path, input.source, ts.ScriptTarget.Latest, true);
    if (source.parseDiagnostics.length) {
        return {path: input.path, units: [], error: ts.flattenDiagnosticMessageText(source.parseDiagnostics[0].messageText, '\n')};
    }
    const position = pos => {
        const p = source.getLineAndCharacterOfPosition(pos);
        return {line: p.line + 1, column: p.character + 1};
    };
    const line = pos => position(pos).line;
    const units = [];
    const fixtureFile = /\.(?:test|spec)\.[cm]?[jt]sx?$/.test(input.path);
    const functions = new Set([ts.SyntaxKind.FunctionDeclaration, ts.SyntaxKind.MethodDeclaration,
        ts.SyntaxKind.Constructor, ts.SyntaxKind.ArrowFunction, ts.SyntaxKind.FunctionExpression]);
    const declarations = new Set([ts.SyntaxKind.ClassDeclaration, ts.SyntaxKind.InterfaceDeclaration,
        ts.SyntaxKind.TypeAliasDeclaration, ts.SyntaxKind.EnumDeclaration]);
    const decisions = new Set([ts.SyntaxKind.IfStatement, ts.SyntaxKind.SwitchStatement, ts.SyntaxKind.CaseClause,
        ts.SyntaxKind.DefaultClause, ts.SyntaxKind.ForStatement, ts.SyntaxKind.ForInStatement,
        ts.SyntaxKind.ForOfStatement, ts.SyntaxKind.WhileStatement, ts.SyntaxKind.DoStatement, ts.SyntaxKind.CatchClause]);
    const logical = new Set([ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken]);
    const configNames = new Set(['server', 'proxy', 'options', 'menuItems', 'docsItems', 'footerItems', 'logo', 'topAlert']);
    // atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-17
    // Подготовка параметров теста не создаёт второй самостоятельный сценарий и не требует дублировать его пояснение.
    const testName = node => {
        if (!ts.isCallExpression(node)) return undefined;
        if (ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'each') return undefined;
        return /^(it|test|describe|afterEach|beforeEach|afterAll|beforeAll)(?:\.|$)/.exec(node.expression.getText(source))?.[1];
    };
    const unwrap = node => {
        while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node))) node = node.expression;
        return node;
    };
    const collection = node => node && (ts.isObjectLiteralExpression(unwrap(node)) || ts.isArrayLiteralExpression(unwrap(node)));
    const keyName = node => node.name ? (ts.isStringLiteralLike(node.name) ? node.name.text : node.name.getText(source)) : '';
    const commonJS = node => ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isPropertyAccessExpression(node.left) && ts.isIdentifier(node.left.expression)
        && node.left.expression.text === 'module' && node.left.name.text === 'exports';
    const micro = node => {
        const body = node.body;
        if (!body) return false;
        if ([ts.SyntaxKind.NullKeyword, ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword].includes(body.kind)) return true;
        if (ts.isIdentifier(body) && body.text === 'undefined') return true;
        if (ts.isPrefixUnaryExpression(body) && body.operator === ts.SyntaxKind.ExclamationToken && ts.isIdentifier(body.operand)) return true;
        if (ts.isBinaryExpression(body) && ts.isIdentifier(body.left) && ts.isNumericLiteral(body.right)
            && [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(body.operatorToken.kind)) return true;
        return ts.isCallExpression(body) && ts.isIdentifier(body.expression) && /^set[A-Z]/.test(body.expression.text)
            && body.arguments.length === 1 && ((ts.isArrowFunction(body.arguments[0]) && micro(body.arguments[0]))
                || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(body.arguments[0].kind));
    };
    const leading = owner => {
        const comments = ts.getLeadingCommentRanges(input.source, owner.getFullStart()) || [];
        const adjacent = [];
        let next = line(owner.getStart(source));
        for (const c of [...comments].reverse()) {
            if (line(c.end) < next - 1) break;
            adjacent.unshift(c);
            next = line(c.pos);
        }
        return adjacent;
    };
    const commentsFor = (node, owner) => {
        const own = leading(node);
        if (own.length) return own;
        const comments = leading(owner);
        if (comments.length) return comments;
        // JSX comment expressions immediately before a gate belong to that gate only.
        const expression = ts.isJsxExpression(node.parent) ? node.parent : node;
        const siblings = expression.parent?.children;
        if (!siblings) return [];
        let index = siblings.indexOf(expression) - 1;
        while (index >= 0 && ts.isJsxText(siblings[index]) && !siblings[index].getText(source).trim()) index--;
        const previous = siblings[index];
        if (!previous || !ts.isJsxExpression(previous) || previous.expression
            || line(expression.getStart(source)) - line(previous.end) > 1) return [];
        return ts.getTrailingCommentRanges(input.source, previous.getStart(source) + 1) || [];
    };
    // atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-9
    // Статический SQL остаётся кандидатом независимо от формы записи; неизвестные значения параметров нельзя считать установленной логикой запроса.
    const sqlCandidate = node => {
        const terminal = expr => ts.isIdentifier(expr) ? expr.text : ts.isPropertyAccessExpression(expr) ? expr.name.text : '';
        if (ts.isTaggedTemplateExpression(node) && terminal(node.tag) === 'sql'
            && (ts.isNoSubstitutionTemplateLiteral(node.template) || ts.isTemplateExpression(node.template))) return 'tag';
        if (!ts.isCallExpression(node) || !['query', 'execute', 'exec', 'raw'].includes(terminal(node.expression))) return undefined;
        const value = node.arguments[0];
        if (!value || !(ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value))) return undefined;
        const first = value.text.trimStart().split(/\s+/, 1)[0].toUpperCase();
        return new Set(['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE',
            'EXPLAIN', 'PRAGMA', 'BEGIN', 'COMMIT', 'ROLLBACK', 'MERGE', 'GRANT', 'REVOKE', 'VALUES', 'REPLACE', 'SHOW', 'SET']).has(first) ? 'call' : undefined;
    };
    const visit = (node, context = {}) => {
        const test = testName(node);
        const sql = sqlCandidate(node);
        const testCallback = functions.has(node.kind) && testName(node.parent);
        let owner = node;
        if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node)) && ts.isVariableDeclaration(node.parent)) owner = node.parent.parent.parent;
        if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node)) && ts.isCallExpression(node.parent)) owner = node.parent;
        const config = context.configPath !== undefined && !context.test && !fixtureFile && !context.style;
        const variable = ts.isVariableStatement(node);
        const topVariable = variable && ts.isSourceFile(node.parent);
        const capability = ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'canDo' && node.arguments[1] && ts.isStringLiteral(node.arguments[1]);
        const exportStatement = ts.isExpressionStatement(node) && commonJS(node.expression);
        const moduleCall = ts.isExpressionStatement(node) && ts.isSourceFile(node.parent)
            && ts.isCallExpression(node.expression) && node.expression.expression.getText(source) === 'configureNavigation';
        const expressionDecision = ts.isConditionalExpression(node) || (ts.isBinaryExpression(node) && logical.has(node.operatorToken.kind));
        const configPart = config && (ts.isObjectLiteralExpression(node) || ts.isArrayLiteralExpression(node)
            || ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node));
        let kind = ts.SyntaxKind[node.kind];
        let role;
        let name = node.name?.getText(source) || kind;
        if (sql) {
            kind = 'SQLQuery';
            role = 'sql';
            name = (sql === 'tag' ? node.tag : node.expression).getText(source);
        } else if (test) {
            kind = 'TestScenario';
            role = test === 'describe' ? 'test_container' : ['it', 'test'].includes(test) ? 'scenario' : 'fixture';
            name = `${test}${ts.isCallExpression(node.expression) || ts.isTaggedTemplateExpression(node.expression) ? '.each' : ''}(${node.arguments[0] && ts.isStringLiteral(node.arguments[0]) ? node.arguments[0].text.slice(0,100) : 'dynamic scenario'})`;
        } else if (configPart) {
            role = 'config';
            name = context.configPath;
        } else if (capability) {
            kind = 'CapabilityGate';
            role = 'decision';
            name = `canDo ${node.arguments[1].text}`;
        } else if (variable) {
            kind = 'VariableStatement';
            role = !topVariable ? 'local_declaration' : node.declarationList.declarations.some(d => collection(d.initializer)) ? (fixtureFile ? 'fixture' : 'config') : 'declaration';
            name = node.declarationList.declarations.map(d => d.name.getText(source)).join(', ');
        } else if (exportStatement || moduleCall) {
            kind = exportStatement ? 'CommonJSExport' : 'ConfigurationCall';
            role = 'config';
            name = exportStatement ? 'module.exports' : 'configureNavigation';
        } else if (expressionDecision || decisions.has(node.kind)) role = 'decision';
        else if (declarations.has(node.kind)) role = 'declaration';
        else if (functions.has(node.kind) && micro(node)) role = 'micro_callback';
        let parent = context.parent;
        if (!testCallback && (sql || test || capability || configPart || variable || exportStatement || moduleCall
            || expressionDecision || decisions.has(node.kind) || declarations.has(node.kind) || functions.has(node.kind))) {
            const start = node.getStart(source);
            const annotationOwner = leading(node).length ? node : owner;
            const comments = commentsFor(node, annotationOwner);
            const body = node.thenStatement || node.statement || node.body;
            const header = ts.isConditionalExpression(node) ? node.questionToken.end
                : expressionDecision ? node.operatorToken.end : body ? body.getStart(source) : start;
            const unit = {kind, ...location(input, position, kind, start, node.end, annotationOwner.getStart(source), annotationOwner.end),
                header_end: Math.max(line(start), line(header)), comment_start: comments.length ? line(comments[0].pos) : line(start),
                name, ...annotation(comments.map(c => input.source.slice(c.pos, c.end)).join('\n'))};
            if (role) unit.role = role;
            if (sql) unit.sql_interpolated = sql === 'tag' && ts.isTemplateExpression(node.template);
            if (parent) unit.parent_id = parent;
            if (configPart) unit.config_path = context.configPath;
            if (expressionDecision) {
                unit.operator = ts.isConditionalExpression(node) ? '?:' : node.operatorToken.getText(source);
                unit.jsx_gate = ts.isJsxExpression(node.parent);
            }
            if (test) unit.test_role = role === 'scenario' ? 'test_scenario' : role === 'fixture' ? 'test_infrastructure' : 'test_container';
            units.push(unit);
            parent = unit.id;
        }
        ts.forEachChild(node, child => {
            const next = {parent, test: context.test || Boolean(test), style: context.style};
            if (ts.isJsxAttribute(node) && ['css', 'style'].includes(keyName(node))) next.style = true;
            if (config && !functions.has(node.kind)) {
                if (ts.isPropertyAssignment(node) && child === node.initializer) next.configPath = context.configPath;
                else if (ts.isObjectLiteralExpression(node) && node.properties.includes(child)) {
                    if (!['css', 'style', 'sx'].includes(keyName(child))) next.configPath = `${context.configPath}.${keyName(child)}`;
                } else if (ts.isArrayLiteralExpression(node)) next.configPath = `${context.configPath}[${node.elements.indexOf(child)}]`;
                else if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node)
                    || (ts.isConditionalExpression(node) && child !== node.condition)
                    || (ts.isBinaryExpression(node) && logical.has(node.operatorToken.kind) && child === node.right)) next.configPath = context.configPath;
            }
            if (!next.test && !fixtureFile && !next.style) {
                if (ts.isVariableDeclaration(node) && child === node.initializer && collection(child)
                    && (ts.isSourceFile(node.parent.parent.parent) || /\b(?:ProjectConfig|ServerOptions)\b/.test(node.type?.getText(source) || '') || configNames.has(keyName(node)))) next.configPath = keyName(node);
                if (commonJS(node) && child === node.right) next.configPath = 'module.exports';
                if (ts.isReturnStatement(node) && collection(child) && ts.isObjectLiteralExpression(unwrap(child))
                    && unwrap(child).properties.some(p => ['server', 'proxy', 'guard'].includes(keyName(p)))) next.configPath = 'return';
                if (ts.isJsxAttribute(node) && configNames.has(keyName(node))) next.configPath = `jsx.${keyName(node)}`;
                if (ts.isJsxExpression(node) && context.configPath !== undefined) next.configPath = context.configPath;
                if (ts.isCallExpression(node) && ['configureNavigation', 'useQuery'].includes(node.expression.getText(source)) && collection(child)) next.configPath = node.expression.getText(source);
            }
            visit(child, next);
        });
    };
    visit(source);
    const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, source.languageVariant, input.source);
    const tokens = [], codeLines = new Set();
    let kind;
    while ((kind = scanner.scan()) !== ts.SyntaxKind.EndOfFileToken) {
        tokens.push(`${kind}:${scanner.getTokenText()}`);
        for(let n=line(scanner.getTokenPos());n<=line(Math.max(scanner.getTokenPos(),scanner.getTextPos()-1));n++) codeLines.add(n);
    }
    const policy = policyFacts(input, source, position);
    for (const unit of units) unit.ast_nodes=policy.sizes.get(`${unit.start_offset}:${unit.end_offset}`) || 1;
    return {path: input.path, facts_version:2, units, tokens, policy_units:policy.policy_units, annotations:commentFacts(input,position,policy.comments), generated:policy.comments.some(c=>/^(?:\/\/|\/\*)\s*(?:Code generated .* DO NOT EDIT\.|@generated\b)/i.test(input.source.slice(c.pos,c.end))), code_lines:[...codeLines]};
}

// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
// Аннотация YAML должна относиться к своему ключу или значению; текст строкового значения не выполняет обязательство комментария.
function configuration(input) {
    yaml ??= require(path.join(modules, 'yaml'));
    const counter = new yaml.LineCounter();
    const doc = yaml.parseDocument(input.source, {lineCounter: counter, keepSourceTokens: true, uniqueKeys: true});
    if (doc.errors.length) return {path: input.path, units: [], error: doc.errors[0].message};
    const position = pos => {
        const p = counter.linePos(pos);
        return {line: p.line, column: p.col};
    };
    const comments = [];
    const collect = token => {
        if (!token || typeof token !== 'object') return;
        if (token.type === 'comment') { comments.push({pos: token.offset, end: token.offset + token.source.length}); return; }
        for (const value of Object.values(token)) {
            if (Array.isArray(value)) value.forEach(collect);
            else if (value && typeof value === 'object') collect(value);
        }
    };
    for (const token of new yaml.Parser().parse(input.source)) collect(token);
    comments.sort((a, b) => a.pos - b.pos);
    const astCounts = new Map();
    const measure = node => {
        if (!node?.range) return 0;
        let count=1;
        if(yaml.isMap(node)) for(const pair of node.items) {
            const size=1+measure(pair.key)+measure(pair.value);
            count+=size;
            if(pair.key?.range) astCounts.set(`${pair.key.range[0]}:${pair.value?.range?.[1] ?? pair.key.range[1]}`,size);
        }
        if(yaml.isSeq(node)) for(const child of node.items) count+=measure(child);
        astCounts.set(`${node.range[0]}:${node.range[1]}`,count);
        return count;
    };
    measure(doc.contents);
    const claimed = new Set();
    const leading = offset => {
        let boundary = offset;
        const out = [];
        for (const c of [...comments].reverse()) {
            if (c.end > boundary) continue;
            if (input.source.slice(c.end, boundary).trim() || position(boundary).line - position(c.end).line > 1) break;
            const prefix = input.source.slice(input.source.lastIndexOf('\n', c.pos - 1) + 1, c.pos);
            if (prefix.trim()) break; // inline comments belong to the preceding key/value
            if (!claimed.has(c.pos)) out.unshift(c);
            boundary = c.pos;
        }
        return out;
    };
    const trailing = node => node?.range && node.comment
        ? comments.filter(c => c.pos >= node.range[1] && c.end <= node.range[2]) : [];
    const units = [];
    const add = (kind, start, end, name, owned, parent, header = start) => {
        owned = [...new Map(owned.filter(c => !claimed.has(c.pos)).map(c => [c.pos, c])).values()].sort((a, b) => a.pos - b.pos);
        owned.forEach(c => claimed.add(c.pos));
        const unit = {kind, ...location(input, position, kind, start, end), header_end: position(header).line,
            comment_start: owned.length ? position(owned[0].pos).line : position(start).line,
            name, role: 'config', config_path: name, ast_nodes:astCounts.get(`${start}:${end}`) || 1,
            ...annotation(owned.map(c => input.source.slice(c.pos, c.end)).join('\n'))};
        if (parent) unit.parent_id = parent;
        unit.comment_offsets = owned.map(c => ({start_offset: c.pos, end_offset: c.end}));
        units.push(unit);
        return unit.id;
    };
    const visit = (node, names, parent, record = false, root = false) => {
        if (!node?.range) return;
        const name = names.join('.');
        if (!root && !record && (yaml.isMap(node) || yaml.isSeq(node))) {
            parent = add(yaml.isMap(node) ? 'YAMLMappingGroup' : 'YAMLSequenceGroup', node.range[0], node.range[1], name, [...leading(node.range[0]), ...trailing(node)], parent);
        }
        if (yaml.isMap(node)) {
            for (const pair of node.items) {
                const key = pair.key;
                if (!key?.range) continue;
                const childName = [...names, String(key.value)];
                const value = pair.value;
                const end = value?.range?.[1] ?? key.range[1];
                const owned = leading(key.range[0]);
                // Comments after ':' on the key line are key-owned, not value group prose.
                const valueStart = value?.range?.[0] ?? end;
                owned.push(...comments.filter(c => c.pos >= key.range[1] && c.end <= valueStart
                    && position(c.pos).line === position(key.range[0]).line));
                if (value && !yaml.isCollection(value)) owned.push(...leading(valueStart), ...trailing(value));
                const id = add(yaml.isMap(value) ? 'YAMLMapping' : yaml.isSeq(value) ? 'YAMLSequence' : 'YAMLScalar',
                    key.range[0], end, childName.join('.'), owned, parent);
                visit(value, childName, id);
            }
        } else if (yaml.isSeq(node)) {
            node.items.forEach((child, i) => {
                const item = node.srcToken?.items?.[i];
                const dash = item?.start?.find(t => t.type === 'seq-item-ind');
                const start = dash?.offset ?? child?.range?.[0];
                if (start === undefined) return;
                const end = child?.range?.[1] ?? start + 1;
                const owned = leading(start);
                // A comment between '-' and a record's first key belongs to the record.
                owned.push(...comments.filter(c => c.pos >= start && c.end <= (child?.range?.[0] ?? end)), ...trailing(child));
                const childName = [...names, String(i)];
                const id = add(yaml.isMap(child) ? 'YAMLSequenceRecord' : 'YAMLSequenceItem', start, end, childName.join('.'), owned, parent);
                visit(child, childName, id, true);
            });
        }
    };
    visit(doc.contents, [], undefined, false, true);
    return {path: input.path, facts_version:2, units, tokens: [JSON.stringify(doc.toJS({maxAliasCount: 100}))], annotations:commentFacts(input,position,comments), generated:comments.some(c=>/^#\s*(?:Code generated .* DO NOT EDIT\.|@generated\b)/i.test(input.source.slice(c.pos,c.end))), code_lines:input.source.split('\n').flatMap((line,i)=>line.trim() && !comments.some(c=>position(c.pos).line===i+1 && !line.slice(0,position(c.pos).column-1).trim()) ? [i+1] : [])};
}

const inputs = JSON.parse(fs.readFileSync(0, 'utf8'));
// atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
// Ошибка одного исходника не отменяет полезные результаты остальных, но не позволяет считать всю выборку успешно разобранной.
function parseInput(input) {
    try { return /\.ya?ml$/.test(input.path) ? configuration(input) : typescript(input); }
    catch (error) { return {path: input.path, units: [], error: String(error.message)}; }
}
const results = inputs.map(parseInput);
process.stdout.write(JSON.stringify(results));
