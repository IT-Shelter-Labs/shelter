// Окно персонажа: VRM-модель вместо HUD-реактора.
// Ядро присылает состояния (слушаю/думаю/говорю) и громкость речи для губ.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Travel, destination, type Rect, type Point } from "./desktop";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip, VRMLookAtQuaternionProxy, type VRMAnimation } from "@pixiv/three-vrm-animation";
import { RigMotion, type Gesture } from "./motion";
import { Locomotion } from "./locomotion";
import { SpringScale } from "./physics";
import { validateGlb } from "./assets";
import { Lips, vowels } from "./lips";
import { Seating, seatPoint, type Surface } from "./seating";
import { Accessories, type Accessory } from "./accessories";
import { Controls } from "./controls";
import { StateLayer, type Mood } from "./state";
import { CaptionLayout } from "./captions";
import { language, saveLanguage } from '../lib/language';
import { translate } from '../lib/i18n';

type State = "show" | "listening" | "thinking" | "speaking" | "idle" | "hide" | "confirm" | "error";
const REST_AFTER = 45;          // секунд без дела — персонаж «отдыхает»: расслабленно осматривается
const ERROR_HOLD = 3;           // столько секунд держится огорчение после ошибки

const params = new URLSearchParams(location.search);
const PREVIEW = params.has("preview");
const TAURI = "__TAURI_INTERNALS__" in window && !PREVIEW;
if (PREVIEW) document.body.style.background = "radial-gradient(ellipse at 50% 80%, #17313b, #080f17)";
const canvas = document.getElementById("stage") as HTMLCanvasElement;
const bubble = document.getElementById("say") as HTMLDivElement;
const errorBox = document.getElementById("err") as HTMLDivElement;
const captions = new CaptionLayout(document.getElementById("captions")!);

const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(0, innerWidth, innerHeight, 0, 0.1, 5000);
const actor = new THREE.Group();
scene.add(actor);
const gaze = new THREE.Object3D();
const gazeTarget = new THREE.Vector3();
const seatHip = new THREE.Vector3();
scene.add(gaze);
const travel = new Travel({ x: innerWidth / 2, y: innerHeight - 16 });
let screens: Rect[] = [{ x: 0, y: 0, width: innerWidth, height: innerHeight }];
let placed = false;
let dragging = false;
let dragOffset: Point = { x: 0, y: 0 };
let hover = false;
let pointerPoint = {x:innerWidth/2,y:innerHeight/2};
let pendingPlace: any = null;
let moveId = "";
let actorHeight = 350, actorWidth = 180;
// Освещение под MToon (аниме-шейдер VRM): светотень и «цвет тени» рисует сам
// материал, поэтому нужен один ключевой свет яркостью π (так считают физические
// единицы three.js) и совсем немного заполняющего. Сильный AmbientLight заливал
// модель ровным белым — кожа бледнела, одежда «светилась».
// Подобрано по снимкам моделей: 2.0 + 0.2 — кожа тёплая, белое не «горит», тени объёмные.
const LIGHT = { key: Number(params.get("key") ?? 2.2), fill: Number(params.get("fill") ?? 0.3) };
const fill = new THREE.HemisphereLight(0xfff6ee, 0xe0cfc4, LIGHT.fill);   // тёплый: кожа без серости
scene.add(fill);
const sun = new THREE.DirectionalLight(0xffffff, LIGHT.key);
sun.position.set(0.5, 1.4, 2.0);          // спереди-сверху-справа: мягкая тень под чёлкой и подбородком
scene.add(sun);

let vrm: VRM | null = null;
let modelPath = "";
let state: State = "listening";
let headY = 1.4;
let modelHeight = 1.6;
let waistY = 0.8;
let cropY = 0;
let modelWidth = 0.6;
let modelCenter = new THREE.Vector3(0, 0.8, 0);
const cameraTarget = new THREE.Vector3();
let rig: RigMotion | null = null;
let stateLayer: StateLayer | null = null;
let stateSince = performance.now() / 1000;
let locomotion: Locomotion | null = null;
let springScale: SpringScale | null = null;
let seating: Seating | null = null;
let accessories: Accessories | null = null;
let accessoryItems: Accessory[] = [];
let previewAccessoryBytes: Record<string,ArrayBuffer> = {};
let surfacePolling = false;
let seatTargetX = 0;
const lips = new Lips();
let bundledMotions: Promise<VRMAnimation[]> | null = null;

function loadBundledMotions() {
  return bundledMotions ??= (async () => {
    const read = async (name: string) => {
      const response = await fetch(new URL(`./animations/${name}.vrma`, location.href));
      if (!response.ok) throw new Error("Не удалось загрузить встроенные движения.");
      const bytes = await response.arrayBuffer();
      validateGlb(bytes, "VRMC_vrm_animation");
      const loader = new GLTFLoader();
      loader.register(parser => new VRMAnimationLoaderPlugin(parser));
      return (await loader.parseAsync(bytes, "")).userData.vrmAnimations as VRMAnimation[];
    };
    return (await Promise.all([read("locomotion"), read("gestures"), read("seated")])).flat();
  })().catch(error => { bundledMotions = null; throw error; });
}
let mixer: THREE.AnimationMixer | null = null;
let motionVersion = 0;
let loadVersion = 0;
let loading = false;
let options = { scale: !TAURI && params.get("scale") ? Number(params.get("scale")) : 1, motion: 1, walk: params.get("walk") === "formal" ? "formal" : "natural", fps: 30, subtitles: true, reactions: true, gaze: false, lips: "auto", lip_delay: 0, desktop_framing: params.get("framing") ?? "full", idle_motion: true };
type MotionRequest = { preserve_seat?: boolean; animation: string; file?: string; loop?: boolean; bpm?: number; motion_id?: string };
let pendingMotion: MotionRequest | null = null;
let visible = true;
let lastFrame = 0;

// --------------------------------------------------------------- губы
// Ядро присылает формы рта для воспроизводимого PCM и задержку устройства.
const controls = new Controls({
  post: (path, body) => TAURI ? invoke("core_post", { path, body }) : Promise.resolve(),
  motion: id => { if (TAURI) void invoke("core_post", { path: "/api/avatar/motion", body: { animation: id } }).catch(e => controls.notice(String(e), false)); else void playMotion({animation:id}); },
  seat: kind => { if(TAURI) void invoke('core_post',{path:'/api/avatar/motion',body:{animation:kind==='stand'?'stand':'sit-'+kind}}).catch(e=>controls.notice(String(e),false)); else void requestSeat(kind); },
  home: () => { stand(); place({position:"home"}); },
  settings: () => { if (TAURI) void invoke("avatar_settings"); },
  menu: active => { if (TAURI) void invoke("avatar_menu_state", {active}); },
});
if (PREVIEW) controls.badge.hidden = true;

function stand() {
  if (seating?.seated && TAURI) void invoke('core_post',{path:'/api/avatar/seated',body:{seated:false}}).catch(()=>{});
  seating?.stand(performance.now()/1000);
}
async function requestSeat(kind: string) {
  const now = performance.now()/1000;
  if (!seating) return;
  const requestedSeating=seating;
  if (kind === 'stand') { stand(); place({position:PREVIEW?'bottom':'bottom-right'}); return; }
  const data = TAURI ? await invoke<{surfaces:Surface[]}>('avatar_surfaces') : {surfaces:[{id:'preview',kind:kind==='taskbar'?'taskbar':'window',x:0,y:innerHeight*.62,width:innerWidth,height:100} as Surface]};
  if (requestedSeating!==seating) return;
  const candidates = data.surfaces.filter(r => r.kind === kind).map(surface => ({surface,point:seatPoint(surface,screens,actorHeight,travel.point.x)})).filter(x => x.point);
  candidates.sort((a,b) => Math.hypot(a.point!.x-travel.point.x,a.point!.y-travel.point.y)-Math.hypot(b.point!.x-travel.point.x,b.point!.y-travel.point.y));
  if (!candidates.length) { if(TAURI) void invoke('core_post',{path:'/api/avatar/seated',body:{seated:false}}); controls.notice('Нет свободного края с достаточным местом. Передвиньте или уменьшите окно.',false); return; }
  const {surface,point} = candidates[0];
  ++motionVersion; mixer?.stopAllAction(); mixer=null; rig?.start('stop',now);
  travel.drag(point!); seatTargetX=point!.x; seating.sit(surface,now);
}

setInterval(async () => {
  if (!TAURI || !visible || !seating?.surface || surfacePolling) return;
  surfacePolling=true;
  try {
    const id=seating.surface.id;
    const {surfaces} = await invoke<{surfaces:Surface[]}>('avatar_surfaces');
    if (!seating?.surface || seating.surface.id!==id) return;
    const old = seating.surface;
    const surface=surfaces.find(r => r.id===old?.id);
    const point=surface ? seatPoint(surface,screens,actorHeight,seatTargetX+(surface.x-old!.x)) : null;
    if (!point) { stand(); place({position:'bottom-right'}); }
    else { seating.surface=surface!; seatTargetX=point.x; travel.drag(point); }
  } catch(e) { controls.notice(String(e),false); } finally { surfacePolling=false; }
}, 350);

// --------------------------------------------------------------- модель

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  // Окно — на весь рабочий стол (все мониторы), а персонаж маленький: на огромном
  // холсте повышенная плотность пикселей только нагружает видеокарту в играх.
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, w * h > 4e6 ? 1 : 2));
  renderer.setSize(w, h, false);
  camera.left = 0; camera.right = w; camera.top = h; camera.bottom = 0;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

function frame(dt = 1) {
  const now = performance.now() / 1000;
  const wasMoving = travel.moving;
  travel.update(now);
  if (wasMoving && !travel.moving) saveAnchor();
  const cut = options.desktop_framing === "portrait" ? Math.max(waistY, headY - modelHeight * .15) : options.desktop_framing === "waist" ? waistY : 0;
  cropY = dt >= 1 ? cut : cropY + (cut - cropY) * (1 - Math.exp(-Math.max(0, dt) * 9));
  const visibleHeight = Math.max(modelHeight * .2, modelHeight - cropY);
  const targetScale = Math.min(350 / visibleHeight, 400 / modelWidth) * options.scale;
  const factor = dt >= 1 ? targetScale : actor.scale.x + (targetScale - actor.scale.x) * (1 - Math.exp(-Math.max(0, dt) * 9));
  actorHeight = visibleHeight * factor; actorWidth = modelWidth * factor;
  actor.scale.setScalar(factor);
  springScale?.apply(factor);
  actor.position.set(travel.point.x, innerHeight - travel.point.y - cropY * factor, 0);
  camera.position.set(0, 0, 2000);
  camera.lookAt(0, 0, 0);
  const yaw = locomotion?.yaw ?? 0;
  const eyeHeight = Math.max(actorHeight * .4, Math.min(actorHeight, (headY - cropY) * factor));
  gazeTarget.set(travel.point.x + Math.sin(yaw) * 1000, innerHeight - travel.point.y + eyeHeight, Math.cos(yaw) * 1000);
  // Взгляд по состоянию: думает — вверх и в сторону, огорчён — вниз, отдыхает — осматривается.
  if (stateLayer && options.reactions && !travel.moving &&
    (options.idle_motion || !["idle", "show", "hide"].includes(state))) {
    const look = stateLayer.gaze(performance.now() / 1000);
    gazeTarget.x += look.x * actorHeight;
    gazeTarget.y += look.y * actorHeight;
  }
  if (options.gaze && !travel.moving && !dragging) {
    gazeTarget.x = travel.point.x + Math.max(-actorHeight*.65, Math.min(actorHeight*.65,pointerPoint.x-travel.point.x));
    gazeTarget.y = innerHeight-travel.point.y+eyeHeight + Math.max(-actorHeight*.25,Math.min(actorHeight*.25,(travel.point.y-eyeHeight)-pointerPoint.y));
  }
  gaze.position.lerp(gazeTarget, dt >= 1 ? 1 : 1 - Math.exp(-Math.max(0, dt) * 9));
  captions.place(travel.point.x, travel.point.y-actorHeight);
  if (!TAURI) canvas.dataset.actor = JSON.stringify({ ...travel.point, scale: factor, yaw, speed: travel.speed });
}

function saveAnchor() {
  if (TAURI) void invoke("avatar_anchor", travel.point).catch(() => {});
}

function place(event: any) {
  if (!vrm) { pendingPlace = event; return; }
  if (Array.isArray(event.screens) && event.screens.length) screens = event.screens;
  const rect = event.rect ?? screens.find(r => travel.point.x >= r.x && travel.point.x <= r.x + r.width && travel.point.y >= r.y && travel.point.y <= r.y + r.height) ?? screens[0];
  stand();
  mixer?.stopAllAction(); mixer = null;
  ++motionVersion;
  rig?.start("stop", performance.now() / 1000);
  locomotion?.begin();
  moveId = event.motion_id ?? "";
  // The measured stride scales with the character, including short/small rigs.
  const scale = actor.scale.x;
  travel.start(destination(rect, event.position ?? "center", actorWidth, actorHeight), performance.now() / 1000,
    locomotion ? locomotion.stride * scale / (4 / 3) : 180);
  placed = true;
}

/** Только для разработки (?portrait=<адрес>): портрет персонажа по пояс для
 *  карточки в настройках — тем же светом, что и на рабочем столе. */
async function renderPortrait(saveUrl: string) {
  if (!vrm) return;
  visible = false;                                   // главный цикл больше не рисует поверх
  actor.position.set(0, 0, 0); actor.scale.setScalar(1); actor.rotation.set(0, 0, 0);
  vrm.expressionManager?.setValue("blink", 0);
  vrm.update(0);
  actor.updateMatrixWorld(true);
  const head = vrm.humanoid.getNormalizedBoneNode("head")!.getWorldPosition(new THREE.Vector3());
  const cam = new THREE.PerspectiveCamera(24, innerWidth / innerHeight, 0.05, 50);
  const span = Math.max(0.5, modelHeight * 0.56);    // в кадре — голова (с ушками/причёской) и корпус до пояса
  const centerY = head.y - span * 0.17;
  cam.position.set(0, centerY + span * 0.05, span * 2.35);   // 24° по вертикали: span в кадре
  cam.lookAt(0, centerY, 0);
  renderer.setScissorTest(false);
  renderer.setPixelRatio(1);
  renderer.setSize(innerWidth, innerHeight, false);
  renderer.render(scene, cam);
  const png = canvas.toDataURL("image/png");          // сразу после render — буфер ещё цел
  await fetch(saveUrl, { method: "POST", body: png });
  canvas.dataset.portrait = "saved";
}

async function load(path: string) {
  if (!path || path === modelPath) return;
  modelPath = path;
  const version = ++loadVersion;
  loading = true;
  canvas.dataset.modelStatus = "loading";
  ++motionVersion;
  errorBox.textContent = "";
  try {
    const bytes = TAURI ? await invoke<ArrayBuffer>("avatar_model", { path })
                        : await (await fetch(path)).arrayBuffer();      // разработка в обычном браузере
    validateGlb(bytes, "VRMC_vrm");
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.parseAsync(bytes, "");
    const next = gltf.userData.vrm as VRM;
    if (!next?.humanoid) throw new Error("У модели нет гуманоидного скелета.");
    if (version !== loadVersion) { VRMUtils.deepDispose(next.scene); return; }
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.rotateVRM0(next);                    // старые VRM 0.x смотрят в другую сторону
    // Чёткие текстуры под углом (ткань, волосы): анизотропная фильтрация.
    const anisotropy = renderer.capabilities.getMaxAnisotropy();
    next.scene.traverse((o: any) => {
      o.frustumCulled = false;
      for (const material of [o.material].flat().filter(Boolean)) {
        for (const key of ["map", "shadeMultiplyTexture", "normalMap"]) {
          if (material[key]?.isTexture) { material[key].anisotropy = anisotropy; material[key].needsUpdate = true; }
        }
      }
    });
    const motions = await loadBundledMotions();
    if (version !== loadVersion) { VRMUtils.deepDispose(next.scene); return; }
    mixer?.stopAllAction(); mixer = null;
    accessories?.clear(); accessories=null; seating?.dispose(); seating=null;
    locomotion?.dispose(); locomotion = null;
    if (vrm) { actor.remove(vrm.scene); VRMUtils.deepDispose(vrm.scene); }
    vrm = next;
    springScale = new SpringScale(vrm.springBoneManager?.joints ?? []);
    actor.position.set(0, 0, 0);
    actor.scale.setScalar(1);
    actor.rotation.set(0, 0, 0);
    actor.add(vrm.scene);
    rig = new RigMotion(vrm.humanoid, { wave: motions[4].duration, nod: motions[5].duration, bow: motions[6].duration });
    stateLayer = new StateLayer(vrm.humanoid);
    rig.apply(0);
    if (vrm.lookAt) {
      const proxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
      proxy.name = "lookAtQuaternionProxy";
      vrm.scene.add(proxy);
    }
    vrm.update(0);
    const head = vrm.humanoid?.getNormalizedBoneNode("head");
    headY = head ? head.getWorldPosition(new THREE.Vector3()).y : 1.4;
    vrm.scene.updateWorldMatrix(true, true);
    const bounds = new THREE.Box3().setFromObject(vrm.scene);
    modelHeight = Math.max(0.3, bounds.max.y - bounds.min.y);
    headY = Math.max(.1, headY - bounds.min.y);
    modelWidth = Math.max(0.1, bounds.max.x - bounds.min.x);
    bounds.getCenter(modelCenter);
    const pivot = vrm.humanoid.getNormalizedBoneNode("hips")!.getWorldPosition(new THREE.Vector3());
    waistY = Math.max(modelHeight * .25, Math.min(modelHeight * .76, pivot.y - bounds.min.y));
    vrm.scene.position.add(new THREE.Vector3(-pivot.x, -bounds.min.y, -pivot.z));
    locomotion = new Locomotion(vrm, motions.slice(0,7));
    seating = new Seating(vrm, motions.slice(7));
    accessories = new Accessories(vrm, async path => TAURI ? invoke<ArrayBuffer>('avatar_accessory',{path}) : previewAccessoryBytes[path] ?? (await fetch(path)).arrayBuffer());
    void accessories.set(accessoryItems).catch(e => controls.notice(String(e),false));
    if (vrm.lookAt) vrm.lookAt.target = gaze;
    frame();
    if (!placed) { travel.drag(destination(screens[0], PREVIEW || params.has("center") ? "bottom" : "bottom-right", actorWidth, actorHeight)); placed = true; frame(); }
    // Разработка: ?feet=<y> — ступни ниже окна, в кадре крупно голова и корпус (осмотр мимики и позы).
    if (!TAURI && params.get("feet")) { travel.drag({ x: innerWidth / 2, y: Number(params.get("feet")) }); frame(); }
    if (pendingPlace) { place(pendingPlace); pendingPlace = null; }
    actor.updateMatrixWorld(true);
    vrm.springBoneManager?.reset();
    loading = false;
    canvas.dataset.modelStatus = "ready";
    canvas.setAttribute('aria-label', '3D-персонаж загружен');
    if (TAURI) void invoke('avatar_report',{state:'ready'});
    if (!TAURI && params.get("portrait")) void renderPortrait(params.get("portrait")!);
    if (PREVIEW) parent.postMessage({kind:'preview-compat',text:
      `Кости пальцев: ${vrm.humanoid.getNormalizedBoneNode('rightIndexProximal')?'есть':'нет'}. Формы рта: ${vowels.filter(v=>vrm?.expressionManager?.getExpression(v)).length}/5.`},location.origin);
    if (!TAURI) {
      const previewGesture = params.get("motion");
      if (previewGesture && ["wave", "nod", "bow", "dance"].includes(previewGesture)) {
        rig.start(previewGesture as Gesture, performance.now() / 1000);
      }
      if (params.get("travel")) {
        const left = params.get("travel") === "left";
        travel.drag(destination(screens[0], left ? "bottom-right" : "bottom-left", actorWidth, actorHeight));
        place({ position: left ? "bottom-left" : "bottom-right" });
      }
    }
    if (pendingMotion) { const request = pendingMotion; pendingMotion = null; void playMotion(request); }
  } catch (error) {
    if (version !== loadVersion) return;
    modelPath = "";
    loading = false;
    canvas.dataset.modelStatus = "error";
    canvas.setAttribute('aria-label','Не удалось загрузить персонажа: '+String(error));
    if (TAURI) void invoke('avatar_report',{state:String(error)});
    errorBox.textContent = "Модель персонажа не загрузилась: " + String(error);
  }
}

function finishMotion(event: MotionRequest) {
  if (TAURI && event.motion_id) void invoke("core_post", { path: "/api/avatar/finished", body: { motion_id: event.motion_id } }).catch(() => {});
}

async function playMotion(event: MotionRequest) {
  if (!vrm || !rig || loading || modelPath === "") { pendingMotion = event; return; }
  const version = ++motionVersion;
  mixer?.stopAllAction(); mixer = null;
  rig.start("stop", performance.now() / 1000);
  errorBox.textContent = "";
  if (!event.file) {
    const gesture = event.animation as Gesture;
    if (gesture === "stop") {
      if(!event.preserve_seat) stand();
      travel.drag(travel.point); saveAnchor();
      if (moveId) { finishMotion({ animation: "stop", motion_id: moveId }); moveId = ""; }
    }
    if (gesture === "dance") stand();
    if (["wave", "nod", "bow", "dance", "stop"].includes(gesture)) rig.start(gesture, performance.now() / 1000, event.bpm);
    frame(0);
    return;
  }
  if(event.animation!=="wave" && event.animation!=="nod") stand();
  const target = vrm;
  try {
    const bytes = TAURI ? await invoke<ArrayBuffer>("avatar_animation", { path: event.file }) :
      await (await fetch(event.file)).arrayBuffer();
    validateGlb(bytes, "VRMC_vrm_animation");
    const loader = new GLTFLoader();
    loader.register(parser => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.parseAsync(bytes, "");
    if (version !== motionVersion || target !== vrm) return;
    const animation: VRMAnimation | undefined = gltf.userData.vrmAnimations?.[0];
    if (!animation || !Number.isFinite(animation.duration) || animation.duration <= 0 || animation.duration > 600)
      throw new Error("Анимация пуста или длиннее 10 минут.");
    mixer = new THREE.AnimationMixer(target.scene);
    const action = mixer.clipAction(createVRMAnimationClip(animation, target));
    action.setLoop(event.loop ? THREE.LoopRepeat : THREE.LoopOnce, event.loop ? Infinity : 1);
    action.clampWhenFinished = true;
    action.fadeIn(0.2).play();
    mixer.addEventListener("finished", () => {
      if (version === motionVersion) { mixer?.stopAllAction(); mixer = null; frame(0); finishMotion(event); }
    });
    frame(0);
  } catch (error) {
    if (version === motionVersion) {
      errorBox.textContent = "Анимация не загрузилась: " + String(error);
      finishMotion(event);
    }
  }
}

// --------------------------------------------------------------- жизнь

let nextBlink = 2, blinkPhase = -1;
let expression: Record<string, number> = {};

function setExpression(target: Record<string, number>, dt: number) {
  const names = ["happy", "relaxed", "surprised", "sad", "angry"];
  for (const name of names) {
    const current = expression[name] ?? 0;
    const want = target[name] ?? 0;
    expression[name] = current + (want - current) * Math.min(1, dt * 4);
    vrm?.expressionManager?.setValue(name, expression[name]);
  }
}

function tick(timestamp: number) {
  requestAnimationFrame(tick);
  if (!visible || document.hidden || timestamp - lastFrame < 1000 / options.fps - 1) return;
  const resumed = timestamp - lastFrame > 500;
  const motionDelta = Math.min((timestamp - lastFrame) / 1000, 1);
  const dt = Math.min(motionDelta, 0.1);
  lastFrame = timestamp;
  const t = timestamp / 1000;
  const now = performance.now() / 1000;
  if (!vrm) { renderer.render(scene, camera); return; }
  const em = vrm.expressionManager;

  // Моргание: раз в 2–5 с, 0.15 с.
  if (blinkPhase < 0 && t > nextBlink) blinkPhase = 0;
  if (blinkPhase >= 0) {
    blinkPhase += dt / 0.15;
    em?.setValue("blink", Math.sin(Math.min(1, blinkPhase) * Math.PI));
    if (blinkPhase >= 1) { blinkPhase = -1; nextBlink = t + 2 + Math.random() * 3; em?.setValue("blink", 0); }
  }

  frame(dt);
  const waiting = state === "idle" || state === "show" || state === "hide";
  const naturalMotion = waiting && !options.idle_motion ? 0 : options.motion;
  rig?.apply(now, naturalMotion, state === "confirm" || state === "error" ? "listening" : state, dt);
  const weights = options.lips === "off" ? [0,0,0,0,0] : lips.sample(now);
  locomotion?.update(motionDelta, now, travel.moving, travel.speed, travel.travelled, travel.direction, actor.scale.x,
    rig?.gesture ?? "stop", mixer !== null, (now - (rig?.beatOrigin ?? 0)) * (rig?.bpm ?? 120) / 120,
    options.walk, now - (rig?.started ?? now), !waiting || options.idle_motion);
  actor.rotation.y = locomotion?.yaw ?? 0;
  if (moveId && !travel.moving && locomotion?.readyToRest && Math.abs(Math.sin(locomotion.yaw)) < 0.02) {
    finishMotion({ animation: "stop", motion_id: moveId }); moveId = "";
  }
  mixer?.update(dt);
  seating?.update(now,dt,mixer ? 'custom' : rig?.gesture ?? 'stop');
  if (seating && seating.weight > .001) {
    actor.updateMatrixWorld(true);
    const hip=vrm.humanoid.getNormalizedBoneNode('hips');
    if (hip) {
      const local=actor.worldToLocal(hip.getWorldPosition(seatHip));
      if (seating.kind === "window") actor.position.y -= local.y*actor.scale.y*seating.weight;
    }
  }
  // Слой состояния — после анимаций: жест, танец и шаг важнее, поза уступает им и возвращается сама.
  if (stateLayer) {
    if (state === "error" && now - stateSince > ERROR_HOLD && !(!TAURI && params.get("state"))) { state = "idle"; stateSince = now; }
    const mood: Mood = state === "idle" || state === "show" ? (now - stateSince > REST_AFTER ? "rest" : "idle")
      : state === "hide" ? "idle" : state;
    stateLayer.set(mood, now);
    if (!TAURI && params.get("state")) stateLayer.snap();
    const busy = (rig?.gesture && rig.gesture !== "stop") || mixer !== null || (locomotion?.walkingWeight ?? 0) > 0.1 ? 1 : 0;
    const speech = Math.min(1, weights.reduce((a, b) => a + b, 0) * 1.6);
    stateLayer.apply(now, dt, speech, busy, options.reactions ? naturalMotion : 0);
  }
  controls.update(travel.point.x, travel.point.y-actorHeight-40,now,!PREVIEW && visible && options.reactions);

  // Эмоции по состоянию — из того же слоя, чтобы лицо, поза и взгляд совпадали.
  const face = options.reactions ? stateLayer?.face() ?? { relaxed: 0.25 } : {};
  setExpression(options.reactions && controls.mood ? {[controls.mood]: .45} : face, dt);

  const fallback = em?.getExpression('aa') ? 'aa' : vowels.find(v=>em?.getExpression(v));
  for (let i=0;i<vowels.length;i++) {
    const v=vowels[i], current=em?.getValue(v) ?? 0;
    const supported=em?.getExpression(v);
    const want=supported ? Math.min(1, weights[i]+(v===fallback ? weights.reduce((sum,w,n)=>sum+(!em?.getExpression(vowels[n])?w:0),0) : 0)) : 0;
    em?.setValue(v,current+(want-current)*(1-Math.exp(-dt*30)));
  }

  if (!TAURI) {
    canvas.dataset.mouth = JSON.stringify(vowels.map(v=>em?.getValue(v)??0));
    canvas.dataset.seated=String(seating?.seated??false);
  }
  if (resumed) { actor.updateMatrixWorld(true); vrm.springBoneManager?.reset(); }
  vrm.update(dt);
  if (!TAURI && params.has("inspect")) {
    canvas.dataset.gait = JSON.stringify(Object.fromEntries(["hips", "leftFoot", "rightFoot", "leftToes", "rightToes", "leftLowerLeg", "rightLowerLeg", "leftUpperArm", "rightUpperArm"].map(name => {
      const bone = vrm!.humanoid.getNormalizedBoneNode(name as any);
      return [name, bone ? { position: bone.getWorldPosition(new THREE.Vector3()).toArray(), rotation: bone.quaternion.toArray() } : null];
    })));
  }
  // Рисуем только область вокруг персонажа (с запасом на поклон, танец и шаг),
  // а не весь рабочий стол: остальное и так прозрачное.
  const reach = Math.max(actorWidth, actorHeight) * 1.2;
  const feet = innerHeight - travel.point.y;
  renderer.setScissorTest(true);
  const margin = cropY > .001 ? 0 : actorHeight * (seating && seating.weight > .01 ? .9 : .25);
  renderer.setScissor(travel.point.x - reach, feet - margin, reach * 2, actorHeight * 2);
  renderer.render(scene, camera);
}
requestAnimationFrame(tick);

// --------------------------------------------------------------- события ядра

let bubbleTimer = 0;
function showText(text: string) {
  if (!options.subtitles) return;
  bubble.textContent = text.length > 220 ? text.slice(0, 217) + "…" : text;
  bubble.classList.add("on");
  clearTimeout(bubbleTimer);
  bubbleTimer = window.setTimeout(() => bubble.classList.remove("on"), Math.max(4000, text.length * 70));
}

function onEvent(e: any) {
  controls.event(e);
  if (e.kind === "mouth") lips.push({...e,delay:(Number(e.delay)||0)+(options.lip_delay||0)},performance.now()/1000);
  else if (e.kind === "avatar") {
    visible = e.state !== "hide";
    if (!visible) { lips.clear(); bubble.classList.remove("on"); }
    if (e.options) {
      options = { ...options, desktop_framing: "full", idle_motion: true, ...e.options };
      options.fps = [20, 24, 30, 60].includes(options.fps) ? options.fps : 30;
      options.scale = Number.isFinite(options.scale) ? Math.max(0.2, Math.min(4, options.scale)) : 1;
      options.motion = Number.isFinite(options.motion) ? Math.max(0, Math.min(1.5, options.motion)) : 1;
      if (!options.subtitles) bubble.classList.remove("on");
    }
    if (["idle","listening","thinking","hide"].includes(e.state)) lips.clear();
    if (!visible) { controls.close(); controls.badge.hidden=true; }
    if (e.state && e.state !== "show" && e.state !== "hide" && e.state !== state) { state = e.state; stateSince = performance.now() / 1000; }
    if (Array.isArray(e.options?.accessories)) { accessoryItems=e.options.accessories; void accessories?.set(accessoryItems).catch(err=>controls.notice(String(err),false)); }
    if (e.model) load(e.model);
  } else if (e.kind === "reply" && e.text) showText(e.text);
  else if (e.kind === "avatar_seat") void requestSeat(e.surface).catch(err=>controls.notice(String(err),false));
  else if (e.kind === "avatar_place") place(e);
  else if (e.kind === "avatar_motion") void playMotion(e);
  else if (e.kind === "avatar_beat") rig?.sync(performance.now() / 1000, e.bpm, e.age);
  else if (e.kind === "avatar_notice") {
    errorBox.textContent = translate(String(e.text ?? ""),language());
    if (e.motion_id) finishMotion({ animation: "stop", motion_id: e.motion_id });
  }
  else if (e.kind === "persona" && e.persona?.avatar?.model) load(e.persona.avatar.model);
}

if (TAURI) {
  void (async () => {
    const settings=await invoke<any>('settings_get').catch(()=>({}));
    saveLanguage(settings.user?.ui?.language ?? settings.defaults?.ui?.language ?? language());
    await listen<string>('ui:language',({payload})=>saveLanguage(payload));
    const layout = await invoke<{ screens: Rect[]; anchor: Point | null }>("avatar_layout");
    if (layout.screens.length) screens = layout.screens;
    if (layout.anchor) { travel.drag(layout.anchor); placed = true; }
    await listen("avatar:menu", () => controls.show(travel.point.x,travel.point.y-actorHeight));
    await listen<any>("core:event", ({ payload }) => onEvent(payload));
    const timers=await invoke<any>("core_get",{path:"/api/avatar/timers"}).catch(()=>({items:[]}));
    controls.event({kind:"timers",items:timers.items});
    const current = await invoke<any>("avatar_snapshot");
    onEvent({ ...current, kind: "avatar" });
    if (!current.model && params.get("model")) void load(params.get("model")!);
    if (current.placement) place(current.placement);
  })().catch(error => { errorBox.textContent = String(error); });
  // Отключили монитор или поменяли разрешение — персонаж не остаётся за пределами экрана.
  setInterval(async () => {
    if (!visible || dragging) return;
    try {
      const layout = await invoke<{ screens: Rect[] }>("avatar_layout");
      if (!layout.screens.length || JSON.stringify(layout.screens) === JSON.stringify(screens)) return;
      screens = layout.screens;
      const inside = screens.some(r => travel.point.x >= r.x && travel.point.x <= r.x + r.width && travel.point.y >= r.y && travel.point.y <= r.y + r.height);
      if (!inside) { stand(); travel.drag(destination(screens[0], "bottom-right", actorWidth, actorHeight)); saveAnchor(); }
    } catch { /* окно ещё не готово */ }
  }, 4000);
  const ray = new THREE.Raycaster();
  let polling = false;
  setInterval(async () => {
    if (polling || !visible) return;
    polling = true;
    try {
      const point = await invoke<Point>("avatar_pointer", { interactive: dragging || hover || controls.open });
      pointerPoint=point;
      if (!dragging && vrm) {
        const near = Math.abs(point.x - travel.point.x) < Math.max(actorWidth, actorHeight) &&
                     Math.abs(point.y - (travel.point.y - actorHeight / 2)) < actorHeight;
        if (near) {
          ray.setFromCamera(new THREE.Vector2(point.x / innerWidth * 2 - 1, 1 - point.y / innerHeight * 2), camera);
          hover = ray.intersectObject(vrm.scene, true).length > 0;
        } else hover = false;
      }
    } catch { hover = false; } finally { polling = false; }
  }, 80);
  canvas.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !hover) return;
    stand();
    dragging = true; canvas.setPointerCapture(event.pointerId);
    dragOffset = { x: travel.point.x - event.clientX, y: travel.point.y - event.clientY };
  });
  canvas.addEventListener("pointermove", event => {
    if (dragging) travel.drag({ x: Math.max(24, Math.min(innerWidth - 24, event.clientX + dragOffset.x)),
      y: Math.max(48, Math.min(innerHeight - 8, event.clientY + dragOffset.y)) });
  });
  const release = () => { if (dragging) { dragging = false; saveAnchor(); } };
  canvas.addEventListener("contextmenu", event => { event.preventDefault(); if (hover) controls.show(event.clientX,event.clientY); });
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("lostpointercapture", release);
} else if (PREVIEW) {
  window.addEventListener('message', async event => {
    if (event.source!==parent || event.origin!==location.origin) return;
    if (event.data?.kind==='preview-model' && event.data.bytes instanceof ArrayBuffer) {
      const url=URL.createObjectURL(new Blob([event.data.bytes]));
      try { await load(url); options={...options,...event.data.options}; } finally { URL.revokeObjectURL(url); }
    } else if (event.data?.kind==='preview-clip' && event.data.bytes instanceof ArrayBuffer) {
      const url=URL.createObjectURL(new Blob([event.data.bytes]));
      try { await playMotion({animation:'custom',file:url,loop:event.data.loop}); } finally { URL.revokeObjectURL(url); }
    } else if (event.data?.kind==='preview-motion') onEvent({...event.data,kind:'avatar_motion'});
    else if (event.data?.kind==='preview-seat') void requestSeat(event.data.surface);
    else if (event.data?.kind==='preview-mouth') lips.push(event.data,performance.now()/1000);
    else if (event.data?.kind==='preview-options') { previewAccessoryBytes=event.data.accessoryBytes??{}; options={...options,...event.data.options}; accessoryItems=event.data.options.accessories??[]; void accessories?.set(accessoryItems); }
  });
  parent.postMessage({kind:'preview-ready'},location.origin);
} else if (params.get("demo")) {
  // Без приложения: показать, как персонаж слушает, думает и говорит.
  // Только для разработки в браузере: доступ к модели для численной проверки позы.
  (window as any).__avatar = { vrm: () => vrm, layer: () => stateLayer, THREE };
  const holdParam = params.get("state");
  const hold = (holdParam === "rest" ? "idle" : holdParam) as State | null;
  if (hold) setTimeout(() => {
    onEvent({ kind: "avatar", state: hold });
    if (holdParam === "rest") stateSince -= REST_AFTER + 1;           // сразу «давно без дела»
    if (hold === "error") setInterval(() => onEvent({ kind: "avatar", state: hold }), 2500);     // «ошибка» сама проходит — повторить для осмотра
    if (hold === "speaking") setInterval(() => onEvent({ kind: "mouth", rate: 20, levels: Array.from({ length: 40 }, (_, k) => Math.abs(Math.sin(k * 0.9)) * 0.5) }), 1800);
    if (params.has('captions')) {
      const sample=()=>{
        onEvent({kind:'reply',text:'Хорошо! Я выполнила действие и продолжаю слушать вашу следующую просьбу.'});
        onEvent({kind:'tool_result',ok:true,outcome:'done'});
      };
      sample(); setInterval(sample,5000);
    }
  }, 300);
  const states: State[] = ["listening", "thinking", "speaking", "confirm", "error", "idle"];
  let i = 0;
  if (!hold) setInterval(() => {
    const next = states[i++ % states.length];
    onEvent({ kind: "avatar", state: next });
    if (next === "speaking") {
      onEvent({ kind: "mouth", rate: 20, levels: Array.from({ length: 40 }, (_, k) => Math.abs(Math.sin(k * 0.9)) * 0.5) });
      onEvent({ kind: "reply", text: "Хорошо, хозяин! Таймер на пятнадцать минут поставлен." });
    }
  }, 2000);
}

if (!TAURI && !PREVIEW) void load(params.get("model") ?? "");
