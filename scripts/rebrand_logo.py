#!/usr/bin/env python3
"""Replace every Open WebUI logo/favicon/splash asset with a custom image.

Usage:
    python3 scripts/rebrand_logo.py path/to/logo.png [--dark path/to/logo-dark.png]

The source image should be square (it is center-cropped if not). Requires Pillow.
"""

import argparse
import base64
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

# Directories that hold a copy of the branded assets. The frontend build copies
# static/ into build/, and the backend serves backend/open_webui/static/ directly.
TARGET_DIRS = [ROOT / "static" / "static", ROOT / "backend" / "open_webui" / "static"]

# filename -> pixel size
PNG_ASSETS = {
    "favicon.png": 500,
    "favicon-96x96.png": 96,
    "apple-touch-icon.png": 180,
    "web-app-manifest-192x192.png": 192,
    "web-app-manifest-512x512.png": 512,
    "splash.png": 500,
    "logo.png": 500,
}
DARK_ASSETS = {"favicon-dark.png": 500, "splash-dark.png": 500}


def square(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def resized(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def save_png(img: Image.Image, path: Path, size: int) -> None:
    resized(img, size).save(path, "PNG", optimize=True)


def svg_wrapper(img: Image.Image, size: int = 128) -> str:
    buf = io.BytesIO()
    resized(img, size).save(buf, "PNG", optimize=True)
    data = base64.b64encode(buf.getvalue()).decode()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
        f'<image width="{size}" height="{size}" href="data:image/png;base64,{data}"/></svg>\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="square logo image (png/jpg/webp)")
    parser.add_argument("--dark", type=Path, help="optional variant for dark mode")
    args = parser.parse_args()

    light = square(Image.open(args.image))
    # Without a dark variant we reuse the light one. The UI inverts the image
    # when a *-dark.png is missing, which would ruin a full-color logo.
    dark = square(Image.open(args.dark)) if args.dark else light

    for target in TARGET_DIRS:
        target.mkdir(parents=True, exist_ok=True)
        for name, size in PNG_ASSETS.items():
            save_png(light, target / name, size)
        for name, size in DARK_ASSETS.items():
            save_png(dark, target / name, size)
        resized(light, 48).save(target / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
        (target / "favicon.svg").write_text(svg_wrapper(light))

    save_png(light, ROOT / "static" / "favicon.png", 500)
    swagger = ROOT / "backend" / "open_webui" / "static" / "swagger-ui" / "favicon.png"
    if swagger.parent.exists():
        save_png(light, swagger, 32)

    print(f"Rebranded {len(TARGET_DIRS)} asset folders from {args.image}")


if __name__ == "__main__":
    main()
