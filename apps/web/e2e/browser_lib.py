import json, os, ssl, sys, time, urllib.request, http.cookiejar, statistics
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

BASE = os.environ.get("BASE_URL", "https://localhost")
USER = os.environ.get("E2E_USER", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=CTX))
CSRF = ""

def api(method, path, body=None, raw=None, ctype="application/json", timeout=600):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + "/api/v1" + path, data=data, method=method)
    if data is not None: req.add_header("Content-Type", ctype)
    if CSRF: req.add_header("X-CSRF-Token", CSRF)
    with op.open(req, timeout=timeout) as r:
        b = r.read()
        return json.loads(b) if b else None

def login():
    global CSRF
    CSRF = api("POST", "/auth/login", {"username": USER, "password": PASSWORD})["data"]["csrf_token"]

def upload_csv(ws, name, path):
    boundary = "----bench"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    r = api("POST", f"/workspaces/{ws}/files", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
    return r["data"]["job_id"]

def wait_job(job, seconds=900):
    t0 = time.time()
    while time.time() - t0 < seconds:
        j = api("GET", f"/jobs/{job}")["data"]
        if j["status"] in ("succeeded", "failed"): return j, time.time() - t0
        time.sleep(1)
    raise SystemExit("job timeout")

def make_driver():
    o = Options(); o.add_argument("-headless"); o.binary_location = os.environ.get("FIREFOX_BIN", "/opt/ffenv/bin/firefox")
    o.accept_insecure_certs = True
    d = webdriver.Firefox(service=Service(os.environ.get("GECKODRIVER", "/opt/ffenv/bin/geckodriver"), log_output="/tmp/gecko.log"), options=o)
    d.set_window_size(1280, 900)
    return d

BENCH_JS = """
const done = arguments[arguments.length-1];
const [ms, px] = [arguments[0], arguments[1]];
const el = document.querySelector('[role=grid]'); const frames=[]; let last=performance.now(); const t0=last; const s0=el.scrollTop;
function step(now){ frames.push(now-last); last=now; el.scrollTop += px; if(now-t0<ms) requestAnimationFrame(step); else done({frames, scrolled: el.scrollTop-s0}); }
requestAnimationFrame(step);
"""
def cells_js(d): return d.execute_script("return document.querySelectorAll('[role=gridcell]').length")
def cell_requests(d): return d.execute_script("return performance.getEntriesByType('resource').filter(e=>e.name.includes('/cells?')).length")
def loaded_text(d): return d.execute_script("const e=[...document.querySelectorAll('.gv-cell')].find(x=>!x.classList.contains('gv-loading')&&x.textContent.trim()); return e? e.textContent : null")
def wait_for(d, fn, seconds=30, what=""):
    t0 = time.time()
    while time.time()-t0 < seconds:
        v = fn()
        if v: return time.time()-t0
        time.sleep(0.1)
    raise SystemExit("timeout waiting for " + what)
def pct(a, p): s = sorted(a); return s[min(len(s)-1, int(len(s)*p))]

def ui_login(d):
    d.get(BASE + "/")
    wait_for(d, lambda: d.find_elements(By.CSS_SELECTOR, "input[autocomplete=username]"), 20, "login form")
    d.find_element(By.CSS_SELECTOR, "input[autocomplete=username]").send_keys(USER)
    d.find_element(By.CSS_SELECTOR, "input[type=password]").send_keys(PASSWORD)
    d.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
    wait_for(d, lambda: "/workspaces" in d.current_url, 20, "workspaces page")
