WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

customer_holidays AS (
    SELECT DISTINCT ch.cust_id
    FROM customer_holiday ch
    CROSS JOIN target t
    WHERE ch.is_deleted = false
      AND t.target_date BETWEEN ch.valid_from::date AND ch.valid_upto::date
),

subscription_base AS (
    SELECT
        t.target_date,
        s.cust_id AS customer_id,
        s.shipping_address_id,
        s.variant_id,
        LOWER(TRIM(COALESCE(s.subscription_type, ''))) AS subscription_type,
        CASE
            WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'daily'
                 OR COALESCE(s.is_daily, false) = true
                THEN COALESCE(
                    s.start_day_qty::numeric,
                    NULLIF(s.data->>'quantity', '')::numeric,
                    NULLIF(s.data->>'start_day_qty', '')::numeric,
                    0
                )

            WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'alternate'
                 OR COALESCE(s.is_alt_day_sub, false) = true
                THEN CASE
                    WHEN COALESCE(s.valid_from, s.start_date) IS NULL
                        THEN 0
                    WHEN (
                        t.target_date - COALESCE(s.valid_from, s.start_date)::date
                    ) % 2 = 0
                        THEN COALESCE(
                            s.start_day_qty::numeric,
                            NULLIF(s.data->>'start_day_qty', '')::numeric,
                            NULLIF(s.data->>'start_date_qty', '')::numeric,
                            0
                        )
                    ELSE COALESCE(
                        s.next_day_qty::numeric,
                        NULLIF(s.data->>'next_day_qty', '')::numeric,
                        0
                    )
                END

            WHEN LOWER(TRIM(COALESCE(s.subscription_type, ''))) = 'custom'
                THEN CASE EXTRACT(DOW FROM t.target_date)::int
                    WHEN 0 THEN COALESCE(s.sun::numeric, NULLIF(s.data->>'sun', '')::numeric, NULLIF(s.data->>'SUN', '')::numeric, 0)
                    WHEN 1 THEN COALESCE(s.mon::numeric, NULLIF(s.data->>'mon', '')::numeric, NULLIF(s.data->>'MON', '')::numeric, 0)
                    WHEN 2 THEN COALESCE(s.tue::numeric, NULLIF(s.data->>'tue', '')::numeric, NULLIF(s.data->>'TUE', '')::numeric, 0)
                    WHEN 3 THEN COALESCE(s.wed::numeric, NULLIF(s.data->>'wed', '')::numeric, NULLIF(s.data->>'WED', '')::numeric, 0)
                    WHEN 4 THEN COALESCE(s.thu::numeric, NULLIF(s.data->>'thu', '')::numeric, NULLIF(s.data->>'THU', '')::numeric, 0)
                    WHEN 5 THEN COALESCE(s.fri::numeric, NULLIF(s.data->>'fri', '')::numeric, NULLIF(s.data->>'FRI', '')::numeric, 0)
                    WHEN 6 THEN COALESCE(s.sat::numeric, NULLIF(s.data->>'sat', '')::numeric, NULLIF(s.data->>'SAT', '')::numeric, 0)
                END

            ELSE 0
        END AS qty
    FROM subscription s
    CROSS JOIN target t
    LEFT JOIN customer_holidays ch
        ON ch.cust_id = s.cust_id
    WHERE LOWER(TRIM(COALESCE(s.subscription_status, ''))) = 'active'
      AND COALESCE(s.is_paused, false) = false
      AND ch.cust_id IS NULL
      AND NOT (
            s.pause_start_date IS NOT NULL
            AND s.pause_start_date::date <= t.target_date
            AND (
                s.pause_end_date IS NULL
                OR s.pause_end_date::date >= t.target_date
            )
          )
      AND (
            s.valid_from IS NULL
            OR s.valid_from::date <= t.target_date
          )
      AND (
            s.valid_upto IS NULL
            OR s.valid_upto::date >= t.target_date
          )
),

subscription_orders AS (
    SELECT *
    FROM subscription_base
    WHERE qty > 0
),

row_level AS (
    SELECT
        so.customer_id,
        so.subscription_type,
        so.qty,
        COALESCE(pv.price_override_amount, 0) AS selling_price,
        so.qty * COALESCE(pv.price_override_amount, 0) AS row_value,
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
    FROM subscription_orders so
    JOIN product_productvariant pv
        ON pv.id = so.variant_id
    JOIN product_product pp
        ON pp.id = pv.product_id
    LEFT JOIN customer_address ship_ca
        ON ship_ca.id = so.shipping_address_id
    LEFT JOIN (
        SELECT DISTINCT ON (cust_id)
            cust_id,
            city_cd
        FROM customer_address
        WHERE is_active = true
        ORDER BY cust_id, updated_at DESC
    ) ca
        ON ca.cust_id = so.customer_id
),

customer_total AS (
    SELECT
        customer_id,
        SUM(row_value) AS total_order_value
    FROM row_level
    GROUP BY customer_id
),

wallet_check AS (
    SELECT
        ct.customer_id,
        CASE
            WHEN LOWER(COALESCE(c.wallet_type, '')) LIKE '%prepaid%'
             AND ct.total_order_value > COALESCE(c.current_balance, 0)
            THEN true
            ELSE false
        END AS low_balance_flag
    FROM customer_total ct
    JOIN customers c
        ON c.id = ct.customer_id
)

SELECT
    t.target_date,
    r.city_cd,
    r.product_name,
    r.subscription_type,
    SUM(CASE WHEN COALESCE(w.low_balance_flag, false) = false THEN r.qty ELSE 0 END) AS confirmed_qty,
    SUM(r.qty) AS expected_qty,
    SUM(CASE WHEN COALESCE(w.low_balance_flag, false) = true THEN r.qty ELSE 0 END) AS at_risk_qty,
    COUNT(DISTINCT CASE WHEN COALESCE(w.low_balance_flag, false) = false THEN r.customer_id END) AS confirmed_orders,
    COUNT(DISTINCT r.customer_id) AS total_orders
FROM row_level r
LEFT JOIN wallet_check w
    ON w.customer_id = r.customer_id
CROSS JOIN target t
GROUP BY
    t.target_date,
    r.city_cd,
    r.product_name,
    r.subscription_type
ORDER BY
    r.city_cd,
    confirmed_qty DESC;
