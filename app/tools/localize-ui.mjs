// Source migration/audit only: presentation expressions, never API payloads.
import fs from 'node:fs';
import path from 'node:path';
import { parse } from 'svelte/compiler';
const root=path.resolve(import.meta.dirname,'..');
const entries=new Map();
const ru=/[А-Яа-яЁё]/;
const attrs=new Set(['title','hint','placeholder','aria-label','description','emptyText','label']);
function record(s,file) {
  if(typeof s!=='string'||!ru.test(s))return;
  s=s.replace(/\s+/g,' ').trim();
  if(s&&!entries.has(s))entries.set(s,file);
}
function userData(expr,file) {
  return /\.(?:name|text|content|argument|result|question|answer|heard|reply|reference_text|instructions)(?:\??\.[\w(]|\s*$)/.test(expr) ||
    /^(?:text|content|reply|question|answer|phrase|n|line|v|voice|value)$/.test(expr.trim()) ||
    /^(?:m|message|msg)\./.test(expr.trim());
}
function scanScript(node,file) {
  if(!node||typeof node!=='object')return;
  if(node.type==='Literal')record(node.value,file);
  if(node.type==='TemplateLiteral')record(node.quasis.map((q,i)=>q.value.cooked+(i<node.expressions.length?`{${i}}`:'' )).join(''),file);
  if(node.type==='BinaryExpression'&&node.operator==='+') {
    let n=0;
    function fragment(x) {
      if(x.type==='Literal'&&typeof x.value==='string')return x.value;
      if(x.type==='BinaryExpression'&&x.operator==='+')return fragment(x.left)+fragment(x.right);
      return `{${n++}}`;
    }
    record(fragment(node),file);
  }
  for(const [key,value] of Object.entries(node)) {
    if(['loc','parent'].includes(key))continue;
    if(Array.isArray(value))value.forEach(x=>scanScript(x,file));
    else if(value&&typeof value==='object')scanScript(value,file);
  }
}
function processComponent(file,apply) {
  const source=fs.readFileSync(file,'utf8');
  const ast=parse(source,{modern:true});
  const edits=[];
  scanScript(ast.instance,file);
  function walk(node,off=false) {
    if(!node||typeof node!=='object')return;
    const attributes=node.attributes??[];
    off ||= ['pre','code'].includes(node.name)||attributes.some(a=>a.type==='Attribute'&&a.name==='data-i18n'&&a.value?.[0]?.data==='off');
    if(off)return;
    if(node.type==='Text') {
      record(node.data,file);
      if(ru.test(node.data))edits.push([node.start,node.end,`{uiText(${JSON.stringify(node.data)})}`]);
      return;
    }
    if(node.type==='ExpressionTag') {
      scanScript(node.expression,file);
      const expr=source.slice(node.expression.start,node.expression.end);
      if(!/^(?:t|uiText)\(/.test(expr)&&!userData(expr,file))edits.push([node.expression.start,node.expression.end,`uiText(${expr})`]);
      return;
    }
    if(node.type==='Attribute') {
      const expressions=Array.isArray(node.value)?node.value:[node.value];
      expressions.filter(v=>v?.type==='ExpressionTag').forEach(v=>scanScript(v.expression,file));
      if(!attrs.has(node.name)||!node.value||typeof node.value==='boolean')return;
      const values=Array.isArray(node.value)?node.value:[node.value];
      if(!values.length)return;
      node={...node,value:values};
      if(node.value.length===1&&node.value[0].type==='Text') {
        record(node.value[0].data,file);
        if(ru.test(node.value[0].data))edits.push([node.start,node.end,`${node.name}={uiText(${JSON.stringify(node.value[0].data)})}`]);
      } else if(node.value.length===1&&node.value[0].type==='ExpressionTag') {
        const e=node.value[0].expression,expr=source.slice(e.start,e.end);
        scanScript(e,file);
        if(!/^(?:t|uiText)\(/.test(expr)&&!userData(expr,file))edits.push([e.start,e.end,`uiText(${expr})`]);
      } else {
        const expr=node.value.map(v=>v.type==='Text'?JSON.stringify(v.data):`String(${source.slice(v.expression.start,v.expression.end)})`).join(' + ');
        node.value.filter(v=>v.type==='Text').forEach(v=>record(v.data,file));
        edits.push([node.start,node.end,`${node.name}={uiText(${expr})}`]);
      }
      return;
    }
    for(const [key,value] of Object.entries(node)) {
      if(['loc','parent','expression','test','key','context','index','metadata'].includes(key))continue;
      if(Array.isArray(value))value.forEach(x=>walk(x,off));
      else if(value&&typeof value==='object')walk(value,off);
    }
  }
  walk(ast.fragment);
  if(edits.length) {
    let relative=path.relative(path.dirname(file),path.join(root,'src/lib/i18n.svelte')).replaceAll('\\','/');
    if(!relative.startsWith('.'))relative='./'+relative;
    if(!source.includes('t as uiText')) {
      if(ast.instance)edits.push([ast.instance.content.start,ast.instance.content.start,`\n  import { t as uiText } from ${JSON.stringify(relative)};\n`]);
      else edits.push([0,0,`<script lang="ts">import { t as uiText } from ${JSON.stringify(relative)};</script>\n`]);
    }
    let result=source;
    for(const [start,end,text] of edits.sort((a,b)=>b[0]-a[0]))result=result.slice(0,start)+text+result.slice(end);
    const checked=parse(result,{modern:true});
    const withoutLocaleImport=s=>s.replace(/import\s*\{[^}]*t\s+as\s+uiText[^}]*\}\s*from\s*["'][^"']+["'];?/g,'').trim();
    const before=ast.instance?source.slice(ast.instance.content.start,ast.instance.content.end):'';
    const after=checked.instance?result.slice(checked.instance.content.start,checked.instance.content.end):'';
    if(withoutLocaleImport(before)!==withoutLocaleImport(after))throw Error('Migration changed application logic: '+file);
    if(apply)fs.writeFileSync(file,result);
  }
}
const files=fs.readdirSync(path.join(root,'src'),{recursive:true}).filter(p=>p.endsWith('.svelte')).map(p=>path.join(root,'src',p));
files.forEach(f=>processComponent(f,process.argv.includes('--apply')));
for(const name of ['lib/settingsIndex.ts','lib/theme.ts','lib/store.svelte.ts','lib/dialog.svelte.ts','avatar/controls.ts','avatar/main.ts']) {
  const file=path.join(root,'src',name),source=fs.readFileSync(file,'utf8');
  // TS literals are inventoried separately by the TypeScript AST.
  const ts=await import('typescript');
  function visit(node) {
    if(ts.isStringLiteral(node)||ts.isNoSubstitutionTemplateLiteral(node))record(node.text,file);
    if(ts.isTemplateExpression(node))record(node.head.text+node.templateSpans.map((span,i)=>`{${i}}`+span.literal.text).join(''),file);
    ts.forEachChild(node,visit);
  }
  visit(ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true));
}
const report=Object.fromEntries([...entries].sort((a,b)=>a[0].localeCompare(b[0],'ru')));
const target=path.join(root,'../reports/ui-i18n-source.json');
fs.writeFileSync(target,JSON.stringify(report,null,2)+'\n');
console.log(`${Object.keys(report).length} strings in ${files.length} components; ${target}`);
