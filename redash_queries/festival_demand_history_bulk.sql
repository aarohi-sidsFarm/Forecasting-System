/* Bulk festival demand history export.

   Purpose:
     Export major city-scoped festival demand windows in one Redash run.

   Output:
     festival_name, festival_date, delivery_date, days_from_festival,
     city_cd, product_name, total_quantity, subscription_quantity,
     buy_once_quantity, customer_count

   Window:
     festival_date - 7 days through festival_date + 7 days.

   Notes:
     - Dates below are aligned with the reviewed production festival calendar.
     - Do not merge state-specific rows into one shared date. HYD/VGA and
       BLR/PNQ can observe the same named festival on different dates.
*/

WITH festival_dates AS (
    SELECT *
    FROM (VALUES
        /* 2024 */
        ('Ratha Saptami',        '2024-02-16'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Maha Shivaratri',      '2024-03-08'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Holi',                 '2024-03-25'::date, 'HYD,VGA,BLR,PNQ', 'HIGH', -1),
        ('Ugadi',                '2024-04-09'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Gudi Padwa',           '2024-04-09'::date, 'PNQ',         'HIGH',  0),
        ('Ram Navami',           '2024-04-17'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Hanuman Jayanti',      '2024-04-23'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Akshaya Tritiya',      '2024-05-10'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  0),
        ('Golconda Bonalu',      '2024-07-07'::date, 'HYD',         'HIGH',  0),
        ('Ujjaini Mahakali Bonalu','2024-07-21'::date, 'HYD',       'HIGH',  0),
        ('Lal Darwaza Bonalu',   '2024-07-28'::date, 'HYD',         'HIGH',  0),
        ('Naga Panchami',        '2024-08-09'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Varalakshmi Vratam',   '2024-08-16'::date, 'HYD,VGA,BLR', 'HIGH',  0),
        ('Ganesh Chaturthi',     '2024-09-07'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Saddula Bathukamma',   '2024-10-11'::date, 'HYD',         'HIGH',  0),
        ('Dussehra',             '2024-10-12'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Diwali',               '2024-10-31'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Diwali Laxmi Puja',    '2024-11-01'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Nagula Chavithi',      '2024-11-05'::date, 'HYD,VGA',     'HIGH',  1),

        /* 2025 */
        ('Ratha Saptami',        '2025-02-04'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Maha Shivaratri',      '2025-02-26'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Holi',                 '2025-03-14'::date, 'HYD,VGA,BLR,PNQ', 'HIGH', -1),
        ('Ugadi',                '2025-03-30'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Gudi Padwa',           '2025-03-30'::date, 'PNQ',         'HIGH',  0),
        ('Ram Navami',           '2025-04-06'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Hanuman Jayanti',      '2025-04-12'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Akshaya Tritiya',      '2025-04-30'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  0),
        ('Ujjaini Mahakali Bonalu','2025-07-13'::date, 'HYD',       'HIGH',  0),
        ('Lal Darwaza Bonalu',   '2025-07-20'::date, 'HYD',         'HIGH',  0),
        ('Naga Panchami',        '2025-07-29'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Varalakshmi Vratam',   '2025-08-08'::date, 'HYD,VGA,BLR', 'HIGH',  0),
        ('Ganesh Chaturthi',     '2025-08-27'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Saddula Bathukamma',   '2025-09-30'::date, 'HYD',         'HIGH',  0),
        ('Dussehra',             '2025-10-02'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Diwali',               '2025-10-20'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Nagula Chavithi',      '2025-10-25'::date, 'HYD,VGA',     'HIGH',  1),

        /* 2026 */
        ('Ratha Saptami',        '2026-01-25'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Maha Shivaratri',      '2026-02-15'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Holi',                 '2026-03-03'::date, 'HYD,VGA,PNQ', 'HIGH', -1),
        ('Holi',                 '2026-03-04'::date, 'BLR',         'HIGH', -1),
        ('Ugadi',                '2026-03-19'::date, 'HYD,VGA,BLR', 'HIGH',  1),
        ('Gudi Padwa',           '2026-03-19'::date, 'PNQ',         'HIGH',  0),
        ('Ram Navami',           '2026-03-26'::date, 'BLR,PNQ',     'HIGH',  1),
        ('Ram Navami',           '2026-03-27'::date, 'HYD,VGA',     'HIGH',  1),
        ('Hanuman Jayanti',      '2026-04-02'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Akshaya Tritiya',      '2026-04-19'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  0),
        ('Ujjaini Mahakali Bonalu','2026-08-02'::date, 'HYD',       'HIGH',  0),
        ('Lal Darwaza Bonalu',   '2026-08-09'::date, 'HYD',         'HIGH',  0),
        ('Naga Panchami',        '2026-08-17'::date, 'HYD,VGA,BLR,PNQ', 'MED',   0),
        ('Varalakshmi Vratam',   '2026-08-21'::date, 'HYD,VGA',     'HIGH',  0),
        ('Varamahalakshmi Vrata','2026-08-28'::date, 'BLR',         'HIGH',  0),
        ('Ganesh Chaturthi',     '2026-09-14'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Saddula Bathukamma',   '2026-10-18'::date, 'HYD',         'HIGH',  0),
        ('Dussehra',             '2026-10-20'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Diwali',               '2026-11-08'::date, 'HYD,VGA,BLR,PNQ', 'HIGH',  1),
        ('Nagula Chavithi',      '2026-11-13'::date, 'HYD,VGA',     'HIGH',  1)
    ) AS v(festival_name, festival_date, festival_cities, impact, impact_direction)
),

festival_windows AS (
    SELECT
        festival_name,
        festival_date,
        festival_cities,
        impact,
        impact_direction,
        festival_date - INTERVAL '7 days' AS start_date,
        festival_date + INTERVAL '7 days' AS end_date
    FROM festival_dates
),

row_level AS (
    SELECT
        fw.festival_name,
        fw.festival_date,
        fw.impact,
        fw.impact_direction,
        f.delivery_date::date AS delivery_date,
        (f.delivery_date::date - fw.festival_date) AS days_from_festival,
        UPPER(TRIM(f.customer_city)) AS city_cd,
        CASE
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'double toned a2 buffalo milk',
                'a2 buffalo milk double toned',
                'double toned milk'
            )
                THEN 'Double Toned A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'a2 buffalo milk',
                'buffalo_milk',
                'buffalo milk'
            )
                THEN 'A2 Buffalo Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'cow_milk',
                'cow milk'
            )
                THEN 'Cow Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'a2 desi cow milk',
                'a2 cow milk',
                'desi cow milk'
            )
                THEN 'A2 Desi Cow Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'skim_milk',
                'skim milk'
            )
                THEN 'Skim Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) IN (
                'toned_milk',
                'toned milk'
            )
                THEN 'Toned Milk'
            WHEN LOWER(TRIM(REPLACE(f.product_name, E'\t', ''))) = 'curd'
                THEN 'Curd'
            ELSE TRIM(REPLACE(f.product_name, E'\t', ''))
        END AS product_name,
        CASE
            WHEN f.purchase_type ILIKE '%subscription%' THEN 'subscription'
            ELSE 'buy_once'
        END AS demand_source,
        f.order_volume::numeric AS qty,
        f.customer_id
    FROM festival_windows fw
    JOIN d2c_order_newfact f
      ON f.delivery_date::date BETWEEN fw.start_date::date AND fw.end_date::date
    WHERE f.status IN ('CONFIRMED', 'DELIVERED')
      AND COALESCE(f.order_volume, 0) > 0
      AND UPPER(TRIM(f.customer_city)) IN ('HYD', 'BLR')
      AND fw.festival_cities ILIKE '%' || UPPER(TRIM(f.customer_city)) || '%'
      AND f.product_name NOT ILIKE '%sample%'
      AND f.product_name NOT ILIKE '%test%'
      AND (
            f.purchase_type ILIKE '%subscription%'
            OR f.purchase_type IN ('Buy Once', 'Adhoc Buy Once', 'FIRST_X_ORDER')
            OR f.purchase_type ILIKE '%buy once%'
            OR f.purchase_type IS NULL
          )
)

SELECT
    EXTRACT(YEAR FROM delivery_date)::int AS delivery_year,
    festival_name,
    festival_date,
    impact,
    impact_direction,
    delivery_date,
    days_from_festival,
    city_cd,
    product_name,
    SUM(qty) AS total_quantity,
    SUM(CASE WHEN demand_source = 'subscription' THEN qty ELSE 0 END) AS subscription_quantity,
    SUM(CASE WHEN demand_source = 'buy_once' THEN qty ELSE 0 END) AS buy_once_quantity,
    COUNT(DISTINCT customer_id) AS customer_count
FROM row_level
WHERE product_name IN (
    'A2 Buffalo Milk',
    'A2 Desi Cow Milk',
    'Cow Milk',
    'Double Toned A2 Buffalo Milk',
    'Skim Milk',
    'Toned Milk',
    'Curd'
)
GROUP BY
    EXTRACT(YEAR FROM delivery_date)::int,
    festival_name,
    festival_date,
    impact,
    impact_direction,
    delivery_date,
    days_from_festival,
    city_cd,
    product_name
ORDER BY
    festival_date,
    delivery_date,
    city_cd,
    product_name;
