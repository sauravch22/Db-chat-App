-- ============================================================
-- Sales Demo Database — sample data for DbChat
-- ============================================================

-- Regions
CREATE TABLE regions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    country VARCHAR(50) NOT NULL
);
INSERT INTO regions (name, country) VALUES
('Northeast','USA'),('Southeast','USA'),('Midwest','USA'),('West','USA'),
('Ontario','Canada'),('Quebec','Canada'),('London','UK'),('Bavaria','Germany');

-- Departments
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    budget NUMERIC(12,2) NOT NULL
);
INSERT INTO departments (name, budget) VALUES
('Engineering',1500000),('Sales',800000),('Marketing',600000),
('Support',400000),('Finance',350000),('HR',300000);

-- Employees
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    department_id INT REFERENCES departments(id),
    region_id INT REFERENCES regions(id),
    hire_date DATE NOT NULL,
    salary NUMERIC(10,2) NOT NULL,
    is_active BOOLEAN DEFAULT true
);
INSERT INTO employees (first_name,last_name,email,department_id,region_id,hire_date,salary) VALUES
('Alice','Johnson','alice@demo.com',1,1,'2020-03-15',125000),
('Bob','Smith','bob@demo.com',2,2,'2019-07-01',95000),
('Carol','Williams','carol@demo.com',1,3,'2021-01-10',115000),
('David','Brown','david@demo.com',3,4,'2018-11-20',88000),
('Eve','Davis','eve@demo.com',2,1,'2022-05-05',92000),
('Frank','Miller','frank@demo.com',4,2,'2020-08-18',72000),
('Grace','Wilson','grace@demo.com',1,5,'2019-02-28',130000),
('Henry','Moore','henry@demo.com',5,6,'2021-06-14',105000),
('Ivy','Taylor','ivy@demo.com',2,7,'2023-01-09',85000),
('Jack','Anderson','jack@demo.com',6,8,'2022-09-01',78000),
('Karen','Thomas','karen@demo.com',1,1,'2020-12-01',118000),
('Leo','Jackson','leo@demo.com',2,3,'2021-04-22',90000),
('Mia','White','mia@demo.com',3,4,'2019-10-15',82000),
('Noah','Harris','noah@demo.com',4,2,'2023-03-20',68000),
('Olivia','Martin','olivia@demo.com',1,5,'2018-06-30',140000);

-- Categories
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT
);
INSERT INTO categories (name, description) VALUES
('Electronics','Computers, phones, gadgets'),
('Software','SaaS subscriptions and licenses'),
('Services','Consulting and professional services'),
('Hardware','Servers, networking equipment'),
('Accessories','Cables, cases, peripherals');

-- Products
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category_id INT REFERENCES categories(id),
    unit_price NUMERIC(10,2) NOT NULL,
    cost_price NUMERIC(10,2) NOT NULL,
    stock_qty INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO products (name,category_id,unit_price,cost_price,stock_qty) VALUES
('Laptop Pro 15"',1,1299.99,850.00,120),
('Wireless Mouse',5,29.99,12.00,500),
('Cloud Suite License',2,499.00,0.00,9999),
('USB-C Hub',5,59.99,22.00,300),
('4K Monitor 27"',1,449.99,280.00,85),
('Managed Firewall',4,899.00,400.00,40),
('Consulting - 10hrs',3,2500.00,1200.00,9999),
('Keyboard Mechanical',5,89.99,35.00,220),
('Server Rack 42U',4,1850.00,1100.00,15),
('Antivirus Annual',2,79.99,5.00,9999),
('Webcam HD',1,69.99,28.00,180),
('Data Analytics Suite',2,1200.00,0.00,9999),
('Ethernet Switch 24p',4,349.99,180.00,60),
('Standing Desk Mount',5,149.99,65.00,95),
('Security Audit',3,5000.00,2500.00,9999);

-- Customers
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    contact_name VARCHAR(100),
    email VARCHAR(150),
    region_id INT REFERENCES regions(id),
    tier VARCHAR(20) DEFAULT 'standard',
    created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO customers (company_name,contact_name,email,region_id,tier) VALUES
('Acme Corp','John Doe','john@acme.com',1,'enterprise'),
('Beta Industries','Jane Roe','jane@beta.com',2,'premium'),
('Gamma Solutions','Sam Lee','sam@gamma.com',3,'standard'),
('Delta Tech','Pat Kim','pat@delta.com',4,'enterprise'),
('Epsilon Ltd','Alex Fox','alex@epsilon.com',5,'premium'),
('Zeta Group','Morgan Yu','morgan@zeta.com',6,'standard'),
('Eta Systems','Riley Park','riley@eta.com',7,'enterprise'),
('Theta Inc','Jordan Wu','jordan@theta.com',8,'standard'),
('Iota Digital','Casey Ng','casey@iota.com',1,'premium'),
('Kappa Software','Drew Tan','drew@kappa.com',2,'enterprise'),
('Lambda AI','Quinn Roy','quinn@lambda.com',3,'premium'),
('Mu Robotics','Avery Jin','avery@mu.com',4,'standard'),
('Nu Analytics','Blair Cho','blair@nu.com',1,'enterprise'),
('Xi Ventures','Sage Lim','sage@xi.com',5,'standard'),
('Omicron Cloud','Reese Hao','reese@omicron.com',7,'premium');

-- Orders
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    employee_id INT REFERENCES employees(id),
    order_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'completed',
    discount_pct NUMERIC(5,2) DEFAULT 0,
    notes TEXT
);

-- Order Items
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT REFERENCES orders(id) ON DELETE CASCADE,
    product_id INT REFERENCES products(id),
    quantity INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);

-- Generate ~100 orders spread over 2024-2025
INSERT INTO orders (customer_id, employee_id, order_date, status, discount_pct) VALUES
(1,2,'2024-01-08','completed',5),(3,5,'2024-01-15','completed',0),
(2,9,'2024-01-22','completed',10),(5,12,'2024-02-03','completed',0),
(4,2,'2024-02-14','completed',15),(7,5,'2024-02-20','completed',0),
(6,9,'2024-03-01','completed',5),(8,12,'2024-03-10','completed',0),
(10,2,'2024-03-18','completed',0),(1,5,'2024-03-25','completed',10),
(11,9,'2024-04-02','completed',0),(9,12,'2024-04-12','completed',5),
(13,2,'2024-04-19','completed',0),(12,5,'2024-04-28','completed',0),
(14,9,'2024-05-05','completed',10),(15,12,'2024-05-15','completed',0),
(3,2,'2024-05-22','completed',0),(2,5,'2024-06-01','completed',5),
(1,9,'2024-06-10','completed',0),(4,12,'2024-06-18','completed',0),
(7,2,'2024-06-25','completed',15),(6,5,'2024-07-02','completed',0),
(10,9,'2024-07-12','completed',0),(8,12,'2024-07-20','completed',5),
(11,2,'2024-07-28','completed',0),(5,5,'2024-08-05','completed',10),
(9,9,'2024-08-14','completed',0),(13,12,'2024-08-22','completed',0),
(14,2,'2024-08-30','completed',5),(15,5,'2024-09-08','completed',0),
(1,9,'2024-09-16','completed',0),(2,12,'2024-09-24','completed',10),
(3,2,'2024-10-02','completed',0),(4,5,'2024-10-11','completed',0),
(7,9,'2024-10-19','completed',5),(6,12,'2024-10-28','completed',0),
(10,2,'2024-11-05','completed',0),(11,5,'2024-11-14','completed',15),
(8,9,'2024-11-22','completed',0),(5,12,'2024-11-30','completed',0),
(9,2,'2024-12-08','completed',5),(13,5,'2024-12-16','completed',0),
(14,9,'2024-12-24','completed',0),(12,12,'2024-12-31','completed',10),
(1,2,'2025-01-07','completed',0),(3,5,'2025-01-15','completed',5),
(2,9,'2025-01-24','completed',0),(15,12,'2025-02-01','completed',0),
(4,2,'2025-02-10','completed',10),(7,5,'2025-02-18','completed',0),
(6,9,'2025-02-26','completed',5),(10,12,'2025-03-05','completed',0),
(11,2,'2025-03-14','completed',0),(5,5,'2025-03-22','completed',0),
(8,9,'2025-03-30','completed',15),(9,12,'2025-04-07','completed',0),
(1,2,'2025-04-15','completed',5),(13,5,'2025-04-23','completed',0),
(14,9,'2025-05-02','completed',0),(12,12,'2025-05-10','completed',10),
(2,2,'2025-05-19','completed',0),(3,5,'2025-05-27','completed',0),
(4,9,'2025-06-04','completed',5),(15,12,'2025-06-13','completed',0),
(7,2,'2025-06-21','completed',0),(6,5,'2025-06-29','completed',10),
(10,9,'2025-07-08','completed',0),(11,12,'2025-07-16','completed',5),
(5,2,'2025-07-24','completed',0),(8,5,'2025-07-31','completed',0),
(9,9,'2025-08-09','completed',15),(1,12,'2025-08-18','completed',0),
(13,2,'2025-08-26','completed',0),(14,5,'2025-09-03','completed',5),
(12,9,'2025-09-12','completed',0),(2,12,'2025-09-20','completed',0),
(3,2,'2025-09-28','completed',10),(4,5,'2025-10-07','completed',0),
(15,9,'2025-10-15','completed',0),(7,12,'2025-10-24','completed',5),
(6,2,'2025-10-31','completed',0),(10,5,'2025-11-09','completed',0),
(11,9,'2025-11-17','completed',10),(5,12,'2025-11-26','completed',0),
(8,2,'2025-12-04','completed',5),(9,5,'2025-12-12','completed',0),
(1,9,'2025-12-20','pending',0),(13,12,'2025-12-28','pending',0),
(14,2,'2026-01-05','pending',5),(12,5,'2026-01-14','pending',0),
(2,9,'2026-01-22','processing',0),(3,12,'2026-02-01','processing',10),
(4,2,'2026-02-10','processing',0),(15,5,'2026-02-18','shipped',0),
(7,9,'2026-03-01','shipped',5),(6,12,'2026-03-10','shipped',0);

-- Populate order_items (2-4 items per order)
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.id, p.id, (random()*4+1)::int, p.unit_price
FROM orders o
CROSS JOIN LATERAL (
    SELECT id, unit_price FROM products ORDER BY random() LIMIT (random()*2+2)::int
) p;

-- Revenue summary view
CREATE OR REPLACE VIEW monthly_revenue AS
SELECT
    date_trunc('month', o.order_date)::date AS month,
    count(DISTINCT o.id) AS total_orders,
    sum(oi.quantity * oi.unit_price * (1 - o.discount_pct/100)) AS revenue,
    sum(oi.quantity) AS items_sold
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY 1 ORDER BY 1;

-- Top customers view
CREATE OR REPLACE VIEW top_customers AS
SELECT
    c.company_name,
    c.tier,
    r.name AS region,
    count(DISTINCT o.id) AS order_count,
    sum(oi.quantity * oi.unit_price) AS total_spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_items oi ON oi.order_id = o.id
JOIN regions r ON r.id = c.region_id
GROUP BY 1,2,3 ORDER BY 5 DESC;
