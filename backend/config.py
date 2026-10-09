"""All tunables in one place. Override with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("AGRILENS_DATA", ROOT / "data"))
for sub in ("img", "tts", "voices"):
    (DATA / sub).mkdir(parents=True, exist_ok=True)

OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("AGRILENS_MODEL", "gemma4:e4b")

# IMPORTANT: keep num_ctx constant. Ollama reloads the model whenever it changes between requests.
NUM_CTX = int(os.getenv("AGRILENS_NUM_CTX", "8192"))
KEEP_ALIVE = os.getenv("AGRILENS_KEEP_ALIVE", "30m")   # keep model in RAM between requests
THINK = os.getenv("AGRILENS_THINK", "0") == "1"        # thinking mode = slower; off by default

MAX_UPLOAD = int(os.getenv("AGRILENS_MAX_UPLOAD_MB", "25")) * 1024 * 1024
IMG_MAX = int(os.getenv("AGRILENS_IMG_MAX", "1280"))           # longest side sent to the model
LABEL_IMG_MAX = int(os.getenv("AGRILENS_LABEL_IMG_MAX", "1600"))  # labels need more pixels (small print)
OCR_MAX_PAGES = int(os.getenv("AGRILENS_OCR_MAX_PAGES", "8"))

TTS_MODEL = Path(os.getenv("AGRILENS_TTS_MODEL", DATA / "voices" / "ne_NP-google-medium.onnx"))
NEWS_SOURCES = Path(os.getenv("AGRILENS_NEWS_SOURCES", ROOT / "news_sources.json"))
