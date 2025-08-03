import sqlglot
import traceback

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

print("=== TESTING OUTPUT STATEMENT ===")
try:
    result = sqlglot.parse(usql, read="usql")
    print("SUCCESS:", result)
    sparksql = sqlglot.transpile(usql, read="usql", write="spark")[0]
    print("Spark SQL:", sparksql)
except Exception as e:
    print("=== ERROR ===")
    print(e)
    traceback.print_exc()
