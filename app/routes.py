import json
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .models import (
    AwsSizing,
    Environment,
    EnvType,
    InfraKind,
    K8sSizing,
    Operation,
    OperationType,
    Platform,
    VMSizing,
    db,
)
from .sizing import diff_snapshots, snapshot_environment, summarize_diff

bp = Blueprint("main", __name__)


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_sizing_operation(environment, before, after, performed_by=None, file_path=None):
    """Si le sizing a changé, journalise le changement comme une opération RESIZING."""
    changes = diff_snapshots(before, after)
    if not changes:
        return None

    operation = Operation(
        platform_id=environment.platform_id,
        environment_id=environment.id,
        operation_type=OperationType.RESIZING,
        title=f"Changement de sizing — {EnvType.LABELS[environment.env_type]} ({InfraKind.LABELS[environment.infra_kind]})",
        description=summarize_diff(changes),
        performed_by=performed_by or None,
        file_path=file_path or None,
        sizing_before=json.dumps(before),
        sizing_after=json.dumps(after),
    )
    db.session.add(operation)
    return operation


# --- Plateformes ---------------------------------------------------------


@bp.route("/")
def index():
    platforms = Platform.query.order_by(Platform.name).all()
    return render_template("index.html", platforms=platforms)


@bp.route("/platforms/new", methods=["GET", "POST"])
def platform_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        client_name = request.form.get("client_name", "").strip()
        description = request.form.get("description", "").strip()

        if not name or not client_name:
            flash("Le nom de la plateforme et le nom du client sont obligatoires.", "error")
            return render_template(
                "platform_form.html",
                platform=None,
                form_data=request.form,
            )

        platform = Platform(name=name, client_name=client_name, description=description or None)
        db.session.add(platform)
        db.session.commit()
        flash("Plateforme créée.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("platform_form.html", platform=None, form_data={})


@bp.route("/platforms/<int:platform_id>")
def platform_detail(platform_id):
    platform = Platform.query.get_or_404(platform_id)
    return render_template(
        "platform_detail.html",
        platform=platform,
        env_types=EnvType,
        infra_kinds=InfraKind,
        operation_types=OperationType,
    )


@bp.route("/platforms/<int:platform_id>/edit", methods=["GET", "POST"])
def platform_edit(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        client_name = request.form.get("client_name", "").strip()
        description = request.form.get("description", "").strip()

        if not name or not client_name:
            flash("Le nom de la plateforme et le nom du client sont obligatoires.", "error")
            return render_template("platform_form.html", platform=platform, form_data=request.form)

        platform.name = name
        platform.client_name = client_name
        platform.description = description or None
        db.session.commit()
        flash("Plateforme mise à jour.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("platform_form.html", platform=platform, form_data=None)


@bp.route("/platforms/<int:platform_id>/delete", methods=["POST"])
def platform_delete(platform_id):
    platform = Platform.query.get_or_404(platform_id)
    db.session.delete(platform)
    db.session.commit()
    flash("Plateforme supprimée.", "success")
    return redirect(url_for("main.index"))


# --- Environnements -------------------------------------------------------


@bp.route("/platforms/<int:platform_id>/environments/new", methods=["GET", "POST"])
def environment_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        env_type = request.form.get("env_type")
        infra_kind = request.form.get("infra_kind")
        notes = request.form.get("notes", "").strip()

        if env_type not in EnvType.ALL or infra_kind not in InfraKind.ALL:
            flash("Type d'environnement ou type d'infrastructure invalide.", "error")
            return render_template(
                "environment_form.html",
                platform=platform,
                environment=None,
                env_types=EnvType,
                infra_kinds=InfraKind,
                form_data=request.form,
            )

        environment = Environment(
            platform_id=platform.id,
            env_type=env_type,
            infra_kind=infra_kind,
            notes=notes or None,
        )
        db.session.add(environment)
        db.session.flush()

        if infra_kind == InfraKind.K8S:
            db.session.add(K8sSizing(environment_id=environment.id))
        elif infra_kind == InfraKind.AWS:
            db.session.add(AwsSizing(environment_id=environment.id))

        db.session.commit()
        flash("Environnement créé. Renseignez maintenant son sizing.", "success")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    return render_template(
        "environment_form.html",
        platform=platform,
        environment=None,
        env_types=EnvType,
        infra_kinds=InfraKind,
        form_data={},
    )


@bp.route("/environments/<int:environment_id>/edit", methods=["GET", "POST"])
def environment_edit(environment_id):
    environment = Environment.query.get_or_404(environment_id)

    if request.method == "POST":
        env_type = request.form.get("env_type")
        infra_kind = request.form.get("infra_kind")
        notes = request.form.get("notes", "").strip()

        if env_type not in EnvType.ALL or infra_kind not in InfraKind.ALL:
            flash("Type d'environnement ou type d'infrastructure invalide.", "error")
            return redirect(url_for("main.environment_edit", environment_id=environment.id))

        environment.env_type = env_type

        if infra_kind != environment.infra_kind:
            for vm in list(environment.vm_sizings):
                db.session.delete(vm)
            if environment.k8s_sizing:
                db.session.delete(environment.k8s_sizing)
            if environment.aws_sizing:
                db.session.delete(environment.aws_sizing)

            environment.infra_kind = infra_kind
            db.session.flush()

            if infra_kind == InfraKind.K8S:
                db.session.add(K8sSizing(environment_id=environment.id))
            elif infra_kind == InfraKind.AWS:
                db.session.add(AwsSizing(environment_id=environment.id))

        environment.notes = notes or None
        db.session.commit()
        flash("Environnement mis à jour.", "success")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    return render_template(
        "environment_form.html",
        platform=environment.platform,
        environment=environment,
        env_types=EnvType,
        infra_kinds=InfraKind,
        form_data=None,
    )


@bp.route("/environments/<int:environment_id>/delete", methods=["POST"])
def environment_delete(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    platform_id = environment.platform_id
    db.session.delete(environment)
    db.session.commit()
    flash("Environnement supprimé.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))


# --- Sizing VM --------------------------------------------------------------


@bp.route("/environments/<int:environment_id>/vms/add", methods=["POST"])
def vm_add(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    if environment.infra_kind != InfraKind.VM:
        flash("Cet environnement n'est pas de type Machines virtuelles.", "error")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    name = request.form.get("name", "").strip()
    role = request.form.get("role", "").strip()
    cpu_cores = parse_int(request.form.get("cpu_cores"))
    ram_gb = parse_float(request.form.get("ram_gb"))
    storage_gb = parse_float(request.form.get("storage_gb"))

    if not name or cpu_cores is None or ram_gb is None or storage_gb is None:
        flash("Merci de renseigner un nom et des valeurs numériques valides pour la VM.", "error")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    before = snapshot_environment(environment)
    environment.vm_sizings.append(
        VMSizing(name=name, role=role or None, cpu_cores=cpu_cores, ram_gb=ram_gb, storage_gb=storage_gb)
    )
    db.session.flush()
    after = snapshot_environment(environment)
    record_sizing_operation(environment, before, after, performed_by=request.form.get("performed_by", "").strip())

    db.session.commit()
    flash("Machine virtuelle ajoutée.", "success")
    return redirect(url_for("main.environment_edit", environment_id=environment.id))


@bp.route("/vms/<int:vm_id>/edit", methods=["GET", "POST"])
def vm_edit(vm_id):
    vm = VMSizing.query.get_or_404(vm_id)
    environment = vm.environment

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "").strip()
        cpu_cores = parse_int(request.form.get("cpu_cores"))
        ram_gb = parse_float(request.form.get("ram_gb"))
        storage_gb = parse_float(request.form.get("storage_gb"))

        if not name or cpu_cores is None or ram_gb is None or storage_gb is None:
            flash("Merci de renseigner un nom et des valeurs numériques valides pour la VM.", "error")
            return redirect(url_for("main.vm_edit", vm_id=vm.id))

        before = snapshot_environment(environment)
        vm.name = name
        vm.role = role or None
        vm.cpu_cores = cpu_cores
        vm.ram_gb = ram_gb
        vm.storage_gb = storage_gb
        db.session.flush()
        after = snapshot_environment(environment)
        record_sizing_operation(environment, before, after, performed_by=request.form.get("performed_by", "").strip())

        db.session.commit()
        flash("Machine virtuelle mise à jour.", "success")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    return render_template("vm_form.html", vm=vm, environment=environment, platform=environment.platform)


@bp.route("/vms/<int:vm_id>/delete", methods=["POST"])
def vm_delete(vm_id):
    vm = VMSizing.query.get_or_404(vm_id)
    environment = vm.environment
    environment_id = environment.id

    before = snapshot_environment(environment)
    environment.vm_sizings.remove(vm)
    db.session.flush()
    after = snapshot_environment(environment)
    record_sizing_operation(environment, before, after)

    db.session.commit()
    flash("Machine virtuelle supprimée.", "success")
    return redirect(url_for("main.environment_edit", environment_id=environment_id))


# --- Sizing Kubernetes -------------------------------------------------------


@bp.route("/environments/<int:environment_id>/k8s", methods=["POST"])
def k8s_update(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    if environment.infra_kind != InfraKind.K8S:
        flash("Cet environnement n'est pas de type Kubernetes.", "error")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    node_count = parse_int(request.form.get("node_count"))
    cpu_per_node = parse_float(request.form.get("cpu_per_node"))
    ram_per_node_gb = parse_float(request.form.get("ram_per_node_gb"))
    storage_total_gb = parse_float(request.form.get("storage_total_gb"))

    if None in (node_count, cpu_per_node, ram_per_node_gb, storage_total_gb):
        flash("Merci de renseigner des valeurs numériques valides pour le cluster.", "error")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    before = snapshot_environment(environment)

    if not environment.k8s_sizing:
        environment.k8s_sizing = K8sSizing(environment_id=environment.id)
        db.session.add(environment.k8s_sizing)

    environment.k8s_sizing.node_count = node_count
    environment.k8s_sizing.cpu_per_node = cpu_per_node
    environment.k8s_sizing.ram_per_node_gb = ram_per_node_gb
    environment.k8s_sizing.storage_total_gb = storage_total_gb
    db.session.flush()
    after = snapshot_environment(environment)
    record_sizing_operation(environment, before, after, performed_by=request.form.get("performed_by", "").strip())

    db.session.commit()
    flash("Sizing Kubernetes mis à jour.", "success")
    return redirect(url_for("main.environment_edit", environment_id=environment.id))


# --- Sizing AWS (squelette) --------------------------------------------------


@bp.route("/environments/<int:environment_id>/aws", methods=["POST"])
def aws_update(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    if environment.infra_kind != InfraKind.AWS:
        flash("Cet environnement n'est pas de type AWS.", "error")
        return redirect(url_for("main.environment_edit", environment_id=environment.id))

    region = request.form.get("region", "").strip()
    account_id = request.form.get("account_id", "").strip()
    notes = request.form.get("notes", "").strip()

    before = snapshot_environment(environment)

    if not environment.aws_sizing:
        environment.aws_sizing = AwsSizing(environment_id=environment.id)
        db.session.add(environment.aws_sizing)

    environment.aws_sizing.region = region or None
    environment.aws_sizing.account_id = account_id or None
    environment.aws_sizing.notes = notes or None
    db.session.flush()
    after = snapshot_environment(environment)
    record_sizing_operation(environment, before, after, performed_by=request.form.get("performed_by", "").strip())

    db.session.commit()
    flash("Informations AWS mises à jour.", "success")
    return redirect(url_for("main.environment_edit", environment_id=environment.id))


# --- Opérations / journal ----------------------------------------------------


@bp.route("/platforms/<int:platform_id>/operations/new", methods=["GET", "POST"])
def operation_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        operation_type = request.form.get("operation_type")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        performed_by = request.form.get("performed_by", "").strip()
        file_path = request.form.get("file_path", "").strip()
        performed_at_raw = request.form.get("performed_at")
        environment_id = request.form.get("environment_id") or None

        if operation_type not in OperationType.ALL or not title:
            flash("Merci de renseigner un type d'opération et un titre.", "error")
            return render_template(
                "operation_form.html",
                platform=platform,
                operation_types=OperationType,
                form_data=request.form,
            )

        performed_at = datetime.utcnow()
        if performed_at_raw:
            try:
                performed_at = datetime.strptime(performed_at_raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        operation = Operation(
            platform_id=platform.id,
            environment_id=int(environment_id) if environment_id else None,
            operation_type=operation_type,
            title=title,
            description=description or None,
            performed_by=performed_by or None,
            file_path=file_path or None,
            performed_at=performed_at,
        )
        db.session.add(operation)
        db.session.commit()
        flash("Opération enregistrée dans le journal.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template(
        "operation_form.html",
        platform=platform,
        operation_types=OperationType,
        form_data={},
    )


@bp.route("/operations/<int:operation_id>", methods=["GET", "POST"])
def operation_edit(operation_id):
    operation = Operation.query.get_or_404(operation_id)
    platform = operation.platform

    if request.method == "POST":
        operation_type = request.form.get("operation_type")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        performed_by = request.form.get("performed_by", "").strip()
        file_path = request.form.get("file_path", "").strip()
        performed_at_raw = request.form.get("performed_at")
        environment_id = request.form.get("environment_id") or None

        if operation_type not in OperationType.ALL or not title:
            flash("Merci de renseigner un type d'opération et un titre.", "error")
            return redirect(url_for("main.operation_edit", operation_id=operation.id))

        performed_at = operation.performed_at
        if performed_at_raw:
            try:
                performed_at = datetime.strptime(performed_at_raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        operation.operation_type = operation_type
        operation.title = title
        operation.description = description or None
        operation.performed_by = performed_by or None
        operation.file_path = file_path or None
        operation.performed_at = performed_at
        operation.environment_id = int(environment_id) if environment_id else None
        db.session.commit()
        flash("Opération mise à jour.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template(
        "operation_edit.html",
        operation=operation,
        platform=platform,
        operation_types=OperationType,
    )


@bp.route("/operations/<int:operation_id>/delete", methods=["POST"])
def operation_delete(operation_id):
    operation = Operation.query.get_or_404(operation_id)
    platform_id = operation.platform_id
    db.session.delete(operation)
    db.session.commit()
    flash("Opération supprimée du journal.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))


@bp.route("/journal")
def journal():
    operations = Operation.query.order_by(Operation.performed_at.desc()).limit(300).all()
    return render_template("journal.html", operations=operations, operation_types=OperationType)
