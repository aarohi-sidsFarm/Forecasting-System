/* Selected-date final D2C actual demand from order_item + "order".

Purpose:
Use this as SELECTED_ACTUALS_QUERY_ID for dashboard accuracy checking.

Difference from recent_final_total_actuals.sql:
- This returns the selected target_date itself.
- recent_final_total_actuals.sql intentionally excludes target_date and is
only for lag/rolling inference features.

Output contract expected by backend:
     target_date, city_cd, product_name, actual_qty, actual_orders
*/  

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

row_level AS (
    SELECT
        t.target_date,
        UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('double toned a2 buffalo milk', 'a2 buffalo milk double toned', 'double toned milk')
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 buffalo milk', 'buffalo_milk', 'buffalo milk')
                THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('cow_milk', 'cow milk')
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 desi cow milk', 'a2 cow milk', 'desi cow milk')
                THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('skim_milk', 'skim milk')
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('toned_milk', 'toned milk')
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(pp.name, E'\t', ''))
        END AS product_name,
        ooi.quantity::numeric AS qty,
        o.customer_id
    FROM order_item ooi
    JOIN "order" o
        ON o.id = ooi.order_id
    CROSS JOIN target t
    JOIN product_productvariant pv
        ON pv.id = ooi.variant_id
    JOIN product_product pp
        ON pp.id = pv.product_id
    LEFT JOIN customer_address ship_ca
        ON ship_ca.id = o.shipping_address_id
    LEFT JOIN (
        SELECT DISTINCT ON (cust_id)
            cust_id,
            city_cd
        FROM customer_address
        WHERE is_active = true
        ORDER BY cust_id, updated_at DESC
    ) ca
        ON ca.cust_id = o.customer_id
    WHERE o.expected_delivery_date::date = t.target_date
      AND ooi.status IN ('CONFIRMED', 'DELIVERED')
      AND COALESCE(ooi.quantity, 0) > 0
      AND COALESCE(ooi.free_product, false) = false
      AND UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) IN ('HYD', 'PNQ', 'BLR', 'VGA')
      AND pp.name NOT ILIKE '%sample%'
      AND pp.name NOT ILIKE '%test%'
      AND (
            ooi.purchase_type ILIKE '%subscription%'
            OR ooi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR ooi.purchase_type ILIKE '%buy once%'
            OR ooi.purchase_type IS NULL
          )
)

SELECT
    target_date,
    city_cd,
    product_name,
    SUM(qty) AS actual_qty,
    COUNT(DISTINCT customer_id) AS actual_orders
FROM row_level
WHERE product_name IN (
    'A2 Buffalo Milk',
    'A2 Desi Cow Milk',
    'Cow Milk',
    'Double Toned A2 Buffalo Milk',
    'Skim Milk',
    'Toned Milk',
    'Curd'
)
GROUP BY
    target_date,
    city_cd,
    product_name
ORDER BY
    city_cd,
    actual_qty DESC;
