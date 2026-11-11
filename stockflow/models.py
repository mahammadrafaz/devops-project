"""Database models for StockFlow's multi-tenant identity layer."""

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    users = db.relationship("User", back_populates="business", cascade="all, delete-orphan")
    invitations = db.relationship("Invitation", back_populates="business", cascade="all, delete-orphan")
    categories = db.relationship("Category", back_populates="business", cascade="all, delete-orphan")
    products = db.relationship("Product", back_populates="business", cascade="all, delete-orphan")
    stock_movements = db.relationship("StockMovement", back_populates="business", cascade="all, delete-orphan")


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    business = db.relationship("Business", back_populates="categories")
    products = db.relationship("Product", back_populates="category")
    __table_args__ = (db.UniqueConstraint("business_id", "name", name="uq_category_business_name"),)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id", ondelete="RESTRICT"), nullable=True, index=True)
    name = db.Column(db.String(160), nullable=False)
    sku = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    purchase_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    selling_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    business = db.relationship("Business", back_populates="products")
    category = db.relationship("Category", back_populates="products")
    movements = db.relationship("StockMovement", back_populates="product", cascade="all, delete-orphan", order_by="StockMovement.created_at.desc()")
    __table_args__ = (
        db.UniqueConstraint("business_id", "sku", name="uq_product_business_sku"),
        db.CheckConstraint("quantity >= 0", name="ck_product_nonnegative_quantity"),
        db.CheckConstraint("low_stock_threshold >= 0", name="ck_product_nonnegative_threshold"),
        db.Index("ix_product_business_name", "business_id", "name"),
    )


class StockMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    operation_type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    business = db.relationship("Business", back_populates="stock_movements")
    product = db.relationship("Product", back_populates="movements")
    user = db.relationship("User")
    __table_args__ = (
        db.CheckConstraint("operation_type IN ('in', 'out')", name="ck_stock_movement_type"),
        db.CheckConstraint("quantity > 0", name="ck_stock_movement_positive_quantity"),
        db.Index("ix_movement_business_product_date", "business_id", "product_id", "created_at"),
    )


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    business = db.relationship("Business", back_populates="users")

    __table_args__ = (db.CheckConstraint("role IN ('owner', 'manager', 'staff')", name="ck_user_valid_role"),)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    business = db.relationship("Business", back_populates="invitations")

    __table_args__ = (db.CheckConstraint("role IN ('manager', 'staff')", name="ck_invitation_valid_role"),)
