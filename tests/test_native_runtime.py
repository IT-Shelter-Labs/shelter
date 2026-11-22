import io
import unittest
from unittest.mock import patch
import numpy as np
import native_runtime as native
import audio_io
import audio
import media


class MediaSelection(unittest.TestCase):
    def test_youtube_with_music_metadata_is_not_a_music_player(self):
        video = {"source":"firefox.exe","kind":"music","title":"Видео","artist":"Автор","playing":True}
        self.assertIsNone(media._select([video],music_only=True))
        self.assertEqual(media._select([video])["title"],"Видео")

    def test_music_player_is_selected_even_when_browser_is_current(self):
        items = [{"source":"chrome.exe","kind":"music","playing":True,"current":True},
                 {"source":"Spotify.exe","kind":"music","playing":False}]
        self.assertEqual(media._select(items,True)["app"],"Spotify")

    def test_controls_keep_exact_source_and_do_not_touch_current_browser(self):
        with patch.object(media.native_runtime,"media_control",return_value=True) as control:
            self.assertTrue(media.control("pause","Spotify.exe"))
        control.assert_called_once_with("pause","Spotify.exe")

    def test_media_buttons_do_not_run_through_the_language_model(self):
        from pathlib import Path
        code = (Path(__file__).resolve().parent.parent / "app/src/components/home/MusicCard.svelte").read_text(encoding="utf8")
        self.assertNotIn("api.ask(",code)


class WaveIO(unittest.TestCase):
    def test_wav_roundtrip_preserves_pcm_and_float_amplitude(self):
        for dtype in (np.int16,np.int32,np.float32):
            x = np.array([[0,.2],[-.5,.7]],np.float32)
            if np.issubdtype(dtype,np.integer): x = (x * np.iinfo(dtype).max).astype(dtype)
            buf = io.BytesIO(); audio_io.write(buf,24000,x); buf.seek(0)
            rate,y = audio_io.read(buf)
            self.assertEqual(rate,24000); np.testing.assert_array_equal(x,y)


@unittest.skipUnless(native.LIBRARY,"compile native/ before running native integration tests")
class NativeAudio(unittest.TestCase):
    def test_resampler_matches_previous_filter_including_boundaries(self):
        from scipy.signal import resample_poly
        rng = np.random.default_rng(71)
        for size in (0,1,17,8192):
            x = rng.uniform(-1,1,size).astype(np.float32)
            for up,down in ((1,1),(1,2),(1,3),(160,441),(100,112),(3,2)):
                np.testing.assert_allclose(native.resample_poly(x,up,down),resample_poly(x,up,down),atol=2e-6,rtol=2e-6)

    def test_downsampling_rejects_frequencies_above_new_nyquist(self):
        t = np.arange(32000,dtype=np.float32)/32000
        x = np.sin(2*np.pi*12000*t).astype(np.float32)
        y = native.resample_poly(x,1,2)[30:-30]
        self.assertLess(float(np.sqrt(np.mean(y*y))),.003)

    def test_ring_accepts_blocks_bigger_than_ring_and_preserves_windows(self):
        ring = native.Ring(7)
        ring.write(np.arange(20,dtype=np.float32))
        np.testing.assert_array_equal(ring.read(7),np.arange(13,20,dtype=np.float32))
        ring.write(np.array([20,21],np.float32))
        np.testing.assert_array_equal(ring.read(4),np.array([18,19,20,21],np.float32))

    def test_microphone_ring_does_not_duplicate_detector_queue_when_disabled(self):
        cap = audio.AudioCapture(10,detector_enabled=False)
        cap._callback(np.arange(50,dtype=np.float32).reshape(-1,1),50,None,False)
        np.testing.assert_array_equal(cap.get_window(2,0),np.arange(30,50,dtype=np.float32))
        self.assertTrue(cap.det_queue.empty()); self.assertEqual(cap.vosk_queue.qsize(),1)
