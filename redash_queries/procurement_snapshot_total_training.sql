/* Procurement snapshot training export.

   Purpose:
     Improve procurement accuracy by giving the model the same information
     operations had when the forecast was created.

   Snapshot timing:
     HYD/PNQ: D-2 18:00 IST
     BLR/VGA: D-3 18:00 IST

   Cutoff:
     D-1 22:00 IST

   Target:
     final_total_qty from order_item joined to "order".expected_delivery_date.

   Important limitation:
     temp_order_item appears to be a current-state table, not a status history
     table. The snapshot quantities below are therefore a practical Redash-only
     approximation. For exact historical snapshots, developers need an order
     status history/audit table or daily snapshot table.
*/

WITH params AS (
    SELECT
        '{{start_date}}'::date AS start_date,
        '{{end_date}}'::date AS end_date
),

priority_products AS (
    SELECT *
    FROM (VALUES
        ('A2 Buffalo Milk'),
        ('A2 Desi Cow Milk'),
        ('Cow Milk'),
        ('Double Toned A2 Buffalo Milk'),
        ('Skim Milk'),
        ('Toned Milk'),
        ('Curd')
    ) AS p(product_name)
),

city_dates AS (
    SELECT
        d::date AS target_date,
        c.city_cd,
        CASE
            WHEN c.city_cd IN ('HYD', 'PNQ')
                THEN (d::date - INTERVAL '2 days' + TIME '18:00')
            ELSE (d::date - INTERVAL '3 days' + TIME '18:00')
        END AS snapshot_ts_ist,
        (d::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
    FROM params p
    CROSS JOIN generate_series(p.start_date, p.end_date, INTERVAL '1 day') d
    CROSS JOIN (VALUES ('HYD'), ('PNQ'), ('BLR'), ('VGA')) AS c(city_cd)
),

final_fact AS (
    SELECT
        o.expected_delivery_date::date AS target_date,
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
        CASE
            WHEN ooi.purchase_type ILIKE '%subscription%' THEN 'subscription'
            ELSE 'buy_once'
        END AS demand_source,
        ooi.quantity::numeric AS qty,
        o.customer_id
    FROM order_item ooi
    JOIN "order" o
        ON o.id = ooi.order_id
    JOIN params p
        ON o.expected_delivery_date::date BETWEEN p.start_date AND p.end_date
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
    WHERE ooi.status IN ('CONFIRMED', 'DELIVERED')
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
),

final_agg AS (
    SELECT
        target_date,
        city_cd,
        product_name,
        SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS final_subscription_qty,
        SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS final_buy_once_qty,
        SUM(qty) AS final_total_qty,
        COUNT(DISTINCT customer_id) AS final_orders
    FROM final_fact
    WHERE product_name IN (SELECT product_name FROM priority_products)
    GROUP BY
        target_date,
        city_cd,
        product_name
),

snapshot_order_items AS (
    SELECT
        cd.target_date,
        cd.city_cd,
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
        toi.status,
        toi.quantity::numeric AS qty,
        toi.customer_id
    FROM city_dates cd
    JOIN temp_order_item toi
        ON toi.order_date::date = cd.target_date
       AND (toi.created_at AT TIME ZONE 'Asia/Kolkata') <= cd.snapshot_ts_ist
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
    WHERE COALESCE(toi.quantity, 0) > 0
      AND COALESCE(toi.free_product, false) = false
      AND COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN') = cd.city_cd
      AND (
            toi.purchase_type ILIKE '%subscription%'
            OR toi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR toi.purchase_type ILIKE '%buy once%'
          )
),

snapshot_agg AS (
    SELECT
        target_date,
        city_cd,
        product_name,
        SUM(CASE WHEN demand_source = 'subscription' AND status IN ('DRAFT', 'PROCESSED_TO_ORDER') THEN qty ELSE 0 END) AS snapshot_subscription_qty,
        SUM(CASE WHEN demand_source = 'buy_once' AND status IN ('DRAFT', 'PROCESSED_TO_ORDER') THEN qty ELSE 0 END) AS snapshot_buy_once_qty,
        SUM(CASE WHEN status IN ('DRAFT', 'PROCESSED_TO_ORDER') THEN qty ELSE 0 END) AS snapshot_visible_qty,
        SUM(CASE WHEN status ILIKE 'CANCELLED%' THEN qty ELSE 0 END) AS eventually_cancelled_snapshot_qty,
        COUNT(DISTINCT CASE WHEN status IN ('DRAFT', 'PROCESSED_TO_ORDER') THEN customer_id END) AS snapshot_visible_orders
    FROM snapshot_order_items
    WHERE product_name IN (SELECT product_name FROM priority_products)
    GROUP BY
        target_date,
        city_cd,
        product_name
)

SELECT
    fa.target_date,
    fa.city_cd,
    fa.product_name,
    COALESCE(sa.snapshot_subscription_qty, 0) AS snapshot_subscription_qty,
    COALESCE(sa.snapshot_buy_once_qty, 0) AS snapshot_buy_once_qty,
    COALESCE(sa.snapshot_visible_qty, 0) AS snapshot_visible_qty,
    COALESCE(sa.snapshot_visible_orders, 0) AS snapshot_visible_orders,
    COALESCE(sa.eventually_cancelled_snapshot_qty, 0) AS eventually_cancelled_snapshot_qty,
    fa.final_subscription_qty,
    fa.final_buy_once_qty,
    fa.final_total_qty,
    fa.final_orders,
    fa.final_total_qty - COALESCE(sa.snapshot_visible_qty, 0) AS final_gap_from_snapshot_qty
FROM final_agg fa
LEFT JOIN snapshot_agg sa
    ON sa.target_date = fa.target_date
   AND sa.city_cd = fa.city_cd
   AND sa.product_name = fa.product_name
ORDER BY
    fa.target_date,
    fa.city_cd,
    fa.product_name;
