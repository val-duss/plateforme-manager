"""Snapshot et calcul de différences de sizing, pour l'historique des changements."""

from .models import InfraKind


def snapshot_environment(environment):
    """Retourne un état sérialisable (JSON-compatible) du sizing courant d'un environnement."""
    if environment.infra_kind == InfraKind.VM:
        items = [
            {
                "name": vm.name,
                "role": vm.role or "",
                "cpu_cores": vm.cpu_cores,
                "ram_gb": vm.ram_gb,
                "storage_gb": vm.storage_gb,
            }
            for vm in sorted(environment.vm_sizings, key=lambda v: v.name)
        ]
        return {
            "infra_kind": InfraKind.VM,
            "cpu": sum(i["cpu_cores"] for i in items),
            "ram": sum(i["ram_gb"] for i in items),
            "storage": sum(i["storage_gb"] for i in items),
            "items": items,
        }

    if environment.infra_kind == InfraKind.K8S:
        k = environment.k8s_sizing
        if not k:
            return {"infra_kind": InfraKind.K8S, "cpu": 0, "ram": 0, "storage": 0, "items": []}
        return {
            "infra_kind": InfraKind.K8S,
            "cpu": k.node_count * k.cpu_per_node,
            "ram": k.node_count * k.ram_per_node_gb,
            "storage": k.storage_total_gb,
            "items": [
                {
                    "node_count": k.node_count,
                    "cpu_per_node": k.cpu_per_node,
                    "ram_per_node_gb": k.ram_per_node_gb,
                    "storage_total_gb": k.storage_total_gb,
                }
            ],
        }

    if environment.infra_kind == InfraKind.AWS:
        a = environment.aws_sizing
        return {
            "infra_kind": InfraKind.AWS,
            "cpu": None,
            "ram": None,
            "storage": None,
            "items": [
                {
                    "region": (a.region if a else "") or "",
                    "account_id": (a.account_id if a else "") or "",
                    "notes": (a.notes if a else "") or "",
                }
            ],
        }

    return {"infra_kind": environment.infra_kind, "cpu": 0, "ram": 0, "storage": 0, "items": []}


def _fmt(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _vm_label(item):
    return f"{_fmt(item['cpu_cores'])} vCPU / {_fmt(item['ram_gb'])} Go RAM / {_fmt(item['storage_gb'])} Go stockage"


def diff_snapshots(before, after):
    """Calcule la liste des différences entre deux snapshots de sizing."""
    changes = []

    for field, label, unit in (
        ("cpu", "vCPU total", ""),
        ("ram", "RAM totale", " Go"),
        ("storage", "Stockage total", " Go"),
    ):
        b, a = before.get(field), after.get(field)
        if b != a:
            changes.append({"label": label, "before": f"{_fmt(b)}{unit}", "after": f"{_fmt(a)}{unit}"})

    infra_kind = after.get("infra_kind") or before.get("infra_kind")

    if infra_kind == InfraKind.VM:
        before_by_name = {i["name"]: i for i in before.get("items", [])}
        after_by_name = {i["name"]: i for i in after.get("items", [])}
        for name in sorted(set(before_by_name) | set(after_by_name)):
            b, a = before_by_name.get(name), after_by_name.get(name)
            if b and not a:
                changes.append({"label": f"VM « {name} » supprimée", "before": _vm_label(b), "after": "—"})
            elif a and not b:
                changes.append({"label": f"VM « {name} » ajoutée", "before": "—", "after": _vm_label(a)})
            elif a and b and a != b:
                changes.append({"label": f"VM « {name} » modifiée", "before": _vm_label(b), "after": _vm_label(a)})

    elif infra_kind == InfraKind.K8S:
        b = (before.get("items") or [{}])[0]
        a = (after.get("items") or [{}])[0]
        for field, label in (
            ("node_count", "Nombre de nœuds"),
            ("cpu_per_node", "vCPU par nœud"),
            ("ram_per_node_gb", "RAM par nœud (Go)"),
            ("storage_total_gb", "Stockage total (Go)"),
        ):
            if b.get(field) != a.get(field):
                changes.append({"label": label, "before": _fmt(b.get(field)), "after": _fmt(a.get(field))})

    elif infra_kind == InfraKind.AWS:
        b = (before.get("items") or [{}])[0]
        a = (after.get("items") or [{}])[0]
        for field, label in (("region", "Région"), ("account_id", "Compte AWS"), ("notes", "Notes")):
            if (b.get(field) or "") != (a.get(field) or ""):
                changes.append({"label": label, "before": _fmt(b.get(field)), "after": _fmt(a.get(field))})

    return changes


def summarize_diff(changes):
    if not changes:
        return ""
    return " · ".join(f"{c['label']} : {c['before']} → {c['after']}" for c in changes)
