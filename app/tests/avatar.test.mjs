import { test } from 'node:test';
import assert from 'node:assert/strict';
import { captionPosition } from '../src/avatar/captions.ts';

test('one caption stack stays onscreen for tall text at every screen edge', () => {
  for (const [x,y] of [[0,0],[1920,0],[0,1080],[1920,1080],[960,540]]) {
    const p=captionPosition(x,y,320,250,1920,1080);
    assert.ok(p.left>=8 && p.left+320<=1912);
    assert.ok(p.top>=8 && p.top+250<=1072);
  }
});
import * as THREE from 'three';
import { RigMotion } from '../src/avatar/motion.ts';
import { validateGlb } from '../src/avatar/assets.ts';
import { Travel, destination } from '../src/avatar/desktop.ts';
import { Locomotion, heading, turnTowards } from '../src/avatar/locomotion.ts';
import { VRMHumanBoneList, VRMHumanBoneParentMap } from '@pixiv/three-vrm';
import { VRMAnimationLoaderPlugin } from '@pixiv/three-vrm-animation';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { readFile } from 'node:fs/promises';
import { SpringScale } from '../src/avatar/physics.ts';
import { Lips } from '../src/avatar/lips.ts';
import { StateLayer } from '../src/avatar/state.ts';
import { Seating, seatPoint } from '../src/avatar/seating.ts';
import { VRMSpringBoneJoint, VRMSpringBoneManager } from '@pixiv/three-vrm';

function rig() {
  const bones = new Map();
  const humanoid = { getNormalizedBoneNode(name) {
    if (!bones.has(name)) bones.set(name, new THREE.Object3D());
    return bones.get(name);
  } };
  return { motion: new RigMotion(humanoid), bones };
}

test('character state eases back to neutral and yields arms to authored gestures', () => {
  const bones = new Map();
  const humanoid = {getNormalizedBoneNode(name) { if (!bones.has(name)) bones.set(name, new THREE.Object3D()); return bones.get(name); }};
  const motion = new RigMotion(humanoid);
  const layer = new StateLayer(humanoid);
  const authored = new THREE.Quaternion().setFromEuler(new THREE.Euler(.3, .2, -.4));
  layer.set('speaking', 0); layer.snap();
  const frame = (now, busy) => { motion.apply(now, 0, 'idle', 1/60); bones.get('leftUpperArm').quaternion.copy(authored); layer.apply(now, 1/60, 1, busy, 1); };
  for (let i=0;i<180;i++) frame(i/60, 1);
  assert.ok(bones.get('leftUpperArm').quaternion.angleTo(authored) < .002);
  layer.set('thinking', 3);
  for (let i=180;i<300;i++) frame(i/60, 0);
  assert.ok(bones.get('neck').quaternion.angleTo(new THREE.Quaternion()) > .1);
  layer.set('idle', 5);
  for (let i=300;i<540;i++) frame(i/60, 0);
  assert.ok(bones.get('neck').quaternion.angleTo(new THREE.Quaternion()) < .002);
  for (const bone of bones.values()) assert.ok(bone.quaternion.toArray().every(Number.isFinite));
});

test('mouth clock follows playback, rejects backlog and clears on interruption', () => {
  const lips=new Lips();
  lips.push({frames:[[.8,0,0,0,0],[0,0,.7,0,0]],duration:.2,delay:.1},10);
  assert.deepEqual(lips.sample(10),[0,0,0,0,0]);
  assert.deepEqual(lips.sample(10.15),[.8,0,0,0,0]);
  assert.deepEqual(lips.sample(10.25),[0,0,.7,0,0]);
  lips.push({clear:true},10.25);
  assert.deepEqual(lips.sample(10.26),[0,0,0,0,0]);
  lips.push({frames:[[1,0,0,0,0]],duration:1000},11);
  assert.deepEqual(lips.sample(12),[0,0,0,0,0]);
});

test('speech energy spikes cannot snap the arms or distort an authored pose', () => {
  const vrm = walkingRig('1'), layer = new StateLayer(vrm.humanoid);
  layer.set('speaking', 0); layer.snap();
  const authored = new THREE.Quaternion().setFromEuler(new THREE.Euler(.3, .2, -.4));
  let previous = authored.clone();
  const arm = vrm.humanoid.getNormalizedBoneNode('leftLowerArm');
  for (let i = 0; i < 600; i++) {
    for (const n of VRMHumanBoneList) vrm.humanoid.getNormalizedBoneNode(n).quaternion.copy(authored);
    layer.apply(i / 60, 1 / 60, i % 2 ? 1 : 0, 0);
    assert.ok(arm.quaternion.angleTo(previous) <= .35 / 60 + 1e-6, 'speech offset has an abrupt frame');
    assert.ok(arm.quaternion.angleTo(authored) < .05, 'speech must remain a subtle additive pose');
    previous.copy(arm.quaternion);
  }
});

test('speaking pose remains consistent on a slow and fast display', () => {
  const sample = fps => {
    const vrm = walkingRig('1'), layer = new StateLayer(vrm.humanoid);
    layer.set('speaking', 0); layer.snap();
    for (let i = 1; i <= fps * 4; i++) {
      for (const n of VRMHumanBoneList) vrm.humanoid.getNormalizedBoneNode(n).quaternion.identity();
      layer.apply(i / fps, 1 / fps, 1, 0);
    }
    return vrm.humanoid.getNormalizedBoneNode('leftLowerArm').quaternion.clone();
  };
  assert.ok(sample(30).angleTo(sample(120)) < .001);
});

test('seating rejects offscreen and cramped edges, clamps within a negative monitor', () => {
  const screens=[{x:-1920,y:0,width:1920,height:1080}];
  assert.equal(seatPoint({x:-1500,y:40,width:500,height:600},screens,350,-1600),null);
  assert.equal(seatPoint({x:200,y:500,width:500,height:400},screens,350,400),null);
  assert.deepEqual(seatPoint({x:-1500,y:500,width:500,height:400},screens,350,-1800),{x:-1470,y:500});
});

test('authored seated clips bend knees and release smoothly on both VRM versions', async () => {
  const bytes=await readFile(new URL('../public/animations/seated.vrma',import.meta.url));
  const loader=new GLTFLoader();loader.register(p=>new VRMAnimationLoaderPlugin(p));
  const clips=(await loader.parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'')).userData.vrmAnimations;
  assert.equal(clips.length,4);
  for(const version of ['0','1']) {
    const vrm=walkingRig(version), seat=new Seating(vrm,clips), base=new RigMotion(vrm.humanoid);
    seat.sit({id:'window',kind:'window',x:0,y:500,width:500,height:300},0);
    for(let t=0;t<3;t+=1/30){base.apply(t);seat.update(t,1/30,'stop');}
    assert.ok(vrm.humanoid.getNormalizedBoneNode('leftLowerLeg').quaternion.angleTo(new THREE.Quaternion())>.5);
    seat.stand(3);
    for(let t=3;t<5;t+=1/30){base.apply(t);seat.update(t,1/30,'stop');}
    assert.ok(seat.weight<.001); assert.equal(seat.surface,null);
    seat.dispose();
  }
});

test('gesture timeline expires and old finger poses are cleared', () => {
  const { motion, bones } = rig();
  motion.apply(2);
  const rest = bones.get('rightUpperArm').quaternion.clone();
  motion.start('wave', 2);
  motion.apply(3);
  bones.get('rightIndexIntermediate').quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1), 1.3);
  motion.apply(3.1);
  assert.ok(bones.get('rightIndexIntermediate').quaternion.angleTo(new THREE.Quaternion()) < 1e-7);
  motion.apply(8);
  assert.equal(motion.gesture, 'stop');
  assert.ok(rest.angleTo(bones.get('rightUpperArm').quaternion) < 1e-7);
});

test('dance follows tempo without accumulating a positional or rotational drift', () => {
  const { motion, bones } = rig();
  motion.start('dance', 0, 120);
  motion.apply(2.125);
  const first = bones.get('hips').position.clone();
  const rotation = bones.get('hips').quaternion.clone();
  motion.apply(2002.125);
  assert.ok(first.distanceTo(bones.get('hips').position) < 1e-8);
  assert.ok(rotation.angleTo(bones.get('hips').quaternion) < 1e-7);
  motion.start('stop', 2003);
  motion.apply(2003);
  assert.equal(bones.get('hips').position.y, 0);
});

test('gestures tolerate models with missing optional bones and stop at zero intensity', () => {
  const motion = new RigMotion({ getNormalizedBoneNode() { return null; } });
  for (const gesture of ['wave', 'nod', 'bow', 'dance', 'stop']) {
    motion.start(gesture, 0);
    assert.doesNotThrow(() => motion.apply(1, 0));
  }
});

test('authored bow leans forward for VRM 0 and 1', async () => {
  for (const version of ['0','1']) {
    const vrm = walkingRig(version), motion = new Locomotion(vrm, await motions());
    motion.update(1, 1.7, false, 0, 0, {x:0,y:0}, 1, 'bow', false, 0, 'natural', 1.7);
    assert.ok(vrm.humanoid.getNormalizedBoneNode('head').getWorldPosition(new THREE.Vector3()).z > 0.1);
    motion.dispose();
  }
});

test('downloaded wave opens the index and middle fingers on both VRM versions', async () => {
  for(const version of ['0','1']) {
    const vrm = walkingRig(version), base = new RigMotion(vrm.humanoid), motion = new Locomotion(vrm, await motions());
    // Simulate a clenched hand left by the previous idle clip.
    for(const finger of ['Index','Middle']) vrm.humanoid.getNormalizedBoneNode('right'+finger+'Intermediate').quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1), 1.5);
    base.apply(1.7);
    motion.update(1, 1.7, false, 0, 0, {x:0,y:0}, 1, 'wave', false, 0, 'natural', 1.7);
    assert.ok(vrm.humanoid.getNormalizedBoneNode('rightUpperArm').quaternion.angleTo(new THREE.Quaternion()) > .5);
    for(const finger of ['Index','Middle']) for(const joint of ['Proximal','Intermediate','Distal']) {
      const angle = vrm.humanoid.getNormalizedBoneNode('right'+finger+joint).quaternion.angleTo(new THREE.Quaternion());
      assert.ok(angle < .5, `${version}: ${finger}${joint} is curled into a fist`);
    }
    motion.dispose();
  }
});

test('movement supports negative monitor coordinates and reaches the exact destination smoothly', () => {
  const target = destination({ x: -1920, y: 0, width: 1920, height: 1080 }, 'top-left', 180, 350);
  assert.ok(target.x < 0); assert.equal(target.y, 374);
  const travel = new Travel({ x: 1700, y: 900 }); travel.start(target, 10);
  travel.update(10); assert.deepEqual(travel.point, { x: 1700, y: 900 });
  travel.update(12); assert.ok(travel.point.x < 1700 && travel.point.x > target.x);
  travel.update(100); assert.deepEqual(travel.point, target); assert.equal(travel.moving, false);
});

test('walking turns first, accelerates smoothly and does not race across distant monitors', () => {
  const t = new Travel({ x: 0, y: 0 }); t.start({ x: 2400, y: 0 }, 0, 150);
  t.update(0.3); assert.equal(t.point.x, 0); assert.equal(t.speed, 0);
  t.update(0.5); assert.ok(t.speed > 0 && t.speed < 150);
  t.update(5); assert.ok(t.point.x < 750); assert.equal(t.speed, 150);
  t.update(16.6); assert.ok(t.speed < 150 && t.speed > 0);
  t.update(20); assert.deepEqual(t.point, { x: 2400, y: 0 }); assert.equal(t.speed, 0);
  assert.equal(heading({ x: 1, y: 0 }), Math.PI / 2);
  assert.equal(heading({ x: -1, y: 0 }), -Math.PI / 2);
  const turned = turnTowards(Math.PI - 0.01, -Math.PI + 0.01, 0.05);
  assert.ok(Math.abs(turned - Math.PI) < 0.01);
});

async function motions() {
  const result=[];
  for(const name of ['locomotion','gestures']) {
    const bytes = await readFile(new URL('../public/animations/'+name+'.vrma', import.meta.url));
    const loader = new GLTFLoader(); loader.register(parser => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '');
    result.push(...gltf.userData.vrmAnimations);
  }
  return result;
}

function walkingRig(version) {
  const scene = new THREE.Group(); scene.rotation.y = version === '0' ? Math.PI : 0;
  const bones = new Map();
  for (const name of VRMHumanBoneList) {
    const bone = new THREE.Object3D(); bone.name = name; bones.set(name, bone);
  }
  for (const [name, bone] of bones) (bones.get(VRMHumanBoneParentMap[name]) ?? scene).add(bone);
  bones.get('hips').position.y = 1;
  for(const name of ['spine','chest','upperChest','neck','head']) bones.get(name).position.y = 0.18;
  for (const side of ['left', 'right']) {
    bones.get(side+'UpperLeg').position.set(side === 'left' ? 0.1 : -0.1, 0, 0);
    bones.get(side+'LowerLeg').position.y = -0.45;
    bones.get(side+'Foot').position.y = -0.45;
    bones.get(side+'Toes').position.z = 0.15;
  }
  return { scene, meta: { metaVersion: version }, humanoid: {
    getNormalizedBoneNode: n => bones.get(n), normalizedRestPose: { hips: { position: [0, 1, 0] } }
  } };
}

test('bundled full-body walk retargets to VRM 0 and 1, follows distance and keeps foot contact', async () => {
  const clips = await motions(); assert.equal(clips.length, 7);
  assert.ok(clips[1].humanoidTracks.rotation.has('leftToes'));
  assert.ok(clips[1].humanoidTracks.rotation.has('rightHand'));
  const legs = [];
  for (const version of ['0', '1']) {
    const vrm = walkingRig(version), l = new Locomotion(vrm, clips), h = vrm.humanoid;
    const knee = h.getNormalizedBoneNode('rightLowerLeg');
    l.update(1, 1, true, 200, l.stride * 0.37, { x: 1, y: 0 }, 1, 'stop');
    const q = knee.quaternion.clone(); legs.push(q);
    assert.ok(q.angleTo(new THREE.Quaternion()) > 0.2);
    assert.ok(Math.abs(l.yaw - Math.PI / 2) < 0.01);
    const feet = ['leftFoot', 'rightFoot', 'leftToes', 'rightToes'].map(n => h.getNormalizedBoneNode(n).getWorldPosition(new THREE.Vector3()).y);
    assert.ok(Math.abs(Math.min(...feet) - 0.1) < 1e-5);
    l.update(1, 11, true, 200, l.stride * 0.37, { x: 1, y: 0 }, 1, 'stop');
    assert.ok(q.angleTo(knee.quaternion) < 0.0001, 'standing still must not advance the step');
    l.update(1, 12, false, 0, l.stride * 0.37, { x: 1, y: 0 }, 1, 'stop');
    assert.ok(l.readyToRest); assert.ok(Math.abs(l.yaw) < 0.01);
    l.dispose();
  }
  assert.ok(Math.abs(legs[0].x + legs[1].x) < 1e-6, 'old and new VRM skeletons need opposite X rotations');
});

test('the authored dance moves the body and loops without accumulating drift', async () => {
  const vrm = walkingRig('1'), l = new Locomotion(vrm, await motions());
  const sample = phase => {
    l.update(1, phase, false, 0, 0, { x: 0, y: 0 }, 1, 'dance', false, phase);
    return VRMHumanBoneList.map(n => vrm.humanoid.getNormalizedBoneNode(n).quaternion.clone());
  };
  const q = sample(0.25);
  const other = sample(0.5);
  assert.ok(Math.max(...q.map((v, i) => v.angleTo(other[i]))) > 0.1);
  const looped = sample(1000.25);
  assert.ok(Math.max(...q.map((v, i) => v.angleTo(looped[i]))) < 1e-6);
  l.dispose();
});

test('hair physics behaves the same at model size and desktop pixel scale', () => {
  const make = scale => {
    const actor = new THREE.Group(), bone = new THREE.Object3D(), tip = new THREE.Object3D();
    actor.scale.setScalar(scale); actor.add(bone); bone.position.y = 1; bone.add(tip); tip.position.y = 0.3;
    const joint = new VRMSpringBoneJoint(bone, tip, { stiffness: 4, gravityPower: 0.5, dragForce: 0.4, hitRadius: 0.02 });
    const manager = new VRMSpringBoneManager(); manager.addJoint(joint);
    const correction = new SpringScale(manager.joints); correction.apply(scale); correction.apply(scale);
    actor.updateMatrixWorld(true); manager.setInitState(); manager.reset();
    return { actor, bone, manager, correction, joint };
  };
  const a = make(1), b = make(225);
  for (let i = 1; i < 90; i++) {
    a.actor.position.x = Math.sin(i / 20) * 0.2;
    b.actor.position.x = a.actor.position.x * 225;
    a.actor.updateMatrixWorld(true); b.actor.updateMatrixWorld(true);
    a.manager.update(1/60); b.manager.update(1/60);
    assert.ok(a.bone.quaternion.angleTo(b.bone.quaternion) < 1e-6);
  }
  b.correction.apply(300); assert.equal(b.joint.settings.stiffness, 1200);
  assert.equal(b.joint.settings.hitRadius, 6);
});

test('resting arms point down for either local arm orientation', () => {
  for (const sign of [-1, 1]) {
    const upper = new THREE.Object3D();
    const lower = new THREE.Object3D();
    lower.position.x = sign * 0.3;
    upper.add(lower);
    const motion = new RigMotion({ getNormalizedBoneNode(name) {
      return name === 'rightUpperArm' ? upper : name === 'rightLowerArm' ? lower : null;
    } });
    motion.apply(1);
    assert.ok(lower.getWorldPosition(new THREE.Vector3()).y < -0.2);
  }
});

function glb(data) {
  const json = new TextEncoder().encode(JSON.stringify(data));
  const size = Math.ceil(json.length / 4) * 4;
  const buffer = new ArrayBuffer(20 + size);
  const view = new DataView(buffer);
  view.setUint32(0, 0x46546c67, true); view.setUint32(4, 2, true);
  view.setUint32(8, buffer.byteLength, true); view.setUint32(12, size, true);
  view.setUint32(16, 0x4e4f534a, true);
  new Uint8Array(buffer, 20).fill(32);
  new Uint8Array(buffer, 20, json.length).set(json);
  return buffer;
}

test('accepts VRM 0/1 and VRMA, refuses external network/disk resources', () => {
  for (const ext of ['VRMC_vrm', 'VRM']) assert.doesNotThrow(() => validateGlb(glb({ extensions: { [ext]: {} } }), 'VRMC_vrm'));
  assert.doesNotThrow(() => validateGlb(glb({ extensions: { VRMC_vrm_animation: {} } }), 'VRMC_vrm_animation'));
  for (const uri of ['https://example.com/track.png', 'file:///C:/secret', '../image.png', '//server/share']) {
    assert.throws(() => validateGlb(glb({ extensions: { VRMC_vrm: {} }, images: [{ uri }] }), 'VRMC_vrm'));
  }
  assert.throws(() => validateGlb(new ArrayBuffer(10), 'VRMC_vrm'));
  assert.throws(() => validateGlb(glb({ asset: { version: '2.0' } }), 'VRMC_vrm'));
});
