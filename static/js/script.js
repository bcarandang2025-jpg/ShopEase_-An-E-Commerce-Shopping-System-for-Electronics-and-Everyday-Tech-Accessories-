
const CART_KEY = "shopease_cart";

/* =========================================
   LOAD AND SAVE CART
========================================= */

function loadCart() {
    try {
        const saved = JSON.parse(localStorage.getItem(CART_KEY) || "{}");

        if (!saved || typeof saved !== "object" || Array.isArray(saved)) {
            return {};
        }

        const validCart = {};

        Object.entries(saved).forEach(([key, item]) => {
            const id = Number(item?.id ?? key);
            const price = Number(item?.price);
            const quantity = Math.floor(Number(item?.quantity));
            const stock = Math.max(0, Math.floor(Number(item?.stock) || 0));

            if (
                Number.isSafeInteger(id) && id > 0 &&
                Number.isFinite(price) && price >= 0 &&
                Number.isSafeInteger(quantity) && quantity > 0 &&
                stock > 0
            ) {
                validCart[String(id)] = {
                    id,
                    name: String(item.name || "Product"),
                    price,
                    quantity: Math.min(quantity, stock),
                    stock
                };
            }
        });

        return validCart;
    } catch (error) {
        console.error("Unable to load cart:", error);
        return {};
    }
}

let cart = loadCart();

function saveCart() {
    try {
        localStorage.setItem(CART_KEY, JSON.stringify(cart));
    } catch (error) {
        console.error("Unable to save cart:", error);
    }
}

/* =========================================
   FORMAT PRICE
========================================= */

function formatPrice(amount) {
    return Number(amount).toLocaleString("en-PH", {
        style: "currency",
        currency: "PHP",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/* =========================================
   PRODUCT PICTURES
========================================= */

function getProductImage(productName) {
    const name = String(productName || "").toLowerCase();

    if (name.includes("mouse")) {
        return "https://images.unsplash.com/photo-1527814050087-3793815479db?auto=format&fit=crop&w=300&q=80";
    }

    if (name.includes("keyboard")) {
        return "https://images.unsplash.com/photo-1587829741301-dc798b83add3?auto=format&fit=crop&w=300&q=80";
    }

    if (name.includes("headphone")) {
        return "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=300&q=80";
    }

    if (name.includes("flash drive") || name.includes("usb")) {
        return "/static/images/flash-drive.jpg";
    }

    if (name.includes("stand")) {
        return "/static/images/laptop-stand.jpg";
    }

    return "/static/images/shopease-logo.png";
}

/* =========================================
   CART COUNT
========================================= */

function updateCartCount() {
    const count = Object.values(cart).reduce(
        (sum, item) => sum + item.quantity,
        0
    );

    const countElement = document.getElementById("cart-count");

    if (countElement) {
        countElement.textContent = count;
    }
}

/* =========================================
   RENDER SHOPPING CART
========================================= */

function renderCart() {
    const container = document.getElementById("cart-items");

    // The homepage does not contain this element.
    if (!container) {
        updateCartCount();
        return;
    }

    container.replaceChildren();

    const items = Object.values(cart);
    let total = 0;

    if (items.length === 0) {
        const emptyMessage = document.createElement("div");
        emptyMessage.className = "empty-cart";

        const heading = document.createElement("h2");
        heading.textContent = "Your cart is empty";

        const description = document.createElement("p");
        description.textContent =
            "You haven't added any products to your shopping bag yet.";

        const link = document.createElement("a");
        link.href = "/";
        link.textContent = "Browse Products";

        emptyMessage.append(heading, description, link);
        container.appendChild(emptyMessage);
    }

    items.forEach((item) => {
        const id = String(item.id);
        const subtotal = item.price * item.quantity;

        total += subtotal;

        const row = document.createElement("article");
        row.className = "cart-row";

        // Product image
        const imageContainer = document.createElement("div");
        imageContainer.className = "cart-product-image";

        const image = document.createElement("img");
        image.src = getProductImage(item.name);
        image.alt = item.name;
        image.loading = "lazy";

        image.onerror = function () {
            this.onerror = null;
            this.src = "/static/images/shopease-logo.png";
        };

        imageContainer.appendChild(image);

        // Product details
        const details = document.createElement("div");
        details.className = "cart-product-details";

        const title = document.createElement("h3");
        title.textContent = item.name;

        const unitPrice = document.createElement("p");
        unitPrice.textContent = `Price: ${formatPrice(item.price)} each`;

        const subtotalText = document.createElement("p");
        subtotalText.className = "cart-item-price";
        subtotalText.textContent = `Subtotal: ${formatPrice(subtotal)}`;

        const stockText = document.createElement("p");
        stockText.textContent = `Available stock: ${item.stock}`;

        details.append(title, unitPrice, subtotalText, stockText);

        // Quantity controls
        const controls = document.createElement("div");
        controls.className = "cart-controls";

        const quantityControls = document.createElement("div");
        quantityControls.className = "quantity-controls";

        const minus = document.createElement("button");
        minus.type = "button";
        minus.textContent = "−";
        minus.setAttribute("aria-label", `Decrease ${item.name}`);

        minus.addEventListener("click", () => {
            if (!cart[id]) return;

            cart[id].quantity -= 1;

            if (cart[id].quantity <= 0) {
                delete cart[id];
            }

            saveCart();
            renderCart();
        });

        const quantityText = document.createElement("span");
        quantityText.textContent = item.quantity;
        quantityText.setAttribute("aria-label", "Quantity");

        const plus = document.createElement("button");
        plus.type = "button";
        plus.textContent = "+";
        plus.setAttribute("aria-label", `Increase ${item.name}`);
        plus.disabled = item.quantity >= item.stock;

        plus.addEventListener("click", () => {
            if (!cart[id]) return;

            if (cart[id].quantity >= cart[id].stock) {
                alert("You have reached the available stock.");
                return;
            }

            cart[id].quantity += 1;
            saveCart();
            renderCart();
        });

        quantityControls.append(minus, quantityText, plus);

        // Remove button
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-button";
        remove.textContent = "Remove";
        remove.setAttribute("aria-label", `Remove ${item.name} from cart`);

        remove.addEventListener("click", () => {
            delete cart[id];
            saveCart();
            renderCart();
        });

        controls.append(quantityControls, remove);
        row.append(imageContainer, details, controls);
        container.appendChild(row);
    });

    // Update total
    const totalElement = document.getElementById("cart-total");

    if (totalElement) {
        totalElement.textContent = formatPrice(total);
    }

    // Disable checkout if the cart is empty
    const checkoutButton = document.getElementById("checkout-button");

    if (checkoutButton) {
        checkoutButton.disabled = items.length === 0;
    }

    updateCartCount();
}

/* =========================================
   ADD PRODUCTS FROM CATALOG
========================================= */

document.querySelectorAll(".add-button").forEach((button) => {
    const originalText = button.textContent.trim() || "Add to Cart +";

    button.addEventListener("click", () => {
        const id = Number(button.dataset.id);
        const stock = Math.floor(Number(button.dataset.stock));
        const price = Number(button.dataset.price);
        const name = String(button.dataset.name || "").trim();

        if (
            !Number.isSafeInteger(id) || id <= 0 ||
            !Number.isSafeInteger(stock) || stock < 1 ||
            !Number.isFinite(price) || price < 0 ||
            !name
        ) {
            alert("Unable to read product information.");
            return;
        }

        const key = String(id);

        if (cart[key] && cart[key].quantity >= stock) {
            alert("You have reached the available stock.");
            return;
        }

        if (!cart[key]) {
            cart[key] = {
                id,
                name,
                price,
                quantity: 0,
                stock
            };
        } else {
            // Refresh the stored stock and product information.
            cart[key].stock = stock;
            cart[key].name = name;
            cart[key].price = price;
        }

        cart[key].quantity += 1;

        saveCart();
        updateCartCount();

        button.textContent = "Added ✓";
        button.disabled = cart[key].quantity >= stock;

        setTimeout(() => {
            button.textContent = originalText;
            button.disabled = stock < 1;
        }, 800);
    });
});

/* =========================================
   CHECKOUT
========================================= */

const checkoutForm = document.getElementById("checkout-form");

if (checkoutForm) {
    checkoutForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const message = document.getElementById("checkout-message");
        const button = document.getElementById("checkout-button");

        if (!message || !button) {
            console.error("Checkout message or button element is missing.");
            return;
        }

        if (Object.keys(cart).length === 0) {
            message.textContent = "Please add products to your cart first.";
            return;
        }

        if (!checkoutForm.reportValidity()) {
            return;
        }

        const formData = new FormData(checkoutForm);

        const payload = {
            name: String(formData.get("name") || "").trim(),
            email: String(formData.get("email") || "").trim(),
            phone: String(formData.get("phone") || "").trim(),
            items: Object.values(cart).map((item) => ({
                id: item.id,
                quantity: item.quantity
            }))
        };

        if (!payload.name || !payload.email) {
            message.textContent = "Please enter your name and email.";
            return;
        }

        button.disabled = true;
        message.textContent = "Processing your mock order...";

        try {
            const response = await fetch("/api/checkout", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });

            // Handle non-JSON server responses safely.
            let result;

            try {
                result = await response.json();
            } catch {
                throw new Error("The server returned an unexpected response.");
            }

            if (!response.ok) {
                throw new Error(result.error || "Checkout failed.");
            }

            if (!result.order_id) {
                throw new Error("Order was created, but no order number was returned.");
            }

            // Clear cart only after a successful server response.
            cart = {};
            saveCart();
            renderCart();
            checkoutForm.reset();

            message.textContent =
                `Order #${result.order_id} confirmed! ` +
                `Total: ${formatPrice(result.total)}. ` +
                "Mock payment successful.";

            // Redirect to the tracking page after a short delay.
            const trackingUrl =
                result.tracking_url ||
                `/track-order?order_id=${encodeURIComponent(result.order_id)}`;

            setTimeout(() => {
                window.location.href = trackingUrl;
            }, 1800);

        } catch (error) {
            message.textContent =
                error.message || "Something went wrong. Please try again.";
        } finally {
            button.disabled = Object.keys(cart).length === 0;
        }
    });
}

/* =========================================
   INITIALIZE
========================================= */

renderCart();
updateCartCount();


/* =====================================
   SHOEASE PRODUCT SEARCH
===================================== */

document.addEventListener("DOMContentLoaded", function () {
    const searchForm = document.getElementById("product-search-form");
    const searchInput = document.getElementById("product-search");
    const productGrid = document.querySelector(".product-grid");
    const productCount = document.querySelector(".product-count");

    if (!searchForm || !searchInput || !productGrid) {
        return;
    }

    const productCards = Array.from(
        productGrid.querySelectorAll(".product-card")
    );

    // Create a no-results message
    const noResults = document.createElement("div");
    noResults.id = "search-no-results";
    noResults.className = "empty-products";
    noResults.hidden = true;

    noResults.innerHTML = `
        <i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>
        <h3>No products found</h3>
        <p>Try another product name or keyword.</p>
    `;

    productGrid.appendChild(noResults);

    function searchProducts() {
        const query = searchInput.value.trim().toLowerCase();
        let visibleCount = 0;

        productCards.forEach(function (card) {
            const name =
                card.querySelector("h3")?.textContent || "";

            const description =
                card.querySelector(".description")?.textContent || "";

            const category =
                card.querySelector(".product-category")?.textContent || "";

            const searchableText =
                `${name} ${description} ${category}`.toLowerCase();

            const matches = searchableText.includes(query);

            card.hidden = !matches;

            if (matches) {
                visibleCount++;
            }
        });

        // Show the message only when a search has no matches
        noResults.hidden = query === "" || visibleCount > 0;

        // Update the product count
        if (productCount) {
            if (query === "") {
                productCount.textContent =
                    `${productCards.length} products`;
            } else {
                productCount.textContent =
                    `${visibleCount} matching products`;
            }
        }
    }

    // Search as the customer types
    searchInput.addEventListener("input", searchProducts);

    // Handle clicking Search or pressing Enter
    searchForm.addEventListener("submit", function (event) {
        event.preventDefault();

        searchProducts();

        document.getElementById("products")?.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    });
});
