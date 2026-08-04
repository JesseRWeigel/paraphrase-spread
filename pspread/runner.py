"""Run every (paraphrase, item) pair through a local Ollama model and save every raw response.

Two properties matter more than speed here.

RESUMABLE. Every response is appended to disk as it arrives, keyed by (paraphrase id, item key).
A rerun reads what is already on disk and asks only for what is missing. The GPU on this machine
is shared with other work, so a run that has to start over from zero after an eviction is a run
that never finishes.

EVERY RESPONSE IS KEPT. Grading happens later, from the files. That means the headline numbers
can be re-derived, re-graded under a different convention, or checked by code that shares nothing
with the grader, without paying for the model again.
"""

import json
import os
import pathlib
import queue
import threading
import time
import urllib.error
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
SHARD_BYTES = 600_000  # keeps every tracked raw file well under a megabyte

# Fixed for every call. Temperature 0 means the only randomness left in a paraphrase's score is
# which 24 items it was asked, which is exactly the noise the analysis has to separate out.
OPTIONS = {"temperature": 0.0, "top_p": 1.0, "seed": 20260803, "num_predict": 200}


def model_slug(model):
    return model.replace(":", "-").replace("/", "-")


def shard_paths(raw_dir, task_name, model):
    stem = f"{task_name}__{model_slug(model)}__"
    return sorted(pathlib.Path(raw_dir).glob(stem + "*.jsonl"))


def load_done(raw_dir, task_name, model):
    """Every (paraphrase id, item key) already on disk, plus the records themselves."""
    records = []
    for path in shard_paths(raw_dir, task_name, model):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    done = {(r["p"], r["i"]) for r in records}
    return done, records


class _ShardWriter:
    def __init__(self, raw_dir, task_name, model):
        self.dir = pathlib.Path(raw_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stem = f"{task_name}__{model_slug(model)}__"
        self.lock = threading.Lock()
        self._open_latest()

    def _open_latest(self):
        existing = sorted(self.dir.glob(self.stem + "*.jsonl"))
        if existing and existing[-1].stat().st_size < SHARD_BYTES:
            self.path = existing[-1]
        else:
            self.path = self.dir / f"{self.stem}{len(existing):03d}.jsonl"
        self.fh = open(self.path, "a", encoding="utf-8")

    def write(self, record):
        with self.lock:
            self.fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.fh.flush()
            if self.fh.tell() >= SHARD_BYTES:
                self.fh.close()
                self._open_latest()

    def close(self):
        with self.lock:
            self.fh.close()


def generate(model, prompt, timeout=300, retries=3):
    """One completion. Returns (text, eval_count, error_string_or_None).

    A failed call returns an explicit error rather than an empty string, because an empty string
    grades as unparseable and an unreachable server would then look like a model that refuses to
    answer. Those are different facts and the pipeline keeps them apart.
    """
    body = {"model": model, "prompt": prompt, "stream": False, "options": dict(OPTIONS),
            "keep_alive": "10m", "think": False}
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{OLLAMA}/api/generate", data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            return d.get("response", ""), d.get("eval_count"), None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return None, None, last


def unload(model):
    """Ask Ollama to drop the model from VRAM. The GPU is shared; leaving 10 GB parked on it
    after a phase finishes is rude to whatever runs next."""
    try:
        req = urllib.request.Request(
            f"{OLLAMA}/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass


def run(task, paraphrases, model, raw_dir, workers=6, limit=None, progress=None):
    """Fill in every missing (paraphrase, item) response. Returns a summary dict."""
    done, _ = load_done(raw_dir, task.name, model)
    jobs = []
    for pid, template in paraphrases:
        for item in task.items:
            if (pid, item.key) in done:
                continue
            jobs.append((pid, item.key, template.format(**item.slots)))
    if limit is not None:
        jobs = jobs[:limit]
    if not jobs:
        return {"model": model, "task": task.name, "new": 0, "already_done": len(done)}

    writer = _ShardWriter(raw_dir, task.name, model)
    q = queue.Queue()
    for j in jobs:
        q.put(j)
    state = {"n": 0, "errors": 0, "t0": time.time()}
    lock = threading.Lock()

    def worker():
        while True:
            try:
                pid, key, prompt = q.get_nowait()
            except queue.Empty:
                return
            t0 = time.time()
            text, ec, err = generate(model, prompt)
            rec = {"p": pid, "i": key, "r": text, "n": ec,
                   "ms": int((time.time() - t0) * 1000)}
            if err:
                rec["e"] = err
            writer.write(rec)
            with lock:
                state["n"] += 1
                state["errors"] += int(bool(err))
                if progress and state["n"] % 250 == 0:
                    rate = state["n"] / (time.time() - state["t0"])
                    progress(state["n"], len(jobs), rate, state["errors"])

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writer.close()
    elapsed = time.time() - state["t0"]
    return {"model": model, "task": task.name, "new": state["n"], "errors": state["errors"],
            "already_done": len(done), "seconds": round(elapsed, 1),
            "calls_per_second": round(state["n"] / elapsed, 2) if elapsed else None}
