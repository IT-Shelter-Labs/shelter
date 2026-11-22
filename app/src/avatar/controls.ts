import { translate } from '../lib/i18n';
import { language } from '../lib/language';
type Commands = { post: (path: string, body: any) => Promise<any>; motion: (id: string) => void;
  seat: (kind: string) => void; home: () => void; settings: () => void; menu: (open: boolean) => void };

/** Local DOM controls never interpret model-generated text as HTML or commands. */
export class Controls {
  root = document.createElement('div');
  badge = document.createElement('div');
  private timers: any[] = [];
  private status = '';
  private until = 0;
  private input: HTMLInputElement;
  private currentRun = '';
  private labels = new Map<HTMLElement,string>();
  mood = '';
  constructor(private commands: Commands) {
    this.root.id = 'companion-menu'; this.root.hidden = true;
    this.root.setAttribute('role', 'dialog'); this.root.setAttribute('aria-label', 'Управление персонажем');
    const title = document.createElement('strong'); this.labels.set(title,'Рядом с вами'); this.root.append(title);
    const button = (name: string, action: () => unknown) => {
      const b = document.createElement('button'); this.labels.set(b,name);
      b.onclick = () => { Promise.resolve(action()).catch(e => this.notice(String(e), false)); }; this.root.append(b);
    };
    button('Говорить', () => { this.close(); return commands.post('/api/listen', {}); });
    this.input = document.createElement('input'); this.input.placeholder = 'Написать ассистенту…'; this.input.maxLength = 2000;
    this.input.onkeydown = e => { if (e.key === 'Enter' && this.input.value.trim()) { void commands.post('/api/ask', { text: this.input.value.trim() }).catch(e => this.notice(String(e), false)); this.input.value = ''; this.close(); } };
    this.root.append(this.input);
    button('Остановить речь и движения', () => { commands.motion('stop'); commands.seat('stand'); return commands.post('/api/assistant', {op:'task.stop'}); });
    for (const [id, name] of [['wave','Помахать'],['nod','Кивнуть'],['bow','Поклониться'],['dance','Танцевать']]) button(name, () => commands.motion(id));
    for (const value of [.5, 1, 1.5, 2]) button(`Размер ${value * 100}%`, () => commands.post('/api/avatar/resize', { scale: value }));
    button('Сесть на окно', () => commands.seat('window'));
    button('Сесть у панели задач', () => commands.seat('taskbar'));
    button('Встать', () => commands.seat('stand'));
    button('Вернуться домой', () => { this.close(); commands.home(); });
    button('Настройки персонажа', () => { this.close(); commands.settings(); });
    button('Закрыть меню · Esc', () => this.close());
    this.root.addEventListener('pointerdown', e => e.stopPropagation());
    this.badge.id = 'companion-status'; this.badge.hidden = true;
    document.body.append(this.root);
    (document.getElementById('captions') ?? document.body).append(this.badge);
    window.addEventListener('keydown', e => { if (e.key === 'Escape') this.close(); });
    window.addEventListener('pointerdown', e => { if (!this.root.contains(e.target as Node)) this.close(); });
    window.addEventListener('blur', () => this.close());
    const refresh=()=>{
      const lang=language();
      for(const [element,text] of this.labels)element.textContent=translate(text,lang);
      this.root.setAttribute('aria-label',translate('Управление персонажем',lang));
      this.input.placeholder=translate('Написать ассистенту…',lang);
    };
    window.addEventListener('jarvis-language',refresh);
    window.addEventListener('storage',refresh);
    refresh();
  }
  get open() { return !this.root.hidden; }
  show(x: number, y: number) {
    this.root.hidden = false; this.commands.menu(true);
    this.root.style.left = `${Math.max(8, Math.min(innerWidth - 288, x))}px`;
    this.root.style.top = `${Math.max(8, Math.min(innerHeight - this.root.offsetHeight - 8, y))}px`;
    this.root.querySelector('button')?.focus({ preventScroll: true });
  }
  close() { if (this.open) { this.root.hidden = true; this.commands.menu(false); } }
  notice(text: string, ok: boolean) { this.status = text.slice(0, 160); this.mood = ok ? 'happy' : 'sad'; this.until = performance.now() / 1000 + 6; }
  event(e: any) {
    if (e.kind === 'timers' && Array.isArray(e.items)) this.timers = e.items;
    if (e.kind === 'run') {
      if (e.status === 'running') { this.currentRun = e.id; this.status = 'Выполняю задачу…'; this.until = Infinity; this.mood = 'relaxed'; }
      else if (e.id === this.currentRun) { this.notice(e.status === 'cancelled' ? 'Задача остановлена' : e.error || 'Задача завершена', e.status === 'completed'); this.currentRun = ''; }
    }
    if (e.kind === 'tool_start') { this.status='Выполняю действие…'; this.until=performance.now()/1000+30; this.mood='relaxed'; }
    if (e.kind === 'tool_result') this.notice(e.outcome==='cancelled'?'Действие остановлено':e.outcome==='say'?'Проверьте ответ ассистента':e.outcome==='data'?'Данные получены':e.ok?'Действие выполнено':'Не удалось выполнить действие',e.ok);

    if (e.kind === 'error') this.notice(String(e.text ?? 'Ошибка'), false);
  }
  update(x: number, y: number, now: number, enabled: boolean) {
    const timer = this.timers.filter(t => Number.isFinite(t.due) && t.due > Date.now() / 1000).sort((a,b) => a.due - b.due)[0];
    const seconds = timer ? Math.max(0, Math.ceil(timer.due - Date.now() / 1000)) : 0;
    const text = this.until > now ? this.status : timer ? `⏱ ${String(Math.floor(seconds / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')} ${String(timer.label || '').slice(0,40)}` : '';
    if (this.until <= now) this.mood = '';
    this.badge.hidden = !enabled || !text;
    const shown=translate(text,language());
    if (this.badge.textContent !== shown) this.badge.textContent = shown;
  }
}
