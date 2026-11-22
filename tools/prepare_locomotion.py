"""Build the bundled VRMA from Quaternius Universal Animation Library Standard.

Usage: python tools/prepare_locomotion.py path/to/UAL1_Standard.glb
The source archive is not required at runtime. Only skeleton and four motions
are retained; meshes, textures and unrelated motions are excluded.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys


def prepare(source: Path, output: Path):
    data = source.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    src = json.loads(data[20:20 + length])
    binary = data[28 + length:]
    nodes = json.loads(json.dumps(src["nodes"]))
    for node in nodes:
        for key in ("mesh", "skin", "weights"):
            node.pop(key, None)

    def values(index):
        accessor = src["accessors"][index]
        view = src["bufferViews"][accessor["bufferView"]]
        size = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
        offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        return struct.unpack_from("<" + "f" * accessor["count"] * size, binary, offset)

    # VRMA requires the reference skeleton to be in T-pose. The source bind
    # pose is A-pose: using it as the reference would bend shoulders incorrectly.
    tpose = next(a for a in src["animations"] if a["name"] == "A_TPose")
    for channel in tpose["channels"]:
        target = channel["target"]
        size = 4 if target["path"] == "rotation" else 3
        nodes[target["node"]][target["path"]] = list(values(tpose["samplers"][channel["sampler"]]["output"])[:size])

    names = {n["name"]: i for i, n in enumerate(nodes)}
    mapping = {"pelvis": "hips", "spine_01": "spine", "spine_02": "chest",
               "spine_03": "upperChest", "neck_01": "neck", "Head": "head"}
    for side, suffix in (("left", "l"), ("right", "r")):
        for source_name, bone in (("clavicle", "Shoulder"), ("upperarm", "UpperArm"),
                                  ("lowerarm", "LowerArm"), ("hand", "Hand"),
                                  ("thigh", "UpperLeg"), ("calf", "LowerLeg"),
                                  ("foot", "Foot"), ("ball", "Toes")):
            mapping[f"{source_name}_{suffix}"] = side + bone
        for finger in ("index", "middle", "ring", "pinky", "thumb"):
            vrm_finger = "Little" if finger == "pinky" else finger.title()
            segments = ("Metacarpal", "Proximal", "Distal") if finger == "thumb" else ("Proximal", "Intermediate", "Distal")
            for i, segment in enumerate(segments, 1):
                mapping[f"{finger}_{i:02}_{suffix}"] = side + vrm_finger + segment
    bones = {bone: {"node": names[name]} for name, bone in mapping.items()}
    bone_indices = {v["node"] for v in bones.values()}
    out = {"asset": {"version": "2.0", "generator": "Jarvis prepare_locomotion.py; Quaternius UAL Standard (CC0)"},
           "scene": 0, "scenes": src["scenes"], "nodes": nodes,
           "extensionsUsed": ["VRMC_vrm_animation"],
           "extensions": {"VRMC_vrm_animation": {"specVersion": "1.0", "humanoid": {"humanBones": bones}}},
           "animations": [], "accessors": [], "bufferViews": [], "buffers": []}
    chunks = bytearray()
    indices = {}

    def copy_accessor(index):
        if index in indices:
            return indices[index]
        a = dict(src["accessors"][index])
        v = src["bufferViews"][a["bufferView"]]
        size = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
        offset = v.get("byteOffset", 0) + a.pop("byteOffset", 0)
        payload = binary[offset:offset + a["count"] * size * 4]
        a["bufferView"] = len(out["bufferViews"])
        out["bufferViews"].append({"buffer": 0, "byteOffset": len(chunks), "byteLength": len(payload)})
        chunks.extend(payload)
        indices[index] = len(out["accessors"])
        out["accessors"].append(a)
        return indices[index]

    for name in ("Idle_Loop", "Walk_Loop", "Walk_Formal_Loop", "Dance_Loop"):
        a = next(a for a in src["animations"] if a["name"] == name)
        animation = {"name": name, "channels": [], "samplers": []}
        for c in a["channels"]:
            target = c["target"]
            if target["node"] not in bone_indices or not (target["path"] == "rotation" or
                    target["node"] == names["pelvis"] and target["path"] == "translation"):
                continue
            sampler = dict(a["samplers"][c["sampler"]])
            sampler["input"] = copy_accessor(sampler["input"])
            sampler["output"] = copy_accessor(sampler["output"])
            animation["channels"].append({"target": target, "sampler": len(animation["samplers"])})
            animation["samplers"].append(sampler)
        out["animations"].append(animation)
    out["buffers"] = [{"byteLength": len(chunks)}]
    raw_json = json.dumps(out, separators=(",", ":")).encode()
    raw_json += b" " * (-len(raw_json) % 4)
    chunks.extend(b"\0" * (-len(chunks) % 4))
    glb = (struct.pack("<III", 0x46546C67, 2, 28 + len(raw_json) + len(chunks)) +
           struct.pack("<II", len(raw_json), 0x4E4F534A) + raw_json +
           struct.pack("<II", len(chunks), 0x004E4942) + chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(glb)
    print(json.dumps({"bytes": len(glb), "source_sha256": hashlib.sha256(data).hexdigest(),
                      "output_sha256": hashlib.sha256(glb).hexdigest()}, indent=2))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "app/public/animations/locomotion.vrma")
