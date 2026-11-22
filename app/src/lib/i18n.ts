import english from './locales/en.json' with { type: 'json' };
export type Language = 'ru' | 'en';
const catalog: Record<string,string> = english;
const cache = new Map<string,string>();
const patterns = Object.entries(catalog).filter(([key])=>/\{\d+\}/.test(key)).map(([key,value])=>{
  const ids:number[]=[];
  const escaped=key.split(/(\{\d+\})/).map(piece=>{
    if(/^\{\d+\}$/.test(piece)) { ids.push(Number(piece.slice(1,-1))); return '([\\s\\S]*?)'; }
    return piece.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  }).join('');
  return {regex:new RegExp('^'+escaped+'$'),value,ids,prefix:key.slice(0,key.indexOf('{')),specificity:key.replace(/\{\d+\}/g,'').length};
}).sort((a,b)=>b.specificity-a.specificity||b.prefix.length-a.prefix.length);
export function translate<T>(value:T, language:Language):T {
  if(language==='ru'||typeof value!=='string'||!/[а-яё]/i.test(value))return value;
  const key=value.replace(/\s+/g,' ').trim();
  let result=cache.get(key)??catalog[key];
  if(result===undefined&&key.length<=16000) {
    for(const p of patterns) {
      if(!key.startsWith(p.prefix))continue;
      const match=key.match(p.regex);
      if(match) {
        const args=new Map(p.ids.map((id,i)=>[id,match[i+1]]));
        result=p.value.replace(/\{(\d+)\}/g,(_,id)=>args.get(Number(id))??'');
        break;
      }
    }
  }
  if(result===undefined)return value;
  if(cache.size>=512)cache.delete(cache.keys().next().value!);
  cache.set(key,result);
  return ((value.match(/^\s*/)?.[0]??'')+result+(value.match(/\s*$/)?.[0]??'')) as T;
}
export function countLabel(n:number, forms:{one:string;few:string;many:string}, language:Language) {
  const kind=new Intl.PluralRules(language).select(n);
  return translate(kind==='one'?forms.one:kind==='few'?forms.few:forms.many,language);
}
