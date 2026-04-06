import os
import tempfile
import time
import unittest
from unittest.mock import patch

from app import tts


class TestTTSCleanup(unittest.TestCase):
    def test_cleanup_expired_tts_files_removes_only_old_audio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_mp3 = os.path.join(tmpdir, "old.mp3")
            new_wav = os.path.join(tmpdir, "new.wav")
            keep_txt = os.path.join(tmpdir, "note.txt")

            for path in [old_mp3, new_wav, keep_txt]:
                with open(path, "wb") as f:
                    f.write(b"data")

            now = time.time()
            old_time = now - 7200
            os.utime(old_mp3, (old_time, old_time))

            with patch("app.tts.TTS_OUTPUT_DIR", tmpdir), patch("app.tts.TTS_FILE_TTL_SECONDS", 3600):
                result = tts.cleanup_expired_tts_files()

            self.assertEqual(result["deleted_count"], 1)
            self.assertFalse(os.path.exists(old_mp3))
            self.assertTrue(os.path.exists(new_wav))
            self.assertTrue(os.path.exists(keep_txt))


if __name__ == "__main__":
    unittest.main()
