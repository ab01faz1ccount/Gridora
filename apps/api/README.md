# apps/api — HTTP API and composition layer

FastAPI service: local accounts and sessions, workspaces and files, import/export jobs, workbook windows, edits with history, undo/redo, operations with preview, Data Tables, charts, saved tools. It is the only place that wires the engine and dataops together.

Full description of what it does, how it is built and its limits: [docs/REFERENCE.md](../../docs/REFERENCE.md#http-api-appsapi). Design record: [DESIGN.md](../DESIGN.md)

```bash
pip install -e ../../contracts/python -e '.[dev]'
pytest   # needs PostgreSQL: GRIDORA_TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/db_test
GRIDORA_DATA_ROOT=./data uvicorn --factory gridora_api.main:run --reload
```
