import sqlite3
import unittest


class DatabaseTests(unittest.TestCase):

    def setUp(self):

        self.connection = sqlite3.connect(":memory:")

        self.connection.execute(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL
            )
            """
        )

    def tearDown(self):
        self.connection.close()

    def test_insert_product(self):

        self.connection.execute(
            """
            INSERT INTO products (name, price, stock)
            VALUES (?, ?, ?)
            """,
            ("Wireless Mouse", 500.00, 10)
        )

        self.connection.commit()

        cursor = self.connection.execute(
            "SELECT * FROM products WHERE name = ?",
            ("Wireless Mouse",)
        )

        product = cursor.fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(product[1], "Wireless Mouse")
        self.assertEqual(product[2], 500.00)
        self.assertEqual(product[3], 10)

    def test_update_stock(self):

        self.connection.execute(
            """
            INSERT INTO products (name, price, stock)
            VALUES (?, ?, ?)
            """,
            ("Keyboard", 1000.00, 10)
        )

        self.connection.execute(
            """
            UPDATE products
            SET stock = ?
            WHERE name = ?
            """,
            (5, "Keyboard")
        )

        self.connection.commit()

        cursor = self.connection.execute(
            "SELECT stock FROM products WHERE name = ?",
            ("Keyboard",)
        )

        stock = cursor.fetchone()[0]

        self.assertEqual(stock, 5)

    def test_delete_product(self):

        self.connection.execute(
            """
            INSERT INTO products (name, price, stock)
            VALUES (?, ?, ?)
            """,
            ("Headphones", 1500.00, 5)
        )

        self.connection.execute(
            "DELETE FROM products WHERE name = ?",
            ("Headphones",)
        )

        self.connection.commit()

        cursor = self.connection.execute(
            "SELECT * FROM products WHERE name = ?",
            ("Headphones",)
        )

        product = cursor.fetchone()

        self.assertIsNone(product)

    def test_empty_database(self):

        cursor = self.connection.execute(
            "SELECT * FROM products"
        )

        products = cursor.fetchall()

        self.assertEqual(len(products), 0)


if __name__ == "__main__":
    unittest.main()