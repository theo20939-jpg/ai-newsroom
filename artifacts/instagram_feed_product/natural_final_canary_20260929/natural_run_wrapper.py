"""Wrapper (scratch, not repo): runs scripts/_instagram_viral_nominated_canary.py unchanged, and additionally captures the EXACT Telegram
review payload (scripts/_instagram_controlled_completion.install_review_payload_capture) on top of the harness's no-Telegram recorder."""
import asyncio, runpy, sys
from pathlib import Path
WT = Path(r"C:\Users\Theodor\ai-newsroom\.worktrees\instagram-b61")
sys.path.insert(0, str(WT))
import scripts._instagram_e2e_week as harness
import scripts._instagram_controlled_completion as cc_script
out = Path(sys.argv[3])
real_install = harness._install_capture
def install_with_payload():
    suit = real_install()
    cc_script.install_review_payload_capture(out)
    return suit
harness._install_capture = install_with_payload
# the worker's own cycle (worker/content_cycle.py: mark_tried + continue on preflight != PASS): skip the event ids already tried this cycle
import os
import services.instagram_viral_nomination as nom
TRIED = {t for t in os.environ.get("KAGE_TRIED_IDS", "").split(",") if t}
real_reads = nom.nominated_reads
def reads_after_tried(nomination, limit):
    return [(p, r) for p, r in real_reads(nomination, limit) if p.id not in TRIED]
nom.nominated_reads = reads_after_tried
sys.argv = [str(WT / "scripts/_instagram_viral_nominated_canary.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
