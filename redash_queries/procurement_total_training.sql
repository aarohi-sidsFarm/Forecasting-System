/* Procurement-grade training export.

   Target:
     net_remaining_qty = final_confirmed_total_qty_at_cutoff
                         - known_total_qty_at_procurement_snapshot

   Delivery date:
     - Snapshot rows: temp_order_item.order_date (planned delivery date in staging table)
     - Final rows: "order".expected_delivery_date

   City snapshot times:
     HYD/PNQ: D-2 18:00 IST
     BLR/VGA: D-3 18:00 IST

   IMPORTANT:
     - Run diagnostic_final_actual_status.sql first and update FINAL_STATUSES
       below if your final order table uses different confirmed/delivered statuses.
     - If the final table is named order_orderitem instead of order_order_item,
       replace order_item / "order" in this query.
*/

WITH params AS (
    SELECT
        '{{start_date}}'::date AS start_date,
        '{{end_date}}'::date AS end_date
),

target_dates AS (
    SELECT generate_series(p.start_date, p.end_date, INTERVAL '1 day')::date AS target_date
    FROM params p
),

city_snapshot AS (
    SELECT 'HYD' AS city_cd, 2 AS lead_days, TIME '18:00' AS snapshot_time_ist
    UNION ALL SELECT 'PNQ', 2, TIME '18:00'
    UNION ALL SELECT 'BLR', 3, TIME '18:00'
    UNION ALL SELECT 'VGA', 3, TIME '18:00'
),

targets AS (
    SELECT
        td.target_date,
        cs.city_cd,
        (td.target_date - (cs.lead_days * INTERVAL '1 day') + cs.snapshot_time_ist) AS snapshot_ts_ist,
        (td.target_date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
    FROM target_dates td
    CROSS JOIN city_snapshot cs
),

snapshot_rows AS (
    SELECT
        t.target_date,
        t.city_cd,
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
        SUM(COALESCE(toi.quantity, 0)) AS qty,
        COUNT(DISTINCT toi.customer_id) AS orders
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
    GROUP BY
        t.target_date,
        t.city_cd,
        product_name,
        demand_source
),

snapshot_agg AS (
    SELECT
        target_date,
        city_cd,
        product_name,
        SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS known_subscription_qty_at_snapshot,
        SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS known_buy_once_qty_at_snapshot,
        SUM(qty) AS known_total_qty_at_snapshot,
        SUM(orders) AS known_orders_at_snapshot
    FROM snapshot_rows
    GROUP BY
        target_date,
        city_cd,
        product_name
),

final_rows AS (
    SELECT
        t.target_date,
        t.city_cd,
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
            WHEN ooi.purchase_type ILIKE '%subscription%' THEN 'subscription'
            ELSE 'buy_once'
        END AS demand_source,
        SUM(COALESCE(ooi.quantity, 0)) AS qty,
        COUNT(DISTINCT o.customer_id) AS orders
    FROM targets t
    JOIN order_item ooi
        ON (ooi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.cutoff_ts_ist
    JOIN "order" o
        ON o.id = ooi.order_id
       AND o.expected_delivery_date::date = t.target_date
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
    WHERE COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN') = t.city_cd
      AND ooi.status IN ('CONFIRMED', 'DELIVERED')
      AND COALESCE(ooi.quantity, 0) > 0
      AND COALESCE(ooi.free_product, false) = false
      AND (
            ooi.purchase_type ILIKE '%subscription%'
            OR ooi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR ooi.purchase_type ILIKE '%buy once%'
          )
    GROUP BY
        t.target_date,
        t.city_cd,
        product_name,
        demand_source
),

final_agg AS (
    SELECT
        target_date,
        city_cd,
        product_name,
        SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS final_subscription_qty_at_cutoff,
        SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS final_buy_once_qty_at_cutoff,
        SUM(qty) AS final_total_qty_at_cutoff,
        SUM(orders) AS final_orders_at_cutoff
    FROM final_rows
    GROUP BY
        target_date,
        city_cd,
        product_name
),

joined AS (
    SELECT
        COALESCE(f.target_date, s.target_date) AS target_date,
        COALESCE(f.city_cd, s.city_cd) AS city_cd,
        COALESCE(f.product_name, s.product_name) AS product_name,
        t.snapshot_ts_ist,
        t.cutoff_ts_ist,
        COALESCE(s.known_subscription_qty_at_snapshot, 0) AS known_subscription_qty_at_snapshot,
        COALESCE(s.known_buy_once_qty_at_snapshot, 0) AS known_buy_once_qty_at_snapshot,
        COALESCE(s.known_total_qty_at_snapshot, 0) AS known_total_qty_at_snapshot,
        COALESCE(s.known_orders_at_snapshot, 0) AS known_orders_at_snapshot,
        COALESCE(f.final_subscription_qty_at_cutoff, 0) AS final_subscription_qty_at_cutoff,
        COALESCE(f.final_buy_once_qty_at_cutoff, 0) AS final_buy_once_qty_at_cutoff,
        COALESCE(f.final_total_qty_at_cutoff, 0) AS final_total_qty_at_cutoff,
        COALESCE(f.final_orders_at_cutoff, 0) AS final_orders_at_cutoff
    FROM final_agg f
    FULL OUTER JOIN snapshot_agg s
        ON s.target_date = f.target_date
       AND s.city_cd = f.city_cd
       AND s.product_name = f.product_name
    JOIN targets t
        ON t.target_date = COALESCE(f.target_date, s.target_date)
       AND t.city_cd = COALESCE(f.city_cd, s.city_cd)
)

SELECT
    target_date,
    city_cd,
    product_name,
    snapshot_ts_ist,
    cutoff_ts_ist,
    known_subscription_qty_at_snapshot,
    known_buy_once_qty_at_snapshot,
    known_total_qty_at_snapshot,
    known_orders_at_snapshot,
    final_subscription_qty_at_cutoff,
    final_buy_once_qty_at_cutoff,
    final_total_qty_at_cutoff,
    final_orders_at_cutoff,
    final_total_qty_at_cutoff - known_total_qty_at_snapshot AS net_remaining_qty,
    final_orders_at_cutoff - known_orders_at_snapshot AS net_remaining_orders
FROM joined
WHERE product_name IN (
    'A2 Buffalo Milk',
    'A2 Desi Cow Milk',
    'Cow Milk',
    'Double Toned A2 Buffalo Milk',
    'Skim Milk',
    'Toned Milk',
    'Curd'
)
ORDER BY
    target_date,
    city_cd,
    product_name;
