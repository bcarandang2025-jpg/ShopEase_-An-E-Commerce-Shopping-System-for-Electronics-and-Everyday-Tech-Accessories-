
class Product:
    def __init__(self, product_id, name, description, price, stock):
        self.product_id = product_id
        self.name = name
        self.description = description
        self.price = float(price)
        self.stock = int(stock)

    def is_available(self, quantity=1):
        return 0 < quantity <= self.stock

    def __str__(self):
        return f"{self.name} - ₱{self.price:.2f}"
