"""Tests for tools/check_pieces.py.

Each test copies piece 01, breaks the copy in one specific way, and checks
that the checker notices. A checker that passes a broken piece is worse
than no checker, because it is trusted.
"""

import pathlib
import shutil
import sys

import pytest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / 'tools'))

import check_pieces  # pylint: disable=wrong-import-position

GOOD_PIECE = REPOSITORY_ROOT / 'pieces' / '01-sun-and-hills'

# Each entry: a name for the test, CSS added to the end of style.css, and
# words that must appear in the problem the checker reports.
BROKEN_STYLES = [
    ('moved with a transform',
     '.hill-lavender { transform: translate(8%, 8%) rotate(9.9deg); }',
     'does more than rotate'),
    ('shrunk with a transform',
     '.hill-green { transform: rotate(2.8deg) scale(0.5); }',
     'does more than rotate'),
    ('turned with the rotate property', '.sun { rotate: 45deg; }',
     'rotated 45.0 degrees'),
    ('moved with the translate property', '.sun { translate: 10% 0; }',
     'uses the translate property'),
    ('circles drawn as squares', '.scene > * { border-radius: 0; }',
     'needs border-radius: 50%'),
    ('gradient painted over a shape',
     '.sun { background: var(--sun) linear-gradient(red, red); }',
     'background image or gradient'),
    ('shape made see-through', '.sun { opacity: 0; }', 'hidden or see-through'),
    ('shape made invisible', '.sun { visibility: hidden; }',
     'hidden or see-through'),
    ('extra shape drawn with a pseudo-element',
     ".sun::after { content: ''; position: absolute; inset: 0; "
     'background: red; }', '::before or ::after'),
    ('shape in the wrong place', '.sun { left: 40%; }', 'left is 40.0%'),
    ('shape in the wrong color', '.sun { background: #ff0000; }',
     'painted rgb(255, 0, 0)'),
    ('scene in the wrong color', '.scene { background: #ff0000; }',
     'painted rgb(255, 0, 0)'),
    ('transition left on under reduced motion',
     '.hill-green { transition: transform 3s; }',
     'still has a transition under'),
    ('transition of a property that must not move',
     '@media (prefers-reduced-motion: no-preference) { '
     '.hill-green { transition: left 3s; } }', 'transitions left'),
    ('animation of a property that must not move',
     '@keyframes drift-down { to { top: 70%; } } '
     '.hill-lavender { animation: drift-down 3s infinite; } '
     '@media (prefers-reduced-motion: reduce) { '
     '.hill-lavender { animation: none; } }',
     'animation drift-down changes top'),
    ('animation left running under reduced motion',
     '@keyframes fade-out { to { opacity: 0.5; } } '
     '.hill-lavender { animation: fade-out 3s infinite; }',
     'still run under prefers-reduced-motion'),
    # Nothing in the style checks looks at shadows. The pixel score does.
    ('something the style checks do not know about',
     '.sun { box-shadow: 0 0 0 60px red; }', 'compare/score.json says'),
]

# Each entry: a name, text to find in index.html, its replacement, and
# words that must appear in the problem the checker reports.
BROKEN_MARKUP = [
    ('image element', '<div class="sun"></div>',
     '<div class="sun"></div><img src="original.webp" alt="">', 'uses <img>'),
    ('style block in the page', '<div class="sun"></div>',
     '<style>.sun { left: 0; }</style><div class="sun"></div>', 'uses <style>'),
    ('embedded object', '<div class="sun"></div>',
     '<div class="sun"></div><object data="original.webp"></object>',
     'uses <object>'),
    ('inline style', '<div class="sun"></div>',
     '<div class="sun" style="left: 0"></div>', 'inline style attribute'),
    ('event handler', '<div class="sun"></div>',
     '<div class="sun" onclick="return false"></div>', 'event handler'),
    ('element nested inside a shape', '<div class="sun"></div>',
     '<div class="sun"><div class="spot"></div></div>', 'nested inside it'),
    ('extra element in the scene', '<div class="sun"></div>',
     '<div class="sun"></div><div class="cloud"></div>',
     'the scene has 4 element(s)'),
    ('shapes in the wrong order', '<div class="hill hill-green"></div>\n      '
     '<div class="hill hill-lavender"></div>',
     '<div class="hill hill-lavender"></div>\n      '
     '<div class="hill hill-green"></div>', 'expected this shape next'),
    ('element outside the scene', '</body>', '<div class="extra"></div></body>',
     'only element in <body>'),
    ('second stylesheet', '<link rel="stylesheet" href="style.css">',
     '<link rel="stylesheet" href="style.css">'
     '<link rel="stylesheet" href="more.css">', 'exactly one stylesheet'),
    ('missing label', 'role="img"', 'role="presentation"',
     '.scene needs role="img"'),
]


@pytest.fixture(name='piece_copy')
def make_piece_copy(tmp_path):
    """Returns a scratch copy of piece 01 that a test may break."""
    piece_copy = tmp_path / GOOD_PIECE.name
    shutil.copytree(GOOD_PIECE, piece_copy)
    return piece_copy


def problems_reported_for(piece_folder, capsys):
    """Runs the checker on one piece and returns (exit code, its output)."""
    exit_code = check_pieces.main([str(piece_folder)])
    return exit_code, capsys.readouterr().out


def test_the_real_piece_passes(capsys):
    """Piece 01 as committed has no problems."""
    exit_code, output = problems_reported_for(GOOD_PIECE, capsys)

    assert exit_code == 0, output
    assert '01-sun-and-hills: ok' in output


def test_an_unbroken_copy_passes(piece_copy, capsys):
    """Copying alone causes no problems, so the tests below are fair."""
    exit_code, output = problems_reported_for(piece_copy, capsys)

    assert exit_code == 0, output


@pytest.mark.parametrize('added_css, expected_words',
                         [case[1:] for case in BROKEN_STYLES],
                         ids=[case[0] for case in BROKEN_STYLES])
def test_broken_style_is_reported(piece_copy, capsys, added_css,
                                  expected_words):
    """A piece with one style rule broken fails, and the output says why."""
    style_path = piece_copy / 'style.css'
    style_path.write_text(style_path.read_text() + '\n' + added_css + '\n')

    exit_code, output = problems_reported_for(piece_copy, capsys)

    assert exit_code == 1
    assert expected_words in output


@pytest.mark.parametrize('find_text, replacement, expected_words',
                         [case[1:] for case in BROKEN_MARKUP],
                         ids=[case[0] for case in BROKEN_MARKUP])
def test_broken_markup_is_reported(piece_copy, capsys, find_text, replacement,
                                   expected_words):
    """A piece with its HTML broken fails, and the output says why."""
    page_path = piece_copy / 'index.html'
    page_text = page_path.read_text()
    assert find_text in page_text, 'the test is out of date with index.html'
    page_path.write_text(page_text.replace(find_text, replacement))

    exit_code, output = problems_reported_for(piece_copy, capsys)

    assert exit_code == 1
    assert expected_words in output


def test_missing_files_are_reported_without_a_crash(piece_copy, capsys):
    """A folder that is not a complete piece gets a plain message."""
    (piece_copy / 'breakdown.json').unlink()

    exit_code, output = problems_reported_for(piece_copy, capsys)

    assert exit_code == 1
    assert 'is missing breakdown.json' in output


def test_finding_no_pieces_is_a_failure(tmp_path, monkeypatch, capsys):
    """An empty pieces folder must not pass by checking nothing."""
    (tmp_path / 'pieces').mkdir()
    monkeypatch.setattr(check_pieces, 'REPOSITORY_ROOT', tmp_path)

    exit_code = check_pieces.main([])

    assert exit_code == 1
    assert 'no pieces found' in capsys.readouterr().out
