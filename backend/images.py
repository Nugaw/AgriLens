"""One-pass image prep: rotate by EXIF, shrink, (optionally) boost contrast, measure quality."""
import io
from PIL import Image, ImageFilter, ImageOps, ImageStat


def prep(data: bytes, max_side=1280, enhance=False):
    """Return (jpeg_bytes, metrics). Smaller images = fewer vision tokens = faster model + faster upload."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    min_side = min(im.size)
    g = im.convert("L")
    if g.width > 800:
        g = g.resize((800, int(g.height * 800 / g.width)))
    metrics = {
        "min_side": min_side,
        "brightness": ImageStat.Stat(g).mean[0],
        "sharp": ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).var[0],
    }
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    if enhance and metrics["brightness"] < 110:
        im = ImageOps.autocontrast(im, cutoff=1)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue(), metrics


def issues(m: dict, blur_limit=40):
    out = []
    if m["min_side"] < 300:
        out.append("small")
    if m["brightness"] < 45:
        out.append("dark")
    if m["sharp"] < blur_limit:
        out.append("blurry")
    return out
