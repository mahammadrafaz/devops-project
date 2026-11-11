"""Registration, session authentication, and invitation routes."""

from datetime import datetime, time, timedelta, timezone
import hashlib
import secrets

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Business, Category, Invitation, Product, StockMovement, User, utcnow
from .tenancy import current_business_id

auth = Blueprint("auth", __name__)


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_valid(password):
    return len(password) >= 8


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    if request.method == "POST":
        name = request.form.get("business_name", "").strip()
        owner = request.form.get("owner_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not all((name, owner, email, password, confirm)):
            flash("Please complete every field.", "error")
        elif "@" not in email or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif not _password_valid(password):
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            business = Business(name=name)
            user = User(name=owner, email=email, role="owner", business=business)
            user.set_password(password)
            try:
                db.session.add(business)
                db.session.add(user)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("An account with that email already exists.", "error")
            else:
                flash("Your workspace has been created successfully. Please sign in.", "success")
                return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=False)
            return redirect(url_for("auth.dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth/login.html")


@auth.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth.get("/dashboard")
@login_required
def dashboard():
    business_id = current_business_id()
    # The dashboard accepts only the two supported rolling windows. Invalid input
    # falls back to 7 days, keeping both validation and query bounds predictable.
    period = request.args.get("period", "7")
    if period not in {"7", "30"}:
        period = "7"
    days = int(period)
    today = utcnow().date()
    start_date = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)

    stats = db.session.query(
        func.count(Product.id),
        func.coalesce(func.sum(Product.quantity), 0),
        func.coalesce(func.sum(Product.purchase_price * Product.quantity), 0),
        func.coalesce(func.sum(case((Product.quantity <= Product.low_stock_threshold, 1), else_=0)), 0),
    ).filter(Product.business_id == business_id).one()
    low_stock = Product.query.filter(
        Product.business_id == business_id, Product.quantity <= Product.low_stock_threshold
    ).order_by(
        Product.quantity.asc(), Product.name.asc()
    ).limit(8).all()

    movement_rows = db.session.query(
        func.date(StockMovement.created_at).label("day"), StockMovement.operation_type,
        func.sum(StockMovement.quantity),
    ).filter(
        StockMovement.business_id == business_id,
        StockMovement.created_at >= start_at,
        StockMovement.created_at < end_at,
    ).group_by(func.date(StockMovement.created_at), StockMovement.operation_type).all()
    activity = { (start_date + timedelta(days=offset)).isoformat(): {"in": 0, "out": 0}
        for offset in range(days) }
    for day, operation, quantity in movement_rows:
        if day in activity:
            activity[day][operation] = int(quantity or 0)

    category_rows = db.session.query(
        Category.name, func.coalesce(func.sum(Product.quantity), 0),
    ).outerjoin(Product, (Product.category_id == Category.id) & (Product.business_id == business_id)).filter(
        Category.business_id == business_id
    ).group_by(Category.id, Category.name).order_by(Category.name).all()
    uncategorized = db.session.query(func.coalesce(func.sum(Product.quantity), 0)).filter(
        Product.business_id == business_id, Product.category_id.is_(None)
    ).scalar()
    category_labels = [row[0] for row in category_rows]
    category_values = [int(row[1]) for row in category_rows]
    if uncategorized:
        category_labels.append("Uncategorized")
        category_values.append(int(uncategorized))

    recent_movements = StockMovement.query.options(
        joinedload(StockMovement.product), joinedload(StockMovement.user)
    ).filter_by(business_id=business_id).order_by(
        StockMovement.created_at.desc(), StockMovement.id.desc()
    ).limit(10).all()
    return render_template("auth/dashboard.html", period=period, days=days,
        stats={"products": stats[0], "units": stats[1], "value": stats[2], "low_stock": stats[3]},
        low_stock=low_stock, activity_labels=list(activity),
        stock_in=[values["in"] for values in activity.values()],
        stock_out=[values["out"] for values in activity.values()],
        category_labels=category_labels, category_values=category_values,
        recent_movements=recent_movements)


@auth.get("/manage")
@login_required
def manage():
    if current_user.role not in {"owner", "manager"}:
        abort(403)
    users = User.query.filter_by(business_id=current_user.business_id).order_by(User.created_at).all()
    invitations = Invitation.query.filter_by(business_id=current_user.business_id).order_by(Invitation.created_at.desc()).all()
    return render_template("auth/manage.html", users=users, invitations=invitations)


@auth.post("/manage/invitations")
@login_required
def create_invitation():
    if current_user.role != "owner":
        abort(403)
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "")
    if "@" not in email or len(email) > 254 or role not in {"manager", "staff"}:
        flash("Enter a valid email and invitation role.", "error")
        return redirect(url_for("auth.manage"))
    if User.query.filter_by(email=email).first():
        flash("That email already has an account.", "error")
        return redirect(url_for("auth.manage"))
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=current_app.config["INVITATION_EXPIRY_HOURS"])
    invitation = Invitation(
        business_id=current_user.business_id, email=email, role=role,
        token_hash=token_digest(token), expires_at=expires, created_by_id=current_user.id,
    )
    db.session.add(invitation)
    db.session.commit()
    link = url_for("auth.accept_invitation", token=token, _external=True)
    return render_template("auth/manage.html", users=User.query.filter_by(business_id=current_user.business_id).order_by(User.created_at).all(), invitations=Invitation.query.filter_by(business_id=current_user.business_id).order_by(Invitation.created_at.desc()).all(), invitation_link=link)


@auth.post("/manage/users/<int:user_id>/role")
@login_required
def update_user_role(user_id):
    if current_user.role != "owner":
        abort(403)
    member = User.query.filter_by(id=user_id, business_id=current_user.business_id).first_or_404()
    role = request.form.get("role", "")
    if member.role == "owner" or role not in {"manager", "staff"}:
        abort(400)
    member.role = role
    db.session.commit()
    flash("Team member role updated.", "success")
    return redirect(url_for("auth.manage"))


@auth.post("/manage/invitations/<int:invitation_id>/revoke")
@login_required
def revoke_invitation(invitation_id):
    if current_user.role != "owner":
        abort(403)
    invite = Invitation.query.filter_by(id=invitation_id, business_id=current_user.business_id).first_or_404()
    if invite.used_at is not None:
        abort(409)
    db.session.delete(invite)
    db.session.commit()
    flash("Invitation revoked.", "success")
    return redirect(url_for("auth.manage"))


@auth.route("/invite/<token>", methods=["GET", "POST"])
def accept_invitation(token):
    invite = Invitation.query.filter_by(token_hash=token_digest(token)).first_or_404()
    now = utcnow()
    expiry = invite.expires_at.replace(tzinfo=now.tzinfo) if invite.expires_at.tzinfo is None else invite.expires_at
    if invite.used_at is not None or expiry <= now:
        abort(410, description="This invitation has expired or has already been used.")
    if current_user.is_authenticated:
        logout_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not name or not _password_valid(password) or password != confirm:
            flash("Enter your name and a matching password of at least 8 characters.", "error")
        elif User.query.filter_by(email=invite.email).first():
            abort(409, description="An account already exists for this email.")
        else:
            user = User(business_id=invite.business_id, name=name, email=invite.email, role=invite.role)
            user.set_password(password)
            invite.used_at = now
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                abort(409, description="This invitation has already been accepted.")
            login_user(user)
            return redirect(url_for("auth.dashboard"))
    return render_template("auth/accept_invitation.html", invitation=invite)
