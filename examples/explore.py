import sqlglot

spark_sql = """
WITH customer_metrics AS (
    -- Customer-level aggregations with window functions
    SELECT 
        customer_id,
        region,
        COLLECT_LIST(order_date) AS order_dates,
        COUNT(*) AS total_orders,
        SUM(order_value) AS total_spent,
        AVG(order_value) AS avg_order_value,
        ROW_NUMBER() OVER (PARTITION BY region ORDER BY SUM(order_value) DESC) AS customer_rank,
        DATEDIFF('2024-01-01', MAX(order_date)) AS days_since_last_order,
        PERCENTILE_APPROX(order_value, 0.5) AS median_order_value,
        ARRAY_JOIN(COLLECT_SET(product_category), ',') AS categories_purchased
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE order_date >= DATE_SUB('2024-01-01', 365)
        AND order_value > 0
    GROUP BY customer_id, region
),
product_performance AS (
    -- Product performance with complex aggregations
    SELECT 
        product_id,
        product_category,
        COUNT(DISTINCT customer_id) AS unique_customers,
        SUM(quantity * unit_price) AS total_revenue,
        STDDEV(quantity * unit_price) AS revenue_std_dev,
        MAP_FROM_ARRAYS(
            COLLECT_LIST(MONTH(order_date)),
            COLLECT_LIST(SUM(quantity))
        ) AS monthly_quantities,
        CASE 
            WHEN COUNT(*) >= 100 THEN 'High Volume'
            WHEN COUNT(*) >= 50 THEN 'Medium Volume'
            ELSE 'Low Volume'
        END AS volume_category,
        UNIX_TIMESTAMP() - UNIX_TIMESTAMP(MAX(order_date)) AS seconds_since_last_sale
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.id
    JOIN products p ON oi.product_id = p.id
    WHERE o.order_date BETWEEN DATE_SUB(CURRENT_DATE(), 180) AND CURRENT_DATE()
        AND oi.quantity > 0
    GROUP BY product_id, product_category
),
regional_summary AS (
    -- Regional performance summary with advanced analytics
    SELECT 
        cm.region,
        COUNT(DISTINCT cm.customer_id) AS active_customers,
        SUM(cm.total_spent) AS region_revenue,
        AVG(cm.avg_order_value) AS avg_regional_order_value,
        APPROX_COUNT_DISTINCT(pp.product_id) AS distinct_products_sold,
        STRUCT(
            MIN(cm.total_spent) AS min_customer_value,
            MAX(cm.total_spent) AS max_customer_value,
            STDDEV(cm.total_spent) AS customer_value_std
        ) AS customer_value_stats,
        EXPLODE(ARRAY(
            NAMED_STRUCT('metric', 'total_customers', 'value', COUNT(DISTINCT cm.customer_id)),
            NAMED_STRUCT('metric', 'total_revenue', 'value', SUM(cm.total_spent))
        )) AS metrics_exploded
    FROM customer_metrics cm
    LEFT JOIN product_performance pp ON 1=1  -- Cross join for analysis
    WHERE cm.customer_rank <= 100  -- Top 100 customers per region
    GROUP BY cm.region
)
-- Final output with JSON aggregation and complex transformations
SELECT 
    rs.region,
    rs.active_customers,
    rs.region_revenue,
    ROUND(rs.avg_regional_order_value, 2) AS avg_order_value_rounded,
    rs.distinct_products_sold,
    TO_JSON(rs.customer_value_stats) AS customer_stats_json,
    ARRAY_JOIN(
        TRANSFORM(
            FILTER(
                COLLECT_LIST(cm.customer_id), 
                x -> cm.total_spent > rs.avg_regional_order_value * 10
            ),
            x -> CONCAT('CUST_', CAST(x AS STRING))
        ),
        '|'
    ) AS high_value_customers,
    CASE 
        WHEN rs.region_revenue > 1000000 THEN 'Tier 1'
        WHEN rs.region_revenue > 500000 THEN 'Tier 2'
        ELSE 'Tier 3'
    END AS region_tier,
    CURRENT_TIMESTAMP() AS report_generated_at,
    DATE_FORMAT(CURRENT_DATE(), 'yyyy-MM-dd') AS report_date
FROM regional_summary rs
LEFT JOIN customer_metrics cm ON rs.region = cm.region
WHERE rs.region_revenue > 10000
    AND rs.active_customers >= 5
GROUP BY rs.region, rs.active_customers, rs.region_revenue, 
         rs.avg_regional_order_value, rs.distinct_products_sold, 
         rs.customer_value_stats
ORDER BY rs.region_revenue DESC, rs.active_customers DESC
LIMIT 50
"""

fabric_sql = sqlglot.transpile(spark_sql, read="spark", write="fabric")[0]

print("=== ORIGINAL SPARK SQL ===")
print(spark_sql)
print("\n" + "="*80 + "\n")
print("=== FORMATTED FABRIC SQL ===")
formatted_fabric = sqlglot.transpile(spark_sql, read="spark", write="fabric", pretty=True)[0]
print(formatted_fabric)