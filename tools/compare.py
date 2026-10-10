"""Compare a CSS piece against its original image.

Usage:
    python3 tools/compare.py pieces/01-sun-and-hills

What it does:
    1. Renders the piece's index.html in headless Chromium at the original
       image's pixel size.
    2. Measures how far each rendered pixel's color is from the original's.
    3. Writes four files into the piece's compare/ folder:
         render.png   the CSS piece as the browser drew it
         diff.png     the render, faded, with mismatched pixels in red
         compare.png  original | render | diff, side by side
         score.json   the numbers printed at the end

How a pixel is judged:
    Color distance is the straight-line distance between two RGB colors
    (0 = identical, about 441 = black versus white). A pixel "matches" when
    that distance is at most COLOR_TOLERANCE.
"""

import json
import sys
from pathlib import Path

import numpy
from PIL import Image
from playwright.sync_api import sync_playwright

# Large enough to ignore compression noise and soft anti-aliased edges,
# small enough to catch a wrong color or a misplaced shape.
COLOR_TOLERANCE = 24

MISMATCH_HIGHLIGHT_COLOR = (220, 30, 60)

# The diff image shows the render washed out towards white so the red
# mismatch pixels stand out. 0.35 keeps 35% of the render's color.
DIFF_RENDER_OPACITY = 0.35

COMPARISON_SHEET_PANEL_SIZE = 600


def render_piece(piece_folder: Path, size_in_pixels: int,
                 screenshot_path: Path) -> None:
    """Screenshot the piece's .scene element at the given square size."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={
            "width": size_in_pixels,
            "height": size_in_pixels
        })
        # Ask for reduced motion so animated pieces hold still and every
        # run produces the same screenshot.
        page.emulate_media(reduced_motion="reduce")
        page.goto((piece_folder / "index.html").resolve().as_uri())
        page.locator(".scene").screenshot(path=str(screenshot_path))
        browser.close()


def find_original_image(piece_folder: Path) -> Path:
    """Return the piece's original image, whatever its file extension."""
    return next(piece_folder.glob("original.*"))


def measure_color_distance(original_image: Image.Image,
                           rendered_image: Image.Image) -> numpy.ndarray:
    """Return a grid holding the color distance at every pixel."""
    original_pixels = numpy.asarray(original_image, dtype=float)
    rendered_pixels = numpy.asarray(rendered_image, dtype=float)
    squared_channel_differences = (original_pixels - rendered_pixels)**2
    return numpy.sqrt(squared_channel_differences.sum(axis=-1))


def draw_diff_image(rendered_image: Image.Image,
                    pixel_is_mismatched: numpy.ndarray) -> Image.Image:
    """Fade the render towards white and paint mismatched pixels red."""
    rendered_pixels = numpy.asarray(rendered_image, dtype=float)
    white = 255
    faded_pixels = (rendered_pixels * DIFF_RENDER_OPACITY + white *
                    (1 - DIFF_RENDER_OPACITY)).astype(numpy.uint8)
    faded_pixels[pixel_is_mismatched] = MISMATCH_HIGHLIGHT_COLOR
    return Image.fromarray(faded_pixels)


def draw_comparison_sheet(panels: list[Image.Image]) -> Image.Image:
    """Place the given images in one row, each scaled to the same square."""
    panel_size = COMPARISON_SHEET_PANEL_SIZE
    sheet = Image.new("RGB", (panel_size * len(panels), panel_size))
    for panel_number, panel in enumerate(panels):
        left_edge = panel_number * panel_size
        sheet.paste(panel.resize((panel_size, panel_size)), (left_edge, 0))
    return sheet


def compare_piece(piece_folder: Path) -> dict:
    """Render the piece, compare it to its original, and save the results."""
    output_folder = piece_folder / "compare"
    output_folder.mkdir(exist_ok=True)

    original_image = Image.open(
        find_original_image(piece_folder)).convert("RGB")

    render_path = output_folder / "render.png"
    render_piece(piece_folder, original_image.width, render_path)
    rendered_image = Image.open(render_path).convert("RGB").resize(
        original_image.size)

    color_distance = measure_color_distance(original_image, rendered_image)
    pixel_is_mismatched = color_distance > COLOR_TOLERANCE
    mismatched_fraction = pixel_is_mismatched.mean()

    diff_image = draw_diff_image(rendered_image, pixel_is_mismatched)
    diff_image.save(output_folder / "diff.png")
    draw_comparison_sheet([original_image, rendered_image,
                           diff_image]).save(output_folder / "compare.png")

    score = {
        "match_percent": round(100 * (1 - mismatched_fraction), 2),
        "mean_color_distance": round(float(color_distance.mean()), 2),
        "color_tolerance": COLOR_TOLERANCE,
    }
    (output_folder /
     "score.json").write_text(json.dumps(score, indent=2) + "\n")
    return score


if __name__ == "__main__":
    piece_folder_argument = Path(sys.argv[1])
    print(json.dumps(compare_piece(piece_folder_argument)))
