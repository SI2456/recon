"""Supplier–buyer network graph with circular-trading (ITC fraud ring) detection.

Builds a directed graph across the caller's clients where an edge means
"supplier billed buyer", then enumerates elementary cycles with DFS. A cycle
(A -> B -> C -> A) is the classic circular-trading pattern used to inflate
input tax credit, so every edge inside a cycle is flagged suspicious and the
GST riding on those invoices is reported as ITC at risk.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, scoped_client_ids
from app.db.models import Client, Invoice, User
from app.db.session import get_db


router = APIRouter()

MAX_CYCLE_LENGTH = 6
MAX_CYCLES = 50


def _find_cycles(adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Enumerate elementary directed cycles (length >= 2) via DFS.

    Each cycle is emitted once, anchored at its lowest-ordered node, so
    rotations of the same ring are not double counted.
    """
    order = {node: i for i, node in enumerate(adjacency)}
    cycles: list[list[str]] = []

    def dfs(start: str, current: str, path: list[str], on_path: set[str]) -> None:
        if len(cycles) >= MAX_CYCLES:
            return
        for nxt in adjacency.get(current, ()):  # neighbours of current
            if nxt == start and len(path) >= 2:
                cycles.append(path[:])
            elif (
                nxt not in on_path
                and order.get(nxt, -1) > order[start]  # anchor at lowest node
                and len(path) < MAX_CYCLE_LENGTH
            ):
                on_path.add(nxt)
                path.append(nxt)
                dfs(start, nxt, path, on_path)
                path.pop()
                on_path.discard(nxt)

    for node in adjacency:
        dfs(node, node, [node], {node})
        if len(cycles) >= MAX_CYCLES:
            break
    return cycles


def _format_amount(value: float) -> str:
    if value >= 10_000_000:
        return f"₹{value / 10_000_000:.2f}Cr"
    if value >= 100_000:
        return f"₹{value / 100_000:.2f}L"
    if value >= 1_000:
        return f"₹{value / 1_000:.1f}K"
    return f"₹{value:.0f}"


@router.get("")
def graph(clientId: int = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_client_scope(db, user, clientId)

    # Build the network across the caller's whole portfolio so cross-client
    # rings are visible, not just the star around one client.
    client_ids = scoped_client_ids(db, user)
    clients = db.query(Client).filter(Client.id.in_(client_ids)).all() if client_ids else []
    buyer_gstin = {c.id: c.gstin for c in clients if c.gstin}

    nodes: dict[str, dict] = {}
    for client in clients:
        if client.gstin:
            nodes[client.gstin] = {"id": client.gstin, "label": client.name, "type": "client", "risk": "low"}

    # Aggregate invoices into directed edges: supplier -> buyer.
    edge_map: dict[tuple[str, str], dict] = {}
    invoices = db.query(Invoice).filter(Invoice.client_id.in_(client_ids)).all() if client_ids else []
    for inv in invoices:
        supplier = inv.supplier_gstin
        buyer = buyer_gstin.get(inv.client_id)
        if not supplier or not buyer or supplier == buyer:
            continue
        if supplier not in nodes:
            nodes[supplier] = {"id": supplier, "label": inv.supplier or supplier, "type": "supplier", "risk": "low"}
        key = (supplier, buyer)
        edge = edge_map.setdefault(key, {"from": supplier, "to": buyer, "amountValue": 0.0, "gst": 0.0, "count": 0})
        edge["amountValue"] += float(inv.total or 0)
        edge["gst"] += float(inv.gst or 0)
        edge["count"] += 1

    # Detect circular-trading rings.
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for supplier, buyer in edge_map:
        adjacency[supplier].add(buyer)
    raw_cycles = _find_cycles(adjacency)

    # Flag edges that lie on any cycle and tally ITC at risk per ring.
    suspicious_edges: set[tuple[str, str]] = set()
    cycles: list[dict] = []
    for ring in raw_cycles:
        pairs = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
        itc = 0.0
        for pair in pairs:
            suspicious_edges.add(pair)
            edge = edge_map.get(pair)
            if edge:
                itc += edge["gst"]
        for gstin in ring:
            if gstin in nodes:
                nodes[gstin]["risk"] = "critical"
        cycles.append({
            "gstins": ring,
            "labels": [nodes[g]["label"] for g in ring],
            "length": len(ring),
            "itc": round(itc, 2),
            "itcDisplay": _format_amount(itc),
        })

    edges = []
    for key, edge in edge_map.items():
        is_suspicious = key in suspicious_edges
        edges.append({
            "from": edge["from"],
            "to": edge["to"],
            "amount": _format_amount(edge["amountValue"]),
            "amountValue": round(edge["amountValue"], 2),
            "gst": round(edge["gst"], 2),
            "count": edge["count"],
            "suspicious": is_suspicious,
        })

    itc_at_risk = round(sum(c["itc"] for c in cycles), 2)
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "cycles": cycles,
        "metrics": {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "cyclesDetected": len(cycles),
            "suspiciousEdges": len(suspicious_edges),
            "itcAtRisk": itc_at_risk,
            "itcAtRiskDisplay": _format_amount(itc_at_risk),
        },
    }
