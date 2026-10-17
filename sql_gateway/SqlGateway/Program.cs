using System.Text.Json;
using Microsoft.Extensions.Hosting.WindowsServices;
using SqlGateway;

var isService = WindowsServiceHelpers.IsWindowsService();
var baseDir = AppContext.BaseDirectory;
var liveOptions = SettingsService.Load();

if (!isService)
{
    ApplicationConfiguration.Initialize();

    // Primera pantalla: pedir datos y guardar. Luego sigue corriendo en bandeja.
    using (var setup = new ConfigForm(Clone(liveOptions)))
    {
        setup.Text = "SqlGateway — Configuración inicial";
        if (setup.ShowDialog() != DialogResult.OK)
        {
            return;
        }

        liveOptions.CopyFrom(setup.Result);
        SettingsService.Save(liveOptions);
    }
}

var builder = WebApplication.CreateBuilder(new WebApplicationOptions
{
    Args = args,
    ContentRootPath = baseDir
});

builder.Configuration
    .SetBasePath(baseDir)
    .AddJsonFile("appsettings.json", optional: false, reloadOnChange: true);

builder.Host.UseWindowsService();

builder.Services.AddSingleton(liveOptions);
builder.Services.AddSingleton<SqlExecutor>();

var listenUrl = $"http://{liveOptions.ListenHost}:{liveOptions.ListenPort}";
builder.WebHost.UseUrls(listenUrl);

builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
    o.SerializerOptions.WriteIndented = false;
});

var app = builder.Build();

app.Use(async (context, next) =>
{
    var opts = context.RequestServices.GetRequiredService<GatewayOptions>();
    if (!string.IsNullOrEmpty(opts.ApiKey))
    {
        if (!context.Request.Path.StartsWithSegments("/health"))
        {
            if (!context.Request.Headers.TryGetValue("X-Api-Key", out var key) || key != opts.ApiKey)
            {
                context.Response.StatusCode = StatusCodes.Status401Unauthorized;
                await context.Response.WriteAsJsonAsync(QueryResponse.Fail("No autorizado. Envíe header X-Api-Key."));
                return;
            }
        }
    }

    await next();
});

app.MapGet("/health", (GatewayOptions opts) => Results.Ok(new
{
    status = "ok",
    listen = $"http://{opts.ListenHost}:{opts.ListenPort}",
    sqlServer = $"{opts.SqlServer},{opts.SqlPort}",
    database = opts.Database,
    readOnlyMode = opts.ReadOnlyMode,
    maxRows = opts.MaxRows
}));

app.MapPost("/query", async (QueryRequest request, SqlExecutor executor, CancellationToken ct) =>
{
    var result = await executor.ExecuteAsync(request.Sql, ct);
    return result.Ok
        ? Results.Ok(result)
        : Results.Json(result, statusCode: StatusCodes.Status400BadRequest);
});

app.MapGet("/", () => Results.Ok(new
{
    name = "SqlGateway",
    endpoints = new
    {
        health = "GET /health",
        query = "POST /query  body: { \"sql\": \"SELECT 1 AS n\" }"
    }
}));

var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("SqlGateway");
logger.LogInformation("SqlGateway escuchando en {Url}", listenUrl);

if (isService)
{
    app.Run();
}
else
{
    await app.StartAsync();

    using var tray = new TrayApplicationContext(liveOptions, async () =>
    {
        await app.StopAsync(TimeSpan.FromSeconds(5));
        await app.DisposeAsync();
    });

    Application.Run(tray);
}

static GatewayOptions Clone(GatewayOptions source)
{
    var copy = new GatewayOptions();
    copy.CopyFrom(source);
    return copy;
}
