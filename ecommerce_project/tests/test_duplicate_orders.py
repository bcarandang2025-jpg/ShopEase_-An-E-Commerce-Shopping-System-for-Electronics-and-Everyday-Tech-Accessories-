import sqlite3
import unittest

from services.order_service import find_duplicate_order


class DuplicateOrderTests(unittest.TestCase):

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

        self.connection.executescript(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                total REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL
            );

            INSERT INTO customers (id, email)
            VALUES (1, 'test@example.com');

            INSERT INTO orders (
                id, customer_id, total, created_at
            )
            VALUES (
                1, 1, 1500.00,
                datetime('now', '-1 minute')
            );

            INSERT INTO order_items (
                order_id, product_id, quantity
            )
            VALUES (1, 1, 2);

            INSERT INTO order_items (
                order_id, product_id, quantity
            )
            VALUES (1, 2, 1);
            """
        )

    def tearDown(self):
        self.connection.close()

    def test_duplicate_order_is_detected(self):

        items = [
            {"product_id": 1, "quantity": 2},
            {"product_id": 2, "quantity": 1}
        ]

        duplicate_id = find_duplicate_order(
            self.connection,
            "test@example.com",
            items,
            1500.00
        )

        self.assertEqual(duplicate_id, 1)

    def test_different_email_is_not_duplicate(self):

        items = [
            {"product_id": 1, "quantity": 2},
            {"product_id": 2, "quantity": 1}
        ]

        duplicate_id = find_duplicate_order(
            self.connection,
            "another@example.com",
            items,
            1500.00
        )

        self.assertIsNone(duplicate_id)

    def test_different_total_is_not_duplicate(self):

        items = [
            {"product_id": 1, "quantity": 2},
            {"product_id": 2, "quantity": 1}
        ]

        duplicate_id = find_duplicate_order(
            self.connection,
            "test@example.com",
            items,
            2000.00
        )

        self.assertIsNone(duplicate_id)

    def test_different_items_are_not_duplicate(self):

        items = [
            {"product_id": 3, "quantity": 1}
        ]

        duplicate_id = find_duplicate_order(
            self.connection,
            "test@example.com",
            items,
            1500.00
        )

        self.assertIsNone(duplicate_id)

    def test_empty_items_return_none(self):

        duplicate_id = find_duplicate_order(
            self.connection,
            "test@example.com",
            [],
            1500.00
        )

        self.assertIsNone(duplicate_id)


if __name__ == "__main__":
    unittest.main()