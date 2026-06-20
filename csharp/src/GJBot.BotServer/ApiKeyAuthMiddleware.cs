using System.Security.Cryptography;
using System.Text;
using GJBot.Shared;
using Microsoft.Extensions.Options;

namespace GJBot.BotServer;

public sealed class ApiKeyAuthMiddleware
{
    private readonly RequestDelegate _next;

    public ApiKeyAuthMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context, IOptions<ControlServerOptions> options)
    {
        if (!context.Request.Path.StartsWithSegments("/api"))
        {
            await _next(context);
            return;
        }

        var configuredKey = options.Value.ApiKey;
        if (string.IsNullOrWhiteSpace(configuredKey))
        {
            await WriteJsonAsync(
                context,
                StatusCodes.Status503ServiceUnavailable,
                ApiEnvelope<object>.Fail("ControlApi:ApiKey or GJBOT_CONTROL_API_KEY is not configured."));
            return;
        }

        if (!context.Request.Headers.TryGetValue(ControlApiClient.ApiKeyHeaderName, out var providedKey) ||
            !SecureEquals(providedKey.ToString(), configuredKey!))
        {
            await WriteJsonAsync(
                context,
                StatusCodes.Status401Unauthorized,
                ApiEnvelope<object>.Fail("Invalid control API key."));
            return;
        }

        await _next(context);
    }

    private static bool SecureEquals(string left, string right)
    {
        var leftHash = SHA256.HashData(Encoding.UTF8.GetBytes(left));
        var rightHash = SHA256.HashData(Encoding.UTF8.GetBytes(right));
        return CryptographicOperations.FixedTimeEquals(leftHash, rightHash);
    }

    private static async Task WriteJsonAsync<T>(HttpContext context, int statusCode, ApiEnvelope<T> envelope)
    {
        context.Response.StatusCode = statusCode;
        context.Response.ContentType = "application/json; charset=utf-8";
        await context.Response.WriteAsJsonAsync(envelope);
    }
}
