# AgriLens

(कृषि लेन्स) — offline Nepali farming assistant

AgriLens is an offline, Nepali-first farming assistant that runs Gemma 4 locally through Ollama to help farmers check plant problems, read pesticide and fertilizer labels, question documents, follow summarized agriculture news, and chat with spoken answers, all from a simple web page on their own laptop or phone.

## Third-Party Licenses

AgriLens is licensed under the MIT License. This license applies to the AgriLens project code owned by The 127.

Third-party software, libraries, AI models, datasets, and external resources used by AgriLens are subject to their respective licenses and terms of use. In particular, the Gemma model and Ollama are governed by their applicable terms. The AgriLens MIT License does not replace or override those terms.

Users and contributors should review and comply with the applicable terms for third-party components.

## Agricultural Safety Disclaimer

AgriLens provides AI-generated agricultural information for informational purposes only. Its responses may be inaccurate, incomplete, or outdated and should not be treated as a substitute for qualified agricultural advice. Always verify pesticide and fertilizer labels and follow the manufacturer's instructions and applicable local regulations before use.

## Run

```bash
ollama pull gemma4:e4b            # once (Ollama >= 0.20)
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt 
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 (phone on same Wi-Fi: http://<laptop-ip>:8000).
Check the model: `curl localhost:8000/api/health`.

## Speed settings (Ollama side — set before `ollama serve`)

```
OLLAMA_FLASH_ATTENTION=1   OLLAMA_KV_CACHE_TYPE=q8_0   OLLAMA_NUM_PARALLEL=1
```

AgriLens env: `AGRILENS_MODEL` `AGRILENS_NUM_CTX=8192` (keep constant!) `AGRILENS_KEEP_ALIVE=30m` `AGRILENS_THINK=0` `AGRILENS_IMG_MAX=1280` `AGRILENS_LABEL_IMG_MAX=1600`.

## Nepali voice

1. Works immediately: browser voice. Needs a Nepali voice in the device's text-to-speech settings (falls back to a Hindi voice with a notice).
2. Offline neural voice (recommended for farmers' laptops): `pip install piper-tts && python scripts/get_voice.py`, restart. Test:
   `echo "नमस्कार किसान दाइ" | python -m piper -m data/voices/ne_NP-google-medium.onnx -f /tmp/t.wav`
   If your Piper version has other flags, set `AGRILENS_TTS_CMD` (see backend/tts.py).
3. Mic (voice input) uses the browser's speech recognition: Chrome only, needs internet, and https or localhost (hidden on http://<ip>).

## News

Edit `news_sources.json` (set `"enabled": true` + a real `url`). Check a source first:
`python -m backend.news https://example.com/feed`. News is fetched only when the user presses the button; summaries are cached and work offline.

## Data

Everything (chats, scans, docs, news) is in `data/agrilens.db` + `data/img/`. Delete the folder to reset.
