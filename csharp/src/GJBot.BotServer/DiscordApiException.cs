namespace GJBot.BotServer;

public sealed class DiscordApiException : Exception
{
    public DiscordApiException(int statusCode, string message)
        : base(message)
    {
        StatusCode = statusCode;
    }

    public int StatusCode { get; }
}
