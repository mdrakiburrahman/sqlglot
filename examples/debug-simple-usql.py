import sqlglot

# Test OUTPUT statement
output_usql = """
OUTPUT @row
TO @outputFile
USING Outputters.Tsv();
"""

print("=== TESTING OUTPUT STATEMENT ===")
try:
    result = sqlglot.parse(output_usql, read="usql")
    print("SUCCESS:", result)
except Exception as e:
    print("ERROR:", e)
