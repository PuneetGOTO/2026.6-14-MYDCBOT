import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import asyncio
import logging
import os
import urllib.parse
from typing import cast, Dict, Any, Optional

# 注意：database 模块将在具体指令中导入，以避免循环导入问题

class MusicCog(commands.Cog, name="音乐播放"):
    VOICE_LINK_WARNING = "Lavalink 已加载歌曲，但 Discord 语音链路没有建立，请让机器人重新加入频道或检查服务器语音区域/权限。"
    POSITION_STALLED_WARNING = "Lavalink 已连接语音，但播放进度没有推进，请检查 Lavalink 音源/解码日志或换一首歌测试。"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._playback_warnings: Dict[int, str] = {}
        self._last_player_updates: Dict[int, Dict[str, Any]] = {}
        self._health_tasks: Dict[int, asyncio.Task] = {}
        self._stalled_recovery_attempts: Dict[int, Dict[str, Any]] = {}

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

    def clear_playback_warning(self, guild_id: Optional[int]) -> None:
        if guild_id is not None:
            self._playback_warnings.pop(int(guild_id), None)

    def cancel_playback_health_check(self, guild_id: Optional[int]) -> None:
        if guild_id is None:
            return

        task = self._health_tasks.pop(int(guild_id), None)
        if task and not task.done():
            task.cancel()

    def schedule_playback_health_check(self, guild_id: Optional[int], reason: str) -> None:
        if guild_id is None:
            return

        guild_id = int(guild_id)
        task = self._health_tasks.get(guild_id)
        if task and not task.done():
            task.cancel()

        self._health_tasks[guild_id] = self.bot.loop.create_task(
            self._playback_health_check(guild_id, reason)
        )

    async def ensure_lavalink_connected(self) -> tuple[bool, str]:
        """Ensure Wavelink has a connected node, reconnecting if Lavalink came up late."""
        try:
            node = wavelink.Pool.get_node()
            if node.status == wavelink.NodeStatus.CONNECTED:
                return True, "Lavalink 节点已连接"
        except Exception:
            node = None

        try:
            await wavelink.Pool.reconnect()
            node = wavelink.Pool.get_node()
            if node.status == wavelink.NodeStatus.CONNECTED:
                logging.info("[Music] Reconnected existing Lavalink node.")
                return True, "Lavalink 节点已重新连接"
        except Exception:
            logging.warning("[Music] Existing Lavalink node reconnect failed.", exc_info=True)

        if wavelink.Pool.nodes:
            return False, "Lavalink 节点存在但未连接，请重启 lavalink.service 或 gjteam-bot。"

        password = os.environ.get("LAVALINK_PASSWORD")
        if not password:
            return False, "未配置 LAVALINK_PASSWORD，音乐功能无法连接 Lavalink。"

        host = os.environ.get("LAVALINK_HOST", "127.0.0.1")
        try:
            port = int(os.environ.get("LAVALINK_PORT", 2333))
        except (TypeError, ValueError):
            return False, "LAVALINK_PORT 配置无效。"

        try:
            node = wavelink.Node(uri=f"http://{host}:{port}", password=password)
            await wavelink.Pool.connect(client=self.bot, nodes=[node])
            connected = wavelink.Pool.get_node()
            if connected.status == wavelink.NodeStatus.CONNECTED:
                logging.info("[Music] Connected new Lavalink node %s:%s.", host, port)
                return True, "Lavalink 节点已连接"
        except Exception as exc:
            logging.warning("[Music] Creating Lavalink node failed: %s", exc, exc_info=True)

        return False, f"Lavalink 节点未连接，请确认 lavalink.service 正在运行且端口为 {host}:{port}。"

    async def search_tracks(self, query: str):
        ok, message = await self.ensure_lavalink_connected()
        if not ok:
            raise RuntimeError(message)

        query = query.strip()
        if query.startswith("http"):
            search_queries = [query]
            if "?" in query:
                parsed = urllib.parse.urlsplit(query)
                cleaned = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                if cleaned != query:
                    search_queries.append(cleaned)
        else:
            search_queries = [
                f"scsearch:{query}",
                f"ytsearch:{query}",
                f"ytmsearch:{query}",
            ]

        last_error = None
        tried_queries = []
        for search_query in search_queries:
            tried_queries.append(search_query.split(":", 1)[0] if ":" in search_query else "direct")
            try:
                tracks = await wavelink.Playable.search(search_query)
            except wavelink.LavalinkLoadException as exc:
                last_error = exc
                logging.warning("[Music] Lavalink failed query=%r: %s", search_query, exc)
                continue
            except Exception as exc:
                last_error = exc
                logging.warning("[Music] Search failed query=%r: %s", search_query, exc, exc_info=True)
                continue

            if tracks:
                try:
                    count = len(tracks.tracks) if isinstance(tracks, wavelink.Playlist) else len(tracks)
                except Exception:
                    count = "unknown"
                logging.warning("[Music] Search matched query=%r count=%s", search_query, count)
                return tracks

            logging.warning("[Music] Search empty query=%r", search_query)

        if last_error:
            raise RuntimeError(
                f"Lavalink 无法加载或搜索这首歌，已尝试 {', '.join(tried_queries)}；请换一个链接或关键词。"
                "如果所有关键词搜索都失败，请检查 Lavalink 是否启用 SoundCloud/YouTube 搜索源或 youtube-source 插件。"
            ) from last_error

        raise RuntimeError(
            f"未找到歌曲，已尝试 {', '.join(tried_queries)}。"
            "如果关键词搜索一直为空，请检查 Lavalink 是否启用 SoundCloud/YouTube 搜索源或 youtube-source 插件。"
        )

    async def connect_player(self, channel) -> wavelink.Player:
        """Connect a Wavelink player, replacing native Discord voice clients when needed."""
        ok, message = await self.ensure_lavalink_connected()
        if not ok:
            raise RuntimeError(message)

        guild = channel.guild
        existing_voice = guild.voice_client

        if isinstance(existing_voice, wavelink.Player):
            player = existing_voice
            player_channel = getattr(player, "channel", None)
            try:
                node_connected = player.node.status == wavelink.NodeStatus.CONNECTED
            except Exception:
                node_connected = False

            if not player.connected or not player_channel or not node_connected:
                logging.info(
                    "[Music] Recreating stale Wavelink player in guild %s.",
                    guild.id,
                )
                self.cancel_playback_health_check(guild.id)
                await player.disconnect()
                await asyncio.sleep(0.5)
                existing_voice = None
            elif player_channel.id != channel.id:
                await player.move_to(channel)
                return player
            else:
                return player

        if existing_voice:
            logging.info(
                "[Music] Replacing native voice client with Wavelink player in guild %s.",
                guild.id,
            )
            self.cancel_playback_health_check(guild.id)
            await existing_voice.disconnect(force=True)
            await asyncio.sleep(0.5)

        self.clear_playback_warning(guild.id)
        return await channel.connect(cls=wavelink.Player)

    def _empty_state(self, guild: Optional[discord.Guild] = None) -> Dict[str, Any]:
        voice_warning = None
        voice_channel = None
        if guild and guild.voice_client and not isinstance(guild.voice_client, wavelink.Player):
            channel = getattr(guild.voice_client, "channel", None)
            if channel:
                voice_channel = {"id": str(channel.id), "name": channel.name}
                voice_warning = f"机器人当前由信道控制连接在 #{channel.name}，音乐播放需要在音乐页重新加入频道。"
            else:
                voice_warning = "机器人当前不是音乐播放器连接，请在音乐页重新加入频道。"

        return {
            'is_playing': False,
            'is_paused': False,
            'connected': False,
            'node_connected': False,
            'voice_channel': voice_channel,
            'voice_warning': voice_warning,
            'voice_ping': -1,
            'position': 0,
            'volume': 100,
            'loop_mode': 'none',
            'current_song': None,
            'queue': [],
        }

    def _voice_status(self, player: wavelink.Player) -> Dict[str, Any]:
        guild = player.guild
        voice_channel = None
        voice_warning = None
        playback_warning = None

        connected = bool(getattr(player, "connected", False))
        try:
            node_connected = player.node.status == wavelink.NodeStatus.CONNECTED
        except Exception:
            node_connected = False

        bot_member = None
        voice_state = None
        if guild:
            if guild.id in self._playback_warnings:
                playback_warning = self._playback_warnings[guild.id]
            bot_user = self.bot.user
            bot_member = guild.me or (guild.get_member(bot_user.id) if bot_user else None)
            voice_state = getattr(bot_member, "voice", None) if bot_member else None

        last_update = self._last_player_updates.get(guild.id) if guild else None
        voice_ping = getattr(player, "ping", -1)
        position = getattr(player, "position", 0)
        if last_update:
            voice_ping = last_update.get("ping", voice_ping)
            position = last_update.get("position", position)

        if voice_state and voice_state.channel:
            voice_channel = {"id": str(voice_state.channel.id), "name": voice_state.channel.name}
        else:
            player_channel = getattr(player, "channel", None)
            if player_channel:
                voice_channel = {"id": str(player_channel.id), "name": player_channel.name}

        if not node_connected:
            voice_warning = "Lavalink 节点未连接，无法播放音乐。"
        elif not connected:
            voice_warning = "音乐播放器未连接语音频道。"
        elif not guild or not bot_member:
            voice_warning = "无法获取机器人在服务器中的语音状态。"
        elif not voice_state or not voice_state.channel:
            voice_warning = "机器人未连接语音频道。"
        elif getattr(voice_state, "mute", False) or getattr(voice_state, "self_mute", False):
            voice_warning = "机器人在语音频道已被静音，无法发声。"
        elif getattr(voice_state, "suppress", False):
            voice_warning = "机器人在舞台频道被禁止发言，无法发声。"
        else:
            permissions = voice_state.channel.permissions_for(bot_member)
            if not permissions.speak:
                voice_warning = f"机器人在 #{voice_state.channel.name} 没有说话权限。"
            elif playback_warning:
                voice_warning = playback_warning

        return {
            'connected': connected,
            'node_connected': node_connected,
            'voice_channel': voice_channel,
            'voice_warning': voice_warning,
            'voice_ping': voice_ping,
            'position': position,
        }

    def is_effectively_playing(self, player: wavelink.Player) -> bool:
        status = self._voice_status(player)
        return bool(
            player.current
            and player.playing
            and not player.paused
            and status['connected']
            and status['node_connected']
            and not status['voice_warning']
        )

    async def _retry_stalled_playback(
        self,
        guild_id: int,
        player: wavelink.Player,
        reason: str,
        first_position: Any,
        later_position: Any,
    ) -> bool:
        track = player.current
        if not track:
            return False

        track_key = str(
            getattr(track, "uri", None)
            or getattr(track, "identifier", None)
            or getattr(track, "title", "unknown")
        )
        now = self.bot.loop.time()
        previous_attempt = self._stalled_recovery_attempts.get(guild_id)
        if (
            previous_attempt
            and previous_attempt.get("track_key") == track_key
            and now - float(previous_attempt.get("time", 0)) < 300
        ):
            logging.warning(
                "[Music Health] stalled recovery already attempted guild=%s reason=%s track=%s first_position=%s later_position=%s",
                guild_id,
                reason,
                getattr(track, "title", "unknown"),
                first_position,
                later_position,
            )
            return False

        self._stalled_recovery_attempts[guild_id] = {"track_key": track_key, "time": now}
        current_task = asyncio.current_task()
        if self._health_tasks.get(guild_id) is current_task:
            self._health_tasks.pop(guild_id, None)

        try:
            if player.paused:
                await player.pause(False)
            await player.play(track)
        except Exception:
            logging.warning(
                "[Music Health] stalled recovery failed guild=%s reason=%s track=%s",
                guild_id,
                reason,
                getattr(track, "title", "unknown"),
                exc_info=True,
            )
            return False

        self.clear_playback_warning(guild_id)
        logging.warning(
            "[Music Health] restarted stalled track guild=%s reason=%s track=%s first_position=%s later_position=%s",
            guild_id,
            reason,
            getattr(track, "title", "unknown"),
            first_position,
            later_position,
        )
        await self.broadcast_music_state(guild_id)
        self.schedule_playback_health_check(guild_id, f"{reason}_stalled_retry")
        return True

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

        voice_status = self._voice_status(player)
        is_paused = bool(player.paused)
        is_playing = self.is_effectively_playing(player)

        return {
            'is_playing': is_playing,
            'is_paused': is_paused,
            'connected': voice_status['connected'],
            'node_connected': voice_status['node_connected'],
            'voice_channel': voice_status['voice_channel'],
            'voice_warning': voice_status['voice_warning'],
            'voice_ping': voice_status['voice_ping'],
            'position': voice_status['position'],
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
            self.bot.dispatch('music_state_update', guild_id, self._empty_state(guild))
            return

        # 发送实时状态
        self.bot.dispatch('music_state_update', guild_id, self.to_dict(player))

    # --- 事件监听器 ---

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """当歌曲播放结束时触发"""
        player = payload.player
        if not player or not player.guild: return

        # 核心逻辑：自动播放下一首
        if not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)
            self.schedule_playback_health_check(player.guild.id, "track_end_next")
        
        # 无论是否播放下一首，都更新 Web 状态
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        """当歌曲开始播放时触发"""
        player = payload.player
        if not player or not player.guild: return
        self.clear_playback_warning(player.guild.id)
        self.schedule_playback_health_check(player.guild.id, "track_start")
        # 立即更新 Web 面板，显示当前歌曲信息
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_wavelink_player_update(self, payload: wavelink.PlayerUpdateEventPayload):
        """Keep the latest Lavalink voice-link telemetry for diagnostics."""
        player = getattr(payload, "player", None)
        if not player or not player.guild:
            return

        guild_id = player.guild.id
        self._last_player_updates[guild_id] = {
            "connected": getattr(payload, "connected", None),
            "ping": getattr(payload, "ping", None),
            "position": getattr(payload, "position", None),
            "time": getattr(payload, "time", None),
        }

        if (
            getattr(payload, "connected", False)
            and getattr(payload, "ping", -1) >= 0
            and self._playback_warnings.get(guild_id) == self.VOICE_LINK_WARNING
        ):
            self.clear_playback_warning(guild_id)
            await self.broadcast_music_state(guild_id)

    async def _playback_health_check(self, guild_id: int, reason: str) -> None:
        try:
            await asyncio.sleep(5)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return

            player = self.get_player(guild)
            if not player or not player.current or player.paused:
                return

            status = self._voice_status(player)
            last_update = self._last_player_updates.get(guild_id)
            track_title = getattr(player.current, "title", "unknown")
            player_ping = getattr(player, "ping", -1)
            lavalink_info = None
            lavalink_position = None
            lavalink_connected = None
            lavalink_ping = None
            lavalink_paused = None

            try:
                lavalink_info = await player.node.fetch_player_info(guild_id)
                if lavalink_info:
                    lavalink_position = getattr(lavalink_info.state, "position", None)
                    lavalink_connected = getattr(lavalink_info.state, "connected", None)
                    lavalink_ping = getattr(lavalink_info.state, "ping", None)
                    lavalink_paused = getattr(lavalink_info, "paused", None)
            except Exception:
                logging.warning("[Music Health] failed to fetch Lavalink player info guild=%s", guild_id, exc_info=True)

            if status.get("voice_warning"):
                logging.warning(
                    "[Music Health] warning guild=%s reason=%s track=%s warning=%s player_connected=%s node_connected=%s ping=%s last_update=%s",
                    guild_id,
                    reason,
                    track_title,
                    status.get("voice_warning"),
                    status.get("connected"),
                    status.get("node_connected"),
                    player_ping,
                    last_update,
                )
                await self.broadcast_music_state(guild_id)
                return

            link_connected = bool(last_update and last_update.get("connected"))
            link_ping = last_update.get("ping") if last_update else player_ping
            if not link_connected or link_ping is None or link_ping < 0:
                self._playback_warnings[guild_id] = self.VOICE_LINK_WARNING
                logging.warning(
                    "[Music Health] voice link not ready guild=%s reason=%s track=%s player_connected=%s node_connected=%s player_ping=%s last_update=%s",
                    guild_id,
                    reason,
                    track_title,
                    status.get("connected"),
                    status.get("node_connected"),
                    player_ping,
                    last_update,
                )
                await self.broadcast_music_state(guild_id)
                return

            first_position = lavalink_position
            if first_position is None:
                first_position = last_update.get("position") if last_update else getattr(player, "position", 0)

            logging.warning(
                "[Music Health] ok guild=%s reason=%s track=%s ping=%s position=%s lavalink_connected=%s lavalink_ping=%s lavalink_paused=%s",
                guild_id,
                reason,
                track_title,
                link_ping,
                first_position,
                lavalink_connected,
                lavalink_ping,
                lavalink_paused,
            )

            if first_position is None or first_position > 1000:
                return

            await asyncio.sleep(7)
            guild = self.bot.get_guild(guild_id)
            player = self.get_player(guild) if guild else None
            if not player or not player.current or player.paused:
                return

            later_info = None
            later_position = None
            try:
                later_info = await player.node.fetch_player_info(guild_id)
                if later_info:
                    later_position = getattr(later_info.state, "position", None)
            except Exception:
                logging.warning("[Music Health] failed to fetch later Lavalink player info guild=%s", guild_id, exc_info=True)

            if later_position is None:
                later_update = self._last_player_updates.get(guild_id)
                later_position = later_update.get("position") if later_update else getattr(player, "position", 0)

            if later_position is not None and later_position <= first_position + 1000:
                if await self._retry_stalled_playback(
                    guild_id,
                    player,
                    reason,
                    first_position,
                    later_position,
                ):
                    return

                self._playback_warnings[guild_id] = self.POSITION_STALLED_WARNING
                logging.warning(
                    "[Music Health] stalled position guild=%s reason=%s track=%s first_position=%s later_position=%s current=%s",
                    guild_id,
                    reason,
                    track_title,
                    first_position,
                    later_position,
                    getattr(player.current, "title", "unknown"),
                )
                await self.broadcast_music_state(guild_id)
                return

            logging.warning(
                "[Music Health] progressing guild=%s reason=%s track=%s first_position=%s later_position=%s",
                guild_id,
                reason,
                track_title,
                first_position,
                later_position,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("[Music Health] failed guild=%s reason=%s", guild_id, reason)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        """When Lavalink reports a track failure, stop showing it as actively playing."""
        player = getattr(payload, "player", None)
        track = getattr(payload, "track", None)
        exception = getattr(payload, "exception", None)
        if not player or not player.guild:
            return

        self._playback_warnings[player.guild.id] = "当前歌曲播放失败，请跳过或重新点歌。"
        logging.error(
            "[Music] Lavalink track exception guild=%s track=%s exception=%s",
            player.guild.id,
            getattr(track, "title", "unknown"),
            exception,
        )
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        """When Lavalink reports a stuck track, surface that state to the web panel."""
        player = getattr(payload, "player", None)
        track = getattr(payload, "track", None)
        threshold = getattr(payload, "threshold", None)
        if not player or not player.guild:
            return

        self._playback_warnings[player.guild.id] = "当前歌曲播放卡住，请跳过或重新点歌。"
        logging.error(
            "[Music] Lavalink track stuck guild=%s track=%s threshold=%s",
            player.guild.id,
            getattr(track, "title", "unknown"),
            threshold,
        )
        await self.broadcast_music_state(player.guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """处理机器人被强制断开或状态改变的情况"""
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                await self.broadcast_music_state(member.guild.id)
            elif (
                before.channel != after.channel
                or getattr(before, "mute", False) != getattr(after, "mute", False)
                or getattr(before, "self_mute", False) != getattr(after, "self_mute", False)
                or getattr(before, "suppress", False) != getattr(after, "suppress", False)
            ):
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
        player = self.get_player(interaction.guild)
        target_channel = interaction.user.voice.channel
        node_connected = False
        if player:
            try:
                node_connected = player.node.status == wavelink.NodeStatus.CONNECTED
            except Exception:
                node_connected = False

        if (
            not player
            or not player.connected
            or not getattr(player, "channel", None)
            or not node_connected
        ):
            try:
                player = await self.connect_player(target_channel)
            except Exception as e:
                await interaction.followup.send(f"❌ 无法连接语音频道: {e}", ephemeral=True)
                return
        else:
            if player.channel.id != target_channel.id:
                await interaction.followup.send(f"❌ 机器人正在另一个频道 ({player.channel.mention}) 播放。", ephemeral=True)
                return

        # --- 核心修改：使用字符串前缀而非 Enum，强制 SC 搜索 ---
        try:
            query = query.strip()
            tracks: wavelink.Search = await self.search_tracks(query)
        
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

        if player.paused:
            await player.pause(False)
        if (not player.current or not self.is_effectively_playing(player)) and not player.queue.is_empty:
            next_track = player.queue.get()
            logging.warning(
                "[Music] slash_play starting track guild=%s title=%s",
                interaction.guild_id,
                getattr(next_track, "title", "unknown"),
            )
            await player.play(next_track)
            self.schedule_playback_health_check(interaction.guild_id, "slash_play")
        elif player.current:
            self.schedule_playback_health_check(interaction.guild_id, "slash_play_existing")
        
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
            self.clear_playback_warning(interaction.guild_id)
            self.cancel_playback_health_check(interaction.guild_id)
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
