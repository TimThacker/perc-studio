"""Build the app icon: the CURENT mark (assets/branding/curent_icon.png)
centered on an opaque white square, as a multi-size Windows .ico.

Writes assets/branding/app_icon.ico (window, taskbar, desktop shortcut and
installer icon) and assets/branding/app_icon.png (a 256 px preview). Run
again only if the source mark changes; both outputs are committed.

    uv run --group packaging python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BRANDING = Path(__file__).resolve().parent.parent / "assets" / "branding"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
# White margin around the mark, as a fraction of the square's side. Small
# sizes get less margin so the mark stays legible at 16-24 px.
PADDING = {16: 0.02, 20: 0.03, 24: 0.04, 32: 0.05}
DEFAULT_PADDING = 0.07


def render(mark: Image.Image, size: int) -> Image.Image:
    padding = PADDING.get(size, DEFAULT_PADDING)
    inner = max(1, round(size * (1 - 2 * padding)))
    # Downscale in one high-quality step from the 512 px source.
    scaled = mark.resize((inner, inner), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    offset = (size - inner) // 2
    square.alpha_composite(scaled, (offset, offset))
    return square


def main() -> None:
    mark = Image.open(BRANDING / "curent_icon.png").convert("RGBA")
    bbox = mark.getbbox()  # crop transparent margin so padding is exact
    mark = mark.crop(bbox)
    side = max(mark.size)
    squared = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    squared.alpha_composite(mark, ((side - mark.width) // 2, (side - mark.height) // 2))

    images = [render(squared, size) for size in SIZES]
    largest = images[-1]
    largest.save(BRANDING / "app_icon.ico", sizes=[(s, s) for s in SIZES],
                 append_images=images[:-1])
    largest.convert("RGB").save(BRANDING / "app_icon.png")
    print(f"wrote {BRANDING / 'app_icon.ico'} ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
