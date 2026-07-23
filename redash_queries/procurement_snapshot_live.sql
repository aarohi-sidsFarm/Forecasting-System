/* Live known demand at procurement snapshot for one target date.

   Parameters:
     target_date

   Uses city-specific procurement lead times:
     HYD/PNQ: D-2 18:00 IST
     BLR/VGA: D-3 18:00 IST
*/

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

city_snapshot AS (
    SELECT 'HYD' AS city_cd, 2 AS lead_days, TIME '18:00' AS snapshot_time_ist
    UNION ALL SELECT 'PNQ', 2, TIME '18:00'
    UNION ALL SELECT 'BLR', 3, TIME '18:00'
    UNION ALL SELECT 'VGA', 3, TIME '18:00'
),

targets AS (
    SELECT
        t.target_date,
        cs.city_cd,
        (t.target_date - (cs.lead_days * INTERVAL '1 day') + cs.snapshot_time_ist) AS snapshot_ts_ist,
        (t.target_date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
    FROM target t
    CROSS JOIN city_snapshot cs
),

row_level AS (
    SELECT
        t.target_date,
        t.city_cd,
        t.snapshot_ts_ist,
        t.cutoff_ts_ist,
        CASE
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('double toned a2 buffalo milk', 'a2 buffalo milk double toned')
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 buffalo milk', 'buffalo_milk', 'buffalo milk')
                THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('cow_milk', 'cow milk')
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 desi cow milk', 'a2 cow milk', 'desi cow milk')
                THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('double toned milk')
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('skim_milk', 'skim milk')
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('toned_milk', 'toned milk')
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(pp.name, E'\t', ''))
        END AS product_name,
        CASE
            WHEN toi.purchase_type ILIKE '%subscription%' THEN 'subscription'
            ELSE 'buy_once'
        END AS demand_source,
        toi.quantity::numeric AS qty,
        toi.customer_id
    FROM targets t
    JOIN temp_order_item toi
        ON toi.order_date::date = t.target_date
       AND (toi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.snapshot_ts_ist
    JOIN product_productvariant pv
        ON pv.id = toi.variant_id
    JOIN product_product pp
        ON pp.id = pv.product_id
    LEFT JOIN customer_address ship_ca
        ON ship_ca.id = toi.shipping_address_id
    LEFT JOIN (
        SELECT DISTINCT ON (cust_id)
            cust_id,
            city_cd
        FROM customer_address
        WHERE is_active = true
        ORDER BY cust_id, updated_at DESC
    ) ca
        ON ca.cust_id = toi.customer_id
    WHERE COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN') = t.city_cd
      AND toi.status IN ('DRAFT', 'PROCESSED_TO_ORDER')
      AND COALESCE(toi.quantity, 0) > 0
      AND COALESCE(toi.free_product, false) = false
      AND (
            toi.purchase_type ILIKE '%subscription%'
            OR toi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR toi.purchase_type ILIKE '%buy once%'
          )
)

SELECT
    target_date,
    city_cd,
    product_name,
    snapshot_ts_ist,
    cutoff_ts_ist,
    SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS known_subscription_qty_at_snapshot,
    SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS known_buy_once_qty_at_snapshot,
    SUM(qty) AS known_total_qty_at_snapshot,
    COUNT(DISTINCT customer_id) AS known_orders_at_snapshot
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
    product_name,
    snapshot_ts_ist,
    cutoff_ts_ist
ORDER BY
    city_cd,
    product_name;
