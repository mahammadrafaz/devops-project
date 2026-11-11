import hashlib
import re
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import inspect

from stockflow import create_app
from stockflow.extensions import db
from stockflow.models import Business, Invitation, User, utcnow


def test_alembic_upgrade_creates_phase_two_and_three_tables(tmp_path):
    database_path = tmp_path / "migration-test.db"
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
    })

    result = app.test_cli_runner().invoke(args=["db", "upgrade"])

    assert result.exit_code == 0, result.output
    with app.app_context():
        assert {"business", "user", "invitation", "category", "product", "stock_movement"}.issubset(
            set(inspect(db.engine).get_table_names())
        )


def register(client, email="owner@example.com", password="strong-password"):
    return client.post("/register", data={
        "business_name": "Acme Supply", "owner_name": "Alex Owner", "email": email,
        "password": password, "confirm_password": password,
    }, follow_redirects=True)


def login(client, email, password="strong-password"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def make_user(app, email, role="owner", business_name="Tenant"):
    with app.app_context():
        business = Business(name=business_name)
        user = User(name=email.split("@")[0], email=email, role=role, business=business)
        user.set_password("strong-password")
        db.session.add_all([business, user])
        db.session.commit()
        return user.id


def test_business_and_owner_registration_are_atomic(client, app):
    response = register(client)
    assert response.status_code == 200
    assert b"Welcome, Alex" in response.data
    with app.app_context():
        assert Business.query.count() == 1
        owner = User.query.one()
        assert owner.role == "owner"
        assert owner.business.name == "Acme Supply"
        assert owner.business_id is not None


def test_duplicate_email_rejected_without_creating_business(client, app):
    register(client)
    client.post("/logout")
    response = register(client, email="OWNER@example.com")
    assert b"already exists" in response.data
    with app.app_context():
        assert Business.query.count() == 1
        assert User.query.count() == 1


def test_password_is_hashed_and_verifiable(client, app):
    register(client)
    with app.app_context():
        user = User.query.one()
        assert user.password_hash != "strong-password"
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password("strong-password")
        assert not user.check_password("wrong-password")


def test_login_logout_and_protected_routes(client):
    register(client)
    client.post("/logout")
    protected = client.get("/dashboard")
    assert protected.status_code == 302
    assert urlparse(protected.location).path == "/login"
    assert login(client, "owner@example.com").status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_login_rejects_invalid_password(client):
    register(client)
    client.post("/logout")
    response = login(client, "owner@example.com", password="incorrect")
    assert b"Email or password is incorrect" in response.data


def test_registration_and_login_forms_require_csrf(app):
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    response = client.post("/register", data={"email": "nobody@example.com"})
    assert response.status_code == 400
    assert b"form expired" in response.data


def test_owner_creates_hashed_business_invitation_and_employee_accepts(client, app):
    register(client)
    response = client.post("/manage/invitations", data={"email": "staff@example.com", "role": "staff"})
    assert response.status_code == 200
    match = re.search(rb'value="(http[^\"]+/invite/([^\"]+))"', response.data)
    assert match
    link, token = match.group(1).decode(), match.group(2).decode()
    with app.app_context():
        invite = Invitation.query.one()
        assert invite.business_id == User.query.filter_by(email="owner@example.com").one().business_id
        assert invite.token_hash != token
        assert len(invite.token_hash) == 64
        assert invite.role == "staff"
    accepted = client.post(f"/invite/{token}", data={"name": "Sam Staff", "password": "staff-password", "confirm_password": "staff-password"}, follow_redirects=True)
    assert accepted.status_code == 200
    assert b"Welcome, Sam" in accepted.data
    with app.app_context():
        employee = User.query.filter_by(email="staff@example.com").one()
        assert employee.role == "staff"
        assert employee.business_id == Invitation.query.one().business_id
        assert Invitation.query.one().used_at is not None
    assert client.get(f"/invite/{token}").status_code == 410


def test_expired_invitation_rejected(client, app):
    register(client)
    client.post("/manage/invitations", data={"email": "late@example.com", "role": "manager"})
    with app.app_context():
        invite = Invitation.query.one()
        invite.expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    # The raw token is only returned at creation time, so use a deterministic token in a direct fixture row.
    token = "expired-token"
    with app.app_context():
        invite = Invitation.query.one()
        invite.token_hash = hashlib.sha256(token.encode()).hexdigest()
        db.session.commit()
    assert client.get(f"/invite/{token}").status_code == 410


def test_manager_invitation_assigns_manager_role(client, app):
    register(client)
    client.post("/manage/invitations", data={"email": "manager@acme.test", "role": "manager"})
    with app.app_context():
        invite = Invitation.query.one()
        token = "manager-invite"
        invite.token_hash = hashlib.sha256(token.encode()).hexdigest()
        db.session.commit()
    response = client.post(f"/invite/{token}", data={"name": "Mina Manager", "password": "manager-password", "confirm_password": "manager-password"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email="manager@acme.test").one().role == "manager"


def test_role_permissions_and_cross_business_isolation(client, app):
    register(client)
    with app.app_context():
        owner_business_id = User.query.filter_by(email="owner@example.com").one().business_id
    client.post("/logout")
    staff_id = make_user(app, "staff@other.example", role="staff", business_name="Other Inc")
    manager_id = make_user(app, "manager@other.example", role="manager", business_name="Other Inc")

    login(client, "staff@other.example")
    assert client.get("/manage").status_code == 403
    assert client.post("/manage/invitations", data={"email": "x@example.com", "role": "staff"}).status_code == 403
    client.post("/logout")

    login(client, "manager@other.example")
    team_page = client.get("/manage")
    assert team_page.status_code == 200
    assert b"manager@other.example" in team_page.data
    assert b"owner@example.com" not in team_page.data
    assert client.post("/manage/invitations", data={"email": "x@example.com", "role": "staff"}).status_code == 403

    with app.app_context():
        assert db.session.get(User, staff_id).business_id != owner_business_id
        assert db.session.get(User, manager_id).business_id != owner_business_id


def test_invitation_data_is_business_scoped(client, app):
    register(client)
    client.post("/manage/invitations", data={"email": "one@acme.test", "role": "staff"})
    client.post("/logout")
    make_user(app, "another-owner@example.com", business_name="Different Business")
    login(client, "another-owner@example.com")
    response = client.get("/manage")
    assert b"one@acme.test" not in response.data
    with app.app_context():
        assert Invitation.query.count() == 1
        assert Invitation.query.one().business_id != User.query.filter_by(email="another-owner@example.com").one().business_id


def test_owner_can_update_only_members_of_their_business(client, app):
    register(client)
    with app.app_context():
        owner = User.query.filter_by(email="owner@example.com").one()
        employee = User(name="Team Member", email="team@acme.test", role="staff", business_id=owner.business_id)
        employee.set_password("team-password")
        db.session.add(employee)
        db.session.commit()
        employee_id = employee.id
    response = client.post(f"/manage/users/{employee_id}/role", data={"role": "manager"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, employee_id).role == "manager"
    client.post("/logout")
    make_user(app, "foreign-owner@example.test", role="owner")
    login(client, "foreign-owner@example.test")
    assert client.post(f"/manage/users/{employee_id}/role", data={"role": "staff"}).status_code == 404


def test_owner_can_revoke_only_their_pending_invitation(client, app):
    register(client)
    client.post("/manage/invitations", data={"email": "pending@acme.test", "role": "staff"})
    with app.app_context():
        invitation_id = Invitation.query.one().id
    assert client.post(f"/manage/invitations/{invitation_id}/revoke").status_code == 302
    with app.app_context():
        assert Invitation.query.count() == 0
