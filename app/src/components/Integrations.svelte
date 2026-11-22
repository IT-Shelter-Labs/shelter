<script lang="ts">
  import { t as uiText } from "../lib/i18n.svelte";

  import Setting from "./Setting.svelte";
  import Toggle from "./Toggle.svelte";
  import { app, get, set, saveNow, toast, toastError } from "../lib/store.svelte";
  import { api } from "../lib/api";
  type Server = {id:string;enabled:boolean;transport:string;command:string;args:string[];url:string;token_env:string;tools:string[];trusted_tools:string[]};
  let id=$state(""); let command=$state(""); let args=$state("[]"); let url=$state(""); let tokenEnv=$state(""); let transport=$state("stdio");
  let discovered=$state<Record<string, {name:string;description:string}[]>>({});
  let probing=$state("");
  const servers=$derived(get<Server[]>("integrations.servers", []) ?? []);
  function change(server:Server, patch:Partial<Server>) {set("integrations.servers", servers.map(s => s.id===server.id ? {...s,...patch}:s));}
  async function add() {
    try {
      if(!/^[a-zA-Z0-9_-]{1,40}$/.test(id) || servers.some(s=>s.id===id)) throw "Задайте уникальное имя латиницей, до 40 знаков";
      const parsed=JSON.parse(args);
      if(!Array.isArray(parsed)||!parsed.every(a=>typeof a==="string")) throw "Аргументы — JSON-список строк";
      if(transport==="stdio"&&!command.trim() || transport==="http"&&!url.trim()) throw "Укажите программу или адрес сервера";
      set("integrations.servers", [...servers,{id,enabled:true,transport,command:command.trim(),args:parsed,url:url.trim(),token_env:tokenEnv.trim(),tools:[],trusted_tools:[]}]);
      set("integrations.enabled", true);
      const tools=get<string[]>("llm.tools",[]) ?? []; if(!tools.includes("mcp")) set("llm.tools",[...tools,"mcp"]);
      await saveNow(); id="";command="";url="";args="[]";
      toast("Подключение сохранено. Примените настройки перед проверкой.","success");
    }catch(e){toastError(e);}
  }
  async function probe(server:Server){
    probing=server.id;
    try{const r=await api.assistantAction<{tools:{name:string;description:string}[]}>({op:"mcp.probe",id:server.id});discovered={...discovered,[server.id]:r.tools};}
    catch(e){toastError(e);}finally{probing="";}
  }
</script>

<div class="card">
  <div class="caps">{uiText("Подключения MCP")}</div>
  <Setting title={uiText("Внешние инструменты")} hint={uiText("Подключайте свои сервисы и приложения. Доступны локальные программы MCP и серверы Streamable HTTP. Каждый инструмент включается отдельно.")}>
    <Toggle checked={get("integrations.enabled",false)} onchange={v=>set("integrations.enabled",v)}/>
  </Setting>
  {#each servers as server}
    <section class="server">
      <Setting title={uiText(server.id)} hint={uiText(server.transport==="http"?server.url:server.command)}><Toggle checked={server.enabled} onchange={v=>change(server,{enabled:v})}/></Setting>
      <div class="buttons"><button class="btn" disabled={!!probing || !app.status || app.dirty || !server.enabled} onclick={()=>probe(server)}>{uiText(probing===server.id?"Подключаюсь…":"Проверить и выбрать инструменты")}</button><button class="btn ghost" onclick={()=>set("integrations.servers",servers.filter(s=>s.id!==server.id))}>{uiText("Удалить подключение")}</button></div>
      {#if server.tools.length}<p class="dim">{uiText("Разрешены: ")}{uiText(server.tools.join(", "))}</p>{/if}
      {#each discovered[server.id] ?? [] as tool}
        <Setting title={tool.name} hint={uiText(tool.description)}>
          <Toggle checked={server.tools.includes(tool.name)} onchange={v=>change(server,{tools:v?[...server.tools,tool.name]:server.tools.filter(n=>n!==tool.name)})}/>
        </Setting>
        {#if server.tools.includes(tool.name)}<Setting title={uiText("Выполнять без вопроса")} hint={uiText("Включайте только для знакомого инструмента, которому доверяете. По умолчанию Джарвис спрашивает разрешение.")}><Toggle checked={server.trusted_tools.includes(tool.name)} onchange={v=>change(server,{trusted_tools:v?[...server.trusted_tools,tool.name]:server.trusted_tools.filter(n=>n!==tool.name)})}/></Setting>{/if}
      {/each}
    </section>
  {/each}
  <details>
    <summary>{uiText("Добавить подключение")}</summary>
    <div class="form">
      <label>{uiText("Имя подключения")}<input placeholder={uiText("Например, notes")} bind:value={id}/></label>
      <label>{uiText("Способ подключения")}<select bind:value={transport}><option value="stdio">{uiText("Программа на компьютере (stdio)")}</option><option value="http">{uiText("Сервер (Streamable HTTP)")}</option></select></label>
      {#if transport==="stdio"}
        <label>{uiText("Исполняемый файл")}<input placeholder={uiText("Полный путь к программе MCP")} bind:value={command}/></label>
        <label>{uiText("Аргументы, списком")}<textarea rows="2" placeholder={uiText('["C:/tools/server.py"]')} bind:value={args}></textarea></label>
      {:else}
        <label>{uiText("Адрес")}<input placeholder="https://example.com/mcp" bind:value={url}/></label>
        <label>{uiText("Имя переменной окружения с ключом")}<input placeholder={uiText("Например, NOTES_TOKEN")} bind:value={tokenEnv}/></label>
      {/if}
      <p class="dim">{uiText("Проверка запустит указанную программу или подключится к серверу. Ключи задаются через переменные окружения.")}</p>
      <button class="btn primary" onclick={add}>{uiText("Сохранить подключение")}</button>
    </div>
  </details>
</div>
<style>
  .card{margin-top:16px}.server{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}.buttons{display:flex;gap:8px;flex-wrap:wrap}summary{cursor:pointer;color:var(--accent-2);padding:12px 0}.form{display:flex;flex-direction:column;gap:12px}.form label{display:flex;flex-direction:column;gap:6px;font-size:13px}.form input,.form textarea{width:100%}
</style>
