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
        if self.infra_kind == InfraKind.VM:
            return {
                "cpu": sum(v.cpu_cores for v in self.vm_sizings),
                "ram": sum(v.ram_gb for v in self.vm_sizings),
                "storage": sum(v.storage_gb for v in self.vm_sizings),
                "detail": f"{len(self.vm_sizings)} VM(s)",
            }
        if self.infra_kind == InfraKind.K8S and self.k8s_sizing:
            k = self.k8s_sizing
            return {
                "cpu": k.node_count * k.cpu_per_node,
                "ram": k.node_count * k.ram_per_node_gb,
                "storage": k.storage_total_gb,
                "detail": f"{k.node_count} nœud(s)",
            }
        if self.infra_kind == InfraKind.AWS:
            return None
        return None


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
