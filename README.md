# AMS Store — B2B Commerce (Django)

A wholesale ordering site where authenticated **buyers** browse a product
catalog, see stock **only for the warehouses assigned to them**, fill a basket
and place orders. Store staff manage everything through the Django admin.

## Features

- Custom buyer accounts (registration + login) with per-buyer warehouse access.
- Catalog of products (unique **SKU**, plus non-unique **article** and optional
  **manufacturer number**, name, brand, **category + subcategory**, picture,
  description, price) with search and brand / category / subcategory filters.
- Multiple warehouses, each with its own per-product stock.
- Session-based **current warehouse** switcher — buyers only ever see the stock
  of warehouses they are allowed to access.
- Basket (add / update quantity / remove) and checkout that validates stock,
  decrements it atomically, and snapshots prices onto the order.
- Order history for buyers; full management (products, stock, buyers, orders)
  in the Django admin.

## Apps

| App          | Responsibility                                  |
|--------------|-------------------------------------------------|
| `accounts`   | Custom `User` (buyer), auth, warehouse access    |
| `catalog`    | `Brand`, `Category`, `Product`                   |
| `warehouses` | `Warehouse`, `Stock`, current-warehouse logic    |
| `orders`     | `Cart`/`CartItem`, `Order`/`OrderItem`, checkout |

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo      # optional: demo data + accounts
python manage.py runserver
```

Open http://127.0.0.1:8000/

### Demo accounts (created by `seed_demo`)

| Role  | Login                  | Sees warehouses     |
|-------|------------------------|---------------------|
| Admin | `admin` / `admin12345` | all (Django admin)  |
| Buyer | `buyer1` / `buyerpass123` | Berlin, Warsaw   |
| Buyer | `buyer2` / `buyerpass123` | Amsterdam        |

> The `admin` account is created for local development only — change the
> password (or create your own superuser with `python manage.py createsuperuser`)
> before deploying anywhere.

## Managing the store

Log in to `/admin/` as staff to:

- add brands, categories and products (set the product **picture** here);
- **bulk-import products from Excel** (Products → *Upload from Excel*): columns
  `sku, article, Name, category, subcategory, model product, weight, volume,
  manufacturer number, price`; any extra column (e.g. a city) becomes a
  **warehouse** whose cells are stock quantities;
- manage the **home-page banner** (Banner slides): upload up to 7 images shown
  as a rotating full-width carousel on the main page;
- create warehouses and set **stock** per warehouse (inline on either the
  product or the warehouse);
- create buyer accounts and assign their **warehouses** (User → "Buyer info");
- review and update **orders**.

## Notes / next steps

- **Database:** set `DB_NAME` (+ `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT`)
  in `.env` to use **PostgreSQL**; leave `DB_NAME` unset to fall back to SQLite.
  Locally a Homebrew `postgresql@16` service backs the `ams` database
  (`brew services start postgresql@16`).
- **Order emails:** give each warehouse an email (admin → Warehouses). When a
  buyer places an order it is emailed to the warehouse (reply-to = buyer) **and**
  a confirmation is sent to the buyer (reply-to = warehouse). Configure SMTP in a
  **`.env`** file (copy `.env.example`); delivery switches from the console to
  real SMTP automatically once `EMAIL_HOST` is set.
- Prices are stored as plain decimals (no currency symbol is assumed).
- Before production: set `DEBUG = False`, a real `SECRET_KEY`, `ALLOWED_HOSTS`,
  and serve `static`/`media` properly.
