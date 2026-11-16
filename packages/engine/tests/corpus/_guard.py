"""Run ONE file through the engine in a child process with memory and time limits and print a
JSON outcome. A crash, a hang or an untyped exception is then a test failure, not a test-run crash."""
import json
import resource
import sys
import time
from pathlib import Path

resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))
from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError

p = Path(sys.argv[1])
out: dict = {"name": p.name}
t0 = time.perf_counter()
try:
    eng = create_engine({})
    h, wb, rep = eng.import_xlsx(p)
    for s in eng._open[h.id].sheets:
        s.lazy.materialize_all()  # lazy errors must be typed too
    out.update(outcome="ok", sheets=len(wb.sheets), cells=eng._open[h.id].budget.cells,
               codes=sorted({i.code for i in rep.items}))
except GridoraEngineError as e:
    out.update(outcome="typed", code=e.code, reason=e.reason, message=e.public_message)
except BaseException as e:  # noqa: BLE001
    out.update(outcome="untyped", exc=type(e).__name__, message=str(e)[:200])
out["secs"] = round(time.perf_counter() - t0, 3)
print(json.dumps(out, ensure_ascii=False))
