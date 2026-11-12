# ShopEase – E-Commerce Web Application

**An E-Commerce Web Application for Electronics and Everyday Tech Accessories**

## 1. Project Overview

ShopEase is a web-based e-commerce application developed using Python, Flask, SQLite, HTML, CSS, and JavaScript. It provides customers with a convenient platform to browse electronic products, manage their shopping cart, proceed to checkout, and view their order information.

This project was developed as a requirement for the Object-Oriented Programming (CSC 221) course.

## 2. Project Objectives

- Develop a simple and user-friendly online shopping application.
- Allow customers to browse available products.
- Provide shopping cart and checkout functionality.
- Implement simulated payment processing.
- Allow administrators to manage customer orders.
- Demonstrate Object-Oriented Programming principles.

## 3. Main Features

- **Product Catalog** – Displays available electronics and accessories.
- **Shopping Cart** – Allows customers to add, update, and remove products.
- **Checkout System** – Collects customer information and order details.
- **Mock Payment** – Simulates payment processing without real transactions.
- **Order Tracking** – Allows customers to check their order information.
- **Admin Login** – Provides protected access to administrative functions.
- **Admin Dashboard** – Helps administrators manage orders.

## 4. Technologies Used

| Technology | Purpose |
|---|---|
| Python | Main programming language |
| Flask | Backend web framework |
| SQLite | Database management |
| HTML | Web page structure |
| CSS | Website styling |
| JavaScript | Interactive website functions |
| Git and GitHub | Version control and project hosting |
| Render | Web application deployment |

## 5. Object-Oriented Programming Concepts

- **Encapsulation** – Organizes product, customer, and cart data within classes.
- **Abstraction** – Uses an abstract Payment class to define payment behavior.
- **Inheritance** – Allows MockPayment and MockCashPayment to inherit from Payment.
- **Polymorphism** – Allows different payment classes to implement the same pay() method differently.

## 6. Installation and Setup

### Prerequisites

- Python 3
- Git
- Visual Studio Code

### Clone the Repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd ecommerce_project
```

### Create a Virtual Environment

```bash
python -m venv .venv
```

### Activate the Virtual Environment

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the Application

```bash
python app.py
```

Open your browser and visit:

```text
http://127.0.0.1:5000
```

## 7. Deployment

The ShopEase application is deployed using Render.

**Live Website:** [Insert your Render URL here]

**GitHub Repository:** [Insert your GitHub repository URL here]

## 8. Project Developer

**Bonifacio II A. Carandang**

Object-Oriented Programming (CSC 221)

## 9. Project Purpose

ShopEase was developed as an educational project to demonstrate the practical application of Object-Oriented Programming concepts in building a simple e-commerce web application. It also provides experience in database integration, web development, software testing, and application deployment.

---

*ShopEase – Smart Finds. Everyday Value.*
