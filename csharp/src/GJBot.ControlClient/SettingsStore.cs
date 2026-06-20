using System.Text.Json;

namespace GJBot.ControlClient;

public static class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static string SettingsPath
    {
        get
        {
            var folder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "GJBotControlClient");
            return Path.Combine(folder, "settings.json");
        }
    }

    public static ClientSettings Load()
    {
        try
        {
            if (!File.Exists(SettingsPath))
            {
                return new ClientSettings();
            }

            var json = File.ReadAllText(SettingsPath);
            return JsonSerializer.Deserialize<ClientSettings>(json, JsonOptions) ?? new ClientSettings();
        }
        catch
        {
            return new ClientSettings();
        }
    }

    public static void Save(ClientSettings settings)
    {
        var folder = Path.GetDirectoryName(SettingsPath);
        if (!string.IsNullOrWhiteSpace(folder))
        {
            Directory.CreateDirectory(folder);
        }

        var json = JsonSerializer.Serialize(settings, JsonOptions);
        File.WriteAllText(SettingsPath, json);
    }
}
