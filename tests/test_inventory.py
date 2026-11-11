from stockflow.extensions import db
from stockflow.models import Business, Category, Product, StockMovement, User


def _login(client, email, password="strong-password"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _register_and_login(client, email):
    password = "strong-password"
    response = client.post("/register", data={
        "business_name": "Acme",
        "owner_name": "Alex",
        "email": email,
        "password": password,
        "confirm_password": password,
    })

    assert response.status_code == 302
    return _login(client, email, password)


def _business_user(app, email, role="owner"):
    with app.app_context():
        business = Business(name=email)
        user = User(name=email.split("@")[0], email=email, role=role, business=business)
        user.set_password("strong-password")
        db.session.add(user)
        db.session.commit()
        return user.id, business.id


def _product_data(**updates):
    data = {
        "name": "Copper Cable",
        "sku": "CAB-01",
        "description": "Two core",
        "category_id": "",
        "purchase_price": "3.25",
        "selling_price": "5.50",
        "quantity": "10",
        "low_stock_threshold": "3",
    }
    data.update(updates)
    return data


def _add_product(client, **updates):
    return client.post(
        "/inventory/products/new",
        data=_product_data(**updates),
        follow_redirects=True,
    )


def test_product_crud_search_category_and_stock_adjustment_history(client, app):
    _register_and_login(client, "owner@example.com")

    assert client.post("/inventory/categories", data={"name": "Electrical"}).status_code == 302
    with app.app_context():
        category_id = Category.query.one().id

    response = _add_product(client, category_id=str(category_id))
    assert b"Copper Cable" in response.data
    with app.app_context():
        product = Product.query.one()
        product_id = product.id
        assert product.business_id == User.query.one().business_id
        assert product.quantity == 10
        assert StockMovement.query.one().notes == "Opening stock"

    assert b"CAB-01" in client.get("/inventory?q=CAB-01").data
    assert b"Copper Cable" not in client.get("/inventory?q=missing").data
    assert client.post(
        f"/inventory/products/{product_id}/edit",
        data=_product_data(
            name="Copper Wire",
            sku="CAB-02",
            category_id=str(category_id),
            quantity="8",
        ),
    ).status_code == 302

    with app.app_context():
        assert Product.query.one().name == "Copper Wire"
        assert [m.quantity for m in StockMovement.query.order_by(StockMovement.id).all()] == [10, 2]

    history_response = client.get(f"/inventory/products/{product_id}/history")
    assert b"Opening stock" in history_response.data
    assert b"adjusted during product edit" in history_response.data
    assert client.post(f"/inventory/products/{product_id}/delete").status_code == 302

    with app.app_context():
        assert Product.query.count() == 0
        assert StockMovement.query.count() == 0


def test_sku_uniqueness_is_scoped_to_business(client, app):
    _register_and_login(client, "a@x.test")
    _add_product(client)
    duplicate = _add_product(client, name="Duplicate")
    assert b"SKU is already used" in duplicate.data

    client.post("/logout")
    _business_user(app, "b@x.test")
    _login(client, "b@x.test")
    _add_product(client)

    with app.app_context():
        assert Product.query.count() == 2


def test_category_crud_uniqueness_and_protected_delete(client, app):
    _register_and_login(client, "cat@x.test")

    client.post("/inventory/categories", data={"name": "Hardware"})
    duplicate = client.post(
        "/inventory/categories",
        data={"name": "Hardware"},
        follow_redirects=True,
    )
    assert b"already exists" in duplicate.data

    with app.app_context():
        category_id = Category.query.one().id

    assert client.post(
        f"/inventory/categories/{category_id}/edit",
        data={"name": "Tools"},
    ).status_code == 302

    _add_product(client, category_id=str(category_id))
    response = client.post(
        f"/inventory/categories/{category_id}/delete",
        follow_redirects=True,
    )
    assert b"Reassign or remove" in response.data

    with app.app_context():
        assert Category.query.count() == 1
        assert Category.query.one().name == "Tools"
        product_id = Product.query.one().id

    client.post(f"/inventory/products/{product_id}/delete")
    assert client.post(f"/inventory/categories/{category_id}/delete").status_code == 302

    with app.app_context():
        assert Category.query.count() == 0


def test_stock_in_out_validation_atomicity_history_and_low_stock(client, app):
    _register_and_login(client, "stock@x.test")
    _add_product(client, quantity="5", low_stock_threshold="3")

    with app.app_context():
        product_id = Product.query.one().id

    assert client.post(
        f"/inventory/products/{product_id}/stock",
        data={"operation_type": "in", "quantity": "4", "notes": "delivery"},
    ).status_code == 302
    assert client.post(
        f"/inventory/products/{product_id}/stock",
        data={"operation_type": "out", "quantity": "6", "notes": "sale"},
    ).status_code == 302

    failure = client.post(
        f"/inventory/products/{product_id}/stock",
        data={"operation_type": "out", "quantity": "99"},
        follow_redirects=True,
    )
    assert b"Insufficient stock" in failure.data

    for invalid in ("0", "-2"):
        response = client.post(
            f"/inventory/products/{product_id}/stock",
            data={"operation_type": "in", "quantity": invalid},
            follow_redirects=True,
        )
        assert b"greater than zero" in response.data

    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.quantity == 3
        assert StockMovement.query.count() == 3
        assert sum(
            m.quantity if m.operation_type == "in" else -m.quantity
            for m in product.movements
        ) == product.quantity

    assert b"Low stock" in client.get("/inventory").data
    history = client.get(f"/inventory/products/{product_id}/history")
    assert b"delivery" in history.data and b"sale" in history.data and b"A" in history.data


def test_roles_and_cross_business_isolation(client, app):
    _register_and_login(client, "owner@a.test")
    _add_product(client)
    client.post("/logout")

    with app.app_context():
        business_id = User.query.filter_by(email="owner@a.test").one().business_id
        staff = User(
            name="staff",
            email="staff@a.test",
            role="staff",
            business_id=business_id,
        )
        staff.set_password("strong-password")
        db.session.add(staff)
        db.session.commit()
        staff_id = staff.id

    foreign_id, _ = _business_user(app, "owner@b.test")
    _login(client, "staff@a.test")

    assert client.get("/inventory").status_code == 200
    assert client.get("/inventory/products/new").status_code == 403
    assert client.get("/inventory/categories").status_code == 403

    with app.app_context():
        product_id = Product.query.one().id

    assert client.post(
        f"/inventory/products/{product_id}/stock",
        data={"operation_type": "in", "quantity": "1"},
    ).status_code == 302

    client.post("/logout")
    _login(client, "owner@b.test")
    assert b"Copper Cable" not in client.get("/inventory").data
    assert client.get(f"/inventory/products/{product_id}/history").status_code == 404
    assert client.post(
        f"/inventory/products/{product_id}/stock",
        data={"operation_type": "out", "quantity": "1"},
    ).status_code == 404

    with app.app_context():
        assert db.session.get(User, staff_id).role == "staff"
        assert db.session.get(User, foreign_id).role == "owner"
        assert Product.query.count() == 1
        assert StockMovement.query.count() == 2
