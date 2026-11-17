"""Turn the logo image into the Windows icon used by the app window, taskbar and Phoebix.exe.

Usage:  python tools/make_icon.py [source image]      (default: assets/phoebix.png)
Writes: assets/phoebix.ico (16-256 px) and assets/phoebix-64.png (window icon fallback).

The square logo has the word "Pharmacy" under the symbol. Text is unreadable at taskbar sizes, so the
small sizes (16-48 px) use only the symbol; the large sizes keep the full logo.
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)
SMALL = 48  # sizes up to this use the symbol-only crop


def square(image):
    w, h = image.size
    side = min(w, h)
    return image.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))


def symbol_crop(image):
    """Top ~78% of the logo holds the symbol; take a centred square of it (drops the caption)."""
    w, h = image.size
    side = int(h * 0.70)
    top = int(h * 0.10)
    left = (w - side) // 2
    return image.crop((left, top, left + side, top + side))


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "phoebix.png"
    if not source.is_file():
        sys.exit(f"Logo not found: {source}\nSave the logo image there (PNG or JPG) and run this again.")
    logo = square(Image.open(source).convert("RGBA"))
    symbol = symbol_crop(logo)
    frames = [(symbol if size <= SMALL else logo).resize((size, size), Image.LANCZOS) for size in SIZES]
    ASSETS.mkdir(exist_ok=True)
    ico = ASSETS / "phoebix.ico"
    frames[-1].save(ico, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    symbol.resize((64, 64), Image.LANCZOS).save(ASSETS / "phoebix-64.png")
    print(f"Wrote {ico} and {ASSETS / 'phoebix-64.png'}")


if __name__ == "__main__":
    main()
