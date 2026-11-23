
from database import get_connection

connection = get_connection()

print("\n===== CUSTOMERS =====")
for row in connection.execute(
    "SELECT * FROM customers ORDER BY id"
).fetchall():
    print(dict(row))

print("\n===== ORDERS =====")
for row in connection.execute(
    "SELECT * FROM orders ORDER BY id"
).fetchall():
    print(dict(row))

print("\n===== ORDER ITEMS =====")
for row in connection.execute("""
    SELECT
        order_items.order_id,
        products.name,
        order_items.quantity,
        order_items.price
    FROM order_items
    JOIN products
        ON products.id = order_items.product_id
    ORDER BY order_items.id
""").fetchall():
    print(dict(row))

print("\n===== UPDATED STOCK =====")
for row in connection.execute(
    "SELECT name, stock FROM products ORDER BY id"
).fetchall():
    print(dict(row))

connection.close()
