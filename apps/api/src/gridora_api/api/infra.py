"""Infrastructure endpoints. NOT part of /api/v1 and not part of the contract.

/healthz  liveness: the process is up.
/readyz   readiness: dependencies are usable. Reports only check names and ok/fail, never reasons.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["infra"], include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    results = await request.app.state.readiness.run()
    ok = all(results.values())
    body = {
        "status": "ok" if ok else "unavailable",
        "checks": {k: ("ok" if v else "fail") for k, v in results.items()},
    }
    return JSONResponse(body, status_code=200 if ok else 503, headers={"Cache-Control": "no-store"})
