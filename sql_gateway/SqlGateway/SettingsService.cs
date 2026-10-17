using System.Text.Json;
using System.Text.Json.Nodes;

namespace SqlGateway;

public static class SettingsService
{
    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true
    };

    public static string ConfigPath => Path.Combine(AppContext.BaseDirectory, "appsettings.json");

    public static GatewayOptions Load()
    {
        try
        {
            if (!File.Exists(ConfigPath))
            {
                return new GatewayOptions();
            }

            using var doc = JsonDocument.Parse(File.ReadAllText(ConfigPath));
            if (!doc.RootElement.TryGetProperty(GatewayOptions.SectionName, out var section))
            {
                return new GatewayOptions();
            }

            return JsonSerializer.Deserialize<GatewayOptions>(section.GetRawText()) ?? new GatewayOptions();
        }
        catch
        {
            return new GatewayOptions();
        }
    }

    public static void Save(GatewayOptions options)
    {
        JsonNode root;
        if (File.Exists(ConfigPath))
        {
            root = JsonNode.Parse(File.ReadAllText(ConfigPath)) ?? new JsonObject();
        }
        else
        {
            root = new JsonObject
            {
                ["Logging"] = new JsonObject
                {
                    ["LogLevel"] = new JsonObject
                    {
                        ["Default"] = "Information",
                        ["Microsoft.AspNetCore"] = "Warning"
                    }
                }
            };
        }

        // Al usar campos separados, limpiamos ConnectionString para que no pise la UI.
        var toSave = new GatewayOptions();
        toSave.CopyFrom(options);
        toSave.ConnectionString = string.Empty;

        root[GatewayOptions.SectionName] = JsonSerializer.SerializeToNode(toSave, WriteOptions);
        File.WriteAllText(ConfigPath, root.ToJsonString(WriteOptions));
    }
}
