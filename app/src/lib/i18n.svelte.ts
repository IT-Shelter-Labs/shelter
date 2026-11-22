import { translate, countLabel, type Language } from './i18n';
import { language, saveLanguage } from './language';
export const locale=$state({language:language()});
export function t<T>(value:T):T {return translate(value,locale.language);}
export function count(n:number, forms:{one:string;few:string;many:string}) {return countLabel(n,forms,locale.language);}
export function setLanguage(value:unknown) {
  locale.language=saveLanguage(value);
}
if(typeof window!=='undefined')window.addEventListener('storage',e=>{
  if(e.key==='jarvis.ui.language')setLanguage(e.newValue);
});
