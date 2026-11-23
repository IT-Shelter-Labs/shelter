// Связь окна с бэкендом (Rust) и через него — с ядром Джарвиса.
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type CoreState = {
  running: boolean;
  paused: boolean;
  stopping: boolean;
  pid: number | null;
  lastError: string;
  python: boolean;
  root: string;
};

export type CoreStatus = {
  version: string;
  listening: boolean;
  speaking: boolean;
  thinking: boolean;
  voice: string;
  clone_ready: boolean | null;
  persona_sample?: boolean;
  voice_status?: { phase: string; reason: string } | null;
  asr: string;
  wake_engine?: string;
  wake_ready?: boolean;
  persona?: { id?: string; name?: string; title?: string; address?: string; gender?: "m" | "f" };
  echo?: { speaker: string | null; error: string | null; frames: number } | null;
  llm: { enabled: boolean; model: string; provider: string };
  in_game: boolean;
  mic: string;
  wake_word: string;
  workers: Record<string, { state: string; error: string }>;
  confirming?: boolean;
  executing?: boolean;
  task?: string;
  queued?: number;
  recognizing?: boolean;
};

export type FeedEvent = { kind: string; time: number; text?: string; name?: string; arg?: string; ok?: boolean; label?: string; fast?: boolean; session_id?: string };

/** Персонаж: характер, обращение, голос и внешность (personas/<id>/persona.json). */
export type Persona = {
  wake_words?: string[];
  appearance?: string;
  appearances?: { id: string; name: string; model: string; preview?: string; credit?: string }[];
  id: string;
  name: string;
  title?: string;
  aliases?: string[];
  switch_hint?: string;
  address?: string;
  gender?: "m" | "f";
  system?: string;
  wake_reply?: string;
  switch_reply?: string;
  builtin?: boolean;
  voice?: { reference?: string; reference_text?: string; silero?: string; piper?: string; pitch?: number; about?: string; effect?: "" | "robot"; status?: string };
  avatar?: { type?: "hud" | "vrm"; model?: string; preview?: string; credit?: string; source?: string; scale?: number; motion?: number;
             accessories?: import('../avatar/accessories').Accessory[]; lips?: 'auto'|'audio'|'off'; lip_delay?: number; reactions?: boolean; gaze?: boolean;
             framing?: "portrait" | "full"; desktop_framing?: "full" | "waist" | "portrait";
             walk?: "natural" | "formal"; fps?: number; bpm?: number; subtitles?: boolean; idle_motion?: boolean };
  animations?: { id: string; name: string; file: string; phrases: string[]; loop?: boolean; role?: string }[];
};

export type AssistantRun = { id: string; session_id: string; question: string; status: string; result: string; error: string; created: number; updated: number };
export type AssistantSnapshot = {
  session_id: string; project_id: string;
  memory_total: number;
  indexed_memories?: number;
  context_diagnostic?: {model:string;connection:string;route:string;context_limit:number;
    input_tokens_estimate:number;actual_prompt_tokens?:number;output_tokens?:number;recent_messages:number;
    available_messages:number;shortened_exchanges:number;materials_shortened:boolean;share_context:boolean;
    sources:{id:string;title:string;kind:string;source:string;shortened:boolean}[]} | null;
  projects: { id: string; name: string; instructions: string }[];
  sessions: { id: string; title: string; updated: number }[];
  memories: { id: string; text: string; project_id: string; source: string; updated: number }[];
  messages: { id: number; role: string; content: string; created: number }[];
  runs: AssistantRun[];
  context: { id: string; title: string; content: string; source: string }[];
  documents: { id: string; title: string; source: string; updated: number }[];
};
export type RunDetail = AssistantRun & { steps: { id: number; name: string; argument: string; outcome: string; result: string }[] };

export type Step = { type: string; enabled?: boolean; note?: string; then?: Step[]; else?: Step[]; steps?: Step[]; condition?: Condition; [k: string]: any };
export type Condition = { type: string; [k: string]: any };
export type Trigger = { type: string; [k: string]: any };
export type Scenario = {
  format?: string; version?: number; id: string; name: string; category: string; enabled: boolean; description?: string;
  phrases: string[]; match: "word" | "whole"; keep_listening: boolean; triggers: Trigger[]; conditions: Condition[];
  confirm: string; steps: Step[]; timeout: number; on_error: "stop" | "continue"; cooldown: number; platforms: string[];
  origin?: string; created?: number; updated?: number; [k: string]: any;
};
export type Field = { key: string; label: string; kind: string; required?: boolean; default?: any; min?: number; max?: number;
  options?: [string, string][]; hint?: string; advanced?: boolean; show_if?: Record<string, any> };
export type ActionSpec = { label: string; group?: string; icon?: string; fields: Field[]; advanced?: boolean; capability?: string;
  platforms?: string[]; safe_retry?: boolean; irreversible?: boolean; container?: boolean; hint?: string; unavailable?: string };
export type RunStep = { path: string; label: string; status: string; detail: string; ms?: number };
export type ScenarioRun = { run: string; scenario: string; name: string; source: string; status: string; steps: RunStep[];
  warnings: string[]; error: string; started: number; finished: number };
export type ScenarioSnapshot = { items: Scenario[]; error: string; platform: string; version: number;
  actions: Record<string, ActionSpec>; conditions: Record<string, ActionSpec>; triggers: Record<string, ActionSpec>;
  recent: ScenarioRun[]; events: { time: number; name: string; why: string; result: string }[];
  backups: { id: string; reason: string; created: number; count: number }[];
  conflicts: { scenario: string; phrase: string; text: string }[] };
export type Explain = { phrase: string; route: string; title: string; detail: string; scenario: string | null; match: string;
  calls: { tool: string; arg: string; text: string }[]; alternatives: { scenario: string; name: string; phrase: string }[];
  warnings: string[]; ambiguous: boolean; plan?: PlanLine[] };
export type PlanLine = { depth: number; text: string; off?: boolean; note?: string; irreversible?: boolean; llm?: boolean; group?: boolean };
export type Plan = { steps: PlanLine[]; triggers: string[]; conditions: string[]; problems: string[]; needs: string[]; confirm: string; uses_llm: boolean };
export type Pack = { id: string; name: string; icon: string; about: string; installed: boolean;
  params: { key: string; label: string; default: string; hint?: string }[];
  requires: { app: string; label: string; optional?: boolean; found: boolean }[];
  items: { name: string; phrases: string[]; steps: string[] }[] };

export type Gpu = { name: string; vendor: string; vramGb: number; integrated: boolean };
export type Hardware = {
  os: string;
  cpu: string;
  cpuThreads: number;
  ramTotalGb: number;
  gpus: Gpu[];
  diskFreeGb: number | null;
  recommendation: { model: string; modelReason: string; voice: string; voiceReason: string };
};

export type SetupEvent = {
  component?: string;
  status?: "start" | "ok" | "error" | "finished";
  stage?: string;
  done?: number;
  total?: number;
  text?: string;
  message?: string;
  ok?: boolean;
};

export const api = {
  appInfo: () => invoke<{ version: string; root: string; onboarded: boolean; minimized: boolean; platform: string; contextRequested?: boolean }>("app_info"),
  coreState: () => invoke<CoreState>("core_state"),
  coreStart: () => invoke<CoreState>("core_start"),
  coreStop: () => invoke<CoreState>("core_stop"),
  coreRestart: () => invoke<void>("core_restart"),
  status: () => invoke<CoreStatus>("core_get", { path: "/api/status" }),
  devices: () => invoke<{ devices: { index: number; name: string; default: boolean }[]; current: number | null }>("core_get", { path: "/api/audio/devices" }),
  level: () => invoke<{ rms: number; db: number }>("core_get", { path: "/api/audio/level" }),
  ask: (text: string, session_id?: string) => invoke("core_post", { path: "/api/ask", body: { text, session_id } }),
  assistant: (q = "") => invoke<AssistantSnapshot>("core_get", { path: "/api/assistant?q=" + encodeURIComponent(q) }),
  assistantAction: <T = { ok: boolean }>(body: Record<string, unknown>) => invoke<T>("core_post", { path: "/api/assistant", body }),
  say: (text: string) => invoke("core_post", { path: "/api/say", body: { text } }),
  speaker: (action: "enroll" | "test" | "forget" | "status", seconds = 0) =>
    invoke<{ available?: boolean; enrolled?: boolean; seconds?: number; consistency?: number; score?: number; owner?: boolean; threshold?: number }>(
      "core_post", { path: `/api/speaker/${action}`, body: { seconds } }),
  listen: () =>invoke("core_post", { path: "/api/listen", body: {} }),
  setHotkey: (combo: string) => invoke<void>("set_hotkey", { combo }),
  voiceRecord:(seconds: number, target = "") => invoke<{ path: string; text: string; seconds: number }>("core_post", { path: "/api/voice/record", body: { seconds, target } }),
  voiceImport: (path: string, target = "") => invoke<{ path: string; text: string; seconds: number }>("core_post", { path: "/api/voice/import", body: { path, target } }),
  personas: () => invoke<{ active: string; personas: Persona[] }>("core_get", { path: "/api/personas" }),
  persona: (id: string) => invoke<{ ok: boolean; active: string }>("core_post", { path: "/api/persona", body: { id } }),
  personaSave: (persona: Partial<Persona>) => invoke<{ ok: boolean; persona: Persona }>("core_post", { path: "/api/persona/save", body: { persona } }),
  personaDelete: (id: string) => invoke<{ ok: boolean }>("core_post", { path: "/api/persona/delete", body: { id } }),
  avatarMotion: (animation: string, bpm?: number, beat = false) => invoke<{ ok: boolean; text: string }>("core_post", {
    path: "/api/avatar/motion", body: { animation, bpm, beat } }),
  avatarOptions: (options: Record<string, boolean>) => invoke("core_post", { path: "/api/avatar/options", body: { options } }),
  settings: () => invoke<{ defaults: Record<string, any>; user: Record<string, any> }>("settings_get"),
  saveSettings: (user: Record<string, any>) => invoke<void>("settings_save", { user }),
  hardware: () => invoke<Hardware>("hardware_info"),
  setupCheck: () => invoke<Record<string, any>>("setup_check"),
  setupInstall: (components: string[]) => invoke<void>("setup_install", { components }),
  reloadSettings: () => invoke<{ applied: string[] }>("core_post", { path: "/api/settings/reload", body: {} }),
  cancel: () => invoke<{ ok: boolean; stopped: string[] }>("core_post", { path: "/api/cancel", body: {} }),
  media: () => invoke<{ playing: { app: string; source: string; title: string; artist: string; playing: boolean; next_enabled?: boolean; previous_enabled?: boolean } | null }>("core_post", { path: "/api/media", body: {} }),
  mediaControl: (action: string, source: string) => invoke<{ok: boolean}>("core_post", {path:"/api/media",body:{action,source}}),
  timers: () => invoke<{ items: { id?: string; label: string; due: number; repeat?: string; kind?: string }[] }>("core_get", { path: "/api/avatar/timers" }),
  scenarios: () => invoke<ScenarioSnapshot>("core_get", { path: "/api/scenarios" }),
  scenarioOp: <T = any>(body: Record<string, unknown>) => invoke<T>("core_post", { path: "/api/scenarios", body }),
  open: (what: "logs" | "folder" | "config") => invoke<void>("open_in_system", { what }),
};

export function on<T>(event: string, handler: (payload: T) => void): Promise<UnlistenFn> {
  return listen<T>(event, (e) => handler(e.payload));
}

export function errorText(e: unknown): string {
  return typeof e === "string" ? e : e instanceof Error ? e.message : JSON.stringify(e);
}
