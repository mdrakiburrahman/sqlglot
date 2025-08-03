import sqlglot

usql = """
WITH t1(c)
     AS (SELECT 1),
     t2
     AS (SELECT Cast(c AS INTEGER) AS c
         FROM   t1)
SELECT *
FROM   t2 
"""

print("=== ORIGINAL USQL ===")
print(usql)
print("\n" + "=" * 80 + "\n")
print("=== FORMATTED SPARK SQL ===")
formatted_spark = sqlglot.transpile(usql, read="usql", write="spark", pretty=True)[0]
print(formatted_spark)
