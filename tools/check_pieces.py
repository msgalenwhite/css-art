"""Check that every piece follows the rules and matches its breakdown.

Usage:
    python3 tools/check_pieces.py            # every piece
    python3 tools/check_pieces.py pieces/01-sun-and-hills

For each piece this checks, in a real browser:
    1. The page uses no banned elements, inline styles, or image files.
    2. There is one element per shape in breakdown.json, in the same
       back-to-front order, with the shape's name as its class.
    3. Each element is painted in its shape's palette color.
    4. Each element sits where breakdown.json says the shape is.
    5. Nothing moves when the visitor asks for reduced motion.

It prints every problem it finds and exits with status 1 if there are any.
"""

import json
import math
import pathlib
import sys

from playwright.sync_api import sync_playwright

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The page is laid out with the scene exactly this wide, so that one pixel
# is a tenth of a percent of the scene and positions are easy to compare.
SCENE_WIDTH_PIXELS = 1000

# How far an element may be from its breakdown shape, in percent of the
# scene width. Breakdown values are rounded to one decimal place, so two
# values worked out from them can differ by a little more than 0.1.
POSITION_TOLERANCE_PERCENT = 0.15
ROTATION_TOLERANCE_DEGREES = 0.15

BANNED_ELEMENTS = ['script', 'svg', 'img', 'canvas', 'video', 'iframe']

# Runs inside the page. Returns what the checks below need to know about
# the scene's children, in the order they appear in the HTML.
READ_SCENE_ELEMENTS = """
() => Array.from(document.querySelector('.scene').children).map(element => {
  const style = getComputedStyle(element);
  return {
    classNames: Array.from(element.classList),
    left: parseFloat(style.left),
    top: parseFloat(style.top),
    width: parseFloat(style.width),
    height: parseFloat(style.height),
    transform: style.transform,
    backgroundColor: style.backgroundColor,
    borderRadius: style.borderRadius,
  };
})
"""


def hex_to_rgb_text(hex_code):
    """Turns '#74c6f3' into 'rgb(116, 198, 243)', the browser's spelling."""
    red, green, blue = (
        int(hex_code[start:start + 2], 16) for start in (1, 3, 5))
    return f'rgb({red}, {green}, {blue})'


def rotation_from_transform(transform_text):
    """Returns the clockwise rotation, in degrees, of a CSS transform.

    The browser reports a transform as 'matrix(a, b, c, d, e, f)'. For a
    pure rotation, a is the cosine of the angle and b is its sine.
    """
    if transform_text == 'none':
        return 0.0
    numbers = transform_text[transform_text.index('(') + 1:-1].split(',')
    cosine, sine = float(numbers[0]), float(numbers[1])
    return math.degrees(math.atan2(sine, cosine))


def to_percent(pixels):
    """Converts scene pixels to percent of the scene width."""
    return pixels * 100 / SCENE_WIDTH_PIXELS


def expected_box(shape):
    """Returns the left, top, width, and height a shape's element needs."""
    if shape['primitive'] in ('circle', 'ellipse'):
        return {
            'left': shape['center_x'] - shape['radius_x'],
            'top': shape['center_y'] - shape['radius_y'],
            'width': 2 * shape['radius_x'],
            'height': 2 * shape['radius_y'],
        }
    if shape['primitive'] in ('rectangle', 'rounded-rectangle'):
        return {key: shape[key] for key in ('left', 'top', 'width', 'height')}
    return None


def check_rules(page):
    """Returns problems with banned elements, inline styles, and images."""
    problems = []
    for element_name in BANNED_ELEMENTS:
        count = page.locator(element_name).count()
        if count:
            problems.append(f'uses <{element_name}> ({count} found); a piece '
                            'is HTML and CSS only')
    inline_style_count = page.locator('[style]').count()
    if inline_style_count:
        problems.append(f'{inline_style_count} element(s) have an inline '
                        'style attribute; put styles in style.css')
    scene = page.locator('.scene')
    if scene.count() != 1:
        return problems + ['needs exactly one element with class "scene"']
    if scene.get_attribute('role') != 'img':
        problems.append('.scene needs role="img"')
    if not scene.get_attribute('aria-label'):
        problems.append('.scene needs an aria-label describing the picture')
    return problems


def check_background_shape(shape, breakdown, page):
    """Returns problems with a shape that is drawn as the scene itself."""
    palette = {color['name']: color['hex'] for color in breakdown['palette']}
    scene_color = page.evaluate(
        "() => getComputedStyle(document.querySelector('.scene'))"
        '.backgroundColor')
    expected_color = hex_to_rgb_text(palette[shape['color']])
    if scene_color != expected_color:
        name = shape['name']
        return [
            f'{name}: the scene background is {scene_color} but the '
            f'breakdown says {expected_color}'
        ]
    return []


def check_element(shape, element, palette):
    """Returns problems with one element compared to its breakdown shape."""
    name = shape['name']
    problems = []
    if name not in element['classNames']:
        found = ' '.join(element['classNames']) or '(no class)'
        return [
            f'{name}: expected this shape next in the HTML but found '
            f'an element with class "{found}"'
        ]
    expected_color = hex_to_rgb_text(palette[shape['color']])
    if element['backgroundColor'] != expected_color:
        actual_color = element['backgroundColor']
        problems.append(f'{name}: painted {actual_color} but the breakdown '
                        f'says {expected_color}')
    box = expected_box(shape)
    if box is None:
        kind = shape['primitive']
        return problems + [
            f'{name}: this checker cannot yet verify a {kind}; '
            'teach tools/check_pieces.py how before adding one'
        ]
    for side, expected in box.items():
        actual = to_percent(element[side])
        if abs(actual - expected) > POSITION_TOLERANCE_PERCENT:
            problems.append(f'{name}: {side} is {actual:.1f}% but the '
                            f'breakdown gives {expected:.1f}%')
    actual_rotation = rotation_from_transform(element['transform'])
    expected_rotation = shape['rotation_degrees']
    if abs(actual_rotation - expected_rotation) > ROTATION_TOLERANCE_DEGREES:
        problems.append(f'{name}: rotated {actual_rotation:.1f} degrees but '
                        f'the breakdown gives {expected_rotation:.1f}')
    return problems


def fills_the_canvas(shape, breakdown):
    """Says whether a shape is a backdrop covering the whole canvas."""
    canvas_height = breakdown['canvas']['height_as_percent_of_width']
    return (shape['primitive'] == 'rectangle' and shape['left'] == 0 and
            shape['top'] == 0 and shape['width'] == 100 and
            shape['height'] == canvas_height and shape['rotation_degrees'] == 0)


def check_shapes(breakdown, page):
    """Returns problems with the elements compared to the breakdown."""
    palette = {color['name']: color['hex'] for color in breakdown['palette']}
    shapes = list(breakdown['shapes'])
    problems = []
    # A backdrop that fills the canvas is drawn as the scene's own
    # background, so it needs no element of its own.
    if shapes and fills_the_canvas(shapes[0], breakdown):
        problems += check_background_shape(shapes.pop(0), breakdown, page)
    elements = page.evaluate(READ_SCENE_ELEMENTS)
    if len(elements) != len(shapes):
        problems.append(f'the scene has {len(elements)} element(s) but the '
                        f'breakdown has {len(shapes)} shape(s) to draw')
    for shape, element in zip(shapes, elements):
        problems += check_element(shape, element, palette)
    return problems


def check_piece(piece_folder, browser):
    """Returns every problem found in one piece."""
    breakdown = json.loads((piece_folder / 'breakdown.json').read_text())
    scene_height = round(SCENE_WIDTH_PIXELS *
                         breakdown['canvas']['height_as_percent_of_width'] /
                         100)
    page = browser.new_page(viewport={
        'width': SCENE_WIDTH_PIXELS,
        'height': scene_height
    })
    # Reduced motion is requested so that animated shapes are measured in
    # their resting place, the one the breakdown describes.
    page.emulate_media(reduced_motion='reduce')
    page.goto((piece_folder / 'index.html').resolve().as_uri())
    problems = check_rules(page)
    if not problems:
        problems += check_shapes(breakdown, page)
    running_animation_count = page.evaluate(
        '() => document.getAnimations().length')
    if running_animation_count:
        problems.append(f'{running_animation_count} animation(s) still run '
                        'under prefers-reduced-motion: reduce')
    page.close()
    return problems


def main(arguments):
    """Checks the given pieces, or every piece, and reports problems."""
    if arguments:
        piece_folders = [pathlib.Path(argument) for argument in arguments]
    else:
        piece_folders = sorted(folder for folder in (REPOSITORY_ROOT /
                                                     'pieces').iterdir()
                               if folder.is_dir())
    problem_count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for piece_folder in piece_folders:
            problems = check_piece(piece_folder, browser)
            problem_count += len(problems)
            verdict = 'ok' if not problems else f'{len(problems)} problem(s)'
            print(f'{piece_folder.name}: {verdict}')
            for problem in problems:
                print(f'  - {problem}')
        browser.close()
    return 1 if problem_count else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
