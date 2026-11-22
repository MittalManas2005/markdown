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


class TestTocValuelessId(TestCase):

    def test_valueless_id_gets_generated_id(self):
        self.assertMarkdownRenders(
            '# Heading {: id }',
            '<h1 id="heading">Heading</h1>',
            extensions=['toc', 'attr_list']
        )

    def test_valueless_id_is_listed_in_toc(self):
        self.assertMarkdownRenders(
            '[TOC]\n\n# Heading {: id }',
            '<div class="toc">\n'
            '<ul>\n'
            '<li><a href="#heading">Heading</a></li>\n'
            '</ul>\n'
            '</div>\n'
            '<h1 id="heading">Heading</h1>',
            extensions=['toc', 'attr_list']
        )

    def test_explicit_id_is_kept(self):
        self.assertMarkdownRenders(
            '# Heading {: id="custom" }',
            '<h1 id="custom">Heading</h1>',
            extensions=['toc', 'attr_list']
        )
