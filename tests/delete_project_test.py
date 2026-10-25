"""Deleting a project from the list: its folder goes, a running one stays, a queued one never starts.

python tests/delete_project_test.py
On Windows also: a file held open by another program refuses the deletion and leaves the project whole.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOWPOLY_PROJECTS"] = tempfile.mkdtemp(prefix="berria-suppr-Frédéric ")
os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="berria-suppr-data-")
sys.path.insert(0, ROOT)
from fastapi import HTTPException  # noqa: E402

from app import server  # noqa: E402


def project(jid, state):
    job = {"id": jid, "name": jid, "created": 0, "mode": "auto", "main_photo": None, "engine": None,
           "settings": server.clean_settings({}), "photos": [], "results": {}, "state": state, "step": "",
           "error": None, "running_level": None, "log": []}
    os.makedirs(os.path.join(server.job_dir(jid), "photos"))
    with open(os.path.join(server.job_dir(jid), "photos", "a.jpg"), "wb") as f:
        f.write(b"x")
    server.JOBS[jid] = job
    server.save(job)
    return job


def refused(jid, status):
    try:
        server.delete_job(jid)
    except HTTPException as e:
        assert e.status_code == status, e.status_code
        return
    raise AssertionError(f"{jid} supprimé")


def main():
    project("fini", "done")
    assert server.delete_job("fini") == {"ok": True}
    assert "fini" not in server.JOBS and not os.path.exists(server.job_dir("fini"))
    assert not os.path.exists(server.job_dir("fini") + server.TRASH)
    refused("fini", 404)

    project("en cours", "running")
    refused("en cours", 409)
    assert "en cours" in server.JOBS and os.path.exists(server.job_dir("en cours"))

    queued = project("en attente", "queued")
    server.delete_job("en attente")
    server.process(queued, "lowpoly", lambda line: None)  # what the worker does with the stale entry of its queue
    assert queued["state"] == "queued" and not os.path.exists(server.job_dir("en attente"))

    os.makedirs(os.path.join(server.PROJECTS, "vieux" + server.TRASH, "photos"))
    with open(os.path.join(server.PROJECTS, "vieux" + server.TRASH, "job.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "vieux"}, f)
    server.JOBS.clear()
    server.load_projects()
    assert not os.path.exists(os.path.join(server.PROJECTS, "vieux" + server.TRASH))
    assert set(server.JOBS) == {"en cours"}, set(server.JOBS)

    if sys.platform == "win32":
        project("ouvert", "done")
        with open(os.path.join(server.job_dir("ouvert"), "photos", "a.jpg"), "rb"):
            refused("ouvert", 409)
        assert "ouvert" in server.JOBS and os.path.exists(os.path.join(server.job_dir("ouvert"), "job.json"))
        server.delete_job("ouvert")
        assert not os.path.exists(server.job_dir("ouvert"))
    print("serveur : projet supprimé avec ses fichiers, calcul en cours protégé, projet en attente jamais lancé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
