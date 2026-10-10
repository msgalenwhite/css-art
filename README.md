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
pip install -r requirements-dev.txt
python3 tools/compare.py pieces/01-sun-and-hills
```

This renders the piece in headless Chromium at the original's size and writes `compare/compare.png` and `compare/score.json`.

## Naming rules, checked automatically

Code here is meant to be read by people and agents who have never seen it, so names are whole words: no single letters, no clipped abbreviations.

```
npm install
npm run lint
```

| Linter | Checks | Rules live in |
|---|---|---|
| Stylelint | Class, custom property, and animation names in every piece | `.stylelintrc.json` |
| Pylint | Variable, argument, function, and constant names in `tools/` | `pyproject.toml` |

Both run on every push and pull request (`.github/workflows/lint.yml`).

Not checked automatically yet: unexplained numbers. Give every number a named constant or a comment saying where it came from.
