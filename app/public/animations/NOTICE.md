# Bundled character motions

Author: Quaternius — Universal Animation Library, Standard pack.

- Source: https://quaternius.com/packs/universalanimationlibrary.html
- Download: https://quaternius.itch.io/universal-animation-library
- License: CC0 1.0 Universal, https://creativecommons.org/publicdomain/zero/1.0/
- Retrieved: 2026-11-14. No Adobe/Mixamo assets are bundled.

`locomotion.vrma` retains Idle_Loop, Walk_Loop, Walk_Formal_Loop and Dance_Loop,
including the finger, toe and torso motion. No source mesh/textures are included.
The reference A-pose was replaced by the pack's A_TPose animation for VRMA
retargeting. Rebuild with `tools/prepare_locomotion.py UAL1_Standard.glb`.

Source GLB SHA-256:
`69591853d817488edaa8fd9bf8fc1d821eaeaf789f8627b3cd23b41c4ed67997`

Bundled VRMA SHA-256:
`d8bc8b63e6eca0caed4ebaf61ccf888fd005a17e25fe8bb290c6ebd248677f14`

The matching Walk_Loop root-motion clip travels 1.3 m per 1.333333 s cycle
on the reference rig (hips rest height 0.9167 m). Desktop travel speed and
animation phase use that measurement, scaled to the chosen character.

VRMA interpretation and VRM 0/1 retargeting use @pixiv/three-vrm-animation
(MIT), already included in the application dependencies.

## Authored gestures (2026-11-15)

`gestures.vrma`: Greeting (wave), Head Nod and Bow from Mesh2Motion.
Art and animations: CC0 1.0. Mesh2Motion / Scott Petrovic and contributors.

- Repository: https://github.com/Mesh2Motion/mesh2motion-app
- Pinned commit: `5d6918ef67203e68c661b3e32e8e8f227bfd953e`
- License: https://github.com/Mesh2Motion/mesh2motion-app/blob/5d6918ef67203e68c661b3e32e8e8f227bfd953e/LICENSE-CC0.MD
- Source files in that commit: `static/assets/human/animations/`
  `rest-pose.glb`, `greeting.glb`, `head-nod.glb`, `bow.glb`.
- Rebuild: `node app/tools/prepare-gestures.mjs <source-folder>`.

The compressed source clips are decoded offline, resampled at 30 Hz and
retargeted from the source reference pose to an identity-axis VRMA skeleton.
All 52 humanoid bones, including finger joints, are retained. No meshes,
textures, external resources, scripts or runtime decoders are included.

SHA-256:

| File | SHA-256 |
| --- | --- |
| rest-pose.glb | e1669b4f6dee30e2c0723a359b269661d85aaee46ebd20d696922d3c4c05d25a |
| greeting.glb | abf286fad0374970d78e72f1d0d8ce190d4b6d976adf58d8bbd6072d873b88bf |
| head-nod.glb | 8a44b309edc5c9371e10afa823caa48bfcb2d2cf4fe1faf98f036b429644a8d3 |
| bow.glb | 311e5421b721b62b8b7859919d8fa16987bf5354f2515f950b8597d8b35cf50d |
| gestures.vrma | 450696f538e34b224b85d1c24d8f7fdc474ee68f7b875358f9d5ef966d545ac0 |

## Seated poses — Mesh2Motion (CC0)

Same pinned upstream commit `5d6918ef67203e68c661b3e32e8e8f227bfd953e` and CC0 art licence as the gestures above.
Source directory: `static/assets/human/animations/`. Rebuild: `node app/tools/prepare-gestures.mjs .review_tools --seated`.

| File | SHA-256 |
| --- | --- |
| sitting-enter.glb | 7a149a9b939b53e2dfa767542b1770cb848b52ee741e7a6ea784a9bec19e5e51 |
| sitting-idle.glb | f727f07d89165bba6baf07eaf93ddb0e68606845c20feaa239f9dac08aa2dc6e |
| sitting-exit.glb | 0f4472c389cec362dd95356095282b09a6723ec38eae2c0c847aaf4618f92003 |
| sit-ground-idle.glb | 4fd660495f41d22fb1229873395e66c15e1369b8481948c11507177ed0d2d74f |
| seated.vrma | 321b04c6b13ee00f8209878899e787309977c11e29b9c194bf92de01c585ac32 |
