"""SCRATCH ONLY -- deliberate failing test to prove CI can go red.

This file exists on the scratch branch ci-red-proof-j1e6 and NOWHERE else.
Its whole job is to make the `Tests` job report a genuine TEST failure inside
a suite that collected and executed -- "165 passed, 1 failed" -- rather than a
setup or lint error, which would prove nothing about the gate.
"""


def test_red_proof_deliberate_failure() -> None:
    assert 1 == 2, "deliberate failure: proving the Tests job gates on real assertions"
