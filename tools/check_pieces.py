"""Check that every piece follows the rules and matches its breakdown.

Usage:
    python3 tools/check_pieces.py            # every piece
    python3 tools/check_pieces.py pieces/01-sun-and-hills

For each piece this checks, in a real browser:
    1. The page is plain HTML and CSS: no banned elements, inline styles,
       event handlers, image files, gradients, or generated content.
    2. There is one element per shape in breakdown.json, in the same
       back-to-front order, with the shape's name as its class, and
       nothing else is drawn.
    3. Each element is painted in its shape's palette color and is fully
       visible.
    4. Each element sits where breakdown.json says the shape is, with the
       same size, rotation, and corner rounding.
    5. Only transform and opacity are animated, and nothing moves when the
       visitor asks for reduced motion.
    6. The piece still looks like its original: its match score has not
       fallen below the floor or drifted from the score saved in compare/.

Checks 1 to 5 read the page's structure and styles. Check 6 looks at the
pixels, so it also catches anything the first five did not think of.

It prints every problem it finds and exits with status 1 if there are any.
"""

import json
import math
import pathlib
import sys
import tempfile

from playwright.sync_api import sync_playwright

import compare

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The page is laid out with the scene exactly this wide, so that one pixel
# is a tenth of a percent of the scene and positions are easy to compare.
SCENE_WIDTH_PIXELS = 1000

# How far an element may be from its breakdown shape, in percent of the
# scene width. Breakdown values are rounded to one decimal place, so two
# values worked out from them can differ by a little more than 0.1.
POSITION_TOLERANCE_PERCENT = 0.15
ROTATION_TOLERANCE_DEGREES = 0.15

# How far a transform's numbers may be from those of a plain rotation.
# Browsers report them to six decimal places.
TRANSFORM_NUMBER_TOLERANCE = 0.0001

# A piece must match its original on at least this share of pixels.
MINIMUM_MATCH_PERCENT = 98.0

# The match score measured now may differ from the one saved in
# compare/score.json by at most this many percentage points. Different
# browser versions draw soft edges slightly differently; anything larger
# means the piece changed and compare/ was not regenerated.
SCORE_DRIFT_ALLOWANCE_PERCENT = 0.1

BANNED_ELEMENTS = [
    'script', 'svg', 'img', 'canvas', 'video', 'audio', 'iframe', 'object',
    'embed', 'picture', 'source', 'style'
]

ANIMATABLE_PROPERTIES = {'transform', 'opacity'}

# Entries in a keyframe that describe timing, not a property being changed.
KEYFRAME_TIMING_ENTRIES = {'offset', 'computedOffset', 'easing', 'composite'}

# Runs inside the page. Returns the facts the rule checks need.
READ_PAGE_FACTS = """
(bannedElements) => {
  const everything = Array.from(document.querySelectorAll('*'));
  const scene = document.querySelector('.scene');
  return {
    bannedCounts: Object.fromEntries(bannedElements.map(
      name => [name, document.querySelectorAll(name).length])),
    inlineStyleCount: document.querySelectorAll('[style]').length,
    eventHandlerCount: everything.filter(element =>
      Array.from(element.attributes).some(
        attribute => attribute.name.startsWith('on'))).length,
    stylesheetAddresses: Array.from(
      document.querySelectorAll('link[rel="stylesheet"]')).map(
        link => link.getAttribute('href')),
    otherLinkCount: document.querySelectorAll(
      'link:not([rel="stylesheet"])').length,
    sceneCount: document.querySelectorAll('.scene').length,
    bodyChildCount: document.body.children.length,
    sceneRole: scene ? scene.getAttribute('role') : null,
    sceneLabel: scene ? scene.getAttribute('aria-label') : null,
  };
}
"""

# Runs inside the page. Returns how the scene and each of its children are
# styled, children in the order they appear in the HTML.
READ_SCENE_STYLES = """
() => {
  const describe = element => {
    const style = getComputedStyle(element);
    return {
      classNames: Array.from(element.classList),
      childCount: element.children.length,
      left: parseFloat(style.left),
      top: parseFloat(style.top),
      width: parseFloat(style.width),
      height: parseFloat(style.height),
      transform: style.transform,
      rotate: style.rotate,
      translate: style.translate,
      scale: style.scale,
      backgroundColor: style.backgroundColor,
      backgroundImage: style.backgroundImage,
      cornerRadii: [
        style.borderTopLeftRadius, style.borderTopRightRadius,
        style.borderBottomRightRadius, style.borderBottomLeftRadius,
      ],
      opacity: style.opacity,
      visibility: style.visibility,
      display: style.display,
      generatedContent: [
        getComputedStyle(element, '::before').content,
        getComputedStyle(element, '::after').content,
      ],
      transitionDurations: style.transitionDuration.split(',').map(
        duration => duration.trim()),
      transitionProperties: style.transitionProperty.split(',').map(
        property => property.trim()),
    };
  };
  const scene = document.querySelector('.scene');
  return {
    scene: describe(scene),
    elements: Array.from(scene.children).map(describe),
  };
}
"""

# Runs inside the page. Returns, for each running animation, its name and
# the properties its keyframes change.
READ_ANIMATIONS = """
() => document.getAnimations().map(animation => ({
  name: animation.animationName || '(unnamed)',
  entries: Array.from(new Set(
    animation.effect.getKeyframes().flatMap(keyframe => Object.keys(keyframe)))),
}))
"""


def hex_to_rgb_text(hex_code):
    """Turns '#74c6f3' into 'rgb(116, 198, 243)', the browser's spelling."""
    hex_digits_per_channel = 2
    red, green, blue = (int(hex_code[start:start + hex_digits_per_channel], 16)
                        for start in (1, 3, 5))  # skips the leading '#'
    return f'rgb({red}, {green}, {blue})'


def to_percent(pixels):
    """Converts scene pixels to percent of the scene width."""
    return pixels * 100 / SCENE_WIDTH_PIXELS


def rotation_from_transform(transform_text):
    """Returns (clockwise degrees, problem) for a CSS transform.

    The browser reports a flat transform as 'matrix(a, b, c, d, e, f)'.
    A plain rotation has a = d = the angle's cosine, b = -c = its sine,
    and e = f = 0. Anything else also moves, stretches, or skews the
    element, which would put it somewhere the breakdown does not say.
    """
    if transform_text == 'none':
        return 0.0, None
    if not transform_text.startswith('matrix('):
        return 0.0, ('uses a transform this checker cannot read: '
                     f'{transform_text}')
    numbers = [
        float(number) for number in transform_text[len('matrix('):-1].split(',')
    ]
    cosine, sine, minus_sine, second_cosine, shift_x, shift_y = numbers
    differences_from_a_rotation = [
        cosine - second_cosine, sine + minus_sine,
        math.hypot(cosine, sine) - 1, shift_x, shift_y
    ]
    if any(
            abs(difference) > TRANSFORM_NUMBER_TOLERANCE
            for difference in differences_from_a_rotation):
        return 0.0, ('its transform does more than rotate (it moves, '
                     f'stretches, or skews): {transform_text}')
    return math.degrees(math.atan2(sine, cosine)), None


def rotation_from_rotate_property(rotate_text):
    """Returns (clockwise degrees, problem) for the CSS rotate property."""
    if rotate_text == 'none':
        return 0.0, None
    if rotate_text.endswith('deg') and ' ' not in rotate_text:
        return float(rotate_text[:-len('deg')]), None
    return 0.0, f'uses a rotate value this checker cannot read: {rotate_text}'


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


def check_page_rules(facts):
    """Returns problems with what the page is made of."""
    problems = []
    for element_name, count in facts['bannedCounts'].items():
        if count:
            problems.append(f'uses <{element_name}> ({count} found); a piece '
                            'is HTML and CSS only, with styles in style.css')
    if facts['inlineStyleCount']:
        count = facts['inlineStyleCount']
        problems.append(f'{count} element(s) have an inline style attribute; '
                        'put styles in style.css')
    if facts['eventHandlerCount']:
        count = facts['eventHandlerCount']
        problems.append(f'{count} element(s) have an on... event handler; a '
                        'piece has no scripting')
    if facts['stylesheetAddresses'] != ['style.css']:
        found = facts['stylesheetAddresses']
        problems.append('the page must load exactly one stylesheet, '
                        f'style.css, but loads {found}')
    if facts['otherLinkCount']:
        problems.append('the page has a <link> that is not a stylesheet')
    if facts['sceneCount'] != 1:
        return problems + ['needs exactly one element with class "scene"']
    if facts['bodyChildCount'] != 1:
        problems.append('the scene must be the only element in <body>')
    if facts['sceneRole'] != 'img':
        problems.append('.scene needs role="img"')
    if not facts['sceneLabel']:
        problems.append('.scene needs an aria-label describing the picture')
    return problems


def check_paint(name, element, expected_color):
    """Returns problems with how an element is painted.

    Used for the scene and for every shape: one flat color, fully visible,
    with nothing extra drawn by images or generated content.
    """
    problems = []
    if element['backgroundColor'] != expected_color:
        actual_color = element['backgroundColor']
        problems.append(f'{name}: painted {actual_color} but the breakdown '
                        f'says {expected_color}')
    if element['backgroundImage'] != 'none':
        problems.append(f'{name}: has a background image or gradient; shapes '
                        'are one flat color')
    hidden = (element['opacity'] != '1' or element['visibility'] != 'visible' or
              element['display'] == 'none')
    if hidden:
        problems.append(f'{name}: is hidden or see-through when at rest')
    if any(content != 'none' for content in element['generatedContent']):
        problems.append(f'{name}: draws extra content with ::before or '
                        '::after; every shape needs its own element')
    return problems


def check_corners(shape, element):
    """Returns problems with how an element's corners are rounded."""
    name = shape['name']
    corner_radii = element['cornerRadii']
    if shape['primitive'] in ('circle', 'ellipse'):
        if any(radius != '50%' for radius in corner_radii):
            return [
                f'{name}: needs border-radius: 50% to be round, but has '
                f'{corner_radii}'
            ]
        return []
    expected_radius = shape.get('corner_radius', 0)
    for radius in corner_radii:
        if not radius.endswith('px'):
            return [
                f'{name}: corner radius {radius} is not a plain length, so '
                'its size depends on the element and cannot be checked'
            ]
        actual_radius = to_percent(float(radius[:-len('px')]))
        if abs(actual_radius - expected_radius) > POSITION_TOLERANCE_PERCENT:
            return [
                f'{name}: corner radius is {actual_radius:.1f}% but the '
                f'breakdown gives {expected_radius:.1f}%'
            ]
    return []


def check_placement(shape, element, box):
    """Returns problems with where an element sits and how it is turned."""
    name = shape['name']
    problems = []
    for side, expected in box.items():
        actual = to_percent(element[side])
        if abs(actual - expected) > POSITION_TOLERANCE_PERCENT:
            problems.append(f'{name}: {side} is {actual:.1f}% but the '
                            f'breakdown gives {expected:.1f}%')
    for property_name in ('translate', 'scale'):
        if element[property_name] != 'none':
            problems.append(f'{name}: uses the {property_name} property at '
                            'rest; place and size it with left, top, width, '
                            'and height')
    transform_rotation, transform_problem = rotation_from_transform(
        element['transform'])
    property_rotation, property_problem = rotation_from_rotate_property(
        element['rotate'])
    unreadable = [
        problem for problem in (transform_problem, property_problem) if problem
    ]
    if unreadable:
        return problems + [f'{name}: {problem}' for problem in unreadable]
    actual_rotation = transform_rotation + property_rotation
    expected_rotation = shape['rotation_degrees']
    if abs(actual_rotation - expected_rotation) > ROTATION_TOLERANCE_DEGREES:
        problems.append(f'{name}: rotated {actual_rotation:.1f} degrees but '
                        f'the breakdown gives {expected_rotation:.1f}')
    return problems


def check_element(shape, element, palette):
    """Returns problems with one element compared to its breakdown shape."""
    name = shape['name']
    if name not in element['classNames']:
        found = ' '.join(element['classNames']) or '(no class)'
        return [
            f'{name}: expected this shape next in the HTML but found '
            f'an element with class "{found}"'
        ]
    problems = check_paint(name, element,
                           hex_to_rgb_text(palette[shape['color']]))
    if element['childCount']:
        problems.append(f'{name}: has elements nested inside it; every shape '
                        'is a direct child of the scene')
    box = expected_box(shape)
    if box is None:
        kind = shape['primitive']
        return problems + [
            f'{name}: this checker cannot yet verify a {kind}; '
            'teach tools/check_pieces.py how before adding one'
        ]
    return (problems + check_corners(shape, element) +
            check_placement(shape, element, box))


def fills_the_canvas(shape, breakdown):
    """Says whether a shape is a backdrop covering the whole canvas."""
    canvas_height = breakdown['canvas']['height_as_percent_of_width']
    return (shape['primitive'] == 'rectangle' and shape['left'] == 0 and
            shape['top'] == 0 and shape['width'] == 100 and
            shape['height'] == canvas_height and shape['rotation_degrees'] == 0)


def check_shapes(breakdown, styles):
    """Returns problems with the scene's elements compared to the breakdown."""
    palette = {color['name']: color['hex'] for color in breakdown['palette']}
    shapes = list(breakdown['shapes'])
    problems = []
    # A backdrop that fills the canvas is drawn as the scene's own
    # background, so it needs no element of its own.
    if shapes and fills_the_canvas(shapes[0], breakdown):
        backdrop = shapes.pop(0)
        problems += check_paint(backdrop['name'], styles['scene'],
                                hex_to_rgb_text(palette[backdrop['color']]))
    elements = styles['elements']
    if len(elements) != len(shapes):
        problems.append(f'the scene has {len(elements)} element(s) but the '
                        f'breakdown has {len(shapes)} shape(s) to draw')
    for shape, element in zip(shapes, elements):
        problems += check_element(shape, element, palette)
    return problems


def check_transitions(styles, motion_is_reduced):
    """Returns problems with CSS transitions on the scene and its shapes.

    A transition only runs when something changes, such as on hover, so it
    cannot be caught by looking for running animations. Its declaration is
    checked instead.
    """
    problems = []
    for element in [styles['scene']] + styles['elements']:
        name = ' '.join(element['classNames'])
        has_transition = any(
            duration != '0s' for duration in element['transitionDurations'])
        if not has_transition:
            continue
        if motion_is_reduced:
            problems.append(f'{name}: still has a transition under '
                            'prefers-reduced-motion: reduce')
            continue
        not_allowed = set(
            element['transitionProperties']) - ANIMATABLE_PROPERTIES
        if not_allowed:
            listed = ', '.join(sorted(not_allowed))
            problems.append(f'{name}: transitions {listed}; only transform '
                            'and opacity may move')
    return problems


def check_animations(animations):
    """Returns problems with which properties the animations change."""
    problems = []
    for animation in animations:
        changed = (set(animation['entries']) - KEYFRAME_TIMING_ENTRIES -
                   ANIMATABLE_PROPERTIES)
        if changed:
            name = animation['name']
            listed = ', '.join(sorted(changed))
            problems.append(f'animation {name} changes {listed}; only '
                            'transform and opacity may be animated')
    return problems


def check_score(piece_folder):
    """Returns problems with how closely the piece matches its original."""
    saved_score_path = piece_folder / 'compare' / 'score.json'
    if not saved_score_path.exists():
        return ['has no compare/score.json; run python3 tools/compare.py on it']
    saved_percent = json.loads(saved_score_path.read_text())['match_percent']
    with tempfile.TemporaryDirectory() as scratch_folder:
        score = compare.score_piece(piece_folder,
                                    pathlib.Path(scratch_folder) /
                                    'render.png')[0]
    current_percent = score['match_percent']
    problems = []
    if current_percent < MINIMUM_MATCH_PERCENT:
        problems.append(f'matches its original on {current_percent}% of '
                        f'pixels; the floor is {MINIMUM_MATCH_PERCENT}%')
    if abs(current_percent - saved_percent) > SCORE_DRIFT_ALLOWANCE_PERCENT:
        problems.append(f'matches its original on {current_percent}% of '
                        f'pixels but compare/score.json says {saved_percent}%; '
                        'the piece changed, so run python3 tools/compare.py '
                        'on it and look at the result')
    return problems


def open_piece(piece_folder, breakdown, browser, motion_is_reduced):
    """Opens the piece's page at the checking size and returns the page."""
    scene_height = round(SCENE_WIDTH_PIXELS *
                         breakdown['canvas']['height_as_percent_of_width'] /
                         100)
    page = browser.new_page(viewport={
        'width': SCENE_WIDTH_PIXELS,
        'height': scene_height
    })
    if motion_is_reduced:
        page.emulate_media(reduced_motion='reduce')
    page.goto((piece_folder / 'index.html').resolve().as_uri())
    return page


def check_structure(piece_folder, browser):
    """Returns the problems found by reading a piece's page and styles."""
    missing = [
        file_name for file_name in ('breakdown.json', 'index.html', 'style.css')
        if not (piece_folder / file_name).exists()
    ]
    if missing:
        return ['is missing ' + ', '.join(missing)]
    breakdown = json.loads((piece_folder / 'breakdown.json').read_text())

    # Reduced motion is requested first so that animated shapes are
    # measured in their resting place, the one the breakdown describes.
    resting_page = open_piece(piece_folder, breakdown, browser, True)
    problems = check_page_rules(
        resting_page.evaluate(READ_PAGE_FACTS, BANNED_ELEMENTS))
    if problems:
        resting_page.close()
        return problems
    resting_styles = resting_page.evaluate(READ_SCENE_STYLES)
    problems += check_shapes(breakdown, resting_styles)
    problems += check_transitions(resting_styles, motion_is_reduced=True)
    still_running = resting_page.evaluate(READ_ANIMATIONS)
    if still_running:
        problems.append(f'{len(still_running)} animation(s) still run under '
                        'prefers-reduced-motion: reduce')
    resting_page.close()

    # Then with motion allowed, to see what the animations change.
    moving_page = open_piece(piece_folder, breakdown, browser, False)
    problems += check_animations(moving_page.evaluate(READ_ANIMATIONS))
    problems += check_transitions(moving_page.evaluate(READ_SCENE_STYLES),
                                  motion_is_reduced=False)
    moving_page.close()

    return problems


def find_piece_folders(arguments):
    """Returns the folders to check: those named, or every piece."""
    if arguments:
        return [pathlib.Path(argument) for argument in arguments]
    pieces_folder = REPOSITORY_ROOT / 'pieces'
    if not pieces_folder.is_dir():
        return []
    return sorted(
        folder for folder in pieces_folder.iterdir() if folder.is_dir())


def main(arguments):
    """Checks the given pieces, or every piece, and reports problems."""
    piece_folders = find_piece_folders(arguments)
    if not piece_folders:
        # Passing with nothing checked would hide a renamed or emptied
        # pieces folder, so finding no pieces is itself a failure.
        print('no pieces found to check')
        return 1
    problems_by_piece = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for piece_folder in piece_folders:
            problems_by_piece[piece_folder] = check_structure(
                piece_folder, browser)
        browser.close()
    # The score check opens its own browser through the comparison tool,
    # and only one may be open at a time, so it runs after the first closes.
    for piece_folder, problems in problems_by_piece.items():
        if 'is missing' not in ' '.join(problems):
            problems += check_score(piece_folder)
        verdict = 'ok' if not problems else f'{len(problems)} problem(s)'
        print(f'{piece_folder.name}: {verdict}')
        for problem in problems:
            print(f'  - {problem}')
    return 1 if any(problems_by_piece.values()) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
