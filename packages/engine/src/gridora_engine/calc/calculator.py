"""Dependency graph and recalculation for one workbook (PLAN.md §8, ADR-003 part 2 option C).

Cell identity: fk = (sheet_index << 40) | (row << 14) | col.
Rules (PLAN.md §8): no recalculation at import; formulas with unsupported functions, parse errors
or array/data-table kind keep their cached value ("frozen") and are reported, as are cells
downstream of them ("stale") and cells in circular references (they keep their cached value).
"""
from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from ..formula import xlerrors as E
from ..formula.evaluator import evaluate_formula
from ..formula.functions import REGISTRY
from ..formula.parser import (
    FormulaSyntaxError,
    Func,
    Name,
    Node,
    Ref,
    StructRef,
    parse,
    substitute,
    walk,
)
from ..model.edits import Snap, set_cell, snapshot
from ..model.shared import child_text, group_members
from ..model.values import BOOL, ERR, ERR_CODES, NUM, STR
from ..model.workbook import WorkbookState
from .env import WorkbookEnv
from .tables import load_tables, resolve_struct

Rect = tuple[int, int, int, int, int]  # sheet, r0, c0, r1, c1
_ERR_INDEX = {c: i for i, c in enumerate(ERR_CODES)}
_VOLATILE_NAMES = {"INDIRECT", "OFFSET"}
_NARROW = 32  # ranges up to this many columns are indexed per column, wider ones in a side list
ARRAY, DATA_TABLE = 4, 5


def fk_of(s: int, r: int, c: int) -> int:
    return (s << 40) | (r << 14) | c


def split_fk(fk: int) -> tuple[int, int, int]:
    return fk >> 40, (fk >> 14) & 0xFFFFF, fk & 0x3FFF


class Calculator:
    def __init__(self, state: WorkbookState, now: Callable[[], datetime] | None = None,
                 calendar: str = "gregorian") -> None:
        self.state = state
        self.now = now
        self.calendar = calendar
        self.env = WorkbookEnv(state, self)
        self.built = False
        self.asts: dict[int, Node] = {}
        self.refs: dict[int, list[Rect]] = {}
        self.frozen: dict[int, str] = {}
        self.volatile: set[int] = set()
        self.cell_deps: dict[tuple[int, int, int], set[int]] = {}
        self.rect_users: dict[Rect, set[int]] = {}
        self.col_rects: dict[tuple[int, int], list[Rect]] = {}
        self.wide_rects: list[Rect] = []
        self.circular: set[int] = set()
        self.stale: set[int] = set()
        self._tables: dict[str, Any] | None = None

    # -- graph construction ----------------------------------------------------------------------
    def ensure_built(self) -> None:
        if self.built:
            return
        self.built = True  # set first: registration may call back into helpers
        for si, sheet in enumerate(self.state.sheets):
            lazy = sheet.lazy
            if lazy is not None:
                src = getattr(lazy, "source", None)
                has = (src.formula_count if src is not None else 1) or sheet.formulas or sheet.fkind
                if has:
                    lazy.materialize_all()
        for si, sheet in enumerate(self.state.sheets):
            for key, text in list(sheet.formulas.items()):
                self.set_formula(si, key, text)
            for key, kind in sheet.fkind.items():
                if kind == 3:
                    t = child_text(sheet, key)
                    if t is not None:
                        self.set_formula(si, key, t)
                elif kind in (ARRAY, DATA_TABLE):
                    fk = fk_of(si, key >> 14, key & 0x3FFF)
                    self.frozen[fk] = "array_formula" if kind == ARRAY else "data_table"
        # cells of an array range other than the anchor hold plain cached values (nothing to freeze)

    def has_formulas(self) -> bool:
        if self.built:
            return bool(self.asts or self.frozen)
        return any(
            s.formulas or s.fkind or (getattr(getattr(s.lazy, "source", None), "formula_count", 0))
            for s in self.state.sheets
        )

    def set_formula(self, si: int, key: int, text: str | None) -> None:
        fk = (si << 40) | key
        self._unregister(fk)
        if not text:
            return
        try:
            ast = parse(text)
        except FormulaSyntaxError:
            self.frozen[fk] = "parse_error"
            return
        if any(isinstance(n, StructRef) for n in walk(ast)):
            if self._tables is None:
                self._tables = load_tables(self.state)
            r_, c_ = key >> 14, key & 0x3FFF
            tables = self._tables
            ast = substitute(
                ast,
                lambda n: resolve_struct(n, tables, self.state, si, r_, c_) if isinstance(n, StructRef) else n,
            )
        bad = _unsupported(ast)
        if bad:
            self.frozen[fk] = "function:" + bad
            self.asts[fk] = ast
            return
        self.asts[fk] = ast
        rects, vol = self._collect(ast, si)
        self.refs[fk] = rects
        if vol:
            self.volatile.add(fk)
        for rect in rects:
            self._index(rect, fk)

    def _unregister(self, fk: int) -> None:
        self.frozen.pop(fk, None)
        self.asts.pop(fk, None)
        self.volatile.discard(fk)
        self.circular.discard(fk)
        for rect in self.refs.pop(fk, ()):
            users = self.rect_users.get(rect)
            if users is None:
                continue
            users.discard(fk)
            if not users:
                del self.rect_users[rect]
                s, r0, c0, r1, c1 = rect
                if r0 == r1 and c0 == c1:
                    self.cell_deps.pop((s, r0, c0), None)
                elif c1 - c0 < _NARROW:
                    for c in range(c0, c1 + 1):
                        lst = self.col_rects.get((s, c))
                        if lst and rect in lst:
                            lst.remove(rect)
                elif rect in self.wide_rects:
                    self.wide_rects.remove(rect)

    def _index(self, rect: Rect, fk: int) -> None:
        s, r0, c0, r1, c1 = rect
        users = self.rect_users.get(rect)
        if users is None:
            users = self.rect_users[rect] = set()
            if r0 == r1 and c0 == c1:
                pass
            elif c1 - c0 < _NARROW:
                for c in range(c0, c1 + 1):
                    self.col_rects.setdefault((s, c), []).append(rect)
            else:
                self.wide_rects.append(rect)
        users.add(fk)
        if r0 == r1 and c0 == c1:
            self.cell_deps.setdefault((s, r0, c0), set()).add(fk)

    def _collect(self, ast: Node, si: int, depth: int = 0) -> tuple[list[Rect], bool]:
        rects: list[Rect] = []
        volatile = False
        for n in walk(ast):
            if isinstance(n, Ref):
                s = si if n.sheet is None else self.env.sheet_index(n.sheet)
                if s is not None:
                    rects.append((s, n.r0, n.c0, n.r1, n.c1))
            elif isinstance(n, Func):
                spec = REGISTRY.get(n.name)
                if n.name in _VOLATILE_NAMES or (spec is not None and spec.volatile):
                    volatile = True
            elif isinstance(n, Name) and depth < 8:
                target = self.env.defined_name(n.name, si)
                if target:
                    try:
                        sub = parse(target)
                    except FormulaSyntaxError:
                        continue
                    r2, v2 = self._collect(sub, si, depth + 1)
                    rects.extend(r2)
                    volatile = volatile or v2
        return list(dict.fromkeys(rects)), volatile

    # -- dependents -------------------------------------------------------------------------------
    def dependents_of_cell(self, s: int, r: int, c: int) -> set[int]:
        out: set[int] = set()
        d = self.cell_deps.get((s, r, c))
        if d:
            out |= d
        for rect in self.col_rects.get((s, c), ()):
            if rect[1] <= r <= rect[3]:
                out |= self.rect_users[rect]
        for rect in self.wide_rects:
            if rect[0] == s and rect[1] <= r <= rect[3] and rect[2] <= c <= rect[4]:
                out |= self.rect_users[rect]
        return out

    def dependents_of_rect(self, s: int, r0: int, c0: int, r1: int, c1: int) -> set[int]:
        out: set[int] = set()
        for rect, users in self.rect_users.items():
            if rect[0] == s and rect[1] <= r1 and r0 <= rect[3] and rect[2] <= c1 and c0 <= rect[4]:
                out |= users
        return out

    def is_subtotal(self, fk: int) -> bool:
        a = self.asts.get(fk)
        return isinstance(a, Func) and a.name in ("SUBTOTAL", "AGGREGATE")

    # -- recalculation -------------------------------------------------------------------------------
    def recalc(
        self,
        seed_cells: Iterable[tuple[int, int, int]] = (),
        seed_fks: Iterable[int] = (),
        *,
        full: bool = False,
        seed_rects: Iterable[tuple[int, int, int, int, int]] = (),
    ) -> list[tuple[int, int, int, Snap]]:
        """Recompute every formula affected by the seeds (plus volatile ones). Returns
        (sheet_index, row, col, snapshot before the first change) for each cell whose value changed."""
        self.ensure_built()
        self.env.reset_clock()
        self.stale.clear()
        affected: set[int] = set()
        stack: list[int] = []
        if full:
            affected.update(self.asts)
            affected.update(self.frozen)
            stack = list(affected)
        else:
            for fk in seed_fks:
                if fk not in affected:
                    affected.add(fk)
                    stack.append(fk)
            for fk in self.volatile:
                if fk not in affected:
                    affected.add(fk)
                    stack.append(fk)
            for s, r, c in seed_cells:
                for d in self.dependents_of_cell(s, r, c):
                    if d not in affected:
                        affected.add(d)
                        stack.append(d)
            for s, r0, c0, r1, c1 in seed_rects:
                for d in self.dependents_of_rect(s, r0, c0, r1, c1):
                    if d not in affected:
                        affected.add(d)
                        stack.append(d)
        while stack:
            fk = stack.pop()
            s, r, c = split_fk(fk)
            for d in self.dependents_of_cell(s, r, c):
                if d not in affected:
                    affected.add(d)
                    stack.append(d)
        evaluable = {fk for fk in affected if fk in self.asts and fk not in self.frozen}
        # cells downstream of frozen cells are computed from stale inputs: report them
        for fk in affected:
            if fk in self.frozen:
                s, r, c = split_fk(fk)
                for d in self.dependents_of_cell(s, r, c):
                    if d in evaluable:
                        self.stale.add(d)
        self._propagate_stale(evaluable)
        order, cyc = self._order(evaluable)
        self.circular = (self.circular - evaluable) | cyc
        changes: list[tuple[int, int, int, Snap]] = []
        seen: set[int] = set()
        for fk in order:
            ch = self._evaluate_cell(fk)
            if ch is not None and fk not in seen:
                seen.add(fk)
                changes.append(ch)
        return changes

    def _propagate_stale(self, evaluable: set[int]) -> None:
        stack = list(self.stale)
        while stack:
            fk = stack.pop()
            s, r, c = split_fk(fk)
            for d in self.dependents_of_cell(s, r, c):
                if d in evaluable and d not in self.stale:
                    self.stale.add(d)
                    stack.append(d)

    def _preds(self, fk: int, pos: dict[tuple[int, int, int], int], cols: dict[tuple[int, int], list[int]],
               rows_by_col: dict[tuple[int, int], list[tuple[int, int]]], aff_cols: dict[int, list[int]]) -> Iterable[int]:
        for s, r0, c0, r1, c1 in self.refs.get(fk, ()):
            if r0 == r1 and c0 == c1:
                p = pos.get((s, r0, c0))
                if p is not None and p != fk or p == fk:
                    yield p
                continue
            sc = aff_cols.get(s)
            if not sc:
                continue
            lo = bisect.bisect_left(sc, c0)
            hi = bisect.bisect_right(sc, c1)
            for c in sc[lo:hi]:
                lst = rows_by_col[(s, c)]
                a = bisect.bisect_left(lst, (r0, -1))
                b = bisect.bisect_right(lst, (r1, 1 << 62))
                for _r, p in lst[a:b]:
                    yield p

    def _order(self, nodes: set[int]) -> tuple[list[int], set[int]]:
        """Evaluation order (dependencies first) and the set of cells in circular references.
        Iterative Tarjan SCC over the dependency edges."""
        pos: dict[tuple[int, int, int], int] = {}
        rows_by_col: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for fk in nodes:
            s, r, c = split_fk(fk)
            pos[(s, r, c)] = fk
            rows_by_col.setdefault((s, c), []).append((r, fk))
        for lst in rows_by_col.values():
            lst.sort()
        aff_cols: dict[int, list[int]] = {}
        for s, c in rows_by_col:
            aff_cols.setdefault(s, []).append(c)
        for lst2 in aff_cols.values():
            lst2.sort()
        index: dict[int, int] = {}
        low: dict[int, int] = {}
        on: set[int] = set()
        tstack: list[int] = []
        order: list[int] = []
        cyc: set[int] = set()
        selfloop: set[int] = set()
        counter = 0
        for root in sorted(nodes):
            if root in index:
                continue
            work: list[tuple[int, Any]] = [(root, None)]
            while work:
                v, it = work.pop()
                if it is None:
                    index[v] = low[v] = counter
                    counter += 1
                    tstack.append(v)
                    on.add(v)
                    it = iter(list(self._preds(v, pos, {}, rows_by_col, aff_cols)))
                advanced = False
                for w in it:
                    if w == v:
                        selfloop.add(v)
                        continue
                    if w not in index:
                        work.append((v, it))
                        work.append((w, None))
                        advanced = True
                        break
                    if w in on:
                        low[v] = min(low[v], index[w])
                if advanced:
                    continue
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = tstack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1 or v in selfloop:
                        cyc.update(comp)
                    else:
                        order.append(v)
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
        return order, cyc

    def _evaluate_cell(self, fk: int) -> tuple[int, int, int, Snap] | None:
        s, r, c = split_fk(fk)
        ast = self.asts[fk]
        value = evaluate_formula(ast, self.env, s, r, c)
        tag, val = self._to_internal(value)
        sheet = self.state.sheets[s]
        old_tag, old_val, style = sheet.store.get(r, c)
        if old_tag == tag and (old_val == val):
            return None
        key = (r << 14) | c
        if sheet.fkind.get(key) in (2, 3):  # a recalculated shared-group member is rewritten: un-share its group
            self.unshare(s, [key])
        before = snapshot(sheet, r, c)
        set_cell(sheet, r, c, (tag, val, style, sheet.formulas.get(key)))
        return s, r, c, before

    def _to_internal(self, v: Any) -> tuple[int, float]:
        if v is None:
            return NUM, 0.0
        if isinstance(v, bool):
            return BOOL, 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return NUM, float(v)
        if isinstance(v, str):
            if len(v) > self.state_limit():
                return ERR, float(_ERR_INDEX["#VALUE!"])
            return STR, float(self.state.strings.intern(v))
        if isinstance(v, E.XlError):
            idx = _ERR_INDEX.get(v.code)
            return ERR, float(idx if idx is not None else _ERR_INDEX["#VALUE!"])
        return ERR, float(_ERR_INDEX["#VALUE!"])

    def state_limit(self) -> int:
        return 32767

    # -- shared formulas: un-share before editing a member -------------------------------------------
    def unshare(self, si_sheet: int, keys: Iterable[int]) -> None:
        """Turn every shared group touched by `keys` into plain formulas so a member can change on
        its own (the exporter then rewrites the whole group)."""
        sheet = self.state.sheets[si_sheet]
        groups = {sheet.shared_si[k] for k in keys if sheet.fkind.get(k) in (2, 3) and k in sheet.shared_si}
        for si in groups:
            members = group_members(sheet, si)
            texts = {k: (sheet.formulas.get(k) if sheet.fkind.get(k) == 2 else child_text(sheet, k)) for k in members}
            for k in members:
                t = texts[k]
                tag, val, style = sheet.store.get(k >> 14, k & 0x3FFF)
                sheet.fkind.pop(k, None)
                sheet.shared_si.pop(k, None)
                if t is not None:
                    set_cell(sheet, k >> 14, k & 0x3FFF, (tag, val, style, t))
            sheet._shared_cache = None

    # -- reporting ------------------------------------------------------------------------------------
    def findings(self) -> dict[str, Any]:
        fn_names: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        for reason in self.frozen.values():
            if reason.startswith("function:"):
                fn_names[reason[9:]] += 1
                counts["unsupported_function"] += 1
            else:
                counts[reason] += 1
        return {
            "unsupported_functions": dict(fn_names), "counts": dict(counts),
            "circular": len(self.circular), "stale": len(self.stale),
        }


def _unsupported(ast: Node) -> str | None:
    for n in walk(ast):
        if isinstance(n, Func) and n.name not in REGISTRY:
            return n.name
    return None


def resync_rect(calc: Calculator, si: int, r0: int, c0: int, r1: int, c1: int) -> None:
    """Re-register every formula inside a rectangle after a bulk write replaced its contents."""
    sheet = calc.state.sheets[si]
    for fk in [fk for fk in (*calc.asts, *calc.frozen) if fk >> 40 == si]:
        _s, r, c = split_fk(fk)
        if r0 <= r <= r1 and c0 <= c <= c1:
            calc.set_formula(si, (r << 14) | c, None)
    for key, text in list(sheet.formulas.items()):
        r, c = key >> 14, key & 0x3FFF
        if r0 <= r <= r1 and c0 <= c <= c1:
            calc.set_formula(si, key, text)
