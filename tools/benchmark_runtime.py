"""Reproducible import/RSS and audio resampler comparison, excluding model weights."""
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CHILD = '''import time,json,psutil
started=time.perf_counter()
{reference}
import main,numpy as np,native_runtime as n
x=np.random.default_rng(42).normal(0,.1,8192).astype(np.float32)
f={function}
f(x,1,2)
times=[]
for _ in range(100):
 t=time.perf_counter();f(x,1,2);times.append(time.perf_counter()-t)
import statistics
print(json.dumps(dict(import_seconds=time.perf_counter()-started,rss_mib=psutil.Process().memory_info().rss/2**20,resample_us=statistics.median(times)*1e6,native=bool(n.LIBRARY))))
'''

def main():
    cases = {}
    for name,reference,function in [("previous_scipy","from scipy.signal import resample_poly; from scipy.io import wavfile","resample_poly"),
                                    ("rust","","n.resample_poly")]:
        rows=[]
        for _ in range(3):
            env={**os.environ,"JARVIS_NATIVE":"0" if name=="previous_scipy" else "1"}
            out=subprocess.check_output([sys.executable,"-c",CHILD.format(reference=reference,function=function)],cwd=ROOT,env=env,text=True)
            rows.append(json.loads(out))
        cases[name]={key:statistics.median(row[key] for row in rows) for key in ("import_seconds","rss_mib","resample_us")}
    print(json.dumps({"scope":"Python core imports + 8192 float32 samples, 32kHz to 16kHz; no ASR/LLM/TTS model weights", "cases":cases},indent=2))

if __name__ == "__main__": main()
