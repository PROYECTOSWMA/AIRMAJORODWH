using Microsoft.Data.SqlClient;

namespace SqlGateway;

public sealed class GatewayOptions
{
    public const string SectionName = "Gateway";

    /// <summary>Puerto HTTP en el que escucha el gateway.</summary>
    public int ListenPort { get; set; } = 5055;

    /// <summary>IP de escucha. Use 0.0.0.0 para todas las interfaces, 127.0.0.1 solo local.</summary>
    public string ListenHost { get; set; } = "0.0.0.0";

    /// <summary>Host o IP de SQL Server.</summary>
    public string SqlServer { get; set; } = "localhost";

    /// <summary>Puerto de SQL Server (por defecto 1433).</summary>
    public int SqlPort { get; set; } = 1433;

    /// <summary>Nombre de la base de datos.</summary>
    public string Database { get; set; } = string.Empty;

    /// <summary>Usuario de SQL Server.</summary>
    public string UserId { get; set; } = string.Empty;

    /// <summary>Contraseña de SQL Server.</summary>
    public string Password { get; set; } = string.Empty;

    /// <summary>
    /// Cadena completa opcional. Si está vacía, se arma con SqlServer/SqlPort/Database/UserId/Password.
    /// </summary>
    public string ConnectionString { get; set; } = string.Empty;

    /// <summary>
    /// Si no está vacío, cada petición debe enviar el header X-Api-Key con este valor.
    /// </summary>
    public string ApiKey { get; set; } = string.Empty;

    /// <summary>Timeout de cada comando SQL (segundos).</summary>
    public int CommandTimeoutSeconds { get; set; } = 60;

    /// <summary>Máximo de filas a devolver. 0 = sin límite.</summary>
    public int MaxRows { get; set; } = 10000;

    /// <summary>
    /// Si es true, solo se permiten consultas que empiecen por SELECT / WITH / SHOW / DESCRIBE / EXEC / EXECUTE / DECLARE.
    /// </summary>
    public bool ReadOnlyMode { get; set; } = false;

    public string ResolveConnectionString()
    {
        if (!string.IsNullOrWhiteSpace(ConnectionString))
        {
            return ConnectionString;
        }

        var builder = new SqlConnectionStringBuilder
        {
            DataSource = SqlPort > 0 ? $"{SqlServer},{SqlPort}" : SqlServer,
            InitialCatalog = Database,
            UserID = UserId,
            Password = Password,
            TrustServerCertificate = true,
            Encrypt = false
        };

        return builder.ConnectionString;
    }

    public void CopyFrom(GatewayOptions other)
    {
        ListenPort = other.ListenPort;
        ListenHost = other.ListenHost;
        SqlServer = other.SqlServer;
        SqlPort = other.SqlPort;
        Database = other.Database;
        UserId = other.UserId;
        Password = other.Password;
        ConnectionString = other.ConnectionString;
        ApiKey = other.ApiKey;
        CommandTimeoutSeconds = other.CommandTimeoutSeconds;
        MaxRows = other.MaxRows;
        ReadOnlyMode = other.ReadOnlyMode;
    }
}
