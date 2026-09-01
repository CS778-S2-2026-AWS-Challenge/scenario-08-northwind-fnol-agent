import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../admin/app.js', import.meta.url), 'utf8');

function element() {
  return {
    addEventListener() {},
    classList: { contains: () => false, toggle() {} },
    focus() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
  };
}

function loadConsole() {
  const elements = new Map();
  const document = {
    activeElement: null,
    body: element(),
    createElement() {
      const node = element();
      Object.defineProperty(node, 'textContent', {
        set(value) { node.innerHTML = value == null ? '' : String(value); },
      });
      return node;
    },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
  };
  const context = vm.createContext({
    document,
    fetch: () => new Promise(() => {}),
    globalThis: {},
    localStorage: { getItem: () => '' },
    location: { hash: '' },
    matchMedia: () => ({ addEventListener() {}, matches: false }),
    addEventListener() {},
  });
  vm.runInContext(source, context);
  return context;
}

test('a configuration with validation evidence is not labelled Not validated', () => {
  const context = loadConsole();
  const html = context.renderRecords([{
    configuration_id: 'cfg_validated',
    revision: 2,
    state: 'published',
    values: { name: 'Validated configuration' },
    validation_evidence: {
      result: 'passed',
    },
  }]);

  assert.match(html, /Validation evidence recorded/);
  assert.doesNotMatch(html, /Not validated/);
});

test('null and empty validation evidence are labelled Not validated', () => {
  const context = loadConsole();
  const records = [null, {}].map((validation_evidence, index) => ({
    configuration_id: `cfg_unvalidated_${index}`,
    revision: 1,
    state: 'draft',
    values: { name: `Unvalidated configuration ${index}` },
    validation_evidence,
  }));

  const html = context.renderRecords(records);

  assert.equal(html.match(/Not validated/g)?.length, 2);
});
