import unittest
import markdown

CASES = [
    "[`code`](http://x)",
    "[a `code` b](http://x)",
    "[`a]b`](http://x)",
    "[`code`](http://x 'title')",
    "[`code`][1]\n\n[1]: http://x",
    "[`a(b`](http://x)",
    "[`a`](http://x/`b`)",
    "[code `x` link](http://x_y_z)",
    "[`code`\n](http://x)",
    "[link `code](http://x)` more",
    "[`x`](<http://x>)",
    "[*`x`*](http://x)",
    "[**`x`**](http://x)",
    "[`x` *y*](http://x)",
    "[`a` \\[b](http://x)",
    "[`x`](http://example.com/path_with_underscores)",
    "[`x`]",
    "[`x`] text",
    "[`a`](http://x) [`b`](http://y)",
    "[`a`][]\n\n[a]: http://x",
    "[`a`](http://x \"t\")",
    "[`a[b`](http://x)",
    "[`a`](http://x`y)",
    "- [`code`](http://x)",
    "[`code`](http://x)`",
    "[``a`b``](http://x)",
]


class Probe(unittest.TestCase):
    def test_probe(self):
        for src in CASES:
            with self.subTest(src=src):
                out = markdown.markdown(src)
                print(repr(src), '=>', repr(out))
        self.fail('probe')
