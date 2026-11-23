# packages/dataops — data operations and Data Tables

Fifteen table operations (sort, filter, remove duplicates, find and replace, clean text, split/merge columns, group and total, pivot/unpivot, computed columns, type and calendar conversion, join) with preview, effect summary and exact undo; Persian-aware collation and text handling; versioned Parquet Data Tables; pipelines and saved tools; chart data; a Persian task-phrase search over the catalog. Entry points: `create_executor`, `create_table_store`, `catalog`.

Full description of what it does, how it is built and its limits: [docs/REFERENCE.md](../../docs/REFERENCE.md#data-operations-packagesdataops). Design record: [DESIGN.md](DESIGN.md)

```bash
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```
