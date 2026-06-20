namespace GJBot.ControlClient;

public sealed record ClientSettings
{
    public string BackendUrl { get; init; } = "http://localhost:5088";
    public string WebPanelUrl { get; init; } = "https://puneetblog.org";
    public string ApiKey { get; init; } = "";
    public string LastChannelId { get; init; } = "";
    public bool SuppressMentions { get; init; } = true;
}
