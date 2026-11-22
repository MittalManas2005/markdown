"""
Python Markdown

A Python implementation of John Gruber's Markdown.

Documentation: https://python-markdown.github.io/
GitHub: https://github.com/Python-Markdown/markdown/
PyPI: https://pypi.org/project/Markdown/

Started by Manfred Stienstra (http://www.dwerg.net/).
Maintained for a few years by Yuri Takhteyev (http://www.freewisdom.org).
Currently maintained by Waylan Limberg (https://github.com/waylan),
Dmitry Shachnev (https://github.com/mitya57) and Isaac Muse (https://github.com/facelessuser).

Copyright 2007-2019 The Python Markdown Project (v. 1.7 and later)
Copyright 2004, 2005, 2006 Yuri Takhteyev (v. 0.2-1.6b)
Copyright 2004 Manfred Stienstra (the original version)

License: BSD (see LICENSE.md for details).
"""

import markdown
from markdown.test_tools import TestCase


class TestIssue7CodeInLinkLabel(TestCase):
    """Acceptance tests for issue #7: links with code spans in the label."""

    def test_ac_fr_001_2_inline_link_plain_text(self):
        """`AC-FR-001-2`: an inline link with plain text is unchanged."""

        html = markdown.markdown('[plain](https://example.com)')
        self.assertIn('<a href="https://example.com">plain</a>', html)

    def test_ac_fr_001_3_reference_shortcut_code_label(self):
        """`AC-FR-001-3`: a shortcut reference with a code span becomes a link."""

        source = self.dedent(
            """
            [`foo`]

            [`foo`]: https://example.com
            """
        )
        html = markdown.markdown(source)
        self.assertIn('<a href="https://example.com"><code>foo</code></a>', html)

    def test_ac_fr_001_4_reference_full_code_label(self):
        """`AC-FR-001-4`: a full reference with a code span in the `id` becomes a link."""

        source = self.dedent(
            """
            [text][`foo`]

            [`foo`]: https://example.com
            """
        )
        html = markdown.markdown(source)
        self.assertIn('<a href="https://example.com">text</a>', html)

    def test_ac_fr_001_5_reference_plain_label(self):
        """`AC-FR-001-5`: a full reference with a plain id still becomes a link."""

        source = self.dedent(
            """
            [text][foo]

            [foo]: https://example.com
            """
        )
        html = markdown.markdown(source)
        self.assertIn('<a href="https://example.com">text</a>', html)

    def test_ac_fr_002_1_inline_link_code_label(self):
        """`AC-FR-002-1`: an inline link whose text is a code span still works."""

        html = markdown.markdown('[`foo`](https://example.com)')
        self.assertIn('<a href="https://example.com"><code>foo</code></a>', html)
