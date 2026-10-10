"""Compare a CSS piece against its original image.

Usage: python3 tools/compare.py pieces/01-sun-and-hills

Renders index.html in headless Chromium at the original's pixel size, then
writes render.png, diff.png (red = mismatch) and compare.png (original |
render | diff) into the piece's compare/ folder and prints a score.

A pixel "matches" when its colour is within TOLERANCE of the original.
Colour distance is plain RGB distance (0 = identical, 441 = black vs white).
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

TOLERANCE = 24  # ignores compression noise and soft edges, catches wrong colour/shape

def render(piece: Path, size: int, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size, "height": size})
        page.emulate_media(reduced_motion="reduce")  # freeze animation for repeatable shots
        page.goto((piece / "index.html").resolve().as_uri())
        page.locator(".scene").screenshot(path=str(out))
        browser.close()

def main(piece: Path) -> int:
    out = piece / "compare"; out.mkdir(exist_ok=True)
    original = Image.open(next(piece.glob("original.*"))).convert("RGB")
    size = original.width
    render(piece, size, out / "render.png")
    rendered = Image.open(out / "render.png").convert("RGB").resize(original.size)
    a, b = np.asarray(original, float), np.asarray(rendered, float)
    dist = np.sqrt(((a - b) ** 2).sum(-1))
    miss = dist > TOLERANCE
    diff = (b * 0.35 + 255 * 0.65).astype(np.uint8); diff[miss] = (220, 30, 60)
    Image.fromarray(diff).save(out / "diff.png")
    sheet = Image.new("RGB", (size * 3, size))
    for i, im in enumerate((original, rendered, Image.fromarray(diff))): sheet.paste(im, (i * size, 0))
    sheet.resize((1800, 600)).save(out / "compare.png")
    score = {"match_percent": round(100 * (1 - miss.mean()), 2),
             "mean_colour_distance": round(float(dist.mean()), 2),
             "tolerance": TOLERANCE}
    (out / "score.json").write_text(json.dumps(score, indent=2) + "\n")
    print(json.dumps(score))
    return 0

if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
