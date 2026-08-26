/* Diagnostic only: new buy-once demand arriving after forecast issue date.

   Example for target_date 2026-08-26:
     HYD/VGA issue on 2026-08-24, so this reports arrivals on 2026-08-25.
     BLR/PNQ issue on 2026-08-23, so this reports arrivals on 24 and 25 Aug.

   This current-state query measures rows by their creation date. It cannot
   reconstruct later edits, deletions, or the historical status of an order.
*/

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
),

normalized_orders AS (
    SELECT
        t.target_date,
        toi.customer_id,
        toi.quantity::numeric AS qty,
        (toi.created_at AT TIME ZONE 'Asia/Kolkata')::date AS placed_date,
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
        ORDER BY cust_id, updated_at DESC NULLS LAST, id DESC
    ) ca
        ON ca.cust_id = toi.customer_id
    WHERE toi.order_date::date = t.target_date
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

with_issue_date AS (
    SELECT
        n.*,
        CASE WHEN n.city_cd IN ('HYD', 'VGA') THEN 2 ELSE 3 END AS lead_time_days,
        n.target_date
            - CASE WHEN n.city_cd IN ('HYD', 'VGA') THEN 2 ELSE 3 END
            AS issue_date
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
)

SELECT
    target_date,
    issue_date,
    lead_time_days,
    placed_date,
    placed_date - issue_date AS days_after_issue,
    target_date - placed_date AS days_before_target,
    city_cd,
    product_name,
    SUM(qty) AS new_buy_once_qty,
    COUNT(*) AS new_buy_once_line_count,
    COUNT(DISTINCT customer_id) AS new_buy_once_customers
FROM with_issue_date
WHERE placed_date > issue_date
  AND placed_date < target_date
GROUP BY
    target_date,
    issue_date,
    lead_time_days,
    placed_date,
    city_cd,
    product_name
ORDER BY
    placed_date,
    city_cd,
    new_buy_once_qty DESC;
