"""Regression test: the worker and request threads save the same job at once.

python tests/save_race_test.py
Before the fix, about a third of the saves raised FileNotFoundError on the shared temp file.
"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOWPOLY_PROJECTS"] = tempfile.mkdtemp(prefix="lowpoly3d-save-")
os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="lowpoly3d-save-data-")
sys.path.insert(0, ROOT)
from app import server  # noqa: E402


def main():
    job = {"id": "race", "log": [], "n": 0}
    os.makedirs(server.job_dir("race"))
    errors = []

    def worker(tag):
        for i in range(300):
            with server.LOCK:
                job["n"] += 1
                job["log"].append(f"{tag}{i}")
            try:
                server.save(job)
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(t,)) for t in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(os.path.join(server.job_dir("race"), "job.json"), encoding="utf-8") as f:
        final = json.load(f)
    leftovers = [n for n in os.listdir(server.job_dir("race")) if n.endswith(".tmp")]
    print(json.dumps({"errors": len(errors), "first_error": errors[:1], "final_n": final["n"],
                      "expected_n": job["n"], "tmp_left": leftovers}))
    return 1 if errors or leftovers or final["n"] != job["n"] else 0


if __name__ == "__main__":
    sys.exit(main())
