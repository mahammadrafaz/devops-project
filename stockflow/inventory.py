"""Business-scoped product, category, and stock management."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Category, Product, StockMovement, utcnow
from .tenancy import current_business_id

inventory = Blueprint("inventory", __name__, url_prefix="/inventory")
MANAGERS = {"owner", "manager"}


def _manager_required():
    if current_user.role not in MANAGERS:
        abort(403)


def _product(product_id):
    return Product.query.filter_by(id=product_id, business_id=current_business_id()).first_or_404()


def _category(category_id):
    return Category.query.filter_by(id=category_id, business_id=current_business_id()).first_or_404()


def _parse_product(form):
    name, sku = form.get("name", "").strip(), form.get("sku", "").strip()
    description = form.get("description", "").strip()
    try:
        purchase = Decimal(form.get("purchase_price", ""))
        selling = Decimal(form.get("selling_price", ""))
        quantity = int(form.get("quantity", ""))
        threshold = int(form.get("low_stock_threshold", ""))
        category_id = int(form.get("category_id") or 0)
    except (ValueError, InvalidOperation):
        raise ValueError("Enter valid prices and whole-number stock quantities.")
    if not name or not sku or len(name) > 160 or len(sku) > 80:
        raise ValueError("Product name and SKU are required.")
    if purchase < 0 or selling < 0 or quantity < 0 or threshold < 0:
        raise ValueError("Prices and stock thresholds cannot be negative.")
    if not purchase.is_finite() or not selling.is_finite():
        raise ValueError("Enter valid prices.")
    category = Category.query.filter_by(id=category_id, business_id=current_business_id()).first() if category_id else None
    if category_id and not category:
        raise ValueError("Choose a category from your business.")
    return dict(name=name, sku=sku, description=description, purchase_price=purchase,
                selling_price=selling, quantity=quantity, low_stock_threshold=threshold,
                category=category)


@inventory.get("")
@login_required
def index():
    query = Product.query.filter_by(business_id=current_business_id())
    search = request.args.get("q", "").strip()
    category_id = request.args.get("category", "")
    if search:
        query = query.filter(or_(Product.name.ilike(f"%{search}%"), Product.sku.ilike(f"%{search}%")))
    if category_id.isdigit():
        query = query.filter_by(category_id=int(category_id))
    products = query.order_by(Product.name).all()
    categories = Category.query.filter_by(business_id=current_business_id()).order_by(Category.name).all()
    low_stock = Product.query.filter(Product.business_id == current_business_id(), Product.quantity <= Product.low_stock_threshold).order_by(Product.name).all()
    return render_template("inventory/index.html", products=products, categories=categories,
                           low_stock=low_stock, search=search, category_filter=category_id)


@inventory.route("/products/new", methods=["GET", "POST"])
@login_required
def new_product():
    _manager_required()
    if request.method == "POST":
        try:
            values = _parse_product(request.form)
            product = Product(business_id=current_business_id(), **values)
            db.session.add(product)
            db.session.flush()
            if product.quantity:
                db.session.add(StockMovement(business_id=current_business_id(), product=product,
                    user_id=current_user.id, operation_type="in", quantity=product.quantity,
                    notes="Opening stock"))
            db.session.commit()
            flash("Product added.", "success")
            return redirect(url_for("inventory.index"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "error")
        except IntegrityError:
            db.session.rollback()
            flash("That SKU is already used in your business.", "error")
    categories = Category.query.filter_by(business_id=current_business_id()).order_by(Category.name).all()
    return render_template("inventory/product_form.html", product=None, categories=categories)


@inventory.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    _manager_required()
    product = _product(product_id)
    if request.method == "POST":
        old_quantity = product.quantity
        try:
            values = _parse_product(request.form)
            new_quantity = values.pop("quantity")
            for key, value in values.items():
                setattr(product, key, value)
            difference = new_quantity - old_quantity
            product.quantity = new_quantity
            if difference:
                db.session.add(StockMovement(business_id=current_business_id(), product=product,
                    user_id=current_user.id, operation_type="in" if difference > 0 else "out",
                    quantity=abs(difference), notes="Quantity adjusted during product edit"))
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("inventory.index"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "error")
        except IntegrityError:
            db.session.rollback()
            flash("That SKU is already used in your business.", "error")
    categories = Category.query.filter_by(business_id=current_business_id()).order_by(Category.name).all()
    return render_template("inventory/product_form.html", product=product, categories=categories)


@inventory.post("/products/<int:product_id>/delete")
@login_required
def delete_product(product_id):
    _manager_required()
    db.session.delete(_product(product_id))
    db.session.commit()
    flash("Product deleted.", "success")
    return redirect(url_for("inventory.index"))


@inventory.get("/products/<int:product_id>/history")
@login_required
def history(product_id):
    product = _product(product_id)
    movements = StockMovement.query.filter_by(product_id=product.id, business_id=current_business_id()).order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).all()
    return render_template("inventory/history.html", product=product, movements=movements)


@inventory.post("/products/<int:product_id>/stock")
@login_required
def stock_operation(product_id):
    product = _product(product_id)
    operation = request.form.get("operation_type", "")
    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError:
        quantity = 0
    notes = request.form.get("notes", "").strip()
    if operation not in {"in", "out"} or quantity <= 0:
        flash("Choose stock-in or stock-out and enter a quantity greater than zero.", "error")
        return redirect(url_for("inventory.index"))
    try:
        # Locking the product serializes competing stock changes on databases that support row locks.
        with db.session.begin_nested():
            locked = Product.query.filter_by(id=product.id, business_id=current_business_id()).with_for_update().one()
            if operation == "out" and locked.quantity < quantity:
                raise ValueError("Insufficient stock for this stock-out.")
            locked.quantity += quantity if operation == "in" else -quantity
            movement = StockMovement(business_id=current_business_id(), product=locked,
                user_id=current_user.id, operation_type=operation, quantity=quantity,
                notes=notes[:500])
            db.session.add(movement)
            db.session.flush()
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
    except Exception:
        db.session.rollback()
        raise
    else:
        flash("Stock updated.", "success")
    return redirect(url_for("inventory.index"))


@inventory.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    _manager_required()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name or len(name) > 100:
            flash("Enter a category name up to 100 characters.", "error")
        else:
            db.session.add(Category(business_id=current_business_id(), name=name))
            try:
                db.session.commit()
                flash("Category added.", "success")
                return redirect(url_for("inventory.categories"))
            except IntegrityError:
                db.session.rollback()
                flash("That category already exists in your business.", "error")
    items = Category.query.filter_by(business_id=current_business_id()).order_by(Category.name).all()
    return render_template("inventory/categories.html", categories=items)


@inventory.post("/categories/<int:category_id>/edit")
@login_required
def edit_category(category_id):
    _manager_required()
    category = _category(category_id)
    name = request.form.get("name", "").strip()
    if not name or len(name) > 100:
        flash("Enter a category name up to 100 characters.", "error")
    else:
        category.name = name
        try:
            db.session.commit()
            flash("Category updated.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("That category already exists in your business.", "error")
    return redirect(url_for("inventory.categories"))


@inventory.post("/categories/<int:category_id>/delete")
@login_required
def delete_category(category_id):
    _manager_required()
    category = _category(category_id)
    if Product.query.filter_by(category_id=category.id, business_id=current_business_id()).first():
        flash("Reassign or remove this category from its products before deleting it.", "error")
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Category deleted.", "success")
    return redirect(url_for("inventory.categories"))
