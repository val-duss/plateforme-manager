import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class EnvType:
    INT = "INT"
    UAT = "UAT"
    PRODUCTION = "PRODUCTION"
    ALL = [INT, UAT, PRODUCTION]
    LABELS = {
        INT: "Intégration (INT)",
        UAT: "Recette (UAT)",
        PRODUCTION: "Production",
    }


class InfraKind:
    VM = "VM"
    K8S = "K8S"
    AWS = "AWS"
    ALL = [VM, K8S, AWS]
    LABELS = {
        VM: "Machines virtuelles",
        K8S: "Kubernetes",
        AWS: "AWS",
    }


class OperationType:
    INSTALLATION = "INSTALLATION"
    MAINTENANCE = "MAINTENANCE"
    RESIZING = "RESIZING"
    LOG_RETRIEVAL = "LOG_RETRIEVAL"
    INCIDENT = "INCIDENT"
    ALL = [INSTALLATION, MAINTENANCE, RESIZING, LOG_RETRIEVAL, INCIDENT]
    LABELS = {
        INSTALLATION: "Installation",
        MAINTENANCE: "Maintenance",
        RESIZING: "Changement de sizing",
        LOG_RETRIEVAL: "Récupération de logs",
        INCIDENT: "Incident",
    }


class Platform(db.Model):
    __tablename__ = "platforms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    client_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    environments = db.relationship(
        "Environment",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="Environment.env_type",
    )
    operations = db.relationship(
        "Operation",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="Operation.performed_at.desc()",
    )
    procedures = db.relationship(
        "Procedure",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="Procedure.title",
    )
    billing_entries = db.relationship(
        "BillingEntry",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="BillingEntry.created_at.desc()",
    )
    tasks = db.relationship(
        "Task",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="Task.created_at.desc()",
    )
    incidents = db.relationship(
        "Incident",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="Incident.date.desc()",
    )
    action_plans = db.relationship(
        "ActionPlan",
        backref="platform",
        cascade="all, delete-orphan",
        order_by="ActionPlan.created_at.desc()",
    )


class Environment(db.Model):
    __tablename__ = "environments"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    env_type = db.Column(db.String(20), nullable=False)
    infra_kind = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    vm_sizings = db.relationship(
        "VMSizing", backref="environment", cascade="all, delete-orphan"
    )
    k8s_sizing = db.relationship(
        "K8sSizing", backref="environment", uselist=False, cascade="all, delete-orphan"
    )
    aws_sizing = db.relationship(
        "AwsSizing", backref="environment", uselist=False, cascade="all, delete-orphan"
    )
    operations = db.relationship(
        "Operation",
        backref="environment",
        cascade="all, delete-orphan",
        order_by="Operation.performed_at.desc()",
    )
    daily_checks = db.relationship(
        "DailyCheck",
        backref="environment",
        cascade="all, delete-orphan",
        order_by="DailyCheck.check_date.desc()",
    )
    alerts = db.relationship(
        "EnvironmentAlert",
        backref="environment",
        cascade="all, delete-orphan",
        order_by="EnvironmentAlert.opened_at.desc()",
    )
    resource_usage = db.relationship(
        "ResourceUsage", backref="environment", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def open_alerts(self):
        return [a for a in self.alerts if a.is_open]

    @property
    def open_alert_count(self):
        return len(self.open_alerts)

    @property
    def sizing_summary(self):
        """Retourne un résumé CPU/RAM/stockage selon le type d'infrastructure."""
        from .sizing import snapshot_environment

        snap = snapshot_environment(self)
        if snap["infra_kind"] == InfraKind.AWS:
            return None
        if snap["infra_kind"] == InfraKind.VM:
            detail = f"{len(snap['items'])} VM(s)"
        elif snap["items"]:
            detail = f"{snap['items'][0]['node_count']} nœud(s)"
        else:
            detail = "0 nœud(s)"
        return {"cpu": snap["cpu"], "ram": snap["ram"], "storage": snap["storage"], "detail": detail}


class VMSizing(db.Model):
    __tablename__ = "vm_sizings"

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(
        db.Integer, db.ForeignKey("environments.id"), nullable=False
    )
    name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(100), nullable=True)
    cpu_cores = db.Column(db.Integer, nullable=False, default=0)
    ram_gb = db.Column(db.Float, nullable=False, default=0)
    storage_gb = db.Column(db.Float, nullable=False, default=0)


class K8sSizing(db.Model):
    __tablename__ = "k8s_sizings"

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(
        db.Integer, db.ForeignKey("environments.id"), unique=True, nullable=False
    )
    node_count = db.Column(db.Integer, nullable=False, default=0)
    cpu_per_node = db.Column(db.Float, nullable=False, default=0)
    ram_per_node_gb = db.Column(db.Float, nullable=False, default=0)
    storage_total_gb = db.Column(db.Float, nullable=False, default=0)


class AwsSizing(db.Model):
    """Squelette minimal pour les environnements AWS natifs, à enrichir plus tard."""

    __tablename__ = "aws_sizings"

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(
        db.Integer, db.ForeignKey("environments.id"), unique=True, nullable=False
    )
    region = db.Column(db.String(100), nullable=True)
    account_id = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)


class Operation(db.Model):
    __tablename__ = "operations"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    environment_id = db.Column(
        db.Integer, db.ForeignKey("environments.id"), nullable=True
    )
    operation_type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    performed_by = db.Column(db.String(200), nullable=True)
    performed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Chemin vers un fichier accessible depuis l'explorateur de fichiers (ex. partage Windows).
    file_path = db.Column(db.String(500), nullable=True)

    # Snapshots JSON du sizing avant/après, renseignés uniquement pour les opérations
    # de type RESIZING générées automatiquement lors d'un changement de sizing.
    sizing_before = db.Column(db.Text, nullable=True)
    sizing_after = db.Column(db.Text, nullable=True)

    @property
    def sizing_diff(self):
        if not self.sizing_before or not self.sizing_after:
            return []
        from .sizing import diff_snapshots

        return diff_snapshots(json.loads(self.sizing_before), json.loads(self.sizing_after))

    @property
    def file_link_url(self):
        """Convertit le chemin renseigné en URI file:// (best-effort, pour un clic depuis le navigateur)."""
        if not self.file_path:
            return None
        normalized = self.file_path.strip().replace("\\", "/")
        if normalized.startswith("//"):
            return "file:" + normalized
        return "file:///" + normalized.lstrip("/")


class Procedure(db.Model):
    __tablename__ = "procedures"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    steps = db.relationship(
        "ProcedureStep",
        backref="procedure",
        cascade="all, delete-orphan",
        order_by="ProcedureStep.position",
    )


class ProcedureStep(db.Model):
    __tablename__ = "procedure_steps"

    id = db.Column(db.Integer, primary_key=True)
    procedure_id = db.Column(db.Integer, db.ForeignKey("procedures.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text, nullable=True)

    tests = db.relationship(
        "ProcedureStepTest",
        backref="step",
        cascade="all, delete-orphan",
        order_by="ProcedureStepTest.id",
    )


class ProcedureStepTest(db.Model):
    """Test optionnel de validation, rattaché à une étape de procédure."""

    __tablename__ = "procedure_step_tests"

    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey("procedure_steps.id"), nullable=False)
    description = db.Column(db.Text, nullable=False)


class AppSettings(db.Model):
    """Réglages applicatifs, ligne unique (id=1) — contient notamment le PIN d'accès."""

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    pin_hash = db.Column(db.String(255), nullable=False)


class BillingPeriodicity:
    UNIQUE = "UNIQUE"
    MENSUELLE = "MENSUELLE"
    TRIMESTRIELLE = "TRIMESTRIELLE"
    ANNUELLE = "ANNUELLE"
    ALL = [UNIQUE, MENSUELLE, TRIMESTRIELLE, ANNUELLE]
    LABELS = {
        UNIQUE: "Unique",
        MENSUELLE: "Mensuelle",
        TRIMESTRIELLE: "Trimestrielle",
        ANNUELLE: "Annuelle",
    }


class BillingEntry(db.Model):
    __tablename__ = "billing_entries"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    periodicity = db.Column(db.String(20), nullable=False, default=BillingPeriodicity.UNIQUE)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PresaleStatus:
    EN_COURS = "EN_COURS"
    EN_ATTENTE = "EN_ATTENTE"
    GAGNE = "GAGNE"
    PERDU = "PERDU"
    ALL = [EN_COURS, EN_ATTENTE, GAGNE, PERDU]
    LABELS = {
        EN_COURS: "En cours",
        EN_ATTENTE: "En attente",
        GAGNE: "Gagné",
        PERDU: "Perdu",
    }


class Presale(db.Model):
    """Opportunité avant-vente, indépendante d'une plateforme existante."""

    __tablename__ = "presales"

    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(200), nullable=False)
    project_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=PresaleStatus.EN_COURS)
    estimated_amount = db.Column(db.Float, nullable=True)
    contact = db.Column(db.String(200), nullable=True)
    expected_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaskType:
    INSTALLATION = "INSTALLATION"
    MAINTENANCE = "MAINTENANCE"
    BUILD = "BUILD"
    ATELIER_TECHNIQUE = "ATELIER_TECHNIQUE"
    ALL = [INSTALLATION, MAINTENANCE, BUILD, ATELIER_TECHNIQUE]
    LABELS = {
        INSTALLATION: "Installation",
        MAINTENANCE: "Maintenance",
        BUILD: "Build",
        ATELIER_TECHNIQUE: "Atelier technique",
    }


class TaskStatus:
    A_FAIRE = "A_FAIRE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"
    ALL = [A_FAIRE, EN_COURS, TERMINEE]
    LABELS = {
        A_FAIRE: "À faire",
        EN_COURS: "En cours",
        TERMINEE: "Terminée",
    }


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=True)
    task_type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=TaskStatus.A_FAIRE)
    assigned_to = db.Column(db.String(200), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CheckStatus:
    OK = "OK"
    ALERT = "ALERT"
    ALL = [OK, ALERT]
    LABELS = {
        OK: "RAS",
        ALERT: "Alerte",
    }


class AlertSeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    ALL = [INFO, WARNING, ERROR, CRITICAL]
    LABELS = {
        INFO: "Info",
        WARNING: "Avertissement",
        ERROR: "Erreur",
        CRITICAL: "Critique",
    }
    RANK = {INFO: 0, WARNING: 1, ERROR: 2, CRITICAL: 3}


class DailyCheck(db.Model):
    """Confirmation quotidienne « RAS » pour un environnement donné.

    Une alerte ouverte sur l'environnement prévaut toujours sur cette
    confirmation pour l'affichage du statut du jour (voir app/checks.py).
    """

    __tablename__ = "daily_checks"
    __table_args__ = (db.UniqueConstraint("environment_id", "check_date", name="uq_daily_check_env_date"),)

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(db.Integer, db.ForeignKey("environments.id"), nullable=False)
    check_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=CheckStatus.OK)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text, nullable=True)


class EnvironmentAlert(db.Model):
    """Alerte remontée sur un environnement, ouverte jusqu'à sa clôture."""

    __tablename__ = "environment_alerts"

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(db.Integer, db.ForeignKey("environments.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(20), nullable=False, default=AlertSeverity.WARNING)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by = db.Column(db.String(200), nullable=True)
    resolution_notes = db.Column(db.Text, nullable=True)

    @property
    def is_open(self):
        return self.closed_at is None


class SupervisionLink(db.Model):
    """Lien vers un outil de supervision externe (nom + URL)."""

    __tablename__ = "supervision_links"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ResourceUsage(db.Model):
    """Ressources effectivement utilisées sur un environnement (un instantané, mis à jour à la volée).

    Le provisionné n'est pas dupliqué ici : il est déjà disponible via
    Environment.sizing_summary (VM/K8s/AWS).
    """

    __tablename__ = "resource_usages"

    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(db.Integer, db.ForeignKey("environments.id"), unique=True, nullable=False)
    storage_used_gb = db.Column(db.Float, nullable=True)
    cpu_min_15min = db.Column(db.Float, nullable=True)
    cpu_max_15min = db.Column(db.Float, nullable=True)
    cpu_avg = db.Column(db.Float, nullable=True)
    ram_min_15min = db.Column(db.Float, nullable=True)
    ram_max_15min = db.Column(db.Float, nullable=True)
    ram_avg = db.Column(db.Float, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Incident(db.Model):
    """Incident déclaré sur une plateforme : date, durée totale et temps d'interruption de service."""

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False, default=0)
    downtime_minutes = db.Column(db.Integer, nullable=False, default=0)
    reference = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    action_plans = db.relationship(
        "ActionPlan", secondary="action_plan_incidents", back_populates="incidents"
    )


action_plan_incidents = db.Table(
    "action_plan_incidents",
    db.Column("action_plan_id", db.Integer, db.ForeignKey("action_plans.id"), primary_key=True),
    db.Column("incident_id", db.Integer, db.ForeignKey("incidents.id"), primary_key=True),
)


class ActionPlan(db.Model):
    """Plan d'action lié à un ou plusieurs incidents."""

    __tablename__ = "action_plans"

    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey("platforms.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=TaskStatus.A_FAIRE)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    incidents = db.relationship(
        "Incident",
        secondary=action_plan_incidents,
        back_populates="action_plans",
        order_by="Incident.date.desc()",
    )
