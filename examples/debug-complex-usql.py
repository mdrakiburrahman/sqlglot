import os
import sqlglot
from sqlglot.dialects.usql import _convert_usql_to_standard_sql

BASE_DIR = os.path.dirname(__file__)
SAMPLES_DIRS = [
    os.path.join(BASE_DIR, "samples", "external"),
    os.path.join(BASE_DIR, "samples", "internal"),
]

results = []

for SAMPLES_DIR in SAMPLES_DIRS:
    if not os.path.isdir(SAMPLES_DIR):
        continue
    for filename in os.listdir(SAMPLES_DIR):
        if any(filename.endswith(ext) for ext in [".script", ".view"]):
            filepath = os.path.join(SAMPLES_DIR, filename)
            didsucceed = True
            exception = None
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    usql = f.read()

                print("\n" + "="*80 + "\n")
                print(f"=== ORIGINAL U-SQL: {filename} ({os.path.basename(SAMPLES_DIR)}) ===")
                print("\n" + "="*80 + "\n")
                if len(usql) > 10000:
                    print(usql[:10000] + "\n....")
                else:
                    print(usql)

                parsed = sqlglot.parse(usql, read="usql")
                transformed = []
                for expr in parsed:
                    new_expr = _convert_usql_to_standard_sql(expr)
                    if not isinstance(new_expr, sqlglot.expressions.Placeholder):
                        transformed.append(new_expr)

                print("\n" + "="*80 + "\n")
                print(f"=== CONVERTED SPARK-SQL: {filename} ({os.path.basename(SAMPLES_DIR)}) ===")
                print("\n" + "="*80 + "\n")

                for expr in transformed:
                    try:
                        spark_sql = sqlglot.transpile(str(expr), read="usql", write="spark", pretty=True)[0]
                        print(spark_sql)
                    except Exception as e:
                        didsucceed = False
                        exception = e
                        print("[Failed to transpile]")
                        break

            except Exception as e:
                didsucceed = False
                exception = e

            results.append((f"{os.path.basename(SAMPLES_DIR)}/{filename}", didsucceed, exception))

print("\n" + "="*80 + "\n")
print("=== CONVERSION RESULTS ===")
print("\n" + "="*80 + "\n")
for filename, didsucceed, exception in results:
    if didsucceed:
        print(f"{filename}: Success")
    else:
        print(f"{filename}: Failed")
        print("-"*80)
        print(f"\t: {exception}")
        print("-"*80)
