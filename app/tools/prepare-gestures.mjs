// Convert the pinned Mesh2Motion CC0 clips to a mesh-free normalized VRMA.
// node app/tools/prepare-gestures.mjs <folder with rest-pose/greeting/head-nod/bow.glb>
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { VRMHumanBoneParentMap } from '@pixiv/three-vrm';

const folder = path.resolve(process.argv[2]);
const seated = process.argv.includes('--seated');
const output = fileURLToPath(new URL(seated ? '../public/animations/seated.vrma' : '../public/animations/gestures.vrma', import.meta.url));
async function load(name) {
  const bytes = await fs.readFile(path.join(folder, name + '.glb'));
  return new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '');
}
const reference = await load('rest-pose');
const mixer = new THREE.AnimationMixer(reference.scene);
mixer.clipAction(reference.animations[0]).play(); mixer.setTime(0);
reference.scene.updateMatrixWorld(true);
const sourceNames = { hips: 'pelvis', spine: 'spine_01', chest: 'spine_02', upperChest: 'spine_03', neck: 'neck_01', head: 'head' };
for (const [side, suffix] of [['left','l'],['right','r']]) {
  for (const [bone, source] of [['Shoulder','clavicle'],['UpperArm','upperarm'],['LowerArm','lowerarm'],['Hand','hand'],['UpperLeg','thigh'],['LowerLeg','calf'],['Foot','foot'],['Toes','ball']]) sourceNames[side+bone] = source+'_'+suffix;
  for (const [finger, source] of [['Thumb','thumb'],['Index','index'],['Middle','middle'],['Ring','ring'],['Little','pinky']]) {
    const segments = finger==='Thumb' ? ['Metacarpal','Proximal','Distal'] : ['Proximal','Intermediate','Distal'];
    segments.forEach((segment,i) => sourceNames[side+finger+segment] = source+'_'+String(i+1).padStart(2,'0')+'_'+suffix);
  }
}
const rest = {}, indices = {}, nodes = [];
for (const [bone, source] of Object.entries(sourceNames)) {
  const node = reference.scene.getObjectByName(source);
  if (!node) throw new Error('Missing reference bone '+source);
  rest[bone] = { rotation: node.getWorldQuaternion(new THREE.Quaternion()), position: node.getWorldPosition(new THREE.Vector3()) };
  indices[bone] = nodes.length;
  nodes.push({ name: bone, translation: [0,0,0] });
}
for (const bone of Object.keys(sourceNames)) {
  const parent = VRMHumanBoneParentMap[bone];
  nodes[indices[bone]].translation = rest[bone].position.clone().sub(rest[parent]?.position ?? new THREE.Vector3()).toArray();
  if (parent && indices[parent] !== undefined) (nodes[indices[parent]].children ??= []).push(indices[bone]);
}
const out = { asset: {version:'2.0',generator:'Jarvis Mesh2Motion CC0 gesture conversion'}, scene:0, scenes:[{nodes:[indices.hips]}], nodes,
  extensionsUsed:['VRMC_vrm_animation'], extensions:{VRMC_vrm_animation:{specVersion:'1.0',humanoid:{humanBones:Object.fromEntries(Object.entries(indices).map(([name,node])=>[name,{node}]))}}},
  animations:[],accessors:[],bufferViews:[],buffers:[] };
const chunks=[];let offset=0;
function accessor(values, type) {
  const bytes = Buffer.from(new Float32Array(values).buffer), count = values.length / ({SCALAR:1,VEC3:3,VEC4:4}[type]);
  const view=out.bufferViews.length;out.bufferViews.push({buffer:0,byteOffset:offset,byteLength:bytes.length});chunks.push(bytes);offset+=bytes.length;
  const index=out.accessors.length;out.accessors.push({bufferView:view,componentType:5126,type,count,...(type==='SCALAR'?{min:[values[0]],max:[values.at(-1)]}:{})});return index;
}
for (const [id,file] of (seated ? [['enter','sitting-enter'],['idle','sitting-idle'],['exit','sitting-exit'],['ground','sit-ground-idle']] : [['wave','greeting'],['nod','head-nod'],['bow','bow']])) {
  const asset=await load(file), clip=asset.animations[0], mix=new THREE.AnimationMixer(asset.scene);
  mix.clipAction(clip).setLoop(THREE.LoopOnce,1).play().clampWhenFinished=true;
  const count=Math.ceil(clip.duration*30), times=Array.from({length:count+1},(_,i)=>clip.duration*i/count);
  const rotations=Object.fromEntries(Object.keys(sourceNames).map(n=>[n,[]])), positions=[];
  for (const time of times) {
    mix.setTime(time);asset.scene.updateMatrixWorld(true);
    const deltas={};
    for (const [bone,source] of Object.entries(sourceNames)) {
      const node=asset.scene.getObjectByName(source);
      deltas[bone]=node.getWorldQuaternion(new THREE.Quaternion()).multiply(rest[bone].rotation.clone().invert());
      if(bone==='hips')positions.push(...node.getWorldPosition(new THREE.Vector3()).toArray());
    }
    for (const bone of Object.keys(sourceNames)) {
      const parent=VRMHumanBoneParentMap[bone], q=(deltas[parent]?.clone().invert()??new THREE.Quaternion()).multiply(deltas[bone]).normalize();
      rotations[bone].push(...q.toArray());
    }
  }
  const animation={name:id,samplers:[],channels:[]}, input=accessor(times,'SCALAR');
  const track=(bone,prop,values,type)=>{animation.channels.push({sampler:animation.samplers.length,target:{node:indices[bone],path:prop}});animation.samplers.push({input,output:accessor(values,type),interpolation:'LINEAR'});};
  track('hips','translation',positions,'VEC3');
  for(const [bone,values] of Object.entries(rotations))track(bone,'rotation',values,'VEC4');
  out.animations.push(animation);console.log(id,clip.duration.toFixed(3)+'s',Object.keys(rotations).length+' bones');
}
out.buffers=[{byteLength:offset}];
let json=Buffer.from(JSON.stringify(out));json=Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]);
const binary=Buffer.concat(chunks), header=Buffer.alloc(20);header.writeUInt32LE(0x46546c67,0);header.writeUInt32LE(2,4);header.writeUInt32LE(28+json.length+binary.length,8);header.writeUInt32LE(json.length,12);header.writeUInt32LE(0x4e4f534a,16);
const binHeader=Buffer.alloc(8);binHeader.writeUInt32LE(binary.length);binHeader.writeUInt32LE(0x004e4942,4);
await fs.writeFile(output,Buffer.concat([header,json,binHeader,binary]));
console.log('Wrote',output,(await fs.stat(output)).size);
