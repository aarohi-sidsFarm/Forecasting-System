/* Use this first to confirm final actual statuses in order_order_item.
   Final rows live in order_item joined to "order" for delivery date/city. */

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
)

SELECT
    ooi.status,
    COALESCE(ooi.purchase_type, 'NULL') AS purchase_type,
    COALESCE(ooi.free_product, false) AS free_product,
    COUNT(*) AS rows,
    SUM(COALESCE(ooi.quantity, 0)) AS qty,
    MIN(ooi.created_at AT TIME ZONE 'Asia/Kolkata') AS min_created_ist,
    MAX(ooi.created_at AT TIME ZONE 'Asia/Kolkata') AS max_created_ist,
    MIN(ooi.updated_at AT TIME ZONE 'Asia/Kolkata') AS min_updated_ist,
    MAX(ooi.updated_at AT TIME ZONE 'Asia/Kolkata') AS max_updated_ist
FROM order_item ooi
JOIN "order" o
    ON o.id = ooi.order_id
CROSS JOIN target t
WHERE o.expected_delivery_date::date = t.target_date
GROUP BY
    ooi.status,
    COALESCE(ooi.purchase_type, 'NULL'),
    COALESCE(ooi.free_product, false)
ORDER BY
    qty DESC;
