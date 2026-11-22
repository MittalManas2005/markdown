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


class TestFencedCodeBoolOptions(TestCase):

    def test_valueless_linenums_does_not_crash(self):
        self.assertMarkdownRenders(
            '``` { .python linenums }\nprint(1)\n```',
            '<pre><code class="language-python" linenums="True">print(1)\n</code></pre>',
            extensions=['fenced_code', 'attr_list']
        )

    def test_linenums_true_does_not_crash(self):
        self.assertMarkdownRenders(
            '``` { .python linenums=true }\nprint(1)\n```',
            '<pre><code class="language-python" linenums="True">print(1)\n</code></pre>',
            extensions=['fenced_code', 'attr_list']
        )

    def test_other_attributes_kept(self):
        self.assertMarkdownRenders(
            '``` { .python data-x="y" }\nprint(1)\n```',
            '<pre><code class="language-python" data-x="y">print(1)\n</code></pre>',
            extensions=['fenced_code', 'attr_list']
        )
