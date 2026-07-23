WITH target AS (
    SELECT
        '{{target_date}}'::date AS target_date,
        ('{{target_date}}'::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
)

SELECT
    toi.order_date::date AS order_date,
    toi.status,
    COALESCE(toi.purchase_type, 'NULL') AS purchase_type,
    COALESCE(toi.free_product, false) AS free_product,
    COUNT(*) AS rows,
    SUM(COALESCE(toi.quantity, 0)) AS qty,
    MIN(toi.created_at AT TIME ZONE 'Asia/Kolkata') AS min_created_ist,
    MAX(toi.created_at AT TIME ZONE 'Asia/Kolkata') AS max_created_ist
FROM temp_order_item toi
CROSS JOIN target t
WHERE (toi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.cutoff_ts_ist
  AND toi.order_date::date BETWEEN t.target_date - INTERVAL '1 day'
                               AND t.target_date + INTERVAL '1 day'
GROUP BY
    toi.order_date::date,
    toi.status,
    COALESCE(toi.purchase_type, 'NULL'),
    COALESCE(toi.free_product, false)
ORDER BY
    order_date,
    qty DESC;
