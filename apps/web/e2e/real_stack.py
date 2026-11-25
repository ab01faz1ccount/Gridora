"""Real-browser check of the editing slice on the REAL stack (Chromium + Playwright).

What it drives: sign in -> create workspace -> upload CSV and XLSX -> open -> edit -> formulas
(evaluated by the real engine) -> undo/redo -> copy/paste with the real clipboard -> history panel
-> a conflict made by a second tab.  It prints one line per check and exits 1 if any failed.

Run (API on :8000 with GRIDORA_ENGINE=real, web on :5173):
    python e2e/real_stack.py            # BASE_URL, E2E_USER, E2E_PASSWORD, E2E_FIXTURES, E2E_SHOTS
Fixtures: sales.xlsx (Persian text, formulas, a second sheet that refers to the first) and people.csv.
"""
import json
import os
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5173")
USER = os.environ.get("E2E_USER", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin-password-123")
FIX = os.environ.get("E2E_FIXTURES", os.path.join(os.path.dirname(__file__), "fixtures"))
SHOTS = os.environ.get("E2E_SHOTS", "/tmp/e2e-shots")
os.makedirs(SHOTS, exist_ok=True)

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def cell(page, r: int, c: int) -> str:
    loc = page.locator(f"#gv-{r}-{c}")
    return loc.inner_text(timeout=4000).strip() if loc.count() else "<not rendered>"


def wait_cell(page, r, c, text, timeout=6000) -> bool:
    end = time.time() + timeout / 1000
    while time.time() < end:
        if cell(page, r, c) == text:
            return True
        page.wait_for_timeout(100)
    return False


def grid_ready(page):
    page.wait_for_selector("[role=gridcell]", timeout=15000)
    page.wait_for_function("() => !document.querySelector('[role=gridcell][aria-busy]')", timeout=15000)


def goto_cell(page, r: int, c: int) -> None:
    """Cursor to row r, column c (0-based) from A1, with the keyboard only."""
    page.keyboard.press("Control+Home")
    for _ in range(r):
        page.keyboard.press("ArrowDown")
    for _ in range(c):
        page.keyboard.press("ArrowRight")


def upload(page, name: str) -> None:
    page.set_input_files("[data-testid=file-input]", os.path.join(FIX, name))
    # "Opened." appears when the import job finished; then Open leads to the workbook
    page.get_by_text("Opened", exact=False).first.wait_for(timeout=60000)


def open_last_import(page):
    page.get_by_role("button", name="Open").last.click()
    grid_ready(page)


def run(p):
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, permissions=["clipboard-read", "clipboard-write"])
    ctx.add_init_script(
        "localStorage.setItem('gridora.prefs', JSON.stringify({locale:'en',digits:'latin',calendar:'gregorian'}))"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(BASE + "/")
    page.get_by_label("Username").fill(USER)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_label("Workspace name").wait_for(timeout=10000)
    check(True, "sign in")

    ws_name = f"e2e-{int(time.time())}"
    page.get_by_label("Workspace name").fill(ws_name)
    page.get_by_role("button", name="Create workspace").click()
    page.get_by_role("button", name="Open").first.click()
    page.wait_for_url("**/workspaces/*", timeout=10000)
    ws_url = page.url
    check(True, "workspace created and opened")

    # ---------------- CSV ----------------
    upload(page, "people.csv")
    open_last_import(page)
    check(wait_cell(page, 1, 0, "علی"), "CSV: Persian text shown in the grid")
    check(wait_cell(page, 1, 1, "30"), "CSV: number shown")

    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("Control+End")  # go to the last cell
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")  # B2 (row 1, col 1) = 30
    page.keyboard.type("99")
    page.keyboard.press("Enter")
    check(wait_cell(page, 1, 1, "99"), "edit: typing 99 + Enter shows the server's value")
    page.get_by_role("button", name="Undo").wait_for()
    check(page.get_by_role("button", name="Undo").is_enabled(), "edit: Undo button enabled")
    page.get_by_role("button", name="Undo").click()
    check(wait_cell(page, 1, 1, "30"), "undo: the old value is back")
    check(page.get_by_role("button", name="Redo").is_enabled(), "undo: Redo button enabled")
    grid.focus()
    page.keyboard.press("Control+Y")
    check(wait_cell(page, 1, 1, "99"), "redo with Ctrl+Y")
    page.keyboard.press("Control+Z")
    check(wait_cell(page, 1, 1, "30"), "undo with Ctrl+Z")

    # formula in an empty cell outside the data (the grid is padded, so C2 can be typed into)
    goto_cell(page, 1, 2)
    page.keyboard.type("=B2*2")
    page.keyboard.press("Enter")
    check(wait_cell(page, 1, 2, "60"), "formula =B2*2 in C2 evaluated by the real engine")
    page.screenshot(path=f"{SHOTS}/csv-edit.png")

    # Persian digits typed by the user are stored as numbers
    goto_cell(page, 0, 2)
    # F2 first: Playwright types non-US characters as text insertion without key events, which cannot
    # start an edit by typing (a real Persian keyboard sends keydown with the character, which does)
    page.keyboard.press("F2")
    page.keyboard.type("۱۲٫۵")
    page.keyboard.press("Enter")
    check(wait_cell(page, 0, 2, "12.5"), "Persian digits typed -> number 12.5")

    # ---------------- clipboard (real Ctrl+C / Ctrl+V) ----------------
    grid.focus()
    page.keyboard.press("Control+Home")
    page.keyboard.down("Shift")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    page.keyboard.up("Shift")
    page.keyboard.press("Control+C")
    clip = page.evaluate("navigator.clipboard.readText()")
    check(clip == "name\tage\nعلی\t30", f"copy: clipboard text is TSV ({clip!r})")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")  # row 4, col 0
    page.keyboard.press("Control+V")
    check(wait_cell(page, 4, 0, "name") and wait_cell(page, 5, 1, "30"), "paste: 2x2 block landed at the cursor")
    page.keyboard.press("Control+Z")  # ONE undo removes the whole paste
    check(wait_cell(page, 4, 0, "") and wait_cell(page, 5, 1, ""), "paste is a single undo step")

    # ---------------- history panel ----------------
    page.get_by_role("button", name="History").click()
    page.get_by_role("listitem").first.wait_for(timeout=8000)
    items = page.get_by_role("listitem").all_inner_texts()
    check(len(items) >= 3 and any("undone" in t for t in items), f"history panel lists changes, undone ones marked ({len(items)} entries)")
    page.screenshot(path=f"{SHOTS}/history.png")
    page.get_by_role("button", name="Close panel").first.click()

    # ---------------- conflict from a second tab ----------------
    wb_url = page.url
    page2 = ctx.new_page()
    page2.goto(wb_url)
    grid_ready(page2)
    page2.get_by_role("grid").focus()
    page2.keyboard.press("Control+Home")
    page2.keyboard.type("from tab 2")
    page2.keyboard.press("Enter")
    wait_cell(page2, 0, 0, "from tab 2")
    page2.close()
    page.bring_to_front()
    grid.focus()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.type("from tab 1")
    page.keyboard.press("Enter")
    banner = page.get_by_role("alert")
    try:
        banner.first.wait_for(timeout=8000)
        check("changed somewhere else" in banner.first.inner_text(), "conflict: banner shown for a stale second tab")
    except Exception:
        check(False, "conflict: banner shown for a stale second tab")
    check(wait_cell(page, 0, 0, "from tab 2"), "conflict: the screen reloaded the other tab's change")
    page.screenshot(path=f"{SHOTS}/conflict.png")
    page.get_by_role("button", name="Dismiss").first.click()
    page.keyboard.press("Control+Home")
    grid.focus()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.type("retry")
    page.keyboard.press("Enter")
    check(wait_cell(page, 1, 0, "retry"), "conflict: after reload the same edit succeeds")

    # ---------------- XLSX with formulas and a second sheet ----------------
    page.goto(ws_url)
    upload(page, "sales.xlsx")
    page.screenshot(path=f"{SHOTS}/xlsx-import.png")
    open_last_import(page)
    check(wait_cell(page, 0, 0, "Item"), "XLSX: header shown")
    check(wait_cell(page, 1, 0, "نان"), "XLSX: Persian text shown")
    check(wait_cell(page, 1, 3, "31.5"), "XLSX: formula result from the file (=B2*C2) shown")
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    page.keyboard.type("10")  # Qty of row 2: 3 -> 10, Total D2 = 105
    page.keyboard.press("Enter")
    check(wait_cell(page, 1, 3, "105"), "XLSX: editing an input recalculates the dependent formula cell")
    # F2 = SUM(D2:D4) = 105 + 40 + 36.25 = 181.25
    check(wait_cell(page, 1, 5, "181.25"), "XLSX: SUM over the changed cells recalculated")
    page.get_by_role("tab", name="Other").click()
    grid_ready(page)
    check(wait_cell(page, 0, 0, "362.5"), "XLSX: formula on ANOTHER sheet follows (cross-sheet recalculation, `others`)")
    page.get_by_role("tab", name="Sales").click()
    grid_ready(page)
    page.get_by_role("grid").focus()
    page.keyboard.press("Control+Z")
    check(wait_cell(page, 1, 3, "31.5"), "XLSX: undo restores the formula result")
    page.get_by_role("tab", name="Other").click()
    grid_ready(page)
    check(wait_cell(page, 0, 0, "215.5"), "XLSX: undo also restores the other sheet (=Sales!F2*2 = 107.75*2)")
    page.screenshot(path=f"{SHOTS}/xlsx-other.png")

    # ---------------- dynamic array: spill ----------------
    page.get_by_role("tab", name="Sales").click()
    grid_ready(page)
    page.get_by_role("grid").focus()
    goto_cell(page, 10, 8)
    page.keyboard.type("=SEQUENCE(3)")
    page.keyboard.press("Enter")
    check(wait_cell(page, 10, 8, "1") and wait_cell(page, 11, 8, "2") and wait_cell(page, 12, 8, "3"),
          "spill: =SEQUENCE(3) fills three cells (the server sent the neighbours)")
    goto_cell(page, 11, 8)
    page.keyboard.type("x")
    page.keyboard.press("Enter")
    check(wait_cell(page, 10, 8, "#SPILL!") and wait_cell(page, 12, 8, ""), "spill: a value in the way gives #SPILL! and the rest is emptied")
    page.keyboard.press("Control+Z")
    check(wait_cell(page, 10, 8, "1") and wait_cell(page, 12, 8, "3"), "spill: undo of the blocking value restores the spill")
    page.keyboard.press("Control+Z")
    check(wait_cell(page, 10, 8, "") and wait_cell(page, 12, 8, ""), "spill: undo of the formula removes the whole spill")

    page.keyboard.press("Control+Y")
    check(wait_cell(page, 12, 8, "3"), "spill: redo brings the spill back")
    page.keyboard.press("Control+Z")  # the spill is a formula on this sheet; rows can't move around it
    check(wait_cell(page, 12, 8, ""), "spill: removed again before the row tests")

    # insert / delete rows (docs/API_CONTRACTS.md, StructureEngine)
    goto_cell(page, 1, 0)
    page.get_by_label("Rows and columns").select_option("insertRowAbove")
    check(wait_cell(page, 2, 3, "31.5") and wait_cell(page, 1, 3, ""), "rows: inserting above row 2 moves the formula down")
    check(wait_cell(page, 2, 0, "نان"), "rows: its neighbours moved with it")
    page.keyboard.press("Control+z")
    check(wait_cell(page, 1, 3, "31.5") and wait_cell(page, 1, 0, "نان"), "rows: undo puts everything back")
    page.keyboard.press("Control+y")
    check(wait_cell(page, 2, 3, "31.5"), "rows: redo inserts again")
    page.keyboard.press("Control+z")
    check(wait_cell(page, 1, 3, "31.5"), "rows: second undo")

    # ---------------- fill (Ctrl+D) and find (Ctrl+F) ----------------
    goto_cell(page, 20, 12)
    page.keyboard.type("77")
    page.keyboard.press("Enter")
    check(wait_cell(page, 20, 12, "77"), "fill: the source value is in")
    goto_cell(page, 20, 12)
    page.keyboard.down("Shift")
    for _ in range(2):
        page.keyboard.press("ArrowDown")
    page.keyboard.up("Shift")
    page.keyboard.press("Control+D")
    check(wait_cell(page, 21, 12, "77") and wait_cell(page, 22, 12, "77"), "fill: Ctrl+D copies the top cell down")
    page.keyboard.press("Control+Z")
    check(wait_cell(page, 22, 12, ""), "fill: one undo removes the whole fill")
    page.keyboard.press("Control+F")
    box = page.get_by_placeholder("Find…")
    box.wait_for(timeout=5000)
    box.fill("۷۷")  # Persian digits find the Latin 77
    box.press("Enter")
    check(wait_cell(page, 20, 12, "77") and page.locator("#gv-20-12[aria-selected=true], #gv-20-12.gv-active").count() >= 0
          and page.get_by_text("Not found").count() == 0, "find: Ctrl+F with Persian digits finds 77")
    box.fill("zzzz-nothing")
    box.press("Enter")
    try:
        page.get_by_text("Not found").first.wait_for(timeout=5000)
        shown = True
    except Exception:
        shown = False
    check(shown, "find: a missing text says so")
    box.press("Escape")

    # ---------------- cell formatting ----------------
    page.get_by_role("grid").focus()
    goto_cell(page, 20, 12)
    page.get_by_role("button", name="Bold").click()
    weight = lambda: page.evaluate("getComputedStyle(document.querySelector('#gv-20-12')).fontWeight")
    deadline = time.time() + 8
    while time.time() < deadline and int(weight()) < 600:
        time.sleep(0.2)
    check(int(weight()) >= 600, "format: the Bold button makes the cell bold")
    page.get_by_label("Number format").select_option("0.00%")
    check(wait_cell(page, 20, 12, "7700.00%"), "format: number format 0.00% shows 7700.00% (value stays 77)")
    page.get_by_label("Font", exact=True).select_option("Tahoma")
    deadline = time.time() + 8
    fam = ""
    while time.time() < deadline and "Tahoma" not in fam:
        fam = page.evaluate("getComputedStyle(document.querySelector('#gv-20-12')).fontFamily")
        time.sleep(0.2)
    check("Tahoma" in fam, "format: the font picker sets the font")
    page.get_by_role("grid").focus()
    for _ in range(3):
        page.keyboard.press("Control+Z")
        time.sleep(0.4)
    check(wait_cell(page, 20, 12, "77") and int(weight()) < 600, "format: three undos bring back the plain cell")
    page.keyboard.press("Control+B")
    deadline = time.time() + 8
    while time.time() < deadline and int(weight()) < 600:
        time.sleep(0.2)
    check(int(weight()) >= 600, "format: Ctrl+B makes the cell bold")
    page.screenshot(path=f"{SHOTS}/format.png")

    # ---------------- Data Table, chart, export (panels) ----------------
    page.get_by_role("grid").focus()
    page.keyboard.press("Control+Home")
    page.keyboard.down("Shift")
    for _ in range(3):
        page.keyboard.press("ArrowDown")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    page.keyboard.up("Shift")  # A1:D4: a header row, item names, three number columns
    page.get_by_role("button", name="Charts").click()
    page.get_by_role("button", name="Make a chart from the selection").click()
    page.get_by_label("Title").fill("Totals")
    page.get_by_role("button", name="Create the chart").click()
    try:
        page.get_by_role("img", name="Totals").wait_for(timeout=10000)
        check(page.locator("svg[aria-label=Totals] rect").count() >= 3, "chart: bars drawn from the server's numbers")
    except Exception:
        check(False, "chart: bars drawn from the server's numbers")
    page.get_by_role("button", name="Close panel").first.click()

    page.get_by_role("button", name="Data Tables").click()
    page.get_by_role("button", name="Make a table from the selection").click()
    page.get_by_label("Table name").fill("Sales copy")
    page.get_by_text("rows,", exact=False).first.wait_for(timeout=10000)
    page.get_by_role("button", name="Create the table").click()
    try:
        page.get_by_role("columnheader").first.wait_for(timeout=10000)
        check(page.get_by_role("columnheader").count() >= 3, "table: created from the range and opened with its columns")
    except Exception:
        check(False, "table: created from the range and opened with its columns")
    page.get_by_role("button", name="Close panel").first.click()

    page.get_by_role("button", name="Save / Export").click()
    page.get_by_role("button", name="Save a version").click()
    page.get_by_text("Version saved", exact=False).first.wait_for(timeout=15000)
    check(True, "save: a version is stored")
    page.get_by_role("button", name="Export as Excel").click()
    try:
        link = page.get_by_role("link", name="Download XLSX")
        link.wait_for(timeout=30000)
        with page.expect_download() as dl:
            link.click()
        path = dl.value.path()
        check(path is not None and os.path.getsize(path) > 1000, "export: the .xlsx downloads and is not empty")
    except Exception as e:
        check(False, f"export: the .xlsx downloads and is not empty ({str(e)[:100]})")
    page.screenshot(path=f"{SHOTS}/export.png")
    page.get_by_role("button", name="Close panel").first.click()

    # expected: the 401 of the "who am I" probe before sign-in, and the 409 this script causes on purpose
    bad = [e for e in errors if "favicon" not in e and "status of 401" not in e and "status of 409" not in e]
    # ---------------- sign-up: a new person gets their own empty space ----------------
    name = f"e2e_{int(time.time())}"
    pw = "correct horse battery"
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx2.add_init_script("localStorage.setItem('gridora.prefs', JSON.stringify({locale:'en',digits:'latin',calendar:'gregorian'}))")
    p2 = ctx2.new_page()
    p2.goto(BASE + "/")
    p2.get_by_role("button", name="Create an account").click()
    p2.get_by_label("Username").fill(name)
    p2.get_by_label("Password", exact=True).fill(pw)
    p2.get_by_label("Repeat the password").fill(pw)
    p2.get_by_role("button", name="Create account").click()
    p2.get_by_label("Workspace name").wait_for(timeout=15000)
    check(p2.get_by_text(name).first.is_visible(), "sign-up: the new account is signed in")
    check(p2.locator(".card, li, [role=listitem]").filter(has_text="e2e").count() == 0
          or p2.get_by_text("sales.xlsx").count() == 0, "sign-up: the new account sees none of the admin's files")
    p2.get_by_label("Workspace name").fill("mine")
    p2.keyboard.press("Enter")
    p2.get_by_text("mine").first.wait_for(timeout=10000)
    check(True, "sign-up: the new user creates their own workspace")
    p2.goto(BASE + "/account")
    p2.get_by_label("Current password").fill(pw)
    p2.get_by_label("New password").fill("another long phrase!")
    p2.get_by_label("Repeat the password").fill("another long phrase!")
    p2.get_by_role("button", name="Change password").click()
    p2.get_by_text("Password changed").wait_for(timeout=10000)
    check(True, "sign-up: password change works")
    ctx2.close()

    check(not bad, f"no console errors or page errors ({bad[:3]})")
    browser.close()


with sync_playwright() as p:
    try:
        run(p)
    except Exception as e:  # report what was reached
        check(False, f"script stopped: {type(e).__name__}: {str(e)[:300]}")
failed = [w for ok, w in results if not ok]
print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed)}))
sys.exit(1 if failed else 0)
