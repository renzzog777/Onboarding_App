"""Shared test helper: a bag-of-words "embedding" so retrieval behaves
meaningfully without Ollama (not a test module)."""
import hashlib
import math
import re

DIM = 512
STOP = set("a an and the in of to on or how do i is it my with your for".split())


def fake_embed(texts, *, query=False):
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            if w in STOP:
                continue
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out
