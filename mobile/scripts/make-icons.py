"""Draw Nodly's app icons from the logo in the design handoff (design/2026-09-26-nodly-handoff).

The logo, on a 40x40 grid: a green rounded square (radius 12), a cream circle (20, 14.5, r 4.6)
and a cream smile, the quadratic curve M11 23.5 Q20 31.5 29 23.5 stroked 3.4 wide with round
caps. Shapes are drawn 4x larger and scaled down, for smooth edges.

    python scripts/make-icons.py      (from mobile/, with Pillow installed)
"""

from pathlib import Path

from PIL import Image, ImageDraw

GREEN = (0x2D, 0x6A, 0x4F, 255)
CREAM = (0xFA, 0xF6, 0xEE, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)
OUT = Path(__file__).resolve().parent.parent / "assets" / "images"
SUPER = 4


def draw_glyph(draw: ImageDraw.ImageDraw, scale: float, dx: float, dy: float, color) -> None:
    """The face: head and smile, from 40-unit logo coordinates."""

    def p(x: float, y: float) -> tuple[float, float]:
        return (dx + x * scale, dy + y * scale)

    cx, cy = p(20, 14.5)
    r = 4.6 * scale
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    # The smile: a round brush dragged along the curve (Pillow's wide lines leave jagged seams),
    # which also gives the round caps.
    half = 3.4 * scale / 2
    steps = 2000
    for i in range(steps + 1):
        t = i / steps
        x, y = p(
            (1 - t) ** 2 * 11 + 2 * (1 - t) * t * 20 + t**2 * 29,
            (1 - t) ** 2 * 23.5 + 2 * (1 - t) * t * 31.5 + t**2 * 23.5,
        )
        draw.ellipse((x - half, y - half, x + half, y + half), fill=color)


def render(size: int, background, glyph_color, logo_px: float, rounded: bool = False) -> Image.Image:
    """A size x size image with the logo's 40-unit grid mapped onto logo_px pixels, centred."""
    big = size * SUPER
    image = Image.new("RGBA", (big, big), background if not rounded else CLEAR)
    draw = ImageDraw.Draw(image)
    scale = logo_px * SUPER / 40
    offset = (big - logo_px * SUPER) / 2
    if rounded:
        box = (offset, offset, offset + 40 * scale, offset + 40 * scale)
        draw.rounded_rectangle(box, radius=12 * scale, fill=GREEN)
    draw_glyph(draw, scale, offset, offset, glyph_color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    # iOS / store icon: full bleed (the OS rounds the corners).
    render(1024, GREEN, CREAM, 1024).save(OUT / "icon.png")
    # Android adaptive icon: 108 dp canvas, 72 dp visible, so the logo grid spans 72/108.
    visible = 1024 * 72 / 108
    render(1024, GREEN, GREEN, visible).save(OUT / "android-icon-background.png")
    render(1024, CLEAR, CREAM, visible).save(OUT / "android-icon-foreground.png")
    render(1024, CLEAR, WHITE, visible).save(OUT / "android-icon-monochrome.png")
    # Splash: the logo itself, rounded square and all.
    render(512, CLEAR, CREAM, 512, rounded=True).save(OUT / "splash-icon.png")
    print(f"wrote icons to {OUT}")


if __name__ == "__main__":
    main()
