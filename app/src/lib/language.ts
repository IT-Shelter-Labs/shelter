import type { Language } from './i18n';
export function language():Language {
  try{return localStorage.getItem('jarvis.ui.language')==='en'?'en':'ru';}catch{return 'ru';}
}
export function saveLanguage(value:unknown):Language {
  const next=value==='en'?'en':'ru';
  try{localStorage.setItem('jarvis.ui.language',next);}catch{}
  if(typeof document!=='undefined') {
    document.documentElement.lang=next;
    document.title="Shelter";
  }
  if(typeof window!=='undefined')window.dispatchEvent(new CustomEvent('jarvis-language',{detail:next}));
  return next;
}
