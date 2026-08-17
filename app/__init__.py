import os
import secrets

from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .models import (
    AppSettings,
    BillingPeriodicity,
    CheckStatus,
    EnvType,
    InfraKind,
    OperationType,
    PresaleStatus,
    TaskStatus,
    TaskType,
    db,
)

DEFAULT_PIN = "0000"


def _upgrade_schema(engine):
    """Ajoute les colonnes manquantes sur une base SQLite existante (pas de framework de migration)."""
    additions = {
        "file_path": "VARCHAR(500)",
        "sizing_before": "TEXT",
        "sizing_after": "TEXT",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(operations)"))}
        for column, coltype in additions.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE operations ADD COLUMN {column} {coltype}"))
        conn.commit()


def _load_or_create_secret_key(path):
    """Lit la clé persistée, ou en crée une de façon atomique (plusieurs workers
    gunicorn peuvent appeler create_app() en parallèle au démarrage)."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key

    candidate = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(candidate)
        return candidate
    except FileExistsError:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()


def _ensure_default_pin():
    """Crée la ligne de réglages par défaut si absente (idempotent face aux
    workers gunicorn qui appellent create_app() en parallèle)."""
    if AppSettings.query.get(1) is not None:
        return
    try:
        db.session.add(AppSettings(id=1, pin_hash=generate_password_hash(DEFAULT_PIN)))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def create_app():
    app = Flask(__name__)

    db_path = os.environ.get("DATABASE_PATH", os.path.join("instance", "app.db"))
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    secret_key_path = os.environ.get("SECRET_KEY_PATH", os.path.join(db_dir or ".", "secret_key"))
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or _load_or_create_secret_key(secret_key_path)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from . import routes

    app.register_blueprint(routes.bp)

    with app.app_context():
        db.create_all()
        _upgrade_schema(db.engine)
        _ensure_default_pin()

    @app.context_processor
    def inject_reference_data():
        return {
            "EnvType": EnvType,
            "InfraKind": InfraKind,
            "OperationType": OperationType,
            "PresaleStatus": PresaleStatus,
            "TaskType": TaskType,
            "TaskStatus": TaskStatus,
            "BillingPeriodicity": BillingPeriodicity,
            "CheckStatus": CheckStatus,
        }

    return app
