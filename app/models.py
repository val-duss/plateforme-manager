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
