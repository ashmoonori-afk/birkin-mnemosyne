"""Safe nightly curation on ANY model — including your own client.

The model only proposes a typed JSON plan; a deterministic executor validates,
clamps, and applies it under file-safety invariants. A weak or adversarial
model cannot delete, mass-archive, escape the vault, or archive a protected
note.

    # use a subscription CLI (no API key needed):
    python examples/curate_safely.py            # provider="claude"
    # or bring your own str->str completion (openclaw / hermes / raw HTTP):
    #   run_curation_pass(vault, my_complete, provider="custom")
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from birkin_mnemosyne import VaultMemory, run_curation_pass, get_completer

vault = Path(tempfile.mkdtemp()) / "vault"
mem = VaultMemory({"vault_path": str(vault)})
# leave everything in the inbox (no zone) so the curator has work to do
for title, body in [
    ("K8s ingress DNS", "nginx ingress resolves service dns"),
    ("CoreDNS tuning", "scale coredns replicas when pod dns lookups spike"),
    ("Sourdough starter", "feed the starter 1:1:1 for an active levain"),
    ("Bulk ferment", "the dough is ready when it domes and jiggles"),
    ("Dentist appt", "book the cleaning for next Tuesday"),      # a one-off
]:
    mem.write_note(title, body)

provider = sys.argv[1] if len(sys.argv) > 1 else "claude"
# For a fully offline demo, define your own trivial completer instead:
#   complete = lambda prompt: '{"plan_version":1,"ops":[...],"summary":""}'
complete = get_completer(provider, cwd=str(vault))

outcome = run_curation_pass(vault, complete, provider=provider)
print(f"proposed {outcome.plan_ops} ops, "
      f"{len(outcome.accepted)} accepted, {len(outcome.dropped)} dropped "
      f"(archive cap {outcome.archive_cap})")
for op in outcome.effected[:20]:
    print("  ", op)
