using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using GJBot.Shared;
using Microsoft.Extensions.Options;

namespace GJBot.BotServer;

public sealed class DiscordRestClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    private readonly HttpClient _httpClient;
    private readonly IOptionsMonitor<DiscordOptions> _options;

    public DiscordRestClient(HttpClient httpClient, IOptionsMonitor<DiscordOptions> options)
    {
        _httpClient = httpClient;
        _options = options;
    }

    public bool BotTokenConfigured => !string.IsNullOrWhiteSpace(_options.CurrentValue.BotToken);

    public Task<BotIdentityResponse> GetCurrentBotAsync(CancellationToken cancellationToken)
    {
        return SendDiscordAsync<BotIdentityResponse>(HttpMethod.Get, "users/@me", null, null, cancellationToken);
    }

    public async Task<List<GuildSummary>> GetGuildsAsync(CancellationToken cancellationToken)
    {
        var guilds = await SendDiscordAsync<List<DiscordGuildDto>>(
            HttpMethod.Get,
            "users/@me/guilds",
            null,
            null,
            cancellationToken).ConfigureAwait(false);

        return guilds.Select(static guild => new GuildSummary
        {
            Id = guild.Id,
            Name = guild.Name,
            Icon = guild.Icon,
            Owner = guild.Owner,
            Permissions = guild.Permissions,
            ApproximateMemberCount = guild.ApproximateMemberCount,
            ApproximatePresenceCount = guild.ApproximatePresenceCount
        }).ToList();
    }

    public async Task<GuildOverviewResponse> GetGuildOverviewAsync(string guildId, CancellationToken cancellationToken)
    {
        var guildTask = SendDiscordAsync<DiscordGuildDto>(
            HttpMethod.Get,
            $"guilds/{Url(guildId)}?with_counts=true",
            null,
            null,
            cancellationToken);
        var channelsTask = GetGuildChannelsAsync(guildId, cancellationToken);
        var rolesTask = GetGuildRolesAsync(guildId, cancellationToken);

        await Task.WhenAll(guildTask, channelsTask, rolesTask).ConfigureAwait(false);

        var guild = await guildTask.ConfigureAwait(false);
        return new GuildOverviewResponse
        {
            Guild = new GuildSummary
            {
                Id = guild.Id,
                Name = guild.Name,
                Icon = guild.Icon,
                Owner = guild.Owner,
                Permissions = guild.Permissions,
                ApproximateMemberCount = guild.ApproximateMemberCount,
                ApproximatePresenceCount = guild.ApproximatePresenceCount
            },
            Channels = await channelsTask.ConfigureAwait(false),
            Roles = await rolesTask.ConfigureAwait(false)
        };
    }

    public async Task<List<DiscordChannelSummary>> GetGuildChannelsAsync(string guildId, CancellationToken cancellationToken)
    {
        var channels = await SendDiscordAsync<List<DiscordChannelDto>>(
            HttpMethod.Get,
            $"guilds/{Url(guildId)}/channels",
            null,
            null,
            cancellationToken).ConfigureAwait(false);

        return channels
            .Select(static channel => new DiscordChannelSummary
            {
                Id = channel.Id,
                GuildId = channel.GuildId ?? "",
                Name = channel.Name ?? "",
                Type = channel.Type,
                Position = channel.Position,
                ParentId = channel.ParentId
            })
            .OrderBy(static channel => channel.Type == 4 ? 0 : 1)
            .ThenBy(static channel => channel.Position ?? int.MaxValue)
            .ThenBy(static channel => channel.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public async Task<List<DiscordRoleSummary>> GetGuildRolesAsync(string guildId, CancellationToken cancellationToken)
    {
        var roles = await SendDiscordAsync<List<DiscordRoleDto>>(
            HttpMethod.Get,
            $"guilds/{Url(guildId)}/roles",
            null,
            null,
            cancellationToken).ConfigureAwait(false);

        return roles
            .Select(ToRoleSummary)
            .OrderByDescending(static role => role.Position)
            .ThenBy(static role => role.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public async Task<DiscordMessageResult> SendMessageAsync(
        DiscordMessageRequest request,
        CancellationToken cancellationToken)
    {
        var payload = CreateMessagePayload.FromRequest(request);
        var message = await SendDiscordAsync<DiscordMessageDto>(
            HttpMethod.Post,
            $"channels/{Url(request.ChannelId)}/messages",
            payload,
            null,
            cancellationToken).ConfigureAwait(false);

        return ToMessageResult(message);
    }

    public async Task<DiscordMessageResult> SendDirectMessageAsync(
        DirectMessageRequest request,
        CancellationToken cancellationToken)
    {
        var dm = await SendDiscordAsync<DiscordDmChannelDto>(
            HttpMethod.Post,
            "users/@me/channels",
            new CreateDmPayload { RecipientId = request.UserId },
            null,
            cancellationToken).ConfigureAwait(false);

        return await SendMessageAsync(new DiscordMessageRequest
        {
            ChannelId = dm.Id,
            Content = request.Content,
            SuppressMentions = request.SuppressMentions
        }, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DiscordRoleSummary> CreateRoleAsync(RoleCreateRequest request, CancellationToken cancellationToken)
    {
        var role = await SendDiscordAsync<DiscordRoleDto>(
            HttpMethod.Post,
            $"guilds/{Url(request.GuildId)}/roles",
            new CreateRolePayload
            {
                Name = request.Name,
                Color = request.Color,
                Hoist = request.Hoist,
                Mentionable = request.Mentionable
            },
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return ToRoleSummary(role);
    }

    public async Task<OperationResult> DeleteRoleAsync(RoleDeleteRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Delete,
            $"guilds/{Url(request.GuildId)}/roles/{Url(request.RoleId)}",
            null,
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("delete-role", request.RoleId, "Role deleted.");
    }

    public async Task<OperationResult> AddMemberRoleAsync(MemberRoleRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Put,
            $"guilds/{Url(request.GuildId)}/members/{Url(request.UserId)}/roles/{Url(request.RoleId)}",
            null,
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("add-member-role", request.UserId, $"Role {request.RoleId} added.");
    }

    public async Task<OperationResult> RemoveMemberRoleAsync(MemberRoleRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Delete,
            $"guilds/{Url(request.GuildId)}/members/{Url(request.UserId)}/roles/{Url(request.RoleId)}",
            null,
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("remove-member-role", request.UserId, $"Role {request.RoleId} removed.");
    }

    public async Task<OperationResult> KickMemberAsync(MemberModerationRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Delete,
            $"guilds/{Url(request.GuildId)}/members/{Url(request.UserId)}",
            null,
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("kick-member", request.UserId, "Member kicked.");
    }

    public async Task<OperationResult> BanMemberAsync(BanMemberRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Put,
            $"guilds/{Url(request.GuildId)}/bans/{Url(request.UserId)}",
            new BanPayload { DeleteMessageSeconds = Math.Clamp(request.DeleteMessageDays, 0, 7) * 86400 },
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("ban-member", request.UserId, "Member banned.");
    }

    public async Task<OperationResult> UnbanMemberAsync(MemberModerationRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Delete,
            $"guilds/{Url(request.GuildId)}/bans/{Url(request.UserId)}",
            null,
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("unban-member", request.UserId, "Member unbanned.");
    }

    public async Task<OperationResult> TimeoutMemberAsync(TimeoutMemberRequest request, CancellationToken cancellationToken)
    {
        var duration = request.DurationMinutes <= 0
            ? TimeSpan.FromDays(28)
            : TimeSpan.FromMinutes(Math.Min(request.DurationMinutes, 28 * 24 * 60));

        var until = DateTimeOffset.UtcNow.Add(duration);
        await SendDiscordNoContentAsync(
            HttpMethod.Patch,
            $"guilds/{Url(request.GuildId)}/members/{Url(request.UserId)}",
            new TimeoutPayload { CommunicationDisabledUntil = until },
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("timeout-member", request.UserId, $"Member timed out until {until:O}.");
    }

    public async Task<OperationResult> RemoveTimeoutAsync(MemberModerationRequest request, CancellationToken cancellationToken)
    {
        await SendDiscordNoContentAsync(
            HttpMethod.Patch,
            $"guilds/{Url(request.GuildId)}/members/{Url(request.UserId)}",
            new TimeoutPayload { CommunicationDisabledUntil = null },
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("remove-timeout", request.UserId, "Member timeout removed.");
    }

    public async Task<OperationResult> RenameChannelAsync(ChannelRenameRequest request, CancellationToken cancellationToken)
    {
        var channel = await SendDiscordAsync<DiscordChannelDto>(
            HttpMethod.Patch,
            $"channels/{Url(request.ChannelId)}",
            new RenameChannelPayload { Name = request.NewName },
            request.Reason,
            cancellationToken).ConfigureAwait(false);

        return Result("rename-channel", request.ChannelId, $"Channel renamed to {channel.Name}.");
    }

    public async Task<ClearMessagesResult> ClearMessagesAsync(ClearMessagesRequest request, CancellationToken cancellationToken)
    {
        var amount = Math.Clamp(request.Amount, 1, 100);
        var messages = await SendDiscordAsync<List<DiscordMessageDto>>(
            HttpMethod.Get,
            $"channels/{Url(request.ChannelId)}/messages?limit={amount}",
            null,
            null,
            cancellationToken).ConfigureAwait(false);

        var deletable = messages
            .Where(static message => ParseTimestamp(message.Timestamp) is DateTimeOffset createdAt &&
                                     DateTimeOffset.UtcNow - createdAt < TimeSpan.FromDays(14))
            .Select(static message => message.Id)
            .ToList();

        if (deletable.Count == 1)
        {
            await SendDiscordNoContentAsync(
                HttpMethod.Delete,
                $"channels/{Url(request.ChannelId)}/messages/{Url(deletable[0])}",
                null,
                request.Reason,
                cancellationToken).ConfigureAwait(false);
        }
        else if (deletable.Count > 1)
        {
            await SendDiscordNoContentAsync(
                HttpMethod.Post,
                $"channels/{Url(request.ChannelId)}/messages/bulk-delete",
                new BulkDeletePayload { Messages = deletable },
                request.Reason,
                cancellationToken).ConfigureAwait(false);
        }

        return new ClearMessagesResult
        {
            ChannelId = request.ChannelId,
            Requested = amount,
            Deleted = deletable.Count,
            MessageIds = deletable
        };
    }

    private async Task<T> SendDiscordAsync<T>(
        HttpMethod method,
        string relativePath,
        object? body,
        string? auditLogReason,
        CancellationToken cancellationToken)
    {
        var response = await SendDiscordRawAsync(method, relativePath, body, auditLogReason, cancellationToken)
            .ConfigureAwait(false);
        using (response)
        {
            return await ReadDiscordResponseAsync<T>(response, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task SendDiscordNoContentAsync(
        HttpMethod method,
        string relativePath,
        object? body,
        string? auditLogReason,
        CancellationToken cancellationToken)
    {
        var response = await SendDiscordRawAsync(method, relativePath, body, auditLogReason, cancellationToken)
            .ConfigureAwait(false);
        using (response)
        {
            await EnsureDiscordSuccessAsync(response, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<HttpResponseMessage> SendDiscordRawAsync(
        HttpMethod method,
        string relativePath,
        object? body,
        string? auditLogReason,
        CancellationToken cancellationToken)
    {
        var token = _options.CurrentValue.BotToken;
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("Discord:BotToken or DISCORD_BOT_TOKEN is not configured.");
        }

        var response = await SendDiscordOnceRawAsync(method, relativePath, body, auditLogReason, token, cancellationToken)
            .ConfigureAwait(false);
        if (response.StatusCode != (HttpStatusCode)429)
        {
            return response;
        }

        using (response)
        {
            await DelayForRateLimitAsync(response, cancellationToken).ConfigureAwait(false);
        }

        return await SendDiscordOnceRawAsync(method, relativePath, body, auditLogReason, token, cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task<HttpResponseMessage> SendDiscordOnceRawAsync(
        HttpMethod method,
        string relativePath,
        object? body,
        string? auditLogReason,
        string token,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativePath);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bot", token);
        if (!string.IsNullOrWhiteSpace(auditLogReason))
        {
            request.Headers.TryAddWithoutValidation("X-Audit-Log-Reason", Uri.EscapeDataString(auditLogReason));
        }

        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: JsonOptions);
        }

        return await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<T> ReadDiscordResponseAsync<T>(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new DiscordApiException((int)response.StatusCode, BuildDiscordError(response, text));
        }

        if (typeof(T) == typeof(string))
        {
            return (T)(object)text;
        }

        var result = JsonSerializer.Deserialize<T>(text, JsonOptions);
        if (result is null)
        {
            throw new DiscordApiException((int)response.StatusCode, "Discord returned an empty response.");
        }

        return result;
    }

    private static async Task EnsureDiscordSuccessAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        throw new DiscordApiException((int)response.StatusCode, BuildDiscordError(response, text));
    }

    private static async Task DelayForRateLimitAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var delay = TimeSpan.FromSeconds(2);

        if (response.Headers.TryGetValues("Retry-After", out var retryAfterValues) &&
            double.TryParse(retryAfterValues.FirstOrDefault(), NumberStyles.Float, CultureInfo.InvariantCulture, out var retryAfterSeconds))
        {
            delay = TimeSpan.FromSeconds(Math.Clamp(retryAfterSeconds, 0.5, 10));
        }
        else
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            var parsedDelay = TryParseRetryAfter(text);
            if (parsedDelay is not null)
            {
                delay = parsedDelay.Value;
            }
        }

        await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
    }

    private static TimeSpan? TryParseRetryAfter(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            if (document.RootElement.TryGetProperty("retry_after", out var retryAfter) &&
                retryAfter.TryGetDouble(out var seconds))
            {
                return TimeSpan.FromSeconds(Math.Clamp(seconds, 0.5, 10));
            }
        }
        catch (JsonException)
        {
        }

        return null;
    }

    private static string BuildDiscordError(HttpResponseMessage response, string text)
    {
        var message = $"Discord API HTTP {(int)response.StatusCode}: {response.ReasonPhrase}";
        if (string.IsNullOrWhiteSpace(text))
        {
            return message;
        }

        try
        {
            using var document = JsonDocument.Parse(text);
            if (document.RootElement.TryGetProperty("message", out var discordMessage))
            {
                var code = document.RootElement.TryGetProperty("code", out var codeElement)
                    ? $" ({codeElement})"
                    : "";
                return $"{message} - {discordMessage.GetString()}{code}";
            }
        }
        catch (JsonException)
        {
        }

        return $"{message} - {text}";
    }

    private static DiscordMessageResult ToMessageResult(DiscordMessageDto message)
    {
        return new DiscordMessageResult
        {
            MessageId = message.Id,
            ChannelId = message.ChannelId,
            GuildId = message.GuildId,
            JumpUrl = BuildJumpUrl(message),
            CreatedAt = ParseTimestamp(message.Timestamp)
        };
    }

    private static DiscordRoleSummary ToRoleSummary(DiscordRoleDto role)
    {
        return new DiscordRoleSummary
        {
            Id = role.Id,
            Name = role.Name,
            Color = role.Color,
            Position = role.Position,
            Permissions = role.Permissions,
            Hoist = role.Hoist,
            Mentionable = role.Mentionable,
            Managed = role.Managed
        };
    }

    private static OperationResult Result(string action, string targetId, string detail)
    {
        return new OperationResult
        {
            Action = action,
            TargetId = targetId,
            Detail = detail
        };
    }

    private static string BuildJumpUrl(DiscordMessageDto message)
    {
        var guildPart = string.IsNullOrWhiteSpace(message.GuildId) ? "@me" : message.GuildId;
        return $"https://discord.com/channels/{guildPart}/{message.ChannelId}/{message.Id}";
    }

    private static DateTimeOffset? ParseTimestamp(string? timestamp)
    {
        if (DateTimeOffset.TryParse(timestamp, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var parsed))
        {
            return parsed;
        }

        return null;
    }

    private static string Url(string value)
    {
        return WebUtility.UrlEncode(value);
    }

    private sealed record CreateMessagePayload
    {
        public string? Content { get; init; }

        [JsonPropertyName("allowed_mentions")]
        public AllowedMentionsPayload? AllowedMentions { get; init; }

        public List<EmbedPayload>? Embeds { get; init; }

        public static CreateMessagePayload FromRequest(DiscordMessageRequest request)
        {
            var embed = string.IsNullOrWhiteSpace(request.EmbedTitle) && string.IsNullOrWhiteSpace(request.EmbedDescription)
                ? null
                : new EmbedPayload
                {
                    Title = string.IsNullOrWhiteSpace(request.EmbedTitle) ? null : request.EmbedTitle.Trim(),
                    Description = string.IsNullOrWhiteSpace(request.EmbedDescription) ? null : request.EmbedDescription.Trim(),
                    Color = request.EmbedColor
                };

            return new CreateMessagePayload
            {
                Content = string.IsNullOrWhiteSpace(request.Content) ? null : request.Content,
                AllowedMentions = request.SuppressMentions ? new AllowedMentionsPayload { Parse = Array.Empty<string>() } : null,
                Embeds = embed is null ? null : new List<EmbedPayload> { embed }
            };
        }
    }

    private sealed record AllowedMentionsPayload
    {
        public string[] Parse { get; init; } = Array.Empty<string>();
    }

    private sealed record EmbedPayload
    {
        public string? Title { get; init; }
        public string? Description { get; init; }
        public int? Color { get; init; }
    }

    private sealed record CreateDmPayload
    {
        [JsonPropertyName("recipient_id")]
        public string RecipientId { get; init; } = "";
    }

    private sealed record CreateRolePayload
    {
        public string Name { get; init; } = "";
        public int? Color { get; init; }
        public bool Hoist { get; init; }
        public bool Mentionable { get; init; }
    }

    private sealed record BanPayload
    {
        [JsonPropertyName("delete_message_seconds")]
        public int DeleteMessageSeconds { get; init; }
    }

    private sealed record TimeoutPayload
    {
        [JsonPropertyName("communication_disabled_until")]
        public DateTimeOffset? CommunicationDisabledUntil { get; init; }
    }

    private sealed record RenameChannelPayload
    {
        public string Name { get; init; } = "";
    }

    private sealed record BulkDeletePayload
    {
        public List<string> Messages { get; init; } = new();
    }

    private sealed record DiscordGuildDto
    {
        public string Id { get; init; } = "";
        public string Name { get; init; } = "";
        public string? Icon { get; init; }
        public bool? Owner { get; init; }
        public string? Permissions { get; init; }

        [JsonPropertyName("approximate_member_count")]
        public int? ApproximateMemberCount { get; init; }

        [JsonPropertyName("approximate_presence_count")]
        public int? ApproximatePresenceCount { get; init; }
    }

    private sealed record DiscordChannelDto
    {
        public string Id { get; init; } = "";

        [JsonPropertyName("guild_id")]
        public string? GuildId { get; init; }

        public string? Name { get; init; }
        public int Type { get; init; }
        public int? Position { get; init; }

        [JsonPropertyName("parent_id")]
        public string? ParentId { get; init; }
    }

    private sealed record DiscordRoleDto
    {
        public string Id { get; init; } = "";
        public string Name { get; init; } = "";
        public int Color { get; init; }
        public int Position { get; init; }
        public string Permissions { get; init; } = "";
        public bool Hoist { get; init; }
        public bool Mentionable { get; init; }
        public bool Managed { get; init; }
    }

    private sealed record DiscordDmChannelDto
    {
        public string Id { get; init; } = "";
    }

    private sealed record DiscordMessageDto
    {
        public string Id { get; init; } = "";

        [JsonPropertyName("channel_id")]
        public string ChannelId { get; init; } = "";

        [JsonPropertyName("guild_id")]
        public string? GuildId { get; init; }

        public string? Timestamp { get; init; }
    }
}
