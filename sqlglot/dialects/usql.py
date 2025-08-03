from __future__ import annotations

import typing as t

from sqlglot import exp, parser, transforms
from sqlglot.dialects.dialect import NormalizationStrategy
from sqlglot.dialects.tsql import TSQL
from sqlglot.tokens import TokenType

def _convert_usql_to_standard_sql(expression: exp.Expression) -> exp.Expression:
    """Transform U-SQL specific constructs to standard SQL equivalents"""
    if isinstance(expression, USqlDeclareConst):
        # Skip constant declarations - they can be inlined later
        return exp.Placeholder()
    
    elif isinstance(expression, USqlAssignment):
        # Convert @var = EXTRACT/SELECT to a CTE or view
        if isinstance(expression.expression, USqlExtract):
            # Convert EXTRACT to SELECT from file
            extract = expression.expression
            columns = [exp.alias_(col.this, col.this) for col in extract.expressions]
            from_clause = extract.args.get("from")
            
            # Create a SELECT statement that reads from the file
            select = exp.Select(
                expressions=columns,
                **{"from": exp.From(this=from_clause)}
            )
            return select
        else:
            # Regular assignment - just return the expression
            return expression.expression
    
    elif isinstance(expression, USqlExtract):
        # Convert standalone EXTRACT to SELECT
        columns = [exp.alias_(col.this, col.this) for col in expression.expressions]  
        from_clause = expression.args.get("from")
        
        return exp.Select(
            expressions=columns,
            **{"from": exp.From(this=from_clause)}
        )
    
    elif isinstance(expression, USqlOutput):
        # Convert OUTPUT to INSERT or CREATE TABLE AS SELECT
        source = expression.this
        destination = expression.args.get("to")
        
        # For now, convert to INSERT statement  
        return exp.Insert(
            this=destination,
            expression=source if isinstance(source, exp.Select) else exp.Select(expressions=[source])
        )
    
    return expression


# U-SQL specific expressions
class USqlExtract(exp.Expression):
    """U-SQL EXTRACT statement: @variable = EXTRACT columns FROM source USING extractor;"""
    arg_types = {
        "this": True,  # variable being assigned to 
        "expressions": True,  # column definitions
        "from": True,  # source file/table
        "using": True,  # extractor function
    }


class USqlOutput(exp.Expression):
    """U-SQL OUTPUT statement: OUTPUT @variable TO destination USING outputter;"""
    arg_types = {
        "this": True,  # variable/query to output
        "to": True,  # destination file/table
        "using": True,  # outputter function
    }


class USqlAssignment(exp.Expression):
    """U-SQL variable assignment: @variable = SELECT/query;"""
    arg_types = {
        "this": True,  # variable being assigned to
        "expression": True,  # the SELECT query or other expression
    }


class USqlDeclareConst(exp.Expression):
    """U-SQL constant declaration: DECLARE CONST @variable type = value;"""
    arg_types = {
        "this": True,  # variable name
        "kind": True,  # data type
        "default": False,  # default value
    }


class USqlCreateView(exp.Expression):
    """U-SQL CREATE VIEW with SCHEMA and PARAMS: CREATE VIEW name SCHEMA (...) PARAMS (...) AS BEGIN ... END"""
    arg_types = {
        "this": True,  # view name
        "schema": False,  # schema definition (column list)
        "params": False,  # parameters definition
        "expression": True,  # view body (AS BEGIN ... END)
    }


class USqlHashDeclare(exp.Expression):
    """U-SQL hash declare: #DECLARE variable type = value;"""
    arg_types = {
        "this": True,  # variable name
        "kind": True,  # data type
        "default": False,  # default value
    }


class USqlIfDirective(exp.Expression):
    """U-SQL conditional compilation: #IF(condition) ... #ENDIF"""
    arg_types = {
        "this": True,  # condition
        "expression": False,  # body
    }


class USqlViewInvocation(exp.Expression):
    """U-SQL view invocation: variable = VIEW @path PARAMS (...);"""
    arg_types = {
        "this": True,  # view path (identifier/parameter)
        "params": False,  # parameters passed to view
    }


def _cap_data_type_precision(expression: exp.DataType, max_precision: int = 6) -> exp.DataType:
    """
    Cap the precision of to a maximum of `max_precision` digits.
    If no precision is specified, default to `max_precision`.
    """

    precision_param = expression.find(exp.DataTypeParam)

    if precision_param and precision_param.this.is_int:
        current_precision = precision_param.this.to_py()
        target_precision = min(current_precision, max_precision)
    else:
        target_precision = max_precision

    return exp.DataType(
        this=expression.this,
        expressions=[exp.DataTypeParam(this=exp.Literal.number(target_precision))],
    )


def _convert_usql_create_view_to_standard(expression: exp.Expression) -> exp.Expression:
    """Convert USqlCreateView to standard Create expression for transpilation"""
    if isinstance(expression, USqlCreateView):
        # Extract the view body and convert to a standard SELECT
        body = expression.args.get("expression")
        if body and len(body) > 0:
            # Look for the LAST meaningful SELECT statement in the body
            # U-SQL views typically end with a final SELECT that represents the view output
            select_stmt = None
            
            # Iterate through body in reverse to find the last meaningful statement
            for stmt in reversed(body):
                if isinstance(stmt, exp.Select):
                    select_stmt = stmt
                    break
                elif isinstance(stmt, USqlAssignment):
                    # For assignments, check what the expression is
                    if isinstance(stmt.expression, exp.Select):
                        # This is a variable assignment with a SELECT - use this
                        select_stmt = stmt.expression
                        break
                    elif isinstance(stmt.expression, USqlExtract):
                        # This is an EXTRACT assignment - convert to SELECT but keep looking
                        # for a later SELECT (EXTRACT is usually intermediate, not final)
                        extract = stmt.expression
                        if hasattr(extract, 'expressions') and extract.expressions:
                            columns = [exp.alias_(col.this, col.this) for col in extract.expressions]
                            from_clause = extract.args.get("from")
                            fallback_select = exp.Select(
                                expressions=columns,
                                **{"from": exp.From(this=from_clause)}
                            )
                            # Only use this if we don't find a better SELECT later
                            if not select_stmt:
                                select_stmt = fallback_select
            
            # Only use placeholder as absolute last resort
            if not select_stmt:
                select_stmt = exp.Select(expressions=[exp.Star()])
            
            # Create a standard CREATE VIEW expression
            return exp.Create(
                this=expression.this,  # view name
                kind="VIEW",
                expression=select_stmt,
                replace=False,
                temporary=False
            )
    
    elif isinstance(expression, USqlAssignment):
        # Convert USqlAssignment to just its expression (typically a SELECT)
        # But first ensure the nested expression is also transformed
        nested_expr = expression.expression
        if isinstance(nested_expr, (USqlExtract, USqlOutput, USqlCreateView)):
            nested_expr = _convert_usql_create_view_to_standard(nested_expr)
        elif isinstance(nested_expr, USqlViewInvocation):
            # For view invocations, use the assignment variable name as the table name
            var_name = expression.this
            if hasattr(var_name, 'this'):
                table_name = var_name.this
            elif hasattr(var_name, 'name'):
                table_name = var_name.name
            else:
                table_name = str(var_name)
            
            nested_expr = exp.Select(
                expressions=[exp.Star()],
                **{"from": exp.From(this=exp.Table(this=table_name))}
            )
        return nested_expr
    
    elif isinstance(expression, USqlExtract):
        # Convert EXTRACT to SELECT from file
        columns = [exp.alias_(col.this, col.this) for col in expression.expressions]
        from_clause = expression.args.get("from")
        
        # Create a SELECT statement that reads from the file
        return exp.Select(
            expressions=columns,
            **{"from": exp.From(this=from_clause)}
        )
    
    elif isinstance(expression, USqlOutput):
        # Convert OUTPUT to INSERT or CREATE TABLE AS SELECT
        source = expression.this
        destination = expression.args.get("to")
        
        # For now, convert to INSERT statement  
        return exp.Insert(
            this=destination,
            expression=source if isinstance(source, exp.Select) else exp.Select(expressions=[source])
        )
    
    elif isinstance(expression, USqlViewInvocation):
        # Convert view invocation to a placeholder SELECT for now
        # In a real implementation, this would need to resolve the view definition
        # and substitute parameters, but for now we'll create a dummy SELECT
        # Use the view path as the table name if available
        view_path = expression.this
        if hasattr(view_path, 'this'):
            table_name = view_path.this
        elif hasattr(view_path, 'name'):
            table_name = view_path.name
        else:
            table_name = str(view_path) if view_path else "view_placeholder"
        
        return exp.Select(
            expressions=[exp.Star()],
            **{"from": exp.From(this=exp.Table(this=table_name))}
        )
    
    elif isinstance(expression, (USqlDeclareConst, USqlHashDeclare)):
        # U-SQL constant and hash declarations are preprocessing directives
        # Return as-is, they will be filtered out at the parser level
        return expression
    
    elif isinstance(expression, USqlIfDirective):
        # U-SQL #IF directives are conditional compilation
        # Return as-is, they will be filtered out at the parser level
        return expression
    
    return expression


def _add_default_precision_to_varchar(expression: exp.Expression) -> exp.Expression:
    """Transform function to add VARCHAR(MAX) or CHAR(MAX) for cross-dialect conversion."""
    if (
        isinstance(expression, exp.Create)
        and expression.kind == "TABLE"
        and isinstance(expression.this, exp.Schema)
    ):
        for column in expression.this.expressions:
            if isinstance(column, exp.ColumnDef):
                column_type = column.kind
                if (
                    isinstance(column_type, exp.DataType)
                    and column_type.this in (exp.DataType.Type.VARCHAR, exp.DataType.Type.CHAR)
                    and not column_type.expressions
                ):
                    # For transpilation, VARCHAR/CHAR without precision becomes VARCHAR(MAX)/CHAR(MAX)
                    column_type.set("expressions", [exp.var("MAX")])

    return expression


class USQL(TSQL):
    """
    U-SQL is a Data Processing language modelled after T-SQL with a small subset
    of transformation surface area.

    Azure Data Lake Analytics (ADLA) is a distributed analytics service built 
    on Apache YARN. Included with ADLA is a language called U-SQL, which has
    similarities to HiveQL and T-SQL.

    References:
    - Homepage: https://azure.github.io/usql/
    - References: https://github.com/Azure/USQL
    - Launch blog: https://devblogs.microsoft.com/visualstudio/introducing-u-sql-a-language-that-makes-big-data-processing-easy/
    - Getting started: https://azure.microsoft.com/en-us/blog/get-started-with-u-sql-it-s-easy/
    """

    # Fabric is case-sensitive unlike T-SQL which is case-insensitive
    NORMALIZATION_STRATEGY = NormalizationStrategy.CASE_SENSITIVE

    class Tokenizer(TSQL.Tokenizer):
        # U-SQL supports // single-line comments in addition to -- and /* */
        COMMENTS = ["--", "//", ("/*", "*/")]
        
        # Override T-SQL tokenizer to handle TIMESTAMP differently
        # In T-SQL, TIMESTAMP is a synonym for ROWVERSION, but in U-SQL we want it to be a datetime type
        # Also add UTINYINT keyword mapping since T-SQL doesn't have it
        KEYWORDS = {
            **TSQL.Tokenizer.KEYWORDS,
            "BOOL": TokenType.BOOLEAN,
            "CONST": TokenType.CONSTRAINT,  # Reuse existing token 
            "DATETIME": TokenType.DATETIME,
            "EXTRACT": TokenType.VAR,  # Treat as identifier, not command
            "GUID": TokenType.UUID,  # Use UUID token for GUID
            "OUTPUT": TokenType.VAR,   # Treat as identifier, not command  
            "PARAMS": TokenType.VAR,  # Treat as identifier, not command
            "SCHEMA": TokenType.SCHEMA,
            "STRING": TokenType.VARCHAR,  # U-SQL string type
            "TIMESTAMP": TokenType.TIMESTAMP,
            "USING": TokenType.USING,
            "UTINYINT": TokenType.UTINYINT,
        }

        # Add == as equality operator (in addition to =)
        def _scan_num(self) -> bool:
            # Check for == operator first before numbers
            if self._match("=="):
                self._advance(2)
                self._add_token(TokenType.EQ)
                return True
            return super()._scan_num()

        def _scan_operator(self) -> bool:
            # Override to handle == operator
            if self._match("=="):
                self._advance(2)
                self._add_token(TokenType.EQ)
                return True
            return super()._scan_operator()

        def _scan_var(self) -> bool:
            # Handle #DECLARE and other # directives
            if self._match("#"):
                start_index = self._index
                self._advance()
                if self._match_text_seq("DECLARE"):
                    self._add_token(TokenType.PRAGMA, "#DECLARE")
                    return True
                elif self._match_text_seq("IF"):
                    self._add_token(TokenType.PRAGMA, "#IF")
                    return True
                elif self._match_text_seq("ENDIF"):
                    self._add_token(TokenType.PRAGMA, "#ENDIF")
                    return True
                else:
                    # Just a # symbol, reset position and let parent handle it
                    self._index = start_index
            
            return super()._scan_var()

    class Parser(TSQL.Parser):
        # Add post-processing to convert USql expressions to standard SQL for transpilation
        def parse(
            self,
            sql: str | exp.Expression,
            *args,
            **kwargs,
        ) -> t.List[t.Optional[exp.Expression]]:
            expressions = super().parse(sql, *args, **kwargs)
            
            # Apply transformations for cross-dialect compatibility
            transformed_expressions = []
            for expression in expressions:
                if expression:
                    transformed = self._transform_usql_to_standard(expression)
                    # Filter out U-SQL directives that don't have SQL equivalents
                    if transformed and not isinstance(transformed, (USqlDeclareConst, USqlHashDeclare, USqlIfDirective)):
                        transformed_expressions.append(transformed)
                else:
                    transformed_expressions.append(expression)
            
            return transformed_expressions
        
        def _transform_usql_to_standard(self, expression: exp.Expression) -> exp.Expression:
            """Transform U-SQL specific expressions to standard SQL for transpilation"""
            return expression.transform(_convert_usql_create_view_to_standard)

        # U-SQL specific parsing functions
        def _parse_statement(self) -> t.Optional[exp.Expression]:
            # Check for U-SQL specific statements first
            
            # Handle CREATE VIEW with SCHEMA (U-SQL specific) - look ahead to find SCHEMA keyword
            if (self._curr and self._curr.token_type == TokenType.CREATE and
                self._next and self._next.token_type == TokenType.VIEW):
                # Look ahead to see if SCHEMA appears within next few tokens
                has_schema = False
                for i in range(2, min(6, len(self._tokens) - self._index)):
                    if (self._index + i < len(self._tokens) and 
                        self._tokens[self._index + i].token_type == TokenType.SCHEMA):
                        has_schema = True
                        break
                
                if has_schema:
                    return self._parse_usql_create_view()
            
            # Handle #DECLARE directive (HASH + DECLARE tokens)
            if (self._curr and self._curr.token_type == TokenType.HASH and
                self._next and self._next.token_type == TokenType.DECLARE):
                self._advance()  # consume HASH
                self._advance()  # consume DECLARE
                return self._parse_usql_hash_declare()
            
            # Handle #DECLARE directive (single PRAGMA token - fallback)
            if self._curr and self._curr.token_type == TokenType.PRAGMA and self._curr.text == "#DECLARE":
                self._advance()  # consume #DECLARE
                return self._parse_usql_hash_declare()
            
            # Handle #IF directive
            if self._curr and self._curr.token_type == TokenType.PRAGMA and self._curr.text == "#IF":
                self._advance()  # consume #IF
                return self._parse_usql_if_directive()
            
            # Check for regular DECLARE CONST
            if self._match(TokenType.DECLARE):
                if self._match(TokenType.CONSTRAINT):  # CONST reuses CONSTRAINT token
                    return self._parse_usql_declare_const()
                else:
                    # Fall back to standard DECLARE
                    self._retreat(self._index - 1)
                    return super()._parse_statement()
            
            # Check for variable assignment (@var = ... or var = ...)
            if self._curr and self._curr.token_type == TokenType.PARAMETER:
                # This is a @ symbol - check if next is VAR and then EQ
                if self._next and self._next.token_type == TokenType.VAR:
                    # Look ahead one more to check for EQ
                    lookahead = self._tokens[self._index + 2] if self._index + 2 < len(self._tokens) else None
                    if lookahead and lookahead.token_type == TokenType.EQ:
                        return self._parse_usql_assignment()
            
            # Check for regular variable assignment (var = ...)
            if (self._curr and self._curr.token_type == TokenType.VAR and
                self._next and self._next.token_type == TokenType.EQ):
                return self._parse_usql_variable_assignment()
            
            # Check for EXTRACT and OUTPUT commands  
            if self._curr and self._curr.text and self._curr.text.upper() == "EXTRACT":
                return self._parse_usql_extract()
            
            if self._curr and self._curr.text and self._curr.text.upper() == "OUTPUT":
                return self._parse_usql_output()
                
            return super()._parse_statement()

        def _parse_usql_create_view(self) -> exp.Expression:
            """Parse U-SQL CREATE VIEW with SCHEMA"""
            if not self._match(TokenType.CREATE):
                self.raise_error("Expected CREATE")
            
            if not self._match(TokenType.VIEW):
                self.raise_error("Expected VIEW")
            
            view_name = self._parse_table_parts()
            if not view_name:
                self.raise_error("Expected view name")
            
            # Check for SCHEMA clause
            schema_def = None
            if self._match(TokenType.SCHEMA):
                schema_def = self._parse_usql_schema_definition()
            
            # Check for PARAMS clause
            params_def = None
            if self._curr and self._curr.token_type == TokenType.VAR and self._curr.text.upper() == "PARAMS":
                self._advance()  # consume PARAMS
                params_def = self._parse_usql_params_definition()
            
            # Parse AS BEGIN ... END body
            if not self._match(TokenType.ALIAS):
                self.raise_error("Expected AS after view definition")
            
            if not self._match(TokenType.BEGIN):
                self.raise_error("Expected BEGIN after AS")
            
            # Parse the body until END - try to parse as SQL statements
            body_expressions = []
            
            # Try to parse statements inside the body
            while (self._curr and 
                   self._index < len(self._tokens) and 
                   self._curr.token_type != TokenType.END):
                
                try:
                    # Try to parse a regular statement
                    stmt = self._parse_select(nested=True)
                    if stmt:
                        body_expressions.append(stmt)
                    else:
                        # If can't parse as select, advance and try again
                        if self._index < len(self._tokens):
                            self._advance()
                        else:
                            break
                except:
                    # If parsing fails, advance and continue
                    if self._index < len(self._tokens):
                        self._advance()
                    else:
                        break
            
            # Handle the END token
            if self._curr and self._curr.token_type == TokenType.END:
                if self._index < len(self._tokens):
                    self._advance()  # consume END
            
            # If no valid expressions found, use placeholder
            if not body_expressions:
                body_expressions = [exp.Placeholder(this="BODY_PLACEHOLDER")]
            
            # Create the U-SQL view expression
            return USqlCreateView(
                this=view_name,
                schema=schema_def,
                params=params_def,
                expression=body_expressions
            )

        def _parse_create(self) -> exp.Create | exp.Command:
            """Override to handle U-SQL CREATE VIEW with SCHEMA"""
            start_index = self._index
            
            if not self._match(TokenType.CREATE):
                return None
            
            # Check if this is a U-SQL VIEW with SCHEMA
            if self._match(TokenType.VIEW):
                view_name = self._parse_table_parts()
                if not view_name:
                    self.raise_error("Expected view name")
                
                # Check for SCHEMA clause
                schema_def = None
                if self._match(TokenType.SCHEMA):
                    schema_def = self._parse_usql_schema_definition()
                
                # Check for PARAMS clause
                params_def = None
                if self._curr and self._curr.text and self._curr.text.upper() == "PARAMS":
                    self._advance()  # consume PARAMS
                    params_def = self._parse_usql_params_definition()
                
                # Parse AS BEGIN ... END body
                if not self._match(TokenType.ALIAS):
                    self.raise_error("Expected AS after view definition")
                
                if not self._match(TokenType.BEGIN):
                    self.raise_error("Expected BEGIN after AS")
                
                # Parse the body until END
                body_expressions = []
                while (self._curr and self._curr.token_type != TokenType.END):
                    stmt = self._parse_statement()
                    if stmt:
                        body_expressions.append(stmt)
                
                # Consume END
                if not self._match(TokenType.END):
                    self.raise_error("Expected END")
                
                # Create the U-SQL view expression
                return USqlCreateView(
                    this=view_name,
                    schema=schema_def,
                    params=params_def,
                    expression=body_expressions
                )
            else:
                # Not a U-SQL view, reset and let parent handle it
                self._index = start_index
                return super()._parse_create()

        def _parse_usql_schema_definition(self) -> exp.Schema:
            """Parse SCHEMA (column_name: type, ...) definition"""
            if not self._match(TokenType.L_PAREN):
                self.raise_error("Expected ( after SCHEMA")
            
            columns = []
            while True:
                if self._match(TokenType.R_PAREN):
                    break
                
                # Parse column_name: type [DEFAULT value]
                col_name = self._parse_id_var()
                if not col_name:
                    self.raise_error("Expected column name")
                
                # Accept optional colon after column name (U-SQL allows both with and without colon)
                if self._curr and self._curr.token_type == TokenType.COLON:
                    self._advance()
                
                col_type = self._parse_usql_type()
                if not col_type:
                    self.raise_error("Expected column type")
                
                # Check for optional DEFAULT value
                default_value = None
                if self._curr and self._curr.text and self._curr.text.upper() == "DEFAULT":
                    self._advance()  # consume DEFAULT
                    # Handle optional = after DEFAULT
                    if self._curr and self._curr.token_type == TokenType.EQ:
                        self._advance()  # consume =
                    # Parse the default value
                    default_value = self._parse_bitwise()
                
                columns.append(exp.ColumnDef(this=col_name, kind=col_type, default=default_value))
                
                if not self._match(TokenType.COMMA):
                    # No comma, expect closing paren next
                    if not self._match(TokenType.R_PAREN):
                        self.raise_error("Expected , or ) in column list")
                    break
            
            return exp.Schema(expressions=columns)

        def _parse_usql_params_definition(self) -> exp.Schema:
            """Parse PARAMS (param_name type [DEFAULT value], ...) definition"""
            if not self._match(TokenType.L_PAREN):
                self.raise_error("Expected ( after PARAMS")
            
            params = []
            while True:
                if self._match(TokenType.R_PAREN):
                    break
                
                # Parse param_name [: ] type [DEFAULT value]
                # Two syntaxes supported:
                # 1. @param: type (with colon)
                # 2. param type (without colon)
                
                # Special handling for parameter names that might be keywords like "end"
                if self._curr and self._curr.token_type == TokenType.END:
                    # "end" is a parameter name, not END keyword in this context
                    param_name = exp.Identifier(this=self._curr.text)
                    self._advance()
                else:
                    param_name = self._parse_id_var()
                
                if not param_name:
                    self.raise_error("Expected parameter name")
                
                # Check if there's a colon (syntax 1) or not (syntax 2)
                if self._curr and self._curr.token_type == TokenType.COLON:
                    self._advance()  # consume colon
                    
                param_type = self._parse_usql_type()
                if not param_type:
                    self.raise_error("Expected parameter type")
                
                default_value = None
                if self._curr and self._curr.text and self._curr.text.upper() == "DEFAULT":
                    self._advance()  # consume DEFAULT
                    # Handle optional = after DEFAULT
                    if self._curr and self._curr.token_type == TokenType.EQ:
                        self._advance()  # consume =
                    # Parse the default value
                    default_value = self._parse_bitwise()
                
                params.append(exp.ColumnDef(this=param_name, kind=param_type, default=default_value))
                
                if not self._match(TokenType.COMMA):
                    # No comma, expect closing paren next
                    if not self._match(TokenType.R_PAREN):
                        self.raise_error("Expected , or ) in parameter list")
                    break
            
            return exp.Schema(expressions=params)

        def _parse_usql_type(self) -> exp.DataType:
            """Parse U-SQL types including nullable types (type?)"""
            # Parse base type
            if self._curr and self._curr.text and self._curr.text.upper() == "STRING":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.VARCHAR)
            elif self._curr and self._curr.text and self._curr.text.upper() == "BOOL":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.BOOLEAN)
            elif self._curr and self._curr.text and self._curr.text.upper() == "DATETIME":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.DATETIME)
            elif self._curr and self._curr.text and self._curr.text.upper() == "GUID":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.UUID)
            elif self._curr and self._curr.text and self._curr.text.upper() == "DOUBLE":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.DOUBLE)
            elif self._curr and self._curr.text and self._curr.text.upper() == "LONG":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.BIGINT)
            elif self._curr and self._curr.text and self._curr.text.upper() == "INT":
                self._advance()
                base_type = exp.DataType(this=exp.DataType.Type.INT)
            else:
                # Try standard type parsing
                base_type = self._parse_types()
            
            if not base_type:
                return None
            
            # Check for nullable suffix ?
            if self._match(TokenType.PLACEHOLDER):  # ? token
                # Mark as nullable (this is dialect specific)
                base_type.set("nullable", True)
            
            return base_type

        def _parse_usql_hash_declare(self) -> exp.Expression:
            """Parse: #DECLARE variable type = value;"""
            var = self._parse_id_var()
            if not var:
                self.raise_error("Expected variable name after #DECLARE")
            
            kind = self._parse_usql_type()
            if not kind:
                self.raise_error("Expected type after variable name")
            
            default = None
            if self._match(TokenType.EQ):
                default = self._parse_bitwise()
            
            return USqlHashDeclare(this=var, kind=kind, default=default)

        def _parse_usql_if_directive(self) -> exp.Expression:
            """Parse: #IF(condition) statements #ENDIF"""
            if not self._match(TokenType.L_PAREN):
                self.raise_error("Expected ( after #IF")
            
            condition = self._parse_bitwise()
            if not condition:
                self.raise_error("Expected condition in #IF")
            
            if not self._match(TokenType.R_PAREN):
                self.raise_error("Expected ) after #IF condition")
            
            # Parse body until #ENDIF
            body_expressions = []
            while (self._curr and 
                   not (self._curr.token_type == TokenType.PRAGMA and 
                        self._curr.text == "#ENDIF")):
                stmt = self._parse_statement()
                if stmt:
                    body_expressions.append(stmt)
            
            # Consume #ENDIF
            if self._curr and self._curr.token_type == TokenType.PRAGMA:
                self._advance()
            
            return USqlIfDirective(this=condition, expression=body_expressions)

        def _parse_usql_assignment(self) -> exp.Expression:
            """Parse: @variable = SELECT/EXTRACT/expression;"""
            var = self._parse_id_var()
            if not var:
                self.raise_error("Expected variable name")
            
            if not self._match(TokenType.EQ):
                self.raise_error("Expected = after variable name")
            
            # Check if this is an EXTRACT statement
            if self._curr and self._curr.text and self._curr.text.upper() == "EXTRACT":
                extract_expr = self._parse_usql_extract_expression()
                return USqlAssignment(this=var, expression=extract_expr)
            else:
                # Regular expression (like SELECT)
                expression = self._parse_select()
                return USqlAssignment(this=var, expression=expression)

        def _parse_usql_declare_const(self) -> exp.Expression:
            """Parse: DECLARE CONST @variable type = value;"""
            var = self._parse_id_var()
            if not var:
                self.raise_error("Expected variable name after DECLARE CONST")
            
            kind = self._parse_types()
            if not kind:
                self.raise_error("Expected type after variable name")
            
            default = None
            if self._match(TokenType.EQ):
                default = self._parse_bitwise()
            
            return USqlDeclareConst(this=var, kind=kind, default=default)

        def _parse_usql_variable_assignment(self) -> exp.Expression:
            """Parse: variable = SELECT/EXTRACT/VIEW/expression; (without @ prefix)"""
            var = self._parse_id_var()
            if not var:
                self.raise_error("Expected variable name")
            
            if not self._match(TokenType.EQ):
                self.raise_error("Expected = after variable name")
            
            # Check if this is an EXTRACT statement
            if self._curr and self._curr.text and self._curr.text.upper() == "EXTRACT":
                extract_expr = self._parse_usql_extract_expression()
                return USqlAssignment(this=var, expression=extract_expr)
            # Check if this is a VIEW invocation
            elif self._curr and self._curr.text and self._curr.text.upper() == "VIEW":
                view_invocation = self._parse_usql_view_invocation()
                return USqlAssignment(this=var, expression=view_invocation)
            else:
                # Simple literal or expression parsing
                if self._curr.token_type == TokenType.NUMBER:
                    value = exp.Literal.number(self._curr.text)
                    self._advance()
                    return USqlAssignment(this=var, expression=value)
                else:
                    # Try regular expression (like SELECT)
                    expression = self._parse_select() or self._parse_bitwise()
                    return USqlAssignment(this=var, expression=expression)

        def _parse_usql_assignment(self) -> exp.Expression:
            """Parse: @variable = SELECT/EXTRACT/expression;"""
            var = self._parse_id_var()
            if not var:
                self.raise_error("Expected variable name")
            
            if not self._match(TokenType.EQ):
                self.raise_error("Expected = after variable name")
            
            # Check if this is an EXTRACT statement
            if self._match_text_seq("EXTRACT"):
                self._retreat(self._index - 1)
                extract_expr = self._parse_usql_extract_expression()
                return USqlAssignment(this=var, expression=extract_expr)
            else:
                # Regular expression (like SELECT)
                expression = self._parse_select()
                return USqlAssignment(this=var, expression=expression)

        def _parse_usql_extract(self) -> exp.Expression:
            """Parse standalone: @var = EXTRACT ... FROM ... USING ..."""
            var = None
            if self._curr and self._curr.token_type == TokenType.VAR:
                var = self._parse_id_var()
                if not self._match(TokenType.EQ):
                    self.raise_error("Expected = after variable name")
            
            extract_expr = self._parse_usql_extract_expression()
            
            if var:
                return USqlAssignment(this=var, expression=extract_expr)
            else:
                return extract_expr

        def _parse_usql_extract_expression(self) -> exp.Expression:
            """Parse: EXTRACT columns FROM source USING extractor"""
            if not self._match_text_seq("EXTRACT"):
                self.raise_error("Expected EXTRACT")
            
            # Parse column definitions (Id:int, Name:string, etc.)
            expressions = []
            while not self._match(TokenType.FROM):
                if expressions:
                    if not self._match(TokenType.COMMA):
                        break
                
                col_name = self._parse_id_var() or self._parse_identifier()
                if not col_name:
                    self.raise_error("Expected column name")
                
                # Accept optional colon after column name (U-SQL allows both with and without colon)
                if self._curr and self._curr.token_type == TokenType.COLON:
                    self._advance()
                
                col_type = self._parse_usql_type()
                if not col_type:
                    self.raise_error("Expected column type")
                
                expressions.append(exp.ColumnDef(this=col_name, kind=col_type))
            
            if not expressions:
                self.raise_error("Expected column definitions")
            
            # FROM clause
            from_expr = self._parse_table_parts()
            if not from_expr:
                self.raise_error("Expected FROM source")
            
            # USING clause
            if not self._match(TokenType.USING):
                self.raise_error("Expected USING clause")
            
            # Parse the extractor - could be simple identifier or complex expression
            # For now, let's just capture everything until semicolon as a simple expression
            using_tokens = []
            while self._curr and self._curr.token_type != TokenType.SEMICOLON:
                using_tokens.append(self._curr.text)
                self._advance()
            
            if not using_tokens:
                self.raise_error("Expected extractor function")
            
            # Create a simple anonymous function with the captured text
            using_expr = exp.Anonymous(this="".join(using_tokens), expressions=[])
            
            return USqlExtract(
                expressions=expressions,
                **{"from": from_expr},
                using=using_expr
            )

        def _parse_usql_output(self) -> exp.Expression:
            """Parse: OUTPUT @variable TO destination USING outputter"""
            if not self._curr or self._curr.text.upper() != "OUTPUT":
                self.raise_error("Expected OUTPUT")
            
            self._advance()  # consume OUTPUT
            
            # Source (@variable or SELECT query)
            this = self._parse_id_var() or self._parse_select()
            if not this:
                self.raise_error("Expected variable or SELECT after OUTPUT")
            
            # TO clause
            if not self._curr or self._curr.text.upper() != "TO":
                self.raise_error("Expected TO clause")
            
            self._advance()  # consume TO
            
            to_expr = self._parse_id_var() or self._parse_string()
            if not to_expr:
                self.raise_error("Expected destination after TO")
            
            # USING clause
            if not self._match(TokenType.USING):
                self.raise_error("Expected USING clause")
            
            # Parse the outputter - similar to extractor parsing
            using_tokens = []
            while self._curr and self._curr.token_type != TokenType.SEMICOLON:
                using_tokens.append(self._curr.text)
                self._advance()
            
            if not using_tokens:
                self.raise_error("Expected outputter function")
            
            using_expr = exp.Anonymous(this="".join(using_tokens), expressions=[])
            
            return USqlOutput(
                this=this,
                to=to_expr,
                using=using_expr
            )

        def _parse_usql_view_invocation(self) -> exp.Expression:
            """Parse: VIEW @path PARAMS (...);"""
            if not self._curr or self._curr.text.upper() != "VIEW":
                self.raise_error("Expected VIEW")
            
            self._advance()  # consume VIEW
            
            # Parse the view path (usually a parameter like @potatoViewFullPath)
            view_path = None
            if self._curr and self._curr.token_type == TokenType.PARAMETER:
                # Handle @parameter
                view_path = self._parse_id_var()
            else:
                # Handle regular identifier or string
                view_path = self._parse_id_var() or self._parse_string()
            
            if not view_path:
                self.raise_error("Expected view path after VIEW")
            
            # Check for PARAMS clause
            params = None
            if self._curr and self._curr.text and self._curr.text.upper() == "PARAMS":
                self._advance()  # consume PARAMS
                
                if not self._match(TokenType.L_PAREN):
                    self.raise_error("Expected ( after PARAMS")
                
                # Parse parameter assignments
                param_assignments = []
                while True:
                    if self._match(TokenType.R_PAREN):
                        break
                    
                    # Parse param_name = value
                    param_name = self._parse_id_var()
                    if not param_name:
                        self.raise_error("Expected parameter name")
                    
                    if not self._match(TokenType.EQ):
                        self.raise_error("Expected = after parameter name")
                    
                    param_value = self._parse_bitwise()
                    if not param_value:
                        self.raise_error("Expected parameter value")
                    
                    # Create an assignment expression for this parameter
                    param_assignments.append(exp.EQ(this=param_name, expression=param_value))
                    
                    if not self._match(TokenType.COMMA):
                        # No comma, expect closing paren next
                        if not self._match(TokenType.R_PAREN):
                            self.raise_error("Expected , or ) in parameter list")
                        break
                
                # Store parameters as expressions list
                params = param_assignments
            
            return USqlViewInvocation(
                this=view_path,
                params=params
            )

        def _parse_create(self) -> exp.Create | exp.Command:
            create = super()._parse_create()

            if isinstance(create, exp.Create):
                # Transform VARCHAR/CHAR without precision to VARCHAR(1)/CHAR(1)
                if create.kind == "TABLE" and isinstance(create.this, exp.Schema):
                    for column in create.this.expressions:
                        if isinstance(column, exp.ColumnDef):
                            column_type = column.kind
                            if (
                                isinstance(column_type, exp.DataType)
                                and column_type.this
                                in (exp.DataType.Type.VARCHAR, exp.DataType.Type.CHAR)
                                and not column_type.expressions
                            ):
                                # Add default precision of 1 to VARCHAR/CHAR without precision
                                # When n isn't specified in a data definition or variable declaration statement, the default length is 1.
                                # https://learn.microsoft.com/en-us/sql/t-sql/data-types/char-and-varchar-transact-sql?view=sql-server-ver17#remarks
                                column_type.set("expressions", [exp.Literal.number("1")])

            return create

    class Generator(TSQL.Generator):
        # Fabric-specific type mappings - override T-SQL types that aren't supported
        # Reference: https://learn.microsoft.com/en-us/fabric/data-warehouse/data-types
        TYPE_MAPPING = {
            **TSQL.Generator.TYPE_MAPPING,
            exp.DataType.Type.DATETIME: "DATETIME2",
            exp.DataType.Type.DECIMAL: "DECIMAL",
            exp.DataType.Type.IMAGE: "VARBINARY",
            exp.DataType.Type.INT: "INT",
            exp.DataType.Type.JSON: "VARCHAR",
            exp.DataType.Type.MONEY: "DECIMAL",
            exp.DataType.Type.NCHAR: "CHAR",
            exp.DataType.Type.NVARCHAR: "VARCHAR",
            exp.DataType.Type.ROWVERSION: "ROWVERSION",
            exp.DataType.Type.SMALLDATETIME: "DATETIME2",
            exp.DataType.Type.SMALLMONEY: "DECIMAL",
            exp.DataType.Type.TIMESTAMP: "DATETIME2",
            exp.DataType.Type.TIMESTAMPNTZ: "DATETIME2",
            exp.DataType.Type.TIMESTAMPTZ: "DATETIME2",
            exp.DataType.Type.TINYINT: "SMALLINT",
            exp.DataType.Type.UTINYINT: "SMALLINT",
            exp.DataType.Type.UUID: "VARBINARY(MAX)",
            exp.DataType.Type.XML: "VARCHAR",
        }

        TRANSFORMS = {
            **TSQL.Generator.TRANSFORMS,
            exp.Create: transforms.preprocess([_add_default_precision_to_varchar]),
            USqlExtract: lambda self, e: self._usql_extract_sql(e),
            USqlOutput: lambda self, e: self._usql_output_sql(e),
            USqlAssignment: lambda self, e: self._usql_assignment_sql(e),
            USqlDeclareConst: lambda self, e: self._usql_declare_const_sql(e),
            USqlCreateView: lambda self, e: self._usql_create_view_sql(e),
            USqlHashDeclare: lambda self, e: self._usql_hash_declare_sql(e),
            USqlIfDirective: lambda self, e: self._usql_if_directive_sql(e),
            USqlViewInvocation: lambda self, e: self._usql_view_invocation_sql(e),
        }

        def _usql_extract_sql(self, expression: USqlExtract) -> str:
            """Generate: EXTRACT columns FROM source USING extractor"""
            columns = ", ".join([
                f"{self.sql(col.this)} {self.sql(col.kind)}" 
                for col in expression.expressions
            ])
            from_sql = self.sql(expression.args.get("from"))
            using_sql = self.sql(expression.using)
            return f"EXTRACT {columns} FROM {from_sql} USING {using_sql}"

        def _usql_output_sql(self, expression: USqlOutput) -> str:
            """Generate: OUTPUT source TO destination USING outputter"""
            this_sql = self.sql(expression.this)
            to_sql = self.sql(expression.args.get("to"))
            using_sql = self.sql(expression.args.get("using"))
            return f"OUTPUT {this_sql} TO {to_sql} USING {using_sql}"

        def _usql_assignment_sql(self, expression: USqlAssignment) -> str:
            """Generate: @variable = expression"""
            var_sql = self.sql(expression.this)
            expr_sql = self.sql(expression.expression)
            return f"{var_sql} = {expr_sql}"

        def _usql_declare_const_sql(self, expression: USqlDeclareConst) -> str:
            """Generate: DECLARE CONST @variable type = value"""
            var_sql = self.sql(expression.this)
            type_sql = self.sql(expression.kind)
            parts = [f"DECLARE CONST {var_sql} {type_sql}"]
            if expression.default:
                parts.append(f" = {self.sql(expression.default)}")
            return "".join(parts)

        def _usql_create_view_sql(self, expression: USqlCreateView) -> str:
            """Generate: CREATE VIEW name SCHEMA (...) PARAMS (...) AS BEGIN ... END"""
            view_name = self.sql(expression.this)
            parts = [f"CREATE VIEW {view_name}"]
            
            schema = expression.args.get("schema")
            if schema:
                schema_cols = []
                for col in schema.expressions:
                    col_name = self.sql(col.this)
                    col_type = self.sql(col.kind)
                    nullable = "?" if col.kind and col.kind.args.get("nullable") else ""
                    col_str = f"{col_name}: {col_type}{nullable}"
                    # Add DEFAULT value if present
                    default_val = col.args.get("default")
                    if default_val:
                        col_str += f" DEFAULT {self.sql(default_val)}"
                    schema_cols.append(col_str)
                parts.append(f" SCHEMA ({', '.join(schema_cols)})")
            
            params = expression.args.get("params")
            if params:
                param_cols = []
                for param in params.expressions:
                    param_name = self.sql(param.this)
                    param_type = self.sql(param.kind)
                    param_str = f"{param_name} {param_type}"
                    default_val = param.args.get("default")
                    if default_val:
                        param_str += f" DEFAULT = {self.sql(default_val)}"
                    param_cols.append(param_str)
                parts.append(f" PARAMS ({', '.join(param_cols)})")
            
            parts.append(" AS BEGIN")
            
            body = expression.args.get("expression")
            if body:
                for stmt in body:
                    parts.append(f"\n{self.sql(stmt)}")
            
            parts.append("\nEND")
            return "".join(parts)

        def _usql_hash_declare_sql(self, expression: USqlHashDeclare) -> str:
            """Generate: #DECLARE variable type = value"""
            var_sql = self.sql(expression.this)
            type_sql = self.sql(expression.kind)
            parts = [f"#DECLARE {var_sql} {type_sql}"]
            if expression.default:
                parts.append(f" = {self.sql(expression.default)}")
            return "".join(parts)

        def _usql_if_directive_sql(self, expression: USqlIfDirective) -> str:
            """Generate: #IF(condition) statements #ENDIF"""
            condition_sql = self.sql(expression.this)
            parts = [f"#IF({condition_sql})"]
            
            if expression.expression:
                for stmt in expression.expression:
                    parts.append(f"\n{self.sql(stmt)}")
            
            parts.append("\n#ENDIF")
            return "".join(parts)

        def _usql_view_invocation_sql(self, expression: USqlViewInvocation) -> str:
            """Generate: VIEW @path PARAMS (param1 = value1, param2 = value2)"""
            view_path_sql = self.sql(expression.this)
            parts = [f"VIEW {view_path_sql}"]
            
            params = expression.args.get("params")
            if params:
                param_strs = []
                for param in params:
                    param_str = self.sql(param)
                    param_strs.append(param_str)
                parts.append(f" PARAMS ({', '.join(param_strs)})")
            
            return "".join(parts)

        def datatype_sql(self, expression: exp.DataType) -> str:
            # Check if this is a temporal type that needs precision handling. Fabric limits temporal
            # types to max 6 digits precision. When no precision is specified, we default to 6 digits.
            if (
                expression.is_type(*exp.DataType.TEMPORAL_TYPES)
                and expression.this != exp.DataType.Type.DATE
            ):
                # Create a new expression with the capped precision
                expression = _cap_data_type_precision(expression)

            return super().datatype_sql(expression)

        def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
            # Cast to DATETIMEOFFSET if inside an AT TIME ZONE expression
            # https://learn.microsoft.com/en-us/sql/t-sql/data-types/datetimeoffset-transact-sql#microsoft-fabric-support
            if expression.is_type(exp.DataType.Type.TIMESTAMPTZ):
                at_time_zone = expression.find_ancestor(exp.AtTimeZone, exp.Select)

                # Return normal cast, if the expression is not in an AT TIME ZONE context
                if not isinstance(at_time_zone, exp.AtTimeZone):
                    return super().cast_sql(expression, safe_prefix)

                # Get the precision from the original TIMESTAMPTZ cast and cap it to 6
                capped_data_type = _cap_data_type_precision(expression.to, max_precision=6)
                precision = capped_data_type.find(exp.DataTypeParam)
                precision_value = (
                    precision.this.to_py() if precision and precision.this.is_int else 6
                )

                # Do the cast explicitly to bypass sqlglot's default handling
                datetimeoffset = f"CAST({expression.this} AS DATETIMEOFFSET({precision_value}))"

                return self.sql(datetimeoffset)

            return super().cast_sql(expression, safe_prefix)

        def attimezone_sql(self, expression: exp.AtTimeZone) -> str:
            # Wrap the AT TIME ZONE expression in a cast to DATETIME2 if it contains a TIMESTAMPTZ
            ## https://learn.microsoft.com/en-us/sql/t-sql/data-types/datetimeoffset-transact-sql#microsoft-fabric-support
            timestamptz_cast = expression.find(exp.Cast)
            if timestamptz_cast and timestamptz_cast.to.is_type(exp.DataType.Type.TIMESTAMPTZ):
                # Get the precision from the original TIMESTAMPTZ cast and cap it to 6
                data_type = timestamptz_cast.to
                capped_data_type = _cap_data_type_precision(data_type, max_precision=6)
                precision_param = capped_data_type.find(exp.DataTypeParam)
                precision = precision_param.this.to_py() if precision_param else 6

                # Generate the AT TIME ZONE expression (which will handle the inner cast conversion)
                at_time_zone_sql = super().attimezone_sql(expression)

                # Wrap it in an outer cast to DATETIME2
                return f"CAST({at_time_zone_sql} AS DATETIME2({precision}))"

            return super().attimezone_sql(expression)

        def unixtotime_sql(self, expression: exp.UnixToTime) -> str:
            scale = expression.args.get("scale")
            timestamp = expression.this

            if scale not in (None, exp.UnixToTime.SECONDS):
                self.unsupported(f"UnixToTime scale {scale} is not supported by Fabric")
                return ""

            # Convert unix timestamp (seconds) to microseconds and round to avoid decimals
            microseconds = timestamp * exp.Literal.number("1e6")
            rounded = exp.func("round", microseconds, 0)
            rounded_ms_as_bigint = exp.cast(rounded, exp.DataType.Type.BIGINT)

            # Create the base datetime as '1970-01-01' cast to DATETIME2(6)
            epoch_start = exp.cast("'1970-01-01'", "datetime2(6)", dialect="fabric")

            dateadd = exp.DateAdd(
                this=epoch_start,
                expression=rounded_ms_as_bigint,
                unit=exp.Literal.string("MICROSECONDS"),
            )
            return self.sql(dateadd)
