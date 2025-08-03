import sqlglot
from sqlglot.dialects.usql import _convert_usql_to_standard_sql

usql = """

CREATE VIEW SearchLog
SCHEMA
(
    IId : int,
    UId : int,
    TimeStamp : DateTime,
    Market : string,
    Query : string,
    DwellTime : int,
    Results : string,
    ClickedUrls : string
)
PARAMS
(
    start string,
    end string
)
AS
BEGIN
    
    searchlog = EXTRACT IId:int, UId:int, TimeStamp:DateTime, Market:string, Query:string, DwellTime:int, Results:string, ClickedUrls:string
        FROM @"my/ScopeTutorial/SampleInputs/SearchLog.txt"
        USING DefaultTextExtractor();
    
    filtered_searchlog =
        SELECT *
        FROM searchlog
        WHERE TimeStamp >= DateTime.Parse(@start) AND TimeStamp <= DateTime.Parse(@end);
END;

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
