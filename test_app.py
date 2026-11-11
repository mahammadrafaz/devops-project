
import pytest
from sqlalchemy.exc import OperationalError

from app import app as default_app
from stockflow import create_app
from stockflow.extensions import db


def test_application_factory_initializes_extensions():
    app = create_app({"TESTING": True, "APP_ENV": "test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

    assert app.testing
    assert app.extensions["sqlalchemy"] is db
    assert app.extensions["migrate"].db is db


def test_application_factory_uses_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost/stockflow")
    app = create_app()

    assert app.config["SQLALCHEMY_DATABASE_URI"] == (
        "postgresql+psycopg://user:password@localhost/stockflow?sslmode=require"
    )


def test_production_reads_secrets_from_files(tmp_path, monkeypatch):
    database_file = tmp_path / "database_url"
    secret_file = tmp_path / "secret_key"
    database_file.write_text("postgresql://file-user:file-password@localhost/stockflow\n")
    secret_file.write_text("file-based-production-key\n")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL_FILE", str(database_file))
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_file))

    app = create_app()

    assert app.config["SECRET_KEY"] == "file-based-production-key"
    assert app.config["SQLALCHEMY_DATABASE_URI"] == (
        "postgresql+psycopg://file-user:file-password@localhost/stockflow?sslmode=require"
    )


@pytest.mark.parametrize("name", ["DATABASE_URL", "SECRET_KEY"])
def test_production_rejects_unreadable_secret_file(name, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(f"{name}_FILE", str(tmp_path / "missing-secret"))
    other = "SECRET_KEY" if name == "DATABASE_URL" else "DATABASE_URL"
    monkeypatch.delenv(f"{other}_FILE", raising=False)
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(other, "postgresql://test:test@localhost/stockflow" if other == "DATABASE_URL" else "test-key")

    with pytest.raises(RuntimeError, match=f"{name}_FILE could not be read"):
        create_app()


def test_application_factory_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()

    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///stockflow.db"


def test_development_generates_secret_when_unset(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    app = create_app()

    assert isinstance(app.config["SECRET_KEY"], str)
    assert len(app.config["SECRET_KEY"]) >= 32


def test_production_requires_explicit_secret_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/stockflow")

    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        create_app()


def test_production_requires_postgresql_database_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "test-production-secret-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL must configure PostgreSQL"):
        create_app()


def test_production_accepts_explicit_secret_and_ssl_postgresql_url():
    app = create_app({
        "APP_ENV": "production",
        "SECRET_KEY": "test-production-secret-key",
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://test:test@localhost/stockflow?sslmode=require",
    })

    assert app.config["SECRET_KEY"] == "test-production-secret-key"
    assert app.config["APP_ENV"] == "production"


def test_production_rejects_postgresql_without_required_ssl():
    with pytest.raises(RuntimeError, match="PostgreSQL SSL must be required"):
        create_app({
            "APP_ENV": "production",
            "SECRET_KEY": "test-production-secret-key",
            "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://test:test@localhost/stockflow",
        })


def _readiness_test_app():
    return create_app({
        "TESTING": True,
        "APP_ENV": "test",
        "SECRET_KEY": "readiness-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })


def test_readiness_returns_success_when_database_is_available():
    app = _readiness_test_app()
    response = app.test_client().get("/ready")

    assert response.status_code == 200
    assert response.json == {"status": "ready"}


def test_readiness_reports_database_failure_without_leaking_details(monkeypatch, caplog):
    app = _readiness_test_app()
    secret_marker = "DATABASE_CREDENTIAL_SENTINEL"

    def fail_connection():
        raise OperationalError("SELECT 1", {}, RuntimeError(secret_marker))

    with app.app_context():
        monkeypatch.setattr(db.engine, "connect", fail_connection)

    response = app.test_client().get("/ready")

    assert response.status_code == 503
    assert response.json == {"status": "not_ready", "database": "unavailable"}
    assert secret_marker not in response.get_data(as_text=True)
    assert secret_marker not in caplog.text


def test_health_endpoint():
    response = default_app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "OK"}


def test_home_endpoint_remains_compatible():
    response = default_app.test_client().get("/")

    assert response.status_code == 200
    assert b"Hello from my DevOps project!" in response.data
