/* Fast procurement training export from d2c_order_newfact.

   Use this Redash-only fallback when historical D-2/D-3 procurement snapshots
   cannot be stored.

   Target:
     final_total_qty = final confirmed/delivered packet demand

   Delivery date:
     d2c_order_newfact.delivery_date

   Keep this query aligned with:
     - selected_final_total_actuals.sql
     - recent_final_total_actuals.sql
*/

WITH params AS (
    SELECT
        '{{start_date}}'::date AS start_date,
        '{{end_date}}'::date AS end_date
),

row_level AS (
    SELECT
        f.delivery_date::date AS target_date,
        UPPER(TRIM(f.customer_city)) AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN ('double toned a2 buffalo milk', 'a2 buffalo milk double toned', 'double toned milk')
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
        CASE
            WHEN f.purchase_type ILIKE '%subscription%' THEN 'subscription'
            ELSE 'buy_once'
        END AS demand_source,
        f.order_volume::numeric AS qty,
        f.customer_id
    FROM d2c_order_newfact f
    JOIN params p
        ON f.delivery_date::date BETWEEN p.start_date AND p.end_date
    WHERE f.status IN ('CONFIRMED', 'DELIVERED')
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
    SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS final_subscription_qty,
    SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS final_buy_once_qty,
    SUM(qty) AS final_total_qty,
    COUNT(DISTINCT customer_id) AS final_orders
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
    target_date,
    city_cd,
    product_name;
