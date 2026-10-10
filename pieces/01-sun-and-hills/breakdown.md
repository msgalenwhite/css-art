# Breakdown: 01 Sun and Hills

Measured from `original.webp` (1600 x 1600). Positions are percentages of the canvas, measured from the top-left corner. Machine-readable copy: `breakdown.json`.

## Palette

| Name | Hex | Visible area |
|---|---|---|
| sky | `#74c6f3` | 54.5% |
| sun | `#f8bab0` | 8.6% |
| hill-green | `#94deba` | 16.8% |
| hill-lavender | `#c2a1e3` | 20.0% |

## Shapes, back to front

| Shape | Primitive | Centre (x, y) | Radii (x, y) | Rotation |
|---|---|---|---|---|
| sky | rectangle | fills the canvas | | |
| sun | circle | 50, 50 | 18.8 | 0 |
| hill-green | ellipse | 33.7, 97.2 | 34.3, 43.1 | 2.8 deg clockwise |
| hill-lavender | ellipse | 66.0, 112.1 | 35.2, 51.6 | 10.1 deg clockwise |

Both hills have centres at or below the bottom edge, so only their top arcs show.

## Simplifications

- Each region is flattened to its median colour. The original has faint compression noise.
- A few small teal specks inside the green hill are dropped as generation artefacts.
- The hills are modelled as whole ellipses. Only the top arcs are visible, so the hidden parts are inferred.

## How it was measured

1. Sampled the median colour from the middle of each region.
2. Labelled every pixel by its nearest palette colour, leaving blended edge pixels unlabelled.
3. Fitted an ellipse to each shape's true outline, ignoring edges where another shape covers it.

## Fidelity of the CSS build

`python3 tools/compare.py pieces/01-sun-and-hills` scores 99.39% of pixels within tolerance. The remaining 0.61% is a one-to-two pixel line along shape edges.
