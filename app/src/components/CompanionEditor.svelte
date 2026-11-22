<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '../lib/fileDialogs';
  import type { Persona } from '../lib/api';
  import { toastError } from '../lib/store.svelte';
  import Setting from './Setting.svelte';
  import Toggle from './Toggle.svelte';
  import Range from './Range.svelte';
  let { persona }: { persona: Persona } = $props();
  let frame = $state<HTMLIFrameElement>();
  let ready = $state(false), error = $state(''), compatibility = $state(''), runtime = $state('');
  let previewVersion = 0;
  const motions = [{id:'wave',name:'Приветствие',seconds:'4,9 с'}, {id:'nod',name:'Согласие',seconds:'0,8 с'},
    {id:'bow',name:'Поклон',seconds:'3,7 с'}, {id:'dance',name:'Танец',seconds:'повтор'}];
  const send = (data: any) => frame?.contentWindow?.postMessage(data,location.origin);
  async function model() {
    const version=++previewVersion;
    if (!ready || !persona.avatar?.model) return;
    try {
      const bytes = await invoke<ArrayBuffer>('avatar_model',{path:persona.avatar.model});
      if (version!==previewVersion) return;
      error=''; send({kind:'preview-model',bytes,options:JSON.parse(JSON.stringify({...persona.avatar,scale:1}))});
    } catch { error='Для предпросмотра нового файла сначала сохраните персонажа и откройте редактор снова.'; }
  }
  $effect(() => { if (ready && persona.avatar?.model) void model(); });
  let optionsVersion=0;
  async function previewOptions(options: any) {
    const version=++optionsVersion, accessoryBytes:Record<string,ArrayBuffer>={};
    for(const item of options.accessories??[]) if(item.file) {
      try { accessoryBytes[item.file]=await invoke<ArrayBuffer>('avatar_accessory',{path:item.file}); }
      catch { error='Для предпросмотра нового аксессуара сначала сохраните персонажа.'; }
    }
    if(version===optionsVersion) send({kind:'preview-options',options,accessoryBytes});
  }
  $effect(() => { if (ready) void previewOptions(JSON.parse(JSON.stringify({...persona.avatar,scale:1}))); });
  onMount(() => {
    void invoke<{renderer:string}>('avatar_runtime').then(r=>runtime=r?.renderer??'').catch(()=>{});
    const receive = (e:MessageEvent) => {
      if (e.source!==frame?.contentWindow || e.origin!==location.origin) return;
      if(e.data?.kind==='preview-ready') ready=true;
      if(e.data?.kind==='preview-compat') compatibility=String(e.data.text??'');
    };
    window.addEventListener('message',receive);
    return ()=>window.removeEventListener('message',receive);
  });
  async function accessory(builtin?: string) {
    if(!persona.avatar) return;
    try {
      const path = builtin ? null : await open({multiple:false,filters:[{name:'Аксессуар GLB',extensions:['glb']}]});
      if(!builtin && !path) return;
      persona.avatar.accessories ??= [];
      persona.avatar.accessories.push({id:`a-${Date.now()}`,name:builtin==='glasses'?'Очки':builtin==='headphones'?'Наушники':builtin==='halo'?'Нимб':'Свой аксессуар',
        bone:'head',builtin,file:path as string || undefined,position:[0,0,0],rotation:[0,0,0],scale:1,enabled:true});
    } catch(e) {toastError(e);}
  }
</script>

<div class="companion-editor">
  <div class="caps sub">{uiText("Студия движений")}</div>
  <p class="muted small">{uiText("Предпросмотр изолирован: голос, положение персонажа на рабочем столе и текущая задача не меняются.")}</p>
  <iframe bind:this={frame} src="avatar.html?preview=1" title={uiText("Предпросмотр персонажа и движений")}></iframe>
  {#if error}<p role="status" class="muted small">{uiText(error)}</p>{/if}
  <p class="dim small">{uiText(compatibility)}</p>
  <div class="motion-grid">
    {#each motions as m}
      <button class="btn" onclick={()=>send({kind:'preview-motion',animation:m.id})}>{m.name} · {m.seconds}</button>
    {/each}
    <button class="btn" onclick={()=>send({kind:'preview-motion',animation:'stop'})}>{uiText("Остановить")}</button>
    <button class="btn" onclick={()=>send({kind:'preview-seat',surface:'window'})}>{uiText("Посадка на край")}</button>
    <button class="btn" onclick={()=>send({kind:'preview-seat',surface:'taskbar'})}>{uiText("Сидя на панели")}</button>
  </div>
  {#each persona.animations ?? [] as animation}
    <Setting title={animation.name} hint={uiText("Роль заменяет стандартный жест. Выберите «По своей фразе», чтобы оставить стандартные жесты")}>
      <select bind:value={animation.role}><option value="">{uiText("По своей фразе")}</option>{#each motions as m}<option value={m.id}>{m.name}</option>{/each}</select>
      <button class="btn" onclick={async()=>{try {const bytes=await invoke<ArrayBuffer>('avatar_animation',{path:animation.file});send({kind:'preview-clip',bytes,loop:animation.loop});}catch{toastError('Сначала сохраните импортированную анимацию');}}}>{uiText("Попробовать")}</button>
    </Setting>
  {/each}

  <div class="caps sub">{uiText("Речь и поведение")}</div>
  <Setting title={uiText("Артикуляция")} hint={uiText("Авто: фонетическая разметка подготовленных записей, для новой потоковой речи — анализ звука без задержки. Результат зависит от форм рта в модели")}>
    <select value={persona.avatar?.lips ?? 'auto'} onchange={e=>persona.avatar && (persona.avatar.lips=e.currentTarget.value as 'auto'|'audio'|'off')}>
      <option value="auto">{uiText("Автоматически")}</option><option value="audio">{uiText("Только по звуку")}</option><option value="off">{uiText("Выключена")}</option>
    </select>
  </Setting>
  <Setting title={uiText("Синхронизация губ")} hint={uiText("Если губы опережают звук — увеличьте задержку. Учитывается также задержка звукового устройства")}>
    <Range value={Math.round((persona.avatar?.lip_delay??0)*1000)} min={-100} max={300} step={10} format={v=>`${v} мс`} onchange={v=>persona.avatar&&(persona.avatar.lip_delay=v/1000)} />
  </Setting>
  <Setting title={uiText("Реакции на задачи")} hint={uiText("Взгляд, выражение лица и мягкая поза во время слушания, размышления и ответа. Также показывает результат действия и отсчёт таймера. Жесты и ходьба имеют приоритет")}>
    <Toggle checked={persona.avatar?.reactions??true} onchange={v=>persona.avatar&&(persona.avatar.reactions=v)} />
  </Setting>
  <Setting title={uiText("Смотреть на курсор")} hint={uiText("Мягкое движение взгляда, когда персонаж стоит или сидит. Можно выключить для спокойного поведения")}>
    <Toggle checked={persona.avatar?.gaze??false} onchange={v=>persona.avatar&&(persona.avatar.gaze=v)} />
  </Setting>
  <p class="dim small">{uiText("Правый клик по персонажу открывает быстрое меню. В Windows Ctrl+Alt+M открывает его даже при включённых кликах насквозь. Посадка выполняется по команде, без самопроизвольных перемещений.")}</p>
  <button class="btn" onclick={()=>invoke('avatar_menu_open').catch(toastError)}>{uiText("Открыть меню персонажа на рабочем столе")}</button>
  {#if runtime && runtime!=='ready'}<p class="muted small">{uiText("Окно персонажа: ")}{uiText(runtime)}</p>{/if}

  <div class="caps sub">{uiText("Аксессуары")}</div>
  <p class="dim small">{uiText("Отдельные предметы прикрепляются к кости. Они не меняют костюм модели. Посадку под волосы и лицо можно подстроить здесь.")}</p>
  <div class="motion-grid">
    <button class="btn" onclick={()=>accessory('glasses')}>{uiText("+ Очки")}</button><button class="btn" onclick={()=>accessory('headphones')}>{uiText("+ Наушники")}</button>
    <button class="btn" onclick={()=>accessory('halo')}>{uiText("+ Нимб")}</button><button class="btn" onclick={()=>accessory()}>{uiText("+ Файл .glb")}</button>
  </div>
  {#each persona.avatar?.accessories??[] as item,i (item.id)}
    <div class="accessory">
      <Setting title={item.name} hint={uiText("Выключение сохраняет настройки предмета")}>
        <Toggle checked={item.enabled??true} onchange={v=>item.enabled=v} /><button class="btn" onclick={()=>persona.avatar?.accessories?.splice(i,1)}>{uiText("Убрать")}</button>
      </Setting>
      <Setting title={uiText("Крепление")} hint={uiText("Предмет следует за выбранной костью во время всех движений")}>
        <select bind:value={item.bone}><option value="head">{uiText("Голова")}</option><option value="chest">{uiText("Грудь")}</option><option value="leftHand">{uiText("Левая кисть")}</option><option value="rightHand">{uiText("Правая кисть")}</option></select>
      </Setting>
      <Setting title={uiText("Смещение, см · X / Y / Z")} hint={uiText("Вправо / вверх / вперёд относительно кости")}>
        <div class="vectors">{#each item.position as value,n}<input aria-label={uiText(`Смещение ${n+1}`)} type="number" min={-100} max={100} step={.5} value={Math.round(value*1000)/10} oninput={e=>item.position[n]=Number(e.currentTarget.value)/100} />{/each}</div>
      </Setting>
      <Setting title={uiText("Поворот · X / Y / Z")} hint={uiText("Градусы вокруг трёх осей кости")}>
        <div class="vectors">{#each item.rotation as value,n}<input aria-label={uiText(`Поворот ${n+1}`)} type="number" min={-180} max={180} step={5} bind:value={item.rotation[n]} />{/each}</div>
      </Setting>
      <Setting title={uiText("Масштаб предмета")} hint={uiText("Отдельно от общего размера персонажа")}><Range value={item.scale} min={.05} max={3} step={.05} format={v=>`${v.toFixed(2)}×`} onchange={v=>item.scale=v} /></Setting>
      <Setting title={uiText("Автор / лицензия")} hint={uiText("Укажите источник и условия для импортированного файла")} wide><input bind:value={item.credit} /></Setting>
    </div>
  {/each}
</div>
<style>
  iframe {width:100%;height:380px;display:block;border:1px solid var(--line-2);border-radius:16px;background:radial-gradient(ellipse at 50% 80%,#17313b,#080f17);margin:12px 0;}
  .motion-grid {display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;} .sub {margin-top:20px;} .small {font-size:12px;}
  .accessory {border:1px solid var(--line-2);border-radius:12px;padding:12px;margin-top:12px;}
  .vectors {display:flex;gap:6px;} .vectors input {width:75px;min-width:0;}
</style>
