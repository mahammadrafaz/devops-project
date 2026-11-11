"""StockFlow application package."""

import os
import secrets

from flask import Flask, redirect, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url

# Load the project-local environment for development. Existing process
# environment variables take precedence, and dotenv never overrides them.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from .extensions import csrf, db, login_manager, migrate

def _database_uri():
    """Return a SQLAlchemy URI for PostgreSQL or the local SQLite fallback."""
    database_url = _configured_secret("DATABASE_URL")
    if not database_url:
        return "sqlite:///stockflow.db"

    # Heroku-style URLs use postgres://, and SQLAlchemy otherwise defaults to
    # psycopg2 for postgresql://. The project installs psycopg 3.
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")

    try:
        url = make_url(database_url)
    except SQLAlchemyError:
        raise RuntimeError("DATABASE_URL is invalid.") from None
    if url.get_backend_name() == "postgresql":
        if not url.drivername.endswith("+psycopg"):
            url = url.set(drivername="postgresql+psycopg")
        url = url.update_query_dict({"sslmode": "require"})
    return url.render_as_string(hide_password=False)


def _configured_secret(name):
    """Read a secret from a protected file, falling back to its env variable."""
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as secret_file:
                value = secret_file.read().rstrip("\r\n")
        except OSError:
            raise RuntimeError(f"{name}_FILE could not be read.") from None
        if not value:
            raise RuntimeError(f"{name}_FILE is empty.")
        return value
    return os.environ.get(name)


def create_app(config=None):
    """Create and configure a StockFlow Flask application instance."""
    app = Flask(__name__)
    app.config.from_mapping(
        APP_ENV=os.environ.get("APP_ENV", "development"),
        SECRET_KEY=_configured_secret("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ECHO=False,
        SQLALCHEMY_ENGINE_OPTIONS={"hide_parameters": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
        INVITATION_EXPIRY_HOURS=72,
    )
    if config:
        app.config.update(config)

    app_environment = str(app.config.get("APP_ENV", "development")).strip().lower()
    app.config["APP_ENV"] = app_environment
    if app_environment == "production":
        if not app.config.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
        try:
            database_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        except SQLAlchemyError:
            raise RuntimeError("A valid PostgreSQL DATABASE_URL is required in production.") from None
        if database_url.get_backend_name() != "postgresql":
            raise RuntimeError("DATABASE_URL must configure PostgreSQL when APP_ENV=production.")
        if database_url.query.get("sslmode") != "require":
            raise RuntimeError("PostgreSQL SSL must be required when APP_ENV=production.")
    elif not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "error"

    from . import models  # noqa: F401
    from .auth import auth
    from .inventory import inventory
    app.register_blueprint(auth)
    app.register_blueprint(inventory)

    @app.context_processor
    def inject_template_helpers():
        from .models import utcnow
        def invitation_expired(invitation):
            expiry = invitation.expires_at
            now = utcnow()
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=now.tzinfo)
            return expiry <= now
        return {"now": utcnow(), "invitation_expired": invitation_expired}

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(models.User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.route("/")
    def home():
        if current_user.is_authenticated:
            return redirect(url_for("auth.dashboard"))
        return "Hello from my DevOps project! - Version 2"

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return "The form expired. Please go back, refresh, and try again.", 400

    @app.route("/health")
    def health():
        return {"status": "OK"}

    @app.route("/ready")
    def readiness():
        try:
            with db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            app.logger.warning("Readiness check failed: database unavailable.")
            return {"status": "not_ready", "database": "unavailable"}, 503
        return {"status": "ready"}, 200

    return app
