import sqlglot
from sqlglot.dialects.usql import USQL

simple_usql = """@input = 
EXTRACT
    Id int
FROM @inputFile
USING Extractors.Csv();"""

print("=== TOKENIZING EXTRACT STATEMENT ===")
tokenizer = USQL.Tokenizer()
tokens = tokenizer.tokenize(simple_usql)

for i, token in enumerate(tokens):
    print(f"{i}: {token.token_type} | '{token.text}'")
