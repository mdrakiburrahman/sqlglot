import os
import sqlglot
from sqlglot.dialects.usql import _convert_usql_to_standard_sql

SAMPLES_EXTERNAL_DIR = os.path.join(os.path.dirname(__file__), "samples", "external")

results = []

for filename in os.listdir(SAMPLES_EXTERNAL_DIR):
    if filename.endswith(".script"):
        filepath = os.path.join(SAMPLES_EXTERNAL_DIR, filename)
        didsucceed = True
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                usql = f.read()

            parsed = sqlglot.parse(usql, read="usql")
            transformed = []
            for expr in parsed:
                new_expr = _convert_usql_to_standard_sql(expr)
                if not isinstance(new_expr, sqlglot.expressions.Placeholder):
                    transformed.append(new_expr)

            print("\n" + "="*80 + "\n")
            print(f"=== ORIGINAL U-SQL: {filename} ===")
            print("\n" + "="*80 + "\n")
            print(usql)
            print("\n" + "="*80 + "\n")
            print("=== CONVERTED SPARK-SQL ===")
            print("\n" + "="*80 + "\n")

            for expr in transformed:
                try:
                    spark_sql = sqlglot.transpile(str(expr), read="usql", write="spark", pretty=True)[0]
                    print(spark_sql)
                except Exception:
                    didsucceed = False
                    print("[Failed to transpile]")
                    break

        except Exception:
            didsucceed = False

        results.append((filename, didsucceed))

print("\n" + "="*80 + "\n")
print("=== CONVERSION RESULTS ===")
print("\n" + "="*80 + "\n")
for filename, didsucceed in results:
    print(f"{filename}: {'Success' if didsucceed else 'Failed'}")
