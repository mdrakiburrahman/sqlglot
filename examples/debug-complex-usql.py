import sqlglot
from sqlglot.dialects.usql import _convert_usql_to_standard_sql

usql = """

// declare constants
DECLARE CONST @inputFile string = "input.csv";
DECLARE CONST @outputFile string = "output.tsv";


// read from CSV
@input = 
EXTRACT
    Id int,
    Name string,
    Dept string,
    Salary double
FROM @inputFile
USING Extractors.Csv();

/* test block comment
@row = 
SELECT
    Id,
    Name,
    Salary
FROM @input
WHERE Dept == "Computer Science"; */

// filter required rows
@row = 
SELECT
    Id,
    Name,
    Salary
FROM (SELECT * FROM @input)   // wow a nested query
WHERE Dept == "Computer Science";

// output to a TSV file
OUTPUT @row
TO @outputFile
USING Outputters.Tsv(outputHeader: true);
"""

print("=== ORIGINAL USQL ===")
print(usql)
print("\n" + "=" * 80 + "\n")

# First parse the U-SQL
print("=== PARSING USQL ===")
parsed = sqlglot.parse(usql, read="usql")
print(f"Parsed {len(parsed)} expressions")
print("\n" + "=" * 40 + "\n")

# Transform U-SQL constructs to standard SQL
print("=== TRANSFORMED TO STANDARD SQL ===")
transformed = []
for expr in parsed:
    new_expr = _convert_usql_to_standard_sql(expr)
    if not isinstance(new_expr, sqlglot.expressions.Placeholder):
        transformed.append(new_expr)

for expr in transformed:
    print(expr)
print("\n" + "=" * 40 + "\n")

print("=== FORMATTED SPARK SQL ===")
for expr in transformed:
    try:
        spark_sql = sqlglot.transpile(str(expr), read="usql", write="spark", pretty=True)[0]
        print(spark_sql)
        print()
    except Exception as e:
        print(f"Error converting {expr}: {e}")
        print()
