using System.Data;
using System.Text.RegularExpressions;
using Microsoft.Data.SqlClient;

namespace SqlGateway;

public sealed class SqlExecutor(GatewayOptions options, ILogger<SqlExecutor> logger)
{
    private static readonly Regex LeadingKeyword = new(
        @"^\s*(?:/\*.*?\*/\s*|-\-[^\n]*\n\s*)*(SELECT|WITH|SHOW|DESCRIBE|DESC|EXEC|EXECUTE|DECLARE)\b",
        RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.Compiled);

    public async Task<QueryResponse> ExecuteAsync(string sql, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(sql))
        {
            return QueryResponse.Fail("El SQL no puede estar vacío.");
        }

        var connectionString = options.ResolveConnectionString();
        if (string.IsNullOrWhiteSpace(connectionString)
            || string.IsNullOrWhiteSpace(options.SqlServer) && string.IsNullOrWhiteSpace(options.ConnectionString))
        {
            return QueryResponse.Fail("Configure el servidor SQL en la interfaz gráfica o en appsettings.json.");
        }

        if (options.ReadOnlyMode && !LeadingKeyword.IsMatch(sql))
        {
            return QueryResponse.Fail(
                "ReadOnlyMode está activo: solo se permiten SELECT, WITH, SHOW, DESCRIBE, EXEC, EXECUTE o DECLARE.");
        }

        try
        {
            await using var connection = new SqlConnection(connectionString);
            await connection.OpenAsync(cancellationToken);

            await using var command = new SqlCommand(sql, connection)
            {
                CommandTimeout = options.CommandTimeoutSeconds,
                CommandType = CommandType.Text
            };

            await using var reader = await command.ExecuteReaderAsync(cancellationToken);

            var columns = new List<string>(reader.FieldCount);
            for (var i = 0; i < reader.FieldCount; i++)
            {
                columns.Add(reader.GetName(i));
            }

            var rows = new List<object?[]>();
            var maxRows = options.MaxRows <= 0 ? int.MaxValue : options.MaxRows;
            var truncated = false;

            while (await reader.ReadAsync(cancellationToken))
            {
                if (rows.Count >= maxRows)
                {
                    truncated = true;
                    break;
                }

                var row = new object?[reader.FieldCount];
                for (var i = 0; i < reader.FieldCount; i++)
                {
                    row[i] = reader.IsDBNull(i) ? null : NormalizeValue(reader.GetValue(i));
                }

                rows.Add(row);
            }

            // Si el comando no devolvió result set (INSERT/UPDATE/DELETE), RowsAffected.
            var rowsAffected = reader.RecordsAffected;

            return new QueryResponse
            {
                Ok = true,
                Columns = columns,
                Rows = rows,
                RowCount = rows.Count,
                RowsAffected = rowsAffected < 0 ? null : rowsAffected,
                Truncated = truncated
            };
        }
        catch (SqlException ex)
        {
            logger.LogWarning(ex, "Error SQL al ejecutar consulta");
            return QueryResponse.Fail($"SQL Error {ex.Number}: {ex.Message}");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error inesperado al ejecutar consulta");
            return QueryResponse.Fail(ex.Message);
        }
    }

    private static object? NormalizeValue(object value) => value switch
    {
        DateTime dt => dt.ToString("o"),
        DateTimeOffset dto => dto.ToString("o"),
        TimeSpan ts => ts.ToString(),
        Guid g => g.ToString(),
        byte[] bytes => Convert.ToBase64String(bytes),
        decimal or double or float or long or int or short or byte or bool or string => value,
        _ => value.ToString()
    };
}

public sealed class QueryRequest
{
    public string Sql { get; set; } = string.Empty;
}

public sealed class QueryResponse
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public List<string>? Columns { get; set; }
    public List<object?[]>? Rows { get; set; }
    public int? RowCount { get; set; }
    public int? RowsAffected { get; set; }
    public bool Truncated { get; set; }

    public static QueryResponse Fail(string error) => new()
    {
        Ok = false,
        Error = error
    };
}
