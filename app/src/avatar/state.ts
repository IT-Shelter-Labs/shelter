// Слой состояний поверх анимаций: слушает, думает, говорит, ждёт подтверждения,
// сообщает об ошибке, отдыхает. Небольшие добавочные повороты головы, корпуса и
// рук, плавно смешанные между состояниями. Жест, танец и ходьба важнее: на это
// время слой ослабевает, а потом поза сама возвращается к нейтральной.
import * as THREE from "three";
import type { VRMHumanBoneName, VRMHumanoid } from "@pixiv/three-vrm";

export type Mood = "idle" | "listening" | "thinking" | "speaking" | "confirm" | "error" | "rest";
export const MOODS: Mood[] = ["idle", "listening", "thinking", "speaking", "confirm", "error", "rest"];

type Pose = Partial<Record<VRMHumanBoneName, [number, number, number]>>;
type Ctx = { t: number; since: number; level: number; armSign: { left: number; right: number } };

/** Добавочные повороты (рад) в нормализованном пространстве VRM: x — кивок вниз, y — поворот, z — наклон к плечу. */
const POSES: Record<Mood, (c: Ctx) => Pose> = {
  idle: () => ({}),
  // Слушает: голова чуть набок к собеседнику, корпус подан вперёд.
  listening: () => ({ neck: [0.03, 0, 0.05], head: [0.02, 0, 0.06], spine: [0.035, 0, 0] }),
  // Думает: взгляд вверх и в сторону, медленное покачивание головой.
  thinking: (c) => ({ neck: [-0.1, 0.16, -0.05], head: [-0.13, 0.12 + Math.sin(c.t * 0.8) * 0.05, -0.09],
    chest: [0, 0.05, 0] }),
  // Говорит: лёгкие кивки в такт речи и чуть «живые» руки.
  speaking: (c) => {
    const beat = Math.sin(c.t * 7.5) * c.level, slow = Math.sin(c.t * 2.1) * c.level;
    return { head: [0.035 * beat, 0.02 * slow, 0], neck: [0.015 * slow, 0, 0],
      leftUpperArm: [0, 0, c.armSign.left * 0.025 * Math.max(0, slow)],
      rightUpperArm: [0, 0, c.armSign.right * 0.025 * Math.max(0, -slow)],
      leftLowerArm: [0, c.armSign.left * -0.045 * c.level, 0], rightLowerArm: [0, c.armSign.right * -0.045 * c.level, 0] };
  },
  // Ждёт ответа «да/нет»: заметный наклон головы, внимательная поза.
  confirm: () => ({ neck: [0.04, 0, 0.08], head: [0.03, 0, 0.1], spine: [0.045, 0, 0] }),
  // Ошибка: голова опущена, одно короткое покачивание «нет», плечи опущены.
  error: (c) => {
    const shake = c.since < 1.6 ? Math.sin(c.since * 15) * Math.exp(-c.since * 2.4) * 0.16 : 0;
    return { neck: [0.12, shake * 0.6, 0], head: [0.15, shake, 0.03], spine: [0.05, 0, 0],
      leftUpperArm: [0, 0, c.armSign.left * -0.06], rightUpperArm: [0, 0, c.armSign.right * -0.06] };
  },
  // Отдыхает (давно без дела): расслабленно, иногда осматривается.
  rest: (c) => ({ neck: [0.05, Math.sin(c.t * 0.21) * 0.18, 0.02], head: [0.04, Math.sin(c.t * 0.21 + 0.6) * 0.1, Math.sin(c.t * 0.13) * 0.04],
    spine: [0.02, 0, 0] }),
};

const ARMS = /Arm|Hand|Shoulder/;

export class StateLayer {
  private bones = new Map<VRMHumanBoneName, THREE.Object3D>();
  private weights: Record<Mood, number> = { idle: 1, listening: 0, thinking: 0, speaking: 0, confirm: 0, error: 0, rest: 0 };
  private changed = 0;
  private current: Mood = "idle";
  private armSign = { left: 1, right: -1 };
  private presence = 1;
  private euler = new THREE.Euler();
  private q = new THREE.Quaternion();
  private energy = 0;
  private offsets = new Map<VRMHumanBoneName, {angles: THREE.Vector3; current: THREE.Quaternion}>();

  constructor(humanoid: Pick<VRMHumanoid, "getNormalizedBoneNode">) {
    for (const name of ["spine", "chest", "neck", "head", "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm"] as VRMHumanBoneName[]) {
      const bone = humanoid.getNormalizedBoneNode(name);
      if (bone) { this.bones.set(name, bone); this.offsets.set(name, {angles: new THREE.Vector3(), current: new THREE.Quaternion()}); }
    }
    for (const side of ["left", "right"] as const) {
      const x = humanoid.getNormalizedBoneNode(`${side}LowerArm`)?.position.x ?? 0;
      if (Math.abs(x) > 1e-6) this.armSign[side] = Math.sign(x);
    }
  }

  get mood() { return this.current; }

  /** Сразу встать в позу без перехода — для осмотра в режиме разработки. */
  snap() {
    for (const mood of MOODS) this.weights[mood] = mood === this.current ? 1 : 0;
    this.presence = 1;
  }

  set(mood: Mood, now: number) {
    if (mood !== this.current) { this.current = mood; this.changed = now; }
  }

  /** busy: 0 — свободен, 1 — идёт жест, танец или ходьба (руки заняты, голова почти тоже). */
  apply(now: number, dt: number, level: number, busy: number, intensity = 1) {
    dt = Math.max(0, Math.min(.1, dt));
    const wanted = Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0;
    this.energy += (wanted - this.energy) * (1 - Math.exp(-dt / (wanted > this.energy ? .16 : .34)));
    const k = 1 - Math.exp(-Math.max(0, dt) * 5);                 // ≈0.4 с на смену состояния
    for (const mood of MOODS) this.weights[mood] += ((mood === this.current ? 1 : 0) - this.weights[mood]) * k;
    this.presence += ((1 - busy) - this.presence) * (1 - Math.exp(-Math.max(0, dt) * 8));
    const ctx: Ctx = { t: now, since: now - this.changed, level: this.energy, armSign: this.armSign };
    for (const value of this.offsets.values()) value.angles.set(0, 0, 0);
    for (const mood of MOODS) {
      const w = this.weights[mood];
      if (w < 0.002) continue;
      for (const [name, r] of Object.entries(POSES[mood](ctx)) as [VRMHumanBoneName, [number, number, number]][]) {
        const sum = this.offsets.get(name)?.angles;
        if (sum) { sum.x += r[0] * w; sum.y += r[1] * w; sum.z += r[2] * w; }
      }
    }
    const scale = Math.max(0, Math.min(1.5, intensity));
    for (const [name, value] of this.offsets) {
      const {x, y, z} = value.angles;
      const bone = this.bones.get(name);
      if (!bone) continue;
      // Руки уступают жесту полностью, голова и корпус — на 70%.
      const weight = scale * (ARMS.test(name) ? this.presence : 0.3 + 0.7 * this.presence);
      this.q.setFromEuler(this.euler.set(x * weight, y * weight, z * weight));
      const angle = value.current.angleTo(this.q);
      const maxStep = (ARMS.test(name) ? .35 : 1.1) * dt;
      // Smooth only the additive state offset. Authored walk/gesture clips
      // retain their timing and never feed the smoothing state back into REST.
      if (scale === 0) value.current.identity();
      else value.current.slerp(this.q, Math.min(1 - Math.exp(-dt * 7), angle > 1e-7 ? maxStep / angle : 1));
      bone.quaternion.multiply(value.current).normalize();
    }
  }

  /** Куда смотреть относительно «прямо на собеседника»: доли высоты персонажа. */
  gaze(now: number): { x: number; y: number } {
    const w = this.weights;
    const sweep = Math.sin(now * 0.21) * 0.45;
    return {
      x: w.thinking * 0.5 + w.rest * sweep,
      y: w.thinking * 0.45 - w.error * 0.45 - w.rest * 0.05,
    };
  }

  /** Выражение лица по состоянию (мягко смешивается в main.ts). */
  face(): Record<string, number> {
    const w = this.weights;
    return {
      happy: 0.2 * w.listening + 0.3 * w.speaking + 0.08 * w.confirm,
      relaxed: 0.25 * w.idle + 0.2 * w.thinking + 0.45 * w.rest,
      surprised: 0.1 * w.listening + 0.28 * w.confirm,
      sad: 0.6 * w.error,
    };
  }
}
