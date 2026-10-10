# css-art

AI-generated images rebuilt and animated in CSS, with no JavaScript in the shipped pieces.

Each piece lives in `pieces/<number>-<name>/`:

| File | What it is |
|---|---|
| `original.webp` | The source image |
| `breakdown.md` / `breakdown.json` | Colors, shapes, and layer order measured from the original |
| `index.html` / `style.css` | The CSS rebuild |
| `compare/` | Original vs. render, a difference map, and a match score |

## Pieces

| Piece | Match to original |
|---|---|
| [01 Sun and Hills](pieces/01-sun-and-hills/) | 99.39% |

## Comparing a piece to its original

```
pip install playwright pillow numpy
python3 tools/compare.py pieces/01-sun-and-hills
```

This renders the piece in headless Chromium at the original's size and writes `compare/compare.png` and `compare/score.json`.
