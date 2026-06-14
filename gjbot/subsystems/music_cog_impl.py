import discord
from discord.ext import commands
from discord import app_commands
import wavelink
from typing import cast, Dict, Any, Optional

# 注意：database 模块将在具体指令中导入，以避免循环导入问题

class MusicCog(commands.Cog, name="音乐播放"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        print("MusicCog (Lavalink/SoundCloud/歌单系统) 已挂载。")

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """确保指令只在服务器内使用"""
        if not interaction.guild:
            await interaction.response.send_message("此命令只能在服务器中使用。", ephemeral=True)
            return False
        return True

    def get_player(self, guild: discord.Guild) -> Optional[wavelink.Player]:
        """获取当前服务器的播放器实例"""
        if guild.voice_client and isinstance(guild.voice_client, wavelink.Player):
            return guild.voice_client
        return None

    def to_dict(self, player: wavelink.Player) -> Dict[str, Any]:
        """
        将播放器状态序列化为字典，供 Web 前端使用。
        """
        current_track = player.current
        current_data = None
        
        if current_track:
            current_data = {
                'title': current_track.title,
                'uploader': current_track.author,
                'url': current_track.uri,
                'thumbnail': current_track.artwork or "https://cdn.discordapp.com/embed/avatars/0.png",
                'duration': current_track.length / 1000 if current_track.length else 0,
            }
        
        # 获取队列列表 (仅获取前 20 首，避免 WebSocket 数据包过大)
        queue_list = [{'title': track.title, 'uploader': track.author} for track in list(player.queue)[:20]]

        # 计算循环模式字符串 (适配前端 JS 的逻辑)
        loop_mode_str = "none"
        if player.queue.mode == wavelink.QueueMode.loop:
            loop_mode_str = "song"
        elif player.queue.mode == wavelink.QueueMode.loop_all:
            loop_mode_str = "queue"

        return {
            'is_playing': player.playing,
            'is_paused': player.paused,
            'volume': player.volume,
            'loop_mode': loop_mode_str,
            'current_song': current_data,
            'queue': queue_list
        }
    
    async def broadcast_music_state(self, guild_id: int):
        """触发自定义事件，将状态推送到 Web 面板 (通过 Socket.IO)"""
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        
        player = self.get_player(guild)
        
        if not player:
            # 如果没有播放器，发送空状态重置前端
            empty_state = {
                'is_playing': False, 'is_paused': False, 'volume': 100, 
                'loop_mode': 'none', 'current_song': None, 'queue': []
            }
            self.bot.dispatch('music_state_update', guild_id, empty_state)
            return

        # 发送实时状态
        self.bot.dispatch('music_state_update', guild_id, self.to_dict(player))

    # --- 事件监听器 ---

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """当歌曲播放结束时触发"""
        player = payload.player
        if not player: return

        # 核心逻辑：自动播放下一首
        if not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)
        
        # 无论是否播放下一首，都更新 Web 状态
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        """当歌曲开始播放时触发"""
        player = payload.player
        if not player: return
        # 立即更新 Web 面板，显示当前歌曲信息
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """处理机器人被强制断开或状态改变的情况"""
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                await self.broadcast_music_state(member.guild.id)
            elif before.channel != after.channel:
                await self.broadcast_music_state(member.guild.id)

    # --- 音乐指令组 ---
    music_group = app_commands.Group(name="music", description="Lavalink 高级音乐系统")

    @music_group.command(name="play", description="播放歌曲 (默认搜索 SoundCloud)")
    @app_commands.describe(query="歌曲名称或链接")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.voice:
            await interaction.followup.send("❌ 你需要先进入一个语音频道。", ephemeral=True)
            return

        # 获取或创建播放器
        if not interaction.guild.voice_client:
            try:
                player: wavelink.Player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                await interaction.followup.send(f"❌ 无法连接语音频道: {e}", ephemeral=True)
                return
        else:
            player: wavelink.Player = self.get_player(interaction.guild)
            if not player:
                 try:
                    player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
                 except Exception as e:
                    await interaction.followup.send(f"❌ 连接错误: {e}", ephemeral=True)
                    return
            
            if player.channel.id != interaction.user.voice.channel.id:
                await interaction.followup.send(f"❌ 机器人正在另一个频道 ({player.channel.mention}) 播放。", ephemeral=True)
                return

        # --- 核心修改：使用字符串前缀而非 Enum，强制 SC 搜索 ---
        try:
            query = query.strip()
            # 如果是链接，直接搜 (支持 SC/Spotify 链接)
            if query.startswith("http"):
                tracks: wavelink.Search = await wavelink.Playable.search(query)
            else:
                # 如果是关键词，手动添加 scsearch: 前缀
                tracks: wavelink.Search = await wavelink.Playable.search(f"scsearch:{query}")
        
        except Exception as e:
            await interaction.followup.send(f"❌ 搜索出错: {e}", ephemeral=True)
            return

        if not tracks:
            await interaction.followup.send(f"❌ 未在 SoundCloud 找到关于 `{query}` 的结果。", ephemeral=True)
            return

        if isinstance(tracks, wavelink.Playlist):
            added: int = await player.queue.put_wait(tracks)
            await interaction.followup.send(f"✅ 已添加播放列表 **{tracks.name}** (共 {added} 首) 到队列。", ephemeral=True)
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)
            
            # 显示来源图标
            source_icon = "☁️" if "soundcloud" in (track.uri or "") else "🎵"
            await interaction.followup.send(f"✅ {source_icon} 已添加 **{track.title}** 到队列。", ephemeral=True)

        if not player.playing:
            if not player.queue.is_empty:
                next_track = player.queue.get()
                await player.play(next_track)
        
        await self.broadcast_music_state(interaction.guild_id)

    @music_group.command(name="skip", description="跳过当前播放的歌曲")
    async def skip(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player or not player.playing:
            await interaction.response.send_message("❌ 当前没有正在播放的歌曲。", ephemeral=True)
            return
        
        await player.skip(force=True)
        await interaction.response.send_message("⏭️ 已跳过当前歌曲。", ephemeral=True)

    @music_group.command(name="stop", description="停止播放，清空队列并断开连接")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if player:
            player.queue.clear()
            await player.skip(force=True)
            await player.disconnect()
            await interaction.response.send_message("⏹️ 已停止播放并断开连接。", ephemeral=True)
            await self.broadcast_music_state(interaction.guild_id)
        else:
            await interaction.response.send_message("❌ 机器人未连接。", ephemeral=True)

    @music_group.command(name="volume", description="设置播放音量 (0-1000)")
    @app_commands.describe(level="音量大小 (默认 100)")
    async def volume(self, interaction: discord.Interaction, level: int):
        player = self.get_player(interaction.guild)
        if not player:
            await interaction.response.send_message("❌ 机器人未连接。", ephemeral=True)
            return

        level = max(0, min(1000, level))
        await player.set_volume(level)
        await interaction.response.send_message(f"🔊 音量已设置为 {level}%", ephemeral=True)
        await self.broadcast_music_state(interaction.guild_id)

    @music_group.command(name="loop", description="设置循环模式")
    @app_commands.choices(mode=[
        app_commands.Choice(name="关闭循环 (Off)", value="off"),
        app_commands.Choice(name="单曲循环 (Song)", value="song"),
        app_commands.Choice(name="列表循环 (Queue)", value="queue")
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = self.get_player(interaction.guild)
        if not player:
            await interaction.response.send_message("❌ 机器人未连接。", ephemeral=True)
            return
        
        msg = ""
        if mode.value == "off":
            player.queue.mode = wavelink.QueueMode.normal
            msg = "循环已关闭"
        elif mode.value == "song":
            player.queue.mode = wavelink.QueueMode.loop
            msg = "已开启单曲循环"
        elif mode.value == "queue":
            player.queue.mode = wavelink.QueueMode.loop_all
            msg = "已开启列表循环"
            
        await interaction.response.send_message(f"🔁 {msg}", ephemeral=True)
        await self.broadcast_music_state(interaction.guild_id)

    @music_group.command(name="queue", description="查看当前播放队列")
    async def queue(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player or (player.queue.is_empty and not player.current):
            await interaction.response.send_message("📭 队列是空的。", ephemeral=True)
            return

        embed = discord.Embed(title="🎵 当前播放队列", color=discord.Color.purple())
        
        desc = ""
        if player.current:
            duration_s = int(player.current.length / 1000)
            desc += f"**正在播放:** [{player.current.title}]({player.current.uri}) - `{duration_s}s`\n\n"

        if not player.queue.is_empty:
            desc += "**等待播放:**\n"
            for i, track in enumerate(list(player.queue)[:10]):
                desc += f"`{i+1}.` {track.title}\n"
            
            if len(player.queue) > 10:
                desc += f"\n... 以及其他 {len(player.queue) - 10} 首"

        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    # --- 歌单系统指令组 ---
    playlist_group = app_commands.Group(name="playlist", description="管理你的个人歌单")

    @playlist_group.command(name="save_queue", description="将当前播放队列保存为歌单")
    @app_commands.describe(name="歌单名称")
    async def pl_save(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        player = self.get_player(interaction.guild)
        
        if not player or (player.queue.is_empty and not player.current):
            await interaction.followup.send("❌ 队列是空的，没有什么可保存。", ephemeral=True)
            return

        # 收集歌曲信息
        tracks_to_save = []
        if player.current:
            tracks_to_save.append({
                'uri': player.current.uri, 
                'title': player.current.title, 
                'author': player.current.author
            })
        
        for track in player.queue:
            tracks_to_save.append({
                'uri': track.uri, 
                'title': track.title, 
                'author': track.author
            })

        # 导入 database 模块
        import database
        success, msg = database.db_save_queue_to_playlist(interaction.user.id, name, tracks_to_save)
        
        await interaction.followup.send(f"{'✅' if success else '❌'} {msg}", ephemeral=True)

    @playlist_group.command(name="load", description="加载并播放歌单")
    @app_commands.describe(name="歌单名称")
    async def pl_load(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        
        if not interaction.user.voice:
            await interaction.followup.send("❌ 请先进入语音频道。", ephemeral=True)
            return

        # 获取播放器
        if not interaction.guild.voice_client:
            try:
                player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            except:
                await interaction.followup.send("❌ 无法连接语音。", ephemeral=True)
                return
        else:
            player = self.get_player(interaction.guild)

        # 从数据库读取
        import database
        track_uris = database.db_load_playlist_tracks(interaction.user.id, name)
        
        if not track_uris:
            await interaction.followup.send(f"❌ 歌单 **{name}** 不存在或为空。", ephemeral=True)
            return

        await interaction.followup.send(f"⏳ 正在加载歌单 **{name}** ({len(track_uris)} 首)... 这可能需要一点时间。", ephemeral=True)

        count = 0
        for uri in track_uris:
            try:
                # 歌单里存的都是 URI (链接)，直接加载即可
                tracks = await wavelink.Playable.search(uri)
                if tracks:
                    track = tracks[0] if isinstance(tracks, list) else tracks.tracks[0]
                    await player.queue.put_wait(track)
                    count += 1
            except:
                continue
        
        # 如果当前没播，开始播
        if not player.playing and not player.queue.is_empty:
            await player.play(player.queue.get())
            
        await interaction.followup.send(f"✅ 成功加载 **{count}** 首歌曲到队列。", ephemeral=True)
        await self.broadcast_music_state(interaction.guild_id)

    @playlist_group.command(name="list", description="查看我的所有歌单")
    async def pl_list(self, interaction: discord.Interaction):
        import database
        playlists = database.db_get_user_playlists(interaction.user.id)
        
        if not playlists:
            await interaction.response.send_message("你还没有创建任何歌单。", ephemeral=True)
            return

        embed = discord.Embed(title=f"📂 {interaction.user.display_name} 的歌单", color=discord.Color.gold())
        desc = ""
        for pl in playlists:
            desc += f"**{pl['name']}** - `{pl['track_count']} 首`\n"
        
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @playlist_group.command(name="delete", description="删除一个歌单")
    async def pl_delete(self, interaction: discord.Interaction, name: str):
        import database
        if database.db_delete_playlist(interaction.user.id, name):
            await interaction.response.send_message(f"✅ 歌单 **{name}** 已删除。", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ 未找到名为 **{name}** 的歌单。", ephemeral=True)

async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    # 删除下面这两行手动添加指令的代码，因为 add_cog 会自动处理
    # bot.tree.add_command(cog.music_group)
    # bot.tree.add_command(cog.playlist_group)
    
    await bot.add_cog(cog)