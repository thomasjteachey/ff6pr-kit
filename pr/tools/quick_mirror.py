"""Mirror folders like robocopy /MIR, skipping a folder whose copy already matches.

  python tools/quick_mirror.py SRC DST [SRC DST ...]

deploy.sh's PC installs mirrored every data folder with robocopy /MIR, which walks both trees file
by file even when nothing changed: 2-6 s per folder on this PC (2026-11-20), on every install and
every mod switch. This lists both trees first (os.scandir: names, sizes, modification times, which
Windows hands out with the listing; robocopy keeps the source's times, so a mirrored copy matches
exactly) and, where they differ, copies or deletes just those entries (robocopy /MIR if that fails
or leaves a difference), then checks the copy matches. One line per pair: "<DST>: unchanged" or
"<DST>: mirrored (<n> differed)"; exit 1 if robocopy fails.

snapshot() and mirror() are also what tools/wc_bundle.py --install uses (with the snapshot its build
recorded instead of walking the bundle again).
"""
import os
import shutil
import subprocess
import sys
import time


def snapshot(root):
    """{relative path (os.path.normcase): [size, mtime_ns] for a file, None for a folder}, or None
    when root isn't a folder."""
    if not os.path.isdir(root):
        return None
    out = {}
    todo = [""]
    while todo:
        rel = todo.pop()
        with os.scandir(os.path.join(root, rel) if rel else root) as it:
            for e in it:
                r = os.path.join(rel, e.name) if rel else e.name
                if e.is_dir(follow_symlinks=False):
                    out[os.path.normcase(r)] = None
                    todo.append(r)
                else:
                    s = e.stat(follow_symlinks=False)
                    out[os.path.normcase(r)] = [s.st_size, s.st_mtime_ns]
    return out


def differ(a, b):
    """The paths whose entries differ between two snapshots (all of them if one is None)."""
    if a is None or b is None:
        return sorted((a or {}).keys() | (b or {}).keys()) or ["(missing)"]
    return sorted(k for k in a.keys() | b.keys() if a.get(k, 0) != b.get(k, 0))


def robocopy(src, dst):
    """robocopy /MIR src dst (deploy.sh's flags); raises RuntimeError on its failure codes (8+)."""
    p = subprocess.run(["robocopy", src, dst, "/MIR", "/NJH", "/NJS", "/NP", "/NFL", "/NDL"],
                       capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
    if p.returncode >= 8:
        raise RuntimeError(f"robocopy failed ({p.returncode}): {src} -> {dst}\n{(p.stdout + p.stderr)[-800:]}")


def apply(src, dst, want, have, diff):
    """Copy, create and delete just the differing entries (shutil.copy2 keeps the times, as robocopy
    does). Raises OSError where it can't (a locked or read-only file): then robocopy does it all."""
    have = have or {}
    os.makedirs(dst, exist_ok=True)
    gone = [k for k in diff if k not in want]
    for k in sorted((k for k in gone if have.get(k) is not None), key=len, reverse=True):
        os.remove(os.path.join(dst, k))
    for k in sorted((k for k in gone if k in have and have[k] is None), key=len, reverse=True):
        shutil.rmtree(os.path.join(dst, k))
    for k in sorted((k for k in diff if k in want), key=len):
        s, d = os.path.join(src, k), os.path.join(dst, k)
        if want[k] is None:
            if have.get(k, 0) is not None and os.path.isfile(d):   # a file where a folder belongs
                os.remove(d)
            os.makedirs(d, exist_ok=True)
        else:
            if os.path.isdir(d):
                shutil.rmtree(d)
            shutil.copy2(s, d)


def mirror(src, dst, src_snap=None, dst_snap=None):
    """Make dst a copy of src unless it already is one: the differing entries copied or deleted one by
    one, robocopy /MIR if that fails or leaves a difference. src_snap / dst_snap: snapshots already
    taken. -> (number of entries that differed, [entries still differing after the copy])."""
    want = src_snap if src_snap is not None else snapshot(src)
    if want is None:
        raise RuntimeError(f"no folder to mirror: {src}")
    have = dst_snap if dst_snap is not None else snapshot(dst)
    diff = differ(want, have)
    if not diff:
        return 0, []
    left = diff
    if have is not None:
        try:
            apply(src, dst, want, have, diff)
            left = differ(want, snapshot(dst))
        except OSError:
            pass
    if left:
        robocopy(src, dst)
        left = differ(want, snapshot(dst))
    return len(diff), left


def main(argv):
    if len(argv) < 2 or len(argv) % 2:
        print(__doc__.strip().splitlines()[2])
        return 2
    rc = 0
    for src, dst in zip(argv[::2], argv[1::2]):
        t = time.time()
        try:
            n, left = mirror(src, dst)
        except RuntimeError as e:
            print(f"[mirror] {e}")
            rc = 1
            continue
        what = "unchanged" if not n else f"mirrored ({n} differed)"
        if left:
            what += f"; still differs after robocopy: {', '.join(left[:3])}" + (f" (+{len(left) - 3})" if len(left) > 3 else "")
        print(f"[mirror] {dst}: {what} ({time.time() - t:.1f} s)")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
