---
name: compare-piece
description: Score a CSS piece against its original image and show where they differ. Use after creating or changing anything in a pieces/ folder, or when asked how close a piece is to its original. Do not use for files outside pieces/.
---

# Compare a piece to its original

## Run it

From the repository root:

```
python3 tools/compare.py pieces/<number>-<name>
```

Needs the packages in `requirements-dev.txt` and a Chromium browser that
Playwright can find (`playwright install chromium` if there is none).

## What it produces

The command prints one line of JSON and writes four files into the piece's
`compare/` folder:

| File | Contents |
|---|---|
| `score.json` | `match_percent`, `mean_color_distance`, `color_tolerance` |
| `render.png` | The piece as the browser drew it |
| `diff.png` | The render, faded, with every mismatched pixel in red |
| `compare.png` | Original, render, and diff side by side |

## Read the result

1. Open `compare.png` and look at it. The number alone can hide a problem.
2. Thin red lines that trace shape edges are expected: the original has
   soft edges and the render has crisp ones.
3. A solid red area means a shape has the wrong color, size, position, or
   layer order. Find that shape in `breakdown.json` and fix the matching
   rule in `style.css`.
4. Report `match_percent` before and after your change.

## Rules

- Animation is frozen during the screenshot because the tool requests
  reduced motion. A piece must look like its original in that state.
- Do not change `COLOR_TOLERANCE` in `tools/compare.py` to improve a
  score. Ask the owner first.
- Commit the `compare/` folder with the change that produced it.
