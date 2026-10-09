"""Optional OFFLINE Nepali voice via Piper. The browser voice is used when this is not installed."""
import asyncio, hashlib, os, shlex, sys
from . import config as C

# stdin = text, {model}/{out} are filled in. Override if your Piper version has different flags.
CMD = os.getenv("AGRILENS_TTS_CMD", f"{shlex.quote(sys.executable)} -m piper -m {{model}} -f {{out}}")


def available() -> bool:
    if not C.TTS_MODEL.exists():
        return False
    try:
        import piper  # noqa: F401  (only checking it is installed)
        return True
    except ImportError:
        return False


async def synth(text: str):
    text = text.strip()[:600]
    out = C.DATA / "tts" / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".wav")
    if out.exists():
        return out
    cmd = CMD.format(model=shlex.quote(str(C.TTS_MODEL)), out=shlex.quote(str(out)))
    p = await asyncio.create_subprocess_shell(cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(p.communicate(text.encode()), 60)
    if p.returncode != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise RuntimeError(err.decode("utf-8", "ignore")[-300:])
    return out
