
from models.product import Product
from models.customer import Customer
from models.cart import Cart
from models.payment import MockPayment, MockCashPayment

# Create sample products
mouse = Product(1, "Wireless Mouse", "USB wireless mouse", 350, 10)
keyboard = Product(2, "Keyboard", "Standard USB keyboard", 650, 5)

# Test the cart
cart = Cart()
cart.add_product(mouse, 2)
cart.add_product(keyboard, 1)

print("Cart items:")
for item in cart.get_items():
    print(item["product"], "x", item["quantity"])

print(f"Total: ₱{cart.total:.2f}")

# Test encapsulation
customer = Customer("Alex Santos", "alex@example.com")
print("Customer email:", customer.email)

# Test polymorphism
payments = [MockPayment(), MockCashPayment()]

for payment in payments:
    payment.pay(cart.total)
