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

Copyright 2007-2023 The Python Markdown Project (v. 1.7 and later)
Copyright 2004, 2005, 2006 Yuri Takhteyev (v. 0.2-1.6b)
Copyright 2004 Manfred Stienstra (the original version)

License: BSD (see LICENSE.md for details).
"""

from markdown.test_tools import TestCase


class TestReferenceCodeLabels(TestCase):

    def test_shortcut_reference_with_code_label(self):
        self.assertMarkdownRenders(
            '[`foo`]\n\n[`foo`]: https://example.com',
            '<p><a href="https://example.com"><code>foo</code></a></p>'
        )

    def test_full_reference_with_code_label(self):
        self.assertMarkdownRenders(
            '[text][`foo`]\n\n[`foo`]: https://example.com',
            '<p><a href="https://example.com">text</a></p>'
        )

    def test_inline_link_with_code_unchanged(self):
        self.assertMarkdownRenders(
            '[`foo`](https://example.com)',
            '<p><a href="https://example.com"><code>foo</code></a></p>'
        )
