import pytest

from stockflow import create_app
from stockflow.extensions import db


@pytest.fixture
def app():
    application = create_app({
        "TESTING": True,
        "APP_ENV": "test",
        "SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "SESSION_COOKIE_SECURE": False,
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
