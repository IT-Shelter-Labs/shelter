"""Export SFT talker weights while retaining the original Base clone interface.

The frozen speaker encoder and unused speaker-code row come from the original
local Base snapshot. No training or downloads; output must be a new directory.
This is an experimental export, not the official CustomVoice export recipe.
"""
import argparse
import json
from pathlib import Path
import shutil


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    args=p.parse_args()
    run=json.loads((args.run/'run.json').read_text(encoding='utf8'))
    if run['status']!='complete':raise RuntimeError('Incomplete training run')
    base=Path(run['base']);candidate=args.run/'candidate';out=args.run/'candidate_clone'
    out.mkdir(exist_ok=False)
    from safetensors import safe_open
    from safetensors.torch import load_file,save_file
    state=load_file(str(candidate/'model.safetensors'))
    with safe_open(str(base/'model.safetensors'),framework='pt',device='cpu') as original:
        for key in original.keys():
            if key.startswith('speaker_encoder'):
                state[key]=original.get_tensor(key)
        state['talker.model.codec_embedding.weight'][3000]=original.get_tensor('talker.model.codec_embedding.weight')[3000]
    save_file(state,str(out/'model.safetensors'),metadata={'format':'pt'})
    config=json.loads((base/'config.json').read_text(encoding='utf8'))
    config['talker_config']['codec_eos_token_id']=config['talker_config'].get('codec_eos_id',2150)
    (out/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    for name in ('merges.txt','vocab.json','tokenizer_config.json','preprocessor_config.json','generation_config.json'):
        shutil.copyfile(base/name,out/name)
    shutil.copytree(base/'speech_tokenizer',out/'speech_tokenizer')
    (out/'export.json').write_text(json.dumps({'run':str(args.run.resolve()),'selected_epoch':run['best_epoch'],
        'method':'Retain Base ICL inference; restore only frozen speaker encoder and unused code row 3000. Adapted talker weights retained.',
        'activated':False},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Exported experimental Base clone interface:',out)


if __name__=='__main__':main()
