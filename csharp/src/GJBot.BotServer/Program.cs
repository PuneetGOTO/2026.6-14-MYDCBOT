using GJBot.BotServer;
using GJBot.Shared;

var builder = WebApplication.CreateBuilder(args);

builder.Services.Configure<ControlServerOptions>(options =>
{
    builder.Configuration.GetSection("ControlApi").Bind(options);
    options.ApiKey = Environment.GetEnvironmentVariable("GJBOT_CONTROL_API_KEY") ?? options.ApiKey;
});

builder.Services.Configure<DiscordOptions>(options =>
{
    builder.Configuration.GetSection("Discord").Bind(options);
    options.BotToken = Environment.GetEnvironmentVariable("DISCORD_BOT_TOKEN") ?? options.BotToken;
});

builder.Services.AddHttpClient<DiscordRestClient>(client =>
{
    client.BaseAddress = new Uri("https://discord.com/api/v10/");
    client.DefaultRequestHeaders.UserAgent.ParseAdd("GJBotControlServer/1.0");
    client.Timeout = TimeSpan.FromSeconds(30);
});

var app = builder.Build();

app.UseMiddleware<ApiKeyAuthMiddleware>();

app.MapGet("/", () => Results.Text(
    "GJBot C# BotServer is running. Use /api/health with X-GJBot-Api-Key.",
    "text/plain; charset=utf-8"));

app.MapGet("/api/health", IResult (DiscordRestClient discord) =>
{
    var response = new HealthResponse
    {
        ServerTime = DateTimeOffset.UtcNow,
        DiscordTokenConfigured = discord.BotTokenConfigured
    };

    return Results.Json(ApiEnvelope<HealthResponse>.Ok(response));
});

app.MapGet("/api/discord/me", async Task<IResult> (DiscordRestClient discord, CancellationToken cancellationToken) =>
{
    try
    {
        var identity = await discord.GetCurrentBotAsync(cancellationToken);
        return Results.Json(ApiEnvelope<BotIdentityResponse>.Ok(identity, "Discord Bot token is valid."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<BotIdentityResponse>(ex);
    }
});

app.MapGet("/api/discord/guilds", async Task<IResult> (DiscordRestClient discord, CancellationToken cancellationToken) =>
{
    try
    {
        var guilds = await discord.GetGuildsAsync(cancellationToken);
        return Results.Json(ApiEnvelope<List<GuildSummary>>.Ok(guilds, $"Loaded {guilds.Count} guild(s)."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<List<GuildSummary>>(ex);
    }
});

app.MapGet("/api/discord/guilds/{guildId}/overview", async Task<IResult> (
    string guildId,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateSnowflake(guildId, "guild ID");
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<GuildOverviewResponse>.Fail(validationError));
    }

    try
    {
        var overview = await discord.GetGuildOverviewAsync(guildId, cancellationToken);
        return Results.Json(ApiEnvelope<GuildOverviewResponse>.Ok(overview, "Guild overview loaded."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<GuildOverviewResponse>(ex);
    }
});

app.MapPost("/api/discord/message", async Task<IResult> (
    DiscordMessageRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMessageRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<DiscordMessageResult>.Fail(validationError));
    }

    try
    {
        var result = await discord.SendMessageAsync(request, cancellationToken);
        return Results.Json(ApiEnvelope<DiscordMessageResult>.Ok(result, "Message sent."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<DiscordMessageResult>(ex);
    }
});

app.MapPost("/api/discord/broadcast", async Task<IResult> (
    BroadcastMessageRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateBroadcastRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<BroadcastMessageResult>.Fail(validationError));
    }

    var result = new BroadcastMessageResult();
    foreach (var channelId in request.ChannelIds.Select(static value => value.Trim()).Distinct(StringComparer.Ordinal))
    {
        var itemRequest = new DiscordMessageRequest
        {
            ChannelId = channelId,
            Content = request.Content,
            EmbedTitle = request.EmbedTitle,
            EmbedDescription = request.EmbedDescription,
            EmbedColor = request.EmbedColor,
            SuppressMentions = request.SuppressMentions
        };

        try
        {
            result.Sent.Add(await discord.SendMessageAsync(itemRequest, cancellationToken));
        }
        catch (Exception ex)
        {
            result.Failed.Add(new BroadcastFailure
            {
                ChannelId = channelId,
                Error = ex.Message
            });
        }
    }

    var message = result.HasFailures
        ? $"Broadcast completed with {result.Failed.Count} failure(s)."
        : $"Broadcast sent to {result.Sent.Count} channel(s).";

    return Results.Json(ApiEnvelope<BroadcastMessageResult>.Ok(result, message));
});

app.MapPost("/api/discord/dm", async Task<IResult> (
    DirectMessageRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateDirectMessageRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<DiscordMessageResult>.Fail(validationError));
    }

    try
    {
        var result = await discord.SendDirectMessageAsync(request, cancellationToken);
        return Results.Json(ApiEnvelope<DiscordMessageResult>.Ok(result, "Direct message sent."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<DiscordMessageResult>(ex);
    }
});

app.MapPost("/api/discord/roles", async Task<IResult> (
    RoleCreateRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateRoleCreateRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<DiscordRoleSummary>.Fail(validationError));
    }

    try
    {
        var role = await discord.CreateRoleAsync(request, cancellationToken);
        return Results.Json(ApiEnvelope<DiscordRoleSummary>.Ok(role, "Role created."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<DiscordRoleSummary>(ex);
    }
});

app.MapPost("/api/discord/roles/delete", async Task<IResult> (
    RoleDeleteRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateRoleDeleteRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    try
    {
        var result = await discord.DeleteRoleAsync(request, cancellationToken);
        return Results.Json(ApiEnvelope<OperationResult>.Ok(result, "Role deleted."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<OperationResult>(ex);
    }
});

app.MapPost("/api/discord/members/roles/add", async Task<IResult> (
    MemberRoleRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMemberRoleRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.AddMemberRoleAsync(request, cancellationToken), "Role added.");
});

app.MapPost("/api/discord/members/roles/remove", async Task<IResult> (
    MemberRoleRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMemberRoleRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.RemoveMemberRoleAsync(request, cancellationToken), "Role removed.");
});

app.MapPost("/api/discord/members/kick", async Task<IResult> (
    MemberModerationRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMemberModerationRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.KickMemberAsync(request, cancellationToken), "Member kicked.");
});

app.MapPost("/api/discord/members/ban", async Task<IResult> (
    BanMemberRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateBanRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.BanMemberAsync(request, cancellationToken), "Member banned.");
});

app.MapPost("/api/discord/members/unban", async Task<IResult> (
    MemberModerationRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMemberModerationRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.UnbanMemberAsync(request, cancellationToken), "Member unbanned.");
});

app.MapPost("/api/discord/members/timeout", async Task<IResult> (
    TimeoutMemberRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateTimeoutRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.TimeoutMemberAsync(request, cancellationToken), "Member timed out.");
});

app.MapPost("/api/discord/members/timeout/remove", async Task<IResult> (
    MemberModerationRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateMemberModerationRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.RemoveTimeoutAsync(request, cancellationToken), "Timeout removed.");
});

app.MapPost("/api/discord/channels/rename", async Task<IResult> (
    ChannelRenameRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateChannelRenameRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<OperationResult>.Fail(validationError));
    }

    return await RunOperationAsync(() => discord.RenameChannelAsync(request, cancellationToken), "Channel renamed.");
});

app.MapPost("/api/discord/channels/messages/clear", async Task<IResult> (
    ClearMessagesRequest request,
    DiscordRestClient discord,
    CancellationToken cancellationToken) =>
{
    var validationError = ValidateClearMessagesRequest(request);
    if (validationError is not null)
    {
        return Results.BadRequest(ApiEnvelope<ClearMessagesResult>.Fail(validationError));
    }

    try
    {
        var result = await discord.ClearMessagesAsync(request, cancellationToken);
        return Results.Json(ApiEnvelope<ClearMessagesResult>.Ok(result, $"Deleted {result.Deleted} message(s)."));
    }
    catch (Exception ex)
    {
        return ToErrorResult<ClearMessagesResult>(ex);
    }
});

app.Run();

static async Task<IResult> RunOperationAsync(
    Func<Task<OperationResult>> operation,
    string successMessage)
{
    try
    {
        var result = await operation();
        return Results.Json(ApiEnvelope<OperationResult>.Ok(result, successMessage));
    }
    catch (Exception ex)
    {
        return ToErrorResult<OperationResult>(ex);
    }
}

static string? ValidateMessageRequest(DiscordMessageRequest request)
{
    var content = request.Content ?? "";

    var channelError = ValidateSnowflake(request.ChannelId, "channel ID");
    if (channelError is not null)
    {
        return channelError;
    }

    if (content.Length > 2000)
    {
        return "Discord message content cannot exceed 2000 characters.";
    }

    var hasContent = !string.IsNullOrWhiteSpace(content);
    var hasEmbed = !string.IsNullOrWhiteSpace(request.EmbedTitle) || !string.IsNullOrWhiteSpace(request.EmbedDescription);
    if (!hasContent && !hasEmbed)
    {
        return "Message content or embed content is required.";
    }

    return null;
}

static string? ValidateBroadcastRequest(BroadcastMessageRequest request)
{
    if (request.ChannelIds.Count == 0)
    {
        return "At least one Discord channel ID is required.";
    }

    if (request.ChannelIds.Count > 25)
    {
        return "Broadcast is limited to 25 channels per request.";
    }

    foreach (var channelId in request.ChannelIds)
    {
        var channelError = ValidateSnowflake(channelId.Trim(), "channel ID");
        if (channelError is not null)
        {
            return $"{channelError}: {channelId}";
        }
    }

    return ValidateMessageRequest(new DiscordMessageRequest
    {
        ChannelId = request.ChannelIds[0],
        Content = request.Content,
        EmbedTitle = request.EmbedTitle,
        EmbedDescription = request.EmbedDescription,
        EmbedColor = request.EmbedColor,
        SuppressMentions = request.SuppressMentions
    });
}

static string? ValidateDirectMessageRequest(DirectMessageRequest request)
{
    var userError = ValidateSnowflake(request.UserId, "user ID");
    if (userError is not null)
    {
        return userError;
    }

    if (string.IsNullOrWhiteSpace(request.Content))
    {
        return "Direct message content is required.";
    }

    if (request.Content.Length > 2000)
    {
        return "Discord message content cannot exceed 2000 characters.";
    }

    return null;
}

static string? ValidateRoleCreateRequest(RoleCreateRequest request)
{
    var guildError = ValidateSnowflake(request.GuildId, "guild ID");
    if (guildError is not null)
    {
        return guildError;
    }

    if (string.IsNullOrWhiteSpace(request.Name))
    {
        return "Role name is required.";
    }

    if (request.Name.Length > 100)
    {
        return "Role name cannot exceed 100 characters.";
    }

    if (request.Color is < 0 or > 0xFFFFFF)
    {
        return "Role color must be a valid RGB hex color.";
    }

    return null;
}

static string? ValidateRoleDeleteRequest(RoleDeleteRequest request)
{
    return ValidateSnowflake(request.GuildId, "guild ID") ??
           ValidateSnowflake(request.RoleId, "role ID");
}

static string? ValidateMemberRoleRequest(MemberRoleRequest request)
{
    return ValidateSnowflake(request.GuildId, "guild ID") ??
           ValidateSnowflake(request.UserId, "user ID") ??
           ValidateSnowflake(request.RoleId, "role ID");
}

static string? ValidateMemberModerationRequest(MemberModerationRequest request)
{
    return ValidateSnowflake(request.GuildId, "guild ID") ??
           ValidateSnowflake(request.UserId, "user ID");
}

static string? ValidateBanRequest(BanMemberRequest request)
{
    if (request.DeleteMessageDays is < 0 or > 7)
    {
        return "DeleteMessageDays must be between 0 and 7.";
    }

    return ValidateSnowflake(request.GuildId, "guild ID") ??
           ValidateSnowflake(request.UserId, "user ID");
}

static string? ValidateTimeoutRequest(TimeoutMemberRequest request)
{
    if (request.DurationMinutes < 0)
    {
        return "DurationMinutes cannot be negative. Use 0 for the maximum Discord timeout.";
    }

    if (request.DurationMinutes > 28 * 24 * 60)
    {
        return "Discord timeout cannot exceed 28 days.";
    }

    return ValidateSnowflake(request.GuildId, "guild ID") ??
           ValidateSnowflake(request.UserId, "user ID");
}

static string? ValidateChannelRenameRequest(ChannelRenameRequest request)
{
    var channelError = ValidateSnowflake(request.ChannelId, "channel ID");
    if (channelError is not null)
    {
        return channelError;
    }

    if (string.IsNullOrWhiteSpace(request.NewName))
    {
        return "New channel name is required.";
    }

    if (request.NewName.Length is < 1 or > 100)
    {
        return "Channel name length must be between 1 and 100 characters.";
    }

    return null;
}

static string? ValidateClearMessagesRequest(ClearMessagesRequest request)
{
    var channelError = ValidateSnowflake(request.ChannelId, "channel ID");
    if (channelError is not null)
    {
        return channelError;
    }

    if (request.Amount is < 1 or > 100)
    {
        return "Amount must be between 1 and 100.";
    }

    return null;
}

static string? ValidateSnowflake(string value, string name)
{
    if (string.IsNullOrWhiteSpace(value) || !ulong.TryParse(value.Trim(), out _))
    {
        return $"A valid Discord {name} is required.";
    }

    return null;
}

static IResult ToErrorResult<T>(Exception ex)
{
    return ex switch
    {
        DiscordApiException discordEx => Results.Json(
            ApiEnvelope<T>.Fail(discordEx.Message),
            statusCode: discordEx.StatusCode),
        InvalidOperationException => Results.Json(
            ApiEnvelope<T>.Fail(ex.Message),
            statusCode: StatusCodes.Status503ServiceUnavailable),
        _ => Results.Json(
            ApiEnvelope<T>.Fail(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError)
    };
}
