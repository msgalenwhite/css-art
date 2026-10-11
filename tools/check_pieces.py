"""Check that every piece follows the rules and matches its breakdown.

Usage:
    python3 tools/check_pieces.py            # every piece
    python3 tools/check_pieces.py pieces/01-sun-and-hills

For each piece this checks:
    1. The page is plain HTML and CSS: no banned elements, inline styles,
       event handlers, image files, gradients, or generated content.
    2. Colors are custom properties on :root named after the breakdown's
       palette, and are not written directly anywhere else.
    3. There is one element per shape in breakdown.json, in the same
       back-to-front order, with the shape's name as its class, and
       nothing else is drawn.
    4. Each element is painted in its shape's palette color, is fully
       visible, and sits where breakdown.json says the shape is, with the
       same size, rotation, and corner rounding. This is checked in
       several window sizes, since a piece must scale to any width.
    5. Only transform and opacity are animated, and nothing moves when the
       visitor asks for reduced motion.
    6. The piece still looks like its original: its match score has not
       fallen below the floor or drifted from the score saved in compare/.

Checks 1 to 5 read the page's source, structure, and styles. Check 6 looks
at the pixels, so it also catches anything the first five did not think of.

The checker is meant to catch honest mistakes, not to withstand someone
deliberately hiding a rule break from it.

It prints every problem it finds and exits with status 1 if there are any.
"""

import json
import math
import pathlib
import re
import sys
import tempfile

from playwright.sync_api import sync_playwright

import compare

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The window sizes each piece is measured in, as (width, height, color
# scheme): the size the comparison picture uses, a phone-sized square, a
# wide window, and a tall one. A piece must match its breakdown in all of
# them. The wide window also asks for a dark color scheme, which a piece
# must ignore.
WINDOWS_TO_CHECK = [
    (1000, 1000, 'light'),
    (400, 400, 'light'),
    (1300, 700, 'dark'),
    (500, 900, 'light'),
]

# How far an element may be from its breakdown shape, in percent of the
# scene width. Breakdown values are rounded to one decimal place, so two
# values worked out from them can differ by a little more than 0.1.
POSITION_TOLERANCE_PERCENT = 0.15

# Breakdown rotations are also rounded to one decimal place, and the
# browser reports a rotation as a sine and cosine rounded to six places,
# so a correct element can read up to about 0.1 degrees off.
ROTATION_TOLERANCE_DEGREES = 0.15

# How far a transform's numbers may be from those of a plain rotation.
# Browsers report them rounded to six decimal places, so honest rounding
# is a hundred times smaller than this, while a deliberate one-pixel shift
# or one-percent stretch is a hundred times larger.
TRANSFORM_NUMBER_TOLERANCE = 0.0001

# How far the scene's height may be from the height its width calls for,
# in pixels. Browsers round box sizes to fractions of a pixel.
SCENE_SHAPE_TOLERANCE_PIXELS = 0.5

# A piece must match its original on at least this share of pixels. Piece
# 01, three simple shapes, scores 99.4; the missing 0.6 is the soft edges
# of the original. 98 leaves room for busier pieces with more edges while
# still failing a piece with one shape out of place. The owner sets this
# number: do not lower it to make a piece pass.
MINIMUM_MATCH_PERCENT = 98.0

# The match score measured now may differ from the one saved in
# compare/score.json by at most this many percentage points. Different
# browser versions draw soft edges slightly differently; anything larger
# means the piece changed and compare/ was not regenerated.
SCORE_DRIFT_ALLOWANCE_PERCENT = 0.1

FILES_EVERY_PIECE_NEEDS = ['breakdown.json', 'index.html', 'style.css']

# Looked for in the page's source text, where nothing can hide them.
# 'template' is here because a template can carry a script into the page
# out of sight of everything that inspects the finished page.
BANNED_ELEMENTS = [
    'script', 'svg', 'img', 'canvas', 'video', 'audio', 'iframe', 'object',
    'embed', 'picture', 'source', 'style', 'template', 'base', 'noscript'
]

ANIMATABLE_PROPERTIES = {'transform', 'opacity'}

# Entries in a running animation's keyframes that describe timing, not a
# property being changed.
KEYFRAME_TIMING_ENTRIES = {'offset', 'computedOffset', 'easing', 'composite'}

# Runs inside the page. Returns the facts the page-rule checks need.
READ_PAGE_FACTS = """
() => {
  const everything = Array.from(document.querySelectorAll('*'));
  const scene = document.querySelector('.scene');
  return {
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

# Runs inside the page, given the text of style.css. The browser will not
# let a page opened from a file read its own stylesheet's rules, so the
# text is parsed again as a fresh stylesheet, which can be read. Reads it
# rule by rule, including rules inside @media blocks, and returns:
#   declarations  every "property: value" with the selector it is under
#   keyframes     every property each @keyframes block changes
#   bannedRules   at-rules that fetch other files
# It also marks each declaration whose value writes a color directly.
# (@import is looked for in the text instead, because a stylesheet parsed
# this way silently drops it.)
READ_STYLESHEET_FACTS = """
(stylesheetText) => {
  const declarations = [];
  const keyframes = [];
  const bannedRules = [];
  const colorKeywordsThatAreNotColors = new Set([
    'inherit', 'initial', 'unset', 'revert', 'revert-layer',
    'transparent', 'currentcolor',
  ]);
  const writesAColor = value => value.split(/[\\s,()\\/]+/).some(word =>
    word !== '' && !word.startsWith('--') &&
    !colorKeywordsThatAreNotColors.has(word.toLowerCase()) &&
    CSS.supports('color', word)) || /\\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\\(/i.test(value);
  const readDeclarations = style => style.cssText.split(';').map(
    text => text.trim()).filter(text => text !== '').map(text => {
      const colon = text.indexOf(':');
      return {
        property: text.slice(0, colon).trim(),
        value: text.slice(colon + 1).trim(),
      };
    });
  const walk = rules => {
    for (const rule of rules) {
      if (rule instanceof CSSFontFaceRule) {
        bannedRules.push('@font-face');
      } else if (rule instanceof CSSKeyframesRule) {
        for (const frame of rule.cssRules) {
          keyframes.push({
            name: rule.name,
            properties: readDeclarations(frame.style).map(
              declaration => declaration.property),
          });
        }
      } else {
        if (rule.style) {
          for (const declaration of readDeclarations(rule.style)) {
            declarations.push({
              selector: rule.selectorText || '',
              property: declaration.property,
              value: declaration.value,
              writesAColor: writesAColor(declaration.value),
            });
          }
        }
        if (rule.cssRules) walk(rule.cssRules);
      }
    }
  };
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(stylesheetText);
  walk(sheet.cssRules);
  return { declarations, keyframes, bannedRules };
}
"""

# Runs inside the page. Returns how the scene and each of its children are
# styled, children in the order they appear in the HTML.
READ_SCENE_STYLES = """
() => {
  const describe = element => {
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return {
      classNames: Array.from(element.classList),
      childCount: element.children.length,
      left: parseFloat(style.left),
      top: parseFloat(style.top),
      width: parseFloat(style.width),
      height: parseFloat(style.height),
      paddingAndBorder: [
        style.paddingTop, style.paddingRight, style.paddingBottom,
        style.paddingLeft, style.borderTopWidth, style.borderRightWidth,
        style.borderBottomWidth, style.borderLeftWidth,
      ].reduce((total, length) => total + parseFloat(length), 0),
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
      // The box as drawn on screen, used only for the scene itself.
      drawnWidth: box.width,
      drawnHeight: box.height,
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


def check_page_source(page_source):
    """Returns problems found by reading index.html as text."""
    problems = []
    for element_name in BANNED_ELEMENTS:
        if re.search(rf'<\s*{element_name}\b', page_source, re.IGNORECASE):
            problems.append(f'uses <{element_name}>; a piece is HTML and CSS '
                            'only, with styles in style.css')
    if re.search(r'javascript\s*:', page_source, re.IGNORECASE):
        problems.append('has a javascript: address; a piece has no scripting')
    if re.search(r'\sbackground\s*=', page_source, re.IGNORECASE):
        problems.append('sets a background with an HTML attribute; a piece '
                        'has no background images')
    return problems


def check_page_rules(facts):
    """Returns problems with how the finished page is put together."""
    problems = []
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


def check_stylesheet(stylesheet, stylesheet_text, breakdown):
    """Returns problems with style.css as written.

    Reading the rules themselves, not their effect on the page, catches
    things that only happen sometimes: on hover, at another window size,
    or in an animation that is not running yet.
    """
    problems = []
    banned_rules = set(stylesheet['bannedRules'])
    if re.search(r'@import\b', stylesheet_text, re.IGNORECASE):
        banned_rules.add('@import')
    for rule_name in sorted(banned_rules):
        problems.append(f'style.css uses {rule_name}, which loads another '
                        'file; a piece is one HTML file and one stylesheet')
    root_properties = {}
    for declaration in stylesheet['declarations']:
        selector = declaration['selector']
        property_name = declaration['property']
        value = declaration['value']
        written = f'{selector} {{ {property_name}: {value} }}'
        if re.search(r'url\(|gradient\(', value, re.IGNORECASE):
            problems.append(f'{written} loads an image or draws a gradient; '
                            'shapes are one flat color')
        is_palette_entry = selector == ':root' and property_name.startswith(
            '--')
        if is_palette_entry:
            root_properties[property_name] = value.lower()
        elif declaration['writesAColor']:
            problems.append(f'{written} writes a color directly; use a '
                            'custom property from :root')
    for color in breakdown['palette']:
        property_name = '--' + color['name']
        expected_hex = color['hex'].lower()
        actual_value = root_properties.get(property_name)
        if actual_value != expected_hex:
            found = actual_value or 'nothing'
            problems.append(f':root must set {property_name} to '
                            f'{expected_hex}, the palette color of that name '
                            f'in the breakdown, but sets {found}')
    for keyframe in stylesheet['keyframes']:
        not_allowed = set(keyframe['properties']) - ANIMATABLE_PROPERTIES
        if not_allowed:
            name = keyframe['name']
            listed = ', '.join(sorted(not_allowed))
            problems.append(f'@keyframes {name} changes {listed}; only '
                            'transform and opacity may be animated')
    return sorted(set(problems))


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


def check_corners(shape, element, to_percent):
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


def check_placement(shape, element, box, to_percent):
    """Returns problems with where an element sits and how it is turned."""
    name = shape['name']
    problems = []
    for side, expected in box.items():
        actual = to_percent(element[side])
        if abs(actual - expected) > POSITION_TOLERANCE_PERCENT:
            problems.append(f'{name}: {side} is {actual:.1f}% but the '
                            f'breakdown gives {expected:.1f}%')
    if element['paddingAndBorder']:
        problems.append(f'{name}: has padding or a border, which makes it '
                        'larger than its width and height say')
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


def check_element(shape, element, palette, to_percent):
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
    return (problems + check_corners(shape, element, to_percent) +
            check_placement(shape, element, box, to_percent))


def fills_the_canvas(shape, breakdown):
    """Says whether a shape is a backdrop covering the whole canvas."""
    canvas_height = breakdown['canvas']['height_as_percent_of_width']
    return (shape['primitive'] == 'rectangle' and shape['left'] == 0 and
            shape['top'] == 0 and shape['width'] == 100 and
            shape['height'] == canvas_height and shape['rotation_degrees'] == 0)


def check_shapes(breakdown, styles):
    """Returns problems with the scene's elements compared to the breakdown."""
    scene = styles['scene']
    scene_width = scene['drawnWidth']
    if scene_width <= 0:
        return ['the scene has no width, so nothing is drawn']

    def to_percent(pixels):
        """Converts pixels to percent of the scene's width as drawn."""
        return pixels * 100 / scene_width

    problems = []
    expected_height = (scene_width *
                       breakdown['canvas']['height_as_percent_of_width'] / 100)
    scene_height = scene['drawnHeight']
    if abs(scene_height - expected_height) > SCENE_SHAPE_TOLERANCE_PIXELS:
        problems.append('the scene is not the same shape as the original '
                        f'image: it is {scene_width:.0f} by {scene_height:.0f}')
    palette = {color['name']: color['hex'] for color in breakdown['palette']}
    shapes = list(breakdown['shapes'])
    # A backdrop that fills the canvas is drawn as the scene's own
    # background, so it needs no element of its own.
    if shapes and fills_the_canvas(shapes[0], breakdown):
        backdrop = shapes.pop(0)
        problems += check_paint(backdrop['name'], scene,
                                hex_to_rgb_text(palette[backdrop['color']]))
    elements = styles['elements']
    if len(elements) != len(shapes):
        problems.append(f'the scene has {len(elements)} element(s) but the '
                        f'breakdown has {len(shapes)} shape(s) to draw')
    for shape, element in zip(shapes, elements):
        problems += check_element(shape, element, palette, to_percent)
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
    """Returns problems with which properties running animations change."""
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
        score_and_pictures = compare.score_piece(
            piece_folder,
            pathlib.Path(scratch_folder) / 'render.png')
    current_percent = score_and_pictures[0]['match_percent']
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


def open_piece(piece_folder, browser, window, motion_is_reduced):
    """Opens the piece's page in a window of the given size."""
    width, height, color_scheme = window
    page = browser.new_page(viewport={'width': width, 'height': height})
    page.emulate_media(
        color_scheme=color_scheme,
        reduced_motion='reduce' if motion_is_reduced else 'no-preference')
    page.goto((piece_folder / 'index.html').resolve().as_uri())
    return page


def check_at_rest(piece_folder, breakdown, browser):
    """Returns problems with the still picture, in each window size.

    Reduced motion is requested so that animated shapes are measured in
    their resting place, the one the breakdown describes. Checking stops
    at the first window size with problems, since the rest would mostly
    repeat them.
    """
    for window in WINDOWS_TO_CHECK:
        page = open_piece(piece_folder, browser, window, motion_is_reduced=True)
        styles = page.evaluate(READ_SCENE_STYLES)
        problems = check_shapes(breakdown, styles)
        problems += check_transitions(styles, motion_is_reduced=True)
        still_running = page.evaluate(READ_ANIMATIONS)
        if still_running:
            problems.append(f'{len(still_running)} animation(s) still run '
                            'under prefers-reduced-motion: reduce')
        page.close()
        if problems:
            width, height, color_scheme = window
            where = (f' (in a {width} by {height} window, {color_scheme} '
                     'color scheme)')
            return [problem + where for problem in problems]
    return []


def check_in_motion(piece_folder, browser):
    """Returns problems with what moves when motion is allowed."""
    page = open_piece(piece_folder,
                      browser,
                      WINDOWS_TO_CHECK[0],
                      motion_is_reduced=False)
    problems = check_animations(page.evaluate(READ_ANIMATIONS))
    problems += check_transitions(page.evaluate(READ_SCENE_STYLES),
                                  motion_is_reduced=False)
    page.close()
    return problems


def check_structure(piece_folder, browser):
    """Returns the problems found by reading a piece's source and styles."""
    breakdown = json.loads((piece_folder / 'breakdown.json').read_text())
    problems = check_page_source((piece_folder / 'index.html').read_text())
    page = open_piece(piece_folder,
                      browser,
                      WINDOWS_TO_CHECK[0],
                      motion_is_reduced=True)
    problems += check_page_rules(page.evaluate(READ_PAGE_FACTS))
    if problems:
        # The remaining checks assume a well-formed page.
        page.close()
        return problems
    stylesheet_text = (piece_folder / 'style.css').read_text()
    problems += check_stylesheet(
        page.evaluate(READ_STYLESHEET_FACTS, stylesheet_text), stylesheet_text,
        breakdown)
    page.close()
    return (problems + check_at_rest(piece_folder, breakdown, browser) +
            check_in_motion(piece_folder, browser))


def find_missing_files(piece_folder):
    """Returns the names of files a piece needs but does not have."""
    missing = [
        file_name for file_name in FILES_EVERY_PIECE_NEEDS
        if not (piece_folder / file_name).exists()
    ]
    if not list(piece_folder.glob('original.*')):
        missing.append('original image')
    return missing


def find_piece_folders(arguments):
    """Returns the folders to check: those named, or every piece."""
    if arguments:
        return [pathlib.Path(argument) for argument in arguments]
    pieces_folder = REPOSITORY_ROOT / 'pieces'
    if not pieces_folder.is_dir():
        return []
    return sorted(
        folder for folder in pieces_folder.iterdir() if folder.is_dir())


def report(piece_folder, problems):
    """Prints one piece's verdict and its problems."""
    verdict = 'ok' if not problems else f'{len(problems)} problem(s)'
    print(f'{piece_folder.name}: {verdict}')
    for problem in problems:
        print(f'  - {problem}')


def main(arguments):
    """Checks the given pieces, or every piece, and reports problems."""
    piece_folders = find_piece_folders(arguments)
    if not piece_folders:
        # Passing with nothing checked would hide a renamed or emptied
        # pieces folder, so finding no pieces is itself a failure.
        print('no pieces found to check')
        return 1
    problems_by_piece = {}
    complete_pieces = []
    for piece_folder in piece_folders:
        missing = find_missing_files(piece_folder)
        if missing:
            problems_by_piece[piece_folder] = [
                'is missing ' + ', '.join(missing)
            ]
        else:
            complete_pieces.append(piece_folder)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for piece_folder in complete_pieces:
            problems_by_piece[piece_folder] = check_structure(
                piece_folder, browser)
        browser.close()
    # The score check opens its own browser through the comparison tool,
    # and only one may be open at a time, so it runs after the first closes.
    for piece_folder in complete_pieces:
        problems_by_piece[piece_folder] += check_score(piece_folder)
    for piece_folder in piece_folders:
        report(piece_folder, problems_by_piece[piece_folder])
    return 1 if any(problems_by_piece.values()) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
