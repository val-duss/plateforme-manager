import os

from flask import Flask

from .models import EnvType, InfraKind, OperationType, db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

    db_path = os.environ.get("DATABASE_PATH", os.path.join("instance", "app.db"))
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from . import routes

    app.register_blueprint(routes.bp)

    with app.app_context():
        db.create_all()

    @app.context_processor
    def inject_reference_data():
        return {"EnvType": EnvType, "InfraKind": InfraKind, "OperationType": OperationType}

    return app
