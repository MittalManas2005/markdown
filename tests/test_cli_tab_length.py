"""
Tests for the command-line `--tab_length` option (issue #6).

Each acceptance criterion from the spec has a test named `test_ac_<id>_...`
and the criterion ID is given in the description text of each test.
"""

import contextlib
import io
import os
import subprocess
import sys
import unittest

import markdown
from markdown.__main__ import parse_options


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(markdown.__file__)))
SOURCE = "- a\n\n  - b\n"


def run_cli(args, text):
    """ Run `python -m markdown` with `args`, feeding `text` on standard input; return standard output. """
    result = subprocess.run(
        [sys.executable, '-m', 'markdown'] + args,
        input=text.encode('utf-8'),
        capture_output=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout.decode('utf-8')


class TestCliTabLength(unittest.TestCase):
    """ Acceptance tests for the `--tab_length` command-line option. """

    def test_ac_fr_001_1_equals_form_is_parsed(self):
        """ AC-FR-001-1: `--tab_length=2` is parsed into the options. """
        options, _ = parse_options(['--tab_length=2'])
        self.assertIn('tab_length', options)
        self.assertEqual(options['tab_length'], 2)

    def test_ac_fr_001_2_separate_form_is_parsed(self):
        """ AC-FR-001-2: `--tab_length 2` is parsed into the options. """
        options, _ = parse_options(['--tab_length', '2'])
        self.assertIn('tab_length', options)
        self.assertEqual(options['tab_length'], 2)

    def test_ac_fr_002_1_output_matches_keyword(self):
        """ AC-FR-002-1: With `--tab_length=2` the CLI output equals `markdown.markdown(..., tab_length=2)`. """
        expected = markdown.markdown(SOURCE, tab_length=2)
        actual = run_cli(['--tab_length=2'], SOURCE)
        self.assertEqual(actual, expected)
        # The nested item must actually be nested (`b` inside a second `<ul>`).
        self.assertEqual(actual.count('<ul>'), 2)

    def test_ac_fr_003_1_no_option_keeps_default_options(self):
        """ AC-FR-003-1: Without the option the options dictionary is unchanged (no `tab_length` key). """
        options, logging_level = parse_options([])
        self.assertEqual(options, {
            'input': None,
            'output': None,
            'encoding': None,
            'output_format': 'xhtml',
            'lazy_ol': True,
            'extensions': [],
            'extension_configs': {},
        })
        self.assertNotIn('tab_length', options)

    def test_ac_fr_003_2_no_option_output_unchanged(self):
        """ AC-FR-003-2: Without the option the CLI output equals the default `markdown.markdown()` output. """
        expected = markdown.markdown(SOURCE)
        actual = run_cli([], SOURCE)
        self.assertEqual(actual, expected)

    def test_asm_001_non_integer_value_is_rejected(self):
        """ `ASM-001`: A non-integer `--tab_length` value is rejected by the option parser. """
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                parse_options(['--tab_length=abc'])
        self.assertEqual(cm.exception.code, 2)
