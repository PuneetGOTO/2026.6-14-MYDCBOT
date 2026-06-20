using System.Text.Json.Serialization;

namespace GJBot.Shared;

public sealed record ApiEnvelope<T>
{
    public bool Success { get; init; }
    public string Message { get; init; } = "";
    public T? Data { get; init; }

    public static ApiEnvelope<T> Ok(T? data, string message = "OK")
    {
        return new ApiEnvelope<T>
        {
            Success = true,
            Message = message,
            Data = data
        };
    }

    public static ApiEnvelope<T> Fail(string message)
    {
        return new ApiEnvelope<T>
        {
            Success = false,
            Message = message
        };
    }
}

public sealed record OperationResult
{
    public string Action { get; init; } = "";
    public string TargetId { get; init; } = "";
    public string Detail { get; init; } = "";
}

public sealed record HealthResponse
{
    public string Service { get; init; } = "GJBot.BotServer";
    public DateTimeOffset ServerTime { get; init; }
    public bool DiscordTokenConfigured { get; init; }
}

public sealed record BotIdentityResponse
{
    public string Id { get; init; } = "";
    public string Username { get; init; } = "";

    [JsonPropertyName("global_name")]
    public string? GlobalName { get; init; }
    public string? Discriminator { get; init; }
}

public sealed record GuildSummary
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string? Icon { get; init; }
    public bool? Owner { get; init; }
    public string? Permissions { get; init; }
    public int? ApproximateMemberCount { get; init; }
    public int? ApproximatePresenceCount { get; init; }
}

public sealed record DiscordChannelSummary
{
    public string Id { get; init; } = "";
    public string GuildId { get; init; } = "";
    public string Name { get; init; } = "";
    public int Type { get; init; }
    public int? Position { get; init; }
    public string? ParentId { get; init; }
    public string DisplayName => Type switch
    {
        0 => "#" + Name,
        2 => "[Voice] " + Name,
        4 => "[Category] " + Name,
        5 => "[Announcement] " + Name,
        _ => $"[{Type}] {Name}"
    };
}

public sealed record DiscordRoleSummary
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

public sealed record GuildOverviewResponse
{
    public GuildSummary Guild { get; init; } = new();
    public List<DiscordChannelSummary> Channels { get; init; } = new();
    public List<DiscordRoleSummary> Roles { get; init; } = new();
}

public sealed record DiscordMessageRequest
{
    public string ChannelId { get; init; } = "";
    public string Content { get; init; } = "";
    public string? EmbedTitle { get; init; }
    public string? EmbedDescription { get; init; }
    public int? EmbedColor { get; init; }
    public bool SuppressMentions { get; init; } = true;
}

public sealed record BroadcastMessageRequest
{
    public List<string> ChannelIds { get; init; } = new();
    public string Content { get; init; } = "";
    public string? EmbedTitle { get; init; }
    public string? EmbedDescription { get; init; }
    public int? EmbedColor { get; init; }
    public bool SuppressMentions { get; init; } = true;
}

public sealed record DirectMessageRequest
{
    public string UserId { get; init; } = "";
    public string Content { get; init; } = "";
    public bool SuppressMentions { get; init; } = true;
}

public sealed record DiscordMessageResult
{
    public string MessageId { get; init; } = "";
    public string ChannelId { get; init; } = "";

    [JsonPropertyName("guild_id")]
    public string? GuildId { get; init; }
    public string JumpUrl { get; init; } = "";
    public DateTimeOffset? CreatedAt { get; init; }
}

public sealed record BroadcastMessageResult
{
    public List<DiscordMessageResult> Sent { get; init; } = new();
    public List<BroadcastFailure> Failed { get; init; } = new();

    [JsonIgnore]
    public bool HasFailures => Failed.Count > 0;
}

public sealed record BroadcastFailure
{
    public string ChannelId { get; init; } = "";
    public string Error { get; init; } = "";
}

public sealed record RoleCreateRequest
{
    public string GuildId { get; init; } = "";
    public string Name { get; init; } = "";
    public int? Color { get; init; }
    public bool Hoist { get; init; }
    public bool Mentionable { get; init; }
    public string? Reason { get; init; }
}

public sealed record RoleDeleteRequest
{
    public string GuildId { get; init; } = "";
    public string RoleId { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record MemberRoleRequest
{
    public string GuildId { get; init; } = "";
    public string UserId { get; init; } = "";
    public string RoleId { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record MemberModerationRequest
{
    public string GuildId { get; init; } = "";
    public string UserId { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record BanMemberRequest
{
    public string GuildId { get; init; } = "";
    public string UserId { get; init; } = "";
    public int DeleteMessageDays { get; init; }
    public string? Reason { get; init; }
}

public sealed record TimeoutMemberRequest
{
    public string GuildId { get; init; } = "";
    public string UserId { get; init; } = "";
    public int DurationMinutes { get; init; }
    public string? Reason { get; init; }
}

public sealed record ChannelRenameRequest
{
    public string ChannelId { get; init; } = "";
    public string NewName { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record ClearMessagesRequest
{
    public string ChannelId { get; init; } = "";
    public int Amount { get; init; }
    public string? Reason { get; init; }
}

public sealed record ClearMessagesResult
{
    public string ChannelId { get; init; } = "";
    public int Requested { get; init; }
    public int Deleted { get; init; }
    public List<string> MessageIds { get; init; } = new();
}
