import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { parse } from 'svelte/compiler';
import { translate, countLabel } from '../src/lib/i18n.ts';
import { language, saveLanguage } from '../src/lib/language.ts';

const root = path.resolve(import.meta.dirname, '..');
const english = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/locales/en.json'), 'utf8'));

test('UI translation preserves data, whitespace and Russian text when selected', () => {
  assert.equal(translate('  Настройки\n', 'en'), '  Settings\n');
  assert.equal(translate('Настройки', 'ru'), 'Настройки');
  assert.equal(translate('Это мой личный разговор', 'en'), 'Это мой личный разговор');
  assert.equal(translate(42, 'en'), 42);
  assert.equal(translate(null, 'en'), null);
  const name = '<script>Пиппа</script>';
  assert.equal(translate(`Сменит персонажа на «${name}»`, 'en'), `Switches character to “${name}”`);
});

test('full dynamic messages take precedence over shorter fragments', () => {
  assert.equal(translate('Удалить «Мой персонаж»', 'en'), 'Delete “Мой персонаж”');
  assert.equal(translate('обрыв связи, попытка 2 из 3', 'en'), 'connection lost, attempt 2 of 3');
});

test('Russian and English count labels use their own plural rules', () => {
  const forms = {one:'сценарий', few:'сценария', many:'сценариев'};
  for (const [n,ru,en] of [[1,'сценарий','Scenario'],[2,'сценария','scenarios'],[5,'сценариев','scenarios'],[21,'сценарий','scenarios'],[22,'сценария','scenarios']]) {
    assert.equal(countLabel(n,forms,'ru'), ru);
    assert.equal(countLabel(n,forms,'en').toLowerCase(), en.toLowerCase());
  }
});

test('language selection persists and updates accessibility language', () => {
  const values = new Map();
  const events = [];
  const previous = Object.fromEntries(['localStorage','document','window','CustomEvent'].map(key=>[key,globalThis[key]]));
  globalThis.localStorage = {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
  globalThis.document = {documentElement:{lang:''}};
  globalThis.window = {dispatchEvent:event=>events.push(event)};
  globalThis.CustomEvent = class {constructor(type,options){this.type=type;this.detail=options.detail;}};
  try {
    assert.equal(saveLanguage('en'), 'en');
    assert.equal(language(), 'en');
    assert.equal(document.documentElement.lang, 'en');
    assert.equal(events.at(-1).detail, 'en');
    assert.equal(saveLanguage('unsupported'), 'ru');
  } finally {
    for (const [key,value] of Object.entries(previous)) {
      if(value===undefined)delete globalThis[key];else globalThis[key]=value;
    }
  }
});

test('all literal UI labels have a translation; free text is not rewritten', () => {
  const missing = new Set();
  function walk(node) {
    if(!node||typeof node!=='object')return;
    if(node.type==='CallExpression'&&node.callee?.name==='uiText'&&node.arguments?.[0]?.type==='Literal') {
      const value=node.arguments[0].value;
      if(typeof value==='string'&&/[а-яё]/i.test(value)) {
        const key=value.replace(/\s+/g,' ').trim();
        if(!english[key])missing.add(key);
      }
    }
    for(const [key,value] of Object.entries(node)) {
      if(['loc','metadata'].includes(key))continue;
      if(Array.isArray(value))value.forEach(walk);else if(value&&typeof value==='object')walk(value);
    }
  }
  for(const name of fs.readdirSync(path.join(root,'src'),{recursive:true}).filter(n=>n.endsWith('.svelte'))) {
    walk(parse(fs.readFileSync(path.join(root,'src',name),'utf8'),{modern:true}));
  }
  assert.deepEqual([...missing], []);
  for(const [file,pattern] of [
    ['components/home/ChatCard.svelte', /uiText\(m\.text\)/],
    ['components/home/History.svelte', /uiText\(g\.(?:heard|reply)\)/],
    ['components/MicWizard.svelte', /uiText\(speech\.text/],
    ['views/Persona.svelte', /uiText\(fileName\(/],
  ]) assert.doesNotMatch(fs.readFileSync(path.join(root,'src',file),'utf8'), pattern);
  assert.equal(english['— выберите —'], '— Select —');
  for(const value of Object.values(english)) assert.doesNotMatch(value, /вЂ|РџР|РЎР/, 'UTF-8 must not be decoded as a Windows code page');
});
