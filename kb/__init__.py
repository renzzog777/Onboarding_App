"""
kb/ - the tutorials assistant's local knowledge base.

Every uploaded PDF guide is converted to Markdown (pymupdf4llm, no OCR),
chunked by headings, embedded with EMBED_MODEL on Ollama (ai/llm.py) and
stored in data/kb.db (SQLite + sqlite-vec). The PDF itself stays in
uploads/tutorials/ untouched, so downloads work exactly as before.

  kb/config.py   paths (overridable through env vars for tests/subprocesses)
  kb/convert.py  PDF -> clean Markdown, scanned-PDF detection
  kb/chunk.py    Markdown -> 300-400 word chunks with heading paths
  kb/store.py    kb.db schema, status, chunks, vectors, search
  kb/worker.py   background job (short-lived process) + enqueue/spawn
  python -m kb   CLI: worker | reindex-all | status
"""
