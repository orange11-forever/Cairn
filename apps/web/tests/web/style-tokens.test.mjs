import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const FILES = [
  'main.css', 'workbench.css', 'auth.css', 'primitives.css', 'shell.css',
  'code.css', 'terminal.css', 'coding-overview.css', 'architecture-graph.css',
];
const SIZE_OK = /^(var\(--text-(xs|sm|md|base|lg|xl|2xl)\)|inherit|0|[\d.]+em)$/;
const WEIGHT_OK = /^(var\(--weight-(regular|semibold|bold)\)|inherit)$/;
const RADIUS_PART_OK = /^(var\(--radius(-sm|-lg|-stone)?\)|0|50%|999px|inherit)$/;
const LITERAL_COLOUR = /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?)\(/i;

function rules(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({ selector: match[1].trim(), body: match[2] }));
}

function declarations(body) {
  return body.split(';').map((part) => part.trim()).filter(Boolean).map((part) => {
    const colon = part.indexOf(':');
    return [part.slice(0, colon).trim(), part.slice(colon + 1).trim()];
  });
}

test('stylesheets take colour, type size, weight and radius from tokens', async () => {
  const violations = [];
  for (const file of FILES) {
    const css = await readFile(new URL(`../../styles/${file}`, import.meta.url), 'utf8');
    for (const { selector, body } of rules(css)) {
      for (const [property, value] of declarations(body)) {
        const where = `${file} ${selector.replace(/\s+/g, ' ')} { ${property}: ${value} }`;
        if (property.startsWith('--')) continue;
        if (LITERAL_COLOUR.test(value)) violations.push(`colour  ${where}`);
        if (property === 'font-size' && !SIZE_OK.test(value) && !selector.includes('.knowledge-document')) violations.push(`size    ${where}`);
        if (property === 'font-weight' && !WEIGHT_OK.test(value)) violations.push(`weight  ${where}`);
        if (property === 'border-radius' && !value.split(/\s+/).every((part) => RADIUS_PART_OK.test(part))) violations.push(`radius  ${where}`);
      }
    }
  }
  assert.deepEqual(violations, [], `\n${violations.join('\n')}`);
});

test('the long-form reader is the only place allowed its own type scale', async () => {
  const css = await readFile(new URL('../../styles/workbench.css', import.meta.url), 'utf8');
  assert.match(css, /\.knowledge-document-markdown h1\s*\{[^}]*font-size:/);
});
