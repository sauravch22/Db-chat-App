# SQL Pattern Library — DbChat Few-Shot Pattern Matching

> **108 patterns · 13 categories · Designed for Mistral 7B with reasoning mode**
>
> Each pattern is DB-agnostic: few-shot examples use generic schemas (categories/products/orders),
> and a vocabulary mapper swaps in real table/column names at runtime.

---

## Table of Contents

1. [Architecture: Reasoning Mode + Pattern Matching](#1-architecture-reasoning-mode--pattern-matching)
2. [Pattern Template Format](#2-pattern-template-format)
3. [Category 1 — Basic Retrieval (10 patterns)](#category-1--basic-retrieval)
4. [Category 2 — Compound Filtering (8 patterns)](#category-2--compound-filtering)
5. [Category 3 — Sorting & Ordering (5 patterns)](#category-3--sorting--ordering)
6. [Category 4 — Simple Aggregation (10 patterns)](#category-4--simple-aggregation)
7. [Category 5 — Joins (12 patterns)](#category-5--joins)
8. [Category 6 — Comparison to Aggregate ⚠️ DANGER ZONE (16 patterns)](#category-6--comparison-to-aggregate--danger-zone)
9. [Category 7 — Subquery Patterns (8 patterns)](#category-7--subquery-patterns)
10. [Category 8 — Window Functions (12 patterns)](#category-8--window-functions)
11. [Category 9 — Set Operations (4 patterns)](#category-9--set-operations)
12. [Category 10 — Conditional Logic (6 patterns)](#category-10--conditional-logic)
13. [Category 11 — Date/Time Patterns (7 patterns)](#category-11--datetime-patterns)
14. [Category 12 — String Operations (5 patterns)](#category-12--string-operations)
15. [Category 13 — Advanced Patterns (5 patterns)](#category-13--advanced-patterns)
16. [Pattern Priority Matrix](#pattern-priority-matrix)
17. [Pattern Matching Keywords/Regex](#pattern-matching-keywordsregex)
18. [Validated Test Results](#validated-test-results)

---

## 1. Architecture: Reasoning Mode + Pattern Matching

### Previous Design (reasoning OR few-shot)

```
Pattern matched? → YES → Direct SQL generation with few-shot examples
                 → NO  → Reasoning mode (2-step) as fallback
```

### New Design (reasoning WITH few-shot)

```
User prompt arrives
    ↓
Intent classification → "data"
    ↓
Table selection → schema_context built
    ↓
>>> Pattern classifier runs (regex/keyword, <1ms, no LLM call) <<<
    ↓
┌─ Pattern MATCHED ──────────────────────────────────────┐
│  1. Load few-shot template for that pattern             │
│  2. Fill vocabulary slots from real schema               │
│  3. Inject into Step 2 of reasoning mode                 │
│  4. Run reasoning mode (2-step) WITH few-shot guidance   │
└─────────────────────────────────────────────────────────┘
┌─ Pattern NOT matched ──────────────────────────────────┐
│  1. Run reasoning mode (2-step) WITHOUT few-shot        │
│     (current behavior — generic fallback)                │
└─────────────────────────────────────────────────────────┘
    ↓
Validate SQL → Execute → Error repair if needed
```

### Why Combined Is Better

| Approach | Pros | Cons |
|----------|------|------|
| Reasoning mode alone | Plans correctly | Still generates broken CTE/WITH syntax |
| Few-shot alone | Great syntax guidance | Blind to novel query structures |
| **Combined (new)** | **Reasoning validates approach + few-shot guides exact syntax** | **Slightly more tokens** |

### Integration Point

**File:** `app/services/chat_service.py` ~line 190

**Change in `generate_sql_with_reasoning()`:**
- New optional parameter: `few_shot_block: Optional[str] = None`
- If provided, `sql_prompt` in Step 2 gets the few-shot examples prepended
- Step 1 (reasoning/planning) stays unchanged — it's already generic
- Step 2 benefits from both the reasoning analysis AND the few-shot guidance

---

## 2. Pattern Template Format

Every pattern follows this structure (from validated test files like `test_fewshot_v2_test8.py`):

```
EXAMPLE N: <Natural language description using generic names>

IMPORTANT VOCABULARY:
- "<user phrase>" = <SQL translation> -> use <FUNCTION>()
- "<second phrase>" = <explanation of two-level computation>

Schema:
  <generic_table_1>.<col1>, <generic_table_1>.<col2>
  <generic_table_2>.<col1>, <generic_table_2>.<fk_col>, <generic_table_2>.<measure_col>

Question: <Generic question using generic table names>

SQL:
<Complete, executable SQL using generic schema>

WHY THIS WORKS:
- <Bullet 1: Explains the outer query structure>
- <Bullet 2: Explains the subquery/aggregation approach>
- <Bullet 3: Explains WHY this avoids common Mistral errors>
- <CRITICAL: Explicit anti-pattern warning>
```

**Key Principles:**
- Generic schemas (categories/products, orders/customers) — NOT database-specific
- Vocabulary mapping translates user language to SQL constructs
- "WHY THIS WORKS" teaches the model the reasoning, not just the syntax
- "CRITICAL" lines prevent known Mistral failure modes (broken CTE, scope errors)
- A "BEFORE WRITING — CHECK" checklist is appended with real table/column names

---

## Category 1 — Basic Retrieval

> **10 patterns · LLM risk: LOW · Priority: P3**
>
> Mistral handles these reliably. Included for completeness and edge-case coverage.

### Pattern 1: `simple_select_all`

**Description:** Select all columns from a single table.

**Trigger Keywords:** `show all`, `list all`, `get all`, `give me all`, `display everything`

**Generic Example:**
```sql
SELECT *
FROM products;
```

**WHY THIS WORKS:**
- Single table, no joins, no aggregation
- `SELECT *` returns all columns

---

### Pattern 2: `select_columns`

**Description:** Select specific columns from a table.

**Trigger Keywords:** `show <col> and <col>`, `get the name`, `list names and emails`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.email,
    customers.city
FROM customers;
```

**WHY THIS WORKS:**
- Table-qualified columns avoid ambiguity
- Only references columns from the FROM table

---

### Pattern 3: `select_distinct`

**Description:** Deduplicate results on one or more columns.

**Trigger Keywords:** `unique`, `distinct`, `different`, `all unique`

**Generic Example:**
```sql
SELECT DISTINCT products.category
FROM products;
```

**WHY THIS WORKS:**
- DISTINCT eliminates duplicate rows
- Works on single or multiple columns

---

### Pattern 4: `select_limit`

**Description:** Return only the first N rows (Top-N).

**Trigger Keywords:** `top N`, `first N`, `show N`, `limit to`, `only N`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price
FROM products
ORDER BY products.price DESC
LIMIT 10;
```

**WHY THIS WORKS:**
- ORDER BY defines "top" criteria
- LIMIT truncates result set
- Always pair LIMIT with ORDER BY for deterministic results

---

### Pattern 5: `select_offset`

**Description:** Pagination — skip M rows, return N rows.

**Trigger Keywords:** `page`, `next N`, `skip`, `offset`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price
FROM products
ORDER BY products.product_id
LIMIT 10 OFFSET 20;
```

**WHY THIS WORKS:**
- OFFSET skips rows, LIMIT caps result size
- Stable ORDER BY (usually primary key) ensures consistent paging

---

### Pattern 6: `where_equality`

**Description:** Exact match filter on a column.

**Trigger Keywords:** `where <col> is`, `with <col> equal to`, `for <value>`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    customers.email
FROM customers
WHERE customers.city = 'London';
```

**WHY THIS WORKS:**
- Single equality condition in WHERE
- String literals in single quotes

---

### Pattern 7: `where_inequality`

**Description:** Range filter (greater than, less than, etc.).

**Trigger Keywords:** `more than`, `greater than`, `less than`, `at least`, `over`, `under`, `above`, `below`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price
FROM products
WHERE products.price > 100.00
ORDER BY products.price DESC;
```

**WHY THIS WORKS:**
- Numeric comparison in WHERE
- ORDER BY shows results in meaningful order

---

### Pattern 8: `where_between`

**Description:** Inclusive range filter.

**Trigger Keywords:** `between`, `from X to Y`, `range`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.amount,
    orders.order_date
FROM orders
WHERE orders.amount BETWEEN 50.00 AND 200.00;
```

**WHY THIS WORKS:**
- BETWEEN is inclusive on both ends
- Cleaner than `>= AND <=`

---

### Pattern 9: `where_in_list`

**Description:** Match against multiple values.

**Trigger Keywords:** `in`, `one of`, `either`, `any of these`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.city
FROM customers
WHERE customers.city IN ('London', 'Paris', 'Berlin');
```

**WHY THIS WORKS:**
- IN () is cleaner than multiple OR conditions
- Works with strings, numbers, subqueries

---

### Pattern 10: `where_like`

**Description:** Pattern matching on strings.

**Trigger Keywords:** `like`, `contains`, `starts with`, `ends with`, `matching`, `search for`

**Generic Example:**
```sql
SELECT
    products.name,
    products.description
FROM products
WHERE products.name ILIKE '%wireless%';
```

**WHY THIS WORKS:**
- ILIKE for case-insensitive (PostgreSQL)
- `%` matches any sequence of characters
- `_` matches exactly one character

---

## Category 2 — Compound Filtering

> **8 patterns · LLM risk: LOW-MEDIUM · Priority: P3**
>
> EXISTS and NOT EXISTS can trip up Mistral with scope issues.

### Pattern 11: `where_and_or`

**Description:** Compound conditions with AND/OR and parentheses.

**Trigger Keywords:** `and`, `or`, `either...or`, `both...and`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    products.category
FROM products
WHERE products.category = 'Electronics'
  AND (products.price > 500 OR products.rating >= 4.5);
```

**WHY THIS WORKS:**
- Parentheses enforce precedence: OR is evaluated before AND without them
- Always parenthesize OR groups when combined with AND

---

### Pattern 12: `where_null_check`

**Description:** Filter for NULL or NOT NULL values.

**Trigger Keywords:** `is null`, `is not null`, `missing`, `has no`, `empty`, `not set`, `without`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.phone
FROM customers
WHERE customers.phone IS NOT NULL;
```

**WHY THIS WORKS:**
- `IS NULL` / `IS NOT NULL` — never use `= NULL` (always false)
- NULL is not a value, it's the absence of a value

---

### Pattern 13: `where_not_in`

**Description:** Exclude rows matching a list or subquery.

**Trigger Keywords:** `not in`, `exclude`, `except these`, `other than`

**Generic Example:**
```sql
SELECT
    products.name,
    products.category
FROM products
WHERE products.category NOT IN ('Discontinued', 'Draft');
```

**WHY THIS WORKS:**
- NOT IN inverts the IN condition
- ⚠️ WARNING: NOT IN with NULL values in the list returns no rows — prefer NOT EXISTS

---

### Pattern 14: `where_exists`

**Description:** Include rows where a related record exists.

**Trigger Keywords:** `has at least one`, `who have`, `with orders`, `that have`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name
FROM customers
WHERE EXISTS (
    SELECT 1
    FROM orders
    WHERE orders.customer_id = customers.customer_id
);
```

**WHY THIS WORKS:**
- Correlated subquery: references outer table (`customers.customer_id`)
- SELECT 1 — we don't need actual data, just existence
- More efficient than JOIN when you only need the parent rows

---

### Pattern 15: `where_not_exists`

**Description:** Include rows where NO related record exists (anti-join).

**Trigger Keywords:** `who have no`, `without any`, `never`, `have not`, `no orders`, `missing`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name
FROM customers
WHERE NOT EXISTS (
    SELECT 1
    FROM orders
    WHERE orders.customer_id = customers.customer_id
);
```

**WHY THIS WORKS:**
- Finds customers with ZERO orders
- Safer than `NOT IN` (handles NULLs correctly)
- More efficient than LEFT JOIN + IS NULL for large datasets

---

### Pattern 16: `where_date_range`

**Description:** Filter by date range.

**Trigger Keywords:** `between dates`, `from <date> to <date>`, `in <year>`, `during`, `last year`, `this month`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.order_date,
    orders.amount
FROM orders
WHERE orders.order_date BETWEEN '2024-01-01' AND '2024-12-31';
```

**WHY THIS WORKS:**
- BETWEEN is inclusive on both ends
- Use ISO 8601 date format (YYYY-MM-DD) for portability
- For timestamps, consider using `>= '2024-01-01' AND < '2025-01-01'` to avoid time component issues

---

### Pattern 17: `where_extract`

**Description:** Filter on a date part (year, month, day).

**Trigger Keywords:** `in year`, `in month`, `on day`, `quarterly`, `which year`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.amount
FROM orders
WHERE EXTRACT(YEAR FROM orders.order_date) = 2024
  AND EXTRACT(MONTH FROM orders.order_date) = 6;
```

**WHY THIS WORKS:**
- EXTRACT() pulls numeric date parts
- Standard PostgreSQL — avoid vendor-specific YEAR(), MONTH()
- Can be used in WHERE, SELECT, GROUP BY, ORDER BY

---

### Pattern 18: `where_case_insensitive`

**Description:** Case-insensitive string matching.

**Trigger Keywords:** `case insensitive`, `regardless of case`, `ignoring case`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.email
FROM customers
WHERE customers.name ILIKE '%smith%';
```

**WHY THIS WORKS:**
- PostgreSQL-specific ILIKE is cleaner than LOWER(col) LIKE LOWER(pattern)
- Standard alternative: `WHERE LOWER(customers.name) = LOWER('Smith')`

---

## Category 3 — Sorting & Ordering

> **5 patterns · LLM risk: LOW · Priority: P3**

### Pattern 19: `order_single_asc`

**Description:** Sort results ascending by one column.

**Trigger Keywords:** `sorted by`, `order by`, `alphabetically`, `oldest first`, `lowest first`

**Generic Example:**
```sql
SELECT customers.name, customers.city
FROM customers
ORDER BY customers.name ASC;
```

---

### Pattern 20: `order_single_desc`

**Description:** Sort results descending by one column.

**Trigger Keywords:** `highest first`, `newest first`, `most`, `top`, `largest`, `best`

**Generic Example:**
```sql
SELECT products.name, products.price
FROM products
ORDER BY products.price DESC;
```

---

### Pattern 21: `order_multi_mixed`

**Description:** Multi-column sort with mixed directions.

**Trigger Keywords:** `sort by X then Y`, `order by X descending and Y ascending`

**Generic Example:**
```sql
SELECT
    orders.customer_id,
    orders.order_date,
    orders.amount
FROM orders
ORDER BY orders.customer_id ASC, orders.order_date DESC;
```

---

### Pattern 22: `order_nulls`

**Description:** Control NULL placement in sort.

**Trigger Keywords:** `nulls last`, `nulls first`, `put empty at end`

**Generic Example:**
```sql
SELECT customers.name, customers.phone
FROM customers
ORDER BY customers.phone ASC NULLS LAST;
```

**WHY THIS WORKS:**
- PostgreSQL defaults: ASC → NULLS LAST, DESC → NULLS FIRST
- Explicit NULLS LAST/FIRST overrides default

---

### Pattern 23: `order_by_aggregate`

**Description:** Sort by a computed aggregate value.

**Trigger Keywords:** `most orders first`, `highest total`, `sort by count`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    COUNT(orders.order_id) AS order_count
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY order_count DESC;
```

---

## Category 4 — Simple Aggregation

> **10 patterns · LLM risk: LOW · Priority: P3**
>
> Basic GROUP BY works reliably. Included for edge cases and as building blocks for complex patterns.

### Pattern 24: `count_all`

**Description:** Count total rows in a table.

**Trigger Keywords:** `how many`, `count`, `total number of`, `number of`

**Generic Example:**
```sql
SELECT COUNT(*) AS total_customers
FROM customers;
```

---

### Pattern 25: `count_distinct`

**Description:** Count unique values in a column.

**Trigger Keywords:** `how many unique`, `how many different`, `distinct count`

**Generic Example:**
```sql
SELECT COUNT(DISTINCT orders.customer_id) AS unique_customers
FROM orders;
```

---

### Pattern 26: `sum_column`

**Description:** Sum a numeric column.

**Trigger Keywords:** `total`, `sum`, `combined`, `overall`

**Generic Example:**
```sql
SELECT SUM(orders.amount) AS total_revenue
FROM orders;
```

---

### Pattern 27: `avg_column`

**Description:** Average of a numeric column.

**Trigger Keywords:** `average`, `mean`, `avg`

**Generic Example:**
```sql
SELECT AVG(products.price) AS average_price
FROM products;
```

---

### Pattern 28: `min_max`

**Description:** Min and/or Max of a column.

**Trigger Keywords:** `minimum`, `maximum`, `highest`, `lowest`, `smallest`, `largest`, `cheapest`, `most expensive`

**Generic Example:**
```sql
SELECT
    MIN(products.price) AS cheapest,
    MAX(products.price) AS most_expensive
FROM products;
```

---

### Pattern 29: `group_by_count`

**Description:** Count rows per group.

**Trigger Keywords:** `how many per`, `count by`, `number of X per Y`

**Generic Example:**
```sql
SELECT
    products.category,
    COUNT(*) AS product_count
FROM products
GROUP BY products.category
ORDER BY product_count DESC;
```

---

### Pattern 30: `group_by_sum`

**Description:** Sum a measure per group.

**Trigger Keywords:** `total per`, `sum by`, `revenue per`, `spending per`

**Generic Example:**
```sql
SELECT
    orders.customer_id,
    SUM(orders.amount) AS total_spent
FROM orders
GROUP BY orders.customer_id
ORDER BY total_spent DESC;
```

---

### Pattern 31: `group_by_avg`

**Description:** Average a measure per group.

**Trigger Keywords:** `average per`, `avg by`, `mean per`

**Generic Example:**
```sql
SELECT
    products.category,
    AVG(products.price) AS avg_price
FROM products
GROUP BY products.category
ORDER BY avg_price DESC;
```

---

### Pattern 32: `group_by_multi`

**Description:** Grouping by multiple columns.

**Trigger Keywords:** `per X and Y`, `group by X and Y`, `by category and year`

**Generic Example:**
```sql
SELECT
    orders.customer_id,
    EXTRACT(YEAR FROM orders.order_date) AS order_year,
    SUM(orders.amount) AS yearly_total
FROM orders
GROUP BY orders.customer_id, EXTRACT(YEAR FROM orders.order_date)
ORDER BY orders.customer_id, order_year;
```

---

### Pattern 33: `having_threshold`

**Description:** Filter groups by an aggregate threshold.

**Trigger Keywords:** `having more than`, `with at least`, `where count >`, `only groups with`

**Generic Example:**
```sql
SELECT
    products.category,
    COUNT(*) AS product_count
FROM products
GROUP BY products.category
HAVING COUNT(*) > 5
ORDER BY product_count DESC;
```

**WHY THIS WORKS:**
- HAVING filters AFTER grouping (on aggregates)
- WHERE filters BEFORE grouping (on raw rows)
- Never put aggregate conditions in WHERE

---

## Category 5 — Joins

> **12 patterns · LLM risk: MEDIUM · Priority: P2**
>
> `join_subquery` is a known trouble spot (Test 8 scope issue).
> `self_join_hierarchy` can confuse alias references.

### Pattern 34: `inner_join_2`

**Description:** Join two tables on a foreign key.

**Trigger Keywords:** `with their`, `along with`, `and their`, `show X with Y`

**Generic Example:**
```sql
SELECT
    customers.name,
    orders.order_id,
    orders.amount
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id;
```

---

### Pattern 35: `inner_join_3plus`

**Description:** Multi-hop join across 3 or more tables.

**Trigger Keywords:** queries mentioning entities 3+ tables apart in the schema graph

**Generic Example:**
```sql
SELECT
    customers.name,
    products.name AS product_name,
    order_items.quantity
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
JOIN order_items ON orders.order_id = order_items.order_id
JOIN products ON order_items.product_id = products.product_id;
```

**WHY THIS WORKS:**
- Each JOIN adds one table to the accessible scope
- Join conditions follow the foreign key chain
- All referenced columns are from tables in FROM/JOIN

---

### Pattern 36: `left_join`

**Description:** Include all rows from the left table, even with no match.

**Trigger Keywords:** `all customers even if`, `including those without`, `whether or not they have`

**Generic Example:**
```sql
SELECT
    customers.name,
    COUNT(orders.order_id) AS order_count
FROM customers
LEFT JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY order_count ASC;
```

**WHY THIS WORKS:**
- LEFT JOIN preserves all left-table rows
- Unmatched rows get NULL for right-table columns
- COUNT(orders.order_id) correctly returns 0 for NULL (unlike COUNT(*))

---

### Pattern 37: `left_join_null_filter`

**Description:** Anti-join — find rows with NO matching record in another table.

**Trigger Keywords:** `without any`, `who have no`, `never ordered`, `missing`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name
FROM customers
LEFT JOIN orders ON customers.customer_id = orders.customer_id
WHERE orders.order_id IS NULL;
```

**WHY THIS WORKS:**
- LEFT JOIN + IS NULL on right table's PK = anti-join
- Alternative to NOT EXISTS (sometimes more readable)

---

### Pattern 38: `right_join`

**Description:** Include all rows from the right table.

**Trigger Keywords:** rarely used — same as LEFT JOIN with tables swapped

**Generic Example:**
```sql
SELECT
    orders.order_id,
    customers.name
FROM orders
RIGHT JOIN customers ON orders.customer_id = customers.customer_id;
```

---

### Pattern 39: `full_outer_join`

**Description:** Preserve unmatched rows from both sides.

**Trigger Keywords:** `all from both`, `everything from X and Y`, `combined list including unmatched`

**Generic Example:**
```sql
SELECT
    COALESCE(a.id, b.id) AS id,
    a.value AS left_value,
    b.value AS right_value
FROM table_a AS a
FULL OUTER JOIN table_b AS b ON a.id = b.id;
```

---

### Pattern 40: `cross_join`

**Description:** Cartesian product (every combination).

**Trigger Keywords:** `all combinations`, `every X with every Y`, `pair each`

**Generic Example:**
```sql
SELECT
    colors.name AS color,
    sizes.name AS size
FROM colors
CROSS JOIN sizes;
```

---

### Pattern 41: `self_join`

**Description:** Join a table to itself.

**Trigger Keywords:** `compared to each other`, `pairs of`, `X vs other X`

**Generic Example:**
```sql
SELECT
    a.name AS product_a,
    b.name AS product_b,
    a.price - b.price AS price_diff
FROM products AS a
JOIN products AS b ON a.category = b.category AND a.product_id < b.product_id;
```

**WHY THIS WORKS:**
- Different aliases (a, b) distinguish the two copies
- `a.product_id < b.product_id` avoids duplicate pairs and self-pairs

---

### Pattern 42: `self_join_hierarchy`

**Description:** Parent-child hierarchy in the same table (e.g., employee → manager).

**Trigger Keywords:** `manager`, `reports to`, `parent`, `supervisor`, `hierarchy`

**Generic Example:**
```sql
SELECT
    e.name AS employee_name,
    mgr.name AS manager_name
FROM employees AS e
LEFT JOIN employees AS mgr ON e.reports_to = mgr.employee_id;
```

**WHY THIS WORKS:**
- Two aliases for the same table: `e` (employee) and `mgr` (manager)
- LEFT JOIN because some employees may have no manager (CEO)
- Join condition: child's FK → parent's PK

---

### Pattern 43: `join_subquery`

**Description:** Join to a derived table (subquery in FROM).

**Trigger Keywords:** implicitly used when pre-aggregation is needed before joining

**Generic Example:**
```sql
SELECT
    customers.name,
    order_totals.total_amount
FROM customers
JOIN (
    SELECT
        orders.customer_id,
        SUM(orders.amount) AS total_amount
    FROM orders
    GROUP BY orders.customer_id
) AS order_totals ON customers.customer_id = order_totals.customer_id
WHERE order_totals.total_amount > 1000;
```

**WHY THIS WORKS:**
- Subquery pre-aggregates before joining
- Join key (`customer_id`) MUST be in subquery's SELECT list
- CRITICAL: After joining a subquery, only reference columns FROM that subquery alias — never the original table unless it's also in FROM/JOIN
- This is where Test 8 originally failed: referencing `track.milliseconds` in HAVING when `track` was only inside the subquery

---

### Pattern 44: `join_composite_key`

**Description:** Join on multiple columns.

**Trigger Keywords:** composite foreign keys, multi-column relationships

**Generic Example:**
```sql
SELECT
    enrollments.student_id,
    grades.score
FROM enrollments
JOIN grades ON enrollments.student_id = grades.student_id
          AND enrollments.course_id = grades.course_id;
```

---

### Pattern 45: `join_with_aggregation`

**Description:** Join tables then aggregate.

**Trigger Keywords:** `total X per Y`, `count of X for each Y`

**Generic Example:**
```sql
SELECT
    customers.name,
    SUM(orders.amount) AS total_spent,
    COUNT(orders.order_id) AS order_count
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY total_spent DESC;
```

---

## Category 6 — Comparison to Aggregate ⚠️ DANGER ZONE

> **16 patterns · LLM risk: VERY HIGH · Priority: P0 (CRITICAL)**
>
> This is where Mistral 7B breaks most often: broken CTE/WITH syntax, nested aggregates,
> scope errors. Every pattern here gets a FULL few-shot example with vocabulary mapping,
> "WHY THIS WORKS", and anti-pattern warnings.
>
> **All 15 passing tests validate patterns in this category.**

### Pattern 46: `agg_vs_global_avg_sum` ✅ VALIDATED

**Description:** SUM per entity vs AVG of those SUMs globally.

**Tested in:** Tests 2, 6, 8, 10, 13

**Trigger Keywords:** `total spending more than average`, `total revenue above average`, `sum greater than avg`, `spent more than average`

**IMPORTANT VOCABULARY:**
- "total spending" = SUM of all amounts → use SUM()
- "average spending" = AVG of per-entity totals → AVG() on pre-grouped SUMs
- These require TWO levels: first SUM per entity, then AVG of those sums

**Generic Example:**
```
Schema:
  categories.category_id, categories.name
  products.product_id, products.category_id, products.weight

Question: Find categories whose total product weight is greater than the average category weight.

SQL:
SELECT
    categories.category_id,
    categories.name,
    SUM(products.weight) AS total_weight
FROM categories
JOIN products ON categories.category_id = products.category_id
GROUP BY categories.category_id, categories.name
HAVING SUM(products.weight) > (
    SELECT AVG(cat_weight)
    FROM (
        SELECT SUM(products.weight) AS cat_weight
        FROM products
        GROUP BY products.category_id
    ) sub
)
ORDER BY total_weight DESC;
```

**WHY THIS WORKS:**
- Outer query directly JOINs categories to products (NOT via subquery)
- SUM(products.weight) per category in outer GROUP BY
- Inner subquery computes SUM per category independently
- AVG wraps those sums — computes ONCE, not per row
- HAVING filters after grouping
- CRITICAL: Do NOT join a subquery and then reference the original table
- No CTE needed — nested subquery in HAVING is clean

---

### Pattern 47: `agg_vs_global_avg_count` ✅ VALIDATED

**Description:** COUNT per entity vs AVG of those COUNTs globally.

**Tested in:** Tests 11, 15, 19

**Trigger Keywords:** `more tracks than average`, `more customers than average`, `count above average`

**IMPORTANT VOCABULARY:**
- "number of tracks per artist" = COUNT(track_id) grouped by artist
- "average tracks per artist" = AVG of per-artist COUNTs

**Generic Example:**
```
Schema:
  departments.dept_id, departments.name
  employees.emp_id, employees.dept_id, employees.name

Question: Find departments with more employees than the average department.

SQL:
SELECT
    departments.dept_id,
    departments.name,
    COUNT(employees.emp_id) AS emp_count
FROM departments
JOIN employees ON departments.dept_id = employees.dept_id
GROUP BY departments.dept_id, departments.name
HAVING COUNT(employees.emp_id) > (
    SELECT AVG(dept_count)
    FROM (
        SELECT COUNT(employees.emp_id) AS dept_count
        FROM employees
        GROUP BY employees.dept_id
    ) sub
)
ORDER BY emp_count DESC;
```

**WHY THIS WORKS:**
- Identical structure to Pattern 46, but COUNT instead of SUM
- HAVING COUNT() > (SELECT AVG(x) FROM (SELECT COUNT() GROUP BY) sub)

---

### Pattern 48: `agg_vs_global_avg_max` ✅ VALIDATED

**Description:** MAX per entity vs AVG of those MAXes globally.

**Tested in:** Test 12

**Trigger Keywords:** `longest track more than average longest`, `highest value above average maximum`

**IMPORTANT VOCABULARY:**
- "longest track per artist" = MAX(duration) grouped by artist
- "average of longest tracks" = AVG of per-artist MAX values

**Generic Example:**
```
Schema:
  categories.category_id, categories.name
  products.product_id, products.category_id, products.weight

Question: Find categories whose heaviest product is heavier than the average heaviest product across all categories.

SQL:
SELECT
    categories.category_id,
    categories.name,
    MAX(products.weight) AS heaviest
FROM categories
JOIN products ON categories.category_id = products.category_id
GROUP BY categories.category_id, categories.name
HAVING MAX(products.weight) > (
    SELECT AVG(max_weight)
    FROM (
        SELECT MAX(products.weight) AS max_weight
        FROM products
        GROUP BY products.category_id
    ) sub
)
ORDER BY heaviest DESC;
```

---

### Pattern 49: `agg_vs_global_avg_min`

**Description:** MIN per entity vs AVG of those MINs globally.

**Trigger Keywords:** `cheapest product below average cheapest`, `minimum value less than average minimum`

**Generic Example:**
```
Same structure as Pattern 48, with MIN instead of MAX.

SQL:
SELECT
    categories.category_id,
    categories.name,
    MIN(products.price) AS cheapest
FROM categories
JOIN products ON categories.category_id = products.category_id
GROUP BY categories.category_id, categories.name
HAVING MIN(products.price) < (
    SELECT AVG(min_price)
    FROM (
        SELECT MIN(products.price) AS min_price
        FROM products
        GROUP BY products.category_id
    ) sub
)
ORDER BY cheapest ASC;
```

---

### Pattern 50: `value_vs_group_avg` ✅ VALIDATED

**Description:** Individual row value compared to its group's average (correlated subquery).

**Tested in:** Tests 7, 9

**Trigger Keywords:** `track longer than average in its album`, `price higher than average in genre`, `above their group average`

**IMPORTANT VOCABULARY:**
- "longer than average in its album" = row value > correlated subquery AVG for same group
- This is a per-ROW comparison, NOT per-group

**Generic Example:**
```
Schema:
  categories.category_id, categories.name
  products.product_id, products.category_id, products.name, products.price

Question: Find products whose price is higher than the average price in their category.

SQL:
SELECT
    products.product_id,
    products.name,
    products.price,
    categories.name AS category_name
FROM products
JOIN categories ON products.category_id = categories.category_id
WHERE products.price > (
    SELECT AVG(p2.price)
    FROM products AS p2
    WHERE p2.category_id = products.category_id
)
ORDER BY products.price DESC;
```

**WHY THIS WORKS:**
- Correlated subquery: `WHERE p2.category_id = products.category_id` scopes to same group
- Self-reference via alias (p2) to avoid ambiguity
- WHERE (not HAVING) because this is a row-level comparison
- No GROUP BY in outer query — each row compared individually

---

### Pattern 51: `latest_vs_own_avg` ✅ VALIDATED

**Description:** Most recent value compared to entity's own average.

**Tested in:** Test 1

**Trigger Keywords:** `latest invoice more than average`, `most recent order vs their average`, `last purchase above their mean`

**IMPORTANT VOCABULARY:**
- "latest invoice" = correlated subquery ORDER BY date DESC LIMIT 1
- "average invoice" = AVG() for same customer via correlated subquery

**Generic Example:**
```
Schema:
  customers.customer_id, customers.name
  orders.order_id, orders.customer_id, orders.amount, orders.order_date

Question: Find customers whose latest order amount is higher than their average order amount.

SQL:
SELECT
    customers.customer_id,
    customers.name
FROM customers
WHERE (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date DESC
    LIMIT 1
) > (
    SELECT AVG(orders.amount)
    FROM orders
    WHERE orders.customer_id = customers.customer_id
);
```

**WHY THIS WORKS:**
- Two correlated subqueries in WHERE, both scoped to `customers.customer_id`
- First subquery: ORDER BY date DESC LIMIT 1 → "latest"
- Second subquery: AVG() → "average"
- Compared with `>` directly in WHERE
- No GROUP BY needed — each customer row evaluated independently

---

### Pattern 52: `first_vs_last` ✅ VALIDATED

**Description:** Compare first and last values per entity.

**Tested in:** Test 5

**Trigger Keywords:** `first order vs last order`, `earliest vs latest`, `first invoice less than last`

**Generic Example:**
```
Schema:
  customers.customer_id, customers.name
  orders.order_id, orders.customer_id, orders.amount, orders.order_date

Question: Find customers whose first order amount is less than their last order amount.

SQL:
SELECT
    customers.customer_id,
    customers.name
FROM customers
WHERE (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date ASC
    LIMIT 1
) < (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date DESC
    LIMIT 1
);
```

**WHY THIS WORKS:**
- Two correlated subqueries: ASC LIMIT 1 = "first", DESC LIMIT 1 = "last"
- Comparison operator (`<`) between the two scalar subqueries
- Both correlated to `customers.customer_id`

---

### Pattern 53: `yoy_comparison` ✅ VALIDATED

**Description:** Year-over-year comparison using conditional aggregation.

**Tested in:** Test 3

**Trigger Keywords:** `this year vs last year`, `2024 vs 2023`, `year over year`, `YoY`, `annual comparison`

**IMPORTANT VOCABULARY:**
- "spending in 2024" = SUM(CASE WHEN EXTRACT(YEAR) = 2024 THEN amount ELSE 0 END)
- "year-over-year" = conditional aggregation with CASE WHEN on EXTRACT(YEAR)

**Generic Example:**
```
Schema:
  customers.customer_id, customers.name
  orders.order_id, orders.customer_id, orders.amount, orders.order_date

Question: Find customers who spent more in 2024 than in 2023.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024 THEN orders.amount ELSE 0 END) AS spending_2024,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2023 THEN orders.amount ELSE 0 END) AS spending_2023
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024 THEN orders.amount ELSE 0 END)
     > SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2023 THEN orders.amount ELSE 0 END);
```

**WHY THIS WORKS:**
- CASE WHEN EXTRACT(YEAR) partitions amounts by year within the same query
- No self-join or CTE needed — single pass with conditional aggregation
- HAVING compares the two conditional SUMs
- ELSE 0 ensures clean numeric comparison

---

### Pattern 54: `mom_comparison`

**Description:** Month-over-month comparison.

**Trigger Keywords:** `this month vs last month`, `month over month`, `MoM`, `monthly comparison`

**Generic Example:**
```
Same structure as Pattern 53 but with EXTRACT(MONTH) and EXTRACT(YEAR):

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024
              AND EXTRACT(MONTH FROM orders.order_date) = 6 THEN orders.amount ELSE 0 END) AS jun_2024,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024
              AND EXTRACT(MONTH FROM orders.order_date) = 5 THEN orders.amount ELSE 0 END) AS may_2024
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024
                  AND EXTRACT(MONTH FROM orders.order_date) = 6 THEN orders.amount ELSE 0 END)
     > SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024
                  AND EXTRACT(MONTH FROM orders.order_date) = 5 THEN orders.amount ELSE 0 END);
```

---

### Pattern 55: `max_vs_multiple_of_min` ✅ VALIDATED

**Description:** MAX of a column ≥ N × MIN of that column per entity.

**Tested in:** Test 4

**Trigger Keywords:** `max is at least twice the min`, `largest is N times the smallest`, `range ratio`

**Generic Example:**
```
Schema:
  customers.customer_id, customers.name
  orders.order_id, orders.customer_id, orders.amount

Question: Find customers whose most expensive order is at least 2x their cheapest order.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    MAX(orders.amount) AS max_order,
    MIN(orders.amount) AS min_order
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING MAX(orders.amount) >= 2 * MIN(orders.amount);
```

**WHY THIS WORKS:**
- Simple HAVING with two aggregate functions
- No subquery needed — both MAX and MIN computed in same GROUP BY
- The multiplier (2) is a literal constant in HAVING

---

### Pattern 56: `entity_agg_vs_fixed_percentile`

**Description:** Entity aggregate compared to a percentile value.

**Trigger Keywords:** `above the 75th percentile`, `top quartile`, `above median`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spent
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING SUM(orders.amount) > (
    SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY customer_total)
    FROM (
        SELECT SUM(orders.amount) AS customer_total
        FROM orders
        GROUP BY orders.customer_id
    ) sub
)
ORDER BY total_spent DESC;
```

**WHY THIS WORKS:**
- PERCENTILE_CONT(0.75) computes the 75th percentile of per-customer totals
- Same nested subquery structure as Pattern 46
- WITHIN GROUP (ORDER BY ...) is required PostgreSQL syntax for ordered-set aggregates

---

### Pattern 57: `multi_hop_agg_vs_avg` ✅ VALIDATED

**Description:** 3+ table join chain → aggregate per entity → compare to AVG.

**Tested in:** Test 10

**Trigger Keywords:** `artist revenue above average` (requires artist→album→track→invoice_line→invoice chain)

**Generic Example:**
```
Schema:
  departments.dept_id, departments.name
  teams.team_id, teams.dept_id, teams.name
  employees.emp_id, employees.team_id, employees.salary

Question: Find departments whose total employee salary exceeds the average department salary.

SQL:
SELECT
    departments.dept_id,
    departments.name,
    SUM(employees.salary) AS total_salary
FROM departments
JOIN teams ON departments.dept_id = teams.dept_id
JOIN employees ON teams.team_id = employees.team_id
GROUP BY departments.dept_id, departments.name
HAVING SUM(employees.salary) > (
    SELECT AVG(dept_salary)
    FROM (
        SELECT SUM(employees.salary) AS dept_salary
        FROM departments AS d2
        JOIN teams AS t2 ON d2.dept_id = t2.dept_id
        JOIN employees AS e2 ON t2.team_id = e2.team_id
        GROUP BY d2.dept_id
    ) sub
)
ORDER BY total_salary DESC;
```

**WHY THIS WORKS:**
- Multi-hop join chain in both outer and inner queries
- Inner subquery reproduces the FULL join chain (not just the leaf table)
- Group by the root entity (department) in both queries
- CRITICAL: Inner subquery must use different aliases to avoid ambiguity

---

### Pattern 58: `per_group_max_vs_global_avg`

**Description:** Per-group MAX compared to global AVG.

**Trigger Keywords:** `country's highest invoice above global average`, `group maximum vs overall average`

**Generic Example:**
```sql
SELECT
    orders.region,
    MAX(orders.amount) AS highest_order
FROM orders
GROUP BY orders.region
HAVING MAX(orders.amount) > (
    SELECT AVG(orders.amount)
    FROM orders
);
```

**WHY THIS WORKS:**
- Outer: MAX per group
- Inner: simple scalar AVG over entire table (no nesting needed)
- Simpler than Pattern 46 because the comparison is MAX vs flat AVG (not AVG of aggregates)

---

### Pattern 59: `top_n_by_aggregate`

**Description:** Top N entities ranked by an aggregate.

**Trigger Keywords:** `top 5 customers by spending`, `3 best selling products`, `highest revenue`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spent
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY total_spent DESC
LIMIT 5;
```

---

### Pattern 60: `bottom_n_by_aggregate`

**Description:** Bottom N entities by an aggregate.

**Trigger Keywords:** `bottom 5`, `least`, `worst performing`, `lowest revenue`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spent
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY total_spent ASC
LIMIT 5;
```

---

### Pattern 61: `agg_ratio_comparison`

**Description:** Ratio of two aggregates exceeds a threshold.

**Trigger Keywords:** `average order value`, `revenue per customer`, `ratio of X to Y`

**Generic Example:**
```sql
SELECT
    products.category,
    SUM(order_items.amount) AS total_revenue,
    COUNT(DISTINCT order_items.order_id) AS order_count,
    SUM(order_items.amount) / NULLIF(COUNT(DISTINCT order_items.order_id), 0) AS avg_order_value
FROM products
JOIN order_items ON products.product_id = order_items.product_id
GROUP BY products.category
HAVING SUM(order_items.amount) / NULLIF(COUNT(DISTINCT order_items.order_id), 0) > 100;
```

**WHY THIS WORKS:**
- NULLIF prevents division by zero
- Ratio computed in both SELECT (for display) and HAVING (for filtering)

---

## Category 7 — Subquery Patterns

> **8 patterns · LLM risk: HIGH · Priority: P1**
>
> Correlated subqueries and nested subqueries are fragile for Mistral.
> These patterns support Category 6 as building blocks.

### Pattern 62: `scalar_subquery_select`

**Description:** Computed column via correlated subquery in SELECT.

**Trigger Keywords:** `show each X with their total Y`, `add a column showing`

**Generic Example:**
```sql
SELECT
    customers.customer_id,
    customers.name,
    (SELECT COUNT(orders.order_id)
     FROM orders
     WHERE orders.customer_id = customers.customer_id) AS order_count
FROM customers;
```

**WHY THIS WORKS:**
- Subquery in SELECT returns a single scalar value per row
- Correlated via `customers.customer_id`
- Executes once per row in outer query

---

### Pattern 63: `scalar_subquery_where`

**Description:** Compare a column to a scalar (non-correlated) subquery.

**Trigger Keywords:** `above the overall average`, `more than the total`, `exceeds the global`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price
FROM products
WHERE products.price > (
    SELECT AVG(products.price)
    FROM products
);
```

**WHY THIS WORKS:**
- Inner subquery is NOT correlated — runs once, returns one number
- Outer WHERE compares each row to that single value

---

### Pattern 64: `correlated_subquery`

**Description:** Subquery that references the outer query (per-row evaluation).

**Trigger Keywords:** `in their own group`, `within their category`, `compared to their peers`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    products.category
FROM products
WHERE products.price > (
    SELECT AVG(p2.price)
    FROM products AS p2
    WHERE p2.category = products.category
);
```

**WHY THIS WORKS:**
- `p2.category = products.category` correlates inner to outer
- Use alias `p2` to distinguish inner from outer reference
- Evaluates once per outer row

---

### Pattern 65: `subquery_in`

**Description:** Filter rows where a value is IN a subquery result set.

**Trigger Keywords:** `who have ordered`, `that appear in`, `who are in the list of`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.email
FROM customers
WHERE customers.customer_id IN (
    SELECT orders.customer_id
    FROM orders
    WHERE orders.amount > 1000
);
```

---

### Pattern 66: `subquery_not_in`

**Description:** Filter rows where a value is NOT IN a subquery result set.

**Trigger Keywords:** `who have NOT ordered`, `that don't appear in`, `excluding those who`

**Generic Example:**
```sql
SELECT
    customers.name,
    customers.email
FROM customers
WHERE customers.customer_id NOT IN (
    SELECT orders.customer_id
    FROM orders
    WHERE orders.customer_id IS NOT NULL
);
```

**WHY THIS WORKS:**
- ⚠️ CRITICAL: Add `IS NOT NULL` filter in subquery to avoid NULL trap
- If subquery returns any NULL, NOT IN returns zero rows
- Safer alternative: use NOT EXISTS (Pattern 15)

---

### Pattern 67: `subquery_exists`

**Description:** EXISTS with correlated subquery (same as Pattern 14, included here for subquery completeness).

**Generic Example:**
```sql
SELECT customers.name
FROM customers
WHERE EXISTS (
    SELECT 1
    FROM orders
    WHERE orders.customer_id = customers.customer_id
      AND orders.amount > 500
);
```

---

### Pattern 68: `derived_table_from`

**Description:** Subquery used as a derived table in FROM.

**Trigger Keywords:** implicitly used when pre-aggregation feeds into further computation

**Generic Example:**
```sql
SELECT
    sub.customer_id,
    sub.total_spent,
    sub.total_spent - (SELECT AVG(s2.total_spent)
                       FROM (SELECT SUM(orders.amount) AS total_spent
                             FROM orders GROUP BY orders.customer_id) AS s2) AS diff_from_avg
FROM (
    SELECT
        orders.customer_id,
        SUM(orders.amount) AS total_spent
    FROM orders
    GROUP BY orders.customer_id
) AS sub
ORDER BY sub.total_spent DESC;
```

---

### Pattern 69: `nested_subquery`

**Description:** Subquery inside a subquery (typically AVG of SUMs pattern).

**Trigger Keywords:** `average of totals`, `mean of the sums`, `avg of per-entity aggregates`

**Generic Example:**
```sql
-- This is the innermost pattern used in HAVING across Category 6

HAVING SUM(products.weight) > (
    SELECT AVG(cat_weight)           -- Level 2: AVG over grouped sums
    FROM (
        SELECT SUM(products.weight) AS cat_weight   -- Level 1: SUM per group
        FROM products
        GROUP BY products.category_id
    ) sub
)
```

**WHY THIS WORKS:**
- Level 1 (innermost): Aggregate per group → produces one row per group
- Level 2 (middle): AVG over those rows → produces one scalar
- Level 3 (outer HAVING): Compares outer aggregate to that scalar
- This 3-level nesting is the CORE of all Pattern 46-48 templates

---

## Category 8 — Window Functions

> **12 patterns · LLM risk: MEDIUM-HIGH · Priority: P1**
>
> Mistral sometimes botches PARTITION BY scope or window frame clauses.
> Few-shot examples critical for patterns 71, 75-79, 81.

### Pattern 70: `row_number`

**Description:** Assign sequential numbers to rows.

**Trigger Keywords:** `number the rows`, `row number`, `sequential`

**Generic Example:**
```sql
SELECT
    ROW_NUMBER() OVER (ORDER BY products.price DESC) AS rank,
    products.name,
    products.price
FROM products;
```

---

### Pattern 71: `row_number_partition`

**Description:** Per-group row numbering (critical for top-N-per-group).

**Trigger Keywords:** `number within each group`, `rank within category`, `per-group numbering`

**Generic Example:**
```sql
SELECT
    products.category,
    products.name,
    products.price,
    ROW_NUMBER() OVER (
        PARTITION BY products.category
        ORDER BY products.price DESC
    ) AS rank_in_category
FROM products;
```

**WHY THIS WORKS:**
- PARTITION BY restarts numbering for each group
- ORDER BY within the window determines ranking order
- Combined with Pattern 81 (WHERE rn <= N) for top-N-per-group

---

### Pattern 72: `rank`

**Description:** Rank with gaps (tied rows get same rank, next rank skips).

**Trigger Keywords:** `rank`, `ranking with gaps`, `position`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    RANK() OVER (ORDER BY products.price DESC) AS price_rank
FROM products;
```

---

### Pattern 73: `dense_rank`

**Description:** Rank without gaps (tied rows get same rank, next rank is +1).

**Trigger Keywords:** `dense rank`, `ranking without gaps`, `consecutive ranking`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    DENSE_RANK() OVER (ORDER BY products.price DESC) AS price_rank
FROM products;
```

---

### Pattern 74: `ntile`

**Description:** Distribute rows into N equal buckets.

**Trigger Keywords:** `quartile`, `decile`, `bucket`, `divide into N groups`, `percentile bucket`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    NTILE(4) OVER (ORDER BY products.price) AS price_quartile
FROM products;
```

---

### Pattern 75: `lag`

**Description:** Access the previous row's value.

**Trigger Keywords:** `previous`, `prior`, `compared to last`, `change from previous`

**Generic Example:**
```sql
SELECT
    orders.order_date,
    orders.amount,
    LAG(orders.amount, 1) OVER (ORDER BY orders.order_date) AS prev_amount,
    orders.amount - LAG(orders.amount, 1) OVER (ORDER BY orders.order_date) AS change
FROM orders;
```

**WHY THIS WORKS:**
- LAG(col, N) looks back N rows in the window
- First row gets NULL (no previous row)
- ORDER BY in OVER defines "previous"

---

### Pattern 76: `lead`

**Description:** Access the next row's value.

**Trigger Keywords:** `next`, `following`, `upcoming`

**Generic Example:**
```sql
SELECT
    orders.order_date,
    orders.amount,
    LEAD(orders.amount, 1) OVER (ORDER BY orders.order_date) AS next_amount
FROM orders;
```

---

### Pattern 77: `running_total`

**Description:** Cumulative sum.

**Trigger Keywords:** `running total`, `cumulative sum`, `progressive total`, `year-to-date`

**Generic Example:**
```sql
SELECT
    orders.order_date,
    orders.amount,
    SUM(orders.amount) OVER (
        ORDER BY orders.order_date
        ROWS UNBOUNDED PRECEDING
    ) AS running_total
FROM orders;
```

**WHY THIS WORKS:**
- `ROWS UNBOUNDED PRECEDING` = from first row to current row
- Without frame clause, PostgreSQL defaults to `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`
- Explicit `ROWS` is recommended for clarity and correctness with duplicates

---

### Pattern 78: `running_avg`

**Description:** Cumulative average.

**Trigger Keywords:** `running average`, `cumulative average`, `progressive mean`

**Generic Example:**
```sql
SELECT
    orders.order_date,
    orders.amount,
    AVG(orders.amount) OVER (
        ORDER BY orders.order_date
        ROWS UNBOUNDED PRECEDING
    ) AS running_avg
FROM orders;
```

---

### Pattern 79: `moving_avg`

**Description:** Sliding window average (e.g., 3-period moving average).

**Trigger Keywords:** `moving average`, `sliding window`, `3-day average`, `rolling average`

**Generic Example:**
```sql
SELECT
    orders.order_date,
    orders.amount,
    AVG(orders.amount) OVER (
        ORDER BY orders.order_date
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) AS moving_avg_3
FROM orders;
```

**WHY THIS WORKS:**
- `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` = 3-row window
- First two rows have smaller windows (1 and 2 rows respectively)
- ROWS (not RANGE) ensures physical row-based window

---

### Pattern 80: `first_last_value`

**Description:** First or last value in a window partition.

**Trigger Keywords:** `first order in each group`, `last sale per region`, `opening/closing value`

**Generic Example:**
```sql
SELECT
    orders.customer_id,
    orders.order_date,
    orders.amount,
    FIRST_VALUE(orders.amount) OVER (
        PARTITION BY orders.customer_id
        ORDER BY orders.order_date
    ) AS first_order_amount,
    LAST_VALUE(orders.amount) OVER (
        PARTITION BY orders.customer_id
        ORDER BY orders.order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS last_order_amount
FROM orders;
```

**WHY THIS WORKS:**
- FIRST_VALUE with default frame works correctly
- LAST_VALUE requires explicit `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`
- Without it, LAST_VALUE only sees up to current row (default frame)

---

### Pattern 81: `top_n_per_group`

**Description:** Top N rows within each group.

**Trigger Keywords:** `top 3 per category`, `best 5 in each group`, `most expensive per genre`

**Generic Example:**
```sql
SELECT sub.category, sub.name, sub.price
FROM (
    SELECT
        products.category,
        products.name,
        products.price,
        ROW_NUMBER() OVER (
            PARTITION BY products.category
            ORDER BY products.price DESC
        ) AS rn
    FROM products
) AS sub
WHERE sub.rn <= 3
ORDER BY sub.category, sub.price DESC;
```

**WHY THIS WORKS:**
- ROW_NUMBER() in subquery assigns per-group ranking
- Outer WHERE filters to top N
- Cannot put WHERE rn <= 3 in same query as window function (window runs after WHERE)
- Must wrap in subquery/CTE first

---

## Category 9 — Set Operations

> **4 patterns · LLM risk: LOW · Priority: P3**

### Pattern 82: `union`

**Description:** Combine results from two queries, removing duplicates.

**Trigger Keywords:** `combine`, `merge`, `together`, `both X and Y`

**Generic Example:**
```sql
SELECT customers.name, 'Customer' AS type FROM customers
UNION
SELECT suppliers.name, 'Supplier' AS type FROM suppliers;
```

**WHY THIS WORKS:**
- UNION removes duplicate rows
- Both SELECTs must have the same number and compatible types of columns

---

### Pattern 83: `union_all`

**Description:** Combine results without deduplication.

**Trigger Keywords:** `all results from both`, `including duplicates`

**Generic Example:**
```sql
SELECT orders.order_date, orders.amount, 'Online' AS channel FROM online_orders
UNION ALL
SELECT orders.order_date, orders.amount, 'Store' AS channel FROM store_orders;
```

---

### Pattern 84: `intersect`

**Description:** Only rows that appear in both result sets.

**Trigger Keywords:** `in common`, `overlap`, `both A and B`, `appear in both`

**Generic Example:**
```sql
SELECT customers.customer_id FROM online_customers
INTERSECT
SELECT customers.customer_id FROM store_customers;
```

---

### Pattern 85: `except`

**Description:** Rows in first set that are NOT in second set.

**Trigger Keywords:** `in A but not B`, `only in`, `exclusive to`, `minus`

**Generic Example:**
```sql
SELECT customers.customer_id FROM all_customers
EXCEPT
SELECT customers.customer_id FROM premium_customers;
```

---

## Category 10 — Conditional Logic

> **6 patterns · LLM risk: MEDIUM · Priority: P2**
>
> Conditional aggregation (Pattern 88) is the building block for YoY/MoM comparisons.

### Pattern 86: `case_simple`

**Description:** Simple CASE expression (value mapping).

**Trigger Keywords:** `map X to Y`, `convert status codes`, `translate values`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    CASE orders.status
        WHEN 'P' THEN 'Pending'
        WHEN 'S' THEN 'Shipped'
        WHEN 'D' THEN 'Delivered'
        ELSE 'Unknown'
    END AS status_label
FROM orders;
```

---

### Pattern 87: `case_searched`

**Description:** Searched CASE expression (condition-based).

**Trigger Keywords:** `if greater than`, `categorize by`, `classify`, `bucket`

**Generic Example:**
```sql
SELECT
    products.name,
    products.price,
    CASE
        WHEN products.price > 100 THEN 'Premium'
        WHEN products.price > 50 THEN 'Mid-Range'
        ELSE 'Budget'
    END AS price_tier
FROM products;
```

---

### Pattern 88: `conditional_aggregation` ✅ VALIDATED (via Pattern 53)

**Description:** Aggregate using CASE to split by condition (pivot-like).

**Tested in:** Test 3 (YoY comparison)

**Trigger Keywords:** `revenue by year in columns`, `compare this year vs last year`, `pivot`

**Generic Example:**
```sql
SELECT
    products.category,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2024 THEN orders.amount ELSE 0 END) AS revenue_2024,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2023 THEN orders.amount ELSE 0 END) AS revenue_2023,
    COUNT(CASE WHEN orders.status = 'Returned' THEN 1 END) AS return_count
FROM products
JOIN order_items ON products.product_id = order_items.product_id
JOIN orders ON order_items.order_id = orders.order_id
GROUP BY products.category;
```

**WHY THIS WORKS:**
- CASE inside SUM/COUNT acts as conditional filter per aggregate
- ELSE 0 for SUM ensures clean addition
- For COUNT, omit ELSE (NULL values aren't counted)

---

### Pattern 89: `coalesce`

**Description:** Replace NULL with a default value.

**Trigger Keywords:** `default to`, `if null then`, `fallback`, `replace null`

**Generic Example:**
```sql
SELECT
    customers.name,
    COALESCE(customers.phone, 'No phone') AS phone,
    COALESCE(customers.discount, 0) AS discount
FROM customers;
```

---

### Pattern 90: `nullif`

**Description:** Return NULL if two values are equal (commonly used to prevent division by zero).

**Trigger Keywords:** `avoid division by zero`, `safe divide`, `ratio`

**Generic Example:**
```sql
SELECT
    departments.name,
    departments.budget / NULLIF(departments.employee_count, 0) AS budget_per_employee
FROM departments;
```

**WHY THIS WORKS:**
- NULLIF(x, 0) returns NULL when x = 0
- Division by NULL returns NULL (not an error)
- Wrap in COALESCE for a default: `COALESCE(budget / NULLIF(count, 0), 0)`

---

### Pattern 91: `case_bucketing`

**Description:** Range-based categorization.

**Trigger Keywords:** `group by range`, `age groups`, `size categories`, `tier`

**Generic Example:**
```sql
SELECT
    CASE
        WHEN customers.total_purchases < 100 THEN 'Bronze'
        WHEN customers.total_purchases < 500 THEN 'Silver'
        WHEN customers.total_purchases < 1000 THEN 'Gold'
        ELSE 'Platinum'
    END AS tier,
    COUNT(*) AS customer_count
FROM customers
GROUP BY
    CASE
        WHEN customers.total_purchases < 100 THEN 'Bronze'
        WHEN customers.total_purchases < 500 THEN 'Silver'
        WHEN customers.total_purchases < 1000 THEN 'Gold'
        ELSE 'Platinum'
    END
ORDER BY customer_count DESC;
```

**WHY THIS WORKS:**
- CASE expression repeated in GROUP BY (or use alias in some databases)
- PostgreSQL allows GROUP BY alias: `GROUP BY tier`
- CASE evaluates conditions top-down, first match wins

---

## Category 11 — Date/Time Patterns

> **7 patterns · LLM risk: MEDIUM · Priority: P2**
>
> Period comparisons depend on correct date handling. EXTRACT vs DATE_TRUNC choice matters.

### Pattern 92: `extract_year`

**Description:** Group or filter by year.

**Trigger Keywords:** `by year`, `yearly`, `annual`, `in 2024`

**Generic Example:**
```sql
SELECT
    EXTRACT(YEAR FROM orders.order_date) AS order_year,
    SUM(orders.amount) AS annual_revenue
FROM orders
GROUP BY EXTRACT(YEAR FROM orders.order_date)
ORDER BY order_year;
```

---

### Pattern 93: `extract_month`

**Description:** Group or filter by month.

**Trigger Keywords:** `by month`, `monthly`, `in January`, `which month`

**Generic Example:**
```sql
SELECT
    EXTRACT(MONTH FROM orders.order_date) AS order_month,
    COUNT(*) AS order_count
FROM orders
WHERE EXTRACT(YEAR FROM orders.order_date) = 2024
GROUP BY EXTRACT(MONTH FROM orders.order_date)
ORDER BY order_month;
```

---

### Pattern 94: `date_trunc`

**Description:** Truncate dates to a period for grouping.

**Trigger Keywords:** `monthly totals`, `weekly`, `quarterly summary`, `per month`

**Generic Example:**
```sql
SELECT
    DATE_TRUNC('month', orders.order_date) AS month,
    SUM(orders.amount) AS monthly_revenue,
    COUNT(*) AS order_count
FROM orders
GROUP BY DATE_TRUNC('month', orders.order_date)
ORDER BY month;
```

**WHY THIS WORKS:**
- DATE_TRUNC returns the first moment of the period (e.g., 2024-06-01 00:00:00)
- Better than EXTRACT for grouping because it preserves year context
- Supports: 'year', 'quarter', 'month', 'week', 'day', 'hour', etc.

---

### Pattern 95: `date_arithmetic`

**Description:** Add or subtract intervals from dates.

**Trigger Keywords:** `30 days ago`, `next week`, `3 months from`, `after N days`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.order_date,
    orders.order_date + INTERVAL '30 days' AS due_date,
    orders.order_date - INTERVAL '7 days' AS week_before
FROM orders;
```

---

### Pattern 96: `current_date_filter`

**Description:** Relative date filtering (last N days, this year, etc.).

**Trigger Keywords:** `last 30 days`, `past year`, `recent`, `this month`, `today`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.order_date,
    orders.amount
FROM orders
WHERE orders.order_date >= CURRENT_DATE - INTERVAL '30 days';
```

**WHY THIS WORKS:**
- CURRENT_DATE returns today's date (no time component)
- CURRENT_TIMESTAMP for datetime
- NOW() is PostgreSQL-specific alias for CURRENT_TIMESTAMP

---

### Pattern 97: `date_diff`

**Description:** Calculate duration between two dates.

**Trigger Keywords:** `days between`, `how long`, `duration`, `time since`, `age of`

**Generic Example:**
```sql
SELECT
    orders.order_id,
    orders.order_date,
    orders.ship_date,
    orders.ship_date - orders.order_date AS days_to_ship,
    AGE(orders.ship_date, orders.order_date) AS detailed_duration
FROM orders
WHERE orders.ship_date IS NOT NULL;
```

**WHY THIS WORKS:**
- `date1 - date2` returns integer days in PostgreSQL
- `AGE(end, start)` returns an interval with years, months, days
- `EXTRACT(DAY FROM AGE(...))` to get just the day component

---

### Pattern 98: `group_by_period`

**Description:** Aggregate data by time period (monthly, quarterly, etc.).

**Trigger Keywords:** `monthly breakdown`, `quarterly summary`, `per week`, `yearly totals`

**Generic Example:**
```sql
SELECT
    DATE_TRUNC('quarter', orders.order_date) AS quarter,
    COUNT(*) AS order_count,
    SUM(orders.amount) AS quarterly_revenue,
    AVG(orders.amount) AS avg_order_value
FROM orders
GROUP BY DATE_TRUNC('quarter', orders.order_date)
ORDER BY quarter;
```

---

## Category 12 — String Operations

> **5 patterns · LLM risk: LOW · Priority: P3**

### Pattern 99: `string_concat`

**Description:** Concatenate strings.

**Trigger Keywords:** `full name`, `combine`, `concatenate`, `join strings`

**Generic Example:**
```sql
SELECT
    customers.first_name || ' ' || customers.last_name AS full_name,
    customers.city || ', ' || customers.country AS location
FROM customers;
```

**WHY THIS WORKS:**
- `||` is the PostgreSQL string concatenation operator
- Any NULL operand makes the result NULL — use COALESCE if needed

---

### Pattern 100: `string_agg`

**Description:** Aggregate strings into a comma-separated list.

**Trigger Keywords:** `list of`, `comma separated`, `all names in one row`, `concatenate group`

**Generic Example:**
```sql
SELECT
    orders.customer_id,
    STRING_AGG(products.name, ', ' ORDER BY products.name) AS product_list
FROM orders
JOIN order_items ON orders.order_id = order_items.order_id
JOIN products ON order_items.product_id = products.product_id
GROUP BY orders.customer_id;
```

**WHY THIS WORKS:**
- STRING_AGG(col, delimiter) concatenates values within a group
- ORDER BY inside STRING_AGG controls the concatenation order
- PostgreSQL-specific — standard SQL uses LISTAGG

---

### Pattern 101: `substring`

**Description:** Extract a portion of a string.

**Trigger Keywords:** `first 3 characters`, `extract part`, `substring`, `left N chars`

**Generic Example:**
```sql
SELECT
    customers.name,
    SUBSTRING(customers.postal_code FROM 1 FOR 3) AS area_code,
    LEFT(customers.phone, 4) AS country_code
FROM customers;
```

---

### Pattern 102: `upper_lower`

**Description:** Convert string case.

**Trigger Keywords:** `uppercase`, `lowercase`, `capitalize`

**Generic Example:**
```sql
SELECT
    UPPER(customers.last_name) AS last_name_upper,
    LOWER(customers.email) AS email_lower,
    INITCAP(customers.city) AS city_proper
FROM customers;
```

---

### Pattern 103: `trim`

**Description:** Remove whitespace or specific characters.

**Trigger Keywords:** `remove spaces`, `trim`, `clean up`

**Generic Example:**
```sql
SELECT
    TRIM(customers.name) AS clean_name,
    TRIM(BOTH ' ' FROM customers.address) AS clean_address,
    LTRIM(customers.phone, '+') AS phone_without_plus
FROM customers;
```

---

## Category 13 — Advanced Patterns

> **5 patterns · LLM risk: HIGH · Priority: P3 (niche but needed)**

### Pattern 104: `pivot_case`

**Description:** Pivot rows into columns using CASE expressions.

**Trigger Keywords:** `pivot`, `columns for each`, `cross-tab`, `wide format`

**Generic Example:**
```sql
SELECT
    products.category,
    SUM(CASE WHEN EXTRACT(QUARTER FROM orders.order_date) = 1 THEN orders.amount ELSE 0 END) AS q1_revenue,
    SUM(CASE WHEN EXTRACT(QUARTER FROM orders.order_date) = 2 THEN orders.amount ELSE 0 END) AS q2_revenue,
    SUM(CASE WHEN EXTRACT(QUARTER FROM orders.order_date) = 3 THEN orders.amount ELSE 0 END) AS q3_revenue,
    SUM(CASE WHEN EXTRACT(QUARTER FROM orders.order_date) = 4 THEN orders.amount ELSE 0 END) AS q4_revenue
FROM products
JOIN order_items ON products.product_id = order_items.product_id
JOIN orders ON order_items.order_id = orders.order_id
GROUP BY products.category;
```

---

### Pattern 105: `unpivot_union`

**Description:** Convert columns into rows using UNION ALL.

**Trigger Keywords:** `unpivot`, `melt`, `long format`, `normalize columns`

**Generic Example:**
```sql
SELECT products.product_id, 'weight' AS attribute, products.weight::TEXT AS value FROM products
UNION ALL
SELECT products.product_id, 'height' AS attribute, products.height::TEXT AS value FROM products
UNION ALL
SELECT products.product_id, 'width' AS attribute, products.width::TEXT AS value FROM products;
```

---

### Pattern 106: `cumulative_distribution`

**Description:** Compute percentile rank or cumulative distribution.

**Trigger Keywords:** `percentile`, `distribution`, `what percentile`, `cumulative percentage`

**Generic Example:**
```sql
SELECT
    customers.name,
    SUM(orders.amount) AS total_spent,
    PERCENT_RANK() OVER (ORDER BY SUM(orders.amount)) AS pct_rank,
    CUME_DIST() OVER (ORDER BY SUM(orders.amount)) AS cumulative_dist
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name;
```

**WHY THIS WORKS:**
- PERCENT_RANK: (rank - 1) / (total_rows - 1) → range [0, 1]
- CUME_DIST: rows_up_to_current / total_rows → range (0, 1]
- Window function over aggregated data requires GROUP BY

---

### Pattern 107: `gaps_and_islands`

**Description:** Find consecutive sequences (islands) or gaps in data.

**Trigger Keywords:** `consecutive`, `streak`, `continuous`, `gap`, `missing dates`, `sequence`

**Generic Example:**
```sql
SELECT
    sub.customer_id,
    MIN(sub.order_date) AS island_start,
    MAX(sub.order_date) AS island_end,
    COUNT(*) AS consecutive_orders
FROM (
    SELECT
        orders.customer_id,
        orders.order_date,
        orders.order_date - (ROW_NUMBER() OVER (
            PARTITION BY orders.customer_id
            ORDER BY orders.order_date
        ) * INTERVAL '1 day') AS grp
    FROM orders
) AS sub
GROUP BY sub.customer_id, sub.grp
HAVING COUNT(*) >= 3
ORDER BY consecutive_orders DESC;
```

**WHY THIS WORKS:**
- ROW_NUMBER difference technique: consecutive dates minus sequential row numbers yield a constant
- Group by that constant to find islands
- HAVING COUNT(*) >= N finds islands of at least N days

---

### Pattern 108: `deduplication`

**Description:** Remove duplicates keeping one row per group (usually most recent).

**Trigger Keywords:** `remove duplicates`, `latest per group`, `most recent per`, `deduplicate`

**Generic Example:**
```sql
SELECT sub.customer_id, sub.email, sub.updated_at
FROM (
    SELECT
        customers.customer_id,
        customers.email,
        customers.updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY customers.email
            ORDER BY customers.updated_at DESC
        ) AS rn
    FROM customers
) AS sub
WHERE sub.rn = 1;
```

**WHY THIS WORKS:**
- ROW_NUMBER with PARTITION BY duplicate-key, ORDER BY recency
- WHERE rn = 1 keeps only the most recent per group
- Wrap in subquery because WHERE can't reference window functions directly

---

## Pattern Priority Matrix

| Priority | Category | Pattern IDs | Count | LLM Risk | Why |
|----------|----------|-------------|-------|----------|-----|
| **P0 — CRITICAL** | Cat 6: Comparison to Aggregate | 46–61 | 16 | VERY HIGH | Core danger zone. All 15 passing tests are here. |
| **P1 — HIGH** | Cat 7: Subquery Patterns | 62–69 | 8 | HIGH | Building blocks for Cat 6. Correlated subqueries are fragile. |
| **P1 — HIGH** | Cat 8: Window Functions | 70–81 | 12 | MEDIUM-HIGH | Analytics queries common. Frame clauses trip up Mistral. |
| **P2 — MEDIUM** | Cat 5: Joins | 34–45 | 12 | MEDIUM | Multi-hop + subquery joins cause scope errors. |
| **P2 — MEDIUM** | Cat 10: Conditional Logic | 86–91 | 6 | MEDIUM | Conditional aggregation = building block for YoY. |
| **P2 — MEDIUM** | Cat 11: Date/Time | 92–98 | 7 | MEDIUM | Period comparisons need correct date handling. |
| **P3 — LOW** | Cat 1: Basic Retrieval | 1–10 | 10 | LOW | Mistral handles fine. Include for completeness. |
| **P3 — LOW** | Cat 2: Compound Filtering | 11–18 | 8 | LOW-MEDIUM | EXISTS/NOT EXISTS need guidance. |
| **P3 — LOW** | Cat 3: Sorting & Ordering | 19–23 | 5 | LOW | Reliable. |
| **P3 — LOW** | Cat 4: Simple Aggregation | 24–33 | 10 | LOW | Basic GROUP BY works. |
| **P3 — LOW** | Cat 9: Set Operations | 82–85 | 4 | LOW | Rarely breaks. |
| **P3 — LOW** | Cat 12: String Operations | 99–103 | 5 | LOW | Niche but needed. |
| **P3 — LOW** | Cat 13: Advanced | 104–108 | 5 | HIGH | Niche. Gaps-and-islands + dedup are complex. |

**Summary:** 108 total patterns. Build P0 first (16 patterns), then P1 (20), then P2 (25), then P3 (47).

---

## Pattern Matching Keywords/Regex

The pattern classifier is deterministic (regex/keyword, <1ms, no LLM call). Below is the mapping from user prompt signals to pattern IDs.

### Category 6 (P0) — Trigger Rules

| Pattern | Regex / Keyword Signals |
|---------|------------------------|
| 46: `agg_vs_global_avg_sum` | `(total\|sum\|spending\|revenue).*(more\|greater\|above\|higher\|exceed).*(average\|avg\|mean)` AND aggregate word = sum/total/spending/revenue |
| 47: `agg_vs_global_avg_count` | `(count\|number of\|how many).*(more\|greater\|above).*(average\|avg)` AND aggregate word = count/number |
| 48: `agg_vs_global_avg_max` | `(longest\|highest\|maximum\|max).*(more\|greater\|above).*(average\|avg).*(longest\|highest\|max)` |
| 49: `agg_vs_global_avg_min` | `(shortest\|cheapest\|minimum\|min\|lowest).*(less\|below\|under).*(average\|avg).*(shortest\|min)` |
| 50: `value_vs_group_avg` | `(longer\|higher\|more\|greater).*(than\|above).*(average\|avg).*(in\|within\|for).*(its\|their\|same\|own)` |
| 51: `latest_vs_own_avg` | `(latest\|most recent\|last\|newest).*(more\|greater\|higher\|above).*(average\|avg\|mean)` |
| 52: `first_vs_last` | `(first\|earliest).*(vs\|compared\|less\|more\|greater).*(last\|latest\|most recent)` |
| 53: `yoy_comparison` | `(\d{4}).*(vs\|compared\|than\|over).*(more\|less\|greater).*(\d{4})` OR `year.over.year\|YoY` |
| 54: `mom_comparison` | `month.over.month\|MoM\|(january\|february\|...).*vs.*(january\|february\|...)` |
| 55: `max_vs_multiple_of_min` | `(max\|largest\|highest).*(twice\|2x\|double\|N times\|multiple).*(min\|smallest\|lowest)` |
| 56: `entity_agg_vs_fixed_pct` | `(percentile\|quartile\|top\s+\d+%)` |
| 57: `multi_hop_agg_vs_avg` | Detected when: pattern 46/47/48 triggers AND identified tables are 3+ hops apart |
| 58: `per_group_max_vs_global` | `(highest\|maximum\|largest).*(per\|by\|each).*(above\|exceed\|more than).*(overall\|global\|average)` |
| 59: `top_n_by_aggregate` | `top\s+\d+.*(by\|based on\|ranked).*(total\|sum\|count\|revenue)` |
| 60: `bottom_n_by_aggregate` | `(bottom\|worst\|least\|lowest)\s+\d+.*(by\|based on)` |
| 61: `agg_ratio_comparison` | `(ratio\|per\|average order value).*(more\|greater\|above)` |

### Fallback Rule

If NO pattern matches → use reasoning mode without few-shot injection (current default behavior).

### Multi-Pattern Matching

Some queries match multiple patterns. Priority order:
1. Most specific pattern wins (e.g., `yoy_comparison` > `conditional_aggregation`)
2. Higher category number wins within same specificity
3. If still tied, use the first match

---

## Validated Test Results

| Test # | Pattern Used | Query | Result | Rows |
|--------|-------------|-------|--------|------|
| 1 | `latest_vs_own_avg` (51) | Latest invoice > customer's avg invoice | ✅ PASS | 26 |
| 2 | `agg_vs_global_avg_sum` (46) | Total spending > avg spending | ✅ PASS | 16 |
| 3 | `yoy_comparison` (53) | 2013 vs 2012 spending | ✅ PASS | 0 (correct — Chinook years are 2021-2025) |
| 4 | `max_vs_multiple_of_min` (55) | MAX invoice >= 2x MIN invoice | ✅ PASS | 59 |
| 5 | `first_vs_last` (52) | First invoice < last invoice | ✅ PASS | 27 |
| 6 | `agg_vs_global_avg_sum` (46) | Genre revenue > avg genre revenue | ✅ PASS | 5 |
| 7 | `value_vs_group_avg` (50) | Track length > avg in album | ✅ PASS | 1481 |
| 8 | `agg_vs_global_avg_sum` (46) | Album duration > avg album duration | ✅ PASS | 95 |
| 9 | `value_vs_group_avg` (50) | Track price > avg in genre | ✅ PASS | 213 |
| 10 | `multi_hop_agg_vs_avg` (57) | Artist revenue > avg artist revenue | ✅ PASS | 54 |
| 11 | `agg_vs_global_avg_count` (47) | Artist tracks > avg per artist | ✅ PASS | 71 |
| 12 | `agg_vs_global_avg_max` (48) | Longest track > avg longest | ✅ PASS | 101 |
| 13 | `agg_vs_global_avg_sum` (46) | Country revenue > avg per country | ✅ PASS | 7 |
| 14 | `per_group_max_vs_global` (58) | Country highest invoice > global avg | ⬜ UNTESTED |  |
| 15 | `agg_vs_global_avg_count` (47) | Country customer count > avg | ✅ PASS | 7 |
| 16 | — | TBD | ⬜ UNTESTED | |
| 17 | — | TBD | ⬜ UNTESTED | |
| 18 | — | TBD | ⬜ UNTESTED | |
| 19 | `agg_vs_global_avg_count` (47) | Employees > avg customers | ✅ PASS | 4 |
| 20 | — | TBD | ⬜ UNTESTED | |

**Score: 15/15 passing · 5 untested**

---

## Known Mistral 7B Failure Modes (Anti-Patterns)

These are the specific errors that the few-shot examples are designed to prevent:

| # | Failure Mode | Example Error | Which Patterns Prevent It |
|---|-------------|---------------|--------------------------|
| 1 | **Broken CTE/WITH syntax** | Generates incomplete or malformed WITH clauses | All Cat 6 patterns — explicitly say "Do NOT use CTE / WITH" |
| 2 | **Nested aggregate** | `HAVING SUM(col) > AVG(SUM(col))` — invalid nesting | Pat 46-49 — show correct 2-level subquery |
| 3 | **Subquery scope leak** | References `track.milliseconds` from outside a subquery that contains `track` | Pat 43 — "CRITICAL: Do NOT join a subquery and then reference the original table" |
| 4 | **Missing GROUP BY in HAVING** | Uses HAVING without GROUP BY | Pat 46-49, 55, 61 — examples always show GROUP BY + HAVING together |
| 5 | **Wrong aggregate in HAVING** | `HAVING invoice.total > ...` (raw column, not aggregate) | Pat 46-49 — "Never use raw column in HAVING — always wrap in aggregate" |
| 6 | **Correlated subquery alias confusion** | Inner and outer query use same table without alias | Pat 50, 64 — always use `p2` alias for inner copy |
| 7 | **Window function in WHERE** | `WHERE ROW_NUMBER() OVER (...) <= 3` — can't use window in WHERE | Pat 81 — wrap in subquery first |

---

*Last updated: 2026-02-28 · Generated from 15 validated tests against Chinook PostgreSQL with Mistral 7B via Ollama*
