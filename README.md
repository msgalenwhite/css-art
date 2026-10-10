# css-art

AI-generated images rebuilt and animated in CSS, with no JavaScript in the shipped pieces.

Each piece lives in `pieces/<number>-<name>/`:

| File | What it is |
|---|---|
| `original.webp` | The source image |
| `breakdown.md` / `breakdown.json` | Colors, shapes, and layer order, measured from the original by the [decompose-image skill](https://github.com/msgalenwhite/image-decomposition-skill) |
| `breakdown-preview.png` | The original beside a redraw made from the breakdown |
| `index.html` / `style.css` | The CSS rebuild |
| `compare/` | Original vs. render, a difference map, and a match score |

## Pieces

| Piece | Match to original |
|---|---|
| [01 Sun and Hills](pieces/01-sun-and-hills/) | 99.38% |

Piece 01 is animated: the sun sets behind the hills and rises again. It holds still for anyone whose device asks for reduced motion.

## Comparing a piece to its original

```
pip install -r requirements-dev.txt
python3 tools/compare.py pieces/01-sun-and-hills
```

This renders the piece in headless Chromium at the original's size and writes `compare/compare.png` and `compare/score.json`.

## Checking a piece against its breakdown

```
python3 tools/check_pieces.py
```

This opens every piece in headless Chromium and fails if a piece uses a banned element, if its elements do not match the shapes in `breakdown.json` in order, color, position, size, and rotation, or if anything still moves when reduced motion is requested. It runs on every push and pull request.

## Code Quality & Standards

This repository adheres to the **Google Style Guide**.
Code formatting and static analysis are enforced via `Stylelint`, `html-validate`, `Pylint`, and `yapf` within GitHub Actions.

| Code | Google guide | Enforced by | Rules live in |
|---|---|---|---|
| CSS in `pieces/` | [Google HTML/CSS Style Guide](https://google.github.io/styleguide/htmlcssguide.html) | Stylelint | `.stylelintrc.json` |
| HTML in `pieces/` | [Google HTML/CSS Style Guide](https://google.github.io/styleguide/htmlcssguide.html) | html-validate | `.htmlvalidate.json` |
| Python in `tools/` | [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) | Pylint (lint), yapf (format) | `.pylintrc`, `pyproject.toml` |

Run everything locally:

```
npm install
pip install -r requirements-dev.txt
npm run lint
```

The same checks run on every push and pull request (`.github/workflows/lint.yml`), together with the piece checker described above.

### Where the rules come from

- **Python:** `.pylintrc` is Google's own published Pylint configuration (Copyright 2018 Google LLC, Apache License 2.0), and yapf formats with its built-in `google` style.
- **CSS and HTML:** Google publishes the guide but no linter configuration for it, so `.stylelintrc.json` and `.htmlvalidate.json` are this repo's translation of the guide's rules into checks. Rules a linter cannot judge, such as meaningful class names and semantic elements, are followed by hand.
- The Google style guides are licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).

### Where this repo is stricter than Google

Code here is meant to be read by people and agents who have never seen it, so names are whole words. Google's rules allow single-letter names; this repo does not.

- Python variable, argument, and attribute names are at least three characters, with no exemptions, and common clipped abbreviations (`img`, `tmp`, `idx`, ...) are banned. Every change to Google's file is marked `css-art:` inside `.pylintrc`.
- CSS class, custom property, and animation names are whole lowercase words joined by hyphens, each at least three letters.

Not checked automatically yet: unexplained numbers. Give every number a named constant or a comment saying where it came from.
