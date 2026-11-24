"""Knowledge base CLI.

  python -m kb worker                     index everything pending (used by the app)
  python -m kb reindex-all                convert + index every PDF guide
  python -m kb reindex-all --only-missing   ...only guides not indexed yet
  python -m kb reindex-all --force          ...also re-convert edited Markdown
                                            from the PDF, and rebuild the index if
                                            EMBED_MODEL changed
  python -m kb status                     one line per guide

Run from the app folder with the app's venv and .env loaded, e.g.:
  set -a; . ./.env; set +a; venv/bin/python -m kb reindex-all
"""
import argparse
import sys
import time


def _pdf_resources():
    import database as db

    db.init_db()
    return [r for r in db.list_resources() if r["resource_type"] == "pdf"]


def cmd_worker(args):
    from kb import worker

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    results = worker.run_pending(log=lambda m: print(f"{stamp} {m}", flush=True))
    if results:
        print(f"{stamp} kb worker done: {len(results)} guide(s)", flush=True)


def cmd_reindex_all(args):
    from ai import llm
    from kb import store, worker

    model = llm.setting("EMBED_MODEL")
    built = store.index_info()["embed_model"]
    if built and built != model:
        if not args.force:
            sys.exit(f"Index was built with {built}, EMBED_MODEL is {model}. Re-run with --force to rebuild.")
        print(f"EMBED_MODEL changed ({built} -> {model}): dropping all chunks and vectors.")
        store.reset_index()

    docs = store.all_documents()
    queued = 0
    with worker.worker_lock():  # don't race a running worker while queueing
        for r in _pdf_resources():
            rid = r["id"]
            if args.only_missing and docs.get(rid, {}).get("status") == store.INDEXED:
                continue
            sha = r["sha256"] if "sha256" in r.keys() else None
            store.enqueue(rid, sha, keep_edits=not args.force)
            queued += 1
    print(f"Queued {queued} guide(s). Converting and embedding (one at a time)...", flush=True)
    t0 = time.time()
    results = worker.run_pending(log=lambda m: print(m, flush=True))
    counts = {}
    for status in results.values():
        counts[status] = counts.get(status, 0) + 1
    print(f"\nDone in {time.time() - t0:.0f}s: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    for rid, status in results.items():
        if status != store.INDEXED:
            d = store.get(rid) or {}
            print(f"  {rid}: {status} - {d.get('error')}")
    if any(s != store.INDEXED for s in results.values()):
        sys.exit(1)


def cmd_status(args):
    from kb import store

    docs = store.all_documents()
    info = store.index_info()
    print(f"Index: {info['embed_model'] or '(empty)'} {info['dim'] or ''}")
    for r in _pdf_resources():
        d = docs.get(r["id"])
        if not d:
            print(f"{r['id']:4}  not indexed  {r['title']}")
            continue
        extra = f"{d['chunks']} chunks" if d["status"] == "indexed" else (d["error"] or "")
        edited = " [edited md]" if d["md_edited"] else ""
        print(f"{r['id']:4}  {d['status']:11}  {r['title']}  ({extra}){edited}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kb", description="Tutorials knowledge base")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worker").set_defaults(fn=cmd_worker)
    ra = sub.add_parser("reindex-all")
    ra.add_argument("--only-missing", action="store_true")
    ra.add_argument("--force", action="store_true")
    ra.set_defaults(fn=cmd_reindex_all)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
