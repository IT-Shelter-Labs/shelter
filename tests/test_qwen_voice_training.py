import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("qwen_training",ROOT/"tools/finetune_jarvis_qwen.py")
training=importlib.util.module_from_spec(spec);spec.loader.exec_module(training)


class DatasetIsolation(unittest.TestCase):
    def make(self,folder):
        reference=folder/"reference.wav";reference.touch()
        for split in ("train","validation","test"):
            audio=folder/(split+".wav");audio.touch()
            row={"audio":str(audio),"ref_audio":str(reference),"text":"Проверочная фраза."}
            (folder/f"{split}_qwen.jsonl").write_text(json.dumps(row)+"\n",encoding="utf8")

    def test_shared_audio_across_train_and_test_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.make(folder)
            (folder/"test_qwen.jsonl").write_bytes((folder/"train_qwen.jsonl").read_bytes())
            with self.assertRaisesRegex(ValueError,"Duplicate audio"):
                training.read_splits(folder)

    def test_reference_cannot_be_training_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.make(folder)
            path=folder/"train_qwen.jsonl";row=json.loads(path.read_text());row["audio"]=row["ref_audio"]
            path.write_text(json.dumps(row),encoding="utf8")
            with self.assertRaisesRegex(ValueError,"separate reference"):
                training.read_splits(folder)

    def test_audio_outside_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);folder=parent/"dataset";folder.mkdir();self.make(folder)
            outside=parent/"outside.wav";outside.touch()
            path=folder/"train_qwen.jsonl";row=json.loads(path.read_text());row["audio"]=str(outside)
            path.write_text(json.dumps(row),encoding="utf8")
            with self.assertRaisesRegex(ValueError,"inside"):
                training.read_splits(folder)

    def test_installed_snapshot_eos_alias_is_normalized_and_bounded(self):
        c=SimpleNamespace(talker_config=SimpleNamespace(codec_eos_id=2150,codec_eos_token_id=4198,vocab_size=3072))
        training.normalize_config(c);self.assertEqual(c.talker_config.codec_eos_token_id,2150)
        c.talker_config.codec_eos_id=4000
        with self.assertRaisesRegex(ValueError,"outside"):
            training.normalize_config(c)

    def test_export_keeps_strict_nested_schema_and_leaves_base_untouched(self):
        base={"tts_model_type":"base","talker_config":{"spk_id":{}},
              "speaker_encoder_config":{"enc_dim":1024,"sample_rate":24000}}
        result=training.checkpoint_config(base,2150)
        self.assertEqual(result['speaker_encoder_config'],base['speaker_encoder_config'])
        self.assertEqual(result['talker_config']['codec_eos_token_id'],2150)
        self.assertEqual(result['talker_config']['spk_id'],{'jarvis_pilot':3000})
        self.assertEqual(base['tts_model_type'],'base')
        self.assertEqual(base['talker_config']['spk_id'],{})


if __name__=="__main__":unittest.main()
