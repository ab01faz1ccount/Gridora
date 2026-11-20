"""Dictionary-backed Env for formula unit tests."""
from __future__ import annotations

from gridora_engine.formula.evaluator import evaluate_formula, parse_cached
from gridora_engine.formula.xlerrors import XlError


class DictEnv:
    date1904 = False

    def __init__(self, cells=None, sheets=("Sheet1",), names=None):
        self.cells = cells or {}
        self.sheets = list(sheets)
        self.names = names or {}

    def sheet_index(self, name):
        for i, s in enumerate(self.sheets):
            if s.lower() == name.lower():
                return i
        return None

    def cell(self, s, r, c):
        return self.cells.get((s, r, c))

    def used_size(self, s):
        rs = [k[1] for k in self.cells if k[0] == s]
        cs = [k[2] for k in self.cells if k[0] == s]
        return (max(rs) + 1 if rs else 0, max(cs) + 1 if cs else 0)

    def defined_name(self, n, s):
        return self.names.get(n)

    def now_serial(self):
        return 46000.5


def ev(text, env=None, at=(0, 0, 0), array=False):
    env = env or DictEnv()
    node = parse_cached(text)
    assert node is not None, text
    return evaluate_formula(node, env, *at, array=array)


def show(v):
    return v.code if isinstance(v, XlError) else v
