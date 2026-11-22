"""Isolated, offline single-speaker Qwen3-TTS pilot; never changes live settings.

Based on the loss and checkpoint recipe in QwenLM/Qwen3-TTS/finetuning
(Apache-2.0, Copyright 2026 The Alibaba Qwen team). Local changes: held-out
validation, FP32 trainable weights, frozen lower layers, native Windows SDPA,
explicit Russian prefix, 0.6B text projection, aligned next-frame residual loss,
finite-gradient checks, reproducible logs, bounded epochs and separate outputs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def read_splits(dataset):
    """Reject overlap and path escape before loading any GPU weights."""
    dataset = Path(dataset).resolve(strict=True)
    result, seen, references = {}, set(), set()
    for split in ("train", "validation", "test"):
        rows = [json.loads(line) for line in (dataset / f"{split}_qwen.jsonl").read_text(encoding="utf8").splitlines() if line.strip()]
        for row in rows:
            audio = Path(row["audio"]).resolve(strict=True)
            ref = Path(row["ref_audio"]).resolve(strict=True)
            if not audio.is_relative_to(dataset) or not ref.is_relative_to(dataset):
                raise ValueError("Audio must stay inside the selected prepared dataset")
            if audio in seen or not str(row["text"]).strip():
                raise ValueError("Duplicate audio or empty transcript")
            seen.add(audio); references.add(ref)
            row.update(audio=str(audio), ref_audio=str(ref))
        result[split] = rows
    if len(references) != 1 or references & seen:
        raise ValueError("Use one separate reference, outside all training/evaluation rows")
    if not result["train"] or not result["validation"] or not result["test"]:
        raise ValueError("All three partitions must be nonempty")
    return result, next(iter(references))


def normalize_config(config):
    """Some 0.6B snapshots use codec_eos_id instead of codec_eos_token_id."""
    talker = config.talker_config
    if hasattr(talker, "codec_eos_id"):
        talker.codec_eos_token_id = talker.codec_eos_id
    if not 0 <= talker.codec_eos_token_id < talker.vocab_size:
        raise ValueError("EOS is outside the codec vocabulary")


def checkpoint_config(base_config, eos):
    """Keep the original nested schema accepted by Qwen's strict dataclasses."""
    config = json.loads(json.dumps(base_config))
    config["tts_model_type"] = "custom_voice"
    config["talker_config"]["codec_eos_token_id"] = eos
    config["talker_config"]["spk_id"] = {"jarvis_pilot": 3000}
    config["talker_config"]["spk_is_dialect"] = {"jarvis_pilot": False}
    return config


def prefix_layout(text_ids, config):
    """Match Qwen generate(non_streaming_mode=True, language='Russian')."""
    c = config.talker_config
    content = list(text_ids[3:-5])
    codec = [c.codec_think_id, c.codec_think_bos_id,
             c.codec_language_id["russian"], c.codec_think_eos_id, 0, c.codec_pad_id]
    text = list(text_ids[:3]) + [config.tts_pad_token_id] * 5 + [config.tts_bos_token_id]
    text += content + [config.tts_eos_token_id, config.tts_pad_token_id]
    codec = [0] * 3 + codec + [c.codec_pad_id] * (len(content) + 1) + [c.codec_bos_id]
    return text, codec, 7


def build_inputs(model, text_ids, codes, speaker):
    import torch
    c = model.config
    text, codec, speaker_pos = prefix_layout(text_ids, c)
    device = model.device
    t = model.talker
    text_emb = t.text_projection(t.get_text_embeddings()(torch.tensor([text], device=device)))
    codec_emb = t.get_input_embeddings()(torch.tensor([codec], device=device))
    codec_emb[:, :3] = 0
    codec_emb[:, speaker_pos] = speaker.to(codec_emb.dtype)
    prefix = text_emb + codec_emb
    codes = torch.tensor(codes, device=device, dtype=torch.long)
    audio_emb = t.get_input_embeddings()(codes[:, 0])
    for i in range(1, c.talker_config.num_code_groups):
        audio_emb = audio_emb + t.code_predictor.get_input_embeddings()[i-1](codes[:, i])
    pad = t.text_projection(t.get_text_embeddings()(torch.tensor([c.tts_pad_token_id], device=device)))
    eos_id = c.talker_config.codec_eos_token_id
    eos = t.get_input_embeddings()(torch.tensor([eos_id], device=device)) + pad
    embeddings = torch.cat((prefix, (audio_emb + pad).unsqueeze(0), eos.unsqueeze(0)), dim=1)
    labels = torch.full(embeddings.shape[:2], -100, dtype=torch.long, device=device)
    offset = prefix.shape[1]
    labels[0, offset:offset+len(codes)] = codes[:, 0]
    labels[0, -1] = eos_id
    return embeddings, labels, codes, offset


def loss_for(model, row, speaker):
    import torch
    embeddings, labels, codes, offset = build_inputs(model, row["text_ids"], row["audio_codes"], speaker)
    outputs = model.talker(inputs_embeds=embeddings, attention_mask=torch.ones_like(labels),
                           labels=labels, use_cache=False, output_hidden_states=True)
    # Hidden state BEFORE frame i predicts all its codec groups, matching inference.
    hidden = outputs.hidden_states[0][-1][0, offset-1:offset-1+len(codes)]
    _, residual = model.talker.forward_sub_talker_finetune(codes, hidden)
    return outputs.loss + .3 * residual


def verify_inference_prefix(wrapper, row, speaker):
    """Compare teacher-forcing prefix to the installed native generation code."""
    import torch
    class CapturedPrefix(Exception):
        pass
    captured = []
    def capture(module, positional, keywords):
        captured.append(keywords["inputs_embeds"].detach())
        raise CapturedPrefix()
    model = wrapper.model
    model.eval()
    hook = model.talker.register_forward_pre_hook(capture, with_kwargs=True)
    try:
        with torch.no_grad(), torch.autocast("cuda",dtype=torch.bfloat16):
            try:
                model.generate(input_ids=[torch.tensor([row["text_ids"]],device=model.device)],
                    languages=["Russian"], speakers=[None], non_streaming_mode=True,
                    voice_clone_prompt={"ref_spk_embedding":[speaker],"ref_code":None,
                                        "x_vector_only_mode":[True],"icl_mode":[False]},
                    max_new_tokens=2)
            except CapturedPrefix:
                pass
            embeddings, _, _, offset = build_inputs(model,row["text_ids"],row["audio_codes"],speaker)
    finally:
        hook.remove()
    if len(captured)!=1 or captured[0].shape!=embeddings[:,:offset].shape:
        raise RuntimeError("Training/inference prefix shape mismatch")
    # Batched vs separate BF16 projection matmuls may round at a half-ULP boundary.
    torch.testing.assert_close(captured[0].float(),embeddings[:,:offset].float(),rtol=.008,atol=.001)
    print("CHECK: training prefix matches native Russian inference",flush=True)


def save_checkpoint(wrapper, base, destination, speaker, run):
    import torch
    from safetensors.torch import save_file
    destination.mkdir(exist_ok=True)
    # Copy only inference assets. Do not duplicate the base weight file or caches.
    for name in ("merges.txt", "vocab.json", "tokenizer_config.json", "preprocessor_config.json", "generation_config.json"):
        shutil.copyfile(base/name, destination/name)
    if not (destination/"speech_tokenizer").exists():
        shutil.copytree(base/"speech_tokenizer", destination/"speech_tokenizer")
    # Preserve the snapshot's compatible nested config format. Transformers 5.x
    # to_dict injects dtype into the strict speaker-encoder dataclass.
    config = checkpoint_config(json.loads((base/"config.json").read_text(encoding="utf8")),
                               wrapper.model.config.talker_config.codec_eos_token_id)
    (destination/"config.json").write_text(json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    state = {k:v.detach().to(device="cpu",dtype=torch.bfloat16).contiguous() for k,v in wrapper.model.state_dict().items()
             if not k.startswith("speaker_encoder")}
    state["talker.model.codec_embedding.weight"][3000] = speaker.detach().cpu().to(torch.bfloat16)
    temporary = destination/"model.safetensors.tmp"
    save_file(state, str(temporary), metadata={"format":"pt"})
    temporary.replace(destination/"model.safetensors")
    (destination/"training_run.json").write_text(json.dumps(run,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


def main():
    sys.stdout.reconfigure(encoding="utf8")
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--epochs",type=int,default=3)
    p.add_argument("--lr",type=float,default=1e-6)
    p.add_argument("--train-last-layers",type=int,default=4)
    p.add_argument("--accumulate",type=int,default=4)
    p.add_argument("--patience",type=int,default=3)
    p.add_argument("--seed",type=int,default=20261115)
    args=p.parse_args()
    if not 1 <= args.epochs <= 30 or not 0 < args.lr <= 2e-5 or args.accumulate < 1:
        raise ValueError("Choose bounded pilot training settings")
    splits, reference=read_splits(args.dataset)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    import os
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSTokenizer,Qwen3TTSModel
    torch.set_num_threads(4)
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("Pilot requires a BF16-capable CUDA GPU")
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed);torch.cuda.manual_seed_all(args.seed)
    base=Path(snapshot_download(BASE_ID,local_files_only=True))
    run={"base":str(base),"dataset":str(args.dataset.resolve()),"reference":str(reference),
         "split_counts":{k:len(v) for k,v in splits.items()},"seed":args.seed,
         "epochs_limit":args.epochs,"learning_rate":args.lr,"gradient_accumulation":args.accumulate,
         "train_last_layers":args.train_last_layers,"speaker":"jarvis_pilot",
         "torch":torch.__version__,"gpu":torch.cuda.get_device_name(),"status":"preparing",
         "method":"partial-parameter SFT; frozen lower layers/text embeddings/code predictor/speaker encoder; FP32 master weights; BF16 autocast",
         "selection":"lowest validation loss; test not used in training or checkpoint selection",
         "source":"https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning",
         "script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    def status():
        (output/"run.json").write_text(json.dumps(run,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    status()
    (output/"training_script.py").write_bytes(Path(__file__).read_bytes())
    tokenizer=Qwen3TTSTokenizer.from_pretrained(str(base/"speech_tokenizer"),device_map="cuda:0")
    # The test split stays untouched until the independent evaluation stage.
    for split in ("train","validation"):
        for index,row in enumerate(splits[split]):
            info=sf.info(row["audio"])
            if info.samplerate!=24000 or info.channels!=1 or not 2 <= info.duration <= 25:
                raise ValueError("Training audio must be mono 24kHz, 2–25s")
            with torch.inference_mode():
                codes=tokenizer.encode(row["audio"]).audio_codes[0]
            row["audio_codes"]=codes.cpu().tolist()
            print(f"ENCODE {split} {index+1}/{len(splits[split])}",flush=True)
        (output/f"{split}_with_codes.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in splits[split]),encoding="utf8")
    del tokenizer
    import gc
    gc.collect();torch.cuda.empty_cache()
    wrapper=Qwen3TTSModel.from_pretrained(str(base),device_map="cuda:0",dtype=torch.bfloat16,attn_implementation="sdpa",local_files_only=True)
    model=wrapper.model
    normalize_config(model.config)
    model.requires_grad_(False)
    count=len(model.talker.model.layers)
    if not 1 <= args.train_last_layers <= count:
        raise ValueError("Invalid number of trainable layers")
    modules=list(model.talker.model.layers[-args.train_last_layers:])+[
        model.talker.model.norm,model.talker.text_projection,model.talker.codec_head,
        model.talker.model.codec_embedding]
    for module in modules:
        module.float();module.requires_grad_(True)
    trainable=[v for v in model.parameters() if v.requires_grad]
    run["trainable_parameters"]=sum(v.numel() for v in trainable)
    run["all_parameters"]=sum(v.numel() for v in model.parameters())
    print("PARAMETERS",run["trainable_parameters"],"/",run["all_parameters"],flush=True)
    audio,rate=sf.read(reference,dtype="float32")
    if rate!=24000 or audio.ndim!=1:raise ValueError("Reference must be mono 24kHz")
    with torch.inference_mode():
        speaker=model.extract_speaker_embedding(audio,rate).detach().clone()
    # Cloning an inference tensor outside inference_mode makes it safe for autograd.
    speaker=speaker.clone()
    for split in ("train","validation"):
        for row in splits[split]:
            row["text_ids"]=wrapper.processor(text=f"<|im_start|>assistant\n{row['text']}<|im_end|>\n<|im_start|>assistant\n",return_tensors="pt")["input_ids"][0].tolist()
    verify_inference_prefix(wrapper,splits["train"][0],speaker)
    def validation():
        model.eval()
        with torch.no_grad(),torch.autocast("cuda",dtype=torch.bfloat16):
            losses=[float(loss_for(model,row,speaker)) for row in splits["validation"]]
        value=sum(losses)/len(losses)
        if not math.isfinite(value):raise RuntimeError("Non-finite validation loss")
        return value
    baseline=validation();run.update(status="training",baseline_validation_loss=baseline)
    print("BASELINE VALIDATION",baseline,flush=True);status()
    optimizer=torch.optim.AdamW(trainable,lr=args.lr,weight_decay=.01,foreach=False)
    best=math.inf;bad=0;updates=0;started=time.monotonic()
    try:
        for epoch in range(args.epochs):
            model.train();model.speaker_encoder.eval()
            order=list(splits["train"]);random.shuffle(order)
            losses=[];optimizer.zero_grad(set_to_none=True)
            for index,row in enumerate(order):
                # Normalize each group including a possibly short final group.
                group_size=min(args.accumulate,len(order)-(index//args.accumulate)*args.accumulate)
                with torch.autocast("cuda",dtype=torch.bfloat16):
                    raw_loss=loss_for(model,row,speaker)
                    loss=raw_loss/group_size
                if not torch.isfinite(loss):raise RuntimeError("Non-finite training loss")
                loss.backward();losses.append(float(raw_loss.detach()))
                if (index+1)%args.accumulate==0 or index+1==len(order):
                    norm=torch.nn.utils.clip_grad_norm_(trainable,1.0,error_if_nonfinite=True)
                    optimizer.step();optimizer.zero_grad(set_to_none=True);updates+=1
                    print(f"TRAIN epoch={epoch+1} sample={index+1}/{len(order)} loss={losses[-1]:.4f} grad={norm:.4f}",flush=True)
            value=validation()
            metrics={"epoch":epoch+1,"updates":updates,"train_loss":sum(losses)/len(losses),
                     "validation_loss":value,"elapsed_seconds":round(time.monotonic()-started,2),
                     "peak_vram_gb":round(torch.cuda.max_memory_allocated()/2**30,3)}
            with (output/"metrics.jsonl").open("a",encoding="utf8") as f:f.write(json.dumps(metrics)+"\n")
            print("EPOCH",json.dumps(metrics),flush=True)
            if value < best-1e-4:
                best=value;bad=0
                run.update(best_epoch=epoch+1,best_validation_loss=best,**{"updates":updates})
                save_checkpoint(wrapper,base,output/"candidate",speaker,run)
            else:bad+=1
            status()
            if bad>=args.patience:
                print("EARLY STOP: validation stopped improving",flush=True);break
        run.update(status="complete",elapsed_seconds=round(time.monotonic()-started,2),updates=updates,
                   improves_validation_over_base=bool(best<baseline),
                   activation="Not activated. Human A/B listening required; one validation phrase is too small to prove quality.")
        status()
        checkpoint_meta=output/"candidate/training_run.json"
        selected=json.loads(checkpoint_meta.read_text(encoding="utf8"))
        selected.update(status="selected_checkpoint",parent_run_status="complete",
                        selected_epoch=selected["best_epoch"],checkpoint_updates=selected["updates"])
        checkpoint_meta.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    except BaseException as error:
        run.update(status="failed",error=f"{type(error).__name__}: {error}");status();raise
    print(json.dumps(run,ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":main()
