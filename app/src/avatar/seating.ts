import * as THREE from "three";
import { VRMHumanBoneList, type VRM } from "@pixiv/three-vrm";
import { PoseClip } from "./locomotion.ts";
import type { VRMAnimation } from "@pixiv/three-vrm-animation";
import type { Point, Rect } from "./desktop";

export type Surface = Rect & { id: string; kind: "window" | "taskbar" };
export function seatPoint(surface: Surface, screens: Rect[], height: number, x: number): Point | null {
  const screen = screens.find(r => surface.x + surface.width / 2 >= r.x && surface.x + surface.width / 2 <= r.x + r.width && surface.y >= r.y && surface.y <= r.y + r.height + 2);
  if (!screen || surface.width < 80 || surface.y - screen.y < height * .58) return null;
  const left = Math.max(surface.x + 30, screen.x + height * .2);
  const right = Math.min(surface.x + surface.width - 30, screen.x + screen.width - height * .2);
  if (left > right) return null;
  return { x: Math.max(left, Math.min(right, x)), y: surface.y };
}

/** Authored seated pose with separate upper-body gestures and smooth exit. */
export class Seating {
  private enter: PoseClip;
  private idle: PoseClip;
  private exit: PoseClip;
  private ground: PoseClip;
  kind = "window";
  private since = 0;
  private active = false;
  weight = 0;
  surface: Surface | null = null;
  private vrm: VRM;
  constructor(vrm: VRM, clips: VRMAnimation[]) {
    this.vrm = vrm;
    [this.enter, this.idle, this.exit, this.ground] = clips.map(c => new PoseClip(c, vrm));
  }
  sit(surface: Surface, now: number) { this.surface = surface; this.kind=surface.kind; this.since = now; this.active = true; }
  stand(now: number) { if (this.active) { this.since = now; this.active = false; } this.surface = null; }
  get seated() { return this.active; }
  update(now: number, dt: number, gesture: string) {
    this.weight += ((this.active ? 1 : 0) - this.weight) * (1 - Math.exp(-dt * 5));
    if (this.weight < .001) return;
    const elapsed = now - this.since;
    const clip = this.active ? elapsed < this.enter.duration ? this.enter : this.idle : this.exit;
    const selected = this.kind === "taskbar" ? this.ground : clip;
    selected.sample(this.kind === 'taskbar' ? elapsed : this.active && clip === this.idle ? elapsed - this.enter.duration : elapsed, this.kind === 'taskbar' || clip === this.idle);
    for (const name of VRMHumanBoneList) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name), pose = selected.bones.get(name);
      const lower = name === 'hips' || /Leg|Foot|Toes/.test(name);
      if (!bone || !pose || (!lower && gesture !== 'stop')) continue;
      bone.quaternion.slerp(pose.quaternion, this.weight);
      if (name === 'hips') bone.position.lerp(pose.position, this.weight);
    }
  }
  dispose() { this.enter.dispose(); this.idle.dispose(); this.exit.dispose(); this.ground.dispose(); }
}
