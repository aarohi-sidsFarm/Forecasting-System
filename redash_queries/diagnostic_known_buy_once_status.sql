WITH target AS (
    SELECT
        '{{target_date}}'::date AS target_date,
        ('{{target_date}}'::date - INTERVAL '1 day' + TIME '22:00') AS cutoff_ts_ist
)

SELECT
    toi.status,
    COALESCE(toi.purchase_type, 'NULL') AS purchase_type,
    COALESCE(toi.free_product, false) AS free_product,
    COUNT(*) AS rows,
    SUM(COALESCE(toi.quantity, 0)) AS qty,
    SUM(
        CASE
            WHEN (toi.created_at AT TIME ZONE 'Asia/Kolkata') <= t.cutoff_ts_ist
            THEN COALESCE(toi.quantity, 0)
            ELSE 0
        END
    ) AS qty_before_cutoff,
    MIN(toi.created_at AT TIME ZONE 'Asia/Kolkata') AS min_created_ist,
    MAX(toi.created_at AT TIME ZONE 'Asia/Kolkata') AS max_created_ist
FROM temp_order_item toi
CROSS JOIN target t
WHERE toi.order_date::date = t.target_date
GROUP BY
    toi.status,
    COALESCE(toi.purchase_type, 'NULL'),
    COALESCE(toi.free_product, false)
ORDER BY
    qty DESC;
