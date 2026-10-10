WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

candidate_orders AS (
    SELECT toi.*
    FROM temp_order_item toi
    CROSS JOIN target t
    WHERE toi.order_date >= t.target_date
      AND toi.order_date < t.target_date + INTERVAL '1 day'
      AND UPPER(TRIM(COALESCE(toi.status, ''))) IN ('DRAFT', 'PROCESSED_TO_ORDER')
      AND COALESCE(toi.quantity, 0) > 0
      AND COALESCE(toi.free_product, false) = false
      AND (
            LOWER(TRIM(COALESCE(toi.purchase_type, ''))) IN (
                'buy once', 'adhoc buy once', 'first_x_order'
            )
            OR toi.purchase_type ILIKE '%buy once%'
          )
),

relevant_customers AS (
    SELECT DISTINCT customer_id
    FROM candidate_orders
    WHERE customer_id IS NOT NULL
),

latest_customer_address AS (
    SELECT DISTINCT ON (ca.cust_id)
        ca.cust_id,
        ca.city_cd
    FROM customer_address ca
    JOIN relevant_customers rc
        ON rc.customer_id = ca.cust_id
    WHERE ca.is_active = true
    ORDER BY ca.cust_id, ca.updated_at DESC NULLS LAST, ca.id DESC
),

normalized_orders AS (
    SELECT
        t.target_date,
        toi.customer_id,
        toi.quantity::numeric AS qty,
        toi.created_at AT TIME ZONE 'Asia/Kolkata' AS created_at_ist,
        CASE
            WHEN UPPER(TRIM(COALESCE(ship_ca.city_cd, ca.city_cd, ''))) IN ('HYD', 'HYDERABAD')
                THEN 'HYD'
            WHEN UPPER(TRIM(COALESCE(ship_ca.city_cd, ca.city_cd, ''))) IN ('VGA', 'VIJAYAWADA')
                THEN 'VGA'
            WHEN UPPER(TRIM(COALESCE(ship_ca.city_cd, ca.city_cd, ''))) IN ('BLR', 'BANGALORE', 'BENGALURU', 'CAM')
                THEN 'BLR'
            WHEN UPPER(TRIM(COALESCE(ship_ca.city_cd, ca.city_cd, ''))) IN ('PNQ', 'PUNE')
                THEN 'PNQ'
            ELSE 'UNKNOWN'
        END AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN (
                'double toned a2 buffalo milk',
                'a2 buffalo milk double toned',
                'double toned milk'
            ) THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN (
                'a2 buffalo milk', 'buffalo_milk', 'buffalo milk'
            ) THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('cow_milk', 'cow milk')
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN (
                'a2 desi cow milk', 'a2 cow milk', 'desi cow milk'
            ) THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('skim_milk', 'skim milk')
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) IN ('toned_milk', 'toned milk')
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(pp.name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(pp.name, E'\t', ''))
        END AS product_name
    FROM candidate_orders toi
    CROSS JOIN target t
    JOIN product_productvariant pv
        ON pv.id = toi.variant_id
    JOIN product_product pp
        ON pp.id = pv.product_id
    LEFT JOIN customer_address ship_ca
        ON ship_ca.id = toi.shipping_address_id
    LEFT JOIN latest_customer_address ca
        ON ca.cust_id = toi.customer_id
),

row_level AS (
    SELECT n.*
    FROM normalized_orders n
    WHERE n.city_cd IN ('HYD', 'VGA', 'BLR', 'PNQ')
      AND n.product_name IN (
          'A2 Buffalo Milk',
          'A2 Desi Cow Milk',
          'Cow Milk',
          'Double Toned A2 Buffalo Milk',
          'Skim Milk',
          'Toned Milk',
          'Curd'
      )
      AND n.created_at_ist <= (
          n.target_date
          - CASE
                WHEN n.city_cd IN ('HYD', 'VGA') THEN 2
                WHEN n.city_cd IN ('BLR', 'PNQ') THEN 3
            END
          + TIME '22:05'
      )
)

SELECT
    target_date,
    city_cd,
    product_name,
    SUM(qty) AS known_buy_once_qty,
    COUNT(DISTINCT customer_id) AS known_buy_once_orders,
    COUNT(DISTINCT customer_id) AS known_buy_once_customers
FROM row_level
GROUP BY
    target_date,
    city_cd,
    product_name
ORDER BY
    city_cd,
    known_buy_once_qty DESC;
