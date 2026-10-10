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
| `pieces/<number>-<name>/breakdown.json` | Colours, shapes, and layer order measured from the original. |
| `pieces/<number>-<name>/breakdown.md` | The same breakdown, written for people. |
| `pieces/<number>-<name>/index.html`, `style.css` | The CSS rebuild. |
| `pieces/<number>-<name>/compare/` | Output of the comparison tool. Generated; do not hand-edit. |
| `tools/` | Python development tools. Nothing here ships in a piece. |
| `.agents/skills/` | Skills for agents. `.claude/skills` is a link to the same folder. |

## Commands

```
npm install
pip install -r requirements-dev.txt
npm run lint                                        # every linter
python3 tools/compare.py pieces/<number>-<name>     # score a piece
yapf --in-place --recursive tools                   # format Python
npx stylelint "pieces/**/*.css" --fix               # fix CSS ordering
```

## Rules for pieces

- A piece is HTML and CSS only: no `<script>`, no `<svg>`, no `<img>`, no
  background images, no inline styles.
- One HTML element per shape in `breakdown.json`, in the same back-to-front
  order, with the class name taken from the shape's `name`.
- Sizes and positions are percentages of the square `.scene`, so the piece
  scales to any width.
- Every colour is a custom property on `:root`, named after its palette
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
2. If a piece changed, run the comparison (see the `compare-piece` skill)
   and report the new match percentage next to the old one.
3. Never raise `COLOUR_TOLERANCE` or loosen a lint rule to make a check
   pass. If a rule seems wrong, stop and ask the owner.
4. Commit `compare/` output together with the change that produced it.

## When you use a technique for the first time

Say what it is and why it was the right choice, in plain words, in the
piece's `breakdown.md` or in a code comment. The owner reads these to learn.
