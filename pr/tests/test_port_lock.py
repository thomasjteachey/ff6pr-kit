"""The porter's output lock and build-then-swap (tools/port.py: lock_out, unlock_out, _swap_in, main): one port
per output folder at a time, a lock left by a finished process taken over, and the folder replaced whole.
Offline, a few seconds: no ROM, no port is run.

    .venv/Scripts/python -m unittest tests.test_port_lock -v
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)
import port  # noqa: E402

CHILD = """
import os, sys, time
sys.path.insert(0, {tools!r})
import port
lock = port.lock_out({out!r}, say=lambda m: print(m, flush=True))
print("got", os.getpid(), flush=True)
time.sleep({hold})
port.unlock_out(lock)
"""


def child(out, hold=0.0, wait=None):
    env = dict(os.environ)
    if wait is not None:
        env["PORT_LOCK_WAIT"] = str(wait)
    code = CHILD.format(tools=os.path.abspath(TOOLS), out=out, hold=hold)
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)


class PortLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "mods", "SomeMod")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_port_waits_for_the_first(self):
        first = child(self.out, hold=3)
        got, pid = first.stdout.readline().split(); self.assertEqual(got, "got")
        t = time.time()
        second = child(self.out, wait=60)
        out2, _ = second.communicate(timeout=60)
        first.communicate(timeout=30)
        self.assertEqual(second.returncode, 0, out2)
        self.assertIn("port lock: waiting for", out2)
        self.assertIn("got", out2)
        self.assertGreater(time.time() - t, 1.5)          # it waited for the first to let go
        self.assertFalse(os.path.exists(self.out + port.LOCK_SUFFIX))

    def test_second_port_gives_up_after_the_wait(self):
        first = child(self.out, hold=6)
        got, pid = first.stdout.readline().split(); self.assertEqual(got, "got")
        second = child(self.out, wait=1)
        out2, _ = second.communicate(timeout=30)
        first.communicate(timeout=30)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("is being ported by another process", out2)
        self.assertIn(f"pid {pid}", out2)               # the holder is named

    def test_a_finished_holders_lock_is_taken_over(self):
        gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        dead = int(gone.stdout)
        lock = self.out + port.LOCK_SUFFIX
        os.makedirs(lock)
        with open(os.path.join(lock, "owner.txt"), "w", encoding="utf-8") as f:
            f.write(f"pid {dead}\nstart 2026-11-20 00:00:00\ncmd port.py bnw\n")
        said = []
        os.environ["PORT_LOCK_WAIT"] = "10"
        try:
            got = port.lock_out(self.out, say=said.append)
        finally:
            del os.environ["PORT_LOCK_WAIT"]
        self.assertEqual(got, lock)
        self.assertIn(f"pid {os.getpid()}", open(os.path.join(lock, "owner.txt"), encoding="utf-8").read())
        self.assertTrue(any("taking over" in s for s in said), said)
        port.unlock_out(got)
        self.assertEqual(os.listdir(os.path.dirname(lock)), [])   # no tombs left

    def _stale_lock(self, pid, taken=None):
        lock = self.out + port.LOCK_SUFFIX
        os.makedirs(lock)
        owner = os.path.join(lock, "owner.txt")
        with open(owner, "w", encoding="utf-8") as f:
            f.write(f"pid {pid}\nstart 2026-11-20 00:00:00\ncmd port.py bnw\n")
        if taken is not None:
            os.utime(owner, (taken, taken))
        return lock

    def test_a_lock_naming_this_process_is_taken_over(self):
        # a dead holder's pid that is now ours (Proton restarts its ids): not a holder
        self._stale_lock(os.getpid())
        os.environ["PORT_LOCK_WAIT"] = "5"
        try:
            got = port.lock_out(self.out, say=lambda m: None)
        finally:
            del os.environ["PORT_LOCK_WAIT"]
        port.unlock_out(got)

    @unittest.skipUnless(os.name == "nt", "process start times: Windows (and Proton)")
    def test_a_reused_pid_is_not_a_holder(self):
        # the pid of a process that started after the lock was taken: the holder died, its pid went to another
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
        try:
            time.sleep(0.5)
            lock = self._stale_lock(live.pid, taken=time.time() - 3600)
            self.assertFalse(port._holds(live.pid, lock))
            os.utime(os.path.join(lock, "owner.txt"))            # taken now: that process is its holder
            self.assertTrue(port._holds(live.pid, lock))
        finally:
            live.kill()
            live.wait()

    @unittest.skipUnless(os.name == "nt", "Windows: a process we may not open isn't a holder")
    def test_a_system_process_pid_is_not_a_holder(self):
        lock = self._stale_lock(4)                           # pid 4: Windows' System process (alive, not ours to open)
        self.assertTrue(port._pid_alive(4))
        self.assertFalse(port._holds(4, lock))

    def test_a_live_holder_is_not_taken_over(self):
        self.assertTrue(port._pid_alive(os.getpid()))
        gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        self.assertFalse(port._pid_alive(int(gone.stdout)))

    def test_swap_replaces_the_folder_whole(self):
        os.makedirs(os.path.join(self.out, "old_only"))
        open(os.path.join(self.out, "a.txt"), "w").write("old")
        stage = self.out + port.STAGE_SUFFIX
        os.makedirs(stage)
        open(os.path.join(stage, "a.txt"), "w").write("new")
        port._swap_in(stage, self.out)
        self.assertEqual(open(os.path.join(self.out, "a.txt")).read(), "new")
        self.assertFalse(os.path.exists(os.path.join(self.out, "old_only")))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["SomeMod"])

    def test_swap_clears_old_leftovers(self):
        os.makedirs(self.out)
        left = self.out + ".old999"                  # an earlier swap's leftover a reader held open
        os.makedirs(left)
        open(os.path.join(left, "x"), "w").write("x")
        stage = self.out + port.STAGE_SUFFIX
        os.makedirs(stage)
        port._swap_in(stage, self.out)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["SomeMod"])

    def test_a_failed_swap_puts_the_last_port_back(self):
        os.makedirs(self.out)
        open(os.path.join(self.out, "last.txt"), "w").write("last")
        with self.assertRaises(OSError):
            port._swap_in(self.out + port.STAGE_SUFFIX, self.out)   # no stage: its rename fails
        self.assertEqual(os.listdir(self.out), ["last.txt"])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["SomeMod"])

    def test_main_builds_aside_and_restores_the_profile(self):
        class Prof:
            @property
            def out(self):
                return OUT
        OUT = self.out
        os.makedirs(self.out)
        open(os.path.join(self.out, "last.txt"), "w").write("last complete port")
        seen = {}

        def fake_main(profile):   # the port's body: writes through profile.out
            seen["out"] = profile.out
            seen["during"] = open(os.path.join(OUT, "last.txt")).read()   # readers see the last port meanwhile
            os.makedirs(profile.out)
            open(os.path.join(profile.out, "port_report.txt"), "w").write("ok")

        real, port._main = port._main, fake_main
        try:
            prof = Prof()
            port.main(prof)
        finally:
            port._main = real
        self.assertEqual(seen["out"], self.out + port.STAGE_SUFFIX)
        self.assertEqual(seen["during"], "last complete port")
        self.assertEqual(os.listdir(self.out), ["port_report.txt"])
        self.assertIs(type(prof), Prof)
        self.assertEqual(prof.out, self.out)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["SomeMod"])   # no lock/stage left

    def test_a_failed_port_leaves_the_last_folder(self):
        class Prof:
            out = property(lambda self: OUT)
        OUT = self.out
        os.makedirs(self.out)
        open(os.path.join(self.out, "last.txt"), "w").write("last")

        def broken(profile):
            os.makedirs(profile.out)
            raise RuntimeError("port failed")

        real, port._main = port._main, broken
        try:
            with self.assertRaises(RuntimeError):
                port.main(Prof())
        finally:
            port._main = real
        self.assertEqual(os.listdir(self.out), ["last.txt"])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["SomeMod"])


if __name__ == "__main__":
    unittest.main()
