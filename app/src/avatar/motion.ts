import * as THREE from "three";
import { VRMHumanBoneList, type VRMHumanBoneName, type VRMHumanoid } from "@pixiv/three-vrm";

export type Gesture = "wave" | "nod" | "bow" | "dance" | "stop";
const NAMES = VRMHumanBoneList;
const DURATIONS: Record<Gesture, number> = { wave: 4.917, nod: 0.792, bow: 3.667, dance: Infinity, stop: 0 };

/** Нормализованный скелет VRM; переходы отсчитываются от REST, без накопления поворотов. */
export class RigMotion {
  private bones = new Map<VRMHumanBoneName, THREE.Object3D>();
  private rest = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private hips = new THREE.Vector3();
  private armSigns = { left: 1, right: -1 };
  private durations: Record<Gesture, number>;
  private rendered = new Map<VRMHumanBoneName, THREE.Quaternion>();
  private rotation = new THREE.Quaternion();
  private angles = new THREE.Euler();
  gesture: Gesture = "stop";
  started = 0;
  bpm = 120;
  beatOrigin = 0;

  constructor(humanoid: Pick<VRMHumanoid, "getNormalizedBoneNode">, durations: Partial<Record<Gesture, number>> = {}) {
    this.durations = { ...DURATIONS, ...durations };
    for (const name of NAMES) {
      const bone = humanoid.getNormalizedBoneNode(name);
      if (bone) { this.bones.set(name, bone); this.rest.set(name, bone.quaternion.clone()); this.rendered.set(name, bone.quaternion.clone()); }
    }
    this.bones.get("hips")?.getWorldPosition(this.hips);
    if (this.bones.has("hips")) this.hips.copy(this.bones.get("hips")!.position);
    for (const side of ["left", "right"] as const) {
      const x = this.bones.get(`${side}LowerArm`)?.position.x ?? 0;
      if (Math.abs(x) > 1e-6) this.armSigns[side] = Math.sign(x);
    }
  }

  start(gesture: Gesture, now: number, bpm = 120) {
    this.gesture = gesture;
    this.started = now;
    this.beatOrigin = now;
    this.bpm = Math.max(50, Math.min(200, Number.isFinite(bpm) ? bpm : 120));
  }

  sync(now: number, bpm: number, age: number) {
    if (this.gesture !== "dance" || !Number.isFinite(bpm) || !Number.isFinite(age)) return;
    this.bpm = Math.max(50, Math.min(200, bpm));
    this.beatOrigin = now - Math.max(0, Math.min(1.2, age));
  }

  private rotate(name: VRMHumanBoneName, x = 0, y = 0, z = 0) {
    this.bones.get(name)?.quaternion.multiply(this.rotation.setFromEuler(this.angles.set(x, y, z)));
  }

  apply(now: number, intensity = 1, state = "idle", dt = 1) {
    for (const [name, q] of this.rest) this.bones.get(name)!.quaternion.copy(q);
    const hips = this.bones.get("hips");
    if (hips) hips.position.copy(this.hips);
    for (const side of ["left", "right"] as const) {
      this.rotate(`${side}UpperArm`, 0, 0, -this.armSigns[side] * 1.2);
      this.rotate(`${side}LowerArm`, 0, this.armSigns[side] * 0.25);
    }
    const elapsed = Math.max(0, now - this.started);
    if (elapsed >= this.durations[this.gesture]) this.gesture = "stop";
    const t = Math.max(0, Math.min(1.5, intensity));
    this.rotate("chest", Math.sin(now * 1.6) * 0.015 * t);
    this.rotate("neck", (state === "thinking" ? -0.08 : Math.sin(now * 0.9) * 0.02) * t,
      (Math.sin(now * 0.5) * 0.06 + (state === "thinking" ? 0.12 : 0)) * t,
      (Math.sin(now * 0.7) * 0.03 + (state === "listening" ? 0.08 : 0)) * t);
    const blend = dt >= 1 ? 1 : 1 - Math.exp(-Math.max(0, dt) * 14);
    for (const [name, bone] of this.bones) {
      const previous = this.rendered.get(name)!;
      previous.slerp(bone.quaternion, blend);
      bone.quaternion.copy(previous);
    }
  }
}
