/* Product mapping diagnostic for selected-date actuals.

   Run this when the API actuals do not match the team sheet by product.

   Parameters:
     target_date

   What to inspect:
     - raw_product_name: product_product.name
     - raw_variant_name: product_productvariant.name if present in your DB
     - variant_id
     - purchase_type/status quantity by HYD

   If Redash fails because product_productvariant has no "name" column, remove
   pv.name from SELECT/GROUP BY and rerun.
*/

WITH target AS (
    SELECT '{{target_date}}'::date AS target_date
)

SELECT
    UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) AS city_cd,
    pp.name AS raw_product_name,
    pv.id AS variant_id,
    pv.name AS raw_variant_name,
    ooi.status,
    COALESCE(ooi.purchase_type, 'NULL') AS purchase_type,
    COALESCE(ooi.free_product, false) AS free_product,
    COUNT(*) AS rows,
    SUM(COALESCE(ooi.quantity, 0)) AS qty,
    COUNT(DISTINCT o.customer_id) AS customers
FROM order_item ooi
JOIN "order" o
    ON o.id = ooi.order_id
CROSS JOIN target t
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
WHERE o.expected_delivery_date::date = t.target_date
  AND UPPER(TRIM(COALESCE(o.city_cd, ship_ca.city_cd, ca.city_cd, 'UNKNOWN'))) = 'HYD'
  AND ooi.status IN ('CONFIRMED', 'DELIVERED')
  AND COALESCE(ooi.quantity, 0) > 0
  AND COALESCE(ooi.free_product, false) = false
GROUP BY
    city_cd,
    pp.name,
    pv.id,
    pv.name,
    ooi.status,
    COALESCE(ooi.purchase_type, 'NULL'),
    COALESCE(ooi.free_product, false)
ORDER BY
    qty DESC;
