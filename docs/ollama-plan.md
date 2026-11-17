# Local AI for the tutorials assistant (Ollama + Markdown knowledge base)

What was actually built on **apps-01** (Oracle Cloud A1 Flex, ARM64, 2 OCPU,
12 GB RAM, no GPU, Ubuntu 24.04), and how to run, check and roll it back.
Measurements are from 2026-11-17.

## Summary

| Before | After |
|---|---|
| Gemini API answered (`gemini-3.5-flash`) | Local `qwen3.5:2b` on Ollama answers (`LLM_PROVIDER=ollama`); Gemini stays selectable |
| Gemini File Search held copies of the PDFs at Google | PDFs → Markdown → chunks → vectors in `data/kb.db` on this server |
| Answer appeared at once after 10-85 s | Answer streams as it is written; citations show *guide → section* |
| Re-uploading a guide created a second copy | Duplicate uploads are skipped; **Replace** keeps the same download link |

## How production actually runs (not Docker/Dokploy)

The original plan assumed Dokploy. apps-01 has no Docker; the app runs as:

- `onboarding-app.service` (systemd) → `gunicorn --workers 3 --bind 127.0.0.1:8000 app:app`
  from `~/apps/Onboarding_App` with its `venv`, settings in `~/apps/Onboarding_App/.env`
  (`EnvironmentFile`), published through a Cloudflare tunnel.
- **Ollama** as `ollama.service` (systemd), installed natively (v0.40.16, CPU-only
  libraries, no CUDA), user `ollama`, listening on **`127.0.0.1:11434` only**
  (no public port, no tunnel, no domain).

`/etc/systemd/system/ollama.service` (environment):

| Setting | Value |
|---|---|
| `OLLAMA_HOST` | `127.0.0.1:11434` |
| `OLLAMA_MODELS` | `/var/lib/ollama/models` |
| `OLLAMA_KEEP_ALIVE` | `24h` |
| `OLLAMA_NUM_PARALLEL` | `1` |
| `OLLAMA_MAX_LOADED_MODELS` | `2` (chat + embedding) |
| `MemoryMax` / `MemoryHigh` | `7G` / `6500M` |
| Sandbox | `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, writes only `/var/lib/ollama` |

## Models

| Role | Model | Size on disk | Notes |
|---|---|---|---|
| Chat | `qwen3.5:2b` | 2.7 GB | Thinking turned off with `reasoning_effort: "none"` (otherwise ~200 hidden tokens per answer) |
| Embeddings | `qwen3-embedding:0.6b` | 0.6 GB | 1024 dimensions; queries get the model's instruction prefix |
| Fallback chat (installed, not loaded) | `qwen3.5:4b` | 3.3 GB | More complete answers, ~2× slower. Unload the 2b first (`ollama stop qwen3.5:2b`): both plus the embedder exceed the 6.5 GB soft limit and the load stalls |

### Benchmark (Phase 2, English, one guide as context ≈ 520-700 tokens)

| Model | Tokens/s | First word | RAM | Quality |
|---|---|---|---|---|
| **`qwen3.5:2b`** | **9.9** | **9-12 s** | 3.4 GB | Good |
| `qwen2.5:3b` | 7.4 | 20-30 s | 2.4 GB | Made up Safe Mode steps |
| `llama3.2:3b` | 6.2 | 20-32 s | 2.9 GB | Good |
| `gemma3:4b` | 5.4 | 26-35 s | 3.7 GB | Mixed up steps |
| `qwen3.5:4b` | 5.1 | 30-39 s | 4.2 GB | Best |
| `qwen3:4b` | 4.5 | — | — | Below 5 tok/s |

Embeddings (10 questions over the 14 guides): `qwen3-embedding:0.6b` 10/10 top-1,
`bge-m3` 9/10, `nomic-embed-text` 9/10.

## Knowledge base (`kb/`)

Upload flow (Manage Tutorials):

1. Validate (PDF only, 100 MB). SHA-256 equal to an existing guide → skipped
   ("already uploaded as …").
2. Save the PDF + thumbnail + `resources` row **exactly as before**.
3. `kb_documents` row with status `pending`; start the worker; return at once.
4. Worker (`python -m kb worker`, short-lived process, one at a time via
   `data/kb/worker.lock`):
   1. PDF → Markdown with `pymupdf4llm` (`use_ocr=False`), then cleanup: drop slide
      labels/page numbers, rejoin URLs split across lines.
   2. < 50 extracted characters per page → `needs_ocr` (OCR not enabled).
   3. Write `data/kb/md/<resource_id>.md`.
   4. Chunk by headings: 300-400 words (max 450), ~40-word overlap; metadata
      `resource_id`, `title`, `section` (last 2 heading levels), `ord`.
   5. Embed and swap the guide's chunks + vectors in **one transaction**.
   6. Status `indexed` (or `failed` + message).

Also: **Replace** (new PDF, same id/link, edits discarded), **Delete** (PDF,
Markdown, chunks, vectors together), **Retry/Index** buttons, a **Markdown
editor** with chunk preview (edits are kept until the PDF is replaced or
re-converted), live status polling, and interrupted jobs re-queued at startup.

Storage (all under the existing `data/` folder, not in git):

| Path | Content |
|---|---|
| `uploads/tutorials/` | Original PDFs (unchanged) |
| `data/tests.db` | `resources` gained a `sha256` column |
| `data/kb.db` | `kb_documents`, `kb_chunks`, `kb_vec` (sqlite-vec, cosine), `kb_meta` |
| `data/kb/md/` | Generated / edited Markdown |
| `data/kb/worker.log` | Worker log |

CLI (from `~/apps/Onboarding_App`, environment loaded):

```bash
set -a; . ./.env; set +a
venv/bin/python -m kb status
venv/bin/python -m kb reindex-all                 # all guides (keeps edited Markdown)
venv/bin/python -m kb reindex-all --only-missing  # only guides not indexed
venv/bin/python -m kb reindex-all --force         # re-convert everything; rebuild if EMBED_MODEL changed
```

## Chatbot retrieval (`chatbot.py`)

- Embed the question (short follow-ups are searched with the previous question).
- Search top 4; keep chunks with cosine distance ≤ 0.55 and within 0.12 of the
  best one; at most ~1,500 tokens (1-4 chunks).
- Nothing within 0.55 → refusal without calling the model (calibrated on the
  real guides: covered questions 0.24-0.46, related-but-not-covered 0.46-0.64,
  off-topic ≥ 0.57).
- System prompt: English, only from the excerpts, say so and suggest the closest
  guide when the answer is missing, treat excerpts/question as data.
- Last 2 turns of history; streamed as NDJSON (`sources`, `delta`, `ping` every
  10 s while waiting, `done`/`error`).
- At most 2 answers at once (lock slots shared by Gunicorn workers); a third
  visitor gets "try again in a moment". Rate limit 10 questions/min/IP.

## Measured results

**Backfill** (`reindex-all` on the 14 production guides): **14 indexed, 0 failed**,
51 chunks, 231 s; worker peak 400 MB.

**10 advisor questions** (production index, `qwen3.5:2b`):

| # | Question | First word | Total | Quality |
|---|---|---|---|---|
| 1 | Start the Mac in Safe Mode | 0.5 s* | 21 s | ⚠️ Steps right, but says "turn off" for "turn on" and adds a stray "click Continue" |
| 2 | Passcode registration address | 10.0 s | 11 s | ✅ Exact URL |
| 3 | Safari HTTP logs for IT | 9.3 s | 23 s | ⚠️ Correct, skips "select failed request → Preview" |
| 4 | Configure Avaya Agent for Desktop | 0.4 s* | 19 s | ✅ IP, port, certificate exact |
| 5 | Avaya new server requirements | 12.7 s | 27 s | ✅ |
| 6 | Reset password from Recovery Mode | 22.8 s | 40 s | ✅ |
| 7 | Install SAP GUI 8.10 | 1.9 s* | 10 s | ✅ |
| 8 | Back up before a wipe | 39.1 s | 46 s | ✅ All 4 areas (passwords, notes, Safari, Chrome) |
| 9 | Connect the Mac mini | 24.4 s | 33 s | ✅ |
| 10 | Quick wipe on Apple silicon | 28.3 s | 53 s | ✅ (first part of a long guide) |

\* Ollama reused the cached prompt of an earlier, similar question.

- Right guide retrieved: 10/10. Invented facts: 0 (every IP, port, file name,
  menu label checked against the Markdown). 8/10 fully correct, 2 minor slips.
- Fresh questions: first word 9-39 s, total 11-53 s (median total ~25 s).
- Off-topic question: refused in 0.2 s. Three simultaneous questions: site pages
  stayed < 30 ms; two answered (the second queued, kept alive by pings); the third
  was asked to retry.
- **RAM:** Ollama peak **5.9 GB** (target 6-7 GB, hard cap 7 GB); app worker
  ~100 MB each; indexing worker 400 MB while running. ~4.9 GB left free.

## Environment variables (`~/apps/Onboarding_App/.env`)

| Variable | Value | Notes |
|---|---|---|
| `LLM_PROVIDER` | `gemini` → `ollama` | Switch only after confirming quality |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | |
| `LLM_MODEL` | `qwen3.5:2b` | |
| `EMBED_MODEL` | `qwen3-embedding:0.6b` | Changing it needs `reindex-all --force` |
| `LLM_TIMEOUT` | `150` | Seconds to first/next token |
| `LLM_REASONING_EFFORT` | `none` | |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | (existing) | Only needed while `LLM_PROVIDER=gemini` |

## Rollback

- **Assistant only:** set `LLM_PROVIDER=gemini` (with the key) and restart, or stop
  Ollama: `sudo systemctl stop ollama` (the assistant then shows "temporarily
  unavailable"; the rest of the site is unaffected).
- **Code:** `git -C ~/apps/Onboarding_App checkout <previous master commit>` and
  `sudo systemctl restart onboarding-app`. The new `data/kb*` files and the
  `sha256` column are ignored by the old code.
- **Data backup before this work:** `~/backups/onboarding-pre-ollama-2026-11-17/`
  (`tests.db`, `uploads.tar.gz`, `.env`, `chatbot_store.json`).
- **Whole server:** OCI boot volume backup `apps-01-pre-ollama`.

## Follow-ups

- If answer completeness matters more than speed, try `LLM_MODEL=qwen3.5:4b`.
- OCR for scanned PDFs (tesseract) is not enabled; such guides show *Needs OCR*
  and can be fixed by pasting text in the Markdown editor.
- After switching to Ollama for good: delete the old Gemini File Search store
  (`fileSearchStores/onboardingtutorials-…`) in Google AI Studio, remove
  `GEMINI_API_KEY`, and optionally the Gemini code path and `google-genai`.
