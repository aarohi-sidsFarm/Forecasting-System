WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

buy_once AS (
    SELECT
        'buy_once' AS source,
        COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN') AS city_cd,
        pp.name AS raw_product_name,
        pv.id AS variant_id,
        toi.status,
        toi.purchase_type,
        COUNT(*) AS rows,
        SUM(COALESCE(toi.quantity, 0)) AS qty
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
      AND COALESCE(toi.quantity, 0) > 0
    GROUP BY
        COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN'),
        pp.name,
        pv.id,
        toi.status,
        toi.purchase_type
),

subscription_rows AS (
    SELECT
        'subscription' AS source,
        COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN') AS city_cd,
        pp.name AS raw_product_name,
        pv.id AS variant_id,
        s.subscription_status AS status,
        s.subscription_type AS purchase_type,
        COUNT(*) AS rows,
        SUM(
            CASE
                WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'daily'
                     OR COALESCE(s.is_daily, false) = true
                    THEN COALESCE(s.start_day_qty::numeric, NULLIF(s.data->>'quantity', '')::numeric, 0)
                WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'alternate'
                     OR COALESCE(s.is_alt_day_sub, false) = true
                    THEN CASE
                        WHEN COALESCE(s.valid_from, s.start_date) IS NULL
                            THEN 0
                        WHEN (t.target_date - COALESCE(s.valid_from, s.start_date)::date) % 2 = 0
                            THEN COALESCE(s.start_day_qty::numeric, NULLIF(s.data->>'start_day_qty', '')::numeric, NULLIF(s.data->>'start_date_qty', '')::numeric, 0)
                        ELSE COALESCE(s.next_day_qty::numeric, NULLIF(s.data->>'next_day_qty', '')::numeric, 0)
                    END
                WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'custom'
                    THEN CASE EXTRACT(DOW FROM t.target_date)::int
                        WHEN 0 THEN COALESCE(s.sun::numeric, NULLIF(s.data->>'sun', '')::numeric, 0)
                        WHEN 1 THEN COALESCE(s.mon::numeric, NULLIF(s.data->>'mon', '')::numeric, 0)
                        WHEN 2 THEN COALESCE(s.tue::numeric, NULLIF(s.data->>'tue', '')::numeric, 0)
                        WHEN 3 THEN COALESCE(s.wed::numeric, NULLIF(s.data->>'wed', '')::numeric, 0)
                        WHEN 4 THEN COALESCE(s.thu::numeric, NULLIF(s.data->>'thu', '')::numeric, 0)
                        WHEN 5 THEN COALESCE(s.fri::numeric, NULLIF(s.data->>'fri', '')::numeric, 0)
                        WHEN 6 THEN COALESCE(s.sat::numeric, NULLIF(s.data->>'sat', '')::numeric, 0)
                    END
                ELSE 0
            END
        ) AS qty
    FROM subscription s
    CROSS JOIN target t
    JOIN product_productvariant pv
        ON pv.id = s.variant_id
    JOIN product_product pp
        ON pp.id = pv.product_id
    LEFT JOIN customer_address ship_ca
        ON ship_ca.id = s.shipping_address_id
    LEFT JOIN (
        SELECT DISTINCT ON (cust_id)
            cust_id,
            city_cd
        FROM customer_address
        WHERE is_active = true
        ORDER BY cust_id, updated_at DESC
    ) ca
        ON ca.cust_id = s.cust_id
    WHERE LOWER(TRIM(COALESCE(s.subscription_status, ''))) = 'active'
      AND (s.valid_from IS NULL OR s.valid_from::date <= t.target_date)
      AND (s.valid_upto IS NULL OR s.valid_upto::date >= t.target_date)
    GROUP BY
        COALESCE(ship_ca.city_cd, ca.city_cd, 'UNKNOWN'),
        pp.name,
        pv.id,
        s.subscription_status,
        s.subscription_type
)

SELECT *
FROM buy_once
UNION ALL
SELECT *
FROM subscription_rows
ORDER BY
    city_cd,
    raw_product_name,
    source,
    qty DESC;
