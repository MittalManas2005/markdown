"""
Acceptance tests for issue #6: the `--tab_length` command line option.

Each test is named after the acceptance criterion it checks.
"""

import os
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as etree

import markdown


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = "- a\n\n  - b\n"


def run_cli(args, command=None):
    """ Run the command line with `TEXT` on standard input. """
    if command is None:
        command = [sys.executable, '-m', 'markdown']
    return subprocess.run(
        command + args,
        input=TEXT,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )


def wrap(html):
    """ Parse command line output wrapped in a single element. """
    return etree.fromstring('<div>%s</div>' % html)


class TestAcFr001(unittest.TestCase):
    """ Tests for `FR-001`: the command line accepts `--tab_length`. """

    def test_ac_fr_001_1_help_lists_tab_length(self):
        """ `AC-FR-001-1`: the `--help` output contains `--tab_length`. """
        result = run_cli(['--help'])
        self.assertIn('--tab_length', result.stdout)

    def test_ac_fr_001_2_tab_length_nests_list(self):
        """ `AC-FR-001-2`: with `--tab_length=2`, `b` is nested inside `a`. """
        result = run_cli(['--tab_length=2'])
        self.assertEqual(result.returncode, 0)
        root = wrap(result.stdout)
        nested = root.find('./ul/li/ul/li')
        self.assertIsNotNone(nested)
        self.assertEqual(''.join(nested.itertext()).strip(), 'b')


class TestAcFr002(unittest.TestCase):
    """ Tests for `FR-002`: both option forms are accepted. """

    def test_ac_fr_002_1_both_forms_give_identical_output(self):
        """ `AC-FR-002-1`: `--tab_length 2` and `--tab_length=2` give the same output. """
        separated = run_cli(['--tab_length', '2'])
        joined = run_cli(['--tab_length=2'])
        self.assertEqual(separated.returncode, 0)
        self.assertEqual(joined.returncode, 0)
        self.assertEqual(separated.stdout, joined.stdout)

    def test_ac_fr_002_2_tab_length_runs_without_error(self):
        """ `AC-FR-002-2`: `--tab_length=2` exits without error and produces output. """
        result = run_cli(['--tab_length=2'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


class TestAcFr003(unittest.TestCase):
    """ Tests for `FR-003`: the option matches the `tab_length` library keyword. """

    def test_ac_fr_003_1_output_matches_library(self):
        """ `AC-FR-003-1`: the output equals `markdown.markdown()` with `tab_length=2`. """
        result = run_cli(['--tab_length=2'])
        self.assertEqual(result.returncode, 0)
        expected = markdown.markdown(TEXT, tab_length=2)
        self.assertEqual(result.stdout.strip(), expected.strip())


class TestAcFr004(unittest.TestCase):
    """ Tests for `FR-004`: output is unchanged when the option is absent. """

    def test_ac_fr_004_1_without_option_b_is_not_nested(self):
        """ `AC-FR-004-1`: without the option, `b` is a top-level item, not nested in `a`. """
        result = run_cli([])
        self.assertEqual(result.returncode, 0)
        # The input is a loose list, so each item wraps its text in a `<p>`.
        self.assertIn('<li>\n<p>b</p>\n</li>', result.stdout)
        root = wrap(result.stdout)
        self.assertIsNone(root.find('.//li/ul'))
        self.assertEqual([''.join(li.itertext()).strip() for li in root.findall('./ul/li')], ['a', 'b'])

    def test_ac_fr_004_2_without_option_matches_default_library(self):
        """ `AC-FR-004-2`: without the option, the output equals `markdown.markdown()` with defaults. """
        result = run_cli([])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), markdown.markdown(TEXT).strip())


class TestAcFr005(unittest.TestCase):
    """ Tests for `FR-005`: the `markdown_py` command accepts the option. """

    @unittest.skipIf(shutil.which('markdown_py') is None, '`markdown_py` is not on PATH')
    def test_ac_fr_005_1_markdown_py_matches_module(self):
        """ `AC-FR-005-1`: `markdown_py --tab_length=2` equals `python -m markdown --tab_length=2`. """
        module = run_cli(['--tab_length=2'])
        script = run_cli(['--tab_length=2'], command=['markdown_py'])
        self.assertEqual(script.returncode, 0, script.stderr)
        self.assertEqual(script.stdout, module.stdout)


if __name__ == '__main__':
    unittest.main()
