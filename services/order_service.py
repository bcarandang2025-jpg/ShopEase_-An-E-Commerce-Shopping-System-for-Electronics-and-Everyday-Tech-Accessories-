
def find_duplicate_order(
    connection,
    email,
    items,
    total,
    minutes=5
):
    """
    Detects a recently submitted duplicate order.

    Matching criteria:
    - Customer email
    - Total amount
    - Product IDs and quantities
    - Order within the specified time window

    Returns:
        Order ID if a duplicate is found.
        None if no duplicate is found.
    """

    if not email or not items:
        return None

    email = email.strip().lower()

    try:
        submitted_items = sorted(
            (
                int(item["product_id"]),
                int(item["quantity"])
            )
            for item in items
        )
    except (KeyError, ValueError, TypeError):
        return None

    if not submitted_items:
        return None

    if any(product_id <= 0 or quantity <= 0
           for product_id, quantity in submitted_items):
        return None

    cursor = connection.cursor()

    # Use SQLite's own UTC clock to avoid timezone mismatch.
    time_window = f"-{int(minutes)} minutes"

    cursor.execute(
        """
        SELECT o.id
        FROM orders AS o
        JOIN customers AS c ON o.customer_id = c.id
        WHERE LOWER(TRIM(c.email)) = ?
          AND o.total = ?
          AND o.created_at >= datetime('now', ?)
        ORDER BY o.id DESC
        """,
        (
            email,
            float(total),
            time_window
        )
    )

    possible_orders = cursor.fetchall()

    for order in possible_orders:

        order_id = order["id"] if isinstance(
            order, dict
        ) or hasattr(order, "keys") else order[0]

        cursor.execute(
            """
            SELECT product_id, quantity
            FROM order_items
            WHERE order_id = ?
            """,
            (order_id,)
        )

        existing_items = cursor.fetchall()

        normalized_existing_items = sorted(
            (
                int(row["product_id"]),
                int(row["quantity"])
            )
            for row in existing_items
        )

        if normalized_existing_items == submitted_items:
            return order_id

    return None
