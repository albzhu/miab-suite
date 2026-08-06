"""
T11 (out of scope for M1) — envelope durability under concurrent writers.

`save()` still writes through a fixed `.json.tmp` path with no locking.
Concurrent writers race and interleave, corrupting the envelope or losing
events. This is a known gap, explicitly deferred to M3/T11 by the M1 kickoff
scope boundary — recorded here as an expected failure so it isn't silently
forgotten, per the M1 deliverables checklist.

Do not "fix" this test by adding locking; that's T11's job, not M1's.
"""
import concurrent.futures
import subprocess
import sys

import pytest

from conftest import CB_SCRIPT, parse_json


@pytest.mark.xfail(
    reason="T11 (out of scope for M1): save() has no envelope locking yet; "
           "concurrent load-mutate-save races can corrupt or lose forward events.",
    strict=False,
)
def test_20_parallel_forwards_preserve_stack_depth(run_cb, claw_home):
    r = run_cb("create", "--task", "t", "--from", "main", "--to", "holder0", "--summary", "s")
    assert r.returncode == 0
    cid = parse_json(r.stdout)["id"]

    def do_forward(i):
        import os
        env = os.environ.copy()
        env["CLAW_HOME"] = str(claw_home)
        return subprocess.run(
            [sys.executable, str(CB_SCRIPT), "forward", "--id", cid,
             "--from", "holder0", "--to", f"holder{i}", "--summary", f"s{i}"],
            capture_output=True, text=True, env=env,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(do_forward, range(20)))

    assert all(r.returncode == 0 for r in results), \
        "expect this to fail today: concurrent writers interleave into one .tmp file"

    show = run_cb("show", "--id", cid, "--json")
    assert show.returncode == 0
    env = parse_json(show.stdout)
    # 1 initial frame (main) + 20 forwarded frames, if every write survived.
    assert len(env["stack"]) == 21
