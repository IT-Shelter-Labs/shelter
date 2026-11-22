import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


builder=module('build_jarvis_corpus')
checker=module('check_jarvis_corpus')


class CorpusPlan(unittest.TestCase):
    def setUp(self):
        if (builder.PACK/'source.tsv').is_file(): return
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path=Path(folder.name)
        words='альфа бета гамма дельта эпсилон дзета эта тета йота каппа лямбда мю ню кси омикрон пи ро сигма тау ипсилон'.split()
        pairs=[(a,b) for a in words for b in words][:260]
        (path/'source.tsv').write_text('category|text|notes\n'+''.join(f'{"pilot" if i<20 else "neutral"}|Синтетическая проверка {a} {b}.|\n' for i,(a,b) in enumerate(pairs)),encoding='utf8')
        context=patch.object(builder,'PACK',path);context.start();self.addCleanup(context.stop)

    def test_manifest_is_unique_bounded_and_transcripts_are_tag_free(self):
        rows=builder.build()
        self.assertEqual(len(rows),600)
        self.assertEqual(len({r['text'] for r in rows}),600)
        self.assertEqual(len({r['id'] for r in rows}),600)
        self.assertTrue(all(len(r['generation_text'])<=450 for r in rows))
        self.assertTrue(all(not any(c in r['text'] for c in '<>[]|') for r in rows))
        self.assertEqual([r['id'] for r in rows[:20]], [f'J{i:04d}' for i in range(1,21)])
        self.assertTrue(all(r['phase']=='pilot' for r in rows[:20]))
        self.assertEqual(builder.build(),rows)

    def test_related_families_never_cross_partitions(self):
        groups={}
        for row in builder.build():groups.setdefault(row['family'],set()).add(row['split'])
        self.assertTrue(all(len(s)==1 for s in groups.values()))
        self.assertEqual({r['split'] for r in builder.build()},{'train','validation','test'})

    def test_saved_manifest_matches_builder(self):
        if not (builder.PACK/'corpus.jsonl').is_file():
            self.skipTest('Optional personal corpus is not part of the public source tree')
        stored=[json.loads(line) for line in (builder.PACK/'corpus.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual(stored,builder.build())


class AudioPreparation(unittest.TestCase):
    def fixture(self,folder,decisions=None):
        rows=[{'id':ident,'split':split,'text':'Проверка записи завершена.'} for ident,split in
              [('J0001','train'),('J0002','train'),('J0003','test')]]
        (folder/'corpus.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf8')
        (folder/'audio_raw').mkdir()
        with (folder/'review.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['id','decision','actual_text','comment']);w.writeheader()
            w.writerows(dict(id=r['id'],decision=(decisions or {}).get(r['id'],'pending'),actual_text='',comment='') for r in rows)
        return rows

    def audio(self,path,hz=240):
        import numpy as np
        import soundfile as sf
        x=np.sin(np.arange(24000*3)/24000*2*np.pi*hz)*.15
        sf.write(path,x,24000,subtype='PCM_16')

    def test_pending_recordings_are_not_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder);self.audio(folder/'audio_raw/J0001.wav')
            rows,review,audit,unknown=checker.inspect(folder,folder/'audio_raw',folder/'review.csv')
            self.assertFalse(unknown)
            with self.assertRaisesRegex(ValueError,'Нет принятых'):
                checker.export(folder,rows,review,audit,folder/'prepared','J0001',22050)
            self.assertFalse((folder/'prepared').exists())

    def test_duplicate_and_silent_audio_are_flagged(self):
        import soundfile as sf
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder)
            self.audio(folder/'audio_raw/J0001.wav');self.audio(folder/'audio_raw/J0002.wav')
            sf.write(folder/'audio_raw/J0003.wav',np.zeros(24000*3),24000)
            rows,review,audit,unknown=checker.inspect(folder,folder/'audio_raw',folder/'review.csv')
            self.assertTrue(any(s.startswith('duplicate') for s in audit[0]['issues']))
            self.assertTrue(any(s.startswith('duplicate') for s in audit[1]['issues']))
            self.assertIn('silence_or_too_quiet',audit[2]['issues'])

    def test_export_retains_holdout_and_excludes_reference(self):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder,{f'J{i:04d}':'approved' for i in range(1,4)})
            for i in range(1,4):self.audio(folder/f'audio_raw/J{i:04d}.wav',200+i*100)
            rows,review,audit,unknown=checker.inspect(folder,folder/'audio_raw',folder/'review.csv')
            result=checker.export(folder,rows,review,audit,folder/'prepared','J0001',22050)
            self.assertEqual(result['counts'],{'train':1,'validation':0,'test':1})
            train=(folder/'prepared/train.csv').read_text(encoding='utf8')
            self.assertIn('J0002',train);self.assertNotIn('J0001',train);self.assertNotIn('J0003',train)
            self.assertIn('wavs/J0002.wav|',train)
            self.assertIn('J0003',(folder/'prepared/test.csv').read_text(encoding='utf8'))
            info=sf.info(folder/'prepared/wavs/J0002.wav')
            self.assertEqual(info.samplerate,22050);self.assertEqual(info.channels,1)
            self.assertTrue((folder/'audio_raw/J0002.wav').exists())
            with self.assertRaises(FileExistsError):checker.export(folder,rows,review,audit,folder/'prepared','J0001',22050)


if __name__=='__main__':unittest.main()
