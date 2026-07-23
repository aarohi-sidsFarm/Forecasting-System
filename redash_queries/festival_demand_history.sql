/* Festival demand history export.

   Use this Redash query to export clean festival windows for modeling.

   Parameters:
     festival_name  - e.g. Varalakshmi Vratam
     festival_date  - actual festival date, e.g. 2026-08-28
     start_date     - window start, e.g. festival_date - 7 days
     end_date       - window end, e.g. festival_date + 7 days

   Output grain:
     delivery_date x city x product_name

   Why this shape:
     The model needs to learn demand movement before/on/after festivals.
     days_from_festival lets us compare moving festivals across years.
*/

WITH params AS (
    SELECT
        '{{festival_name}}'::text AS festival_name,
        '{{festival_date}}'::date AS festival_date,
        '{{start_date}}'::date AS start_date,
        '{{end_date}}'::date AS end_date
),

row_level AS (
    SELECT
        p.festival_name,
        p.festival_date,
        f.delivery_date::date AS delivery_date,
        (f.delivery_date::date - p.festival_date) AS days_from_festival,
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
    CROSS JOIN params p
    WHERE f.delivery_date::date BETWEEN p.start_date AND p.end_date
      AND f.status IN ('CONFIRMED', 'DELIVERED')
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
    festival_name,
    festival_date,
    delivery_date,
    days_from_festival,
    city_cd,
    product_name,
    SUM(qty) AS total_quantity,
    SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS subscription_quantity,
    SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS buy_once_quantity,
    COUNT(DISTINCT customer_id) AS customer_count
FROM row_level
GROUP BY
    festival_name,
    festival_date,
    delivery_date,
    days_from_festival,
    city_cd,
    product_name
ORDER BY
    delivery_date,
    city_cd,
    product_name;
