/* Compare possible "actual demand" sources for one date.

   Use this when business dashboard totals do not match the API actuals.

   Parameters:
     target_date

   Focus:
     HYD priority products.
*/

WITH target AS (
    SELECT
        '{{target_date}}'::date AS target_date,
        ('{{target_date}}'::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
),

order_item_rows AS (
    SELECT
        'order_item_no_created_cutoff' AS source,
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
        SUM(COALESCE(ooi.quantity, 0)) AS qty
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
      AND UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) = 'HYD'
      AND (
            ooi.purchase_type ILIKE '%subscription%'
            OR ooi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR ooi.purchase_type ILIKE '%buy once%'
            OR ooi.purchase_type IS NULL
          )
    GROUP BY
        city_cd,
        product_name
),

order_item_cutoff_rows AS (
    SELECT
        'order_item_created_before_cutoff' AS source,
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
        SUM(COALESCE(ooi.quantity, 0)) AS qty
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
      AND (ooi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.cutoff_ts_ist
      AND ooi.status IN ('CONFIRMED', 'DELIVERED')
      AND COALESCE(ooi.quantity, 0) > 0
      AND COALESCE(ooi.free_product, false) = false
      AND UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) = 'HYD'
      AND (
            ooi.purchase_type ILIKE '%subscription%'
            OR ooi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR ooi.purchase_type ILIKE '%buy once%'
            OR ooi.purchase_type IS NULL
          )
    GROUP BY
        city_cd,
        product_name
),

d2c_fact_rows AS (
    SELECT
        'd2c_order_newfact' AS source,
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
        SUM(COALESCE(f.order_volume, 0)) AS qty
    FROM d2c_order_newfact f
    CROSS JOIN target t
    WHERE f.delivery_date::date = t.target_date
      AND f.status IN ('CONFIRMED', 'DELIVERED')
      AND COALESCE(f.order_volume, 0) > 0
      AND UPPER(TRIM(f.customer_city)) = 'HYD'
      AND (
            f.purchase_type ILIKE '%subscription%'
            OR f.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR f.purchase_type ILIKE '%buy once%'
            OR f.purchase_type IS NULL
          )
    GROUP BY
        city_cd,
        product_name
)

SELECT *
FROM order_item_rows
WHERE product_name IN ('A2 Buffalo Milk', 'A2 Desi Cow Milk', 'Cow Milk', 'Double Toned A2 Buffalo Milk', 'Skim Milk', 'Toned Milk', 'Curd')

UNION ALL

SELECT *
FROM order_item_cutoff_rows
WHERE product_name IN ('A2 Buffalo Milk', 'A2 Desi Cow Milk', 'Cow Milk', 'Double Toned A2 Buffalo Milk', 'Skim Milk', 'Toned Milk', 'Curd')

UNION ALL

SELECT *
FROM d2c_fact_rows
WHERE product_name IN ('A2 Buffalo Milk', 'A2 Desi Cow Milk', 'Cow Milk', 'Double Toned A2 Buffalo Milk', 'Skim Milk', 'Toned Milk', 'Curd')

ORDER BY
    product_name,
    source;
