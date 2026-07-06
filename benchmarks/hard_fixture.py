"""A HARD curation fixture — 232 intra-cluster link pairs, on purpose.

The 18-pair labeled fixture is trivial: an explicit "link every pair in a
zone" instruction solves it because placement is easy. This fixture makes
link recall genuinely hard by attacking *placement*:

- **13 clusters, sizes 5–8** → 232 intra-cluster pairs to recover.
- **Deliberate cross-cluster vocabulary overlap.** Networking notes for k8s,
  AWS, and the home LAN all share dns/firewall/subnet; postgres and mysql
  tuning share index/query/replica; sourdough and pizza dough share
  hydration/ferment/flour. A note misfiled into a sibling zone drags its
  ~6 pairs wrong, and *densely* linking a misformed zone tanks precision —
  so "link all pairs" only pays off if the model also clusters correctly.
- **15 distractor singletons** that belong to no cluster and must NOT be
  linked (precision trap).

The scorer (in tune_linkrecall_hard) reports recovered/total intra-cluster
pairs (X/232) and link precision (are linked pairs actually intra-cluster —
both over cluster-note links and over ALL links including distractors).
Reaching 0.90 recall here requires near-perfect placement AND completeness.

CONTAMINATION NOTE: the shared curation prompt must NOT name this fixture's
cluster boundaries as examples (postgres/mysql, sourdough/pizza,
running/cycling, the networking trio, Korean cooking). Runs before 2026-07-05
used a prompt that did; results tagged v6-clean and later use the
decontaminated prompt with fixture-disjoint examples.
"""

from __future__ import annotations

import itertools
from pathlib import Path

# Each cluster: zone-hint theme → list of (title, body). Bodies deliberately
# share surface vocabulary with sibling clusters to make placement hard.
CLUSTERS: dict[str, list[tuple[str, str]]] = {
    "k8s-networking": [
        ("K8s ingress DNS", "nginx ingress resolves service dns inside the cluster; firewall allows 443 to the ingress subnet."),
        ("Cluster CNI subnet", "the CNI assigns a pod subnet per node; overlay handles cross-node dns and firewall policy."),
        ("NetworkPolicy firewall", "kubernetes NetworkPolicy is the in-cluster firewall; default-deny then allow dns egress."),
        ("Service mesh mTLS", "the mesh sidecar terminates mTLS between services; dns names route through the mesh, not the LAN."),
        ("Ingress cert rotation", "cert-manager rotates the ingress TLS cert; the firewall must trust the ACME dns-01 challenge."),
        ("CoreDNS tuning", "CoreDNS caches cluster dns; scale replicas when pod dns lookups to the subnet spike."),
        ("LoadBalancer service", "a LoadBalancer service exposes a subnet IP; the firewall maps the external dns to the cluster."),
        ("Pod egress NAT", "pod egress SNATs to the node subnet; the firewall and dns policy decide what leaves the cluster."),
    ],
    "aws-networking": [
        ("VPC subnet layout", "the VPC splits public and private subnets per AZ; the security-group firewall gates each subnet."),
        ("Route53 DNS", "Route53 resolves the public dns; private hosted zones map internal dns to the VPC subnet."),
        ("Security group rules", "the security group is the instance firewall; allow 443 inbound, dns 53 outbound to the subnet."),
        ("NAT gateway egress", "private subnet egress goes through the NAT gateway; the firewall logs dns and https flows."),
        ("VPC peering", "peering connects two VPC subnets; dns resolution across the peer needs the firewall rule and route."),
        ("Transit gateway", "the transit gateway hubs many VPC subnets; centralized firewall and dns resolver serve each attachment."),
        ("PrivateLink endpoint", "a PrivateLink endpoint keeps traffic on the subnet; the firewall allows the endpoint dns only."),
    ],
    "home-networking": [
        ("Home router firewall", "the home router firewall blocks inbound; port-forward 443 to the NAS on the LAN subnet."),
        ("Pi-hole DNS", "Pi-hole is the LAN dns sinkhole; every device on the home subnet uses it and the firewall enforces it."),
        ("VLAN subnet split", "the managed switch splits IoT onto its own VLAN subnet; the firewall isolates it from the main LAN dns."),
        ("WireGuard VPN", "WireGuard tunnels home; the firewall opens one UDP port and dns routes back over the LAN subnet."),
        ("Mesh WiFi backhaul", "the mesh nodes share one subnet; the firewall and local dns stay on the router, not the satellites."),
        ("Static DHCP lease", "reserve a static DHCP lease per device on the LAN subnet so dns and firewall rules stay stable."),
    ],
    "postgres-tuning": [
        ("Postgres index bloat", "reindex to clear index bloat; the query planner picks a stale index and the replica lags."),
        ("Query plan analyze", "EXPLAIN ANALYZE shows the slow query does a seq scan; add a composite index to help the planner."),
        ("Streaming replication", "the postgres replica streams WAL; a long query on the primary stalls replication and index vacuum."),
        ("Autovacuum tuning", "tune autovacuum so dead tuples do not bloat the index; heavy write queries need it aggressive."),
        ("Connection pooling", "pgbouncer pools connections so query spikes do not exhaust the primary before the replica catches up."),
        ("Partial index", "a partial index over hot rows keeps the query fast without bloating; the replica rebuilds it cheaply."),
        ("WAL checkpoint", "space out WAL checkpoints so a burst of write queries does not stall the replica or the index flush."),
    ],
    "mysql-tuning": [
        ("MySQL slow query log", "the slow query log flags a full scan; a covering index fixes the query and eases the replica."),
        ("InnoDB buffer pool", "size the InnoDB buffer pool so hot index pages stay cached and query latency drops on the replica."),
        ("Binlog replication", "MySQL binlog drives replication; a big query blocks the replica and the index rebuild behind it."),
        ("Composite index order", "column order in a composite index decides whether the query uses it or scans; test on the replica."),
        ("Query cache off", "disable the legacy query cache; it serializes writes and hurts the replica more than the index helps."),
        ("Read replica routing", "route read queries to the replica; keep index-heavy analytics off the primary write path."),
    ],
    "sourdough": [
        ("Sourdough starter", "feed the sourdough starter 1:1:1; a ripe starter ferments the dough with more flour and hydration."),
        ("Bulk ferment cues", "the dough is ready when it domes; warm ferment shortens bulk and higher hydration flour slackens it."),
        ("Sourdough scoring", "score the high-hydration dough cold; steam sets the crust before the ferment gas escapes."),
        ("Levain build", "build the levain the night before; a stiff levain ferments slower and the dough holds hydration better."),
        ("Whole-grain hydration", "whole-grain flour drinks more water; raise hydration or the dough ferments dense and tight."),
        ("Cold retard proof", "retard the shaped dough overnight; the slow cold ferment deepens flavor before the hydration bakes off."),
        ("Crumb open structure", "an open crumb needs strong gluten, high hydration, and a lively ferment from ripe starter flour."),
    ],
    "pizza-dough": [
        ("Neapolitan dough", "Neapolitan dough is 60% hydration 00 flour; a cold ferment 48h builds flavor before the bake."),
        ("Poolish preferment", "a poolish preferment of flour and water ferments overnight, then goes into the final dough hydration."),
        ("Dough ball proof", "ball the dough and proof at room temp; over-ferment and the high-hydration flour tears when stretched."),
        ("Baking steel bake", "the baking steel mimics a deck; a well-fermented, hydrated dough leopards in ninety seconds."),
        ("00 flour gluten", "00 flour has fine gluten; hydration and a long ferment give the dough its stretch without tearing."),
        ("Same-day dough", "a warm same-day ferment skips the cold proof; raise yeast and drop hydration so the flour keeps shape."),
    ],
    "running-training": [
        ("Interval session", "run 6x800 intervals at threshold; watch heart rate on recovery and keep the interval pace even."),
        ("Long run fueling", "the weekly long run builds aerobic base; fuel every 45 min and keep heart rate in zone 2 recovery."),
        ("Taper week", "cut interval volume in the taper; heart rate should drop and legs recover before the race."),
        ("Cadence drills", "cadence drills raise turnover; short intervals at high cadence with full recovery between reps."),
        ("Heart-rate zones", "set heart-rate zones from a field test; easy runs stay zone 2, intervals hit zone 4 with recovery."),
        ("Tempo run", "the tempo run holds threshold heart rate; it bridges easy base and hard intervals with light recovery."),
    ],
    "cycling-training": [
        ("FTP interval", "ride 4x8 at FTP; hold power steady, watch heart rate, and spin easy for recovery between each interval."),
        ("Endurance base", "long endurance rides build the base; keep power in zone 2 and heart rate low for recovery adaptation."),
        ("Sweet spot block", "a sweet-spot block stacks sub-threshold intervals; recovery days keep heart rate and power in check."),
        ("Cadence work", "high-cadence intervals train the spin; recover fully so heart rate settles before the next effort."),
        ("VO2 max reps", "short VO2 intervals push heart rate near max; long recovery keeps power on target across the reps."),
        ("Zone 2 volume", "big zone 2 volume raises the aerobic ceiling; hold power easy and heart rate low for recovery."),
    ],
    "personal-finance": [
        ("Monthly budget", "the monthly budget splits fixed, variable, and savings; review the expense ledger against invoices."),
        ("Index fund plan", "dollar-cost into a broad index fund; dividends reinvest and the budget funds the monthly contribution."),
        ("Tax-loss harvest", "harvest tax losses in December; track cost basis in the ledger and mind the wash-sale window."),
        ("Emergency fund", "hold six months of expenses in the emergency fund; the budget tops it up before extra investing."),
        ("Dividend tracking", "log dividends in the ledger; a rising dividend stream supplements the budget over the years."),
        ("Retirement contribution", "max the tax-advantaged retirement account first; the budget automates the monthly contribution."),
    ],
    "home-espresso": [
        ("Grind dialing", "dial the grind finer until the shot pulls in 28s; dose and tamp stay fixed while grind moves."),
        ("Puck prep", "distribute and tamp level; channeling in the puck ruins extraction even at the right grind and dose."),
        ("Shot ratio", "target a 1:2 ratio in 27s; adjust grind first, then dose, to hit the extraction without bitterness."),
        ("Milk steaming", "steam milk to microfoam; stretch early then swirl, keeping the pitcher cool for latte-art pour."),
        ("Water hardness", "brew water hardness shifts extraction; too soft and the shot is sour, so tweak grind and dose to match."),
        ("Pre-infusion", "a gentle pre-infusion wets the puck evenly; it tames channeling before the full extraction pressure."),
    ],
    "photography": [
        ("Exposure triangle", "balance aperture, shutter, and ISO; open the aperture for shallow depth and drop ISO for clean files."),
        ("Golden hour", "shoot the golden hour for soft light; a wide aperture and low ISO keep the long shadows clean."),
        ("Focus stacking", "stack focus for macro depth; a narrow aperture diffracts, so blend several frames instead."),
        ("RAW editing", "edit the RAW for latitude; recover highlights, lift shadows, and hold ISO noise in the sky."),
        ("Long exposure", "a long exposure smooths water; stop the aperture down, drop ISO, and use a tripod to hold sharpness."),
        ("White balance", "set white balance in the RAW; golden-hour warmth and shade both shift it, so correct per frame."),
    ],
    "korean-cooking": [
        ("김치 담그기", "배추를 소금에 절여 김치를 담근다; 고춧가루와 젓갈로 양념하고 발효 온도를 낮게 유지한다."),
        ("된장찌개", "된장을 풀어 찌개를 끓인다; 두부와 애호박을 넣고 멸치 육수로 감칠맛을 낸다."),
        ("불고기 양념", "간장과 배로 불고기를 재운다; 설탕과 참기름으로 양념하고 센 불에 빠르게 굽는다."),
        ("비빔밥", "밥 위에 나물과 고추장을 올려 비빔밥을 만든다; 참기름을 두르고 계란을 얹는다."),
        ("잡채", "당면을 삶아 잡채를 무친다; 간장과 참기름으로 양념하고 채소를 볶아 섞는다."),
        ("김치찌개", "익은 김치로 찌개를 끓인다; 돼지고기와 두부를 넣고 고춧가루로 얼큰하게 양념한다."),
        ("파전", "밀가루 반죽에 쪽파를 넣어 파전을 부친다; 간장 양념장을 곁들이고 기름에 바삭하게 굽는다."),
    ],
}

DISTRACTORS: list[tuple[str, str]] = [
    ("Dentist appointment", "book the dental cleaning for next Tuesday afternoon."),
    ("Car oil change", "the car is due for an oil change at 90k km."),
    ("Library book due", "return the borrowed novel before the late fee."),
    ("Passport renewal", "the passport expires next spring; start the renewal."),
    ("Birthday gift idea", "get a board game for the nephew's birthday."),
    ("Plumber callback", "the kitchen tap drips; call the plumber back."),
    ("Flight seat pick", "choose an aisle seat for the long-haul flight."),
    ("Umbrella lost", "left the umbrella on the train; buy a cheap one."),
    ("Haircut booking", "schedule a haircut before the wedding."),
    ("Grocery run", "milk, eggs, and coffee beans are running low."),
    ("Battery recycle", "drop the dead AA batteries at the recycle bin."),
    ("Password reset", "reset the streaming account password after the lockout."),
    ("Gym membership", "the gym membership renews monthly; consider pausing."),
    ("Houseplant water", "the fern needs water twice a week in summer."),
    ("Parking permit", "the residential parking permit renews in April."),
]


def total_pairs() -> int:
    return sum(len(list(itertools.combinations(c, 2))) for c in CLUSTERS.values())


def truth_pairs(slug_fn) -> set:
    pairs = set()
    for notes in CLUSTERS.values():
        slugs = [slug_fn(t) for t, _ in notes]
        for a, b in itertools.combinations(slugs, 2):
            pairs.add(frozenset((a, b)))
    return pairs


def seed(vault: Path) -> dict:
    """Write all cluster + distractor notes into the inbox (vault root)."""
    from birkin_mnemosyne.mnemosyne import slug
    vault.mkdir(parents=True, exist_ok=True)

    def _note(title: str, body: str) -> str:
        return ("---\n"
                f"title: {title}\n"
                "type: fact\ncreated: 2026-07-04\nupdated: 2026-07-04\n"
                "confidence: 0.7\npolarity: positive\nversion: 1\n"
                "sources: [\"seed\"]\ntags: []\n---\n\n" + body + "\n")

    truth = {"clusters": {}, "distractors": []}
    for zone, notes in CLUSTERS.items():
        truth["clusters"][zone] = []
        for title, body in notes:
            s = slug(title)
            truth["clusters"][zone].append(s)
            (vault / f"{s}.md").write_text(_note(title, body), encoding="utf-8")
    for title, body in DISTRACTORS:
        s = slug(title)
        truth["distractors"].append(s)
        (vault / f"{s}.md").write_text(_note(title, body), encoding="utf-8")
    return truth


if __name__ == "__main__":
    n_notes = sum(len(c) for c in CLUSTERS.values()) + len(DISTRACTORS)
    print(f"clusters={len(CLUSTERS)} cluster-notes="
          f"{sum(len(c) for c in CLUSTERS.values())} "
          f"distractors={len(DISTRACTORS)} total-notes={n_notes}")
    print(f"intra-cluster pairs (the /N): {total_pairs()}")
    print(f"90% target: {int(0.9 * total_pairs() + 0.999)}")
