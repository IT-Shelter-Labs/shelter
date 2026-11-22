"""Export only trainable SFT tensors for per-persona runtime activation."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    run=json.loads((args.run/'run.json').read_text(encoding='utf8'))
    if run['status']!='complete':raise ValueError('Training incomplete')
    config=json.loads((Path(run['base'])/'config.json').read_text(encoding='utf8'))
    count=config['talker_config']['num_hidden_layers']
    first=count-run['train_last_layers']
    prefixes=tuple(f'talker.model.layers.{i}.' for i in range(first,count))+(
        'talker.model.norm.','talker.text_projection.','talker.codec_head.','talker.model.codec_embedding.')
    from safetensors import safe_open
    from safetensors.torch import save_file
    tensors={}
    with safe_open(str(args.run/'candidate_clone/model.safetensors'),framework='pt',device='cpu') as source:
        for key in source.keys():
            if key.startswith(prefixes):tensors[key]=source.get_tensor(key)
    if not tensors:raise ValueError('No adapter tensors found')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    file=out/'adapter.safetensors';save_file(tensors,str(file),metadata={'format':'pt'})
    meta={'name':'Jarvis '+args.run.name,'base_model':'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
          'base_revision':Path(run['base']).name,'parameters':sorted(tensors),
          'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
          'sampling':{'temperature':.7,'top_p':.9,'chunk':12},
          'source_run':str(args.run.resolve()),'best_epoch':run['best_epoch']}
    (out/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Exported adapter:',round(file.stat().st_size/1024**2,1),'MiB',out)


if __name__=='__main__':main()
