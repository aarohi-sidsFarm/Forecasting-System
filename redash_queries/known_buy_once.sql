WITH target AS (
    SELECT
        '{{target_date}}'::date AS target_date,
        ('{{target_date}}'::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
),

row_level AS (
    SELECT
        toi.customer_id,
        toi.quantity::numeric AS qty,
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
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('toned_milk', 'toned milk')
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(pp.name, E'\t', ''))
        END AS product_name
    FROM temp_order_item toi
    CROSS JOIN target t
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
    WHERE toi.order_date::date = t.target_date
      AND (toi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.cutoff_ts_ist
      AND toi.status IN ('DRAFT', 'PROCESSED_TO_ORDER')
      AND COALESCE(toi.quantity, 0) > 0
      AND COALESCE(toi.free_product, false) = false
      AND (
            toi.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR toi.purchase_type ILIKE '%buy once%'
          )
)

SELECT
    t.target_date,
    r.city_cd,
    r.product_name,
    SUM(r.qty) AS known_buy_once_qty,
    COUNT(DISTINCT r.customer_id) AS known_buy_once_orders
FROM row_level r
CROSS JOIN target t
GROUP BY
    t.target_date,
    r.city_cd,
    r.product_name
ORDER BY
    r.city_cd,
    known_buy_once_qty DESC;
