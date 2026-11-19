// atomic-spec://ATOMIC-GUARD-001/DR-19
// Политика YAML является ограниченными данными, а не способом исполнения кода или неоднозначного изменения правил проверки.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
// atomic-spec://ATOMIC-GUARD-001/DR-19
// Неоднозначная либо чрезмерно большая политика не может стать рабочей конфигурацией; её загрузка должна завершиться явным отказом.
function main() {
try {
    const yaml = require(path.resolve(process.argv[2], 'yaml'));
    const input = fs.readFileSync(0, 'utf8');
    if (Buffer.byteLength(input) > 256 * 1024) throw new Error('policy exceeds 256 KiB');
    const doc = yaml.parseDocument(input, {version: '1.2', schema: 'core', strict: true, uniqueKeys: true, merge: false});
    if (doc.errors.length || doc.warnings.length) throw new Error((doc.errors[0] || doc.warnings[0]).message);
    if (doc.directives.yaml.version !== '1.2') throw new Error('policy requires YAML 1.2');
    yaml.visit(doc, {
        // atomic-spec://ATOMIC-GUARD-001/DR-19
        // Неявные преобразования, ссылки и небезопасные значения YAML не должны менять смысл заявленной политики.
        Node(key, node, context) {
            if (context.length > 64) throw new Error('policy nesting exceeds 64');
            if (node.anchor || node.tag || yaml.isAlias(node)) throw new Error('policy tags, anchors and aliases are not supported');
            if (yaml.isMap(node)) for (const pair of node.items) {
                if (!yaml.isScalar(pair.key) || typeof pair.key.value !== 'string') throw new Error('policy keys must be strings');
            }
            if (yaml.isScalar(node) && typeof node.value === 'number' && !Number.isSafeInteger(node.value)) {
                throw new Error('policy numbers must be finite safe integers');
            }
        },
    });
    process.stdout.write(JSON.stringify(doc.toJS({maxAliasCount: 0})));
} catch (error) {
    process.stderr.write(`Invalid YAML policy: ${error.message}\n`);
    process.exitCode = 2;
}
}
main();
