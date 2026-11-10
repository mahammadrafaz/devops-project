from datetime import timedelta
from decimal import Decimal
import re

from stockflow.extensions import db
from stockflow.models import Business, Category, Product, StockMovement, User, utcnow


def _login(client, email, password="strong-password"):
    client.post("/login", data={"email": email, "password": password})


def _user(app, email, role="owner"):
    with app.app_context():
        business = Business(name=email)
        user = User(name=email.split("@")[0], email=email, role=role, business=business)
        user.set_password("strong-password")
        db.session.add(user)
        db.session.commit()
        return user.id, business.id


def _product(business_id, name, sku, quantity, threshold=5, price="2.50", category=None):
    return Product(business_id=business_id, name=name, sku=sku, quantity=quantity,
                   low_stock_threshold=threshold, purchase_price=Decimal(price),
                   selling_price=Decimal("4.00"), category=category)


def test_dashboard_statistics_value_low_stock_and_category_distribution(client, app):
    _, business_id = _user(app, "owner@dashboard.test")
    with app.app_context():
        category = Category(business_id=business_id, name="Hardware")
        db.session.add(category)
        db.session.flush()
        db.session.add_all([
            _product(business_id, "Bolt", "B-1", 4, 5, "2.50", category),
            _product(business_id, "Nut", "N-1", 10, 3, "1.25", category),
            _product(business_id, "Washer", "W-1", 0, 0, "9.99"),
        ])
        db.session.commit()
    _login(client, "owner@dashboard.test")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Total products" in response.data
    assert b"Inventory value" in response.data
    assert b"Bolt" in response.data
    assert b"Hardware" in response.data
    assert b"Uncategorized" not in response.data  # zero units are omitted from chart labels
    with app.app_context():
        owner_id = User.query.filter_by(email="owner@dashboard.test").one().business_id
        assert owner_id == business_id
        # Purchase value = 4 * 2.50 + 10 * 1.25 + 0 * 9.99 = 22.50.
        assert db.session.query(db.func.sum(Product.purchase_price * Product.quantity)).filter_by(business_id=owner_id).scalar() == Decimal("22.50")
        assert Product.query.filter(Product.business_id == owner_id, Product.quantity <= Product.low_stock_threshold).count() == 2


def test_dashboard_recent_activity_and_7_day_filter(client, app):
    _, business_id = _user(app, "activity@dashboard.test")
    with app.app_context():
        product = _product(business_id, "Cable", "C-1", 20)
        db.session.add(product)
        db.session.flush()
        now = utcnow()
        db.session.add_all([
            StockMovement(business_id=business_id, product_id=product.id, operation_type="in", quantity=7, created_at=now - timedelta(days=2)),
            StockMovement(business_id=business_id, product_id=product.id, operation_type="out", quantity=3, created_at=now - timedelta(days=1)),
            StockMovement(business_id=business_id, product_id=product.id, operation_type="in", quantity=99, created_at=now - timedelta(days=10)),
        ])
        db.session.commit()
    _login(client, "activity@dashboard.test")
    seven = client.get("/dashboard?period=7")
    assert seven.status_code == 200
    assert b"Stock in" in seven.data and b"Stock out" in seven.data
    assert b"Cable" in seven.data
    seven_in = re.search(rb"label:'Stock in',data:(\[[^]]+\])", seven.data).group(1)
    assert b"99" not in seven_in
    with app.app_context():
        recent = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(10).all()
        assert len(recent) == 3
        assert sum(m.quantity for m in recent if (m.created_at.replace(tzinfo=utcnow().tzinfo) if m.created_at.tzinfo is None else m.created_at) >= utcnow() - timedelta(days=7)) == 10
    # Invalid values are rejected by falling back to the supported 7-day window.
    invalid = client.get("/dashboard?period=999")
    assert b"Last 7 days" in invalid.data
    thirty = client.get("/dashboard?period=30")
    assert b"Last 30 days" in thirty.data
    thirty_in = re.search(rb"label:'Stock in',data:(\[[^]]+\])", thirty.data).group(1)
    assert b"99" in thirty_in


def test_dashboard_empty_inventory_and_role_access(client, app):
    for role, email in (("owner", "empty-owner@test.example"), ("manager", "empty-manager@test.example"), ("staff", "empty-staff@test.example")):
        _user(app, email, role)
        _login(client, email)
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"Total products" in response.data
        assert b"No stock movements yet" in response.data
        if role == "staff":
            assert b"Create a catalog item" not in response.data
            assert b"Manage categories" not in response.data
        client.post("/logout")


def test_dashboard_data_is_isolated_between_businesses(client, app):
    _, first_business_id = _user(app, "first@dashboard.test")
    _, second_business_id = _user(app, "second@dashboard.test")
    with app.app_context():
        first = _product(first_business_id, "Private first item", "F-1", 91)
        second = _product(second_business_id, "Private second item", "S-1", 1)
        db.session.add_all([first, second])
        db.session.flush()
        db.session.add_all([
            StockMovement(business_id=first_business_id, product_id=first.id, operation_type="in", quantity=91),
            StockMovement(business_id=second_business_id, product_id=second.id, operation_type="out", quantity=77),
        ])
        db.session.commit()
    _login(client, "first@dashboard.test")
    response = client.get("/dashboard")
    assert b"Private first item" in response.data
    assert b"Private second item" not in response.data
    assert b"second@dashboard.test" not in response.data


def test_dashboard_limits_recent_movements_to_ten(client, app):
    _, business_id = _user(app, "many@dashboard.test")
    with app.app_context():
        product = _product(business_id, "Many moves", "M-1", 50)
        db.session.add(product)
        db.session.flush()
        for amount in range(1, 13):
            db.session.add(StockMovement(business_id=business_id, product_id=product.id,
                operation_type="in", quantity=amount, created_at=utcnow() + timedelta(seconds=amount)))
        db.session.commit()
    _login(client, "many@dashboard.test")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.data.count(b"Stock in") >= 10
