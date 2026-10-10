# Instructions for coding agents

This file is read by Codex directly and by Claude Code through `CLAUDE.md`.
Edit this file only; `CLAUDE.md` just imports it.

## What this repo is

AI-generated images rebuilt and animated in CSS. Each piece is measured,
rebuilt from plain HTML elements, and scored against its original image.
The owner is building with agents and learning as they go, so the code must
be easy for a newcomer, human or agent, to read and extend.

## Layout

| Path | Contents |
|---|---|
| `pieces/<number>-<name>/original.*` | The source image. Never edit it. |
| `pieces/<number>-<name>/breakdown.json` | Colors, shapes, and layer order measured from the original by the `decompose-image` skill. Never edit its numbers by hand. |
| `pieces/<number>-<name>/breakdown.md` | The same breakdown, written for people. |
| `pieces/<number>-<name>/breakdown-preview.png` | The original beside a redraw from the breakdown. |
| `pieces/<number>-<name>/index.html`, `style.css` | The CSS rebuild. |
| `pieces/<number>-<name>/compare/` | Output of the comparison tool. Generated; do not hand-edit. |
| `tools/` | Python development tools. Nothing here ships in a piece. |
| `.agents/skills/` | Skills for agents. `.claude/skills` is a link to the same folder. |

## Commands

```
npm install
pip install -r requirements-dev.txt
npm run lint                                        # every linter
python3 tools/check_pieces.py                       # rules and breakdown match
python3 tools/compare.py pieces/<number>-<name>     # score a piece
yapf --in-place --recursive tools                   # format Python
npx stylelint "pieces/**/*.css" --fix               # fix CSS ordering
```

## Adding a piece

1. Create `pieces/<number>-<name>/` and save the source image in it as
   `original.<extension>`.
2. Measure it with the `decompose-image` skill, which lives in its own
   repository: https://github.com/msgalenwhite/image-decomposition-skill.
   Follow that skill's `SKILL.md`, including renaming the shapes after
   what they depict. The breakdown's format is described in the skill's
   `references/breakdown-format.md`.
3. Write `index.html` and `style.css` from `breakdown.json`, following
   the rules below. Copy piece 01's header comment for how to turn a
   breakdown shape into CSS.
4. Run `python3 tools/check_pieces.py` until it reports no problems.
5. Run the `compare-piece` skill and look at `compare/compare.png`.
6. Add the piece to the table in `README.md`.

## Rules for pieces

- A piece is HTML and CSS only: no `<script>`, no `<svg>`, no `<img>`, no
  background images, no inline styles.
- One HTML element per shape in `breakdown.json`, in the same back-to-front
  order, with the class name taken from the shape's `name`. The one
  exception is a backdrop that fills the canvas: it is the `.scene`
  element's own background.
- Every position, size, and rotation comes from `breakdown.json`. If a
  number looks wrong, fix the measurement, not the CSS.
- Sizes and positions are percentages of the square `.scene`, so the piece
  scales to any width.
- Every color is a custom property on `:root`, named after its palette
  entry in `breakdown.json`.
- The `.scene` element has `role="img"` and an `aria-label` describing the
  picture.
- Animate only `transform` and `opacity`, and stop all motion under
  `prefers-reduced-motion: reduce`.

## Rules for all code

- Names are whole words. No single letters and no clipped abbreviations
  (`image`, not `img`; `index`, not `idx`). The linters enforce a
  three-character minimum; the intent is stricter than that.
- No unexplained numbers. Give each one a named constant, or a comment
  saying where it came from.
- Comments explain why, not what.
- One job per function, with a one-line description of that job.
- Follow the Google style guides listed in `README.md`. Where this file is
  stricter than Google, this file wins.

## Before calling work done

1. `npm run lint` passes with no errors.
2. `python3 tools/check_pieces.py` reports no problems.
3. If a piece changed, run the comparison (see the `compare-piece` skill)
   and report the new match percentage next to the old one.
4. Never raise a tolerance or loosen a lint rule to make a check pass. If
   a rule seems wrong, stop and ask the owner.
5. Commit `compare/` output together with the change that produced it.

## When you use a technique for the first time

Say what it is and why it was the right choice, in plain words, in the
piece's `breakdown.md` or in a code comment. The owner reads these to learn.
