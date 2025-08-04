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
    start string DEFAULT = "2023-01-01T00:00:00Z",
    end string
)
AS
BEGIN

    #DECLARE potato string = @"Crispy";
    #DECLARE tomato string = @"Crunchy";
    #DECLARE startDateOffset int = 0;
    #DECLARE endDateOffset int = 0;

    #DECLARE potatoViewFullPath string = string.Format("{0}local/Potato/Sandbox/Views/Public/{1}.view", @potato, @start);
    
    searchlog = EXTRACT IId:int, UId:int, TimeStamp:DateTime, Market:string, Query:string, DwellTime:int, Results:string, ClickedUrls:string
        FROM @"my/ScopeTutorial/SampleInputs/SearchLog.txt"
        USING DefaultTextExtractor();

    potato_snapshot = VIEW @potatoViewFullPath
    PARAMS
    (
        startDate = DateTime.Parse(@start).AddDays(@startDateOffset).ToString("yyyy-MM-dd"),
        endDate = DateTime.Parse(@end).AddDays(@endDateOffset).ToString("yyyy-MM-dd"),
        tomato = @tomato
    );
    #IF(!LOCAL)
        #DECLARE tomatoViewFullPath string = string.Format("{0}local/Tomato/Sandbox/Views/Public/{1}.view", @tomato, @start);
    #ENDIF
    
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
    sparksql = sqlglot.transpile(usql, read="usql", write="spark", pretty=True)
    print("=== USQL ===")
    print(usql)
    print("=== SPARK SQL ===")
    for i, stmt in enumerate(sparksql, 1):
        print(stmt)
except Exception as e:
    print("=== ERROR ===")
    print(e)
    traceback.print_exc()
