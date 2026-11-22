"""WAV I/O without importing the scientific computing stack at startup."""
def read(path):
    import soundfile as sf
    with sf.SoundFile(path) as stream:
        dtype = "int16" if stream.subtype in ("PCM_16","PCM_U8","PCM_S8") else "int32" if stream.subtype.startswith("PCM_") else "float32"
        return stream.samplerate,stream.read(dtype=dtype)

def write(path, rate, samples):
    import numpy as np
    import soundfile as sf
    data = np.asarray(samples)
    subtype = "PCM_16" if data.dtype == np.int16 else "PCM_32" if data.dtype == np.int32 else "FLOAT"
    sf.write(path,data,rate,subtype=subtype,format="WAV")
