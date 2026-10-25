"""Resumable downloads with integrity checks, shared by the installers (setup_ai, setup_tools)."""
import hashlib
import os
import urllib.request


def download(url, tmp, size, advance):
    """Fetch url into tmp, resuming a partial file; advance(n) reports bytes (negative when starting over)."""
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if have > size:
        os.remove(tmp)
        have = 0
    advance(have)
    if have == size:
        return
    headers = {"User-Agent": "BerriaCraft", **({"Range": f"bytes={have}-"} if have else {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        resumed = have and r.status == 206
        if have and not resumed:  # server ignored the range: start over
            advance(-have)
            have = 0
        with open(tmp, "ab" if resumed else "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                advance(len(chunk))


def digest_ok(path, sha256=None, md5=None):
    if not (sha256 or md5):
        return True
    h = hashlib.sha256() if sha256 else hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest() == (sha256 or md5)
