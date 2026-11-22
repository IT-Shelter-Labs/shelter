import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMUtils, type VRM, type VRMHumanBoneName } from '@pixiv/three-vrm';
import { validateGlb } from './assets';

export type Accessory = { id: string; name: string; bone: string; builtin?: string; file?: string;
  enabled?: boolean; position: number[]; rotation: number[]; scale: number; credit?: string };

export class Accessories {
  private objects: THREE.Object3D[] = [];
  private version = 0;
  private signature = '';
  constructor(private vrm: VRM, private bytes: (path: string) => Promise<ArrayBuffer>) {}
  async set(items: Accessory[]) {
    const signature = JSON.stringify(items);
    if (this.signature === signature) return;
    this.signature = signature;
    this.clear();
    const version = this.version;
    for (const item of items.slice(0, 8)) {
      if (item.enabled === false) continue;
      const bone = this.vrm.humanoid.getRawBoneNode(item.bone as VRMHumanBoneName);
      if (!bone) continue;
      let object: THREE.Object3D;
      if (item.file) {
        const bytes = await this.bytes(item.file); validateGlb(bytes);
        object = (await new GLTFLoader().parseAsync(bytes, '')).scene;
      } else {
        object = new THREE.Group();
        const material = new THREE.MeshStandardMaterial({ color: 0x54d8ec, metalness: .45, roughness: .35 });
        const ring = (x: number, y: number, z: number, radius: number) => {
          const mesh = new THREE.Mesh(new THREE.TorusGeometry(radius, .008, 8, 32), material);
          mesh.position.set(x, y, z); object.add(mesh); return mesh;
        };
        if (item.builtin === 'glasses') {
          const front = this.vrm.meta.metaVersion === '0' ? -.085 : .085;
          ring(-.045, .04, front, .04); ring(.045, .04, front, .04);
          const bridge = new THREE.Mesh(new THREE.BoxGeometry(.025,.008,.008),material);bridge.position.set(0,.04,front);object.add(bridge);
          for(const side of [-1,1]) { const arm=new THREE.Mesh(new THREE.BoxGeometry(.008,.008,.085),material);arm.position.set(side*.085,.04,front/2);object.add(arm); }
        }
        else if (item.builtin === 'headphones') {
          const band = new THREE.Mesh(new THREE.TorusGeometry(.105,.012,8,32,Math.PI),material);band.position.y=.075;object.add(band);
          const padMaterial=new THREE.MeshStandardMaterial({color:0x17202c,roughness:.8});
          for(const side of [-1,1]) {const pad=new THREE.Mesh(new THREE.CylinderGeometry(.045,.045,.035,16),padMaterial);pad.rotation.z=Math.PI/2;pad.position.set(side*.105,.075,0);object.add(pad);}
        }
        else { const halo = ring(0, .24, 0, .13); halo.rotation.x = Math.PI / 2; }
      }
      if (version !== this.version) { VRMUtils.deepDispose(object); return; }
      object.position.fromArray(item.position); object.rotation.set(...item.rotation.map(v => v * Math.PI / 180) as [number, number, number]);
      object.scale.setScalar(item.scale);
      bone.add(object); this.objects.push(object);
    }
  }
  clear() { ++this.version; for (const o of this.objects) { o.removeFromParent(); VRMUtils.deepDispose(o); } this.objects = []; }
}
