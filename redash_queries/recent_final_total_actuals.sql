/* Recent final all-status total packet demand through the latest completed day.

   Use this for RECENT_ACTUALS_QUERY_ID when model target_type is
   procurement_final_total.

   Output contract expected by backend:
     target_date, city_cd, product_name, total_qty, total_orders

   Important:
     Keep this d2c_order_newfact definition aligned with the official actuals
     returned by Redash Query 1968.
*/

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

row_level AS (
    SELECT
        f.delivery_date::date AS target_date,
        UPPER(TRIM(f.customer_city)) AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('double toned a2 buffalo milk', 'a2 buffalo milk double toned', 'double toned milk', 'double toned buffalo milk')
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('a2 buffalo milk', 'buffalo_milk', 'buffalo milk')
                THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('cow_milk', 'cow milk')
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('a2 desi cow milk', 'a2 cow milk', 'desi cow milk')
                THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('skim_milk', 'skim milk')
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('toned_milk', 'toned milk')
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(f.product_name, E'\t', ''))
        END AS product_name,
        f.order_volume::numeric AS qty,
        f.customer_id
    FROM d2c_order_newfact f
    CROSS JOIN target t
    WHERE f.delivery_date >= t.target_date - INTERVAL '90 days'
      AND f.delivery_date < t.target_date + INTERVAL '1 day'
      AND COALESCE(f.order_volume, 0) > 0
      AND UPPER(TRIM(f.customer_city)) IN ('HYD', 'PNQ', 'BLR', 'VGA')
      AND f.product_name NOT ILIKE '%sample%'
      AND f.product_name NOT ILIKE '%test%'
      AND (
            f.purchase_type ILIKE '%subscription%'
            OR f.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR f.purchase_type ILIKE '%buy once%'
            OR f.purchase_type IS NULL
          )
)

SELECT
    target_date,
    city_cd,
    product_name,
    SUM(qty) AS total_qty,
    COUNT(DISTINCT customer_id) AS total_orders
FROM row_level
WHERE product_name IN (
    'A2 Buffalo Milk',
    'A2 Desi Cow Milk',
    'Cow Milk',
    'Double Toned A2 Buffalo Milk',
    'Skim Milk',
    'Toned Milk',
    'Curd',
    'High Protein Toned Milk'
)
GROUP BY
    target_date,
    city_cd,
    product_name
ORDER BY
    target_date,
    city_cd,
    product_name;
