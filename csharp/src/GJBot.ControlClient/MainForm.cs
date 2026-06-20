using System.Globalization;
using GJBot.Shared;

namespace GJBot.ControlClient;

public sealed class MainForm : Form
{
    private readonly TextBox _backendUrlTextBox = new();
    private readonly TextBox _apiKeyTextBox = new();
    private readonly TextBox _guildIdTextBox = new();
    private readonly TextBox _channelIdTextBox = new();
    private readonly TextBox _contentTextBox = new();
    private readonly TextBox _embedTitleTextBox = new();
    private readonly TextBox _embedDescriptionTextBox = new();
    private readonly TextBox _embedColorTextBox = new();
    private readonly TextBox _broadcastChannelsTextBox = new();
    private readonly TextBox _roleNameTextBox = new();
    private readonly TextBox _roleIdTextBox = new();
    private readonly TextBox _roleColorTextBox = new();
    private readonly CheckBox _roleHoistCheckBox = new();
    private readonly CheckBox _roleMentionableCheckBox = new();
    private readonly TextBox _memberUserIdTextBox = new();
    private readonly TextBox _memberRoleIdTextBox = new();
    private readonly NumericUpDown _timeoutMinutesBox = new();
    private readonly NumericUpDown _deleteMessageDaysBox = new();
    private readonly TextBox _roleReasonTextBox = new();
    private readonly TextBox _memberReasonTextBox = new();
    private readonly TextBox _channelReasonTextBox = new();
    private readonly TextBox _newChannelNameTextBox = new();
    private readonly NumericUpDown _clearAmountBox = new();
    private readonly TextBox _dmUserIdTextBox = new();
    private readonly TextBox _dmContentTextBox = new();
    private readonly TextBox _overviewTextBox = new();
    private readonly TextBox _logTextBox = new();
    private readonly CheckBox _suppressMentionsCheckBox = new();
    private readonly ToolStripStatusLabel _statusLabel = new();

    private ClientSettings _settings;

    public MainForm()
    {
        _settings = SettingsStore.Load();
        InitializeComponent();
        LoadSettingsIntoControls();
    }

    private void InitializeComponent()
    {
        Text = "GJBot 我的控制客戶端";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1100, 760);
        Size = new Size(1220, 860);
        Font = new Font("Microsoft JhengHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(12)
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 174));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 170));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));

        var serverGroup = CreateServerGroup();
        var commandTabs = CreateCommandTabs();
        var logGroup = CreateLogGroup();
        var statusStrip = new StatusStrip();
        statusStrip.Items.Add(_statusLabel);
        _statusLabel.Text = "就緒";

        root.Controls.Add(serverGroup, 0, 0);
        root.Controls.Add(commandTabs, 0, 1);
        root.Controls.Add(logGroup, 0, 2);
        root.Controls.Add(statusStrip, 0, 3);

        Controls.Add(root);
    }

    private GroupBox CreateServerGroup()
    {
        var group = new GroupBox
        {
            Text = "後端連線與常用 ID",
            Dock = DockStyle.Fill
        };

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            RowCount = 4,
            Padding = new Padding(10)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));

        _backendUrlTextBox.Dock = DockStyle.Fill;
        _apiKeyTextBox.Dock = DockStyle.Fill;
        _apiKeyTextBox.UseSystemPasswordChar = true;
        _guildIdTextBox.Dock = DockStyle.Fill;
        _channelIdTextBox.Dock = DockStyle.Fill;

        var saveButton = new Button { Text = "儲存設定", Width = 120, Height = 32 };
        saveButton.Click += (_, _) => SaveSettingsFromControls();

        var testButton = new Button { Text = "測試連線", Width = 120, Height = 32 };
        testButton.Click += async (_, _) => await TestConnectionAsync();

        var guildsButton = new Button { Text = "列出伺服器", Width = 120, Height = 32 };
        guildsButton.Click += async (_, _) => await LoadGuildsAsync();

        var overviewButton = new Button { Text = "載入總覽", Width = 120, Height = 32 };
        overviewButton.Click += async (_, _) => await LoadGuildOverviewAsync();

        var buttonPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight
        };
        buttonPanel.Controls.Add(saveButton);
        buttonPanel.Controls.Add(testButton);
        buttonPanel.Controls.Add(guildsButton);
        buttonPanel.Controls.Add(overviewButton);

        layout.Controls.Add(CreateLabel("後端地址"), 0, 0);
        layout.Controls.Add(_backendUrlTextBox, 1, 0);
        layout.SetColumnSpan(_backendUrlTextBox, 3);
        layout.Controls.Add(CreateLabel("API Key"), 0, 1);
        layout.Controls.Add(_apiKeyTextBox, 1, 1);
        layout.SetColumnSpan(_apiKeyTextBox, 3);
        layout.Controls.Add(CreateLabel("伺服器 ID"), 0, 2);
        layout.Controls.Add(_guildIdTextBox, 1, 2);
        layout.Controls.Add(CreateLabel("頻道 ID"), 2, 2);
        layout.Controls.Add(_channelIdTextBox, 3, 2);
        layout.Controls.Add(buttonPanel, 1, 3);
        layout.SetColumnSpan(buttonPanel, 3);

        group.Controls.Add(layout);
        return group;
    }

    private TabControl CreateCommandTabs()
    {
        var tabs = new TabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(CreateOverviewTab());
        tabs.TabPages.Add(CreateSingleMessageTab());
        tabs.TabPages.Add(CreateBroadcastTab());
        tabs.TabPages.Add(CreateRolesTab());
        tabs.TabPages.Add(CreateMemberTab());
        tabs.TabPages.Add(CreateChannelToolsTab());
        tabs.TabPages.Add(CreateDmTab());
        return tabs;
    }

    private TabPage CreateOverviewTab()
    {
        var tab = new TabPage("伺服器總覽");
        _overviewTextBox.Dock = DockStyle.Fill;
        _overviewTextBox.Multiline = true;
        _overviewTextBox.ReadOnly = true;
        _overviewTextBox.ScrollBars = ScrollBars.Both;
        _overviewTextBox.Font = new Font("Consolas", 9F, FontStyle.Regular, GraphicsUnit.Point);
        tab.Controls.Add(_overviewTextBox);
        return tab;
    }

    private TabPage CreateSingleMessageTab()
    {
        var tab = new TabPage("消息/公告");
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 6,
            Padding = new Padding(12)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 44));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 26));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        _contentTextBox.Dock = DockStyle.Fill;
        _contentTextBox.Multiline = true;
        _contentTextBox.ScrollBars = ScrollBars.Vertical;
        _embedTitleTextBox.Dock = DockStyle.Fill;
        _embedDescriptionTextBox.Dock = DockStyle.Fill;
        _embedDescriptionTextBox.Multiline = true;
        _embedDescriptionTextBox.ScrollBars = ScrollBars.Vertical;
        _embedColorTextBox.Dock = DockStyle.Left;
        _embedColorTextBox.Width = 160;
        _embedColorTextBox.PlaceholderText = "#5865F2";
        _suppressMentionsCheckBox.Text = "禁用 @everyone/@here/@role 解析";
        _suppressMentionsCheckBox.AutoSize = true;

        var sendButton = new Button { Text = "發送消息", Width = 130, Height = 34 };
        sendButton.Click += async (_, _) => await SendMessageAsync();

        var bottomPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        bottomPanel.Controls.Add(sendButton);
        bottomPanel.Controls.Add(_suppressMentionsCheckBox);

        layout.Controls.Add(CreateLabel("文字內容"), 0, 0);
        layout.Controls.Add(_contentTextBox, 1, 0);
        layout.Controls.Add(CreateLabel("Embed 標題"), 0, 1);
        layout.Controls.Add(_embedTitleTextBox, 1, 1);
        layout.Controls.Add(CreateLabel("Embed 內容"), 0, 2);
        layout.Controls.Add(_embedDescriptionTextBox, 1, 2);
        layout.Controls.Add(CreateLabel("Embed 顏色"), 0, 3);
        layout.Controls.Add(_embedColorTextBox, 1, 3);
        layout.Controls.Add(bottomPanel, 1, 5);

        tab.Controls.Add(layout);
        return tab;
    }

    private TabPage CreateBroadcastTab()
    {
        var tab = new TabPage("批量廣播");
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 3,
            Padding = new Padding(12)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        _broadcastChannelsTextBox.Dock = DockStyle.Fill;
        _broadcastChannelsTextBox.Multiline = true;
        _broadcastChannelsTextBox.ScrollBars = ScrollBars.Vertical;

        var hint = new Label
        {
            Text = "每行一個頻道 ID，也可用逗號或空格分隔。廣播使用「消息/公告」頁的文字與 Embed 設定。",
            AutoSize = true,
            Dock = DockStyle.Fill
        };

        var broadcastButton = new Button { Text = "開始廣播", Width = 130, Height = 34 };
        broadcastButton.Click += async (_, _) => await BroadcastAsync();

        layout.Controls.Add(CreateLabel("頻道列表"), 0, 0);
        layout.Controls.Add(_broadcastChannelsTextBox, 1, 0);
        layout.Controls.Add(hint, 1, 1);
        layout.Controls.Add(broadcastButton, 1, 2);
        tab.Controls.Add(layout);
        return tab;
    }

    private TabPage CreateRolesTab()
    {
        var tab = new TabPage("身份組");
        var layout = CreateFormLayout(7);

        _roleNameTextBox.Dock = DockStyle.Fill;
        _roleIdTextBox.Dock = DockStyle.Fill;
        _roleColorTextBox.Dock = DockStyle.Left;
        _roleColorTextBox.Width = 160;
        _roleColorTextBox.PlaceholderText = "#2ECC71";
        _roleHoistCheckBox.Text = "分開顯示";
        _roleMentionableCheckBox.Text = "允許提及";

        var createButton = new Button { Text = "建立身份組", Width = 130, Height = 34 };
        createButton.Click += async (_, _) => await CreateRoleAsync();
        var deleteButton = new Button { Text = "刪除身份組", Width = 130, Height = 34 };
        deleteButton.Click += async (_, _) => await DeleteRoleAsync();

        var roleOptions = new FlowLayoutPanel { Dock = DockStyle.Fill };
        roleOptions.Controls.Add(_roleHoistCheckBox);
        roleOptions.Controls.Add(_roleMentionableCheckBox);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        buttons.Controls.Add(createButton);
        buttons.Controls.Add(deleteButton);

        layout.Controls.Add(CreateLabel("名稱"), 0, 0);
        layout.Controls.Add(_roleNameTextBox, 1, 0);
        layout.Controls.Add(CreateLabel("身份組 ID"), 0, 1);
        layout.Controls.Add(_roleIdTextBox, 1, 1);
        layout.Controls.Add(CreateLabel("顏色"), 0, 2);
        layout.Controls.Add(_roleColorTextBox, 1, 2);
        layout.Controls.Add(CreateLabel("選項"), 0, 3);
        layout.Controls.Add(roleOptions, 1, 3);
        layout.Controls.Add(CreateLabel("原因"), 0, 4);
        _roleReasonTextBox.Dock = DockStyle.Fill;
        layout.Controls.Add(_roleReasonTextBox, 1, 4);
        layout.Controls.Add(buttons, 1, 6);
        tab.Controls.Add(layout);
        return tab;
    }

    private TabPage CreateMemberTab()
    {
        var tab = new TabPage("成員管理");
        var layout = CreateFormLayout(9);

        _memberUserIdTextBox.Dock = DockStyle.Fill;
        _memberRoleIdTextBox.Dock = DockStyle.Fill;
        _timeoutMinutesBox.Minimum = 0;
        _timeoutMinutesBox.Maximum = 40320;
        _timeoutMinutesBox.Value = 60;
        _timeoutMinutesBox.Dock = DockStyle.Left;
        _timeoutMinutesBox.Width = 130;
        _deleteMessageDaysBox.Minimum = 0;
        _deleteMessageDaysBox.Maximum = 7;
        _deleteMessageDaysBox.Dock = DockStyle.Left;
        _deleteMessageDaysBox.Width = 130;

        var addRoleButton = new Button { Text = "授予身份組", Width = 130, Height = 34 };
        addRoleButton.Click += async (_, _) => await AddMemberRoleAsync();
        var removeRoleButton = new Button { Text = "移除身份組", Width = 130, Height = 34 };
        removeRoleButton.Click += async (_, _) => await RemoveMemberRoleAsync();
        var timeoutButton = new Button { Text = "禁言", Width = 100, Height = 34 };
        timeoutButton.Click += async (_, _) => await TimeoutMemberAsync();
        var removeTimeoutButton = new Button { Text = "解除禁言", Width = 110, Height = 34 };
        removeTimeoutButton.Click += async (_, _) => await RemoveTimeoutAsync();
        var kickButton = new Button { Text = "踢出", Width = 90, Height = 34 };
        kickButton.Click += async (_, _) => await KickMemberAsync();
        var banButton = new Button { Text = "封禁", Width = 90, Height = 34 };
        banButton.Click += async (_, _) => await BanMemberAsync();
        var unbanButton = new Button { Text = "解封", Width = 90, Height = 34 };
        unbanButton.Click += async (_, _) => await UnbanMemberAsync();

        var roleButtons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        roleButtons.Controls.Add(addRoleButton);
        roleButtons.Controls.Add(removeRoleButton);

        var modButtons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        modButtons.Controls.Add(timeoutButton);
        modButtons.Controls.Add(removeTimeoutButton);
        modButtons.Controls.Add(kickButton);
        modButtons.Controls.Add(banButton);
        modButtons.Controls.Add(unbanButton);

        layout.Controls.Add(CreateLabel("使用者 ID"), 0, 0);
        layout.Controls.Add(_memberUserIdTextBox, 1, 0);
        layout.Controls.Add(CreateLabel("身份組 ID"), 0, 1);
        layout.Controls.Add(_memberRoleIdTextBox, 1, 1);
        layout.Controls.Add(CreateLabel("禁言分鐘"), 0, 2);
        layout.Controls.Add(_timeoutMinutesBox, 1, 2);
        layout.Controls.Add(CreateLabel("刪訊天數"), 0, 3);
        layout.Controls.Add(_deleteMessageDaysBox, 1, 3);
        layout.Controls.Add(CreateLabel("原因"), 0, 4);
        _memberReasonTextBox.Dock = DockStyle.Fill;
        layout.Controls.Add(_memberReasonTextBox, 1, 4);
        layout.Controls.Add(roleButtons, 1, 6);
        layout.Controls.Add(modButtons, 1, 7);
        tab.Controls.Add(layout);
        return tab;
    }

    private TabPage CreateChannelToolsTab()
    {
        var tab = new TabPage("頻道工具");
        var layout = CreateFormLayout(7);

        _newChannelNameTextBox.Dock = DockStyle.Fill;
        _clearAmountBox.Minimum = 1;
        _clearAmountBox.Maximum = 100;
        _clearAmountBox.Value = 10;
        _clearAmountBox.Dock = DockStyle.Left;
        _clearAmountBox.Width = 130;

        var renameButton = new Button { Text = "修改頻道名", Width = 130, Height = 34 };
        renameButton.Click += async (_, _) => await RenameChannelAsync();
        var clearButton = new Button { Text = "清除消息", Width = 130, Height = 34 };
        clearButton.Click += async (_, _) => await ClearMessagesAsync();

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        buttons.Controls.Add(renameButton);
        buttons.Controls.Add(clearButton);

        layout.Controls.Add(CreateLabel("新頻道名"), 0, 0);
        layout.Controls.Add(_newChannelNameTextBox, 1, 0);
        layout.Controls.Add(CreateLabel("清除數量"), 0, 1);
        layout.Controls.Add(_clearAmountBox, 1, 1);
        layout.Controls.Add(CreateLabel("原因"), 0, 2);
        _channelReasonTextBox.Dock = DockStyle.Fill;
        layout.Controls.Add(_channelReasonTextBox, 1, 2);
        layout.Controls.Add(buttons, 1, 5);
        tab.Controls.Add(layout);
        return tab;
    }

    private TabPage CreateDmTab()
    {
        var tab = new TabPage("私信通知");
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 4,
            Padding = new Padding(12)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        _dmUserIdTextBox.Dock = DockStyle.Fill;
        _dmContentTextBox.Dock = DockStyle.Fill;
        _dmContentTextBox.Multiline = true;
        _dmContentTextBox.ScrollBars = ScrollBars.Vertical;

        var sendButton = new Button { Text = "發送私信", Width = 130, Height = 34 };
        sendButton.Click += async (_, _) => await SendDmAsync();

        layout.Controls.Add(CreateLabel("使用者 ID"), 0, 0);
        layout.Controls.Add(_dmUserIdTextBox, 1, 0);
        layout.Controls.Add(CreateLabel("私信內容"), 0, 1);
        layout.Controls.Add(_dmContentTextBox, 1, 1);
        layout.Controls.Add(sendButton, 1, 3);
        tab.Controls.Add(layout);
        return tab;
    }

    private GroupBox CreateLogGroup()
    {
        var group = new GroupBox { Text = "操作紀錄", Dock = DockStyle.Fill };
        _logTextBox.Dock = DockStyle.Fill;
        _logTextBox.Multiline = true;
        _logTextBox.ReadOnly = true;
        _logTextBox.ScrollBars = ScrollBars.Vertical;
        _logTextBox.BackColor = Color.FromArgb(250, 250, 250);
        group.Controls.Add(_logTextBox);
        return group;
    }

    private static TableLayoutPanel CreateFormLayout(int rows)
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = rows,
            Padding = new Padding(12)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (var i = 0; i < rows - 1; i++)
        {
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        }
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        return layout;
    }

    private static Label CreateLabel(string text)
    {
        return new Label
        {
            Text = text,
            AutoSize = true,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft
        };
    }

    private void LoadSettingsIntoControls()
    {
        _backendUrlTextBox.Text = _settings.BackendUrl;
        _apiKeyTextBox.Text = _settings.ApiKey;
        _channelIdTextBox.Text = _settings.LastChannelId;
        _suppressMentionsCheckBox.Checked = _settings.SuppressMentions;
    }

    private void SaveSettingsFromControls()
    {
        _settings = new ClientSettings
        {
            BackendUrl = _backendUrlTextBox.Text.Trim(),
            ApiKey = _apiKeyTextBox.Text.Trim(),
            LastChannelId = _channelIdTextBox.Text.Trim(),
            SuppressMentions = _suppressMentionsCheckBox.Checked
        };

        SettingsStore.Save(_settings);
        Log($"設定已儲存到 {SettingsStore.SettingsPath}");
    }

    private async Task TestConnectionAsync()
    {
        try
        {
            using var client = CreateClient();
            SetBusy("測試連線中...");

            var health = await client.GetHealthAsync();
            if (!health.Success)
            {
                SetReady("連線失敗");
                Log("後端健康檢查失敗：" + health.Message);
                return;
            }

            Log($"後端正常，Discord Token 設定狀態：{health.Data?.DiscordTokenConfigured}");

            var identity = await client.GetBotIdentityAsync();
            if (identity.Success)
            {
                Log($"Discord Bot：{identity.Data?.Username} ({identity.Data?.Id})");
                SetReady("連線成功");
            }
            else
            {
                Log("Discord Bot 檢查失敗：" + identity.Message);
                SetReady("後端可連，但 Discord 檢查失敗");
            }
        }
        catch (Exception ex)
        {
            Log("測試連線失敗：" + ex.Message);
            SetReady("連線失敗");
        }
    }

    private async Task LoadGuildsAsync()
    {
        await RunClientActionAsync("載入伺服器中...", async client =>
        {
            var response = await client.GetGuildsAsync();
            if (!response.Success)
            {
                Log("載入伺服器失敗：" + response.Message);
                return;
            }

            _overviewTextBox.Text = string.Join(Environment.NewLine, response.Data?.Select(static guild =>
                $"{guild.Name} | {guild.Id} | Members: {guild.ApproximateMemberCount?.ToString(CultureInfo.InvariantCulture) ?? "?"}") ?? Array.Empty<string>());
            Log($"已載入 {response.Data?.Count ?? 0} 個伺服器。");
        });
    }

    private async Task LoadGuildOverviewAsync()
    {
        var guildId = _guildIdTextBox.Text.Trim();
        if (!EnsureSnowflake(guildId, "伺服器 ID"))
        {
            return;
        }

        await RunClientActionAsync("載入總覽中...", async client =>
        {
            var response = await client.GetGuildOverviewAsync(guildId);
            if (!response.Success || response.Data is null)
            {
                Log("載入總覽失敗：" + response.Message);
                return;
            }

            var data = response.Data;
            var lines = new List<string>
            {
                $"Guild: {data.Guild.Name} ({data.Guild.Id})",
                $"Members: {data.Guild.ApproximateMemberCount?.ToString(CultureInfo.InvariantCulture) ?? "?"}",
                "",
                "Channels:"
            };
            lines.AddRange(data.Channels.Select(static channel => $"  {channel.DisplayName} | {channel.Id} | Type {channel.Type}"));
            lines.Add("");
            lines.Add("Roles:");
            lines.AddRange(data.Roles.Select(static role => $"  @{role.Name} | {role.Id} | Pos {role.Position} | Color #{role.Color:X6}"));
            _overviewTextBox.Text = string.Join(Environment.NewLine, lines);
            Log("伺服器總覽已更新。");
        });
    }

    private async Task SendMessageAsync()
    {
        var request = BuildMessageRequest();
        var validationError = ValidateMessageRequest(request);
        if (validationError is not null)
        {
            ShowWarning(validationError);
            return;
        }

        SaveSettingsFromControls();
        await RunClientActionAsync("發送中...", async client =>
        {
            var response = await client.SendMessageAsync(request);
            if (response.Success)
            {
                Log($"已發送到頻道 {response.Data?.ChannelId}，消息 ID：{response.Data?.MessageId}");
                if (!string.IsNullOrWhiteSpace(response.Data?.JumpUrl))
                {
                    Log(response.Data.JumpUrl);
                }
                return;
            }

            Log("發送失敗：" + response.Message);
        });
    }

    private async Task BroadcastAsync()
    {
        var channelIds = ParseChannelIds(_broadcastChannelsTextBox.Text);
        if (channelIds.Count == 0)
        {
            ShowWarning("請輸入至少一個頻道 ID。");
            return;
        }

        var messageRequest = BuildMessageRequest();
        var validationError = ValidateMessageRequest(messageRequest, requireChannelId: false);
        if (validationError is not null)
        {
            ShowWarning(validationError);
            return;
        }

        await RunClientActionAsync("廣播中...", async client =>
        {
            var response = await client.BroadcastMessageAsync(new BroadcastMessageRequest
            {
                ChannelIds = channelIds,
                Content = messageRequest.Content,
                EmbedTitle = messageRequest.EmbedTitle,
                EmbedDescription = messageRequest.EmbedDescription,
                EmbedColor = messageRequest.EmbedColor,
                SuppressMentions = messageRequest.SuppressMentions
            });

            if (!response.Success)
            {
                Log("廣播失敗：" + response.Message);
                return;
            }

            var result = response.Data;
            Log($"廣播完成：成功 {result?.Sent.Count ?? 0}，失敗 {result?.Failed.Count ?? 0}");
            if (result is not null)
            {
                foreach (var failure in result.Failed)
                {
                    Log($"頻道 {failure.ChannelId} 失敗：{failure.Error}");
                }
            }
        });
    }

    private async Task SendDmAsync()
    {
        var userId = _dmUserIdTextBox.Text.Trim();
        if (!EnsureSnowflake(userId, "使用者 ID") || string.IsNullOrWhiteSpace(_dmContentTextBox.Text))
        {
            ShowWarning("請輸入使用者 ID 和私信內容。");
            return;
        }

        await RunClientActionAsync("發送私信中...", async client =>
        {
            var response = await client.SendDirectMessageAsync(new DirectMessageRequest
            {
                UserId = userId,
                Content = _dmContentTextBox.Text,
                SuppressMentions = true
            });
            Log(response.Success
                ? $"私信已發送，DM 頻道：{response.Data?.ChannelId}"
                : "私信失敗：" + response.Message);
        });
    }

    private async Task CreateRoleAsync()
    {
        if (!EnsureGuildId())
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(_roleNameTextBox.Text))
        {
            ShowWarning("請輸入身份組名稱。");
            return;
        }

        await RunClientActionAsync("建立身份組中...", async client =>
        {
            var response = await client.CreateRoleAsync(new RoleCreateRequest
            {
                GuildId = _guildIdTextBox.Text.Trim(),
                Name = _roleNameTextBox.Text.Trim(),
                Color = ParseColor(_roleColorTextBox.Text),
                Hoist = _roleHoistCheckBox.Checked,
                Mentionable = _roleMentionableCheckBox.Checked,
                Reason = NullIfWhiteSpace(_roleReasonTextBox.Text)
            });
            Log(response.Success
                ? $"身份組已建立：@{response.Data?.Name} ({response.Data?.Id})"
                : "建立身份組失敗：" + response.Message);
        });
    }

    private async Task DeleteRoleAsync()
    {
        if (!EnsureGuildId() || !EnsureSnowflake(_roleIdTextBox.Text.Trim(), "身份組 ID"))
        {
            return;
        }

        if (!ConfirmDanger("確定要刪除此身份組？"))
        {
            return;
        }

        await RunClientActionAsync("刪除身份組中...", async client =>
        {
            var response = await client.DeleteRoleAsync(new RoleDeleteRequest
            {
                GuildId = _guildIdTextBox.Text.Trim(),
                RoleId = _roleIdTextBox.Text.Trim(),
                Reason = NullIfWhiteSpace(_roleReasonTextBox.Text)
            });
            Log(response.Success ? "身份組已刪除。" : "刪除身份組失敗：" + response.Message);
        });
    }

    private Task AddMemberRoleAsync() => ChangeMemberRoleAsync(add: true);

    private Task RemoveMemberRoleAsync() => ChangeMemberRoleAsync(add: false);

    private async Task ChangeMemberRoleAsync(bool add)
    {
        if (!EnsureGuildId() ||
            !EnsureSnowflake(_memberUserIdTextBox.Text.Trim(), "使用者 ID") ||
            !EnsureSnowflake(_memberRoleIdTextBox.Text.Trim(), "身份組 ID"))
        {
            return;
        }

        await RunClientActionAsync(add ? "授予身份組中..." : "移除身份組中...", async client =>
        {
            var request = new MemberRoleRequest
            {
                GuildId = _guildIdTextBox.Text.Trim(),
                UserId = _memberUserIdTextBox.Text.Trim(),
                RoleId = _memberRoleIdTextBox.Text.Trim(),
                Reason = NullIfWhiteSpace(_memberReasonTextBox.Text)
            };
            var response = add
                ? await client.AddMemberRoleAsync(request)
                : await client.RemoveMemberRoleAsync(request);
            Log(response.Success ? response.Message : "身份組操作失敗：" + response.Message);
        });
    }

    private async Task TimeoutMemberAsync()
    {
        if (!EnsureMemberModerationInput())
        {
            return;
        }

        await RunClientActionAsync("禁言中...", async client =>
        {
            var response = await client.TimeoutMemberAsync(new TimeoutMemberRequest
            {
                GuildId = _guildIdTextBox.Text.Trim(),
                UserId = _memberUserIdTextBox.Text.Trim(),
                DurationMinutes = (int)_timeoutMinutesBox.Value,
                Reason = NullIfWhiteSpace(_memberReasonTextBox.Text)
            });
            Log(response.Success ? response.Message : "禁言失敗：" + response.Message);
        });
    }

    private async Task RemoveTimeoutAsync()
    {
        if (!EnsureMemberModerationInput())
        {
            return;
        }

        await RunMemberModerationAsync("解除禁言中...", client => client.RemoveTimeoutAsync(BuildMemberModerationRequest()));
    }

    private async Task KickMemberAsync()
    {
        if (!EnsureMemberModerationInput() || !ConfirmDanger("確定要踢出這個成員？"))
        {
            return;
        }

        await RunMemberModerationAsync("踢出中...", client => client.KickMemberAsync(BuildMemberModerationRequest()));
    }

    private async Task BanMemberAsync()
    {
        if (!EnsureMemberModerationInput() || !ConfirmDanger("確定要封禁這個使用者？"))
        {
            return;
        }

        await RunClientActionAsync("封禁中...", async client =>
        {
            var response = await client.BanMemberAsync(new BanMemberRequest
            {
                GuildId = _guildIdTextBox.Text.Trim(),
                UserId = _memberUserIdTextBox.Text.Trim(),
                DeleteMessageDays = (int)_deleteMessageDaysBox.Value,
                Reason = NullIfWhiteSpace(_channelReasonTextBox.Text)
            });
            Log(response.Success ? response.Message : "封禁失敗：" + response.Message);
        });
    }

    private async Task UnbanMemberAsync()
    {
        if (!EnsureMemberModerationInput())
        {
            return;
        }

        await RunMemberModerationAsync("解封中...", client => client.UnbanMemberAsync(BuildMemberModerationRequest()));
    }

    private async Task RenameChannelAsync()
    {
        if (!EnsureSnowflake(_channelIdTextBox.Text.Trim(), "頻道 ID") ||
            string.IsNullOrWhiteSpace(_newChannelNameTextBox.Text))
        {
            ShowWarning("請輸入頻道 ID 和新頻道名。");
            return;
        }

        await RunClientActionAsync("修改頻道名中...", async client =>
        {
            var response = await client.RenameChannelAsync(new ChannelRenameRequest
            {
                ChannelId = _channelIdTextBox.Text.Trim(),
                NewName = _newChannelNameTextBox.Text.Trim(),
                Reason = NullIfWhiteSpace(_channelReasonTextBox.Text)
            });
            Log(response.Success ? response.Message : "修改頻道名失敗：" + response.Message);
        });
    }

    private async Task ClearMessagesAsync()
    {
        if (!EnsureSnowflake(_channelIdTextBox.Text.Trim(), "頻道 ID") ||
            !ConfirmDanger($"確定要清除最近 {(int)_clearAmountBox.Value} 則可刪除消息？"))
        {
            return;
        }

        await RunClientActionAsync("清除消息中...", async client =>
        {
            var response = await client.ClearMessagesAsync(new ClearMessagesRequest
            {
                ChannelId = _channelIdTextBox.Text.Trim(),
                Amount = (int)_clearAmountBox.Value,
                Reason = NullIfWhiteSpace(_channelReasonTextBox.Text)
            });
            Log(response.Success
                ? $"已刪除 {response.Data?.Deleted ?? 0} 則消息。"
                : "清除消息失敗：" + response.Message);
        });
    }

    private async Task RunMemberModerationAsync(
        string busyMessage,
        Func<ControlApiClient, Task<ApiEnvelope<OperationResult>>> operation)
    {
        await RunClientActionAsync(busyMessage, async client =>
        {
            var response = await operation(client);
            Log(response.Success ? response.Message : "成員操作失敗：" + response.Message);
        });
    }

    private DiscordMessageRequest BuildMessageRequest()
    {
        return new DiscordMessageRequest
        {
            ChannelId = _channelIdTextBox.Text.Trim(),
            Content = _contentTextBox.Text,
            EmbedTitle = NullIfWhiteSpace(_embedTitleTextBox.Text),
            EmbedDescription = NullIfWhiteSpace(_embedDescriptionTextBox.Text),
            EmbedColor = ParseColor(_embedColorTextBox.Text),
            SuppressMentions = _suppressMentionsCheckBox.Checked
        };
    }

    private MemberModerationRequest BuildMemberModerationRequest()
    {
        return new MemberModerationRequest
        {
            GuildId = _guildIdTextBox.Text.Trim(),
            UserId = _memberUserIdTextBox.Text.Trim(),
            Reason = NullIfWhiteSpace(_memberReasonTextBox.Text)
        };
    }

    private async Task RunClientActionAsync(string busyMessage, Func<ControlApiClient, Task> action)
    {
        try
        {
            using var client = CreateClient();
            SetBusy(busyMessage);
            await action(client);
            SetReady("就緒");
        }
        catch (Exception ex)
        {
            Log("操作失敗：" + ex.Message);
            SetReady("操作失敗");
        }
    }

    private ControlApiClient CreateClient()
    {
        return new ControlApiClient(_backendUrlTextBox.Text.Trim(), _apiKeyTextBox.Text.Trim());
    }

    private bool EnsureGuildId()
    {
        return EnsureSnowflake(_guildIdTextBox.Text.Trim(), "伺服器 ID");
    }

    private bool EnsureMemberModerationInput()
    {
        return EnsureGuildId() && EnsureSnowflake(_memberUserIdTextBox.Text.Trim(), "使用者 ID");
    }

    private static string? ValidateMessageRequest(DiscordMessageRequest request, bool requireChannelId = true)
    {
        if (requireChannelId && string.IsNullOrWhiteSpace(request.ChannelId))
        {
            return "請輸入 Discord 頻道 ID。";
        }

        if (request.Content.Length > 2000)
        {
            return "Discord 文字內容不可超過 2000 字。";
        }

        var hasContent = !string.IsNullOrWhiteSpace(request.Content);
        var hasEmbed = !string.IsNullOrWhiteSpace(request.EmbedTitle) ||
                       !string.IsNullOrWhiteSpace(request.EmbedDescription);
        if (!hasContent && !hasEmbed)
        {
            return "請輸入文字內容或 Embed 內容。";
        }

        return null;
    }

    private static List<string> ParseChannelIds(string value)
    {
        return value
            .Split(new[] { '\r', '\n', ',', ';', ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(static item => item.Trim())
            .Where(static item => item.Length > 0)
            .Distinct(StringComparer.Ordinal)
            .ToList();
    }

    private static string? NullIfWhiteSpace(string value)
    {
        return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    }

    private static int? ParseColor(string value)
    {
        value = value.Trim();
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        if (value.StartsWith("#", StringComparison.Ordinal))
        {
            value = value[1..];
        }

        return int.TryParse(value, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var color)
            ? color
            : null;
    }

    private static bool ConfirmDanger(string message)
    {
        return MessageBox.Show(message, "確認操作", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes;
    }

    private static bool EnsureSnowflake(string value, string label)
    {
        if (!string.IsNullOrWhiteSpace(value) && ulong.TryParse(value, out _))
        {
            return true;
        }

        ShowWarning($"請輸入有效的 Discord {label}。");
        return false;
    }

    private static void ShowWarning(string message)
    {
        MessageBox.Show(message, "資料不完整", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private void SetBusy(string message)
    {
        _statusLabel.Text = message;
        UseWaitCursor = true;
    }

    private void SetReady(string message)
    {
        _statusLabel.Text = message;
        UseWaitCursor = false;
    }

    private void Log(string message)
    {
        _logTextBox.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
    }
}
