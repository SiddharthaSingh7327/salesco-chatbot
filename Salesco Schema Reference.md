# SalesCo Demo Database — Schema & Relationship Reference

Sales & fulfillment database, sized 
- 6 tables, 
- each with 75–140 realistic rows, 
- real foreign keys, 
- enough business logic (discounts, hierarchy, statuses) to exercise a range of query complexity.

Import: `psql -U <user> -d <dbname> -f salesco_demo.sql`

## Tables

| Table | Rows | What it represents |
|---|---|---|
| `employees` | 75 | Sales org staff — reps up through VP, with a manager hierarchy |
| `customers` | 85 | Companies/individuals who place orders |
| `products` | 90 | Product catalog across 5 categories |
| `orders` | 95 | Orders placed by customers, handled by a sales rep |
| `order_items` | 140 | Line items within each order (product, qty, discount) |
| `shipments` | 80 | Shipment tracking for a subset of orders |

## Entity-Relationship Diagram

```
                     ┌─────────────┐
                     │  employees  │◄──┐
                     └──────┬──────┘   │ manager_id
                            │          │ (self-referencing:
                            │ employee_id  reports_to hierarchy)
                            │          └──┘
                            ▼
┌────────────┐        ┌─────────┐        ┌──────────┐
│ customers  │───────►│ orders  │◄───────│  (rep)   │
└────────────┘customer_id   │employee_id
                            │
                ┌───────────┼────────────┐
                ▼                        ▼
        ┌──────────────┐          ┌────────────┐
        │ order_items  │◄────────►│  products  │
        └──────────────┘product_id└────────────┘
                ▲
                │ order_id
                │
        ┌──────────────┐
        │  shipments   │
        └──────────────┘
```

## Table Details

### `employees`
| Column | Type | Notes |
|---|---|---|
| employee_id | PK | |
| first_name, last_name | | |
| title | | VP of Sales → Sales Director → Regional Sales Manager → Sr./Account Exec → Sales Representative |
| email | unique | |
| hire_date | | |
| region | | North America / EMEA / APAC / LATAM |
| manager_id | FK → employees.employee_id | **self-referencing** — nullable at the top (VP has no manager) |

### `customers`
| Column | Type | Notes |
|---|---|---|
| customer_id | PK | |
| company_name, contact_name | | |
| email | unique | |
| city, country | | |
| segment | | Enterprise / SMB / Individual |

### `products`
| Column | Type | Notes |
|---|---|---|
| product_id | PK | |
| product_name, category | | 5 categories: Office Supplies, Electronics, Furniture, Software Licenses, Packaging |
| unit_price | | list price (order_items may differ — see below) |
| units_in_stock | | |
| discontinued | boolean | ~8% of catalog |

### `orders`
| Column | Type | Notes |
|---|---|---|
| order_id | PK | |
| customer_id | FK → customers | |
| employee_id | FK → employees | only reps/senior reps/account execs take orders, not managers |
| order_date, required_date | | |
| status | | Completed / Processing / Pending / Cancelled / On Hold |
| ship_country | | may differ from customer's home country |

### `order_items`
| Column | Type | Notes |
|---|---|---|
| order_item_id | PK | |
| order_id | FK → orders | |
| product_id | FK → products | |
| unit_price | | price *at time of sale* — intentionally can differ from `products.unit_price` (mirrors real-world price history) |
| quantity | | |
| discount | | 0, 5, 10, 15, or 20% |

### `shipments`
| Column | Type | Notes |
|---|---|---|
| shipment_id | PK | |
| order_id | FK → orders | not every order has a shipment row (pending/cancelled ones may not) |
| carrier | | FedEx / UPS / DHL / USPS / Maersk Logistics |
| tracking_number | | |
| ship_date | | |
| delivery_date | nullable | null unless status = Delivered |
| shipment_status | | Delivered / In Transit / Delayed / Returned |

## Relationship Summary

| Relationship | Type | Meaning |
|---|---|---|
| employees.manager_id → employees.employee_id | self-referencing 1:N | org hierarchy — a manager has many reports |
| customers.customer_id → orders.customer_id | 1:N | a customer can place many orders |
| employees.employee_id → orders.employee_id | 1:N | a rep can handle many orders |
| orders.order_id → order_items.order_id | 1:N | an order has many line items |
| products.product_id → order_items.product_id | 1:N | a product appears in many order line items |
| orders.order_id → shipments.order_id | 1:N | an order may have one or more shipment records |

## Why this schema is good for text-to-SQL testing

- **Simple lookups**: "Show all customers in Germany"
- **Aggregation**: "Total revenue by product category"
- **Multi-table joins (3–4 hops)**: "Which sales rep generated the most revenue after discounts?"
- **Self-join / hierarchy**: "List everyone who reports to Mario Hernandez" or "Show the full management chain for employee X"
- **Nullable / conditional logic**: "Which orders have no shipment yet?" or "What's the average delivery time for delivered shipments?"
- **Time-based filtering**: "Orders placed in Q1 2025 that are still Pending"
- **Business calculations**: "Revenue after discount" requires `quantity * unit_price * (1 - discount)` — good test of whether your chatbot can generate correct arithmetic in SQL, not just simple SELECTs
