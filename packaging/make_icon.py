"""Generate the Macro2k application icon.

Draws the same brand mark the Hub header shows (three rounded tiles + an accent
plus) on a dark rounded-square app tile, and writes:

    packaging/app.ico   multi-resolution icon (16 … 256) — used by
                        ``apps_build.spec`` / ``runner_build.spec`` for the
                        ``.exe`` and by ``installer.iss`` for ``Setup.exe``
    packaging/app.png   256 px preview / source for any web or docs use

Every size is rendered independently at 8x and downsampled, so the 16 px frame
stays legible instead of being a blurry shrink of the 256 px art. Small frames
drop the tile padding and fatten the strokes (the usual icon "optical" pass).

Run (Pillow is the only dependency)::

    .venv\\Scripts\\python packaging/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

# ── palette (mirrors apps/web/shared/tokens.css) ─────────────────────────────
TILE_TOP = (32, 44, 62)       # tile gradient start  (lifted --ink)
TILE_BOTTOM = (15, 20, 28)    # tile gradient end
TILE_EDGE = (72, 92, 120)     # 1 px inner bevel so the tile reads on dark chrome
MARK = (244, 247, 251)        # --panel: the three squares
ACCENT = (86, 143, 255)       # --accent brightened for a dark background

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SS = 8  # supersample factor

HERE = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(HERE, "app.ico")
PNG_PATH = os.path.join(HERE, "app.png")


def _gradient_tile(px: int, radius: int) -> Image.Image:
    """A vertical-gradient rounded square, transparent outside the corners."""
    grad = Image.new("RGB", (1, px))
    for y in range(px):
        t = y / max(px - 1, 1)
        grad.putpixel((0, y), tuple(
            round(a + (b - a) * t) for a, b in zip(TILE_TOP, TILE_BOTTOM)
        ))
    tile = grad.resize((px, px), Image.NEAREST).convert("RGBA")

    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, px - 1, px - 1), radius, fill=255)
    tile.putalpha(mask)
    return tile


def _frame(size: int) -> Image.Image:
    """Render one square icon frame at ``size`` px."""
    px = size * SS
    small = size <= 32          # optical pass for the tiny frames

    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    # Full-bleed tile: squircle-ish on big frames, nearly square on tiny ones so
    # the corners don't eat the mark.
    radius = round(px * (0.16 if small else 0.215))
    img.alpha_composite(_gradient_tile(px, radius))

    edge = ImageDraw.Draw(img)
    edge.rounded_rectangle(
        (0, 0, px - 1, px - 1), radius,
        outline=TILE_EDGE + (110,), width=max(1, round(px * 0.006)),
    )

    # The mark lives on a 24x24 grid (identical to the inline SVG in the Hub).
    inset = px * (0.085 if small else 0.155)
    unit = (px - inset * 2) / 24.0

    def U(v: float) -> float:
        return inset + v * unit

    d = ImageDraw.Draw(img)
    box = 7.0
    sq_r = max(1, round(unit * (1.4 if small else 1.7)))
    for x, y in ((3, 3), (14, 3), (3, 14)):
        d.rounded_rectangle((U(x), U(y), U(x + box), U(y + box)), sq_r, fill=MARK)

    # Accent plus in the free quadrant. Thicker on tiny frames so it survives.
    t = unit * (3.1 if small else 2.7)
    cx, cy = U(17.5), U(17.5)
    bar_r = max(1, round(t * 0.35))
    d.rounded_rectangle((cx - t / 2, U(14), cx + t / 2, U(21)), bar_r, fill=ACCENT)
    d.rounded_rectangle((U(14), cy - t / 2, U(21), cy + t / 2), bar_r, fill=ACCENT)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    frames = [_frame(s) for s in SIZES]
    frames[-1].save(PNG_PATH, format="PNG")
    # Pillow writes every size handed to ``sizes`` from the base image, so pass
    # the pre-rendered frames via append_images to keep the optical pass.
    frames[-1].save(
        ICO_PATH, format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[:-1],
    )
    print(f"wrote {ICO_PATH} ({', '.join(f'{s}x{s}' for s in SIZES)})")
    print(f"wrote {PNG_PATH} (256x256)")


if __name__ == "__main__":
    main()
