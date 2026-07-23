WITH params AS (
    SELECT
        '{{start_date}}'::date AS start_date,
        '{{end_date}}'::date AS end_date,
        COALESCE(NULLIF('{{snapshot_time_ist}}', '')::time, TIME '10:00') AS snapshot_time_ist
),

row_level AS (
    SELECT
        toi.order_date::date AS target_date,
        (toi.order_date::date - INTERVAL '1 day' + p.snapshot_time_ist) AS snapshot_ts_ist,
        (toi.order_date::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist,
        (toi.created_at AT TIME ZONE 'Asia/Kolkata') AS created_ts_ist,
        COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN') AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('double toned a2 buffalo milk', 'a2 buffalo milk double toned')
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 buffalo milk', 'buffalo_milk', 'buffalo milk')
                THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('cow_milk', 'cow milk')
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('a2 desi cow milk', 'a2 cow milk', 'desi cow milk')
                THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('skim_milk', 'skim milk')
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(pp.name, E'\t', ''))
        END AS product_name,
        toi.quantity::numeric AS qty,
        toi.customer_id
    FROM temp_order_item toi
    JOIN params p
        ON toi.order_date::date BETWEEN p.start_date AND p.end_date
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
    WHERE toi.status = 'PROCESSED_TO_ORDER'
      AND COALESCE(toi.free_product, false) = false
      AND (
            toi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR toi.purchase_type ILIKE '%buy once%'
          )
),

aggregated AS (
    SELECT
        target_date,
        city_cd,
        product_name,
        SUM(qty) AS final_adhoc_qty,
        SUM(CASE WHEN created_ts_ist <= snapshot_ts_ist THEN qty ELSE 0 END) AS known_buy_once_qty_at_snapshot,
        SUM(CASE WHEN created_ts_ist > snapshot_ts_ist THEN qty ELSE 0 END) AS remaining_unknown_adhoc_qty,
        SUM(CASE WHEN created_ts_ist <= cutoff_ts_ist THEN qty ELSE 0 END) AS known_buy_once_qty_at_cutoff,
        SUM(CASE WHEN created_ts_ist > cutoff_ts_ist THEN qty ELSE 0 END) AS residual_unknown_adhoc_qty,
        COUNT(*) AS final_adhoc_orders,
        COUNT(*) FILTER (WHERE created_ts_ist <= snapshot_ts_ist) AS known_buy_once_orders_at_snapshot,
        COUNT(*) FILTER (WHERE created_ts_ist > snapshot_ts_ist) AS remaining_unknown_orders,
        COUNT(*) FILTER (WHERE created_ts_ist <= cutoff_ts_ist) AS known_buy_once_orders_at_cutoff,
        COUNT(*) FILTER (WHERE created_ts_ist > cutoff_ts_ist) AS residual_unknown_orders
    FROM row_level
    GROUP BY
        target_date,
        city_cd,
        product_name
)

SELECT
    target_date,
    city_cd,
    product_name,
    final_adhoc_qty,
    known_buy_once_qty_at_snapshot,
    remaining_unknown_adhoc_qty,
    known_buy_once_qty_at_cutoff,
    residual_unknown_adhoc_qty,
    final_adhoc_orders,
    known_buy_once_orders_at_snapshot,
    remaining_unknown_orders,
    known_buy_once_orders_at_cutoff,
    residual_unknown_orders
FROM aggregated
ORDER BY
    target_date,
    city_cd,
    product_name;
