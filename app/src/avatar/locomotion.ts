import * as THREE from "three";
import { VRMHumanBoneList, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";
import { createVRMAnimationClip, type VRMAnimation } from "@pixiv/three-vrm-animation";
import type { Point } from "./desktop";

/** Shortest angular path, including a turn across the -PI / PI boundary. */
export function turnTowards(current: number, target: number, dt: number) {
  const delta = Math.atan2(Math.sin(target - current), Math.cos(target - current));
  return current + delta * (1 - Math.exp(-Math.max(0, dt) * 8));
}

export function heading(direction: Point) {
  return Math.atan2(direction.x, -direction.y * 1.6);
}

/** Samples on a separate rig, so fading never overwrites a live gesture's pose. */
export class PoseClip {
  root = new THREE.Group();
  bones = new Map<VRMHumanBoneName, THREE.Object3D>();
  mixer: THREE.AnimationMixer;
  duration: number;
  constructor(animation: VRMAnimation, vrm: VRM) {
    for (const name of VRMHumanBoneList) {
      const source = vrm.humanoid.getNormalizedBoneNode(name);
      if (!source) continue;
      const bone = new THREE.Object3D(); bone.name = source.name;
      bone.position.copy(source.position); bone.quaternion.copy(source.quaternion);
      this.root.add(bone); this.bones.set(name, bone);
    }
    this.mixer = new THREE.AnimationMixer(this.root);
    const clip = createVRMAnimationClip(animation, vrm);
    // A VRM may have its pelvis slightly in front of its model origin. Keep
    // that reference offset; transfer the sway, not the source rig's origin.
    const hips = vrm.humanoid.getNormalizedBoneNode("hips");
    const rest = vrm.humanoid.normalizedRestPose.hips?.position;
    const position = clip.tracks.find(t => t.name === `${hips?.name}.position`);
    if (position && rest) {
      const ratio = rest[1] / animation.restHipsPosition.y;
      const sign = vrm.meta.metaVersion === "0" ? -1 : 1;
      for (let i = 0; i < position.values.length; i += 3) {
        position.values[i] += rest[0] - animation.restHipsPosition.x * ratio * sign;
        position.values[i + 2] += rest[2] - animation.restHipsPosition.z * ratio * sign;
      }
    }
    this.duration = clip.duration;
    this.mixer.clipAction(clip).play();
  }
  sample(time: number, loop = true) { this.mixer.setTime(loop ? ((time % this.duration) + this.duration) % this.duration : Math.max(0, Math.min(this.duration - 1e-6, time))); }
  dispose() { this.mixer.stopAllAction(); this.mixer.uncacheRoot(this.root); }
}

/** Retargeted full-body clips; step phase is driven by distance, not a timer. */
export class Locomotion {
  private idle: PoseClip;
  private walk: PoseClip;
  private formal: PoseClip;
  private dance: PoseClip;
  private gestures: Record<string, PoseClip>;
  private weight = 0;
  private idleWeight = 1;
  private phase = 0;
  private lastDistance = 0;
  private ground = new Map<VRMHumanBoneName, number>();
  private point = new THREE.Vector3();
  yaw = 0;
  /** 1.3 m per cycle, measured from the matching source root-motion clip. */
  stride: number;
  private vrm: VRM;
  constructor(vrm: VRM, animations: VRMAnimation[]) {
    this.vrm = vrm;
    if (animations.length !== 7) throw new Error("Неполный набор движений персонажа.");
    this.idle = new PoseClip(animations[0], vrm);
    this.walk = new PoseClip(animations[1], vrm);
    this.formal = new PoseClip(animations[2], vrm);
    this.dance = new PoseClip(animations[3], vrm);
    this.gestures = { wave: new PoseClip(animations[4], vrm), nod: new PoseClip(animations[5], vrm), bow: new PoseClip(animations[6], vrm) };
    const hipsHeight = vrm.humanoid.normalizedRestPose.hips?.position?.[1];
    if (!hipsHeight || hipsHeight <= 0) throw new Error("У модели некорректная высота таза.");
    this.stride = 1.3 * hipsHeight / 0.9167;
    for (const name of ["leftFoot", "rightFoot", "leftToes", "rightToes"] as VRMHumanBoneName[]) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name);
      if (bone) this.ground.set(name, vrm.scene.worldToLocal(bone.getWorldPosition(this.point)).y);
    }
  }
  get readyToRest() { return this.weight < 0.01; }
  get walkingWeight() { return this.weight; }
  begin() { this.lastDistance = 0; }
  update(dt: number, now: number, moving: boolean, speed: number, distance: number, direction: Point,
         scale: number, gesture: string, suppress = false, danceTime = 0, style = "natural", gestureTime = 0, animateIdle = true) {
    this.yaw = turnTowards(this.yaw, moving ? heading(direction) : 0, dt);
    const pixelsPerCycle = this.stride * scale;
    const advance = Math.max(0, distance - this.lastDistance);
    this.lastDistance = distance;
    this.phase += advance / pixelsPerCycle * this.walk.duration;
    const blend = 1 - Math.exp(-dt * 12);
    this.weight += ((moving && speed > 0.5 ? 1 : 0) - this.weight) * blend;
    this.idleWeight += ((gesture === "stop" && !suppress ? 1 : 0) - this.idleWeight) * blend;
    const walkClip = style === "formal" ? this.formal : this.walk;
    const dancing = gesture === "dance" && !suppress;
    const action = !suppress ? this.gestures[gesture] : undefined;
    const actionWeight = action ? Math.max(0, Math.min(1, gestureTime / .25, (action.duration - gestureTime) / .35)) : 0;
    if (this.idleWeight > 0.001) this.idle.sample(animateIdle ? now : 0);
    if (this.weight > 0.001) walkClip.sample(this.phase);
    if (dancing) this.dance.sample(danceTime);
    action?.sample(gestureTime, false);
    for (const name of VRMHumanBoneList) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name);
      if (!bone) continue;
      const idle = this.idle.bones.get(name), walk = walkClip.bones.get(name), dance = this.dance.bones.get(name);
      if (idle) {
        bone.quaternion.slerp(idle.quaternion, this.idleWeight);
        if (name === "hips") bone.position.lerp(idle.position, this.idleWeight);
      }
      if (dancing && dance) {
        bone.quaternion.copy(dance.quaternion);
        if (name === "hips") bone.position.copy(dance.position);
      }
      const pose = action?.bones.get(name);
      if (pose && actionWeight > 0) {
        bone.quaternion.slerp(pose.quaternion, actionWeight);
        if (name === "hips") bone.position.lerp(pose.position, actionWeight);
      }
      if (walk) {
        const upperGesture = actionWeight > 0 && name !== 'hips' && !/Leg|Foot|Toes/.test(name);
        bone.quaternion.slerp(walk.quaternion, this.weight * (upperGesture ? 1 - actionWeight : 1));
        if (name === "hips") bone.position.lerp(walk.position, this.weight);
      }
      bone.quaternion.normalize();
    }
    // Match the character's own ankle/toe rest heights. This preserves contact
    // after retargeting to a different leg length; it doesn't flatten the knees.
    if ((this.weight > 0.01 || this.idleWeight > 0.99) && !suppress && !dancing) {
      let lowest = Infinity;
      this.vrm.humanoid.getNormalizedBoneNode("hips")?.updateWorldMatrix(true, true);
      for (const [name, height] of this.ground) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name)!;
        lowest = Math.min(lowest, this.vrm.scene.worldToLocal(bone.getWorldPosition(this.point)).y - height);
      }
      const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
      if (hips && Number.isFinite(lowest)) hips.position.y -= lowest;
    }
  }
  dispose() { this.idle.dispose(); this.walk.dispose(); this.formal.dispose(); this.dance.dispose(); Object.values(this.gestures).forEach(g => g.dispose()); }
}
