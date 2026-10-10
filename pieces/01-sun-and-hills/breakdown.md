# Breakdown of original.webp

Canvas: 1600 x 1600 pixels. Every position and size is a percentage of the canvas width, measured from the top-left corner.

## Palette

| Name | Hex | Visible area |
|---|---|---|
| sky | `#74c6f3` | 54.5% |
| hill-lavender | `#c2a1e3` | 20.0% |
| hill-green | `#94deba` | 16.8% |
| sun | `#f8bab0` | 8.7% |

## Shapes, back to front

| Shape | Primitive | Color | Position and size |
|---|---|---|---|
| sky | rectangle | sky | left 0.0, top 0.0, width 100.0, height 100.0 |
| sun | circle | sun | center 50.0, 49.6; radii 18.6, 18.6 |
| hill-green | ellipse | hill-green | center 33.7, 96.6; radii 34.3, 42.6; rotated 2.8 degrees clockwise |
| hill-lavender | ellipse | hill-lavender | center 66.1, 111.9; radii 35.3, 51.4; rotated 9.9 degrees clockwise |

## Groups

- hills: hill-green, hill-lavender

## Simplifications

- Each region is flattened to one color: the median of its pixels.
- Shapes partly hidden behind others are completed from the part of their outline that is visible.

## Accuracy

Redrawing the image from these shapes gives the right color on 99.88% of the original's flat-colored pixels. The blended pixels along edges are not scored. See `breakdown-preview.png` (original on the left, redraw on the right).
