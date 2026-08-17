import calendar
import json
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .checks import MONTH_NAMES_FR, STATUS_LABELS, WEEKDAY_NAMES_FR, WEEKDAY_NAMES_FR_LONG, compute_environment_statuses
from .models import (
    ActionPlan,
    AlertSeverity,
    AppSettings,
    AwsSizing,
    BillingEntry,
    BillingPeriodicity,
    CheckStatus,
    DailyCheck,
    Environment,
    EnvironmentAlert,
    EnvType,
    Incident,
    InfraKind,
    K8sSizing,
    Operation,
    OperationType,
    Platform,
    Presale,
    PresaleStatus,
    Procedure,
    ProcedureStep,
    ProcedureStepTest,
    ResourceUsage,
    SupervisionLink,
    Task,
    TaskStatus,
    TaskType,
    VMSizing,
    db,
)
from .sizing import diff_snapshots, snapshot_environment, summarize_diff

bp = Blueprint("main", __name__)

# Racine du projet (parent du package app/), où vivent les scripts de lancement.
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WINDOWS_SCRIPTS = {
    "demarrer-application.sh": "Script shell (WSL/Linux/macOS) : démarre l'application (construit l'image si besoin) et l'ouvre dans sa propre fenêtre.",
    "mettre-a-jour-et-rebuild.sh": "Script shell (WSL/Linux/macOS) : récupère les dernières modifications (git pull) puis reconstruit et redémarre l'application.",
    "demarrer-application.bat": "Raccourci Windows : délègue à WSL et exécute demarrer-application.sh.",
    "mettre-a-jour-et-rebuild.bat": "Raccourci Windows : délègue à WSL et exécute mettre-a-jour-et-rebuild.sh.",
}


# --- Authentification par PIN -----------------------------------------


@bp.before_request
def require_pin():
    if request.endpoint == "main.login":
        return
    if not session.get("authenticated"):
        return redirect(url_for("main.login", next=request.path))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        settings = AppSettings.query.get(1)
        if settings and check_password_hash(settings.pin_hash, pin):
            session["authenticated"] = True
            next_path = request.form.get("next") or url_for("main.index")
            return redirect(next_path)
        flash("Code PIN incorrect.", "error")

    next_path = request.args.get("next", "")
    return render_template("login.html", next_path=next_path)


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("authenticated", None)
    flash("Vous avez été déconnecté.", "success")
    return redirect(url_for("main.login"))


@bp.route("/parametres", methods=["GET", "POST"])
def settings_page():
    settings = AppSettings.query.get(1)

    if request.method == "POST":
        current_pin = request.form.get("current_pin", "").strip()
        new_pin = request.form.get("new_pin", "").strip()
        confirm_pin = request.form.get("confirm_pin", "").strip()

        if not check_password_hash(settings.pin_hash, current_pin):
            flash("Le PIN actuel est incorrect.", "error")
        elif not (new_pin.isdigit() and len(new_pin) == 4):
            flash("Le nouveau PIN doit être composé de 4 chiffres.", "error")
        elif new_pin != confirm_pin:
            flash("La confirmation ne correspond pas au nouveau PIN.", "error")
        else:
            settings.pin_hash = generate_password_hash(new_pin)
            db.session.commit()
            flash("PIN mis à jour.", "success")
            return redirect(url_for("main.settings_page"))

    return render_template("settings.html")


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


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def normalize_url(url):
    if url and not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def parse_hours_minutes(hours_value, minutes_value):
    hours = parse_int(hours_value) or 0
    minutes = parse_int(minutes_value) or 0
    return max(hours, 0) * 60 + max(minutes, 0)


def format_duration(total_minutes):
    if total_minutes is None:
        return "—"
    total_minutes = int(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def platform_downtime_minutes(platform_id, start_date, end_date):
    total = (
        db.session.query(db.func.coalesce(db.func.sum(Incident.downtime_minutes), 0))
        .filter(Incident.platform_id == platform_id, Incident.date >= start_date, Incident.date <= end_date)
        .scalar()
    )
    return total or 0


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
    return render_template("home.html")


@bp.route("/plateformes")
def platforms_list():
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

    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    return render_template(
        "platform_detail.html",
        platform=platform,
        env_types=EnvType,
        infra_kinds=InfraKind,
        operation_types=OperationType,
        downtime_month=platform_downtime_minutes(platform.id, month_start, today),
        downtime_year=platform_downtime_minutes(platform.id, year_start, today),
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
    return redirect(url_for("main.platforms_list"))


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


# --- Procédures ---------------------------------------------------------


@bp.route("/platforms/<int:platform_id>/procedures/new", methods=["GET", "POST"])
def procedure_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Le titre de la procédure est obligatoire.", "error")
            return render_template(
                "procedure_form.html", platform=platform, procedure=None, form_data=request.form
            )

        procedure = Procedure(platform_id=platform.id, title=title, description=description or None)
        db.session.add(procedure)
        db.session.commit()
        flash("Procédure créée. Ajoutez maintenant ses étapes.", "success")
        return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))

    return render_template("procedure_form.html", platform=platform, procedure=None, form_data={})


@bp.route("/procedures/<int:procedure_id>", methods=["GET", "POST"])
def procedure_edit(procedure_id):
    procedure = Procedure.query.get_or_404(procedure_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Le titre de la procédure est obligatoire.", "error")
            return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))

        procedure.title = title
        procedure.description = description or None
        db.session.commit()
        flash("Procédure mise à jour.", "success")
        return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))

    return render_template("procedure_edit.html", procedure=procedure, platform=procedure.platform)


@bp.route("/procedures/<int:procedure_id>/delete", methods=["POST"])
def procedure_delete(procedure_id):
    procedure = Procedure.query.get_or_404(procedure_id)
    platform_id = procedure.platform_id
    db.session.delete(procedure)
    db.session.commit()
    flash("Procédure supprimée.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))


@bp.route("/procedures/<int:procedure_id>/steps/add", methods=["POST"])
def step_add(procedure_id):
    procedure = Procedure.query.get_or_404(procedure_id)
    title = request.form.get("title", "").strip()
    instructions = request.form.get("instructions", "").strip()

    if not title:
        flash("Le titre de l'étape est obligatoire.", "error")
        return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))

    next_position = max([s.position for s in procedure.steps], default=0) + 1
    procedure.steps.append(
        ProcedureStep(title=title, instructions=instructions or None, position=next_position)
    )
    db.session.commit()
    flash("Étape ajoutée.", "success")
    return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))


@bp.route("/steps/<int:step_id>/edit", methods=["GET", "POST"])
def step_edit(step_id):
    step = ProcedureStep.query.get_or_404(step_id)
    procedure = step.procedure

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()

        if not title:
            flash("Le titre de l'étape est obligatoire.", "error")
            return redirect(url_for("main.step_edit", step_id=step.id))

        step.title = title
        step.instructions = instructions or None
        db.session.commit()
        flash("Étape mise à jour.", "success")
        return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))

    return render_template("step_form.html", step=step, procedure=procedure, platform=procedure.platform)


@bp.route("/steps/<int:step_id>/delete", methods=["POST"])
def step_delete(step_id):
    step = ProcedureStep.query.get_or_404(step_id)
    procedure_id = step.procedure_id
    db.session.delete(step)
    db.session.commit()
    flash("Étape supprimée.", "success")
    return redirect(url_for("main.procedure_edit", procedure_id=procedure_id))


@bp.route("/steps/<int:step_id>/move", methods=["POST"])
def step_move(step_id):
    step = ProcedureStep.query.get_or_404(step_id)
    procedure = step.procedure
    direction = request.form.get("direction")

    steps = procedure.steps
    index = steps.index(step)
    if direction == "up":
        swap_index = index - 1
    elif direction == "down":
        swap_index = index + 1
    else:
        swap_index = None

    if swap_index is not None and 0 <= swap_index < len(steps):
        other = steps[swap_index]
        step.position, other.position = other.position, step.position
        db.session.commit()

    return redirect(url_for("main.procedure_edit", procedure_id=procedure.id))


@bp.route("/steps/<int:step_id>/tests/add", methods=["POST"])
def step_test_add(step_id):
    step = ProcedureStep.query.get_or_404(step_id)
    description = request.form.get("description", "").strip()

    if not description:
        flash("Merci de renseigner une description pour le test.", "error")
        return redirect(url_for("main.procedure_edit", procedure_id=step.procedure_id))

    step.tests.append(ProcedureStepTest(description=description))
    db.session.commit()
    flash("Test ajouté.", "success")
    return redirect(url_for("main.procedure_edit", procedure_id=step.procedure_id))


@bp.route("/tests/<int:test_id>/delete", methods=["POST"])
def step_test_delete(test_id):
    test = ProcedureStepTest.query.get_or_404(test_id)
    procedure_id = test.step.procedure_id
    db.session.delete(test)
    db.session.commit()
    flash("Test supprimé.", "success")
    return redirect(url_for("main.procedure_edit", procedure_id=procedure_id))


# --- Outils Windows ----------------------------------------------------


@bp.route("/outils")
def tools():
    return render_template("tools.html", scripts=WINDOWS_SCRIPTS)


@bp.route("/outils/telecharger/<path:filename>")
def tools_download(filename):
    if filename not in WINDOWS_SCRIPTS:
        abort(404)
    return send_from_directory(APP_ROOT, filename, as_attachment=True)


# --- Facturation (par plateforme) --------------------------------------


@bp.route("/platforms/<int:platform_id>/facturation/new", methods=["GET", "POST"])
def billing_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        label = request.form.get("label", "").strip()
        amount = parse_float(request.form.get("amount"))
        periodicity = request.form.get("periodicity")
        start_date = parse_date(request.form.get("start_date"))
        end_date = parse_date(request.form.get("end_date"))
        notes = request.form.get("notes", "").strip()

        if not label or periodicity not in BillingPeriodicity.ALL:
            flash("Merci de renseigner un libellé et une périodicité valide.", "error")
            return render_template(
                "billing_form.html", platform=platform, entry=None, periodicities=BillingPeriodicity, form_data=request.form
            )

        platform.billing_entries.append(
            BillingEntry(
                label=label,
                amount=amount,
                periodicity=periodicity,
                start_date=start_date,
                end_date=end_date,
                notes=notes or None,
            )
        )
        db.session.commit()
        flash("Ligne de facturation ajoutée.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template(
        "billing_form.html", platform=platform, entry=None, periodicities=BillingPeriodicity, form_data={}
    )


@bp.route("/facturation/<int:entry_id>/edit", methods=["GET", "POST"])
def billing_edit(entry_id):
    entry = BillingEntry.query.get_or_404(entry_id)
    platform = entry.platform

    if request.method == "POST":
        label = request.form.get("label", "").strip()
        amount = parse_float(request.form.get("amount"))
        periodicity = request.form.get("periodicity")
        start_date = parse_date(request.form.get("start_date"))
        end_date = parse_date(request.form.get("end_date"))
        notes = request.form.get("notes", "").strip()

        if not label or periodicity not in BillingPeriodicity.ALL:
            flash("Merci de renseigner un libellé et une périodicité valide.", "error")
            return redirect(url_for("main.billing_edit", entry_id=entry.id))

        entry.label = label
        entry.amount = amount
        entry.periodicity = periodicity
        entry.start_date = start_date
        entry.end_date = end_date
        entry.notes = notes or None
        db.session.commit()
        flash("Ligne de facturation mise à jour.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template(
        "billing_form.html", platform=platform, entry=entry, periodicities=BillingPeriodicity, form_data=None
    )


@bp.route("/facturation/<int:entry_id>/delete", methods=["POST"])
def billing_delete(entry_id):
    entry = BillingEntry.query.get_or_404(entry_id)
    platform_id = entry.platform_id
    db.session.delete(entry)
    db.session.commit()
    flash("Ligne de facturation supprimée.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))


# --- Avant-ventes (global) -----------------------------------------------


@bp.route("/avant-ventes")
def presales_list():
    presales = Presale.query.order_by(Presale.created_at.desc()).all()
    return render_template("presales_list.html", presales=presales)


@bp.route("/avant-ventes/new", methods=["GET", "POST"])
def presale_new():
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        project_name = request.form.get("project_name", "").strip()
        status = request.form.get("status")
        estimated_amount = parse_float(request.form.get("estimated_amount"))
        contact = request.form.get("contact", "").strip()
        expected_date = parse_date(request.form.get("expected_date"))
        notes = request.form.get("notes", "").strip()

        if not client_name or not project_name or status not in PresaleStatus.ALL:
            flash("Merci de renseigner un client, un projet et un statut valide.", "error")
            return render_template("presale_form.html", presale=None, form_data=request.form)

        presale = Presale(
            client_name=client_name,
            project_name=project_name,
            status=status,
            estimated_amount=estimated_amount,
            contact=contact or None,
            expected_date=expected_date,
            notes=notes or None,
        )
        db.session.add(presale)
        db.session.commit()
        flash("Opportunité créée.", "success")
        return redirect(url_for("main.presales_list"))

    return render_template("presale_form.html", presale=None, form_data={})


@bp.route("/avant-ventes/<int:presale_id>/edit", methods=["GET", "POST"])
def presale_edit(presale_id):
    presale = Presale.query.get_or_404(presale_id)

    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        project_name = request.form.get("project_name", "").strip()
        status = request.form.get("status")
        estimated_amount = parse_float(request.form.get("estimated_amount"))
        contact = request.form.get("contact", "").strip()
        expected_date = parse_date(request.form.get("expected_date"))
        notes = request.form.get("notes", "").strip()

        if not client_name or not project_name or status not in PresaleStatus.ALL:
            flash("Merci de renseigner un client, un projet et un statut valide.", "error")
            return redirect(url_for("main.presale_edit", presale_id=presale.id))

        presale.client_name = client_name
        presale.project_name = project_name
        presale.status = status
        presale.estimated_amount = estimated_amount
        presale.contact = contact or None
        presale.expected_date = expected_date
        presale.notes = notes or None
        db.session.commit()
        flash("Opportunité mise à jour.", "success")
        return redirect(url_for("main.presales_list"))

    return render_template("presale_form.html", presale=presale, form_data=None)


@bp.route("/avant-ventes/<int:presale_id>/delete", methods=["POST"])
def presale_delete(presale_id):
    presale = Presale.query.get_or_404(presale_id)
    db.session.delete(presale)
    db.session.commit()
    flash("Opportunité supprimée.", "success")
    return redirect(url_for("main.presales_list"))


# --- Tâches (global, avec plateforme optionnelle) -------------------------


@bp.route("/taches")
def tasks_list():
    tasks = Task.query.order_by(Task.status, Task.due_date.is_(None), Task.due_date).all()
    return render_template("tasks_list.html", tasks=tasks)


@bp.route("/taches/new", methods=["GET", "POST"])
def task_new():
    platform_id = request.args.get("platform_id", type=int)
    platforms = Platform.query.order_by(Platform.name).all()

    if request.method == "POST":
        task_type = request.form.get("task_type")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status")
        assigned_to = request.form.get("assigned_to", "").strip()
        due_date = parse_date(request.form.get("due_date"))
        form_platform_id = request.form.get("platform_id") or None

        if task_type not in TaskType.ALL or not title or status not in TaskStatus.ALL:
            flash("Merci de renseigner un type, un titre et un statut valides.", "error")
            return render_template(
                "task_form.html", task=None, platforms=platforms, form_data=request.form
            )

        task = Task(
            platform_id=int(form_platform_id) if form_platform_id else None,
            task_type=task_type,
            title=title,
            description=description or None,
            status=status,
            assigned_to=assigned_to or None,
            due_date=due_date,
        )
        db.session.add(task)
        db.session.commit()
        flash("Tâche créée.", "success")
        if task.platform_id:
            return redirect(url_for("main.platform_detail", platform_id=task.platform_id))
        return redirect(url_for("main.tasks_list"))

    return render_template(
        "task_form.html",
        task=None,
        platforms=platforms,
        form_data={"platform_id": str(platform_id)} if platform_id else {},
    )


@bp.route("/taches/<int:task_id>/edit", methods=["GET", "POST"])
def task_edit(task_id):
    task = Task.query.get_or_404(task_id)
    platforms = Platform.query.order_by(Platform.name).all()

    if request.method == "POST":
        task_type = request.form.get("task_type")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status")
        assigned_to = request.form.get("assigned_to", "").strip()
        due_date = parse_date(request.form.get("due_date"))
        form_platform_id = request.form.get("platform_id") or None

        if task_type not in TaskType.ALL or not title or status not in TaskStatus.ALL:
            flash("Merci de renseigner un type, un titre et un statut valides.", "error")
            return redirect(url_for("main.task_edit", task_id=task.id))

        task.task_type = task_type
        task.title = title
        task.description = description or None
        task.status = status
        task.assigned_to = assigned_to or None
        task.due_date = due_date
        task.platform_id = int(form_platform_id) if form_platform_id else None
        db.session.commit()
        flash("Tâche mise à jour.", "success")
        return redirect(url_for("main.tasks_list"))

    return render_template("task_form.html", task=task, platforms=platforms, form_data=None)


@bp.route("/taches/<int:task_id>/delete", methods=["POST"])
def task_delete(task_id):
    task = Task.query.get_or_404(task_id)
    redirect_platform_id = task.platform_id
    db.session.delete(task)
    db.session.commit()
    flash("Tâche supprimée.", "success")
    return redirect(
        url_for("main.platform_detail", platform_id=redirect_platform_id)
        if redirect_platform_id
        else url_for("main.tasks_list")
    )


# --- Check journalier ----------------------------------------------------


def _all_environments():
    return Environment.query.join(Platform).order_by(Platform.name, Environment.env_type).all()


@bp.route("/check-journalier")
def daily_check():
    check_date = parse_date(request.args.get("date")) or date.today()
    environments = _all_environments()
    env_ids = [e.id for e in environments]

    checks_today = {
        c.environment_id: c
        for c in DailyCheck.query.filter(
            DailyCheck.environment_id.in_(env_ids), DailyCheck.check_date == check_date
        ).all()
    }

    return render_template(
        "daily_check.html",
        environments=environments,
        check_date=check_date,
        today=date.today(),
        prev_date=check_date - timedelta(days=1),
        next_date=check_date + timedelta(days=1),
        checks_today=checks_today,
        CheckStatus=CheckStatus,
        AlertSeverity=AlertSeverity,
    )


@bp.route("/check-journalier/<int:environment_id>/ok", methods=["POST"])
def daily_check_ok(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    check_date = parse_date(request.form.get("date")) or date.today()

    if environment.open_alerts:
        flash("Impossible de confirmer RAS : une alerte est encore ouverte sur cet environnement.", "error")
        return redirect(url_for("main.daily_check", date=check_date.isoformat()))

    existing = DailyCheck.query.filter_by(environment_id=environment.id, check_date=check_date).first()
    if existing:
        existing.status = CheckStatus.OK
        existing.checked_at = datetime.utcnow()
    else:
        db.session.add(
            DailyCheck(
                environment_id=environment.id,
                check_date=check_date,
                status=CheckStatus.OK,
            )
        )
    db.session.commit()
    flash("Vérification enregistrée : RAS.", "success")
    return redirect(url_for("main.daily_check", date=check_date.isoformat()))


@bp.route("/check-journalier/<int:environment_id>/alerte", methods=["POST"])
def daily_check_alert(environment_id):
    environment = Environment.query.get_or_404(environment_id)
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    severity = request.form.get("severity")
    check_date = parse_date(request.form.get("date")) or date.today()

    if not title or severity not in AlertSeverity.ALL:
        flash("Merci de renseigner un titre et un type d'alerte valide.", "error")
        return redirect(url_for("main.daily_check", date=check_date.isoformat()))

    db.session.add(
        EnvironmentAlert(
            environment_id=environment.id,
            title=title,
            description=description or None,
            severity=severity,
        )
    )
    db.session.add(
        Operation(
            platform_id=environment.platform_id,
            environment_id=environment.id,
            operation_type=OperationType.INCIDENT,
            title=f"Alerte ({AlertSeverity.LABELS[severity]}) : {title}",
            description=description or None,
        )
    )
    db.session.commit()
    flash("Alerte enregistrée.", "success")
    return redirect(url_for("main.daily_check", date=check_date.isoformat()))


@bp.route("/alertes/<int:alert_id>/clore", methods=["POST"])
def alert_close(alert_id):
    alert = EnvironmentAlert.query.get_or_404(alert_id)
    closed_by = request.form.get("closed_by", "").strip()
    resolution_notes = request.form.get("resolution_notes", "").strip()
    next_path = request.form.get("next") or url_for("main.daily_check")

    alert.closed_at = datetime.utcnow()
    alert.closed_by = closed_by or None
    alert.resolution_notes = resolution_notes or None

    db.session.add(
        Operation(
            platform_id=alert.environment.platform_id,
            environment_id=alert.environment_id,
            operation_type=OperationType.INCIDENT,
            title=f"Clôture d'alerte : {alert.title}",
            description=resolution_notes or None,
            performed_by=closed_by or None,
        )
    )
    db.session.commit()
    flash("Alerte clôturée.", "success")
    return redirect(next_path)


@bp.route("/check-journalier/semaine")
def daily_check_week():
    start = parse_date(request.args.get("start"))
    if not start:
        today = date.today()
        start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)

    environments = _all_environments()
    days, status_by_env = compute_environment_statuses(environments, start, end)

    return render_template(
        "daily_check_overview.html",
        environments=environments,
        days=days,
        status_by_env=status_by_env,
        period_label=f"Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m/%Y')}",
        prev_url=url_for("main.daily_check_week", start=(start - timedelta(days=7)).isoformat()),
        next_url=url_for("main.daily_check_week", start=(start + timedelta(days=7)).isoformat()),
        day_labels=WEEKDAY_NAMES_FR,
        today=date.today(),
        status_labels=STATUS_LABELS,
    )


@bp.route("/check-journalier/mois")
def daily_check_month():
    month_param = request.args.get("month")
    if month_param:
        try:
            year, month = (int(part) for part in month_param.split("-", 1))
        except ValueError:
            year, month = date.today().year, date.today().month
    else:
        today = date.today()
        year, month = today.year, today.month

    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    prev_month_end = start - timedelta(days=1)
    next_month_start = end + timedelta(days=1)

    environments = _all_environments()
    days, status_by_env = compute_environment_statuses(environments, start, end)

    return render_template(
        "daily_check_overview.html",
        environments=environments,
        days=days,
        status_by_env=status_by_env,
        period_label=f"{MONTH_NAMES_FR[month - 1]} {year}",
        prev_url=url_for("main.daily_check_month", month=f"{prev_month_end.year:04d}-{prev_month_end.month:02d}"),
        next_url=url_for("main.daily_check_month", month=f"{next_month_start.year:04d}-{next_month_start.month:02d}"),
        day_labels=None,
        today=date.today(),
        status_labels=STATUS_LABELS,
    )


# --- Supervision -----------------------------------------------------------


@bp.route("/supervision")
def supervision_list():
    links = SupervisionLink.query.order_by(SupervisionLink.name).all()
    return render_template("supervision_list.html", links=links)


@bp.route("/supervision/new", methods=["GET", "POST"])
def supervision_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()

        if not name or not url:
            flash("Merci de renseigner un nom et une URL.", "error")
            return render_template("supervision_form.html", link=None, form_data=request.form)

        db.session.add(SupervisionLink(name=name, url=normalize_url(url)))
        db.session.commit()
        flash("Outil de supervision ajouté.", "success")
        return redirect(url_for("main.supervision_list"))

    return render_template("supervision_form.html", link=None, form_data={})


@bp.route("/supervision/<int:link_id>/edit", methods=["GET", "POST"])
def supervision_edit(link_id):
    link = SupervisionLink.query.get_or_404(link_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()

        if not name or not url:
            flash("Merci de renseigner un nom et une URL.", "error")
            return redirect(url_for("main.supervision_edit", link_id=link.id))

        link.name = name
        link.url = normalize_url(url)
        db.session.commit()
        flash("Outil de supervision mis à jour.", "success")
        return redirect(url_for("main.supervision_list"))

    return render_template("supervision_form.html", link=link, form_data=None)


@bp.route("/supervision/<int:link_id>/delete", methods=["POST"])
def supervision_delete(link_id):
    link = SupervisionLink.query.get_or_404(link_id)
    db.session.delete(link)
    db.session.commit()
    flash("Outil de supervision supprimé.", "success")
    return redirect(url_for("main.supervision_list"))


# --- Ressources utilisées (par environnement) -------------------------------


@bp.route("/environments/<int:environment_id>/ressources", methods=["POST"])
def resource_usage_update(environment_id):
    environment = Environment.query.get_or_404(environment_id)

    storage_used_gb = parse_float(request.form.get("storage_used_gb"))
    cpu_min_15min = parse_float(request.form.get("cpu_min_15min"))
    cpu_max_15min = parse_float(request.form.get("cpu_max_15min"))
    cpu_avg = parse_float(request.form.get("cpu_avg"))
    ram_min_15min = parse_float(request.form.get("ram_min_15min"))
    ram_max_15min = parse_float(request.form.get("ram_max_15min"))
    ram_avg = parse_float(request.form.get("ram_avg"))

    if not environment.resource_usage:
        environment.resource_usage = ResourceUsage(environment_id=environment.id)
        db.session.add(environment.resource_usage)

    usage = environment.resource_usage
    usage.storage_used_gb = storage_used_gb
    usage.cpu_min_15min = cpu_min_15min
    usage.cpu_max_15min = cpu_max_15min
    usage.cpu_avg = cpu_avg
    usage.ram_min_15min = ram_min_15min
    usage.ram_max_15min = ram_max_15min
    usage.ram_avg = ram_avg
    usage.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Utilisation des ressources mise à jour.", "success")
    return redirect(url_for("main.environment_edit", environment_id=environment.id))


# --- Incidents (par plateforme) ---------------------------------------------


@bp.route("/platforms/<int:platform_id>/incidents/new", methods=["GET", "POST"])
def incident_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        incident_date = parse_date(request.form.get("date"))
        duration_minutes = parse_hours_minutes(request.form.get("duration_hours"), request.form.get("duration_minutes"))
        downtime_minutes = parse_hours_minutes(request.form.get("downtime_hours"), request.form.get("downtime_minutes"))
        reference = request.form.get("reference", "").strip()
        notes = request.form.get("notes", "").strip()

        if not incident_date:
            flash("Merci de renseigner une date valide.", "error")
            return render_template("incident_form.html", platform=platform, incident=None, form_data=request.form)
        if downtime_minutes > duration_minutes:
            flash("Le temps d'interruption de service ne peut pas dépasser la durée de l'incident.", "error")
            return render_template("incident_form.html", platform=platform, incident=None, form_data=request.form)

        platform.incidents.append(
            Incident(
                date=incident_date,
                duration_minutes=duration_minutes,
                downtime_minutes=downtime_minutes,
                reference=reference or None,
                notes=notes or None,
            )
        )
        db.session.commit()
        flash("Incident enregistré.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("incident_form.html", platform=platform, incident=None, form_data={})


@bp.route("/incidents/<int:incident_id>/edit", methods=["GET", "POST"])
def incident_edit(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    platform = incident.platform

    if request.method == "POST":
        incident_date = parse_date(request.form.get("date"))
        duration_minutes = parse_hours_minutes(request.form.get("duration_hours"), request.form.get("duration_minutes"))
        downtime_minutes = parse_hours_minutes(request.form.get("downtime_hours"), request.form.get("downtime_minutes"))
        reference = request.form.get("reference", "").strip()
        notes = request.form.get("notes", "").strip()

        if not incident_date:
            flash("Merci de renseigner une date valide.", "error")
            return redirect(url_for("main.incident_edit", incident_id=incident.id))
        if downtime_minutes > duration_minutes:
            flash("Le temps d'interruption de service ne peut pas dépasser la durée de l'incident.", "error")
            return redirect(url_for("main.incident_edit", incident_id=incident.id))

        incident.date = incident_date
        incident.duration_minutes = duration_minutes
        incident.downtime_minutes = downtime_minutes
        incident.reference = reference or None
        incident.notes = notes or None
        db.session.commit()
        flash("Incident mis à jour.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("incident_form.html", platform=platform, incident=incident, form_data=None)


@bp.route("/incidents/<int:incident_id>/delete", methods=["POST"])
def incident_delete(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    platform_id = incident.platform_id
    db.session.delete(incident)
    db.session.commit()
    flash("Incident supprimé.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))


# --- Plans d'action (liés à des incidents) ----------------------------------


@bp.route("/platforms/<int:platform_id>/plans-action/new", methods=["GET", "POST"])
def action_plan_new(platform_id):
    platform = Platform.query.get_or_404(platform_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status")
        due_date = parse_date(request.form.get("due_date"))
        incident_ids = [int(i) for i in request.form.getlist("incident_ids")]

        if not title or status not in TaskStatus.ALL:
            flash("Merci de renseigner un titre et un statut valide.", "error")
            return render_template("action_plan_form.html", platform=platform, plan=None, form_data=request.form)

        plan = ActionPlan(
            platform_id=platform.id,
            title=title,
            description=description or None,
            status=status,
            due_date=due_date,
        )
        if incident_ids:
            plan.incidents = Incident.query.filter(
                Incident.id.in_(incident_ids), Incident.platform_id == platform.id
            ).all()
        db.session.add(plan)
        db.session.commit()
        flash("Plan d'action créé.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("action_plan_form.html", platform=platform, plan=None, form_data={})


@bp.route("/plans-action/<int:plan_id>/edit", methods=["GET", "POST"])
def action_plan_edit(plan_id):
    plan = ActionPlan.query.get_or_404(plan_id)
    platform = plan.platform

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status")
        due_date = parse_date(request.form.get("due_date"))
        incident_ids = [int(i) for i in request.form.getlist("incident_ids")]

        if not title or status not in TaskStatus.ALL:
            flash("Merci de renseigner un titre et un statut valide.", "error")
            return redirect(url_for("main.action_plan_edit", plan_id=plan.id))

        plan.title = title
        plan.description = description or None
        plan.status = status
        plan.due_date = due_date
        plan.incidents = (
            Incident.query.filter(Incident.id.in_(incident_ids), Incident.platform_id == platform.id).all()
            if incident_ids
            else []
        )
        db.session.commit()
        flash("Plan d'action mis à jour.", "success")
        return redirect(url_for("main.platform_detail", platform_id=platform.id))

    return render_template("action_plan_form.html", platform=platform, plan=plan, form_data=None)


@bp.route("/plans-action/<int:plan_id>/delete", methods=["POST"])
def action_plan_delete(plan_id):
    plan = ActionPlan.query.get_or_404(plan_id)
    platform_id = plan.platform_id
    db.session.delete(plan)
    db.session.commit()
    flash("Plan d'action supprimé.", "success")
    return redirect(url_for("main.platform_detail", platform_id=platform_id))
