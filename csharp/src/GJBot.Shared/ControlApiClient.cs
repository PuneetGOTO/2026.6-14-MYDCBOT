using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace GJBot.Shared;

public sealed class ControlApiClient : IDisposable
{
    public const string ApiKeyHeaderName = "X-GJBot-Api-Key";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    private readonly HttpClient _httpClient;

    public ControlApiClient(string baseUrl, string apiKey)
    {
        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            throw new ArgumentException("Backend URL is required.", nameof(baseUrl));
        }

        _httpClient = new HttpClient
        {
            BaseAddress = new Uri(NormalizeBaseUrl(baseUrl)),
            Timeout = TimeSpan.FromSeconds(30)
        };

        if (!string.IsNullOrWhiteSpace(apiKey))
        {
            _httpClient.DefaultRequestHeaders.Add(ApiKeyHeaderName, apiKey);
        }
    }

    public Task<ApiEnvelope<HealthResponse>> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        return SendAsync<HealthResponse>(HttpMethod.Get, "api/health", null, cancellationToken);
    }

    public Task<ApiEnvelope<BotIdentityResponse>> GetBotIdentityAsync(CancellationToken cancellationToken = default)
    {
        return SendAsync<BotIdentityResponse>(HttpMethod.Get, "api/discord/me", null, cancellationToken);
    }

    public Task<ApiEnvelope<List<GuildSummary>>> GetGuildsAsync(CancellationToken cancellationToken = default)
    {
        return SendAsync<List<GuildSummary>>(HttpMethod.Get, "api/discord/guilds", null, cancellationToken);
    }

    public Task<ApiEnvelope<GuildOverviewResponse>> GetGuildOverviewAsync(
        string guildId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<GuildOverviewResponse>(HttpMethod.Get, $"api/discord/guilds/{guildId}/overview", null, cancellationToken);
    }

    public Task<ApiEnvelope<DiscordMessageResult>> SendMessageAsync(
        DiscordMessageRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<DiscordMessageResult>(HttpMethod.Post, "api/discord/message", request, cancellationToken);
    }

    public Task<ApiEnvelope<BroadcastMessageResult>> BroadcastMessageAsync(
        BroadcastMessageRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<BroadcastMessageResult>(HttpMethod.Post, "api/discord/broadcast", request, cancellationToken);
    }

    public Task<ApiEnvelope<DiscordMessageResult>> SendDirectMessageAsync(
        DirectMessageRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<DiscordMessageResult>(HttpMethod.Post, "api/discord/dm", request, cancellationToken);
    }

    public Task<ApiEnvelope<DiscordRoleSummary>> CreateRoleAsync(
        RoleCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<DiscordRoleSummary>(HttpMethod.Post, "api/discord/roles", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> DeleteRoleAsync(
        RoleDeleteRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/roles/delete", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> AddMemberRoleAsync(
        MemberRoleRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/roles/add", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> RemoveMemberRoleAsync(
        MemberRoleRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/roles/remove", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> KickMemberAsync(
        MemberModerationRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/kick", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> BanMemberAsync(
        BanMemberRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/ban", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> UnbanMemberAsync(
        MemberModerationRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/unban", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> TimeoutMemberAsync(
        TimeoutMemberRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/timeout", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> RemoveTimeoutAsync(
        MemberModerationRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/members/timeout/remove", request, cancellationToken);
    }

    public Task<ApiEnvelope<OperationResult>> RenameChannelAsync(
        ChannelRenameRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationResult>(HttpMethod.Post, "api/discord/channels/rename", request, cancellationToken);
    }

    public Task<ApiEnvelope<ClearMessagesResult>> ClearMessagesAsync(
        ClearMessagesRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ClearMessagesResult>(HttpMethod.Post, "api/discord/channels/messages/clear", request, cancellationToken);
    }

    private async Task<ApiEnvelope<T>> SendAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        CancellationToken cancellationToken)
    {
        try
        {
            using var request = new HttpRequestMessage(method, path);
            if (body is not null)
            {
                request.Content = JsonContent.Create(body, options: JsonOptions);
            }

            using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

            if (!string.IsNullOrWhiteSpace(text))
            {
                var envelope = JsonSerializer.Deserialize<ApiEnvelope<T>>(text, JsonOptions);
                if (envelope is not null)
                {
                    return envelope;
                }
            }

            if (response.IsSuccessStatusCode)
            {
                return ApiEnvelope<T>.Ok(default, "Command completed.");
            }

            var message = $"HTTP {(int)response.StatusCode}: {response.ReasonPhrase}";
            if (!string.IsNullOrWhiteSpace(text))
            {
                message += Environment.NewLine + TrimForDisplay(text);
            }

            return ApiEnvelope<T>.Fail(message);
        }
        catch (TaskCanceledException)
        {
            return ApiEnvelope<T>.Fail("Request timed out.");
        }
        catch (Exception ex)
        {
            return ApiEnvelope<T>.Fail(ex.Message);
        }
    }

    private static string NormalizeBaseUrl(string value)
    {
        value = value.Trim();
        if (!value.EndsWith("/", StringComparison.Ordinal))
        {
            value += "/";
        }

        return value;
    }

    private static string TrimForDisplay(string value)
    {
        const int maxLength = 800;
        if (value.Length <= maxLength)
        {
            return value;
        }

        var builder = new StringBuilder(value.AsSpan(0, maxLength).ToString());
        builder.Append("...");
        return builder.ToString();
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }
}
