# contracts/

Normative shared types and module interfaces. **Owned by Agent 0.** Other agents import from here and never edit it; if a contract is wrong or missing, open the PR with a `CONTRACT_CHANGE:` section explaining what and why, and keep working against the current version until it is merged.

- `python/gridora_contracts/models.py` — pydantic v2 data models (mirrors `docs/DATA_MODEL.md`).
- `python/gridora_contracts/protocols.py` — `WorkbookEngine`, `OperationExecutor`, `TableStore`, `ExecContext`.
- `typescript/index.ts` — the same types for the web app.
- `python/tests/` — contract smoke tests; keep green.

Rule: the Python and TypeScript files must stay in sync. Any change touches both, plus `docs/DATA_MODEL.md`/`API_CONTRACTS.md` when the shape changes.

Install for local development: `pip install -e contracts/python`. Run tests: `pytest contracts/python/tests`.
