"""Download the Nepali Piper voice (~60 MB) once. After that, voice works with no internet.
Usage:  pip install piper-tts && python scripts/get_voice.py
If you get a 404, open https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md (or rhasspy/piper VOICES.md),
find the Nepali (ne_NP) voice and change BASE/NAME below."""
import sys, urllib.request
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ne/ne_NP/google/medium/"
NAME = "ne_NP-google-medium"
out = Path(__file__).resolve().parent.parent / "data" / "voices"
out.mkdir(parents=True, exist_ok=True)
for ext in (".onnx", ".onnx.json"):
    dest = out / (NAME + ext)
    if dest.exists():
        print("have", dest.name); continue
    print("downloading", NAME + ext)
    try:
        urllib.request.urlretrieve(BASE + NAME + ext, dest)
    except Exception as e:
        dest.unlink(missing_ok=True); sys.exit(f"failed: {e}")
print("done ->", out)
