# slash_role_manager_bot.py


# ===================================================================
# == 【核心修复】Eventlet 猴子补丁必须在所有网络相关库导入之前执行
# ===================================================================
import eventlet
import eventlet.wsgi # <---【核心修复】添加这一行
if not eventlet.patcher.is_monkey_patched("socket"):
    eventlet.monkey_patch()
# ===================================================================

import discord
import discord.voice_client as discord_voice_client
from discord import app_commands, ui, Interaction
from discord.ext import commands
from discord.utils import get
import os
import logging
import urllib.parse
from dotenv import load_dotenv
import time
import datetime
import asyncio
import wavelink
from typing import Optional, Union, Any, Dict, List
# (在你已有的 import 之后)
from Crypto.PublicKey import RSA
import requests
from flask_wtf.csrf import CSRFProtect
import edge_tts
from itertools import chain

from flask import send_file
import json
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("⚠️ 警告: 未安装 'aiohttp' 库...")

try:
    from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
    from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
    from alipay.aop.api.request.AlipayTradePrecreateRequest import AlipayTradePrecreateRequest
    from alipay.aop.api.util.SignatureUtils import verify_with_rsa
    ALIPAY_SDK_AVAILABLE = True
    logging.info("Successfully imported official alipay-sdk-python.")
except ImportError:
    ALIPAY_SDK_AVAILABLE = False
    logging.critical("CRITICAL: 'alipay-sdk-python' not found...")
    
import qrcode
import io
import html
import secrets
import hmac
from collections import deque
import sys
import database
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 在尝试获取环境变量之前加载 .env 文件
# load_dotenv() 会自动在当前运行目录下寻找一个叫做 .env 的文件
load_dotenv()

def ensure_discord_voice_runtime() -> tuple[bool, str]:
    """Validate the native Discord voice dependency in the running process."""

    try:
        import nacl  # noqa: F401
        import nacl.secret  # noqa: F401
    except Exception as exc:
        discord_voice_client.has_nacl = False
        return False, f"PyNaCl import failed: {type(exc).__name__}: {exc}"

    try:
        import davey  # noqa: F401
    except Exception as exc:
        return False, f"davey import failed: {type(exc).__name__}: {exc}"

    if not discord_voice_client.has_nacl:
        discord_voice_client.has_nacl = True
    return True, "PyNaCl and davey are available"

_voice_runtime_ok, _voice_runtime_message = ensure_discord_voice_runtime()
logging.warning(
    "[VOICE_RUNTIME] python=%s discord_voice_client=%s has_nacl=%s status=%s",
    sys.executable,
    getattr(discord_voice_client, "__file__", "unknown"),
    discord_voice_client.has_nacl,
    _voice_runtime_message,
)

# --- Configuration ---
# --- 支付宝配置 (最终版) ---

# 1. 从环境变量获取所有需要的配置
ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID")
ALIPAY_PRIVATE_KEY_PATH = os.environ.get("ALIPAY_PRIVATE_KEY_PATH")
ALIPAY_PUBLIC_KEY_FOR_SDK = os.environ.get("ALIPAY_PUBLIC_KEY_FOR_SDK_CONTENT")
ALIPAY_PUBLIC_KEY_FOR_VERIFY = os.environ.get("ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY")
ALIPAY_NOTIFY_URL = os.environ.get("ALIPAY_NOTIFY_URL")

# 2. 从文件路径读取私钥内容
ALIPAY_PRIVATE_KEY_STR = None
if ALIPAY_PRIVATE_KEY_PATH:
    try:
        with open(ALIPAY_PRIVATE_KEY_PATH, 'r') as f:
            ALIPAY_PRIVATE_KEY_STR = f.read()
        if not ALIPAY_PRIVATE_KEY_STR:
            logging.critical(f"Private key file at {ALIPAY_PRIVATE_KEY_PATH} is empty.")
            ALIPAY_PRIVATE_KEY_STR = None
    except FileNotFoundError:
        logging.critical(f"FATAL: Alipay private key file not found at path specified in .env: {ALIPAY_PRIVATE_KEY_PATH}")
    except Exception as e:
        logging.critical(f"FATAL: Error reading Alipay private key file: {e}")

# 3. 其他经济系统相关配置
RECHARGE_CONVERSION_RATE = int(os.environ.get("RECHARGE_CONVERSION_RATE", "100"))
ECONOMY_DEFAULT_BALANCE = int(os.environ.get("ECONOMY_DEFAULT_BALANCE", "100"))

# --- 4. 初始化支付宝客户端 (最终修正版) ---
alipay_client = None
if ALIPAY_SDK_AVAILABLE and ALIPAY_APP_ID and ALIPAY_PRIVATE_KEY_STR and ALIPAY_PUBLIC_KEY_FOR_SDK:
    try:
        # --- 使用 pycryptodome 预先加载和验证私钥格式 ---
        # 这一步能确保我们从文件读取的密钥内容是有效的
        from Crypto.PublicKey import RSA
        RSA.import_key(ALIPAY_PRIVATE_KEY_STR)
        logging.info("Private key format check passed (loadable by pycryptodome).")
        # --- 预检验结束 ---

        # 接下来，正常初始化支付宝SDK
        alipay_config = AlipayClientConfig()
        alipay_config.server_url = "https://openapi-sandbox.alipay.com/gateway.do" # 确保是沙箱
        alipay_config.app_id = ALIPAY_APP_ID
        
        # ↓↓↓ 直接使用从文件读取的原始字符串，不做任何 .encode() 或 .replace() 处理 ↓↓↓
        alipay_config.app_private_key = ALIPAY_PRIVATE_KEY_STR
        alipay_config.alipay_public_key = ALIPAY_PUBLIC_KEY_FOR_SDK
        
        alipay_client = DefaultAlipayClient(alipay_client_config=alipay_config)
        
        logging.info("Alipay client initialized successfully.")
        logging.info(f"--- Loaded Alipay Config & Initialized ---")
        logging.info(f"APP_ID: {alipay_config.app_id}")
        logging.info(f"Private Key loaded from path: {bool(alipay_config.app_private_key)}")
        logging.info(f"Notify URL: {ALIPAY_NOTIFY_URL}")
        logging.info(f"Gateway URL: {alipay_config.server_url}")
        logging.info(f"--- End of Alipay Config ---")

    except ValueError as e_key:
        logging.critical(f"FATAL: The private key content is invalid. Error: {e_key}")
        alipay_client = None
    except Exception as e_init:
        logging.critical(f"FATAL: An unexpected error occurred during Alipay client initialization: {e_init}")
        alipay_client = None
else:
    logging.critical("Alipay client could not be initialized due to missing or invalid configuration.")
    # (你已有的调试日志)
    logging.critical(f"  - SDK Available: {ALIPAY_SDK_AVAILABLE}")
    logging.critical(f"  - App ID Loaded: {bool(ALIPAY_APP_ID)}")
    logging.critical(f"  - Private Key Loaded: {bool(ALIPAY_PRIVATE_KEY_STR)}")
    logging.critical(f"  - Public Key Loaded: {bool(ALIPAY_PUBLIC_KEY_FOR_SDK)}")



# --- 充值与通知系统配置 (增加启动诊断) ---
# 【修复】确保变量名与 .env 文件中一致
RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID_STR = os.environ.get("RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID") 
RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID = None

# 【新增】在机器人启动时就进行诊断
print("--- 正在加载关键频道ID配置 ---")
if RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID_STR:
    try:
        RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID = int(RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID_STR)
        print(f"  ✅ [配置加载成功] 管理员通知频道ID: {RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID}")
    except ValueError:
        print(f"  ❌ [配置加载错误] RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID ('{RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID_STR}') 不是一个有效的数字ID。")
else:
    print(f"  ⚠️ [配置加载警告] 未在 .env 文件中找到或加载 RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID。AI上报功能将无法发送通知。")
print("---------------------------------")

# MIN_RECHARGE_AMOUNT 和 MAX_RECHARGE_AMOUNT 的配置保持不变...
MIN_RECHARGE_AMOUNT = float(os.environ.get("MIN_RECHARGE_AMOUNT", "1.0"))
MAX_RECHARGE_AMOUNT = float(os.environ.get("MAX_RECHARGE_AMOUNT", "10000.0"))
# --- 充值系统配置结束 ---


# --- 用于Web面板的Discord权限完整列表 ---
DISCORD_PERMISSIONS = {
    "一般服务器权限": {
        "view_audit_log": "查看审核日志",
        "manage_guild": "管理服务器",
        "manage_roles": "管理身份组",
        "manage_channels": "管理频道",
        "kick_members": "踢出成员",
        "ban_members": "封禁成员",
        "create_instant_invite": "创建邀请",
        "change_nickname": "更改昵称",
        "manage_nicknames": "管理昵称",
        "manage_emojis_and_stickers": "管理表情和贴纸",
        "manage_webhooks": "管理 Webhook",
        "view_channel": "查看频道"
    },
    "成员资格权限": {
        "administrator": "管理员 (启用此项将授予所有权限!)",
    },
    "文字频道权限": {
        "send_messages": "发送消息",
        "send_messages_in_threads": "在讨论串中发送消息",
        "create_public_threads": "创建公开讨论串",
        "create_private_threads": "创建私密讨论串",
        "embed_links": "嵌入链接",
        "attach_files": "附加文件",
        "add_reactions": "添加反应",
        "use_external_emojis": "使用外部表情",
        "use_external_stickers": "使用外部贴纸",
        "mention_everyone": "提及@everyone、@here和所有身份组",
        "manage_messages": "管理消息",
        "manage_threads": "管理讨论串",
        "read_message_history": "读取消息历史",
        "send_tts_messages": "发送文本转语音消息",
        "use_application_commands": "使用应用命令"
    },
    "语音频道权限": {
        "connect": "连接",
        "speak": "说话",
        "video": "视频",
        "use_voice_activation": "使用语音活动",
        "priority_speaker": "优先发言",
        "mute_members": "禁言成员",
        "deafen_members": "拒绝成员语音",
        "move_members": "移动成员",
        "use_embedded_activities": "使用活动"
    },
    "活动权限": {
        "request_to_speak": "请求发言"
    },
    "高级权限": {
        "moderate_members": "超时成员"
    }
}
# [ 结束新增代码块 1.1 ]

# !!! 重要：从环境变量加载 Bot Token !!!
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ 致命错误：未设置 DISCORD_BOT_TOKEN 环境变量。")
    print("   请在你的托管环境（例如 Railway Variables）中设置此变量。")
    exit()

# !!! 重要：从环境变量加载重启密码 !!!
RESTART_PASSWORD = os.environ.get("BOT_RESTART_PASSWORD")
if not RESTART_PASSWORD:
    print("⚠️ 警告：未设置 BOT_RESTART_PASSWORD 环境变量。/管理 restart 指令将不可用。")

# !!! 重要：从环境变量加载 DeepSeek API Key !!!
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("⚠️ 警告：未设置 DEEPSEEK_API_KEY 环境变量。DeepSeek 内容审核功能将被禁用。")

# !!! 重要：确认 DeepSeek API 端点和模型名称 !!!
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions" # <--- 确认 DeepSeek API URL!
DEEPSEEK_MODEL = "deepseek-chat" # <--- 替换为你希望使用的 DeepSeek 模型!

COMMAND_PREFIX = "!" # 旧版前缀（现在主要使用斜线指令）

# --- 新增：AI 对话功能配置与存储 ---
# 用于存储被设置为 AI DEP 频道的配置
# 结构: {channel_id: {"model": "model_id_str", "system_prompt": "optional_system_prompt_str", "history_key": "unique_history_key_for_channel"}}
ai_dep_channels_config = {} 

# 用于存储所有类型的对话历史 (包括公共 AI 频道、私聊等)
# 结构: {history_key: deque_object}
conversation_histories = {} # 注意：这个变量名可能与你之前代码中的不同，确保一致性

# 定义可用于 AI 对话的模型
AVAILABLE_AI_DIALOGUE_MODELS = {
    "deepseek-chat": "通用对话模型 (DeepSeek Chat)",
    "deepseek-coder": "代码生成模型 (DeepSeek Coder)",
    "deepseek-reasoner": "推理模型 (DeepSeek Reasoner - 支持思维链)"
}
DEFAULT_AI_DIALOGUE_MODEL = "deepseek-chat" 
MAX_AI_HISTORY_TURNS = 10 # AI 对话功能的最大历史轮数 (每轮包含用户和AI的发言)

# 用于追踪用户创建的私聊AI频道
# 结构: {channel_id: {"user_id": user_id, "model": "model_id", "history_key": "unique_key", "guild_id": guild_id, "channel_id": channel_id}}
active_private_ai_chats = {} 
# --- AI 对话功能配置与存储结束 ---

# --- 新增：服务器专属AI知识库 ---
# 结构: {guild_id: List[str]}
guild_knowledge_bases = {}
MAX_KB_ENTRIES_PER_GUILD = 50 
MAX_KB_ENTRY_LENGTH = 1000   
MAX_KB_DISPLAY_ENTRIES = 15 
# --- 服务器专属AI知识库结束 ---

# --- (在你的配置区域，可以放在 guild_knowledge_bases 附近) ---

# --- 新增：服务器独立FAQ/帮助系统 ---
# 结构: {guild_id: List[Dict[str, str]]}  每个字典包含 "keyword" 和 "answer"
# 或者更简单：{guild_id: Dict[str, str]}  其中 key 是关键词，value 是答案
# 我们先用简单的 Dict[str, str] 结构，一个关键词对应一个答案。
# 如果需要更复杂的，比如一个关键词对应多个答案片段，或带标题的条目，可以调整。
server_faqs = {}
MAX_FAQ_ENTRIES_PER_GUILD = 100 # 每个服务器FAQ的最大条目数
MAX_FAQ_KEYWORD_LENGTH = 50    # 单个FAQ关键词的最大长度
MAX_FAQ_ANSWER_LENGTH = 1500   # 单个FAQ答案的最大长度
MAX_FAQ_LIST_DISPLAY = 20      # /faq list 中显示的最大条目数
# --- 服务器独立FAQ/帮助系统结束 ---

# --- (在你现有的配置区域) ---

# --- 服务器内匿名中介私信系统 ---
# 结构: {message_id_sent_to_user_dm: {"initiator_id": int, "target_id": int, "original_channel_id": int, "guild_id": int}}
# message_id_sent_to_user_dm 是机器人发送给目标用户的初始私信的ID，用于追踪回复
ANONYMOUS_RELAY_SESSIONS = {}
# 可选：为了让发起者在频道内回复，可能需要一个更持久的会话ID
# {relay_session_id (e.g., unique_string): {"initiator_id": int, "target_id": int, "original_channel_id": int, "guild_id": int, "last_target_dm_message_id": int}}
# 为简化，我们先基于初始DM的message_id

# 允许使用此功能的身份组 (可选, 如果不设置则所有成员可用，但需谨慎)
ANONYMOUS_RELAY_ALLOWED_ROLE_IDS = [] # 例如: [1234567890] 如果需要限制
# --- 服务器内匿名中介私信系统结束 ---

# --- Intents Configuration ---
# 明确、手动地构建所有需要的 Intents，以确保可靠性。
print("正在配置 Discord Intents...")
intents = discord.Intents.default()

# 启用特权意图 (Privileged Intents)
intents.message_content = True  # 必须，用于读取消息内容 (on_message)
intents.members = True          # 【核心】必须，用于获取成员列表、on_member_join, fetch_member 等
intents.presences = True        # 推荐，因为您在门户中已开启

# 启用其他必要的非特权意图
intents.guilds = True           # 用于服务器相关事件
intents.voice_states = True     # 用于临时语音频道 (on_voice_state_update)
intents.integrations = True     # 用于集成事件
intents.webhooks = True         # 用于 webhook 事件
# messages 和 reactions 默认已在 .default() 中启用，无需重复设置。

print("Intents 配置完成：Members 和 Message Content 已明确设置为 True。")

# --- Bot Initialization ---
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)
bot.closing_tickets_in_progress = set()
bot.approved_bot_whitelist = {}
bot.persistent_views_added_in_setup = False

# ==========================================================
# == 轻量级 HTTP 服务器，用于接收支付宝回调
# ==========================================================
class AlipayCallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # 1. 获取并解析POST数据
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = dict(urllib.parse.parse_qsl(post_data.decode('utf-8')))
            logging.info(f"Received Alipay POST notify: {_redact_mapping_for_log(params)}")

            # 2. 验签
            sign = params.pop('sign', None)
            sign_type = params.pop('sign_type', None)
            if not sign or not sign_type:
                logging.warning("Alipay callback missing sign or sign_type.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'failure')
                return
            if sign_type.upper() != "RSA2":
                logging.warning(f"Unsupported Alipay sign_type: {sign_type}")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'failure')
                return
            if not ALIPAY_SDK_AVAILABLE or not ALIPAY_PUBLIC_KEY_FOR_VERIFY:
                logging.error("Alipay callback verification is not configured.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'failure')
                return
            message_to_verify = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

            is_verified = verify_with_rsa(
                message_to_verify.encode('utf-8'),
                sign.encode('utf-8'),
                ALIPAY_PUBLIC_KEY_FOR_VERIFY.encode('utf-8'),
                "RSA2"
            )

            if not is_verified:
                logging.warning("Alipay signature verification FAILED.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'failure')
                return

            # 3. 处理业务逻辑
            logging.info("Alipay signature verification SUCCEEDED.")
            callback_app_id = params.get('app_id')
            if not ALIPAY_APP_ID or callback_app_id != ALIPAY_APP_ID:
                logging.warning("Alipay app_id validation failed.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'failure')
                return
            trade_status = params.get('trade_status')
            
            if trade_status == 'TRADE_SUCCESS':
                # 在一个新的线程或使用 asyncio.run_coroutine_threadsafe 来处理，避免阻塞HTTP服务器
                asyncio.run_coroutine_threadsafe(process_successful_payment(params), bot.loop)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'success')

        except Exception as e:
            logging.error(f"Error handling Alipay callback: {e}", exc_info=True)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'failure')

def run_http_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, AlipayCallbackHandler)
    logging.info(f"Starting Alipay callback listener on port {port}...")
    httpd.serve_forever()

# ==========================================================
# == 异步处理支付成功的业务逻辑
# ==========================================================
async def process_successful_payment(params: Dict[str, Any]):
    out_trade_no = params.get('out_trade_no')
    alipay_trade_no = params.get('trade_no')
    total_amount_str = params.get('total_amount')

    # 1. 查找数据库中的原始订单
    order = database.db_get_recharge_request_by_out_trade_no(out_trade_no)
    if not order:
        logging.error(f"Order not found in DB for out_trade_no: {out_trade_no}")
        return

    # 2. 检查订单状态，防止重复处理
    if order['status'] != 'PENDING_PAYMENT':
        logging.warning(f"Order {out_trade_no} already processed. Status: {order['status']}")
        return
        
    # 3. 检查支付宝交易号是否已被使用
    if database.db_is_alipay_trade_no_processed(alipay_trade_no):
        logging.error(f"CRITICAL: Alipay trade_no {alipay_trade_no} has already been processed!")
        database.db_update_recharge_request_status(order['request_id'], 'DUPLICATE_ALIPAY_TRADE', f"Duplicate Alipay trade_no: {alipay_trade_no}")
        return

    # 4. 核对金额
    paid_amount = float(total_amount_str)
    requested_amount = float(order['requested_cny_amount'])
    if abs(paid_amount - requested_amount) > 0.01:
        logging.error(f"Amount mismatch for {out_trade_no}. Expected {requested_amount}, paid {paid_amount}")
        database.db_update_recharge_request_status(order['request_id'], 'AMOUNT_ISSUE', f"Expected {requested_amount}, paid {paid_amount}")
        return

    # 5. 给用户上分并完成订单
    user_id = int(order['user_id'])
    guild_id = int(order['guild_id'])
    amount_to_credit = int(paid_amount * RECHARGE_CONVERSION_RATE)
    
    if database.db_complete_recharge_and_credit_balance(
        order['request_id'],
        alipay_trade_no,
        paid_amount,
        guild_id,
        user_id,
        amount_to_credit,
        default_balance=ECONOMY_DEFAULT_BALANCE,
    ):
        logging.info(f"Successfully credited {amount_to_credit} units to user {user_id} for order {out_trade_no}")

        # 6. (可选) 私信通知用户
        try:
            user = await bot.fetch_user(user_id)
            await user.send(f"🎉 你的充值已成功到账！\n- 订单号: `{out_trade_no}`\n- 充值金额: {paid_amount:.2f} 元\n- 获得: {amount_to_credit} 金币")
        except Exception as e:
            logging.warning(f"Failed to send DM notification to user {user_id}: {e}")
    else:
        logging.critical(f"CRITICAL: FAILED to atomically complete recharge for user {user_id} and order {out_trade_no}.")

# 【新增】处理转接人工请求的按钮视图
class EscalateTicketView(ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=86400) # 按钮有效期 24 小时
        self.ticket_id = ticket_id

    @ui.button(label="接纳此票据", style=discord.ButtonStyle.success, custom_id="accept_escalation")
    async def accept(self, interaction: Interaction, button: ui.Button):
        # 1. 更新数据库和状态
        database.db_set_ticket_ai_managed_status(self.ticket_id, False)
        database.db_update_ticket_assignee(self.ticket_id, interaction.user.id)
        
        # 2. 通知各方
        await notify_ticket_assignment(self.ticket_id, {"username": "AI助理"}, interaction.user.id)
        
        # 3. 禁用按钮，更新消息
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=f"✅ **{interaction.user.display_name}** 已接纳此票据。", view=self)

    @ui.button(label="驳回请求", style=discord.ButtonStyle.danger, custom_id="reject_escalation")
    async def reject(self, interaction: Interaction, button: ui.Button):
        # 弹出模态框让客服填写理由
        await interaction.response.send_modal(RejectEscalationModal(self.ticket_id))

# 【新增】驳回理由的模态框
class RejectEscalationModal(ui.Modal, title="驳回转接人工请求"):
    def __init__(self, ticket_id: int):
        super().__init__()
        self.ticket_id = ticket_id

    reason = ui.TextInput(label="请输入驳回理由", placeholder="例如：您的问题可以通过知识库解决，请尝试...", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: Interaction):
        ticket_info = database.db_get_ticket_by_id(self.ticket_id)
        if not ticket_info: return

        # 1. 在票据频道内回复用户
        embed = discord.Embed(
            title="请求被驳回",
            description=f"**{interaction.user.display_name}** 驳回了您的转接请求，理由如下：\n```{self.reason.value}```\nAI 将继续为您服务。",
            color=discord.Color.orange()
        )
        channel = bot.get_channel(ticket_info['channel_id'])
        if channel: await channel.send(embed=embed)
        
        # 2. 让交互成功
        await interaction.response.send_message("已驳回请求并通知用户。", ephemeral=True)

class CloseTicketView(ui.View):
    """
    一个简单的视图，只包含一个关闭按钮。
    这个视图在票据频道创建时被实例化，并传入该票据在数据库中的ID。
    """
    def __init__(self, ticket_db_id: int):
        super().__init__(timeout=None)  # 按钮应持久存在
        self.ticket_db_id = ticket_db_id
        
        # 动态修改按钮的 custom_id，使其唯一且可追踪
        # self.children[0] 指的是视图中的第一个组件，也就是下面的 @ui.button
        # 确保这个视图里只有一个按钮
        if self.children:
            close_button = self.children[0]
            close_button.custom_id = f"close_ticket_{self.ticket_db_id}"

    @ui.button(label="关闭并归档票据", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_button(self, interaction: discord.Interaction, button: ui.Button):
        """
        这个回调函数是完全的占位符，不执行任何操作。
        所有逻辑都在 on_interaction 中处理，以避免重复响应。
        """
        pass # 或者直接留空
        # 你可以留空，或者发送一个临时的等待消息，但最好在 on_interaction 中统一处理。


# --- 新版：创建票据的视图 (包含下拉菜单) ---
class DepartmentSelect(ui.Select):
    """
    这是一个动态的下拉菜单类。它将处理完整的票据创建流程。
    """
    def __init__(self, custom_id: str):
        super().__init__(
            custom_id=custom_id,
            placeholder="➡️ 请选择一个部门来创建票据...",
            min_values=1,
            max_values=1,
            # 初始选项，提示用户点击
            options=[discord.SelectOption(label="点击这里加载部门列表...", value="load")]
        )

    # 核心逻辑：当用户与下拉菜单交互时，这个回调函数会被触发
    async def callback(self, interaction: discord.Interaction):
        # self.values[0] 包含了用户选择的选项的 value
        selected_value = self.values[0]
        guild = interaction.guild
        
        # --- 阶段一：用户第一次点击，加载部门列表 ---
        if selected_value == "load":
            # 动态从数据库获取部门列表
            departments = database.db_get_ticket_departments(guild.id)

            if not departments:
                self.placeholder = "❌ 未配置任何票据部门"
                self.options = [discord.SelectOption(label="不可用", value="disabled")]
                self.disabled = True
            else:
                self.placeholder = "➡️ 请选择一个部门来创建票据..."
                self.options = [] # 清空旧选项
                for dept in departments:
                    label = (dept.get('button_label') or dept.get('name') or f"部门 #{dept['department_id']}")[:100]
                    emoji = dept.get('button_emoji') if dept.get('button_emoji', '').strip() else None
                    description = (dept.get('description') or f"关于 {label} 的问题")[:100]
                    
                    self.options.append(discord.SelectOption(
                        label=label,
                        description=description,
                        emoji=emoji,
                        value=str(dept['department_id'])
                    ))
                self.disabled = False
            
            # 【第一次响应】用新的选项更新消息
            await interaction.response.edit_message(view=self.view)
            return

        # --- 阶段二：用户已选择一个具体部门，开始创建票据 ---
        await interaction.response.defer(ephemeral=True, thinking=True)
        user = interaction.user

        try:
            department_id = int(selected_value)
            
            # ... (这里是完整的票据创建逻辑，从 on_interaction 移到这里) ...
            departments = database.db_get_ticket_departments(guild.id)
            dept_info = next((d for d in departments if d['department_id'] == department_id), None)
            if not dept_info:
                await interaction.followup.send("❌ 错误：选择的部门不存在或已被删除。", ephemeral=True)
                return
            
            ticket_category_id = get_setting(ticket_settings, guild.id, "category_id")
            ticket_category = guild.get_channel(ticket_category_id)
            if not ticket_category or not isinstance(ticket_category, discord.CategoryChannel):
                await interaction.followup.send("❌ 票据系统配置错误：找不到有效的票据分类。请管理员运行 `/管理 票据设定`。", ephemeral=True)
                return

            staff_roles_ids = json.loads(dept_info.get('staff_role_ids_json', '[]'))
            staff_roles = [guild.get_role(rid) for rid in staff_roles_ids]
            staff_roles = [r for r in staff_roles if r]
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
            }
            for role in staff_roles:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            
            sanitized_username = "".join(c for c in user.name if c.isalnum()).lower() or "ticket"
            channel_name = f"{dept_info['name']}-{sanitized_username}"[:100]
            new_channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                topic=f"用户 {user.id} 的票据 | 部门: {dept_info['name']}"
            )

            ticket_db_id = database.db_create_ticket(guild.id, new_channel.id, user.id, department_id)
            if not ticket_db_id:
                await new_channel.delete(reason="数据库记录失败")
                await interaction.followup.send("❌ 创建票据失败：无法在数据库中记录。", ephemeral=True)
                return

            welcome_msg_data = json.loads(dept_info.get('welcome_message_json', '{}'))
            welcome_title = welcome_msg_data.get('title', f"欢迎来到 {dept_info['name']} 部门")
            welcome_desc_template = welcome_msg_data.get('description', '你好 {user}！\n\n我们的工作人员 ({staff_roles}) 会尽快为您服务。')
            welcome_desc = welcome_desc_template.format(user=user.mention, staff_roles=" ".join([r.mention for r in staff_roles]))
            
            welcome_embed = discord.Embed(title=welcome_title, description=welcome_desc, color=discord.Color.green())
            await new_channel.send(content=f"{user.mention} {' '.join([r.mention for r in staff_roles])}", embed=welcome_embed, view=CloseTicketView(ticket_db_id))

            await interaction.followup.send(f"✅ 你的票据已创建：{new_channel.mention}", ephemeral=True)
            
            if socketio:
                ticket_info = database.db_get_ticket_by_channel(new_channel.id)
                
                # 【核心修复】确保所有发送到前端的ID都是字符串
                ticket_data_for_socket = {
                    'ticket_id': str(ticket_info['ticket_id']) if ticket_info else None,
                    'channel_id': str(new_channel.id),
                    'creator_id': str(user.id),
                    'creator_name': user.display_name,
                    'creator_avatar_url': str(user.display_avatar.url),
                    'department_id': str(department_id),
                    'department_name': dept_info['name'],
                    'status': 'OPEN',
                    'claimed_by_id': None,
                    'claimed_by_name': None,
                    'created_at': new_channel.created_at.isoformat()
                }
                socketio.emit('new_ticket', ticket_data_for_socket, room=f'tickets_{guild.id}')

        except Exception as e:
            logging.error(f"创建票据时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ 创建票据时发生严重错误。", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ 创建票据时发生严重错误。", ephemeral=True)


class PersistentTicketCreationView(ui.View):
    """
    这是一个专门用于持久化的视图。它不接受任何参数，可以在启动时安全注册。
    """
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DepartmentSelect(custom_id="persistent_ticket_creator"))
# --- 新增：机器人白名单文件存储 (可选, 但推荐) ---
BOT_WHITELIST_FILE = "bot_whitelist.json" # <--- 新增这一行 (如果使用文件存储)

# --- 经济系统配置 ---
ECONOMY_ENABLED = True  # 经济系统全局开关
ECONOMY_CURRENCY_NAME = "金币"
ECONOMY_CURRENCY_SYMBOL = "💰"
ECONOMY_DEFAULT_BALANCE = 100  # 新用户首次查询时的默认余额
ECONOMY_CHAT_EARN_DEFAULT_AMOUNT = 1
ECONOMY_CHAT_EARN_DEFAULT_COOLDOWN_SECONDS = 60  # 1 分钟
ECONOMY_DATA_FILE = "economy_data.json"
SERVER_SETTINGS_FILE = "server_settings.json"
ECONOMY_MAX_SHOP_ITEMS_PER_PAGE = 5 # 减少以便更好地显示
ECONOMY_MAX_LEADERBOARD_USERS = 10
ECONOMY_TRANSFER_TAX_PERCENT = 1 # 示例: 转账收取 1% 手续费。设为 0 则无手续费。
ECONOMY_MIN_TRANSFER_AMOUNT = 10 # 最低转账金额

# --- 经济系统数据存储 (内存中，通过 JSON 持久化) ---
# {guild_id: {user_id: balance}}
user_balances: Dict[int, Dict[int, int]] = {}

# {guild_id: {item_slug: {"name": str, "price": int, "description": str, "role_id": Optional[int], "stock": int (-1 代表无限), "purchase_message": Optional[str]}}}
shop_items: Dict[int, Dict[str, Dict[str, Any]]] = {}

# {guild_id: {"chat_earn_amount": int, "chat_earn_cooldown": int}} # 存储覆盖默认值的设置
guild_economy_settings: Dict[int, Dict[str, int]] = {}

# {guild_id: {user_id: last_earn_timestamp_float}}
last_chat_earn_times: Dict[int, Dict[int, float]] = {}


# --- Spam Detection & Mod Alert Config ---
SPAM_COUNT_THRESHOLD = 5       # 用户刷屏阈值：消息数量
SPAM_TIME_WINDOW_SECONDS = 5   # 用户刷屏时间窗口（秒）
KICK_THRESHOLD = 3             # 警告多少次后踢出
BOT_SPAM_COUNT_THRESHOLD = 8   # Bot 刷屏阈值：消息数量
BOT_SPAM_TIME_WINDOW_SECONDS = 3 # Bot 刷屏时间窗口（秒）

# !!! 重要：替换成你的管理员/Mod身份组ID列表 !!!
MOD_ALERT_ROLE_IDS = [
    1362713317222912140, # <--- 替换! 示例 ID (用于通用警告)
    1362713953960198216  # <--- 替换! 示例 ID
]

# --- Public Warning Log Channel Config ---
# !!! 重要：替换成你的警告/消除警告公开通知频道ID !!!
PUBLIC_WARN_LOG_CHANNEL_ID = 1374390176591122582 # <--- 替换! 示例 ID

# !!! 重要：替换成你的启动通知频道ID !!!
STARTUP_MESSAGE_CHANNEL_ID = 1374390176591122582 # <--- 替换! 示例 ID (例如: 138000000000000000)
                                # 如果为 0 或未配置，则不发送启动消息

# --- Bad Word Detection Config & Storage (In-Memory) ---
# !!! 【警告】仔细审查并【大幅删减】此列表，避免误判 !!!
# !!! 如果你完全信任 DeepSeek API 的判断，可以清空或注释掉这个列表 !!!
BAD_WORDS = [
    "操你妈", "草泥马", "cnm", "日你妈", "rnm", "屌你老母", "屌你媽", "死妈", "死媽", "nmsl", "死全家", "死全家",
    "杂种", "雜種", "畜生", "畜牲", "狗娘养的", "狗娘養的", "贱人", "賤人", "婊子", "bitch", "傻逼", "煞笔", "sb", "脑残", "腦殘",
    "智障", "弱智", "低能", "白痴", "白癡", "废物", "廢物", "垃圾", "lj", "kys", "去死", "自杀", "自殺", "杀你", "殺你",
    "他妈的", "他媽的", "tmd", "妈的", "媽的", "卧槽", "我肏", "我操", "我草", "靠北", "靠杯", "干你娘", "干您娘",
    "fuck", "shit", "cunt", "asshole", "鸡巴", "雞巴", "jb",
]
BAD_WORDS_LOWER = [word.lower() for word in BAD_WORDS]

# 记录用户首次触发提醒 {guild_id: {user_id: {lowercase_word}}}
user_first_offense_reminders = {}

# --- 新增：Web面板权限系统 ---
# 结构: {guild_id: {"role_id_str": {"name": "权限组名称", "permissions": ["dashboard", "members", "economy", "tickets", "channel_control"]}}}
web_permissions = {}
# --- 权限系统结束 --- 

# --- General Settings Storage (In-Memory) ---
# 用于存储各种非特定功能的设置，例如日志频道、公告频道等
general_settings = {} # {guild_id: {"log_channel_id": int, "announce_channel_id": int}}

# --- Temporary Voice Channel Config & Storage (In-Memory) ---
temp_vc_settings = {}  # {guild_id: {"master_channel_id": id, "category_id": id, "member_count_channel_id": id, "member_count_template": str}}
temp_vc_owners = {}    # {channel_id: owner_user_id}
temp_vc_created = set()  # {channel_id1, channel_id2, ...}

# --- Ticket Tool Config & Storage (In-Memory) ---
# 使用 guild_id 作为键
ticket_settings = {} # {guild_id: {"setup_channel_id": int, "category_id": int, "staff_role_ids": list[int], "button_message_id": int, "ticket_count": int}}
# open_tickets = {} # {guild_id: {user_id: channel_id}} # 记录每个用户当前打开的票据

# In-memory storage for spam warnings
user_message_timestamps = {} # {user_id: [timestamp1, timestamp2]}
user_warnings = {}           # {user_id: warning_count}
bot_message_timestamps = {}  # {bot_user_id: [timestamp1, timestamp2]}

# --- AI Content Check Exemption Storage (In-Memory) ---
# !!! 注意：这些列表在机器人重启后会丢失，除非使用数据库存储 !!!
exempt_users_from_ai_check = set() # 存储用户 ID (int)
exempt_channels_from_ai_check = set() # 存储频道 ID (int)

# --- Helper Function to Get/Set Settings (Simulated DB) ---
# 注意：这只是内存中的模拟，重启会丢失数据
# 修改为接受一个字典作为存储目标
def get_setting(store: dict, guild_id: int, key: str):
    """从指定的内存字典中获取服务器设置"""
    return store.get(guild_id, {}).get(key)

def set_setting(store: dict, guild_id: int, key: str, value):
    """设置服务器设置到指定的内存字典"""
    if guild_id not in store:
        store[guild_id] = {}
    store[guild_id][key] = value
    # Less verbose logging for settings now
    # print(f"[内存设置更新 @ {id(store)}] 服务器 {guild_id}: {key}={value}")

# --- Helper Function to Send to Public Log Channel ---
async def send_to_public_log(guild: discord.Guild, embed: discord.Embed, log_type: str = "Generic"):
    """发送 Embed 消息到公共日志频道 (优先使用网页配置，其次使用环境变量)"""
    
    # 1. 优先尝试从网页配置 (general_settings) 获取
    config_channel_id = get_setting(general_settings, guild.id, "log_channel_id")
    
    # 2. 如果网页没配置，则回退到环境变量 (PUBLIC_WARN_LOG_CHANNEL_ID)
    # 注意：如果 RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID_STR 是之前的变量名，请确认你的 .env 变量名
    # 这里我们假设你有一个全局变量叫 PUBLIC_WARN_LOG_CHANNEL_ID
    target_channel_id = config_channel_id if config_channel_id else PUBLIC_WARN_LOG_CHANNEL_ID

    if not target_channel_id:
        # print(f"   ℹ️ 服务器 {guild.name} 未配置日志频道，跳过日志 ({log_type})。")
        return False

    log_channel = guild.get_channel(target_channel_id)
    if log_channel and isinstance(log_channel, discord.TextChannel):
        bot_perms = log_channel.permissions_for(guild.me)
        if bot_perms.send_messages and bot_perms.embed_links:
            try:
                await log_channel.send(embed=embed)
                print(f"   ✅ 已发送公共日志 ({log_type}) 到频道 #{log_channel.name} ({log_channel.id})。")
                return True
            except Exception as log_e:
                print(f"   ❌ 发送公共日志时发生错误 ({log_type}): {log_e}")
        else:
            print(f"   ❌ 错误：机器人在日志频道 #{log_channel.name} 缺少发送消息或嵌入链接的权限。")
    else:
         print(f"⚠️ 在服务器 {guild.name} 中找不到日志频道 ID: {target_channel_id}。")
    return False

# --- Helper Function: DeepSeek API Content Check (Returns Chinese Violation Type) ---
async def check_message_with_deepseek(message_content: str) -> Optional[str]:
    """使用 DeepSeek API 检查内容。返回中文违规类型或 None。"""
    if not DEEPSEEK_API_KEY:
        # print("DEBUG: DeepSeek API Key 未设置，跳过检查。")
        return None # Skip if no key

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    # !!! --- 重要：设计和优化你的 Prompt --- !!!
    # --- V2: 要求返回中文分类 ---
    prompt = f"""
    请分析以下 Discord 消息内容是否包含严重的违规行为。
    严重违规分类包括：仇恨言论、骚扰/欺凌、露骨的 NSFW 内容、严重威胁。
    - 如果检测到明确的严重违规，请【仅】返回对应的中文分类名称（例如：“仇恨言论”）。
    - 如果内容包含一些轻微问题（如刷屏、普通脏话）但【不构成】上述严重违规，请【仅】返回：“轻微违规”。
    - 如果内容安全，没有任何违规，请【仅】返回：“安全”。

    消息内容：“{message_content}”
    分析结果："""
    # !!! --- Prompt 结束 --- !!!

    data = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 30, # 限制返回长度，只需要分类名称
        "temperature": 0.1, # 较低的温度，追求更确定的分类
        "stream": False
    }

    loop = asyncio.get_event_loop()
    try:
        # 使用 run_in_executor 避免阻塞事件循环
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=8) # 设置超时
        )
        response.raise_for_status() # 检查 HTTP 错误
        result = response.json()
        api_response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        # print(f"DEBUG: DeepSeek 对 '{message_content[:30]}...' 的响应: {api_response_text}") # Debug log

        # --- 处理中文响应 ---
        if not api_response_text: # 空响应视为安全
             return None
        if api_response_text == "安全":
            return None
        if api_response_text == "轻微违规":
             # 对于轻微违规，我们目前也视为不需要机器人直接干预（交给刷屏或本地违禁词处理）
             return None
        # 如果不是 "安全" 或 "轻微违规"，则假定返回的是中文的严重违规类型
        # （例如 “仇恨言论”, “骚扰/欺凌” 等）
        return api_response_text

    except requests.exceptions.Timeout:
        print(f"❌ 调用 DeepSeek API 超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ 调用 DeepSeek API 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ 解析 DeepSeek API 响应失败 (非 JSON): {response.text}")
        return None
    except Exception as e:
        print(f"❌ DeepSeek 检查期间发生意外错误: {e}")
        return None


    pass

# --- 新增：通用的 DeepSeek API 请求函数 (用于AI对话功能) ---
async def get_deepseek_dialogue_response(session, api_key, model, messages_for_api, max_tokens_override=None):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    payload = {"model": model, "messages": messages_for_api}
    if model == "deepseek-reasoner":
        if max_tokens_override and isinstance(max_tokens_override, int) and max_tokens_override > 0:
            payload["max_tokens"] = max_tokens_override 
    elif max_tokens_override and isinstance(max_tokens_override, int) and max_tokens_override > 0: 
        payload["max_tokens"] = max_tokens_override

    cleaned_messages_for_api = []
    for msg in messages_for_api:
        cleaned_msg = msg.copy() 
        if "reasoning_content" in cleaned_msg:
            del cleaned_msg["reasoning_content"]
        cleaned_messages_for_api.append(cleaned_msg)
    payload["messages"] = cleaned_messages_for_api

    print(f"[AI DIALOGUE] Requesting: model='{model}', msgs_count={len(cleaned_messages_for_api)}") 
    if cleaned_messages_for_api: print(f"[AI DIALOGUE] First message for API: {cleaned_messages_for_api[0]}")

    try:
        async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=300) as response:
            raw_response_text = await response.text()
            try: response_data = json.loads(raw_response_text)
            except json.JSONDecodeError:
                print(f"[AI DIALOGUE] ERROR: Failed JSON decode. Status: {response.status}. Text: {raw_response_text[:200]}...")
                return None, None, f"无法解析响应(状态{response.status})"

            if response.status == 200:
                if response_data.get("choices") and len(response_data["choices"]) > 0:
                    message_data = response_data["choices"][0].get("message", {})
                    usage = response_data.get("usage")
                    
                    reasoning_content_api = None
                    final_content_api = message_data.get("content")

                    if model == "deepseek-reasoner":
                        reasoning_content_api = message_data.get("reasoning_content")
                        if reasoning_content_api is None: print(f"[AI DIALOGUE] DEBUG: Model '{model}' did not return 'reasoning_content'.")
                    
                    display_response = ""
                    if reasoning_content_api:
                        display_response += f"🤔 **思考过程:**\n```\n{reasoning_content_api.strip()}\n```\n\n"
                    
                    if final_content_api:
                        prefix = "💬 **最终回答:**\n" if reasoning_content_api else "" 
                        display_response += f"{prefix}{final_content_api.strip()}"
                    elif reasoning_content_api and not final_content_api: 
                        print(f"[AI DIALOGUE] WARNING: Model '{model}' returned reasoning but no final content.")
                    elif not final_content_api and not reasoning_content_api:
                        print(f"[AI DIALOGUE] ERROR: API for model '{model}' missing 'content' & 'reasoning_content'. Data: {message_data}")
                        return None, None, "API返回数据不完整(内容和思考过程均缺失)"

                    if not display_response.strip():
                        print(f"[AI DIALOGUE] ERROR: Generated 'display_response' is empty for model '{model}'.")
                        return None, None, "API生成的回复内容为空"

                    print(f"[AI DIALOGUE] INFO: Success for model '{model}'. Usage: {usage}")
                    return display_response.strip(), final_content_api, None 
                else:
                    print(f"[AI DIALOGUE] ERROR: API response missing 'choices' for model '{model}': {response_data}")
                    return None, None, f"意外响应结构：{response_data}"
            else:
                error_detail = response_data.get("error", {}).get("message", f"未知错误(状态{response.status})")
                print(f"[AI DIALOGUE] ERROR: API error (Status {response.status}) for model '{model}': {error_detail}. Resp: {raw_response_text[:200]}")
                user_error_msg = f"API调用出错(状态{response.status}): {error_detail}"
                if response.status == 400:
                    user_error_msg += "\n(提示:400通常因格式错误或在上下文中传入了`reasoning_content`)"
                return None, None, user_error_msg
    except aiohttp.ClientConnectorError as e:
        print(f"[AI DIALOGUE] ERROR: Network error: {e}")
        return None, None, "无法连接API"
    except asyncio.TimeoutError:
        print("[AI DIALOGUE] ERROR: API request timed out.")
        return None, None, "API连接超时"
    except Exception as e:
        print(f"[AI DIALOGUE] EXCEPTION: Unexpected API call error: {type(e).__name__} - {str(e)}")
        import traceback
        traceback.print_exc()
        return None, None, f"未知API错误: {str(e)}"

# --- (get_deepseek_dialogue_response 函数定义结束) ---

# --- Helper Function: Generate HTML Transcript for Tickets ---
# async def generate_ticket_transcript_html(channel: discord.TextChannel) -> Optional[str]:
# ... (接下来的函数定义)
    """使用 DeepSeek API 检查内容。返回中文违规类型或 None。"""
    if not DEEPSEEK_API_KEY:
        # print("DEBUG: DeepSeek API Key 未设置，跳过检查。")
        return None # Skip if no key

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    # !!! --- 重要：设计和优化你的 Prompt --- !!!
    # --- V2: 要求返回中文分类 ---
    prompt = f"""
    请分析以下 Discord 消息内容是否包含严重的违规行为。
    严重违规分类包括：仇恨言论、骚扰/欺凌、露骨的 NSFW 内容、严重威胁。
    - 如果检测到明确的严重违规，请【仅】返回对应的中文分类名称（例如：“仇恨言论”）。
    - 如果内容包含一些轻微问题（如刷屏、普通脏话）但【不构成】上述严重违规，请【仅】返回：“轻微违规”。
    - 如果内容安全，没有任何违规，请【仅】返回：“安全”。

    消息内容：“{message_content}”
    分析结果："""
    # !!! --- Prompt 结束 --- !!!

    data = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 30, # 限制返回长度，只需要分类名称
        "temperature": 0.1, # 较低的温度，追求更确定的分类
        "stream": False
    }

    loop = asyncio.get_event_loop()
    try:
        # 使用 run_in_executor 避免阻塞事件循环
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=8) # 设置超时
        )
        response.raise_for_status() # 检查 HTTP 错误
        result = response.json()
        api_response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        # print(f"DEBUG: DeepSeek 对 '{message_content[:30]}...' 的响应: {api_response_text}") # Debug log

        # --- 处理中文响应 ---
        if not api_response_text: # 空响应视为安全
             return None
        if api_response_text == "安全":
            return None
        if api_response_text == "轻微违规":
             # 对于轻微违规，我们目前也视为不需要机器人直接干预（交给刷屏或本地违禁词处理）
             return None
        # 如果不是 "安全" 或 "轻微违规"，则假定返回的是中文的严重违规类型
        # （例如 “仇恨言论”, “骚扰/欺凌” 等）
        return api_response_text

    except requests.exceptions.Timeout:
        print(f"❌ 调用 DeepSeek API 超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ 调用 DeepSeek API 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ 解析 DeepSeek API 响应失败 (非 JSON): {response.text}")
        return None
    except Exception as e:
        print(f"❌ DeepSeek 检查期间发生意外错误: {e}")
        return None

        # --- Helper Function: Generate HTML Transcript for Tickets ---
async def generate_ticket_transcript_html(channel: discord.TextChannel) -> Optional[str]:
    """Generates an HTML transcript for the given text channel."""
    if not isinstance(channel, discord.TextChannel):
        return None

    messages_history = []
    # Fetch all messages, oldest first.
    async for message in channel.history(limit=None, oldest_first=True):
        messages_history.append(message)

    if not messages_history:
        return f"""
        <!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>票据记录 - {html.escape(channel.name)}</title>
        <style>body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #2C2F33; color: #DCDDDE; text-align: center; }} 
        .container {{ background-color: #36393F; padding: 20px; border-radius: 8px; display: inline-block; }}</style></head>
        <body><div class="container"><h1>票据 #{html.escape(channel.name)}</h1><p>此票据中没有消息。</p></div></body></html>
        """

    message_html_blocks = []
    for msg in messages_history:
        author_name_full = html.escape(f"{msg.author.name}#{msg.author.discriminator if msg.author.discriminator != '0' else ''}")
        author_id = msg.author.id
        avatar_url = msg.author.display_avatar.url
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        content_escaped = ""
        is_system_message = msg.type != discord.MessageType.default and msg.type != discord.MessageType.reply

        if is_system_message:
            if msg.system_content:
                content_escaped = f"<em>系统消息: {html.escape(msg.system_content)}</em>"
            else:
                content_escaped = f"<em>(系统消息: {msg.type.name})</em>"
        elif msg.content:
            content_escaped = html.escape(msg.content).replace("\n", "<br>")

        attachments_html = ""
        if msg.attachments:
            links = []
            for attachment in msg.attachments:
                attachment_url = html.escape(attachment.url, quote=True)
                attachment_name = html.escape(attachment.filename, quote=True)
                links.append(f'<a href="{attachment_url}" target="_blank" rel="noopener noreferrer">[{attachment_name}]</a>')
            attachments_html = f'<div class="attachments">附件: {", ".join(links)}</div>'

        embeds_html = ""
        if msg.embeds:
            embed_parts = []
            for embed_idx, embed in enumerate(msg.embeds):
                embed_str = f'<div class="embed embed-{embed_idx+1}">'
                if embed.title:
                    embed_str += f'<div class="embed-title">{html.escape(embed.title)}</div>'
                if embed.description:
                    escaped_description = html.escape(embed.description).replace("\n", "<br>")
                    embed_str += f'<div class="embed-description">{escaped_description}</div>'
                
                fields_html = ""
                if embed.fields:
                    fields_html += '<div class="embed-fields">'
                    for field in embed.fields:
                        field_name = html.escape(field.name) if field.name else " "
                        field_value = html.escape(field.value).replace("\n", "<br>") if field.value else " "
                        inline_class = " embed-field-inline" if field.inline else ""
                        fields_html += f'<div class="embed-field{inline_class}"><strong>{field_name}</strong><br>{field_value}</div>'
                    fields_html += '</div>'
                embed_str += fields_html

                if embed.footer and embed.footer.text:
                    embed_str += f'<div class="embed-footer">{html.escape(embed.footer.text)}</div>'
                if embed.author and embed.author.name:
                    embed_str += f'<div class="embed-author">作者: {html.escape(embed.author.name)}</div>'
                if not embed.title and not embed.description and not embed.fields:
                    embed_str += '<em>(嵌入内容)</em>'
                embed_str += '</div>'
                embed_parts.append(embed_str)
            embeds_html = "".join(embed_parts)

        message_block = f"""
        <div class="message {'system-message' if is_system_message else ''}">
            <div class="message-header">
                <img src="{html.escape(str(avatar_url), quote=True)}" alt="{html.escape(msg.author.name, quote=True)}'s avatar" class="author-avatar">
                <div class="author-details">
                    <span class="author" title="User ID: {author_id}">{author_name_full}</span>
                </div>
                <span class="timestamp">{timestamp}</span>
            </div>
            <div class="content-area">
                {f'<div class="content"><p>{content_escaped}</p></div>' if content_escaped else ""}
                {attachments_html}
                {embeds_html}
            </div>
        </div>
        """
        message_html_blocks.append(message_block)

    full_html_template = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>票据记录 - {html.escape(channel.name)}</title>
        <style>
            body {{ font-family: 'Whitney', 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 0; padding: 0; background-color: #36393f; color: #dcddde; font-size: 16px; line-height: 1.6; }}
            .container {{ max-width: 90%; width: 800px; margin: 20px auto; background-color: #36393f; padding: 20px; border-radius: 8px; box-shadow: 0 0 15px rgba(0,0,0,0.5); }}
            .header {{ text-align: center; border-bottom: 1px solid #4f545c; padding-bottom: 15px; margin-bottom: 20px; }}
            .header h1 {{ color: #ffffff; margin: 0 0 5px 0; font-size: 24px; }}
            .header p {{ font-size: 12px; color: #b9bbbe; margin: 0; }}
            .message {{ display: flex; flex-direction: column; padding: 12px 0; border-top: 1px solid #40444b; }}
            .message:first-child {{ border-top: none; }}
            .message-header {{ display: flex; align-items: center; margin-bottom: 6px; }}
            .author-avatar {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 12px; background-color: #2f3136; }}
            .author-details {{ display: flex; flex-direction: column; flex-grow: 1; }}
            .author {{ font-weight: 500; color: #ffffff; font-size: 1em; }}
            .timestamp {{ font-size: 0.75em; color: #72767d; margin-left: 8px; white-space: nowrap; }}
            .content-area {{ margin-left: 52px; /* Align with author name, after avatar */ }}
            .content p {{ margin: 0 0 5px 0; white-space: pre-wrap; word-wrap: break-word; color: #dcddde; }}
            .attachments, .embed {{ margin-top: 8px; font-size: 0.9em; }}
            .attachments {{ padding: 5px; background-color: #2f3136; border-radius: 3px; }}
            .attachment a {{ color: #00aff4; text-decoration: none; margin-right: 5px; }}
            .attachment a:hover {{ text-decoration: underline; }}
            .embed {{ border-left: 4px solid #4f545c; padding: 10px; background-color: #2f3136; border-radius: 4px; margin-bottom: 5px; }}
            .embed-title {{ font-weight: bold; color: #ffffff; margin-bottom: 4px; }}
            .embed-description {{ color: #b9bbbe; font-size: 0.95em; }}
            .embed-fields {{ display: flex; flex-wrap: wrap; margin-top: 8px; }}
            .embed-field {{ padding: 5px; margin-bottom: 5px; flex-basis: 100%; }}
            .embed-field-inline {{ flex-basis: calc(50% - 10px); margin-right: 10px; }} /* Adjust for closer to Discord layout */
            .embed-field strong {{ color: #ffffff; }}
            .embed-footer, .embed-author {{ font-size: 0.8em; color: #72767d; margin-top: 5px; }}
            .system-message .content p {{ font-style: italic; color: #72767d; }}
            em {{ color: #b9bbbe; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>票据记录: #{html.escape(channel.name)}</h1>
                <p>服务器: {html.escape(channel.guild.name)} ({channel.guild.id})</p>
                <p>频道 ID: {channel.id}</p>
                <p>生成时间: {datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            </div>
            {''.join(message_html_blocks)}
        </div>
    </body>
    </html>
    """
    return full_html_template.strip()

def save_bot_whitelist_to_file():
    """将机器人白名单保存到JSON文件。"""
    try:
        # 将 set 转换为 list 以便 JSON 序列化
        data_to_save = {str(gid): list(b_set) for gid, b_set in bot.approved_bot_whitelist.items()}
        with open(BOT_WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=4)
        # print(f"[Whitelist] 机器人白名单已成功保存到 {BOT_WHITELIST_FILE}")
    except Exception as e:
        print(f"[Whitelist Error] 保存机器人白名单到文件失败: {e}")

def load_bot_whitelist_from_file():
    """从JSON文件加载机器人白名单到内存。"""
    global bot
    if not os.path.exists(BOT_WHITELIST_FILE):
        bot.approved_bot_whitelist = {}
        return
    try:
        with open(BOT_WHITELIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 将 list 转换回 set
            bot.approved_bot_whitelist = {int(gid): set(b_list) for gid, b_list in data.items()}
            print(f"[Whitelist] 已从 {BOT_WHITELIST_FILE} 加载机器人白名单。")
    except Exception as e:
        print(f"[Whitelist Error] 从文件加载机器人白名单失败: {e}")
        bot.approved_bot_whitelist = {}

# --- 经济系统：持久化 ---
def save_server_settings():
    """将非经济系统的设置（如票据、临时VC等）保存到JSON文件。"""
    data_to_save = {
        "ticket_settings": {str(k): v for k, v in ticket_settings.items()},
        "temp_vc_settings": {str(k): v for k, v in temp_vc_settings.items()},
        "ai_dep_channels_config": {str(k): v for k, v in ai_dep_channels_config.items()},
        "server_faqs": {str(k): v for k, v in server_faqs.items()},
        "guild_knowledge_bases": {str(k): v for k, v in guild_knowledge_bases.items()},
        "welcome_message_settings": {str(k): v for k, v in welcome_message_settings.items()},
        "web_permissions": {str(k): v for k, v in web_permissions.items()},
        "general_settings": {str(k): v for k, v in general_settings.items()}
    }
    try:
        with open(SERVER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Settings Error] 保存服务器设置失败: {e}")

def load_server_settings():
    """从JSON文件加载服务器设置到内存。"""
    global ticket_settings, temp_vc_settings, ai_dep_channels_config, server_faqs, guild_knowledge_bases, welcome_message_settings, web_permissions # 【新增 web_permissions】
    try:
        if os.path.exists(SERVER_SETTINGS_FILE):
            with open(SERVER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ticket_settings = {int(k): v for k, v in data.get("ticket_settings", {}).items()}
                temp_vc_settings = {int(k): v for k, v in data.get("temp_vc_settings", {}).items()}
                ai_dep_channels_config = {int(k): v for k, v in data.get("ai_dep_channels_config", {}).items()}
                server_faqs = {int(k): v for k, v in data.get("server_faqs", {}).items()}
                guild_knowledge_bases = {int(k): v for k, v in data.get("guild_knowledge_bases", {}).items()}
                welcome_message_settings = data.get("welcome_message_settings", {})
                web_permissions = {int(k): v for k, v in data.get("web_permissions", {}).items()} # 【新增】
                general_settings = {int(k): v for k, v in data.get("general_settings", {}).items()} 
                print(f"[Settings] 已成功从 {SERVER_SETTINGS_FILE} 加载服务器设置。")
    except json.JSONDecodeError:
        print(f"[Settings Error] 解析 {SERVER_SETTINGS_FILE} 失败，将使用空设置启动。")
    except Exception as e:
        print(f"[Settings Error] 加载服务器设置失败: {e}")
        
def load_economy_data():
    global user_balances, shop_items, guild_economy_settings, last_chat_earn_times
    if not ECONOMY_ENABLED:
        return
    try:
        if os.path.exists(ECONOMY_DATA_FILE):
            with open(ECONOMY_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 将字符串键转换回整数类型的 guild_id 和 user_id
                user_balances = {int(gid): {int(uid): bal for uid, bal in u_bals.items()} for gid, u_bals in data.get("user_balances", {}).items()}
                shop_items = {int(gid): items for gid, items in data.get("shop_items", {}).items()} # item_slug 保持为字符串
                guild_economy_settings = {int(gid): settings for gid, settings in data.get("guild_economy_settings", {}).items()}
                last_chat_earn_times = {int(gid): {int(uid): ts for uid, ts in u_times.items()} for gid, u_times in data.get("last_chat_earn_times", {}).items()}
                print(f"[经济系统] 成功从 {ECONOMY_DATA_FILE} 加载数据。")
    except json.JSONDecodeError:
        print(f"[经济系统错误] 解析 {ECONOMY_DATA_FILE} 的 JSON 失败。将以空数据启动。")
    except Exception as e:
        print(f"[经济系统错误] 加载经济数据失败: {e}")

def save_economy_data():
    if not ECONOMY_ENABLED:
        return
    try:
        # 准备要保存到 JSON 的数据 (确保键是字符串，如果它们是从整数转换过来的)
        data_to_save = {
            "user_balances": {str(gid): {str(uid): bal for uid, bal in u_bals.items()} for gid, u_bals in user_balances.items()},
            "shop_items": {str(gid): items for gid, items in shop_items.items()},
            "guild_economy_settings": {str(gid): settings for gid, settings in guild_economy_settings.items()},
            "last_chat_earn_times": {str(gid): {str(uid): ts for uid, ts in u_times.items()} for gid, u_times in last_chat_earn_times.items()}
        }
        with open(ECONOMY_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        # print(f"[经济系统] 成功保存数据到 {ECONOMY_DATA_FILE}") # 每次保存都打印可能过于频繁
    except Exception as e:
        print(f"[经济系统错误] 保存经济数据失败: {e}")

# --- 经济系统：辅助函数 ---
def get_user_balance(guild_id: int, user_id: int) -> int:
    return user_balances.get(guild_id, {}).get(user_id, ECONOMY_DEFAULT_BALANCE)

def update_user_balance(guild_id: int, user_id: int, amount: int, is_delta: bool = True) -> bool:
    """
    更新用户余额。
    如果 is_delta 为 True，则 amount 会被加到或从当前余额中减去。
    如果 is_delta 为 False，则 amount 成为新的余额。
    如果操作成功（例如，用 delta 更新时不会导致余额低于零），则返回 True，否则返回 False。
    """
    if guild_id not in user_balances:
        user_balances[guild_id] = {}
    
    current_balance = user_balances[guild_id].get(user_id, ECONOMY_DEFAULT_BALANCE)

    if is_delta:
        if current_balance + amount < 0:
            # 如果尝试花费超过现有金额，则操作失败
            return False 
        user_balances[guild_id][user_id] = current_balance + amount
    else: # 设置绝对余额
        if amount < 0: amount = 0 # 余额不能为负
        user_balances[guild_id][user_id] = amount
    
    # print(f"[经济系统] 用户 {user_id} 在服务器 {guild_id} 的余额已更新: {user_balances[guild_id][user_id]}")
    # save_economy_data() # 每次余额更新都保存可能过于频繁，应在特定事件后保存。
    return True

def get_guild_chat_earn_config(guild_id: int) -> Dict[str, int]:
    defaults = {
        "amount": ECONOMY_CHAT_EARN_DEFAULT_AMOUNT,
        "cooldown": ECONOMY_CHAT_EARN_DEFAULT_COOLDOWN_SECONDS
    }
    if guild_id in guild_economy_settings:
        config = guild_economy_settings[guild_id]
        return {
            "amount": config.get("chat_earn_amount", defaults["amount"]), # 确保键名匹配
            "cooldown": config.get("chat_earn_cooldown", defaults["cooldown"]) # 确保键名匹配
        }
    return defaults
# --- 辅助函数 (如果还没有，添加 get_item_slug) ---
def get_item_slug(item_name: str) -> str:
    return "_".join(item_name.lower().split()).strip() # 简单的 slug：小写，空格转下划线

# --- 定义商店购买按钮的视图 ---
class ShopItemBuyView(discord.ui.View):
    def __init__(self, items_on_page: Dict[str, Dict[str, Any]], guild_id: int):
        super().__init__(timeout=None) # 持久视图或根据需要设置超时

        for slug, item_data in items_on_page.items():
            # 为每个物品创建一个购买按钮
            # custom_id 格式: buy_<guild_id>_<item_slug>
            buy_button = discord.ui.Button(
                label=f"购买 {item_data['name']} ({ECONOMY_CURRENCY_SYMBOL}{item_data['price']})",
                style=discord.ButtonStyle.green,
                custom_id=f"shop_buy_{guild_id}_{slug}", # 确保 custom_id 唯一且可解析
                emoji="🛒" # 可选的表情符号
            )
            # 按钮的回调将在 Cog 中通过 on_interaction 监听 custom_id 来处理，
            # 或者，如果你想直接在这里定义回调（不推荐用于大量动态按钮）：
            # async def button_callback(interaction: discord.Interaction, current_slug=slug): # 使用默认参数捕获slug
            #     # 这个回调逻辑会变得复杂，因为需要访问 GuildMusicState 等
            #     # 更好的方式是在主 Cog 中监听 custom_id
            #     await interaction.response.send_message(f"你点击了购买 {current_slug}", ephemeral=True)
            # buy_button.callback = button_callback
            self.add_item(buy_button)

async def grant_item_purchase(interaction: discord.Interaction, user: discord.Member, item_data: Dict[str, Any]):
    """处理购买物品的效果。"""
    guild = interaction.guild
    
    # 如果指定，则授予身份组
    role_id = item_data.get("role_id")
    if role_id:
        role = guild.get_role(role_id)
        if role:
            if role not in user.roles:
                try:
                    await user.add_roles(role, reason=f"从商店购买了 '{item_data['name']}'")
                    # print(f"[经济系统] 身份组 '{role.name}' 已授予给用户 {user.name} (物品: '{item_data['name']}')。")
                except discord.Forbidden:
                    await interaction.followup.send(f"⚠️ 我无法为你分配 **{role.name}** 身份组，请联系管理员检查我的权限和身份组层级。", ephemeral=True)
                except Exception as e:
                    await interaction.followup.send(f"⚠️ 分配身份组时发生错误: {e}", ephemeral=True)
            # else: # 用户已拥有该身份组
                # print(f"[经济系统] 用户 {user.name} 已拥有物品 '{item_data['name']}' 的身份组。")
        else:
            await interaction.followup.send(f"⚠️ 物品 **{item_data['name']}** 关联的身份组ID `{role_id}` 无效或已被删除，请联系管理员。", ephemeral=True)
            print(f"[经济系统错误] 服务器 {guild.id} 的物品 '{item_data['name']}' 关联的身份组ID {role_id} 无效。")

    # 如果指定，则发送自定义购买消息
    purchase_message = item_data.get("purchase_message")
    if purchase_message:
        try:
            # 替换消息中的占位符
            formatted_message = purchase_message.replace("{user}", user.mention).replace("{item_name}", item_data['name'])
            await user.send(f"🎉 关于你在 **{guild.name}** 商店的购买：\n{formatted_message}")
        except discord.Forbidden:
            await interaction.followup.send(f"ℹ️ 你购买了 **{item_data['name']}**！但我无法私信你发送额外信息（可能关闭了私信）。", ephemeral=True)
        except Exception as e:
            print(f"[经济系统错误] 发送物品 '{item_data['name']}' 的购买私信给用户 {user.id} 时出错: {e}")
# --- Ticket Tool UI Views ---

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # 首先，让默认的指令树处理器处理斜杠指令和已注册的组件交互
    # await bot.process_application_commands(interaction) # discord.py v2.0+
    # 对于 discord.py 的旧版本或如果你想更明确地处理，可以保留或调整
    # 如果你的按钮回调是直接定义在 View 类中的，这部分可能不需要显式处理

    # 处理自定义的商店购买按钮
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id")
# 【【【请将以下代码块，粘贴到 on_interaction 函数的指定位置】】】

        # --- 处理票据部门选择 (创建票据) ---


        # --- 处理关闭票据按钮 ---
        if custom_id and custom_id.startswith("close_ticket_"):
            await interaction.response.defer(ephemeral=True)
            ticket_db_id = int(custom_id.split("_")[2])
            guild = interaction.guild
            user = interaction.user
            channel = interaction.channel

            if not isinstance(channel, discord.TextChannel):
                 await interaction.followup.send("❌ 操作无法在此处完成。", ephemeral=True)
                 return

            ticket_info = database.db_get_ticket_by_channel(channel.id)
            if not ticket_info or ticket_info['ticket_id'] != ticket_db_id:
                await interaction.followup.send("❌ 票据信息不匹配或已过时。", ephemeral=True)
                return

            # --- 关闭逻辑 ---
            await channel.send(f"⏳ {user.mention} 已请求关闭此票据。正在生成聊天记录并归档...")

            # 1. 生成并保存聊天记录
            transcript_content = await generate_ticket_transcript_html(channel)
            transcript_filename = f"transcript-{guild.id}-{channel.id}-{int(time.time())}.html"
            transcript_folder = "transcripts"
            os.makedirs(transcript_folder, exist_ok=True)
            transcript_path = os.path.join(transcript_folder, transcript_filename)
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(transcript_content)

            # 2. 发送给管理员日志频道 (你需要配置这个频道ID)
            admin_log_channel_id = PUBLIC_WARN_LOG_CHANNEL_ID # 使用您已有的公共日志频道ID
            admin_log_channel = guild.get_channel(admin_log_channel_id)
            if admin_log_channel:
                try:
                    await admin_log_channel.send(f"票据 `#{channel.name}` 已由 {user.mention} 关闭。聊天记录见附件。", file=discord.File(transcript_path, filename=transcript_filename))
                except Exception as e:
                    logging.warning(f"无法发送票据日志到管理员频道: {e}")

            # 3. 发送给用户
            try:
                creator = await bot.fetch_user(ticket_info['creator_id'])
                await creator.send(f"您在服务器 **{guild.name}** 创建的票据 `#{channel.name}` 已关闭。聊天记录副本见附件。", file=discord.File(transcript_path, filename=transcript_filename))
            except Exception as e:
                logging.warning(f"无法私信票据记录给用户 {ticket_info['creator_id']}: {e}")
            
            # 4. 更新数据库
            database.db_close_ticket(ticket_db_id, f"由 {user.name} 关闭", transcript_filename)
            
            # 【核心修复】先发送所有需要发送的消息

            # 4.1. 向发起交互的用户发送最终确认消息
            await interaction.followup.send("票据已成功关闭和归档。", ephemeral=True)

            # 4.2. 通过Socket.IO通知Web面板
            if socketio:
                socketio.emit('ticket_closed', {'channel_id': str(channel.id)}, room=f'tickets_{guild.id}')
            
            # 5. 最后，在所有交互和通知都完成后，再删除频道
            await asyncio.sleep(2) # 短暂延迟，确保上面的消息都发出去了
            await channel.delete(reason=f"票据关闭，操作者: {user.name}")
            
            return
# 【【【新增代码块结束】】】        
        if custom_id and custom_id.startswith("shop_buy_"):
            # 解析 custom_id: shop_buy_<guild_id>_<item_slug>
            parts = custom_id.split("_")
            if len(parts) >= 4: # shop, buy, guildid, slug (slug可能含下划线)
                try:
                    action_guild_id = int(parts[2])
                    item_slug_to_buy = "_".join(parts[3:]) # 重新组合 slug
                    
                    # 确保交互的 guild_id 与按钮中的 guild_id 一致
                    if interaction.guild_id != action_guild_id:
                        await interaction.response.send_message("❌ 按钮似乎来自其他服务器。", ephemeral=True)
                        return

                    # --- 执行购买逻辑 (与 /eco buy 非常相似) ---
                    if not ECONOMY_ENABLED:
                        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
                        return

                    # 确保先响应交互，避免超时
                    await interaction.response.defer(ephemeral=True, thinking=True) # thinking=True 显示"思考中"

                    guild_id = interaction.guild_id
                    user = interaction.user # interaction.user 就是点击按钮的用户 (discord.Member)

                    # item_to_buy_data = shop_items.get(guild_id, {}).get(item_slug_to_buy) # 内存版本
                    item_to_buy_data = database.db_get_shop_item(guild_id, item_slug_to_buy) # 数据库版本

                    if not item_to_buy_data:
                        await interaction.followup.send(f"❌ 无法找到物品 `{item_slug_to_buy}`。可能已被移除。", ephemeral=True)
                        return

                    item_price = item_to_buy_data['price']
                    # user_balance = get_user_balance(guild_id, user.id) # 内存版本
                    user_balance = database.db_get_user_balance(guild_id, user.id, ECONOMY_DEFAULT_BALANCE) # 数据库版本

                    if user_balance < item_price:
                        await interaction.followup.send(f"❌ 你的{ECONOMY_CURRENCY_NAME}不足以购买 **{item_to_buy_data['name']}** (需要 {item_price}，你有 {user_balance})。", ephemeral=True)
                        return

                    item_stock = item_to_buy_data.get("stock", -1)
                    if item_stock == 0:
                        await interaction.followup.send(f"❌ 抱歉，物品 **{item_to_buy_data['name']}** 已售罄。", ephemeral=True)
                        return
                    
                    granted_role_id = item_to_buy_data.get("role_id")
                    if granted_role_id and isinstance(user, discord.Member):
                        if discord.utils.get(user.roles, id=granted_role_id):
                            await interaction.followup.send(f"ℹ️ 你已经拥有物品 **{item_to_buy_data['name']}** 关联的身份组了。", ephemeral=True)
                            return
                    
                    # 使用数据库的事务进行购买
                    conn = database.get_db_connection()
                    purchase_successful = False
                    try:
                        conn.execute("BEGIN")
                        balance_updated = database.db_update_user_balance(guild_id, user.id, -item_price, default_balance=ECONOMY_DEFAULT_BALANCE)
                        
                        stock_updated_or_not_needed = True
                        if balance_updated and item_stock != -1:
                            new_stock = item_to_buy_data.get("stock", 0) - 1
                            if not database.db_update_shop_item_stock(guild_id, item_slug_to_buy, new_stock): # 这个函数在 database.py 中
                                 stock_updated_or_not_needed = False
                        
                        if balance_updated and stock_updated_or_not_needed:
                            conn.commit()
                            purchase_successful = True
                        else:
                            conn.rollback()
                    except Exception as db_exc:
                        if conn: conn.rollback()
                        print(f"[Shop Buy Button DB Error] {db_exc}")
                        await interaction.followup.send(f"❌ 购买时发生数据库错误。", ephemeral=True)
                        return # 退出，不继续
                    finally:
                        if conn: conn.close()

                    if purchase_successful:
                        await grant_item_purchase(interaction, user, item_to_buy_data) # 这个函数负责授予身份组和发送私信
                        await interaction.followup.send(f"🎉 恭喜！你已成功购买 **{item_to_buy_data['name']}**！", ephemeral=True)
                        print(f"[Economy][Button Buy] User {user.id} bought '{item_to_buy_data['name']}' for {item_price} in guild {guild_id}.")
                        
                        # 可选: 更新原始商店消息中的库存显示（如果适用且可行）
                        # 这比较复杂，因为需要找到原始消息并修改其 embed 或 view
                        # 简单的做法是让用户重新执行 /eco shop 查看最新库存
                    else:
                        await interaction.followup.send(f"❌ 购买失败，更新数据时发生错误。请重试。", ephemeral=True)

                except ValueError: # int(parts[2]) 转换失败
                    await interaction.response.send_message("❌ 按钮ID格式错误。",ephemeral=True)
                except Exception as e_button:
                    print(f"Error processing shop_buy button: {e_button}")
                    if not interaction.response.is_done():
                        await interaction.response.send_message("处理购买时发生未知错误。",ephemeral=True)
                    else:
                        await interaction.followup.send("处理购买时发生未知错误。",ephemeral=True)
            # 你可以在这里添加 else if 来处理其他 custom_id 的组件
        # else: # 如果不是组件交互，或者 custom_id 不匹配，则让默认的指令树处理
    # 重要：如果你的机器人也使用了 cogs，并且 cog 中有自己的 on_interaction 监听器，
    # 或者你的按钮回调是直接在 View 中定义的，你需要确保这里的 on_interaction 不会干扰它们。
    # 一种常见的做法是在 Cog 的 listener 中返回，或者在这里只处理未被其他地方处理的交互。
    # 对于简单的单文件机器人，这种方式可以工作。
    # 如果你的 discord.py 版本较高，并且正确使用了 bot.process_application_commands，
    # 那么已注册的视图回调会自动被调用，你可能只需要处理这种动态生成的、没有直接回调的按钮。
    # 为了安全，先确保 bot.process_application_commands 或类似的东西被调用。
    # 如果你的指令树可以正常处理已注册的 view 回调，那么上面的 on_interaction 只需要 shop_buy_ 部分。
    # 很多现代 discord.py 模板会为你处理这个。

    # 确保其他交互（如其他按钮、选择菜单、模态框）也能被正常处理
    # 如果你的 bot 对象有 process_application_commands，调用它
    if hasattr(bot, "process_application_commands"):
         await bot.process_application_commands(interaction)
    # 否则，你可能需要依赖 discord.py 内置的事件分发，或者自己实现更复杂的路由

# View for the button to close a ticket
# View for the button to close a ticket




# --- Event: Bot Ready ---
@bot.event
async def on_ready():
    # ===================================================================
    # == 0. 【新增】启动时诊断 Intents 是否生效
    # ===================================================================
    print("-" * 20)
    print("机器人启动诊断:")
    test_guild_id = 1280014596765126666 # 使用您的服务器ID进行测试
    test_guild = bot.get_guild(test_guild_id)
    if test_guild:
        print(f"  - 成功获取服务器: {test_guild.name}")
        print(f"  - 服务器缓存的成员数: {len(test_guild.members)} / 总数: {test_guild.member_count}")
        if len(test_guild.members) > 1:
            print("  - ✅ Server Members Intent 很可能已成功启用！")
        else:
            print("  - ⚠️ 警告：仅能看到机器人自己。Server Members Intent 可能未生效！")
    else:
        print(f"  - ❌ 错误：无法找到测试服务器ID {test_guild_id}。")
    print("-" * 20)
    # ===================================================================
    # == 1. 在 on_ready 开始时，首先获取机器人所有者ID
    # ===================================================================
    try:
        # 检查是否已获取过，避免重连时重复获取
        if not hasattr(bot, 'owner_id') or not bot.owner_id:
            app_info = await bot.application_info()
            bot.owner_id = app_info.owner.id
            print(f"✅ 已获取并设置应用所有者ID: {bot.owner_id}")
    except Exception as e:
        print(f"❌ 获取应用所有者信息失败: {e}")
        bot.owner_id = None # 如果失败，确保它被设置为None

    # ===================================================================
    # == 2. 加载需要持久化的数据
    # ===================================================================
    load_bot_whitelist_from_file() # 加载机器人白名单
    load_server_settings()
    if ECONOMY_ENABLED:
                    load_economy_data()
    

    # ===================================================================
    # == 3. 打印登录信息和调试日志
    # ===================================================================
    print("DEBUG: on_ready - Entered on_ready event") 
    logging.info("DEBUG: on_ready - Entered on_ready event (via logging)") 
    print(f'以 {bot.user.name} ({bot.user.id}) 身份登录')
    print("-" * 20)

    # ===================================================================
    # == 4. 初始化核心系统
    # ===================================================================
    print("DEBUG: on_ready - Before economy system init")
    if ECONOMY_ENABLED:
        database.initialize_database()
        print("[经济系统] 数据库已初始化，经济系统准备就绪。")

    # ===================================================================
    # == 5. 同步应用程序命令 (斜杠指令)
    # ===================================================================
    print('正在同步应用程序命令...')
    try:
        synced = await bot.tree.sync() 
        print(f'已全局同步 {len(synced) if synced else "未知数量"} 个应用程序命令。')
        if synced: 
            # 详细打印已同步的命令 (保持您的调试逻辑)
            for cmd in synced:
                print(f"  - Synced: {cmd.name} (ID: {cmd.id}) type: {type(cmd)}")
                if isinstance(cmd, app_commands.Group):
                    for sub_cmd in cmd.commands:
                        print(f"    - Sub: {sub_cmd.name} (Parent: {cmd.name})")
        else:
            print("  - 未同步任何命令，或同步返回为空。")
        logging.info(f'已全局同步 {len(synced) if synced else "未知数量"} 个应用程序命令。')
    except Exception as e_sync:
        print(f'❌ DEBUG: on_ready - 同步命令时出错: {e_sync}')
        logging.exception("Error during command sync")
    print("DEBUG: on_ready - After command sync")  

    # ===================================================================
    # == 6. 检查持久化视图注册状态 (由 setup_hook 处理)
    # ===================================================================
    if hasattr(bot, 'persistent_views_added_in_setup') and bot.persistent_views_added_in_setup:
        print("ℹ️ 持久化视图 (CreateTicketView, CloseTicketView) 已由 setup_hook 正确注册。")
    else:
        print("⚠️ 警告：持久化视图似乎未在 setup_hook 中注册。请检查 setup_hook 的执行日志和逻辑。")

    # ===================================================================
    # == 7. 初始化 aiohttp 会话
    # ===================================================================
    if AIOHTTP_AVAILABLE and not hasattr(bot, 'http_session'):
         bot.http_session = aiohttp.ClientSession()
         print("已创建 aiohttp 会话。")

    # ===================================================================
    # == 8. 宣告准备就绪并设置状态
    # ===================================================================
    print('机器人已准备就绪！')
    print('------')
    
    print("DEBUG: on_ready - Before setting presence")
    await bot.change_presence(activity=discord.Game(name="/help 显示帮助"))
    print("DEBUG: on_ready - After setting presence")

    # ===================================================================
    # == 9. 发送启动通知 (这部分代码保持不变)
    # ===================================================================
    if STARTUP_MESSAGE_CHANNEL_ID and STARTUP_MESSAGE_CHANNEL_ID != 0:
        startup_channel = None
        for guild in bot.guilds:
            channel = guild.get_channel(STARTUP_MESSAGE_CHANNEL_ID)
            if channel and isinstance(channel, discord.TextChannel):
                startup_channel = channel
                break
        
        if startup_channel:
            bot_perms = startup_channel.permissions_for(startup_channel.guild.me)
            if bot_perms.send_messages and bot_perms.embed_links:
                features_list = [
                    "深度内容审查 (DeepSeek AI)",
                    "本地违禁词检测与自动警告",
                    "用户刷屏行为监测与自动警告/踢出",
                    "机器人刷屏行为监测",
                    "临时语音频道自动管理",
                    "票据系统支持",
                    "机器人白名单与自动踢出 (未授权Bot)",
                    "所有可疑行为将被记录并通知管理员"
                ]
                features_text = "\n".join([f"- {feature}" for feature in features_list])

                embed = discord.Embed(
                    title="🚨 GJ Team 高级监控系统已激活 🚨",
                    description=(
                        f"**本服务器由 {bot.user.name} 全天候监控中。**\n\n"
                        "系统已成功启动并加载以下模块：\n"
                        f"{features_text}\n\n"
                        "**请各位用户自觉遵守服务器规定，共同维护良好环境。**\n"
                        "任何违规行为都可能导致自动警告、禁言、踢出乃至封禁处理。\n"
                        "**所有操作均有详细日志记录。**"
                    ),
                    color=discord.Color.dark_red(),
                    timestamp=discord.utils.utcnow()
                )
                if bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.display_avatar.url)
                embed.set_footer(text="请谨慎发言 | Behave yourselves!")
                try:
                    await startup_channel.send(embed=embed)
                    print(f"✅ 已成功发送启动通知到频道 #{startup_channel.name} ({startup_channel.id})")
                except discord.Forbidden:
                    print(f"❌ 发送启动通知失败：机器人缺少在频道 {STARTUP_MESSAGE_CHANNEL_ID} 发送消息或嵌入链接的权限。")
                except Exception as e:
                    print(f"❌ 发送启动通知时发生错误: {e}")
            else:
                print(f"❌ 发送启动通知失败：机器人在频道 {STARTUP_MESSAGE_CHANNEL_ID} 缺少发送消息或嵌入链接的权限。")
        else:
            print(f"⚠️ 未找到用于发送启动通知的频道 ID: {STARTUP_MESSAGE_CHANNEL_ID}。请检查配置。")
    elif STARTUP_MESSAGE_CHANNEL_ID == 0:
        print(f"ℹ️ STARTUP_MESSAGE_CHANNEL_ID 设置为0，跳过发送启动通知。")
    # --- 启动通知结束 ---
    
@bot.event
async def on_music_state_update(guild_id, state_dict):
    """
    自定义事件：当 MusicCog 状态改变时触发。
    将状态推送到对应的 Web Socket 房间。
    """
    # 检查 socketio 是否已定义且不为 None
    if 'socketio' in globals() and socketio:
        socketio.emit('music_status_update', state_dict, room=f'music_{guild_id}')


# 初始化持久化视图标志
bot.persistent_views_added = False

# 为加载 cogs 添加 setup_hook
async def setup_hook_for_bot():
    print("正在运行 setup_hook...")
    
    # --- 1. 连接 Lavalink 服务器 (新增核心逻辑) ---
    LAVALINK_HOST = os.environ.get("LAVALINK_HOST", "127.0.0.1")
    LAVALINK_PORT = int(os.environ.get("LAVALINK_PORT", 2333))
    LAVALINK_PASSWORD = os.environ.get("LAVALINK_PASSWORD")
    
    if LAVALINK_PASSWORD:
        node = wavelink.Node(
            uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}", 
            password=LAVALINK_PASSWORD
        )
        try:
            # 连接节点
            await wavelink.Pool.connect(client=bot, nodes=[node])
            print(f"✅ [Lavalink] 已成功连接到节点 {LAVALINK_HOST}:{LAVALINK_PORT}")
        except Exception as e:
            print(f"❌ [Lavalink] 连接失败: {e}")
            print("   请确保 lavalink.service 已启动，且 .env 配置正确。")
    else:
        print("⚠️ [Lavalink] 未检测到 LAVALINK_PASSWORD，音乐功能将无法使用。")

    # --- 2. 加载 Cog ---
    try:
        await bot.load_extension("music_cog")
        print("MusicCog (Lavalink版) 扩展已成功加载。")
    except commands.ExtensionAlreadyLoaded:
        print("MusicCog 扩展已被加载过。")
    except commands.ExtensionNotFound:
        print("错误：找不到 music_cog 扩展文件 (music_cog.py)。")
    except Exception as e:
        print(f"加载 music_cog 扩展失败: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()

    # --- 3. 注册持久化视图 (保留原有逻辑) ---
    if not hasattr(bot, 'persistent_views_added'):
        bot.add_view(PersistentTicketCreationView())
        bot.persistent_views_added = True
        print("持久化票据创建视图已注册。")
           
    bot.persistent_views_added_in_setup = True
    print("Setup_hook 执行完毕。")

bot.setup_hook = setup_hook_for_bot # 将钩子函数赋给 bot 实例


# --- Lavalink 事件监听器 ---

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    """
    Lavalink 事件：当歌曲播放结束时触发。
    用于处理自动播放下一首和更新 Web 状态。
    """
    player = payload.player
    if not player: return

    # MusicCog owns queue advancement; this legacy handler only mirrors state to Web.
    music_cog = bot.get_cog("音乐播放")
    if music_cog and player.guild:
        await music_cog.broadcast_music_state(player.guild.id)

@bot.event
async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload):
    """Lavalink 事件：歌曲开始播放，立即更新 Web 面板"""
    player = payload.player
    if not player: return
    
    music_cog = bot.get_cog("音乐播放")
    if music_cog:
        await music_cog.broadcast_music_state(player.guild.id)

# --- Event: Command Error Handling (Legacy Prefix Commands) ---
@bot.event
async def on_command_error(ctx, error):
    # 这个主要处理旧的 ! 前缀命令错误，现在用得少了
    if isinstance(error, commands.CommandNotFound):
        return # 忽略未找到的旧命令
    elif isinstance(error, commands.MissingPermissions):
        try:
            await ctx.send(f"🚫 你缺少使用此旧命令所需的权限: {', '.join(error.missing_permissions)}")
        except discord.Forbidden:
            pass # 无法发送消息就算了
    elif isinstance(error, commands.BotMissingPermissions):
         try:
            await ctx.send(f"🤖 我缺少执行此旧命令所需的权限: {', '.join(error.missing_permissions)}")
         except discord.Forbidden:
             pass
    else:
        print(f"处理旧命令 '{ctx.command}' 时出错: {error}")


# --- Event: App Command Error Handling (Slash Commands) ---
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    error_message = "🤔 处理指令时发生了未知错误。"
    ephemeral_response = True # 默认发送临时消息

    if isinstance(error, app_commands.CommandNotFound):
        error_message = "❓ 未知的指令。"
    elif isinstance(error, app_commands.MissingPermissions):
        missing_perms = ', '.join(f'`{p}`' for p in error.missing_permissions)
        error_message = f"🚫 你缺少执行此指令所需的权限: {missing_perms}。"
    elif isinstance(error, app_commands.BotMissingPermissions):
        missing_perms = ', '.join(f'`{p}`' for p in error.missing_permissions)
        error_message = f"🤖 我缺少执行此指令所需的权限: {missing_perms}。"
    elif isinstance(error, app_commands.CheckFailure):
        # 这个通常是自定义检查（如 is_owner()）失败，或者不满足 @checks 装饰器条件
        error_message = "🚫 你不满足使用此指令的条件或权限。"
    elif isinstance(error, app_commands.CommandOnCooldown):
         error_message = f"⏳ 指令冷却中，请在 {error.retry_after:.2f} 秒后重试。"
    elif isinstance(error, app_commands.CommandInvokeError):
        original = error.original # 获取原始错误
        print(f"指令 '{interaction.command.name if interaction.command else '未知'}' 执行失败: {type(original).__name__} - {original}") # 在后台打印详细错误
        if isinstance(original, discord.Forbidden):
            error_message = f"🚫 Discord权限错误：我无法执行此操作（通常是身份组层级问题或频道权限不足）。请检查机器人的权限和身份组位置。"
        elif isinstance(original, discord.HTTPException):
             error_message = f"🌐 网络错误：与 Discord API 通信时发生问题 (HTTP {original.status})。请稍后重试。"
        elif isinstance(original, TimeoutError): # Catch asyncio.TimeoutError
              error_message = "⏱️ 操作超时，请稍后重试。"
        else:
            error_message = f"⚙️ 执行指令时发生内部错误。请联系管理员。错误类型: {type(original).__name__}" # 对用户显示通用错误
    else:
        # 其他未预料到的 AppCommandError
        print(f'未处理的应用指令错误类型: {type(error).__name__} - {error}')
        error_message = f"🔧 处理指令时发生意外错误: {type(error).__name__}"

    try:
        # 尝试发送错误信息
        if interaction.response.is_done():
            await interaction.followup.send(error_message, ephemeral=ephemeral_response)
        else:
            await interaction.response.send_message(error_message, ephemeral=ephemeral_response)
    except discord.NotFound:
        # If the interaction is gone (e.g., user dismissed), just log
        print(f"无法发送错误消息，交互已失效: {error_message}")
    except Exception as e:
        # 如果连发送错误消息都失败了，就在后台打印
        print(f"发送错误消息时也发生错误: {e}")

# 将错误处理函数绑定到 bot 的指令树
bot.tree.on_error = on_app_command_error

# --- Event: Member Join - Assign Separator Roles & Welcome ---
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    print(f'[+] 成员加入: {member.name} ({member.id}) 加入了服务器 {guild.name} ({guild.id})')

    # --- 自动分配分隔线身份组 ---
    separator_role_names_to_assign = [
        "▽─────————─────身份─────————─────",
        "▽─────————─────通知─────————─────",
        "▽─────————─────其他─────————─────"
    ]
    
    roles_to_add = []
    for role_name in separator_role_names_to_assign:
        role = get(guild.roles, name=role_name)
        if role:
            if role < guild.me.top_role or guild.me == guild.owner:
                roles_to_add.append(role)
    
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason="新成员自动分配分隔线身份组")
            print(f"   ✅ 已为 {member.name} 分配分隔线身份组。")
        except discord.Forbidden:
            print(f"   ❌ 为 {member.name} 分配分隔线身份组失败：机器人缺少 '管理身份组' 权限。")
        except Exception as e:
            print(f"   ❌ 为 {member.name} 分配分隔线身份组时发生未知错误: {e}")

    # --- 【核心修改】使用来自Web面板配置的欢迎消息 ---
    welcome_config = welcome_message_settings.get(str(guild.id))
    
    # 检查是否有有效的欢迎频道ID配置
    if not welcome_config or not welcome_config.get('channel_id'):
        print(f"   ℹ️ 服务器 {guild.name} 未配置有效的欢迎频道，跳过发送欢迎消息。")
    else:
        welcome_channel = guild.get_channel(welcome_config['channel_id'])
        if welcome_channel and isinstance(welcome_channel, discord.TextChannel):
            if not welcome_channel.permissions_for(guild.me).send_messages or not welcome_channel.permissions_for(guild.me).embed_links:
                print(f"   ❌ 发送欢迎消息失败：机器人缺少在 #{welcome_channel.name} 发送消息或嵌入链接的权限。")
            else:
                try:
                    # 获取所有配置，如果不存在则使用 None 或默认值
                    title_template = welcome_config.get('title') or "🎉 欢迎来到 {guild}! 🎉"
                    desc_template = welcome_config.get('description') or "你好 {user}! 很高兴你能加入我们！"
                    
                    rules_id = welcome_config.get('rules_channel_id')
                    roles_info_id = welcome_config.get('roles_info_channel_id')
                    verification_id = welcome_config.get('verification_channel_id')
                    
                    # 动态处理认证链接
                    ticket_setup_id = get_setting(ticket_settings, guild.id, "setup_channel_id")
                    verification_link_text = f"<#{verification_id}>" if verification_id else ""
                    if ticket_setup_id:
                        verification_link_text = f"<#{ticket_setup_id}> (点击按钮开票)"

                    # 替换所有占位符
                    final_title = title_template.replace('{guild}', guild.name).replace('{user}', member.display_name)
                    final_description = desc_template.replace('{user}', member.mention).replace('{guild}', guild.name)
                    # 安全地替换频道ID，如果ID不存在则不替换
                    final_description = final_description.replace('<#{rules_channel_id}>', f'<#{rules_id}>') if rules_id else final_description.replace('<#{rules_channel_id}>', '')
                    final_description = final_description.replace('<#{roles_info_channel_id}>', f'<#{roles_info_id}>') if roles_info_id else final_description.replace('<#{roles_info_channel_id}>', '')
                    final_description = final_description.replace('{verification_link}', verification_link_text)
                    
                    embed = discord.Embed(
                        title=final_title,
                        description=final_description,
                        color=discord.Color.blue()
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"你是服务器的第 {guild.member_count} 位成员！")
                    embed.timestamp = discord.utils.utcnow()

                    await welcome_channel.send(embed=embed)
                    print(f"   ✅ 已在频道 #{welcome_channel.name} 发送对 {member.name} 的自定义欢迎消息。")
                except Exception as e:
                    print(f"   ❌ 发送自定义欢迎消息时发生错误: {e}", exc_info=True)
        else:
            print(f"⚠️ 在服务器 {guild.name} 中找不到配置的欢迎频道 ID: {welcome_config['channel_id']}。")


# --- Event: On Message - Handles Content Check, Spam ---

    # --- 新增/替换：严格的机器人加入控制 ---
    if member.bot and member.id != bot.user.id: # 如果加入的是机器人 (且不是自己的机器人)
        guild_whitelist = bot.approved_bot_whitelist.get(guild.id, set())

        if member.id not in guild_whitelist:
            print(f"[Bot Control] 未经批准的机器人 {member.name} ({member.id}) 尝试加入服务器 {guild.name}。正在踢出...")
            kick_reason = "未经授权的机器人自动踢出。请联系服务器所有者将其ID加入白名单后重试。"
            try:
                if guild.me.guild_permissions.kick_members:
                    if guild.owner:
                        try:
                            owner_embed = discord.Embed(
                                title="🚫 未授权机器人被自动踢出",
                                description=(
                                    f"机器人 **{member.name}** (`{member.id}`) 尝试加入服务器 **{guild.name}** 但未在白名单中，已被自动踢出。\n\n"
                                    f"如果这是一个你信任的机器人，请使用以下指令将其ID添加到白名单：\n"
                                    f"`/管理 bot_whitelist add {member.id}`"
                                ),
                                color=discord.Color.red(),
                                timestamp=discord.utils.utcnow()
                            )
                            await guild.owner.send(embed=owner_embed)
                            print(f"  - 已通知服务器所有者 ({guild.owner.name}) 关于机器人 {member.name} 的自动踢出。")
                        except discord.Forbidden:
                            print(f"  - 无法私信通知服务器所有者 ({guild.owner.name})：TA可能关闭了私信或屏蔽了机器人。")
                        except Exception as dm_e:
                            print(f"  - 私信通知服务器所有者时发生错误: {dm_e}")

                    await member.kick(reason=kick_reason)
                    print(f"  - ✅ 成功踢出机器人 {member.name} ({member.id})。")

                    log_embed = discord.Embed(title="🤖 未授权机器人被踢出", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
                    log_embed.add_field(name="机器人", value=f"{member.mention} (`{member.id}`)", inline=False)
                    log_embed.add_field(name="服务器", value=guild.name, inline=False)
                    log_embed.add_field(name="操作", value="自动踢出 (不在白名单)", inline=False)
                    await send_to_public_log(guild, log_embed, "Unauthorized Bot Kicked")
                else:
                    print(f"  - ❌ 无法踢出机器人 {member.name}：机器人缺少 '踢出成员' 权限。")
                    if guild.owner:
                        try: await guild.owner.send(f"⚠️ 警告：机器人 **{member.name}** (`{member.id}`) 尝试加入服务器 **{guild.name}** 但我缺少踢出它的权限！请手动处理或授予我 '踢出成员' 权限。")
                        except: pass
            except discord.Forbidden:
                print(f"  - ❌ 无法踢出机器人 {member.name}：权限不足 (可能是层级问题)。")
            except Exception as e:
                print(f"  - ❌ 踢出机器人 {member.name} 时发生未知错误: {e}")
        else:
            print(f"[Bot Control] 已批准的机器人 {member.name} ({member.id}) 加入了服务器 {guild.name}。")
            if guild.owner:
                try:
                    await guild.owner.send(f"ℹ️ 白名单中的机器人 **{member.name}** (`{member.id}`) 已加入你的服务器 **{guild.name}**。")
                except: pass
            log_embed = discord.Embed(title="🤖 白名单机器人加入", color=discord.Color.green(), timestamp=discord.utils.utcnow())
            log_embed.add_field(name="机器人", value=f"{member.mention} (`{member.id}`)", inline=False)
            log_embed.add_field(name="服务器", value=guild.name, inline=False)
            log_embed.add_field(name="状态", value="允许加入 (在白名单中)", inline=False)
            await send_to_public_log(guild, log_embed, "Whitelisted Bot Joined")
    # --- 严格的机器人加入控制结束 ---
# role_manager_bot.py

# ... (在你所有命令定义和辅助函数定义之后，但在 Run the Bot 之前) ...



# --- 新增：处理 AI 对话的辅助函数 (你之前已经添加了这个，确保它在 on_message 之前) ---
async def handle_ai_dialogue(message: discord.Message, is_private_chat: bool = False, dep_channel_config: Optional[dict] = None):
    """
    处理来自 AI DEP 频道或 AI 私聊频道的用户消息，并与 DeepSeek AI 交互。
    :param message: discord.Message 对象
    :param is_private_chat: bool, 是否为私聊频道
    :param dep_channel_config: dict, 如果是DEP频道，则传入其配置
    """
    user = message.author
    channel = message.channel
    guild = message.guild # guild is part of message object

    user_prompt_text = message.content.strip()
    if not user_prompt_text:
        if message.attachments: print(f"[AI DIALOGUE HANDLER] Message in {channel.id} from {user.id} has attachments but no text, ignoring.")
        return

    history_key = None
    dialogue_model = None
    system_prompt_for_api = None # 这是从DEP频道配置中获取的原始系统提示

    if is_private_chat:
        chat_info = active_private_ai_chats.get(channel.id)
        if not chat_info :
            print(f"[AI DIALOGUE HANDLER] Private chat {channel.id} - chat_info not found in active_private_ai_chats dict.")
            return
        
        if chat_info.get("user_id") != user.id and user.id != bot.user.id:
             print(f"[AI DIALOGUE HANDLER] Private chat {channel.id} - message from non-owner {user.id} (owner: {chat_info.get('user_id')}). Ignoring.")
             return

        history_key = chat_info.get("history_key")
        dialogue_model = chat_info.get("model", DEFAULT_AI_DIALOGUE_MODEL)
        # 私聊通常没有频道特定的 system_prompt_for_api，但如果以后需要，可以在此添加
    elif dep_channel_config:
        history_key = dep_channel_config.get("history_key")
        dialogue_model = dep_channel_config.get("model", DEFAULT_AI_DIALOGUE_MODEL)
        system_prompt_for_api = dep_channel_config.get("system_prompt") # 获取频道配置的系统提示
    else:
        print(f"[AI DIALOGUE HANDLER ERROR] Called without private_chat flag or dep_channel_config for channel {channel.id}")
        return

    if not history_key or not dialogue_model:
        print(f"[AI DIALOGUE HANDLER ERROR] Missing history_key or dialogue_model for channel {channel.id}. HK:{history_key}, DM:{dialogue_model}")
        try: await channel.send("❌ AI 对话关键配置丢失，请联系管理员。", delete_after=10)
        except: pass
        return
    
    if history_key not in conversation_histories:
        conversation_histories[history_key] = deque(maxlen=MAX_AI_HISTORY_TURNS * 2)
    history_deque = conversation_histories[history_key]

    api_messages = []

    # --- 整合服务器知识库和频道系统提示 ---
    knowledge_base_content = ""
    # 确保 guild_knowledge_bases 已在文件顶部定义
    if guild and guild.id in guild_knowledge_bases and guild_knowledge_bases[guild.id]:
        knowledge_base_content += "\n\n--- 服务器知识库信息 (请优先参考以下内容回答服务器特定问题) ---\n"
        for i, entry in enumerate(guild_knowledge_bases[guild.id]):
            knowledge_base_content += f"{i+1}. {entry}\n"
        knowledge_base_content += "--- 服务器知识库信息结束 ---\n"

    effective_system_prompt = ""
    if system_prompt_for_api: # 使用从DEP频道配置中获取的 system_prompt_for_api
        effective_system_prompt = system_prompt_for_api

    # 【【【核心修复 V3：使用通用化示例，防止跨服务器信息泄露】】】
    # 指导AI如何推理和应用知识库，而不泄露具体信息
    instructional_prompt = (
        "Your primary role is a helpful server assistant. You must follow these rules strictly:\n"
        "1. User prompts will be prefixed with '[提问者: DisplayName (ID: 1234567890)]'. This prefix provides the context of who is asking.\n"
        "2. You MUST analyze the user's ID from the prefix.\n"
        "3. If the user's ID matches an ID mentioned in the server knowledge base, you MUST treat the information in that knowledge base entry as facts ABOUT THE CURRENT USER.\n"
        "4. Your goal is to provide personalized answers by connecting the user's identity to the knowledge base.\n\n"
        "--- GENERIC EXAMPLE OF YOUR LOGIC ---\n"
        "Knowledge Base contains: 'VIP Member ID: 123456789012345678'\n"
        "User asks: '[提问者: SomeUser (ID: 123456789012345678)]\\n\\nDo I have any special roles?'\n"
        "Your CORRECT thought process: The user's ID matches the ID in the knowledge base. The knowledge base says this ID belongs to a VIP Member.\n"
        "Your CORRECT response should be: 'Yes, according to my records, you are a VIP Member.'\n"
        "--- END EXAMPLE ---"
    )
    if effective_system_prompt:
        effective_system_prompt = f"{instructional_prompt}\n\n{effective_system_prompt}"
    else:
        effective_system_prompt = instructional_prompt
    # 【【【修复结束】】】

    if knowledge_base_content: # 将知识库内容附加到（或构成）系统提示
        if effective_system_prompt:
            effective_system_prompt += knowledge_base_content
        else:
            effective_system_prompt = knowledge_base_content.strip()

    if effective_system_prompt:
        api_messages.append({"role": "system", "content": effective_system_prompt})
    # --- 服务器知识库与系统提示整合结束 ---
    
    for msg_entry in history_deque:
        if msg_entry.get("role") in ["user", "assistant"] and "content" in msg_entry and msg_entry.get("content") is not None:
            api_messages.append({"role": msg_entry["role"], "content": msg_entry["content"]})
    
    # --- 【核心修复：增强用户提问，注入上下文信息】 ---
    enhanced_user_prompt = f"[提问者: {message.author.display_name} (ID: {message.author.id})]\n\n{user_prompt_text}"
    api_messages.append({"role": "user", "content": enhanced_user_prompt})

    # 更新的 print 语句
    print(f"[AI DIALOGUE HANDLER] Processing for {('Private' if is_private_chat else 'DEP')} Channel {channel.id}, User {user.id}, Model {dialogue_model}, HistKey {history_key}, SysP: {effective_system_prompt != ''}")

    try:
        async with channel.typing():
            # 确保 aiohttp 已导入
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                response_embed_text, final_content_hist, api_error = await get_deepseek_dialogue_response(
                    session, DEEPSEEK_API_KEY, dialogue_model, api_messages
                )
        
        if api_error:
            try: await channel.send(f"🤖 处理您的请求时出现错误：\n`{api_error}`")
            except: pass
            return

        if response_embed_text:
            # 【重要】历史记录中仍然只保存原始的用户问题，避免上下文信息污染历史记录
            history_deque.append({"role": "user", "content": user_prompt_text})
            if final_content_hist is not None:
                history_deque.append({"role": "assistant", "content": final_content_hist})
            else:
                 print(f"[AI DIALOGUE HANDLER] No 'final_content_hist' (was None) to add to history. HK: {history_key}")

            embed = discord.Embed(
                color=discord.Color.blue() if is_private_chat else discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            author_name_prefix = f"{user.display_name} " if not is_private_chat else ""
            model_display_name_parts = dialogue_model.split('-')
            model_short_name = model_display_name_parts[-1].capitalize() if len(model_display_name_parts) > 1 else dialogue_model.capitalize()
            embed_author_name = f"{author_name_prefix}与 {model_short_name} 对话中"

            if user.avatar:
                embed.set_author(name=embed_author_name, icon_url=user.display_avatar.url)
            else:
                embed.set_author(name=embed_author_name)

            if not is_private_chat:
                 embed.add_field(name="👤 提问者", value=user.mention, inline=False)
            
            q_display = user_prompt_text
            if len(q_display) > 1000 : q_display = q_display[:1000] + "..."
            embed.add_field(name=f"💬 {('你的' if is_private_chat else '')}问题:", value=f"```{q_display}```", inline=False)
            
            if len(response_embed_text) <= 4050:
                embed.description = response_embed_text
            else:
                embed.add_field(name="🤖 AI 回复 (部分):", value=response_embed_text[:1020] + "...", inline=False)
                print(f"[AI DIALOGUE HANDLER] WARN: AI response for {channel.id} was very long and truncated for Embed field.")

            footer_model_info = dialogue_model
            # 更新的 footer 文本逻辑
            if effective_system_prompt and not is_private_chat : # 如果存在有效的系统提示 (可能包含知识库)
                footer_model_info += " (有系统提示/知识库)"
            elif effective_system_prompt and is_private_chat : # 私聊也可能有知识库影响
                footer_model_info += " (受知识库影响)"


            if bot.user.avatar:
                embed.set_footer(text=f"模型: {footer_model_info} | {bot.user.name}", icon_url=bot.user.display_avatar.url)
            else:
                embed.set_footer(text=f"模型: {footer_model_info} | {bot.user.name}")
            
            try: await channel.send(embed=embed)
            except Exception as send_e: print(f"[AI DIALOGUE HANDLER] Error sending embed to {channel.id}: {send_e}")

        else:
            print(f"[AI DIALOGUE HANDLER ERROR] 'response_embed_text' was None/empty after no API error. HK: {history_key}")
            try: await channel.send("🤖 抱歉，AI 未能生成有效的回复内容。")
            except: pass

    except Exception as e:
        print(f"[AI DIALOGUE HANDLER EXCEPTION] Unexpected error in channel {channel.id}. User: {user.id}. Error: {type(e).__name__} - {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            await channel.send(f"🤖 处理消息时发生内部错误 ({type(e).__name__})，请联系管理员。")
        except Exception as send_err:
            print(f"[AI DIALOGUE HANDLER SEND ERROR] Could not send internal error to channel {channel.id}. Secondary: {send_err}")

# ==================================================
# 👑 【进阶版】全局 @ 唤醒管家 + 自然语言指令执行
# ==================================================
async def handle_global_mention_ai(message: discord.Message):
    channel = message.channel
    guild = message.guild
    user = message.author

    # 1. 提取清理后的问题内容
    prompt_text = message.content
    for mention in message.mentions:
        if mention.id == bot.user.id:
            prompt_text = prompt_text.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '')
    prompt_text = prompt_text.strip()

    if not prompt_text:
        await message.reply(f"您好，{user.mention}！我是本服务器的智能管家，请问有什么可以帮您？")
        return

    # 2. 收集附带的上下文（让 AI 知道用户 @ 的那个人 ID 是多少）
    mentioned_users_info = ""
    for m in message.mentions:
        if m.id != bot.user.id:
            mentioned_users_info += f"User '{m.display_name}' has ID: {m.id}\n"

    # 3. 构建强大的 Agent JSON 提示词
    system_prompt = (
        f"You are the highly intelligent butler of the Discord server '{guild.name}'.\n"
        "You can chat naturally, but you can ALSO execute administrative commands if the user requests them.\n"
        "You MUST reply in a strict JSON format:\n"
        "{\n"
        '  "action": "KICK" | "MUTE" | "GIVE_MONEY" | "NONE",\n'
        '  "target_id": "numeric_id_of_the_target_user_if_any",\n'
        '  "amount": 0, // amount of money to give (if GIVE_MONEY)\n'
        '  "duration": 0, // mute duration in minutes (if MUTE)\n'
        '  "reply": "Your natural language conversational response in Chinese"\n'
        "}\n\n"
        "Rules:\n"
        "1. If the user just wants to chat or ask a question, set action to 'NONE' and put your response in 'reply'.\n"
        "2. If the user asks you to kick, banish, or remove someone, set action to 'KICK'.\n"
        "3. If the user asks you to mute, timeout, or silence someone, set action to 'MUTE' and parse the duration in minutes.\n"
        "4. If the user asks you to give, reward, or send money/coins to someone, set action to 'GIVE_MONEY' and parse the amount.\n"
        "5. ALWAYS extract the target user's numeric ID from the prompt or the context provided.\n"
        "6. In 'reply', talk like a polite, elegant butler confirming the action or chatting normally."
    )

    if mentioned_users_info:
        system_prompt += f"\n[Context: Mentioned Users in the prompt]\n{mentioned_users_info}"

    api_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"[{user.display_name}]: {prompt_text}"}
    ]

    try:
        async with channel.typing():
            # 这里我们强制要求 DeepSeek 返回 JSON 格式
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": "deepseek-chat", 
                    "messages": api_messages, 
                    "response_format": {"type": "json_object"}
                }
                
                async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        ai_raw_content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    else:
                        await message.reply(f"🤖 管家网络异常 (API 错误: HTTP {response.status})")
                        return

            # 4. 解析 AI 返回的 JSON 指令
            try:
                ai_decision = json.loads(ai_raw_content)
            except json.JSONDecodeError:
                print(f"[AI 解析错误] {ai_raw_content}")
                await message.reply("🤖 抱歉，我的逻辑处理模块出现了紊乱。")
                return

            action = ai_decision.get("action", "NONE")
            target_id_str = ai_decision.get("target_id", "")
            reply_text = ai_decision.get("reply", "好的。")
            amount = int(ai_decision.get("amount", 0))
            duration = int(ai_decision.get("duration", 0))

            # === 执行 AI 决定的操作 ===

            # 纯聊天，无动作
            if action == "NONE":
                await message.reply(reply_text)
                return

            # 如果有动作，检查目标玩家是否存在
            if not target_id_str or not str(target_id_str).isdigit():
                await message.reply(f"{reply_text}\n*(系统中止：AI 未能识别目标玩家的具体 ID)*")
                return
            
            target_id = int(target_id_str)
            target_member = guild.get_member(target_id)
            
            if not target_member:
                await message.reply(f"{reply_text}\n*(系统中止：该玩家似乎不在本服务器内)*")
                return

            # ⚡ 动作 1：踢出玩家
            if action == "KICK":
                if not user.guild_permissions.kick_members:
                    await message.reply(f"🚫 恕我直言 {user.mention}，您似乎没有权限让我踢出成员。")
                    return
                if target_member.top_role >= guild.me.top_role:
                    await message.reply(f"🚫 抱歉，这位成员的地位比我高，我无权将他踢出。")
                    return
                
                await target_member.kick(reason=f"由智能管家根据 {user.name} 的指令执行")
                database.db_log_moderation_action(guild.id, target_id, user.id, 'kick', 'AI管家口语指令执行', int(time.time()))
                await message.reply(f"🤖 {reply_text}\n*(执行结果：已成功将 {target_member.display_name} 踢出。)*")

            # ⚡ 动作 2：禁言玩家
            elif action == "MUTE":
                if not user.guild_permissions.moderate_members:
                    await message.reply(f"🚫 恕我直言 {user.mention}，您没有禁言成员的权限。")
                    return
                
                if duration <= 0: duration = 10 # 如果AI没解析出时间，默认10分钟
                timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=duration)
                await target_member.timeout(timeout_until, reason=f"由智能管家根据 {user.name} 的指令执行")
                database.db_log_moderation_action(guild.id, target_id, user.id, 'mute', 'AI管家口语指令执行', int(time.time()), duration*60)
                await message.reply(f"🤖 {reply_text}\n*(执行结果：已成功将 {target_member.display_name} 禁言 {duration} 分钟。)*")

            # ⚡ 动作 3：发放金币
            elif action == "GIVE_MONEY":
                if not user.guild_permissions.manage_guild: 
                    await message.reply(f"🚫 恕我直言 {user.mention}，只有服务器核心管理人员才能让我发钱。")
                    return
                
                if amount <= 0:
                    await message.reply("❓ 您要给多少钱呢？我没听清楚具体的数字，请重新吩咐。")
                    return
                
                if ECONOMY_ENABLED:
                    database.db_update_user_balance(guild.id, target_id, amount, is_delta=True, default_balance=ECONOMY_DEFAULT_BALANCE)
                    await message.reply(f"🤖 {reply_text}\n*(执行结果：已成功为 {target_member.display_name} 发放 {amount} 金币。)*")
                else:
                    await message.reply("⚙️ 抱歉，本服务器的经济系统目前处于关闭状态。")

            else:
                await message.reply(reply_text)

    except Exception as e:
        print(f"[Agent Execution Error] {e}")
        await message.reply("🤖 管家系统在执行指令时短路了，请联系技术人员。")
# ==================================================
# 👑 进阶全局唤醒逻辑结束
# ==================================================
# --- (handle_ai_dialogue 函数定义结束) ---


# --- Event: On Message - Handles AI Dialogues, Content Check, Spam ---
@bot.event
async def on_message(message: discord.Message):
    # --- 1. 处理私信 (RelayMsg) ---
    if isinstance(message.channel, discord.DMChannel) and message.author.id != bot.user.id:
        if message.reference and message.reference.message_id in ANONYMOUS_RELAY_SESSIONS:
            session_info = ANONYMOUS_RELAY_SESSIONS[message.reference.message_id]
            if message.author.id == session_info["target_id"]:
                guild = bot.get_guild(session_info["guild_id"])
                original_channel = guild.get_channel(session_info["original_channel_id"]) if guild else None
                if original_channel and isinstance(original_channel, discord.TextChannel):
                    try:
                        target_user_obj = await bot.fetch_user(session_info["target_id"])
                        reply_user_name = target_user_obj.display_name if target_user_obj else f"用户 {session_info.get('target_id', '未知')}"
                        reply_embed = discord.Embed(
                            title=f"💬 来自 {reply_user_name} 的回复",
                            description=f"```\n{message.content}\n```",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        reply_embed.set_footer(text=f"此回复针对由 {session_info.get('initiator_display_name', '未知用户')} 发起的匿名消息")
                        if message.attachments:
                            if message.attachments[0].content_type and message.attachments[0].content_type.startswith('image/'):
                                reply_embed.set_image(url=message.attachments[0].url)
                            else:
                                reply_embed.add_field(name="📎 附件", value=f"[{message.attachments[0].filename}]({message.attachments[0].url})", inline=False)

                        await original_channel.send(content=f"<@{session_info['initiator_id']}>，你收到了对匿名消息的回复：", embed=reply_embed)
                        await message.author.send("✅ 你的回复已成功转发。", delete_after=30)
                    except Exception as e:
                        print(f"[RelayMsg ERROR] Relaying DM reply: {e}")
                else:
                     print(f"[RelayMsg ERROR] Guild or original channel not found for session.")
            return
        return

    # --- 2. 基本过滤 (服务器消息) ---
    if not message.guild or message.author.bot or message.interaction is not None or message.content.startswith(COMMAND_PREFIX) or message.content.startswith('/'):
        return

    author = message.author
    guild = message.guild
    channel = message.channel
    now = discord.utils.utcnow()

    # --- 3. 票据频道相关逻辑 (核心修复) ---
    ticket_info = database.db_get_ticket_by_channel(channel.id)

    if ticket_info:
        # A. 转发消息到Web面板
        if ticket_info['status'] in ['OPEN', 'CLAIMED'] and socketio:
            msg_data = {
                'id': str(message.id),
                'author': {
                    'id': str(message.author.id),
                    'name': message.author.display_name,
                    'avatar_url': str(message.author.display_avatar.url),
                    'is_bot': message.author.bot
                },
                'content': message.clean_content,
                'embeds': [embed.to_dict() for embed in message.embeds],
                'timestamp': message.created_at.isoformat(),
                'channel_id': str(message.channel.id)
            }
            socketio.emit('new_ticket_message', msg_data, room=f'ticket_{message.channel.id}')
        
        # B. 检查并处理AI托管的票据
        # 【【【核心修复】】】使用简单的 await 调用，并增加日志
        if ticket_info.get('is_ai_managed') and ticket_info['creator_id'] == message.author.id:
            logging.info(f"[on_message] AI托管票据 {ticket_info['ticket_id']} 收到用户新消息，准备调用 handle_ai_ticket_reply...")
            await handle_ai_ticket_reply(message)
        
        return
    
    # --- 4. AI专用频道处理 (非票据频道) ---
    if channel.id in ai_dep_channels_config:
        await handle_ai_dialogue(message, is_private_chat=False, dep_channel_config=ai_dep_channels_config[channel.id])
        return

    if channel.id in active_private_ai_chats:
        await handle_ai_dialogue(message, is_private_chat=True)
        return
        
# ==================================
    # 👑 【新增】触发全局 @ 唤醒管家
    # ==================================
    if bot.user in message.mentions:
        await handle_global_mention_ai(message)
        return

    # --- 5. 审核豁免检查 ---
    member = guild.get_member(author.id)
    is_exempt = (
        (member and channel.permissions_for(member).manage_messages) or
        (author.id in exempt_users_from_ai_check) or
        (channel.id in exempt_channels_from_ai_check)
    )

    # === 👇👇👇 在这里添加调试打印 👇👇👇 ===
    print(f"[DEBUG AUDIT] 收到消息: '{message.content}' 来自 {author.name}")
    print(f"[DEBUG AUDIT] 是否豁免: {is_exempt}")
    if is_exempt:
        print(f"   - 原因: 管理员权限? {channel.permissions_for(member).manage_messages}")
        print(f"   - 原因: 白名单用户? {author.id in exempt_users_from_ai_check}")
    # ==========================================
    
    # --- 6. 内容审核核心逻辑 (仅对非豁免用户执行) ---
    if not is_exempt:
        loop = asyncio.get_running_loop()
        
        async def handle_violation(violation_type_str: str, msg_content: str):
            print(f"[AUDIT] Detected violation: '{violation_type_str}' by {author.id}")
            
            auto_deleted = False
            try:
                if channel.permissions_for(guild.me).manage_messages:
                    await message.delete()
                    auto_deleted = True
                    print(f"  - Action: Auto-deleted violation message.")
                else:
                    print(f"  - FAILED to auto-delete: Missing 'Manage Messages' permission.")
            except Exception as del_err:
                print(f"  - FAILED to auto-delete: {del_err}")

            if socketio:
                event_data = {
                    'user': {'id': str(author.id), 'name': author.display_name, 'avatar_url': str(author.display_avatar.url)},
                    'message': {'id': str(message.id), 'content': msg_content[:500], 'channel_id': str(channel.id), 'channel_name': channel.name, 'jump_url': message.jump_url},
                    'guild': {'id': str(guild.id)},
                    'violation_type': violation_type_str,
                    'timestamp': now.isoformat(),
                    'auto_deleted': auto_deleted
                }
                
                event_id = database.db_log_audit_event(event_data)
                
                if event_id:
                    event_data['event_id'] = event_id
                    await loop.run_in_executor(None, lambda: socketio.emit('new_violation', event_data, room=f'audit_{guild.id}'))
                    print(f"  - Action: Logged to DB (Event ID: {event_id}) and sent 'new_violation' event to web audit room.")
                else:
                    print("  - CRITICAL: Failed to log violation to database. Event was not sent to web panel.")

        violation_type = await check_message_with_deepseek(message.content)
        if violation_type:
            await handle_violation(f"AI审查: {violation_type}", message.content)
            return

        if BAD_WORDS_LOWER:
            content_lower = message.content.lower()
            triggered_bad_word = next((word for word in BAD_WORDS_LOWER if word in content_lower), None)
            if triggered_bad_word:
                await handle_violation(f"本地关键词: {triggered_bad_word}", message.content)
                return

    # --- 7. 用户刷屏检测逻辑 (非管理员才进行刷屏检测) ---
    if not is_exempt:
        guild_timestamps = user_message_timestamps.setdefault(guild.id, {})
        guild_warnings = user_warnings.setdefault(guild.id, {})

        guild_timestamps.setdefault(author.id, deque(maxlen=SPAM_COUNT_THRESHOLD + 5))
        if author.id not in guild_warnings: guild_warnings[author.id] = 0

        current_time_dt_spam = datetime.datetime.now(datetime.timezone.utc) 
        guild_timestamps[author.id].append(current_time_dt_spam)
        
        time_limit_user_spam = current_time_dt_spam - datetime.timedelta(seconds=SPAM_TIME_WINDOW_SECONDS)
        recent_messages_count = sum(1 for ts in guild_timestamps[author.id] if ts > time_limit_user_spam)

        if recent_messages_count >= SPAM_COUNT_THRESHOLD:
            print(f"[SPAM] User spam detected: {author.id} in guild {guild.id}")
            guild_timestamps[author.id].clear()
            
            guild_warnings[author.id] += 1
            warning_count_spam = guild_warnings[author.id]
            reason_spam = "自动警告：发送消息过于频繁 (刷屏)"
            
            log_embed_spam = discord.Embed(title="自动警告 (用户刷屏)", color=discord.Color.orange(), timestamp=now)
            log_embed_spam.add_field(name="用户", value=f"{author.mention} ({author.id})", inline=False)
            log_embed_spam.add_field(name="原因", value=reason_spam, inline=False)
            log_embed_spam.add_field(name="当前警告次数", value=f"{warning_count_spam}/{KICK_THRESHOLD}", inline=False)
            
            kick_performed_spam = False
            if warning_count_spam >= KICK_THRESHOLD:
                log_embed_spam.title = "🚨 警告已达上限 - 自动踢出 (用户刷屏) 🚨"
                log_embed_spam.color = discord.Color.red()
                if member and guild.me.guild_permissions.kick_members and (guild.me.top_role > member.top_role or guild.me == guild.owner):
                    try:
                        await member.kick(reason="自动踢出: 刷屏警告达上限")
                        kick_performed_spam = True
                        guild_warnings[member.id] = 0
                        log_embed_spam.add_field(name="踢出状态", value="✅ 成功", inline=False)
                        print(f"  - User {author.id} kicked for spamming.")
                    except Exception as kick_e:
                        log_embed_spam.add_field(name="踢出状态", value=f"❌ 失败 ({kick_e})", inline=False)
                else:
                    log_embed_spam.add_field(name="踢出状态", value="❌ 失败 (权限/层级不足)", inline=False)
            
            await send_to_public_log(guild, log_embed_spam, log_type="Auto Warn (User Spam)")
            if not kick_performed_spam:
                try:
                    await channel.send(f"⚠️ {author.mention}，检测到你发送消息过于频繁，请减缓速度！(警告 {warning_count_spam}/{KICK_THRESHOLD})", delete_after=15)
                except discord.HTTPException:
                    pass
            
            return

    # --- 8. 经济系统聊天赚钱 ---
    if ECONOMY_ENABLED:
        if len(message.content) > 5 or message.attachments or message.stickers:
            guild_id = message.guild.id
            user_id = message.author.id
            config = database.db_get_guild_chat_earn_config(guild_id, ECONOMY_CHAT_EARN_DEFAULT_AMOUNT, ECONOMY_CHAT_EARN_DEFAULT_COOLDOWN_SECONDS)
            earn_amount = config["amount"]
            cooldown_seconds = config["cooldown"]
            
            if earn_amount > 0:
                now_ts = time.time()
                last_earn = last_chat_earn_times.setdefault(guild_id, {}).get(user_id, 0)
                if now_ts - last_earn > cooldown_seconds:
                    if database.db_update_user_balance(guild_id, user_id, earn_amount, is_delta=True, default_balance=ECONOMY_DEFAULT_BALANCE):
                        last_chat_earn_times[guild_id][user_id] = now_ts
                        # print(f"[经济系统] 用户 {user_id} 在服务器 {guild_id} 通过聊天赚取了 {earn_amount} {ECONOMY_CURRENCY_NAME}。")
                        # 可选：发送非常细微的确认或记录，但避免刷屏聊天
                        # await message.add_reaction("🪙") # 示例：细微的反应 - 可能过多
                        # save_economy_data() # 每次赚钱都保存可能导致 I/O 过于密集。
    
    # --- (如果你在末尾有 bot.process_commands(message)，请保留它) ---
    # pass # 如果没有 process_commands

    # --- 5. Bot 刷屏检测逻辑 (如果需要，并且确保它在你原有逻辑中是工作的) ---
    # 注意：这个逻辑块通常应该在 on_message 的最开始处理，因为它只针对其他机器人。
    # 但为了保持你原有结构的顺序，我先放在这里。如果你的机器人不应该响应其他机器人刷屏，
    # 那么在文件开头的 if message.author.bot: return 就可以处理。
    # 如果你需要检测其他机器人刷屏并采取行动，这里的逻辑需要被激活并仔细测试。
    
    # if message.author.bot and message.author.id != bot.user.id: # 已在开头排除自己
    #     bot_author_id = message.author.id
    #     bot_message_timestamps.setdefault(bot_author_id, deque(maxlen=BOT_SPAM_COUNT_THRESHOLD + 5))
    #     current_time_dt_bot_spam = datetime.datetime.now(datetime.timezone.utc)
    #     bot_message_timestamps[bot_author_id].append(current_time_dt_bot_spam)
        
    #     time_limit_bot_spam = current_time_dt_bot_spam - datetime.timedelta(seconds=BOT_SPAM_TIME_WINDOW_SECONDS)
    #     recent_bot_messages_count = sum(1 for ts in bot_message_timestamps[bot_author_id] if ts > time_limit_bot_spam)

    #     if recent_bot_messages_count >= BOT_SPAM_COUNT_THRESHOLD:
    #         print(f"[OnMessage] SPAM (Bot): {bot_author_id} in #{channel.name}")
    #         bot_message_timestamps[bot_author_id].clear()
    #         # ... (你原来的机器人刷屏处理逻辑，例如发送警告给管理员，尝试踢出或移除权限) ...
    #         return

    # 如果消息未被以上任何一个特定逻辑处理
    # 并且你还使用了旧的前缀命令，可以在这里处理 (通常现在不推荐与斜杠命令混用)
    # if message.content.startswith(COMMAND_PREFIX):
    #    await bot.process_commands(message)
    pass
# --- (on_message 函数定义结束) ---


# --- Event: Voice State Update ---
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    guild = member.guild
    # 使用正确的存储字典
    master_vc_id = get_setting(temp_vc_settings, guild.id, "master_channel_id")
    category_id = get_setting(temp_vc_settings, guild.id, "category_id")

    if not master_vc_id: return

    master_channel = guild.get_channel(master_vc_id)
    if not master_channel or not isinstance(master_channel, discord.VoiceChannel):
        print(f"⚠️ 临时语音：服务器 {guild.name} 的母频道 ID ({master_vc_id}) 无效或不是语音频道。")
        # set_setting(temp_vc_settings, guild.id, "master_channel_id", None) # Optional: Clear invalid setting
        return

    category = None
    if category_id:
        category = guild.get_channel(category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            print(f"⚠️ 临时语音：服务器 {guild.name} 配置的分类 ID ({category_id}) 无效或不是分类频道，将尝试在母频道所在分类创建。")
            category = master_channel.category
    else: category = master_channel.category

    # --- User joins master channel -> Create temp channel ---
    if after.channel == master_channel:
        if not category or not category.permissions_for(guild.me).manage_channels or \
           not category.permissions_for(guild.me).move_members:
            print(f"❌ 临时语音创建失败：机器人在分类 '{category.name if category else '未知'}' 中缺少 '管理频道' 或 '移动成员' 权限。 ({member.name})")
            try: await member.send(f"抱歉，我在服务器 **{guild.name}** 中创建临时语音频道所需的权限不足，请联系管理员检查我在分类 '{category.name if category else '默认'}' 中的权限。")
            except: pass
            return

        print(f"🔊 用户 {member.name} 加入了母频道 ({master_channel.name})，准备创建临时频道...")
        new_channel = None # Init before try
        try:
            owner_overwrites = discord.PermissionOverwrite(manage_channels=True, manage_permissions=True, move_members=True, connect=True, speak=True, stream=True, use_voice_activation=True, priority_speaker=True, mute_members=True, deafen_members=True, use_embedded_activities=True)
            everyone_overwrites = discord.PermissionOverwrite(connect=True, speak=True)
            bot_overwrites = discord.PermissionOverwrite(manage_channels=True, manage_permissions=True, move_members=True, connect=True, view_channel=True)
            temp_channel_name = f"🎮 {member.display_name} 的频道"[:100]

            new_channel = await guild.create_voice_channel(
                name=temp_channel_name, category=category,
                overwrites={guild.default_role: everyone_overwrites, member: owner_overwrites, guild.me: bot_overwrites},
                reason=f"由 {member.name} 加入母频道自动创建"
            )
            print(f"   ✅ 已创建临时频道: {new_channel.name} ({new_channel.id})")

            try:
                await member.move_to(new_channel, reason="移动到新创建的临时频道")
                print(f"   ✅ 已将 {member.name} 移动到频道 {new_channel.name}。")
                temp_vc_owners[new_channel.id] = member.id
                temp_vc_created.add(new_channel.id)
            except Exception as move_e:
                print(f"   ❌ 将 {member.name} 移动到新频道时发生错误: {move_e}")
                try: await new_channel.delete(reason="移动用户失败/错误，自动删除")
                except: pass # Ignore deletion error if move failed

        except Exception as e:
            print(f"   ❌ 创建/移动临时语音频道时发生错误: {e}")
            if new_channel: # Clean up channel if created before error
                 try: await new_channel.delete(reason="创建/移动过程中出错")
                 except: pass

    # --- User leaves a temp channel -> Check if empty and delete ---
    if before.channel and before.channel.id in temp_vc_created:
        await asyncio.sleep(1) # Short delay
        channel_to_check = guild.get_channel(before.channel.id)

        if channel_to_check and isinstance(channel_to_check, discord.VoiceChannel):
            is_empty = not any(m for m in channel_to_check.members if not m.bot)
            if is_empty:
                print(f"🔊 临时频道 {channel_to_check.name} ({channel_to_check.id}) 已空，准备删除...")
                try:
                    if channel_to_check.permissions_for(guild.me).manage_channels:
                        await channel_to_check.delete(reason="临时语音频道为空，自动删除")
                        print(f"   ✅ 已成功删除频道 {channel_to_check.name}。")
                    else: print(f"   ❌ 删除频道 {channel_to_check.name} 失败：机器人缺少 '管理频道' 权限。")
                except discord.NotFound: print(f"   ℹ️ 尝试删除频道 {channel_to_check.name} 时未找到 (可能已被删)。")
                except discord.Forbidden: print(f"   ❌ 删除频道 {channel_to_check.name} 失败：机器人权限不足。")
                except Exception as e: print(f"   ❌ 删除频道 {channel_to_check.name} 时发生未知错误: {e}")
                finally: # Clean up memory regardless of deletion success
                    if channel_to_check.id in temp_vc_owners: del temp_vc_owners[channel_to_check.id]
                    if channel_to_check.id in temp_vc_created: temp_vc_created.remove(channel_to_check.id)
                    # print(f"   - 已清理频道 {channel_to_check.id} 的内存记录。") # Less verbose log
        else: # Channel disappeared during delay or isn't a VC anymore
            if before.channel.id in temp_vc_owners: del temp_vc_owners[before.channel.id]
            if before.channel.id in temp_vc_created: temp_vc_created.remove(before.channel.id)


# --- Slash Command Definitions ---

# --- Help Command ---
@bot.tree.command(name="help", description="显示可用指令的帮助信息。")
async def slash_help(interaction: discord.Interaction):
    """显示所有可用斜线指令的概览"""
    embed = discord.Embed(
        title="🤖 GJ Team Bot 指令帮助",
        description="以下是本机器人支持的斜线指令列表：",
        color=discord.Color.purple() # 紫色
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url) # 显示机器人头像

    # 身份组管理
    embed.add_field(
        name="👤 身份组管理",
        value=(
            "`/createrole [身份组名称]` - 创建新身份组\n"
            "`/deleterole [身份组名称]` - 删除现有身份组\n"
            "`/giverole [用户] [身份组名称]` - 赋予用户身份组\n"
            "`/takerole [用户] [身份组名称]` - 移除用户身份组\n"
            "`/createseparator [标签]` - 创建分隔线身份组"
        ),
        inline=False
    )

    # 审核与管理
    embed.add_field(
        name="🛠️ 审核与管理",
        value=(
            "`/clear [数量]` - 清除当前频道消息 (1-100)\n"
            "`/warn [用户] [原因]` - 手动警告用户 (累计3次踢出)\n"
            "`/unwarn [用户] [原因]` - 移除用户一次警告\n"  # <--- 确保这里有换行符
            "`/notify_member [用户] [消息内容]` - 通过机器人向指定成员发送私信。" # <--- 新增这行
        ),
        inline=False
    )

    embed.add_field(
        name="🕵️ 匿名中介私信 (/relaymsg ...)",
        value=(
            "`... send [目标用户] [消息]` - 通过机器人向指定成员发送匿名消息。\n"
            "*接收方可以直接回复机器人私信，回复将被转发回你发起命令的频道。*"
            # 如果未来添加频道内回复功能，可以在此补充
        ),
        inline=False
    )

    # AI 对话与知识库
    embed.add_field(
        name="🤖 AI 对话与知识库 (/ai ...)", # 更新字段标题
        value=(
            "`... setup_dep_channel [频道] [模型] [系统提示]` - 设置AI直接对话频道\n"
            "`... clear_dep_history` - 清除当前AI频道对话历史\n"
            "`... create_private_chat [模型] [初始问题]` - 创建AI私聊频道\n"
            "`... close_private_chat` - 关闭你的AI私聊频道\n"
            "**AI知识库管理 (管理员):**\n" # 新增小标题
            "`... kb_add [内容]` - 添加知识到AI知识库\n"
            "`... kb_list` - 查看AI知识库条目\n"
            "`... kb_remove [序号]` - 移除指定知识条目\n"
            "`... kb_clear` - 清空服务器AI知识库"
        ),
        inline=False
    )

    # FAQ/帮助系统
    embed.add_field(
        name="❓ FAQ/帮助 (/faq ...)",
        value=(
            "`... search [关键词]` - 搜索FAQ/帮助信息\n"
            "**管理员指令:**\n"
            "`... add [关键词] [答案]` - 添加新的FAQ条目\n"
            "`... remove [关键词]` - 移除FAQ条目\n"
            "`... list` - 列出所有FAQ关键词"
        ),
        inline=False
    )

     # 公告
    embed.add_field(
        name="📢 公告发布",
        value=(
            "`/announce [频道] [标题] [消息] [提及身份组] [图片URL] [颜色]` - 发送嵌入式公告"
        ),
        inline=False
    )

    # 高级管理指令组 (/管理 ...)
    embed.add_field(
        name="⚙️ 高级管理指令 (/管理 ...)",
        value=(
            "`... 票据设定 [按钮频道] [票据分类] [员工身份组]` - 设置票据系统\n" # <--- 新增
            "`... 删讯息 [用户] [数量]` - 删除特定用户消息\n"
            "`... 频道名 [新名称]` - 修改当前频道名称\n"
            "`... 禁言 [用户] [分钟数] [原因]` - 禁言用户 (0=永久/28天)\n"
            "`... 踢出 [用户] [原因]` - 将用户踢出服务器\n"
            "`... 封禁 [用户ID] [原因]` - 永久封禁用户 (按ID)\n"
            "`... 解封 [用户ID] [原因]` - 解除用户封禁 (按ID)\n"
            "`... 人数频道 [名称模板]` - 创建/更新成员人数统计频道\n"
            "`... ai豁免-添加用户 [用户]` - 添加用户到AI检测豁免\n"
            "`... ai豁免-移除用户 [用户]` - 从AI豁免移除用户\n"
            "`... ai豁免-添加频道 [频道]` - 添加频道到AI检测豁免\n"
            "`... ai豁免-移除频道 [频道]` - 从AI豁免移除频道\n"
            "`... ai豁免-查看列表` - 查看当前AI豁免列表"
        ),
        inline=False
    )


    # --- 将经济系统指令添加到帮助信息 ---
    embed.add_field(
        name=f"{ECONOMY_CURRENCY_SYMBOL} {ECONOMY_CURRENCY_NAME}系统 (/eco ...)",
        value=(
            f"`... balance ([用户])` - 查看你或他人的{ECONOMY_CURRENCY_NAME}余额。\n"
            f"`... transfer <用户> <金额>` - 向其他用户转账{ECONOMY_CURRENCY_NAME}。\n"
            f"`... shop` - 查看商店中的可用物品。\n"
            f"`... buy <物品名称或ID>` - 从商店购买物品。\n"
            f"`... leaderboard` - 显示{ECONOMY_CURRENCY_NAME}排行榜。"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ 高级管理指令 (/管理 ...)",
        value=(
            "`... 票据设定 ...`\n" # 保持此项简洁
            # ... (其他现有的管理员指令) ...
            f"`... eco_admin give <用户> <金额>` - 给予用户{ECONOMY_CURRENCY_NAME}。\n"
            f"`... eco_admin take <用户> <金额>` - 移除用户{ECONOMY_CURRENCY_NAME}。\n"
            f"`... eco_admin set <用户> <金额>` - 设置用户{ECONOMY_CURRENCY_NAME}。\n"
            f"`... eco_admin config_chat_earn <金额> <冷却>` - 配置聊天收益。\n"
            f"`... eco_admin add_shop_item <名称> <价格> ...` - 添加商店物品。\n"
            f"`... eco_admin remove_shop_item <物品>` - 移除商店物品。\n"
            f"`... eco_admin edit_shop_item <物品> ...` - 编辑商店物品。"
            # ... (你现有的 /管理 帮助信息的其余部分) ...
        ),
        inline=False
    )

    # 临时语音指令组 (/语音 ...)
    embed.add_field(
        name="🔊 临时语音频道 (/语音 ...)",
        value=(
            "`... 设定母频道 [母频道] [分类]` - 设置创建临时语音的入口频道\n"
            "`... 设定权限 [对象] [权限设置]` - (房主) 设置频道成员权限\n"
            "`... 转让 [新房主]` - (房主) 转让频道所有权\n"
            "`... 房主` - (成员) 如果原房主不在，尝试获取房主权限"
        ),
        inline=False
    )

        # 其他
    embed.add_field(
        name="ℹ️ 其他",
        value=(
            "`/help` - 显示此帮助信息\n"
            "`/ping` - 查看机器人与服务器的延迟"  # <--- 新增这行
        ),
        inline=False
    )

    embed.set_footer(text="[] = 必填参数, <> = 可选参数。大部分管理指令需要相应权限。")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    await interaction.response.send_message(embed=embed, ephemeral=True) # 临时消息，仅请求者可见


# --- Role Management Commands ---
@bot.tree.command(name="createrole", description="在服务器中创建一个新的身份组。")
@app_commands.describe(role_name="新身份组的确切名称。")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def slash_createrole(interaction: discord.Interaction, role_name: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    if get(guild.roles, name=role_name): await interaction.followup.send(f"❌ 身份组 **{role_name}** 已经存在！", ephemeral=True); return
    if len(role_name) > 100: await interaction.followup.send("❌ 身份组名称过长（最多100个字符）。", ephemeral=True); return
    if not role_name.strip(): await interaction.followup.send("❌ 身份组名称不能为空。", ephemeral=True); return

    try:
        new_role = await guild.create_role(name=role_name, reason=f"由 {interaction.user} 创建")
        await interaction.followup.send(f"✅ 已成功创建身份组: {new_role.mention}", ephemeral=False)
        print(f"[身份组操作] 用户 {interaction.user} 创建了身份组 '{new_role.name}' ({new_role.id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 创建身份组 **{role_name}** 失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /createrole 时出错: {e}"); await interaction.followup.send(f"⚙️ 创建身份组时发生未知错误: {e}", ephemeral=True)


@bot.tree.command(name="deleterole", description="根据精确名称删除一个现有的身份组。")
@app_commands.describe(role_name="要删除的身份组的确切名称。")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def slash_deleterole(interaction: discord.Interaction, role_name: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    role_to_delete = get(guild.roles, name=role_name)
    if not role_to_delete: await interaction.followup.send(f"❓ 找不到名为 **{role_name}** 的身份组。", ephemeral=True); return
    if role_to_delete == guild.default_role: await interaction.followup.send("🚫 不能删除 `@everyone` 身份组。", ephemeral=True); return
    if role_to_delete.is_integration() or role_to_delete.is_bot_managed(): await interaction.followup.send(f"⚠️ 不能删除由集成或机器人管理的身份组 {role_to_delete.mention}。", ephemeral=True); return
    if role_to_delete.is_premium_subscriber(): await interaction.followup.send(f"⚠️ 不能删除 Nitro Booster 身份组 {role_to_delete.mention}。", ephemeral=True); return
    if role_to_delete >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 无法删除身份组 {role_to_delete.mention}：我的身份组层级低于或等于它。", ephemeral=True); return

    try:
        deleted_role_name = role_to_delete.name
        await role_to_delete.delete(reason=f"由 {interaction.user} 删除")
        await interaction.followup.send(f"✅ 已成功删除身份组: **{deleted_role_name}**", ephemeral=False)
        print(f"[身份组操作] 用户 {interaction.user} 删除了身份组 '{deleted_role_name}' ({role_to_delete.id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 删除身份组 **{role_name}** 失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /deleterole 时出错: {e}"); await interaction.followup.send(f"⚙️ 删除身份组时发生未知错误: {e}", ephemeral=True)


@bot.tree.command(name="giverole", description="将一个现有的身份组分配给指定成员。")
@app_commands.describe(user="要给予身份组的用户。", role_name="要分配的身份组的确切名称。")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def slash_giverole(interaction: discord.Interaction, user: discord.Member, role_name: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    role_to_give = get(guild.roles, name=role_name)
    if not role_to_give: await interaction.followup.send(f"❓ 找不到名为 **{role_name}** 的身份组。", ephemeral=True); return
    if role_to_give == guild.default_role: await interaction.followup.send("🚫 不能手动赋予 `@everyone` 身份组。", ephemeral=True); return
    if role_to_give >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 无法分配身份组 {role_to_give.mention}：我的身份组层级低于或等于它。", ephemeral=True); return
    if isinstance(interaction.user, discord.Member) and interaction.user.id != guild.owner_id:
        if role_to_give >= interaction.user.top_role: await interaction.followup.send(f"🚫 你无法分配层级等于或高于你自己的身份组 ({role_to_give.mention})。", ephemeral=True); return
    if role_to_give in user.roles: await interaction.followup.send(f"ℹ️ 用户 {user.mention} 已经拥有身份组 {role_to_give.mention}。", ephemeral=True); return

    try:
        await user.add_roles(role_to_give, reason=f"由 {interaction.user} 赋予")
        await interaction.followup.send(f"✅ 已成功将身份组 {role_to_give.mention} 赋予给 {user.mention}。", ephemeral=False)
        print(f"[身份组操作] 用户 {interaction.user} 将身份组 '{role_to_give.name}' ({role_to_give.id}) 赋予了用户 {user.name} ({user.id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 赋予身份组 **{role_name}** 给 {user.mention} 失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /giverole 时出错: {e}"); await interaction.followup.send(f"⚙️ 赋予身份组时发生未知错误: {e}", ephemeral=True)


@bot.tree.command(name="takerole", description="从指定成员移除一个特定的身份组。")
@app_commands.describe(user="要移除其身份组的用户。", role_name="要移除的身份组的确切名称。")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def slash_takerole(interaction: discord.Interaction, user: discord.Member, role_name: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    role_to_take = get(guild.roles, name=role_name)
    if not role_to_take: await interaction.followup.send(f"❓ 找不到名为 **{role_name}** 的身份组。", ephemeral=True); return
    if role_to_take == guild.default_role: await interaction.followup.send("🚫 不能移除 `@everyone` 身份组。", ephemeral=True); return
    if role_to_take.is_integration() or role_to_take.is_bot_managed(): await interaction.followup.send(f"⚠️ 不能手动移除由集成或机器人管理的身份组 {role_to_take.mention}。", ephemeral=True); return
    if role_to_take.is_premium_subscriber(): await interaction.followup.send(f"⚠️ 不能手动移除 Nitro Booster 身份组 {role_to_take.mention}。", ephemeral=True); return
    if role_to_take >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 无法移除身份组 {role_to_take.mention}：我的身份组层级低于或等于它。", ephemeral=True); return
    if isinstance(interaction.user, discord.Member) and interaction.user.id != guild.owner_id:
         if role_to_take >= interaction.user.top_role: await interaction.followup.send(f"🚫 你无法移除层级等于或高于你自己的身份组 ({role_to_take.mention})。", ephemeral=True); return
    if role_to_take not in user.roles: await interaction.followup.send(f"ℹ️ 用户 {user.mention} 并未拥有身份组 {role_to_take.mention}。", ephemeral=True); return

    try:
        await user.remove_roles(role_to_take, reason=f"由 {interaction.user} 移除")
        await interaction.followup.send(f"✅ 已成功从 {user.mention} 移除身份组 {role_to_take.mention}。", ephemeral=False)
        print(f"[身份组操作] 用户 {interaction.user} 从用户 {user.name} ({user.id}) 移除了身份组 '{role_to_take.name}' ({role_to_take.id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 从 {user.mention} 移除身份组 **{role_name}** 失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /takerole 时出错: {e}"); await interaction.followup.send(f"⚙️ 移除身份组时发生未知错误: {e}", ephemeral=True)


@bot.tree.command(name="createseparator", description="创建一个用于视觉分隔的特殊身份组。")
@app_commands.describe(label="要在分隔线中显示的文字标签 (例如 '成员信息', '游戏身份')。")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def slash_createseparator(interaction: discord.Interaction, label: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    separator_name = f"▽─── {label} ───" # Simplified name
    if len(separator_name) > 100: await interaction.followup.send(f"❌ 标签文字过长，导致分隔线名称超过100字符限制。", ephemeral=True); return
    if not label.strip(): await interaction.followup.send(f"❌ 标签不能为空。", ephemeral=True); return
    if get(guild.roles, name=separator_name): await interaction.followup.send(f"⚠️ 似乎已存在基于标签 **{label}** 的分隔线身份组 (**{separator_name}**)！", ephemeral=True); return

    try:
        new_role = await guild.create_role(name=separator_name, permissions=discord.Permissions.none(), color=discord.Color.default(), hoist=False, mentionable=False, reason=f"由 {interaction.user} 创建的分隔线")
        await interaction.followup.send(f"✅ 已成功创建分隔线身份组: **{new_role.name}**\n**重要提示:** 请前往 **服务器设置 -> 身份组**，手动将此身份组拖动到你希望的位置！", ephemeral=False)
        print(f"[身份组操作] 用户 {interaction.user} 创建了分隔线 '{new_role.name}' ({new_role.id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 创建分隔线失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /createseparator 时出错: {e}"); await interaction.followup.send(f"⚙️ 创建分隔线时发生未知错误: {e}", ephemeral=True)

# --- Moderation Commands ---
@bot.tree.command(name="clear", description="清除当前频道中指定数量的消息 (1-100)。")
@app_commands.describe(amount="要删除的消息数量 (1 到 100 之间)。")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
async def slash_clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel): await interaction.response.send_message("❌ 此命令只能在文字频道中使用。", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)

    try:
        deleted_messages = await channel.purge(limit=amount)
        deleted_count = len(deleted_messages)
        await interaction.followup.send(f"✅ 已成功删除 {deleted_count} 条消息。", ephemeral=True)
        print(f"[审核操作] 用户 {interaction.user} 在频道 #{channel.name} 清除了 {deleted_count} 条消息。")
        log_embed = discord.Embed(title="🧹 消息清除操作", color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="频道", value=channel.mention, inline=True)
        log_embed.add_field(name="清除数量", value=str(deleted_count), inline=True)
        log_embed.set_footer(text=f"执行者 ID: {interaction.user.id}")
        await send_to_public_log(interaction.guild, log_embed, log_type="Clear Messages")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 清除消息失败：机器人缺少在频道 {channel.mention} 中删除消息的权限。", ephemeral=True)
    except Exception as e: print(f"执行 /clear 时出错: {e}"); await interaction.followup.send(f"⚙️ 清除消息时发生未知错误: {e}", ephemeral=True)


@bot.tree.command(name="warn", description="手动向用户发出一次警告 (累计达到阈值会被踢出)。")
@app_commands.describe(user="要警告的用户。", reason="警告的原因 (可选)。")
@app_commands.checks.has_permissions(kick_members=True) # Or moderate_members
async def slash_warn(interaction: discord.Interaction, user: discord.Member, reason: str = "未指定原因"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    if user.bot: await interaction.followup.send("❌ 不能警告机器人。", ephemeral=True); return
    if user == author: await interaction.followup.send("❌ 你不能警告自己。", ephemeral=True); return
    if isinstance(author, discord.Member) and author.id != guild.owner_id:
        if user.top_role >= author.top_role: await interaction.followup.send(f"🚫 你无法警告层级等于或高于你的成员 ({user.mention})。", ephemeral=True); return

    # 【核心修复】使用 guild.id 作为第一层键
    guild_warnings = user_warnings.setdefault(guild.id, {})
    guild_warnings[user.id] = guild_warnings.get(user.id, 0) + 1
    warning_count = guild_warnings[user.id]

    print(f"[审核操作] 用户 {author} 手动警告了用户 {user}。原因: {reason}。新警告次数: {warning_count}/{KICK_THRESHOLD}")

    embed = discord.Embed(color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"由 {author.display_name} 发出警告", icon_url=author.display_avatar.url)
    embed.add_field(name="被警告用户", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="警告原因", value=reason, inline=False)
    embed.add_field(name="当前警告次数", value=f"**{warning_count}** / {KICK_THRESHOLD}", inline=False)

    kick_performed = False
    if warning_count >= KICK_THRESHOLD:
        embed.title = "🚨 警告已达上限 - 用户已被踢出 🚨"
        embed.color = discord.Color.red()
        embed.add_field(name="处理措施", value="已自动踢出服务器", inline=False)
        print(f"   - 用户 {user.name} 因手动警告达到踢出阈值。")
        bot_member = guild.me
        can_kick = bot_member.guild_permissions.kick_members and (bot_member.top_role > user.top_role or bot_member == guild.owner)
        if can_kick:
            kick_reason_warn = f"自动踢出：因累计达到 {KICK_THRESHOLD} 次警告 (最后一次由 {author.display_name} 手动发出，原因：{reason})。"
            try:
                try: await user.send(f"由于在服务器 **{guild.name}** 中累计达到 {KICK_THRESHOLD} 次警告（最后由 {author.display_name} 发出警告，原因：{reason}），你已被踢出。")
                except Exception as dm_err: print(f"   - 无法向用户 {user.name} 发送踢出私信 (手动警告): {dm_err}")
                await user.kick(reason=kick_reason_warn)
                print(f"   - 已成功踢出用户 {user.name} (手动警告达到上限)。")
                kick_performed = True
                guild_warnings[user.id] = 0 # 【核心修复】重置正确的警告记录
                embed.add_field(name="踢出状态", value="✅ 成功", inline=False)
            except discord.Forbidden: embed.add_field(name="踢出状态", value="❌ 失败 (权限不足)", inline=False); print(f"   - 踢出用户 {user.name} 失败：机器人权限不足。")
            except Exception as kick_err: embed.add_field(name="踢出状态", value=f"❌ 失败 ({kick_err})", inline=False); print(f"   - 踢出用户 {user.name} 时发生未知错误: {kick_err}")
        else:
             embed.add_field(name="踢出状态", value="❌ 失败 (权限/层级不足)", inline=False); print(f"   - 无法踢出用户 {user.name}：机器人权限不足或层级不够。")
             if MOD_ALERT_ROLE_IDS: embed.add_field(name="提醒", value=f"<@&{MOD_ALERT_ROLE_IDS[0]}> 请手动处理！", inline=False)

    else:
        embed.title = "⚠️ 手动警告已发出 ⚠️"
        embed.add_field(name="后续处理", value=f"该用户再收到 {KICK_THRESHOLD - warning_count} 次警告将被自动踢出。", inline=False)

    await interaction.followup.send(embed=embed)
    await send_to_public_log(guild, embed, log_type="Manual Warn")


@bot.tree.command(name="unwarn", description="移除用户的一次警告记录。")
@app_commands.describe(user="要移除其警告的用户。", reason="移除警告的原因 (可选)。")
@app_commands.checks.has_permissions(kick_members=True) # Or moderate_members
async def slash_unwarn(interaction: discord.Interaction, user: discord.Member, reason: str = "管理员酌情处理"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    if user.bot: await interaction.followup.send("❌ 机器人没有警告记录。", ephemeral=True); return

    # 【核心修复】使用 guild.id 作为第一层键
    guild_warnings = user_warnings.setdefault(guild.id, {})
    current_warnings = guild_warnings.get(user.id, 0)
    
    if current_warnings <= 0: 
        await interaction.followup.send(f"ℹ️ 用户 {user.mention} 当前没有警告记录可移除。", ephemeral=True)
        return

    guild_warnings[user.id] = current_warnings - 1
    new_warning_count = guild_warnings[user.id]
    
    print(f"[审核操作] 用户 {author} 移除了用户 {user} 的一次警告。原因: {reason}。新警告次数: {new_warning_count}/{KICK_THRESHOLD}")

    embed = discord.Embed(title="✅ 警告已移除 ✅", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"由 {author.display_name} 操作", icon_url=author.display_avatar.url)
    embed.add_field(name="用户", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="移除原因", value=reason, inline=False)
    embed.add_field(name="新的警告次数", value=f"**{new_warning_count}** / {KICK_THRESHOLD}", inline=False)

    await send_to_public_log(guild, embed, log_type="Manual Unwarn")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="announce", description="以嵌入式消息格式发送服务器公告。")
@app_commands.describe(
    channel="要发送公告的目标文字频道。",
    title="公告的醒目标题。",
    message="公告的主要内容 (使用 '\\n' 来换行)。",
    ping_role="(可选) 要在公告前提及的身份组。",
    image_url="(可选) 要附加在公告底部的图片 URL (必须是 http/https 链接)。",
    color="(可选) 嵌入消息左侧边框的颜色 (十六进制，如 '#3498db' 或 '0x3498db')。"
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
async def slash_announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
    ping_role: Optional[discord.Role] = None,
    image_url: Optional[str] = None,
    color: Optional[str] = None):

    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=True)
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return

    embed_color = discord.Color.blue()
    valid_image = None
    validation_warnings = []

    if color:
        try: embed_color = discord.Color(int(color.lstrip('#').lstrip('0x'), 16))
        except ValueError: validation_warnings.append(f"⚠️ 无效颜色代码'{color}'"); embed_color = discord.Color.blue()

    if image_url:
        if image_url.startswith(('http://', 'https://')):
            valid_image_check = False
            try:
                if AIOHTTP_AVAILABLE and hasattr(bot, 'http_session') and bot.http_session:
                    async with bot.http_session.head(image_url, timeout=5, allow_redirects=True) as head_resp:
                        if head_resp.status == 200 and 'image' in head_resp.headers.get('Content-Type', '').lower(): valid_image_check = True
                        elif head_resp.status != 200: validation_warnings.append(f"⚠️ 图片URL无法访问({head_resp.status})")
                        else: validation_warnings.append(f"⚠️ URL内容非图片({head_resp.headers.get('Content-Type','')})")
                else: # Fallback using requests (blocking)
                    loop = asyncio.get_event_loop()
                    head_resp = await loop.run_in_executor(None, lambda: requests.head(image_url, timeout=5, allow_redirects=True))
                    if head_resp.status_code == 200 and 'image' in head_resp.headers.get('Content-Type', '').lower(): valid_image_check = True
                    elif head_resp.status_code != 200: validation_warnings.append(f"⚠️ 图片URL无法访问({head_resp.status_code})")
                    else: validation_warnings.append(f"⚠️ URL内容非图片({head_resp.headers.get('Content-Type','')})")

                if valid_image_check: valid_image = image_url
            except Exception as req_err: validation_warnings.append(f"⚠️ 验证图片URL时出错:{req_err}")
        else: validation_warnings.append("⚠️ 图片URL格式无效")

    if validation_warnings:
        warn_text = "\n".join(validation_warnings)
        try: await interaction.followup.send(f"**公告参数警告:**\n{warn_text}\n公告仍将尝试发送。", ephemeral=True)
        except: pass # Ignore if interaction expires

    embed = discord.Embed(title=f"**{title}**", description=message.replace('\\n', '\n'), color=embed_color, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"由 {author.display_name} 发布 | {guild.name}", icon_url=guild.icon.url if guild.icon else bot.user.display_avatar.url)
    if valid_image: embed.set_image(url=valid_image)

    ping_content = None
    if ping_role:
        if ping_role.mentionable or (isinstance(author, discord.Member) and author.guild_permissions.mention_everyone): ping_content = ping_role.mention
        else:
             warn_msg = f"⚠️ 身份组 {ping_role.name} 不可提及。公告中不会实际提及。"
             try: await interaction.followup.send(warn_msg, ephemeral=True)
             except: pass
             ping_content = f"(提及 **{ping_role.name}**)"

    try:
        target_perms = channel.permissions_for(guild.me)
        if not target_perms.send_messages or not target_perms.embed_links:
            await interaction.followup.send(f"❌ 发送失败：机器人缺少在频道 {channel.mention} 发送消息或嵌入链接的权限。", ephemeral=True)
            return
        await channel.send(content=ping_content, embed=embed)
        await interaction.followup.send(f"✅ 公告已成功发送到频道 {channel.mention}！", ephemeral=True)
        print(f"[公告] 用户 {author} 在频道 #{channel.name} 发布了公告: '{title}'")
    except discord.Forbidden: await interaction.followup.send(f"❌ 发送失败：机器人缺少在频道 {channel.mention} 发送消息或嵌入链接的权限。", ephemeral=True)
    except Exception as e: print(f"执行 /announce 时出错: {e}"); await interaction.followup.send(f"❌ 发送公告时发生未知错误: {e}", ephemeral=True)
    # --- (在这里或类似位置添加以下代码) ---

@bot.tree.command(name="notify_member", description="通过机器人向指定成员发送私信 (需要管理服务器权限)。")
@app_commands.describe(
    member="要接收私信的成员。",
    message_content="要发送的私信内容。"
)
@app_commands.checks.has_permissions(manage_guild=True) # 只有拥有“管理服务器”权限的用户才能使用
async def slash_notify_member(interaction: discord.Interaction, member: discord.Member, message_content: str):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=True) # 回复设为临时，仅执行者可见

    if not guild:
        await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True)
        return
    if member.bot:
        await interaction.followup.send("❌ 不能向机器人发送私信。", ephemeral=True)
        return
    if member == author:
        await interaction.followup.send("❌ 你不能给自己发送私信。", ephemeral=True)
        return
    if len(message_content) > 1900: # Discord DM 限制为 2000，留一些余量
        await interaction.followup.send("❌ 消息内容过长 (最多约1900字符)。", ephemeral=True)
        return

    # 创建私信的 Embed 消息
    dm_embed = discord.Embed(
        title=f"来自服务器 {guild.name} 管理员的消息",
        description=message_content,
        color=discord.Color.blue(), # 你可以自定义颜色
        timestamp=discord.utils.utcnow()
    )
    dm_embed.set_footer(text=f"发送者: {author.display_name}")
    if author.avatar: # 如果发送者有头像，则使用
        dm_embed.set_author(name=f"来自 {author.display_name}", icon_url=author.display_avatar.url)
    else:
        dm_embed.set_author(name=f"来自 {author.display_name}")

    try:
        await member.send(embed=dm_embed)
        await interaction.followup.send(f"✅ 已成功向 {member.mention} 发送私信。", ephemeral=True)
        print(f"[通知] 用户 {author} ({author.id}) 通过机器人向 {member.name} ({member.id}) 发送了私信。")

        # （可选）在公共日志频道记录操作 (不记录具体内容，保护隐私)
        log_embed_public = discord.Embed(
            title="📬 成员私信已发送",
            description=f"管理员通过机器人向成员发送了一条私信。",
            color=discord.Color.blurple(), # 和私信颜色区分
            timestamp=discord.utils.utcnow()
        )
        log_embed_public.add_field(name="执行管理员", value=author.mention, inline=True)
        log_embed_public.add_field(name="接收成员", value=member.mention, inline=True)
        log_embed_public.set_footer(text=f"执行者 ID: {author.id} | 接收者 ID: {member.id}")
        await send_to_public_log(guild, log_embed_public, log_type="Member DM Sent")

    except discord.Forbidden:
        await interaction.followup.send(f"❌ 无法向 {member.mention} 发送私信。可能原因：该用户关闭了来自服务器成员的私信，或屏蔽了机器人。", ephemeral=True)
        print(f"[通知失败] 无法向 {member.name} ({member.id}) 发送私信 (Forbidden)。")
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ 发送私信给 {member.mention} 时发生网络错误: {e}", ephemeral=True)
        print(f"[通知失败] 发送私信给 {member.name} ({member.id}) 时发生HTTP错误: {e}")
    except Exception as e:
        await interaction.followup.send(f"❌ 发送私信时发生未知错误: {e}", ephemeral=True)
        print(f"[通知失败] 发送私信给 {member.name} ({member.id}) 时发生未知错误: {e}")
        # ... (你现有的 slash_notify_member 指令的完整代码) ...
    except Exception as e:
        await interaction.followup.send(f"❌ 发送私信时发生未知错误: {e}", ephemeral=True)
        print(f"[通知失败] 发送私信给 {member.name} ({member.id}) 时发生未知错误: {e}")


# ↓↓↓↓ 在这里粘贴新的 ping 指令的完整代码 ↓↓↓↓
@bot.tree.command(name="ping", description="检查机器人与 Discord 服务器的延迟。")
async def slash_ping(interaction: discord.Interaction):
    """显示机器人的延迟信息。"""
    # defer=True 使得交互立即得到响应，机器人有更多时间处理
    # ephemeral=True 使得这条消息只有发送者可见
    await interaction.response.defer(ephemeral=True)

    # 1. WebSocket 延迟 (机器人与Discord网关的连接延迟)
    websocket_latency = bot.latency
    websocket_latency_ms = round(websocket_latency * 1000)

    # 2. API 延迟 (发送一条消息并测量所需时间)
    # 我们将发送初始回复，然后编辑它来计算延迟
    start_time = time.monotonic()
    # 发送一个占位消息，后续会编辑它
    # 注意：因为我们已经 defer() 了，所以第一次发送必须用 followup()
    message_to_edit = await interaction.followup.send("正在 Ping API...", ephemeral=True)
    end_time = time.monotonic()
    api_latency_ms = round((end_time - start_time) * 1000)


    # 创建最终的 Embed 消息
    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green(), # 你可以自定义颜色
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📡 WebSocket 延迟", value=f"{websocket_latency_ms} ms", inline=True)
    embed.add_field(name="↔️ API 消息延迟", value=f"{api_latency_ms} ms", inline=True)
    embed.set_footer(text=f"请求者: {interaction.user.display_name}")

    # 编辑之前的占位消息，显示完整的延迟信息
    await message_to_edit.edit(content=None, embed=embed)

    print(f"[状态] 用户 {interaction.user} 执行了 /ping。WebSocket: {websocket_latency_ms}ms, API: {api_latency_ms}ms")
# ↑↑↑↑ 新的 ping 指令代码结束 ↑↑↑↑

# ... (在你现有的 /ping 命令或其他独立斜杠命令定义之后) ...

# --- 新增：AI 对话功能指令组 ---
ai_group = app_commands.Group(name="ai", description="与 DeepSeek AI 交互的指令")

# --- Command: /ai setup_dep_channel ---
@ai_group.command(name="setup_dep_channel", description="[管理员] 将当前频道或指定频道设置为AI直接对话频道")
@app_commands.describe(
    channel="要设置为AI对话的文字频道 (默认为当前频道)",
    model_id="(可选)为此频道指定AI模型 (默认使用通用对话模型)",
    system_prompt="(可选)为此频道设置一个系统级提示 (AI会优先考虑)"
)
@app_commands.choices(model_id=[
    app_commands.Choice(name=desc, value=mid) for mid, desc in AVAILABLE_AI_DIALOGUE_MODELS.items()
])
@app_commands.checks.has_permissions(manage_guild=True) 
async def ai_setup_dep_channel(interaction: discord.Interaction, 
                               channel: Optional[discord.TextChannel] = None, 
                               model_id: Optional[app_commands.Choice[str]] = None,
                               system_prompt: Optional[str] = None):
    target_channel = channel if channel else interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("❌ 目标必须是一个文字频道。", ephemeral=True)
        return

    chosen_model_id = model_id.value if model_id else DEFAULT_AI_DIALOGUE_MODEL
    
    history_key_for_channel = f"ai_dep_channel_{target_channel.id}"
    ai_dep_channels_config[target_channel.id] = {
        "model": chosen_model_id,
        "system_prompt": system_prompt,
        "history_key": history_key_for_channel
    }
    if history_key_for_channel not in conversation_histories:
        conversation_histories[history_key_for_channel] = deque(maxlen=MAX_AI_HISTORY_TURNS * 2) 

    print(f"[AI SETUP] Channel {target_channel.name} ({target_channel.id}) configured for AI. Model: {chosen_model_id}, SysPrompt: {system_prompt is not None}")
    await interaction.response.send_message(
        f"✅ 频道 {target_channel.mention} 已成功设置为 AI 直接对话频道！\n"
        f"- 使用模型: `{chosen_model_id}`\n"
        f"- 系统提示: `{'已设置' if system_prompt else '未使用'}`\n"
        f"用户现在可以在此频道直接向 AI提问。",
        ephemeral=True
    )

@ai_setup_dep_channel.error
async def ai_setup_dep_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 你需要“管理服务器”权限才能设置AI频道。", ephemeral=True)
    else:
        print(f"[AI SETUP ERROR] /ai setup_dep_channel: {error}")
        await interaction.response.send_message(f"设置AI频道时发生错误: {type(error).__name__}", ephemeral=True)

# --- Command: /ai kb_add ---
@ai_group.command(name="kb_add", description="[管理员] 添加一条知识到服务器的AI知识库")
@app_commands.describe(content="要添加的知识内容 (例如：服务器规则、常见问题解答)")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_kb_add(interaction: discord.Interaction, content: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    if len(content) > MAX_KB_ENTRY_LENGTH: # 使用之前定义的常量
        await interaction.response.send_message(f"❌ 内容过长，单个知识条目不能超过 {MAX_KB_ENTRY_LENGTH} 个字符。", ephemeral=True)
        return
    if len(content.strip()) < 10: 
        await interaction.response.send_message(f"❌ 内容过短，请输入有意义的知识条目 (至少10字符)。", ephemeral=True)
        return

    # 确保 guild_knowledge_bases 已在文件顶部定义
    guild_kb = guild_knowledge_bases.setdefault(guild.id, [])
    if len(guild_kb) >= MAX_KB_ENTRIES_PER_GUILD: # 使用之前定义的常量
        await interaction.response.send_message(f"❌ 服务器知识库已满 ({len(guild_kb)}/{MAX_KB_ENTRIES_PER_GUILD} 条)。请先移除一些旧条目。", ephemeral=True)
        return

    guild_kb.append(content.strip())
    print(f"[AI KB] Guild {guild.id}: User {interaction.user.id} added entry. New count: {len(guild_kb)}")
    await interaction.response.send_message(f"✅ 已成功添加知识条目到服务器AI知识库 (当前共 {len(guild_kb)} 条)。\n内容预览: ```{content[:150]}{'...' if len(content)>150 else ''}```", ephemeral=True)

# --- Command: /ai kb_list ---
@ai_group.command(name="kb_list", description="[管理员] 列出当前服务器AI知识库中的条目")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_kb_list(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    guild_kb = guild_knowledge_bases.get(guild.id, [])
    if not guild_kb:
        await interaction.response.send_message("ℹ️ 当前服务器的AI知识库是空的。", ephemeral=True)
        return

    embed = discord.Embed(title=f"服务器AI知识库 - {guild.name}", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    
    description_parts = [f"当前共有 **{len(guild_kb)}** 条知识。显示前 {min(len(guild_kb), MAX_KB_DISPLAY_ENTRIES)} 条：\n"] # 使用常量
    for i, entry in enumerate(guild_kb[:MAX_KB_DISPLAY_ENTRIES]): # 使用常量
        preview = entry[:80] + ('...' if len(entry) > 80 else '') 
        description_parts.append(f"**{i+1}.** ```{preview}```")
    
    if len(guild_kb) > MAX_KB_DISPLAY_ENTRIES: # 使用常量
        description_parts.append(f"\n*还有 {len(guild_kb) - MAX_KB_DISPLAY_ENTRIES} 条未在此处完整显示。*")
    
    embed.description = "\n".join(description_parts)
    embed.set_footer(text=f"使用 /ai kb_remove [序号] 来移除条目。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Command: /ai kb_remove ---
@ai_group.command(name="kb_remove", description="[管理员] 从服务器AI知识库中移除指定序号的条目")
@app_commands.describe(index="要移除的知识条目的序号 (从 /ai kb_list 中获取)")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_kb_remove(interaction: discord.Interaction, index: int):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    guild_kb = guild_knowledge_bases.get(guild.id, [])
    if not guild_kb:
        await interaction.response.send_message("ℹ️ 当前服务器的AI知识库是空的，无法移除。", ephemeral=True)
        return

    if not (1 <= index <= len(guild_kb)):
        await interaction.response.send_message(f"❌ 无效的序号。请输入 1 到 {len(guild_kb)} 之间的数字。", ephemeral=True)
        return

    removed_entry = guild_kb.pop(index - 1) 
    print(f"[AI KB] Guild {guild.id}: User {interaction.user.id} removed entry #{index}. New count: {len(guild_kb)}")
    await interaction.response.send_message(f"✅ 已成功从知识库中移除第 **{index}** 条知识。\n被移除内容预览: ```{removed_entry[:150]}{'...' if len(removed_entry)>150 else ''}```", ephemeral=True)

# --- Command: /ai kb_clear ---
@ai_group.command(name="kb_clear", description="[管理员] 清空当前服务器的所有AI知识库条目")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_kb_clear(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    if guild.id in guild_knowledge_bases and guild_knowledge_bases[guild.id]:
        count_cleared = len(guild_knowledge_bases[guild.id])
        guild_knowledge_bases[guild.id] = [] 
        print(f"[AI KB] Guild {guild.id}: User {interaction.user.id} cleared all {count_cleared} knowledge base entries.")
        await interaction.response.send_message(f"✅ 已成功清空服务器AI知识库中的全部 **{count_cleared}** 条知识。", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ 当前服务器的AI知识库已经是空的。", ephemeral=True)
# --- Command: /ai clear_dep_history ---
@ai_group.command(name="clear_dep_history", description="清除当前AI直接对话频道的对话历史")
async def ai_clear_dep_history(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in ai_dep_channels_config:
        await interaction.response.send_message("❌ 此频道未被设置为 AI 直接对话频道。", ephemeral=True)
        return

    config = ai_dep_channels_config[channel_id]
    history_key = config.get("history_key")

    if history_key and history_key in conversation_histories:
        conversation_histories[history_key].clear()
        print(f"[AI HISTORY] Cleared history for DEP channel {channel_id} (Key: {history_key}) by {interaction.user.id}")
        await interaction.response.send_message("✅ 当前 AI 对话频道的历史记录已清除。", ephemeral=False) 
    else:
        await interaction.response.send_message("ℹ️ 未找到此频道的历史记录或历史键配置错误。", ephemeral=True)

# --- Command: /ai create_private_chat ---
@ai_group.command(name="create_private_chat", description="创建一个与AI的私密聊天频道")
@app_commands.describe(
    model_id="(可选)为私聊指定AI模型",
    initial_question="(可选)创建频道后直接向AI提出的第一个问题"
)
@app_commands.choices(model_id=[
    app_commands.Choice(name=desc, value=mid) for mid, desc in AVAILABLE_AI_DIALOGUE_MODELS.items()
])
async def ai_create_private_chat(interaction: discord.Interaction, 
                                 model_id: Optional[app_commands.Choice[str]] = None,
                                 initial_question: Optional[str] = None):
    user = interaction.user
    guild = interaction.guild
    if not guild: 
        await interaction.response.send_message("此命令似乎不在服务器中执行。", ephemeral=True)
        return

    for chat_id_key, chat_info_val in list(active_private_ai_chats.items()): # Iterate over a copy for safe deletion
        if chat_info_val.get("user_id") == user.id and chat_info_val.get("guild_id") == guild.id:
            existing_channel = guild.get_channel(chat_info_val.get("channel_id"))
            if existing_channel:
                await interaction.response.send_message(f"⚠️ 你已经有一个开启的AI私聊频道：{existing_channel.mention}。\n请先使用 `/ai close_private_chat` 关闭它。", ephemeral=True)
                return
            else: 
                print(f"[AI PRIVATE] Cleaning up stale private chat record for user {user.id}, channel ID {chat_info_val.get('channel_id')}")
                if chat_info_val.get("history_key") in conversation_histories:
                    del conversation_histories[chat_info_val.get("history_key")]
                if chat_id_key in active_private_ai_chats: # chat_id_key is channel_id
                     del active_private_ai_chats[chat_id_key]


    chosen_model_id = model_id.value if model_id else DEFAULT_AI_DIALOGUE_MODEL
    
    await interaction.response.defer(ephemeral=True) 

    category_name_config = "AI Private Chats" # Name for the category
    category = discord.utils.get(guild.categories, name=category_name_config) 
    if not category:
        try:
            bot_member = guild.me
            bot_perms_in_cat = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, view_channel=True)
            everyone_perms_in_cat = discord.PermissionOverwrite(read_messages=False, view_channel=False)
            category_overwrites = {
                guild.me: bot_perms_in_cat,
                guild.default_role: everyone_perms_in_cat
            }
            category = await guild.create_category(category_name_config, overwrites=category_overwrites, reason="Category for AI Private Chats")
            print(f"[AI PRIVATE] Created category '{category_name_config}' in guild {guild.id}")
        except discord.Forbidden:
            print(f"[AI PRIVATE ERROR] Failed to create '{category_name_config}' category in {guild.id}: Bot lacks permissions.")
            await interaction.followup.send("❌ 创建私聊频道失败：机器人无法创建所需分类。请检查机器人是否有“管理频道”权限。", ephemeral=True)
            return
        except Exception as e:
            print(f"[AI PRIVATE ERROR] Error creating category: {e}")
            await interaction.followup.send(f"❌ 创建私聊频道失败：{e}", ephemeral=True)
            return

    channel_name = f"ai-{user.name[:20].lower().replace(' ','-')}-{user.id % 1000}" # Ensure lowercase and no spaces for channel name
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True, manage_messages=True) 
    }

    new_channel = None # Define before try block
    try:
        new_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites, topic=f"AI私聊频道，创建者: {user.display_name}, 模型: {chosen_model_id}")
        
        history_key_private = f"ai_private_chat_{new_channel.id}"
        active_private_ai_chats[new_channel.id] = { # Use new_channel.id as the key
            "user_id": user.id,
            "model": chosen_model_id,
            "history_key": history_key_private,
            "guild_id": guild.id,
            "channel_id": new_channel.id 
        }
        if history_key_private not in conversation_histories:
            conversation_histories[history_key_private] = deque(maxlen=MAX_AI_HISTORY_TURNS * 2)

        print(f"[AI PRIVATE] Created private AI channel {new_channel.name} ({new_channel.id}) for user {user.id}. Model: {chosen_model_id}")
        
        initial_message_content = (
            f"你好 {user.mention}！这是一个你的专属AI私聊频道。\n"
            f"- 当前使用模型: `{chosen_model_id}`\n"
            f"- 直接在此输入你的问题即可与AI对话。\n"
            f"- 使用 `/ai close_private_chat` 可以关闭此频道。\n"
            f"Enjoy! ✨"
        )
        await new_channel.send(initial_message_content)
        await interaction.followup.send(f"✅ 你的AI私聊频道已创建：{new_channel.mention}", ephemeral=True)

        if initial_question: 
            print(f"[AI PRIVATE] Sending initial question from {user.id} to {new_channel.id}: {initial_question}")
            # Simulate a message object for handle_ai_dialogue
            # This is a bit hacky, a cleaner way might be to directly call API and format
            class MinimalMessage:
                def __init__(self, author, channel, content, guild):
                    self.author = author
                    self.channel = channel
                    self.content = content
                    self.guild = guild
                    self.attachments = [] # Assume no attachments for initial question
                    self.stickers = []  # Assume no stickers
                    # Add other attributes if your handle_ai_dialogue strict checks them
                    self.id = discord.utils.time_snowflake(discord.utils.utcnow()) # Fake ID
                    self.interaction = None # Not from an interaction

            mock_message_obj = MinimalMessage(author=user, channel=new_channel, content=initial_question, guild=guild)
            async with new_channel.typing():
                await handle_ai_dialogue(mock_message_obj, is_private_chat=True)

    except discord.Forbidden:
        print(f"[AI PRIVATE ERROR] Failed to create private channel for {user.id}: Bot lacks permissions.")
        await interaction.followup.send("❌ 创建私聊频道失败：机器人权限不足。", ephemeral=True)
        if new_channel and new_channel.id in active_private_ai_chats: # Clean up if entry was made
            del active_private_ai_chats[new_channel.id]
    except Exception as e:
        print(f"[AI PRIVATE ERROR] Error creating private channel: {e}")
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"❌ 创建私聊频道时发生未知错误: {type(e).__name__}", ephemeral=True)
        if new_channel and new_channel.id in active_private_ai_chats: # Clean up if entry was made
            del active_private_ai_chats[new_channel.id]


# --- Command: /ai close_private_chat ---
@ai_group.command(name="close_private_chat", description="关闭你创建的AI私密聊天频道")
async def ai_close_private_chat(interaction: discord.Interaction):
    channel = interaction.channel
    user = interaction.user

    if not (isinstance(channel, discord.TextChannel) and channel.id in active_private_ai_chats):
        await interaction.response.send_message("❌ 此命令只能在你创建的AI私密聊天频道中使用。", ephemeral=True)
        return

    chat_info = active_private_ai_chats.get(channel.id)
    if not chat_info or chat_info.get("user_id") != user.id:
        await interaction.response.send_message("❌ 你不是此AI私密聊天频道的创建者。", ephemeral=True)
        return

    # Deferring here might be an issue if channel is deleted quickly
    # await interaction.response.send_message("⏳ 频道准备关闭...", ephemeral=True) # Ephemeral response
    
    history_key_to_clear = chat_info.get("history_key")
    if history_key_to_clear and history_key_to_clear in conversation_histories:
        del conversation_histories[history_key_to_clear]
        print(f"[AI PRIVATE] Cleared history for private chat {channel.id} (Key: {history_key_to_clear}) during closure.")
    
    if channel.id in active_private_ai_chats:
        del active_private_ai_chats[channel.id]
        print(f"[AI PRIVATE] Removed active private chat entry for channel {channel.id}")

    try:
        # Send confirmation in channel before deleting
        await channel.send(f"此AI私密聊天频道由 {user.mention} 请求关闭，将在大约 5 秒后删除。")
        # Respond to interaction *before* sleep and delete
        await interaction.response.send_message("频道关闭请求已收到，将在几秒后删除。",ephemeral=True)
        await asyncio.sleep(5)
        await channel.delete(reason=f"AI Private Chat closed by owner {user.name}")
        print(f"[AI PRIVATE] Successfully deleted private AI channel {channel.name} ({channel.id})")
        try: # Attempt to DM user as a final confirmation
            await user.send(f"你创建的AI私聊频道 `#{channel.name}` 已成功关闭和删除。")
        except discord.Forbidden:
            print(f"[AI PRIVATE] Could not DM user {user.id} about channel closure.")
    except discord.NotFound:
        print(f"[AI PRIVATE] Channel {channel.id} already deleted before final action.")
        if not interaction.response.is_done(): # If we haven't responded yet
             await interaction.response.send_message("频道似乎已被删除。",ephemeral=True)
    except discord.Forbidden:
        print(f"[AI PRIVATE ERROR] Bot lacks permission to delete channel {channel.id} or send messages in it.")
        if not interaction.response.is_done():
             await interaction.response.send_message("❌ 关闭频道时出错：机器人权限不足。", ephemeral=True)
    except Exception as e:
        print(f"[AI PRIVATE ERROR] Error closing private chat {channel.id}: {e}")
        if not interaction.response.is_done():
             await interaction.response.send_message(f"❌ 关闭频道时发生未知错误: {type(e).__name__}", ephemeral=True)


# 将新的指令组添加到 bot tree
# 这个应该在你的 on_ready 或者 setup_hook 中进行一次性添加，或者在文件末尾（如果 bot.tree 已经定义）
# 为了确保它被添加，我们暂时放在这里，但理想位置是在所有指令定义完后，机器人启动前。
# 如果你已经在其他地方有 bot.tree.add_command(manage_group) 等，就和它们放在一起。
# bot.tree.add_command(ai_group) # 我们会在文件末尾统一添加

# --- (在你所有指令组如 manage_group, voice_group, ai_group 定义完成之后，但在 bot.tree.add_command 系列语句之前) ---

# --- 充值系统指令组 ---
recharge_group = app_commands.Group(name="recharge", description=f"进行{ECONOMY_CURRENCY_NAME}充值操作。")

@recharge_group.command(name="request", description=f"请求充值{ECONOMY_CURRENCY_NAME}并获取支付二维码。")
@app_commands.describe(
    amount=f"您希望充值的金额 (单位: 元，例如 10.00 表示10元)。"
)
async def recharge_request_cmd(
    interaction: discord.Interaction,
    amount: app_commands.Range[float, MIN_RECHARGE_AMOUNT, MAX_RECHARGE_AMOUNT] 
):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user = interaction.user

    if not guild: 
        await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True)
        return

    if not ECONOMY_ENABLED:
        await interaction.followup.send(f"经济系统当前未启用，无法处理{ECONOMY_CURRENCY_NAME}充值请求。", ephemeral=True)
        return

    if not ALIPAY_SDK_AVAILABLE or not alipay_client_config:
        await interaction.followup.send("❌ 支付宝支付功能当前不可用，请联系管理员 (SDK配置问题)。", ephemeral=True)
        logging.error("Alipay SDK not available or client_config not initialized for /recharge request.")
        return
    
    # 详细检查配置是否仍为占位符
    is_config_placeholder = False
    if not ALIPAY_APP_ID or "请替换" in ALIPAY_APP_ID: is_config_placeholder = True
    if not APP_PRIVATE_KEY_STR or "请在这里粘贴您" in APP_PRIVATE_KEY_STR: is_config_placeholder = True
    if not ALIPAY_NOTIFY_URL or ("gjteampiaoj.ggff.net/alipay/notify" == ALIPAY_NOTIFY_URL and "请替换" in ALIPAY_NOTIFY_URL.lower()): is_config_placeholder = True 
    if not ALIPAY_PUBLIC_KEY_STR_FOR_SDK or "请替换" in ALIPAY_PUBLIC_KEY_STR_FOR_SDK: is_config_placeholder = True
    
    if is_config_placeholder:
        logging.critical(f"支付宝关键配置包含占位符或不完整，无法发起支付。 User: {user.id}")
        await interaction.followup.send("❌ 支付配置错误，请联系管理员查看机器人后台日志以获取详细信息。", ephemeral=True)
        return

    # 1. 生成唯一的内部订单号
    out_trade_no = f"GJTRC-{guild.id}-{user.id}-{int(time.time()*1000)}"
    logging.info(f"[Alipay Recharge] User {user.name}({user.id}) in Guild {guild.name}({guild.id}) requested "
                 f"to recharge {amount:.2f} CNY. Generated out_trade_no: {out_trade_no}")

    # 2. 准备回传参数
    passback_content = {
        "discord_user_id": str(user.id), 
        "discord_guild_id": str(guild.id), 
        "expected_amount_cny": f"{amount:.2f}", # 存储用户请求的CNY金额
        "out_trade_no_ref": out_trade_no 
    }
    passback_params_json_str = json.dumps(passback_content)
    passback_params_encoded = urllib.parse.quote_plus(passback_params_json_str)

    # 【关键】在数据库创建待支付的充值请求记录
    # 您需要在 database.py 中实现 db_create_initial_recharge_request
    # 它应该返回新创建的请求ID (例如 internal_db_request_id) 或 None
    internal_db_request_id = database.db_create_initial_recharge_request(
        guild_id=guild.id,
        user_id=user.id,
        requested_cny_amount=float(amount), # 用户请求的CNY金额
        out_trade_no=out_trade_no,
        passback_params_json_str=passback_params_json_str # 存储未编码的JSON，方便DB查看
    )
    if not internal_db_request_id:
        logging.error(f"Failed to create initial recharge request in DB for out_trade_no: {out_trade_no}, user: {user.id}")
        await interaction.followup.send("❌ 创建充值请求时发生内部错误，请稍后再试或联系管理员。", ephemeral=True)
        return
    logging.info(f"Initial recharge request record (DB request_id: {internal_db_request_id}) created for out_trade_no: {out_trade_no}")

    # 3. 调用支付宝“当面付”预创建订单接口
    current_client = DefaultAlipayClient(alipay_client_config=alipay_client_config, logger=alipay_logger)

    model = AlipayTradePrecreateRequest()
    model.notify_url = ALIPAY_NOTIFY_URL 
    model.biz_content = {
        "out_trade_no": out_trade_no,
        "total_amount": f"{amount:.2f}", 
        "subject": f"充值{ECONOMY_CURRENCY_NAME} - {guild.name} ({user.name})", # 商品标题
        "timeout_express": "5m", 
        "passback_params": passback_params_encoded
    }
    
    qr_code_url_from_alipay = None
    alipay_api_error_msg = None

    try:
        logging.info(f"Calling Alipay API (alipay.trade.precreate) for out_trade_no: {out_trade_no}")
        response_str = current_client.execute(model)
        
        response_data = json.loads(response_str)
        alipay_resp_data = response_data.get("alipay_trade_precreate_response", {})
        
        if alipay_resp_data.get("code") == "10000":
            qr_code_url_from_alipay = alipay_resp_data.get("qr_code")
            logging.info(f"Successfully created Alipay precreate order for {out_trade_no}.")
        else:
            sub_code = alipay_resp_data.get("sub_code", "N/A")
            sub_msg = alipay_resp_data.get("sub_msg", "未知业务错误")
            # 检查是否是订单已存在且已支付的情况
            if sub_code == "ACQ.TRADE_HAS_SUCCESS":
                 alipay_api_error_msg = "此订单已成功支付，请勿重复操作。如未到账请联系管理员。"
                 logging.warning(f"Alipay API indicated trade already successful for {out_trade_no}: {sub_msg}")
            else:
                alipay_api_error_msg = f"支付宝业务错误: Code={alipay_resp_data.get('code')}, SubCode={sub_code}, Msg={sub_msg}"
            logging.error(f"Alipay API business error for {out_trade_no}: {alipay_api_error_msg}")


    except Exception as e_alipay_api:
        alipay_api_error_msg = f"调用支付宝API时发生程序异常: {type(e_alipay_api).__name__}"
        logging.error(f"Exception calling Alipay API for {out_trade_no}: {e_alipay_api}", exc_info=True)

    if qr_code_url_from_alipay:
        try:
            qr_img_obj = qrcode.make(qr_code_url_from_alipay)
            img_byte_arr = io.BytesIO()
            qr_img_obj.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            qr_file = discord.File(fp=img_byte_arr, filename="alipay_recharge_qr.png")

            embed = discord.Embed(
                title=f"{ECONOMY_CURRENCY_SYMBOL} 请扫描二维码支付",
                description=(
                    f"请使用支付宝扫描下方二维码支付 **{amount:.2f} 元** 以充值 {ECONOMY_CURRENCY_NAME}。\n\n"
                    f"**内部订单号:** `{out_trade_no}` (请记录此订单号以备查询)\n"
                    f"此二维码将在约 **5 分钟** 后失效。\n\n"
                    f"支付成功后，系统将尝试自动处理您的充值，请耐心等待。\n"
                    f"如果长时间未到账或遇到问题，请联系管理员并提供您的订单号。"
                ),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_image(url="attachment://alipay_recharge_qr.png")
            embed.set_footer(text="请勿重复扫描或支付同一订单。")
            
            await interaction.followup.send(embed=embed, file=qr_file, ephemeral=True)
            logging.info(f"Payment QR code sent to user {user.id} for out_trade_no: {out_trade_no}")
        except Exception as e_qr_send:
            logging.error(f"Error generating or sending QR code image for {out_trade_no}: {e_qr_send}", exc_info=True)
            # 如果二维码图片发送失败，但URL获取成功，至少给用户URL
            await interaction.followup.send(f"✅ 已为您生成支付请求！生成二维码图片时遇到问题，请尝试手动访问以下支付链接：\n{qr_code_url_from_alipay}\n订单号: `{out_trade_no}`", ephemeral=True)
    else:
        error_message_to_user = "抱歉，生成支付二维码失败，请稍后再试。"
        if alipay_api_error_msg: # 如果有来自支付宝的明确错误信息
            error_message_to_user = alipay_api_error_msg # 直接使用支付宝的错误信息（如果它对用户友好）
        
        logging.error(f"Final failure to get QR code for user {user.id}, out_trade_no {out_trade_no}. Message to user: {error_message_to_user}")
        await interaction.followup.send(f"❌ {error_message_to_user}", ephemeral=True)

# --- 新增：FAQ/帮助 指令组 ---
faq_group = app_commands.Group(name="faq", description="服务器FAQ与帮助信息管理和查询")

# --- Command: /faq add ---
@faq_group.command(name="add", description="[管理员] 添加一个新的FAQ条目 (关键词和答案)")
@app_commands.describe(
    keyword="用户搜索时使用的关键词 (简短，唯一)",
    answer="对应关键词的答案/帮助信息"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def faq_add(interaction: discord.Interaction, keyword: str, answer: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    keyword = keyword.lower().strip() 
    if not keyword:
        await interaction.response.send_message("❌ 关键词不能为空。", ephemeral=True)
        return
    if len(keyword) > MAX_FAQ_KEYWORD_LENGTH: # 使用之前定义的常量
        await interaction.response.send_message(f"❌ 关键词过长 (最多 {MAX_FAQ_KEYWORD_LENGTH} 字符)。", ephemeral=True)
        return
    if len(answer) > MAX_FAQ_ANSWER_LENGTH: # 使用之前定义的常量
        await interaction.response.send_message(f"❌ 答案内容过长 (最多 {MAX_FAQ_ANSWER_LENGTH} 字符)。", ephemeral=True)
        return
    if len(answer.strip()) < 10:
         await interaction.response.send_message(f"❌ 答案内容过短 (至少10字符)。", ephemeral=True)
         return

    # 确保 server_faqs 已在文件顶部定义
    guild_faqs = server_faqs.setdefault(guild.id, {})
    if keyword in guild_faqs:
        await interaction.response.send_message(f"⚠️ 关键词 **'{keyword}'** 已存在。如需修改，请先移除旧条目。", ephemeral=True)
        return
    if len(guild_faqs) >= MAX_FAQ_ENTRIES_PER_GUILD: # 使用之前定义的常量
        await interaction.response.send_message(f"❌ 服务器FAQ条目已达上限 ({len(guild_faqs)}/{MAX_FAQ_ENTRIES_PER_GUILD} 条)。", ephemeral=True)
        return

    guild_faqs[keyword] = answer.strip()
    print(f"[FAQ] Guild {guild.id}: User {interaction.user.id} added FAQ for keyword '{keyword}'.")
    await interaction.response.send_message(f"✅ FAQ 条目已添加！\n关键词: **{keyword}**\n答案预览: ```{answer[:150]}{'...' if len(answer)>150 else ''}```", ephemeral=True)

# --- Command: /faq remove ---
@faq_group.command(name="remove", description="[管理员] 移除一个FAQ条目")
@app_commands.describe(keyword="要移除的FAQ条目的关键词")
@app_commands.checks.has_permissions(manage_guild=True)
async def faq_remove(interaction: discord.Interaction, keyword: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    keyword = keyword.lower().strip()
    guild_faqs = server_faqs.get(guild.id, {})

    if keyword not in guild_faqs:
        await interaction.response.send_message(f"❌ 未找到关键词为 **'{keyword}'** 的FAQ条目。", ephemeral=True)
        return

    removed_answer = guild_faqs.pop(keyword)
    if not guild_faqs: 
        if guild.id in server_faqs:
            del server_faqs[guild.id]

    print(f"[FAQ] Guild {guild.id}: User {interaction.user.id} removed FAQ for keyword '{keyword}'.")
    await interaction.response.send_message(f"✅ 已成功移除关键词为 **'{keyword}'** 的FAQ条目。\n被移除答案预览: ```{removed_answer[:150]}{'...' if len(removed_answer)>150 else ''}```", ephemeral=True)

# --- Command: /faq list ---
@faq_group.command(name="list", description="[管理员] 列出所有FAQ关键词和部分答案")
@app_commands.checks.has_permissions(manage_guild=True) 
async def faq_list(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此命令只能在服务器内使用。", ephemeral=True)
        return

    guild_faqs = server_faqs.get(guild.id, {})
    if not guild_faqs:
        await interaction.response.send_message("ℹ️ 当前服务器的FAQ列表是空的。", ephemeral=True)
        return

    embed = discord.Embed(title=f"服务器FAQ列表 - {guild.name}", color=discord.Color.teal(), timestamp=discord.utils.utcnow())
    
    description_parts = [f"当前共有 **{len(guild_faqs)}** 条FAQ。显示前 {min(len(guild_faqs), MAX_FAQ_LIST_DISPLAY)} 条：\n"] # 使用常量
    count = 0
    for kw, ans in guild_faqs.items():
        if count >= MAX_FAQ_LIST_DISPLAY: # 使用常量
            break
        ans_preview = ans[:60] + ('...' if len(ans) > 60 else '')
        description_parts.append(f"🔑 **{kw}**: ```{ans_preview}```")
        count += 1
    
    if len(guild_faqs) > MAX_FAQ_LIST_DISPLAY: # 使用常量
        description_parts.append(f"\n*还有 {len(guild_faqs) - MAX_FAQ_LIST_DISPLAY} 条未在此处完整显示。*")
    
    embed.description = "\n".join(description_parts)
    embed.set_footer(text="用户可使用 /faq search <关键词> 来查询。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Command: /faq search (对所有用户开放) ---
@faq_group.command(name="search", description="搜索FAQ/帮助信息")
@app_commands.describe(keyword="你想要查询的关键词")
async def faq_search(interaction: discord.Interaction, keyword: str):
    guild = interaction.guild
    if not guild: 
        await interaction.response.send_message("此命令似乎不在服务器中执行。", ephemeral=True)
        return

    keyword = keyword.lower().strip()
    guild_faqs = server_faqs.get(guild.id, {})

    if not guild_faqs:
        await interaction.response.send_message("ℹ️ 本服务器尚未配置FAQ信息。", ephemeral=True)
        return

    answer = guild_faqs.get(keyword)

    if not answer:
        possible_matches = []
        for kw, ans_val in guild_faqs.items():
            if keyword in kw or kw in keyword: 
                possible_matches.append((kw, ans_val))
        
        if len(possible_matches) == 1: 
            answer = possible_matches[0][1]
            keyword = possible_matches[0][0] 
        elif len(possible_matches) > 1:
            match_list_str = "\n".join([f"- `{match[0]}`" for match in possible_matches[:5]]) 
            await interaction.response.send_message(f"🤔 找到了多个可能的匹配项，请尝试更精确的关键词：\n{match_list_str}", ephemeral=True)
            return

    if answer:
        embed = discord.Embed(
            title=f"💡 FAQ: {keyword.capitalize()}",
            description=answer,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"由 {guild.name} 提供")
        await interaction.response.send_message(embed=embed, ephemeral=False) 
    else:
        await interaction.response.send_message(f"😕 未找到与 **'{keyword}'**相关的FAQ信息。请尝试其他关键词或联系管理员。", ephemeral=True)

# --- FAQ/帮助 指令组结束 ---

# --- (在你其他指令组如 manage_group, ai_group, faq_group 定义完成之后) ---

relay_msg_group = app_commands.Group(name="relaymsg", description="服务器内匿名中介私信功能")

@relay_msg_group.command(name="send", description="向服务器内另一位成员发送一条匿名消息。")
@app_commands.describe(
    target_user="你要向其发送匿名消息的成员。",
    message="你要发送的消息内容。"
)
async def relay_msg_send(interaction: discord.Interaction, target_user: discord.Member, message: str):
    await interaction.response.defer(ephemeral=True) # 初始响应对发起者临时可见

    guild = interaction.guild
    initiator = interaction.user # 发起者

    if not guild:
        await interaction.followup.send("❌ 此命令只能在服务器频道中使用。", ephemeral=True)
        return
    if target_user.bot:
        await interaction.followup.send("❌ 不能向机器人发送匿名消息。", ephemeral=True)
        return
    if target_user == initiator:
        await interaction.followup.send("❌ 你不能给自己发送匿名消息。", ephemeral=True)
        return
    
    # 可选：检查发起者是否有权使用此功能
    if ANONYMOUS_RELAY_ALLOWED_ROLE_IDS:
        can_use = False
        if isinstance(initiator, discord.Member):
            for role_id in ANONYMOUS_RELAY_ALLOWED_ROLE_IDS:
                if discord.utils.get(initiator.roles, id=role_id):
                    can_use = True
                    break
        if not can_use:
            await interaction.followup.send("🚫 你没有权限使用此功能。", ephemeral=True)
            return

    if len(message) > 1800: # 留一些空间给机器人的提示信息
        await interaction.followup.send("❌ 消息内容过长 (最多约1800字符)。", ephemeral=True)
        return

    dm_embed = discord.Embed(
        title=f"✉️ 一条来自 {guild.name} 的消息",
        description=f"```\n{message}\n```\n\n"
                    f"ℹ️ 这是一条通过服务器机器人转发的消息。\n"
                    f"你可以直接在此私信中 **回复这条消息** 来回应，你的回复也会通过机器人转发。\n"
                    f"*(你的身份对消息来源者是可见的，但消息来源者的身份对你是匿名的)*", # 或者调整匿名性措辞
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    dm_embed.set_footer(text=f"消息来自服务器: {guild.name}")

    try:
        sent_dm_message = await target_user.send(embed=dm_embed)
        # 记录这个会话，使用机器人发送的DM消息ID作为键
        ANONYMOUS_RELAY_SESSIONS[sent_dm_message.id] = {
            "initiator_id": initiator.id,
            "target_id": target_user.id,
            "original_channel_id": interaction.channel_id, # 记录发起命令的频道
            "guild_id": guild.id,
            "initiator_display_name": initiator.display_name # 用于在频道内显示谁发起了对某人的匿名消息
        }
        await interaction.followup.send(f"✅ 你的匿名消息已通过机器人发送给 {target_user.mention}。请等待对方在私信中回复。", ephemeral=True)
        print(f"[RelayMsg] Initiator {initiator.id} sent message to Target {target_user.id} via DM {sent_dm_message.id}. Original channel: {interaction.channel_id}")

    except discord.Forbidden:
        await interaction.followup.send(f"❌ 无法向 {target_user.mention} 发送私信。对方可能关闭了私信或屏蔽了机器人。", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 发送私信时发生错误: {e}", ephemeral=True)
        print(f"[RelayMsg ERROR] Sending DM to {target_user.id}: {e}")

# 将新的指令组添加到 bot tree (这会在文件末尾统一做)

# --- Management Command Group Definitions ---
# manage_group = app_commands.Group(...)
# ... (你现有的 manage_group 指令)

# --- Management Command Group Definitions ---
manage_group = app_commands.Group(name="管理", description="服务器高级管理相关指令 (需要相应权限)")
# ... (后续的 manage_group 指令组代码) ...


# --- Management Command Group Definitions ---
manage_group = app_commands.Group(name="管理", description="服务器高级管理相关指令 (需要相应权限)")

# --- Ticket Setup Command ---
@manage_group.command(name="票据设定", description="在指定频道部署“创建票据”的面板。")
@app_commands.describe(
    panel_channel="将在哪个频道发布“创建票据”的面板？",
    ticket_category="所有新票据都将创建在此分类下。"
)
@app_commands.checks.has_permissions(administrator=True)
async def manage_ticket_setup(interaction: discord.Interaction, panel_channel: discord.TextChannel, ticket_category: discord.CategoryChannel):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    set_setting(ticket_settings, guild.id, "category_id", ticket_category.id)
    save_server_settings()

    embed = discord.Embed(
        title=f"🎫 {guild.name} 服务台",
        description="**需要帮助或有任何疑问吗？**\n\n请从下方的菜单中选择与您问题最相关的部门，以创建一个专属的私人支持频道。\n\n我们的专业团队将在票据频道中为您提供帮助。",
        color=discord.Color.blue()
    )
    embed.set_footer(text="请从下方选择一个部门开始")
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    # 发送新的持久化视图
    view = PersistentTicketCreationView()
    
    try:
        await panel_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ “创建票据”面板已成功部署到 {panel_channel.mention}！", ephemeral=True)
    except Exception as e:
        logging.error(f"部署票据面板时发生错误: {e}", exc_info=True)
        await interaction.followup.send(f"❌ 部署时发生未知错误: {e}", ephemeral=True)

# --- Other Management Commands ---
@manage_group.command(name="ai豁免-添加用户", description="将用户添加到 AI 内容检测的豁免列表 (管理员)。")
@app_commands.describe(user="要添加到豁免列表的用户。")
@app_commands.checks.has_permissions(administrator=True)
async def manage_ai_exempt_user_add(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if user.bot: await interaction.followup.send("❌ 不能将机器人添加到豁免列表。", ephemeral=True); return
    user_id = user.id
    if user_id in exempt_users_from_ai_check: await interaction.followup.send(f"ℹ️ 用户 {user.mention} 已在 AI 检测豁免列表中。", ephemeral=True)
    else:
        exempt_users_from_ai_check.add(user_id)
        await interaction.followup.send(f"✅ 已将用户 {user.mention} 添加到 AI 内容检测豁免列表。", ephemeral=True)
        print(f"[AI豁免] 管理员 {interaction.user} 添加了用户 {user.name}({user_id}) 到豁免列表。")

@manage_group.command(name="ai豁免-移除用户", description="将用户从 AI 内容检测的豁免列表中移除 (管理员)。")
@app_commands.describe(user="要从豁免列表中移除的用户。")
@app_commands.checks.has_permissions(administrator=True)
async def manage_ai_exempt_user_remove(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    user_id = user.id
    if user_id in exempt_users_from_ai_check:
        exempt_users_from_ai_check.remove(user_id)
        await interaction.followup.send(f"✅ 已将用户 {user.mention} 从 AI 内容检测豁免列表中移除。", ephemeral=True)
        print(f"[AI豁免] 管理员 {interaction.user} 从豁免列表移除了用户 {user.name}({user_id})。")
    else: await interaction.followup.send(f"ℹ️ 用户 {user.mention} 不在 AI 检测豁免列表中。", ephemeral=True)

@manage_group.command(name="ai豁免-添加频道", description="将频道添加到 AI 内容检测的豁免列表 (管理员)。")
@app_commands.describe(channel="要添加到豁免列表的文字频道。")
@app_commands.checks.has_permissions(administrator=True)
async def manage_ai_exempt_channel_add(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    channel_id = channel.id
    if channel_id in exempt_channels_from_ai_check: await interaction.followup.send(f"ℹ️ 频道 {channel.mention} 已在 AI 检测豁免列表中。", ephemeral=True)
    else:
        exempt_channels_from_ai_check.add(channel_id)
        await interaction.followup.send(f"✅ 已将频道 {channel.mention} 添加到 AI 内容检测豁免列表。", ephemeral=True)
        print(f"[AI豁免] 管理员 {interaction.user} 添加了频道 #{channel.name}({channel_id}) 到豁免列表。")

@manage_group.command(name="ai豁免-移除频道", description="将频道从 AI 内容检测的豁免列表中移除 (管理员)。")
@app_commands.describe(channel="要从豁免列表中移除的文字频道。")
@app_commands.checks.has_permissions(administrator=True)
async def manage_ai_exempt_channel_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    channel_id = channel.id
    if channel_id in exempt_channels_from_ai_check:
        exempt_channels_from_ai_check.remove(channel_id)
        await interaction.followup.send(f"✅ 已将频道 {channel.mention} 从 AI 内容检测豁免列表中移除。", ephemeral=True)
        print(f"[AI豁免] 管理员 {interaction.user} 从豁免列表移除了频道 #{channel.name}({channel_id})。")
    else: await interaction.followup.send(f"ℹ️ 频道 {channel.mention} 不在 AI 检测豁免列表中。", ephemeral=True)

@manage_group.command(name="ai豁免-查看列表", description="查看当前 AI 内容检测的豁免用户和频道列表 (管理员)。")
@app_commands.checks.has_permissions(administrator=True)
async def manage_ai_exempt_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild: await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return

    exempt_user_mentions = []
    for uid in exempt_users_from_ai_check:
        member = guild.get_member(uid)
        exempt_user_mentions.append(f"{member.mention} (`{member}`)" if member else f"未知用户 ({uid})")
    exempt_channel_mentions = []
    for cid in exempt_channels_from_ai_check:
        channel = guild.get_channel(cid)
        exempt_channel_mentions.append(channel.mention if channel else f"未知频道 ({cid})")

    embed = discord.Embed(title="⚙️ AI 内容检测豁免列表 (当前内存)", color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())
    user_list_str = "\n".join(exempt_user_mentions) if exempt_user_mentions else "无"
    channel_list_str = "\n".join(exempt_channel_mentions) if exempt_channel_mentions else "无"
    embed.add_field(name="豁免用户", value=user_list_str[:1024], inline=False) # Max field length 1024
    embed.add_field(name="豁免频道", value=channel_list_str[:1024], inline=False)
    embed.set_footer(text="注意：此列表存储在内存中，机器人重启后会清空（除非使用数据库）。")
    await interaction.followup.send(embed=embed, ephemeral=True)

@manage_group.command(name="删讯息", description="删除指定用户在当前频道的最近消息 (需要管理消息权限)。")
@app_commands.describe(user="要删除其消息的目标用户。", amount="要检查并删除的最近消息数量 (1 到 100)。")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
async def manage_delete_user_messages(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel): await interaction.followup.send("❌ 此命令只能在文字频道中使用。", ephemeral=True); return

    deleted_count = 0
    try:
        deleted_messages = await channel.purge(limit=amount, check=lambda m: m.author == user, reason=f"由 {interaction.user} 执行 /管理 删讯息")
        deleted_count = len(deleted_messages)
        await interaction.followup.send(f"✅ 成功在频道 {channel.mention} 中删除了用户 {user.mention} 的 {deleted_count} 条消息。", ephemeral=True)
        print(f"[审核操作] 用户 {interaction.user} 在频道 #{channel.name} 删除了用户 {user.name} 的 {deleted_count} 条消息。")
        log_embed = discord.Embed(title="🗑️ 用户消息删除", color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=interaction.user.mention, inline=True); log_embed.add_field(name="目标用户", value=user.mention, inline=True)
        log_embed.add_field(name="频道", value=channel.mention, inline=True); log_embed.add_field(name="删除数量", value=str(deleted_count), inline=True)
        log_embed.set_footer(text=f"执行者 ID: {interaction.user.id} | 目标用户 ID: {user.id}")
        await send_to_public_log(interaction.guild, log_embed, log_type="Delete User Messages")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 删除消息失败：机器人缺少在频道 {channel.mention} 中删除消息的权限。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 删讯息 时出错: {e}"); await interaction.followup.send(f"⚙️ 删除消息时发生未知错误: {e}", ephemeral=True)

@manage_group.command(name="频道名", description="修改当前频道的名称 (需要管理频道权限)。")
@app_commands.describe(new_name="频道的新名称。")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def manage_channel_name(interaction: discord.Interaction, new_name: str):
    channel = interaction.channel
    if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel, discord.Thread)):
        await interaction.response.send_message("❌ 此命令只能在文字/语音/分类频道或讨论串中使用。", ephemeral=True); return
    await interaction.response.defer(ephemeral=False)
    old_name = channel.name
    if len(new_name) > 100 or len(new_name) < 1: await interaction.followup.send("❌ 频道名称长度必须在 1 到 100 个字符之间。", ephemeral=True); return
    if not new_name.strip(): await interaction.followup.send("❌ 频道名称不能为空。", ephemeral=True); return

    try:
        await channel.edit(name=new_name, reason=f"由 {interaction.user} 修改")
        await interaction.followup.send(f"✅ 频道名称已从 `{old_name}` 修改为 `{new_name}`。", ephemeral=False)
        print(f"[管理操作] 用户 {interaction.user} 将频道 #{old_name} ({channel.id}) 重命名为 '{new_name}'。")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 修改频道名称失败：机器人缺少管理频道 {channel.mention} 的权限。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 频道名 时出错: {e}"); await interaction.followup.send(f"⚙️ 修改频道名称时发生未知错误: {e}", ephemeral=True)

@manage_group.command(name="禁言", description="暂时或永久禁言成员 (需要 '超时成员' 权限)。")
@app_commands.describe(user="要禁言的目标用户。", duration_minutes="禁言的分钟数 (输入 0 表示永久禁言，即最长28天)。", reason="(可选) 禁言的原因。")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def manage_mute(interaction: discord.Interaction, user: discord.Member, duration_minutes: int, reason: str = "未指定原因"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False) # Keep ephemeral=False for public confirmation

    if user == author: await interaction.followup.send("❌ 你不能禁言自己。", ephemeral=True); return
    if user.bot: await interaction.followup.send("❌ 不能禁言机器人。", ephemeral=True); return
    if user.id == guild.owner_id: await interaction.followup.send("❌ 不能禁言服务器所有者。", ephemeral=True); return
    
    # Check Discord's current timeout status
    if user.is_timed_out():
        current_timeout_discord = user.timed_out_until
        timeout_timestamp_discord = f"<t:{int(current_timeout_discord.timestamp())}:R>" if current_timeout_discord else "未知时间"
        # Also check our DB for an active mute log
        active_db_mute = database.db_get_latest_active_log_for_user(guild.id, user.id, "mute")
        db_mute_info = ""
        if active_db_mute and active_db_mute["expires_at"] and active_db_mute["expires_at"] > int(time.time()):
            db_expiry_ts = f"<t:{active_db_mute['expires_at']}:R>"
            db_mod = await bot.fetch_user(active_db_mute['moderator_user_id']) if active_db_mute['moderator_user_id'] else '未知管理员'
            db_reason = active_db_mute['reason'] or '无记录'
            db_mute_info = f"\n数据库记录显示由 {db_mod} 禁言，原因: '{db_reason}', 预计 {db_expiry_ts} 解除。"
        
        await interaction.followup.send(f"ℹ️ 用户 {user.mention} 当前已被 Discord 禁言，预计 {timeout_timestamp_discord} 解除。{db_mute_info}", ephemeral=True)
        return

    if isinstance(author, discord.Member) and author.id != guild.owner_id:
        if user.top_role >= author.top_role: await interaction.followup.send(f"🚫 你无法禁言层级等于或高于你的成员 ({user.mention})。", ephemeral=True); return
    if user.top_role >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 机器人无法禁言层级等于或高于自身的成员 ({user.mention})。", ephemeral=True); return
    if duration_minutes < 0: await interaction.followup.send("❌ 禁言时长不能为负数。", ephemeral=True); return

    current_timestamp = int(interaction.created_at.timestamp()) # Use interaction creation time as log time
    
    max_discord_duration_seconds = 28 * 24 * 60 * 60  # 28 days in seconds
    actual_duration_seconds = 0
    duration_text_log = ""

    if duration_minutes == 0: # "Permanent" (Discord max)
        actual_duration_seconds = max_discord_duration_seconds
        duration_text_log = "28 天 (永久)"
    else:
        requested_duration_seconds = duration_minutes * 60
        if requested_duration_seconds > max_discord_duration_seconds:
            actual_duration_seconds = max_discord_duration_seconds
            duration_text_log = f"{duration_minutes} 分钟 (限制为28天)"
            await interaction.followup.send(f"⚠️ 禁言时长超过 Discord 上限，已自动设为28天。", ephemeral=True) # Send this early
        else:
            actual_duration_seconds = requested_duration_seconds
            duration_text_log = f"{duration_minutes} 分钟"

    timeout_until_dt = discord.utils.utcnow() + datetime.timedelta(seconds=actual_duration_seconds)
    expires_at_timestamp = int(timeout_until_dt.timestamp())

    try:
        await user.timeout(timeout_until_dt, reason=f"由 {author.display_name} 禁言，原因: {reason}")
        
        # Log to database
        log_id = database.db_log_moderation_action(
            guild_id=guild.id,
            target_user_id=user.id,
            moderator_user_id=author.id,
            action_type="mute",
            reason=reason,
            created_at=current_timestamp,
            duration_seconds=actual_duration_seconds,
            expires_at=expires_at_timestamp
        )

        timeout_display_timestamp = f"<t:{expires_at_timestamp}:R>"
        response_msg = f"✅ 用户 {user.mention} 已被成功禁言 **{duration_text_log}**，预计 {timeout_display_timestamp} 解除。\n原因: {reason}"
        if not log_id:
            response_msg += "\n⚠️ **注意：** Discord操作成功，但数据库日志记录失败！请检查机器人后台日志。"
        
        await interaction.followup.send(response_msg) # Already deferred, so followup is fine
        print(f"[审核操作] 用户 {author} 禁言了用户 {user} {duration_text_log}。原因: {reason}. DB Log ID: {log_id}")
        
        log_embed = discord.Embed(title="🔇 用户禁言", color=discord.Color.dark_orange(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=author.mention, inline=True); log_embed.add_field(name="被禁言用户", value=user.mention, inline=True)
        log_embed.add_field(name="持续时间", value=duration_text_log, inline=False)
        log_embed.add_field(name="预计解除时间", value=f"<t:{expires_at_timestamp}:F> ({timeout_display_timestamp})", inline=False)
        log_embed.add_field(name="原因", value=reason, inline=False)
        if log_id: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | 日志 ID: {log_id}")
        else: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | DB记录失败")
        await send_to_public_log(guild, log_embed, log_type="Mute Member")

    except discord.Forbidden: await interaction.followup.send(f"⚙️ 禁言用户 {user.mention} 失败：机器人权限不足或层级不够。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 禁言 时出错: {e}"); await interaction.followup.send(f"⚙️ 禁言用户 {user.mention} 时发生未知错误: {e}", ephemeral=True)

@manage_group.command(name="解除禁言", description="解除成员的禁言状态 (需要 '超时成员' 权限)。")
@app_commands.describe(user="要解除禁言的目标用户。", reason="(可选) 解除禁言的原因。")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def manage_unmute(interaction: discord.Interaction, user: discord.Member, reason: str = "管理员解除"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False)

    if not user.is_timed_out():
        await interaction.followup.send(f"ℹ️ 用户 {user.mention} 当前未被禁言。", ephemeral=True)
        return

    current_timestamp = int(interaction.created_at.timestamp())

    try:
        await user.timeout(None, reason=f"由 {author.display_name} 解除禁言，原因: {reason}") # None duration removes timeout

        # Deactivate previous mute log in DB
        active_mute_log = database.db_get_latest_active_log_for_user(guild.id, user.id, "mute")
        if active_mute_log:
            database.db_deactivate_log(active_mute_log["log_id"], f"Unmuted by {author.id}", author.id)
        
        # Log the unmute action
        log_id = database.db_log_moderation_action(
            guild_id=guild.id,
            target_user_id=user.id,
            moderator_user_id=author.id,
            action_type="unmute",
            reason=reason,
            created_at=current_timestamp
        )

        response_msg = f"✅ 用户 {user.mention} 的禁言已被成功解除。\n原因: {reason}"
        if not log_id:
            response_msg += "\n⚠️ **注意：** Discord操作成功，但数据库日志记录失败！请检查机器人后台日志。"
            
        await interaction.followup.send(response_msg)
        print(f"[审核操作] 用户 {author} 解除了用户 {user} 的禁言。原因: {reason}. DB Log ID: {log_id}")

        log_embed = discord.Embed(title="🔊 用户解除禁言", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=author.mention, inline=True)
        log_embed.add_field(name="被解除用户", value=user.mention, inline=True)
        log_embed.add_field(name="原因", value=reason, inline=False)
        if log_id: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | 日志 ID: {log_id}")
        else: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | DB记录失败")
        await send_to_public_log(guild, log_embed, log_type="Unmute Member")

    except discord.Forbidden: await interaction.followup.send(f"⚙️ 解除用户 {user.mention} 禁言失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 解除禁言 时出错: {e}"); await interaction.followup.send(f"⚙️ 解除禁言时发生未知错误: {e}", ephemeral=True)

@manage_group.command(name="踢出", description="将成员踢出服务器 (需要 '踢出成员' 权限)。")
@app_commands.describe(user="要踢出的目标用户。", reason="(可选) 踢出的原因。")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def manage_kick(interaction: discord.Interaction, user: discord.Member, reason: str = "未指定原因"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False)
    if user == author: await interaction.followup.send("❌ 你不能踢出自己。", ephemeral=True); return
    if user.id == guild.owner_id: await interaction.followup.send("❌ 不能踢出服务器所有者。", ephemeral=True); return
    if user.id == bot.user.id: await interaction.followup.send("❌ 不能踢出机器人自己。", ephemeral=True); return
    if isinstance(author, discord.Member) and author.id != guild.owner_id:
        if user.top_role >= author.top_role: await interaction.followup.send(f"🚫 你无法踢出层级等于或高于你的成员 ({user.mention})。", ephemeral=True); return
    if user.top_role >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 机器人无法踢出层级等于或高于自身的成员 ({user.mention})。", ephemeral=True); return

    current_timestamp = int(interaction.created_at.timestamp())
    kick_reason_full = f"由 {author.display_name} 踢出，原因: {reason}"
    dm_sent = False
    try:
        try: await user.send(f"你已被管理员 **{author.display_name}** 从服务器 **{guild.name}** 中踢出。\n原因: {reason}"); dm_sent = True
        except Exception as dm_err: print(f"   - 发送踢出私信给 {user.name} 时发生错误: {dm_err}")
        
        await user.kick(reason=kick_reason_full)
        
        # Log to database
        log_id = database.db_log_moderation_action(
            guild_id=guild.id,
            target_user_id=user.id,
            moderator_user_id=author.id,
            action_type="kick",
            reason=reason,
            created_at=current_timestamp
        )
        
        dm_status = "(已尝试私信通知)" if dm_sent else "(私信通知失败)"
        response_msg = f"👢 用户 {user.mention} (`{user}`) 已被成功踢出服务器 {dm_status}。\n原因: {reason}"
        if not log_id:
            response_msg += "\n⚠️ **注意：** Discord操作成功，但数据库日志记录失败！请检查机器人后台日志。"

        await interaction.followup.send(response_msg)
        print(f"[审核操作] 用户 {author} 踢出了用户 {user}。原因: {reason}. DB Log ID: {log_id}")
        
        log_embed = discord.Embed(title="👢 用户踢出", color=discord.Color.dark_orange(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=author.mention, inline=True); log_embed.add_field(name="被踢出用户", value=f"{user.mention} (`{user}`)", inline=True)
        log_embed.add_field(name="私信状态", value="成功" if dm_sent else "失败", inline=True); log_embed.add_field(name="原因", value=reason, inline=False)
        if log_id: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | 日志 ID: {log_id}")
        else: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {user.id} | DB记录失败")
        await send_to_public_log(guild, log_embed, log_type="Kick Member")

    except discord.Forbidden: await interaction.followup.send(f"⚙️ 踢出用户 {user.mention} 失败：机器人权限不足或层级不够。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 踢出 时出错: {e}"); await interaction.followup.send(f"⚙️ 踢出用户 {user.mention} 时发生未知错误: {e}", ephemeral=True)

    # --- 新增：重启机器人指令 ---
@manage_group.command(name="restart", description="[服主专用] 重启机器人 (需要密码)。")
@app_commands.describe(password="重启机器人所需的密码。")
async def manage_restart_bot(interaction: discord.Interaction, password: str):
    # 确保只有服务器所有者能执行
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("🚫 只有服务器所有者才能重启机器人。", ephemeral=True)
        return

    if not RESTART_PASSWORD:
        await interaction.response.send_message("⚙️ 重启功能未配置密码，无法执行。", ephemeral=True)
        print("⚠️ /管理 restart: RESTART_PASSWORD 未设置，无法执行。")
        return

    if password == RESTART_PASSWORD:
        await interaction.response.send_message("✅ 收到重启指令。机器人将尝试关闭并等待外部进程重启...", ephemeral=True)
        print(f"机器人重启由 {interaction.user.name} ({interaction.user.id}) 发起。")

        # 准备日志 Embed
        log_embed_restart = discord.Embed(title="🤖 机器人重启中...",
                                  description=f"由 {interaction.user.mention} 发起。\n机器人将很快关闭，请等待外部服务（如systemd）自动重启。",
                                  color=discord.Color.orange(),
                                  timestamp=discord.utils.utcnow())
        if bot.user.avatar:
            log_embed_restart.set_thumbnail(url=bot.user.display_avatar.url)

        # 尝试发送重启通知到日志频道
        # 你可以使用 send_to_public_log 函数，或者直接发送到一个指定的频道
        # 为了简单起见，并且 send_to_public_log 依赖 PUBLIC_WARN_LOG_CHANNEL_ID，我们这里直接尝试发送
        # 你可以根据需要调整这里的日志发送逻辑
        log_channel_for_restart_notice = None
        # 优先使用 STARTUP_MESSAGE_CHANNEL_ID，因为它更可能是机器人状态通知的地方
        if STARTUP_MESSAGE_CHANNEL_ID and STARTUP_MESSAGE_CHANNEL_ID != 0: # 确保已配置且不是占位符
            channel_obj = bot.get_channel(STARTUP_MESSAGE_CHANNEL_ID)
            if channel_obj and isinstance(channel_obj, discord.TextChannel):
                log_channel_for_restart_notice = channel_obj
        
        # 如果启动频道无效或未配置，尝试公共日志频道
        if not log_channel_for_restart_notice and PUBLIC_WARN_LOG_CHANNEL_ID:
             # 确保 PUBLIC_WARN_LOG_CHANNEL_ID 不是你之前用作示例的ID (1374390176591122582)
             # 更好的做法是，如果这个ID在你的 .env 中被正确设置了，这里就不需要这个特定数字的检查
             # 假设 PUBLIC_WARN_LOG_CHANNEL_ID 是从 .env 正确读取的
             if PUBLIC_WARN_LOG_CHANNEL_ID != 1374390176591122582: # 移除或调整此硬编码检查
                channel_obj = bot.get_channel(PUBLIC_WARN_LOG_CHANNEL_ID)
                if channel_obj and isinstance(channel_obj, discord.TextChannel):
                    log_channel_for_restart_notice = channel_obj

        if log_channel_for_restart_notice:
            try:
                # 检查机器人是否有权限在目标频道发送消息和嵌入
                bot_member_for_perms = log_channel_for_restart_notice.guild.me
                if log_channel_for_restart_notice.permissions_for(bot_member_for_perms).send_messages and \
                   log_channel_for_restart_notice.permissions_for(bot_member_for_perms).embed_links:
                    await log_channel_for_restart_notice.send(embed=log_embed_restart)
                    print(f"  - 已发送重启通知到频道 #{log_channel_for_restart_notice.name}")
                else:
                    print(f"  - 发送重启通知到频道 #{log_channel_for_restart_notice.name} 失败：缺少发送或嵌入权限。")
            except discord.Forbidden:
                print(f"  - 发送重启通知到频道 #{log_channel_for_restart_notice.name} 失败：权限不足。")
            except Exception as e_log_send:
                print(f"  - 发送重启通知到频道时发生错误: {e_log_send}")
        else:
            print("  - 未找到合适的频道发送重启通知。")


        await bot.change_presence(status=discord.Status.invisible) # 可选：表示正在关闭
        # 清理 aiohttp 会话 (如果存在)
        if hasattr(bot, 'http_session') and bot.http_session and not bot.http_session.closed:
            await bot.http_session.close()
            print("  - aiohttp 会话已关闭。")
        
        await bot.close() # 优雅地关闭与 Discord 的连接
        print("机器人正在关闭以进行重启... 请确保你的托管服务 (如 systemd) 会自动重启脚本。")
        sys.exit(0) # 0 表示成功退出，systemd (如果配置为 Restart=always) 会重启它
    else:
        await interaction.response.send_message("❌ 密码错误，重启取消。", ephemeral=True)
        print(f"用户 {interaction.user.name} 尝试重启机器人但密码错误。")

@manage_group.command(name="封禁", description="永久封禁成员 (需要 '封禁成员' 权限)。")
@app_commands.describe(user_id="要封禁的用户 ID (使用 ID 防止误操作)。", delete_message_days="删除该用户过去多少天的消息 (0-7，可选，默认为0)。", reason="(可选) 封禁的原因。")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def manage_ban(interaction: discord.Interaction, user_id: str, delete_message_days: app_commands.Range[int, 0, 7] = 0, reason: str = "未指定原因"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False)
    
    try: target_user_id_int = int(user_id)
    except ValueError: await interaction.followup.send("❌ 无效的用户 ID 格式。", ephemeral=True); return
    
    if target_user_id_int == author.id: await interaction.followup.send("❌ 你不能封禁自己。", ephemeral=True); return
    if target_user_id_int == guild.owner_id: await interaction.followup.send("❌ 不能封禁服务器所有者。", ephemeral=True); return
    if target_user_id_int == bot.user.id: await interaction.followup.send("❌ 不能封禁机器人自己。", ephemeral=True); return

    current_timestamp = int(interaction.created_at.timestamp())
    banned_user_display = f"用户 ID {target_user_id_int}" # Default display
    
    try: # Check Discord ban status first
        ban_entry = await guild.fetch_ban(discord.Object(id=target_user_id_int))
        banned_user_obj_discord = ban_entry.user
        banned_user_display = f"**{banned_user_obj_discord}** (ID: {target_user_id_int})"
        await interaction.followup.send(f"ℹ️ 用户 {banned_user_display} 已经被 Discord 封禁了。", ephemeral=True)
        return
    except discord.NotFound: # User is not banned on Discord, proceed
        pass
    except Exception as fetch_err:
        print(f"检查用户 {target_user_id_int} Discord 封禁状态时出错: {fetch_err}")
        # Continue, but display might be just ID

    # Fetch user object for better display name if not already fetched
    try:
        user_obj = await bot.fetch_user(target_user_id_int)
        banned_user_display = f"**{user_obj}** (ID: {target_user_id_int})"
        target_member = guild.get_member(target_user_id_int) # Check if member is in guild for hierarchy checks
        if target_member: # If member is in guild, update display and do hierarchy checks
            banned_user_display = f"{target_member.mention} (`{target_member}`)"
            if isinstance(author, discord.Member) and author.id != guild.owner_id:
                if target_member.top_role >= author.top_role: await interaction.followup.send(f"🚫 你无法封禁层级等于或高于你的成员 ({target_member.mention})。", ephemeral=True); return
            if target_member.top_role >= guild.me.top_role and guild.me.id != guild.owner_id: await interaction.followup.send(f"🚫 机器人无法封禁层级等于或高于自身的成员 ({target_member.mention})。", ephemeral=True); return
    except discord.NotFound:
        print(f"用户ID {target_user_id_int} 未找到，将按ID封禁。") # User not found globally, can still ban by ID
    except Exception as e:
        print(f"获取用户 {target_user_id_int} 信息时出错: {e}")


    ban_reason_full = f"由 {author.display_name} 封禁，原因: {reason}"
    try:
        user_to_ban_obj = discord.Object(id=target_user_id_int)
        await guild.ban(user_to_ban_obj, reason=ban_reason_full, delete_message_days=delete_message_days)
        
        # Log to database
        extra_data_for_ban = {"delete_message_days": delete_message_days}
        log_id = database.db_log_moderation_action(
            guild_id=guild.id,
            target_user_id=target_user_id_int,
            moderator_user_id=author.id,
            action_type="ban",
            reason=reason,
            created_at=current_timestamp,
            extra_data=extra_data_for_ban
        )
        
        delete_days_text = f"并删除了其过去 {delete_message_days} 天的消息" if delete_message_days > 0 else ""
        response_msg = f"🚫 用户 {banned_user_display} 已被成功永久封禁{delete_days_text}。\n原因: {reason}"
        if not log_id:
            response_msg += "\n⚠️ **注意：** Discord操作成功，但数据库日志记录失败！请检查机器人后台日志。"
        
        await interaction.followup.send(response_msg)
        print(f"[审核操作] 用户 {author} 封禁了 {banned_user_display}。原因: {reason}. DB Log ID: {log_id}")
        
        log_embed = discord.Embed(title="🚫 用户封禁", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=author.mention, inline=True); log_embed.add_field(name="被封禁用户", value=banned_user_display, inline=True)
        log_embed.add_field(name="原因", value=reason, inline=False)
        if delete_message_days > 0: log_embed.add_field(name="消息删除", value=f"删除了过去 {delete_message_days} 天的消息", inline=True)
        if log_id: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {target_user_id_int} | 日志 ID: {log_id}")
        else: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {target_user_id_int} | DB记录失败")
        await send_to_public_log(guild, log_embed, log_type="Ban Member")

    except discord.Forbidden: await interaction.followup.send(f"⚙️ 封禁用户 ID {target_user_id_int} 失败：机器人权限不足或层级不够。", ephemeral=True)
    # discord.NotFound can happen if trying to ban an ID that doesn't exist on Discord at all
    except discord.NotFound: await interaction.followup.send(f"❓ 封禁失败：Discord 上找不到用户 ID 为 {target_user_id_int} 的用户。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 封禁 时出错: {e}"); await interaction.followup.send(f"⚙️ 封禁用户 ID {target_user_id_int} 时发生未知错误: {e}", ephemeral=True)

@manage_group.command(name="解封", description="解除对用户的封禁 (需要 '封禁成员' 权限)。")
@app_commands.describe(user_id="要解除封禁的用户 ID。", reason="(可选) 解除封禁的原因。")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def manage_unban(interaction: discord.Interaction, user_id: str, reason: str = "管理员酌情处理"):
    guild = interaction.guild
    author = interaction.user
    await interaction.response.defer(ephemeral=False)
    
    try: target_user_id_int = int(user_id)
    except ValueError: await interaction.followup.send("❌ 无效的用户 ID 格式。", ephemeral=True); return

    current_timestamp = int(interaction.created_at.timestamp())
    user_to_unban_obj_discord = None
    user_display = f"用户 ID {target_user_id_int}"
    
    try: # Check Discord ban status
        ban_entry = await guild.fetch_ban(discord.Object(id=target_user_id_int))
        user_to_unban_obj_discord = ban_entry.user
        user_display = f"**{user_to_unban_obj_discord}** (ID: {target_user_id_int})"
    except discord.NotFound: 
        await interaction.followup.send(f"ℹ️ {user_display} 当前并未被此服务器的 Discord 封禁。", ephemeral=True)
        # Optionally, check and deactivate any stray 'active' ban logs in DB
        active_db_ban = database.db_get_latest_active_log_for_user(guild.id, target_user_id_int, "ban")
        if active_db_ban:
            database.db_deactivate_log(active_db_ban["log_id"], f"Discord unban check, user not banned. Deactivated by system.", bot.user.id)
            print(f"[DB Housekeeping] Deactivated stray ban log {active_db_ban['log_id']} for user {target_user_id_int} as they are not Discord banned.")
        return
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 检查封禁状态失败：机器人缺少查看封禁列表的权限。", ephemeral=True); return
    except Exception as fetch_err: print(f"获取用户 {target_user_id_int} 封禁信息时出错: {fetch_err}"); await interaction.followup.send(f"⚙️ 获取封禁信息时出错: {fetch_err}", ephemeral=True); return

    unban_reason_full = f"由 {author.display_name} 解除封禁，原因: {reason}"
    try:
        await guild.unban(user_to_unban_obj_discord, reason=unban_reason_full)
        
        # Deactivate previous ban log in DB
        active_ban_log = database.db_get_latest_active_log_for_user(guild.id, target_user_id_int, "ban")
        if active_ban_log:
            database.db_deactivate_log(active_ban_log["log_id"], f"Unbanned by {author.id}", author.id)
        
        # Log the unban action
        log_id = database.db_log_moderation_action(
            guild_id=guild.id,
            target_user_id=target_user_id_int,
            moderator_user_id=author.id,
            action_type="unban",
            reason=reason,
            created_at=current_timestamp
        )
        
        response_msg = f"✅ 用户 {user_display} 已被成功解除封禁。\n原因: {reason}"
        if not log_id:
             response_msg += "\n⚠️ **注意：** Discord操作成功，但数据库日志记录失败！请检查机器人后台日志。"
        
        await interaction.followup.send(response_msg)
        print(f"[审核操作] 用户 {author} 解除了对 {user_display} 的封禁。原因: {reason}. DB Log ID: {log_id}")
        
        log_embed = discord.Embed(title="✅ 用户解封", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="执行者", value=author.mention, inline=True); log_embed.add_field(name="被解封用户", value=user_display, inline=True)
        log_embed.add_field(name="原因", value=reason, inline=False)
        if log_id: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {target_user_id_int} | 日志 ID: {log_id}")
        else: log_embed.set_footer(text=f"执行者 ID: {author.id} | 用户 ID: {target_user_id_int} | DB记录失败")
        await send_to_public_log(guild, log_embed, log_type="Unban Member")

    except discord.Forbidden: await interaction.followup.send(f"⚙️ 解封 {user_display} 失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /管理 解封 时出错: {e}"); await interaction.followup.send(f"⚙️ 解封 {user_display} 时发生未知错误: {e}", ephemeral=True)


@manage_group.command(name="人数频道", description="创建或更新一个显示服务器成员人数的语音频道。")
@app_commands.describe(channel_name_template="(可选) 频道名称的模板，用 '{count}' 代表人数。")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, connect=True)
async def manage_member_count_channel(interaction: discord.Interaction, channel_name_template: str = "📊｜成员人数: {count}"):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    # 使用 temp_vc_settings 存储人数频道信息
    existing_channel_id = get_setting(temp_vc_settings, guild.id, "member_count_channel_id")
    existing_template = get_setting(temp_vc_settings, guild.id, "member_count_template")
    existing_channel = guild.get_channel(existing_channel_id) if existing_channel_id else None

    member_count = guild.member_count
    try:
        new_name = channel_name_template.format(count=member_count)
        if len(new_name) > 100: await interaction.followup.send(f"❌ 失败：生成的频道名称 '{new_name}' 超过100字符。", ephemeral=True); return
        if not new_name.strip(): await interaction.followup.send(f"❌ 失败：生成的频道名称不能为空。", ephemeral=True); return
    except KeyError: await interaction.followup.send("❌ 失败：频道名称模板无效，必须包含 `{count}`。", ephemeral=True); return
    except Exception as format_err: await interaction.followup.send(f"❌ 失败：处理模板时出错: {format_err}", ephemeral=True); return

    if existing_channel and isinstance(existing_channel, discord.VoiceChannel):
        if existing_channel.name == new_name and existing_template == channel_name_template:
            await interaction.followup.send(f"ℹ️ 人数频道 {existing_channel.mention} 无需更新 (当前: {member_count})。", ephemeral=True); return
        try:
            await existing_channel.edit(name=new_name, reason="更新服务器成员人数")
            set_setting(temp_vc_settings, guild.id, "member_count_template", channel_name_template)
            await interaction.followup.send(f"✅ 已更新人数频道 {existing_channel.mention} 为 `{new_name}`。", ephemeral=True)
            print(f"[管理操作] 服务器 {guild.id} 人数频道 ({existing_channel_id}) 更新为 '{new_name}'。")
        except discord.Forbidden: await interaction.followup.send(f"⚙️ 更新频道 {existing_channel.mention} 失败：权限不足。", ephemeral=True)
        except Exception as e: print(f"更新人数频道时出错: {e}"); await interaction.followup.send(f"⚙️ 更新频道时发生未知错误: {e}", ephemeral=True)
    else: # Create new channel
        try:
            overwrites = {guild.default_role: discord.PermissionOverwrite(connect=False), guild.me: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True)}
            new_channel = await guild.create_voice_channel(name=new_name, overwrites=overwrites, position=0, reason="创建服务器成员人数统计频道")
            set_setting(temp_vc_settings, guild.id, "member_count_channel_id", new_channel.id)
            set_setting(temp_vc_settings, guild.id, "member_count_template", channel_name_template)
            await interaction.followup.send(f"✅ 已创建成员人数统计频道: {new_channel.mention}。", ephemeral=True)
            print(f"[管理操作] 服务器 {guild.id} 创建了成员人数频道 '{new_name}' ({new_channel.id})。")
        except discord.Forbidden: await interaction.followup.send(f"⚙️ 创建人数频道失败：权限不足。", ephemeral=True)
        except Exception as e: print(f"创建人数频道时出错: {e}"); await interaction.followup.send(f"⚙️ 创建人数频道时发生未知错误: {e}", ephemeral=True)

# ... (你已有的 /管理 禁言, /管理 踢出, /管理 人数频道 等指令) ...

# --- 新增：机器人白名单管理指令 (作为 /管理 下的子命令组) ---
# First, define the subcommand group under manage_group
bot_whitelist_group = app_commands.Group(name="bot_whitelist", description="[服主专用] 管理机器人白名单。", parent=manage_group)

# Now, define commands under this new bot_whitelist_group

@bot_whitelist_group.command(name="add", description="[服主专用] 添加一个机器人ID到白名单。")
@app_commands.describe(bot_user_id="要添加到白名单的机器人用户ID。")
async def whitelist_add_cmd(interaction: discord.Interaction, bot_user_id: str): # Renamed function to avoid conflict
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("🚫 只有服务器所有者才能管理机器人白名单。", ephemeral=True)
        return
    
    try:
        target_bot_id = int(bot_user_id)
    except ValueError:
        await interaction.response.send_message("❌ 无效的机器人用户ID格式。请输入纯数字ID。", ephemeral=True)
        return

    if target_bot_id == bot.user.id:
        await interaction.response.send_message("ℹ️ 你不能将此机器人本身添加到白名单（它总是允许的）。", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id not in bot.approved_bot_whitelist:
        bot.approved_bot_whitelist[guild_id] = set()

    if target_bot_id in bot.approved_bot_whitelist[guild_id]:
        await interaction.response.send_message(f"ℹ️ 机器人ID `{target_bot_id}` 已经在白名单中了。", ephemeral=True)
    else:
        bot.approved_bot_whitelist[guild_id].add(target_bot_id)
        bot_name_display = f"ID `{target_bot_id}`"
        try:
            added_bot_user = await bot.fetch_user(target_bot_id)
            if added_bot_user and added_bot_user.bot:
                bot_name_display = f"机器人 **{added_bot_user.name}** (`{target_bot_id}`)"
            elif added_bot_user: 
                 await interaction.response.send_message(f"⚠️ 用户ID `{target_bot_id}` ({added_bot_user.name}) 不是一个机器人。白名单仅用于机器人。", ephemeral=True)
                 bot.approved_bot_whitelist[guild_id].discard(target_bot_id)
                 return
        except discord.NotFound:
            print(f"[Whitelist] Bot ID {target_bot_id} not found by fetch_user, but added to whitelist.")
        except Exception as e:
            print(f"[Whitelist] Error fetching bot user {target_bot_id}: {e}")

        await interaction.response.send_message(f"✅ {bot_name_display} 已成功添加到机器人白名单。下次它加入时将被允许。", ephemeral=True)
        print(f"[Whitelist] 服务器 {guild_id}: 所有者 {interaction.user.name} 添加了机器人ID {target_bot_id} 到白名单。")
        save_bot_whitelist_to_file()

@bot_whitelist_group.command(name="remove", description="[服主专用] 从白名单中移除一个机器人ID。")
@app_commands.describe(bot_user_id="要从白名单中移除的机器人用户ID。")
async def whitelist_remove_cmd(interaction: discord.Interaction, bot_user_id: str): # Renamed function
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("🚫 只有服务器所有者才能管理机器人白名单。", ephemeral=True)
        return

    try:
        target_bot_id = int(bot_user_id)
    except ValueError:
        await interaction.response.send_message("❌ 无效的机器人用户ID格式。请输入纯数字ID。", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if guild_id not in bot.approved_bot_whitelist or target_bot_id not in bot.approved_bot_whitelist[guild_id]:
        await interaction.response.send_message(f"ℹ️ 机器人ID `{target_bot_id}` 不在白名单中。", ephemeral=True)
    else:
        bot.approved_bot_whitelist[guild_id].discard(target_bot_id)
        if not bot.approved_bot_whitelist[guild_id]:
            del bot.approved_bot_whitelist[guild_id]

        bot_name_display = f"ID `{target_bot_id}`"
        try:
            removed_bot_user = await bot.fetch_user(target_bot_id)
            if removed_bot_user: bot_name_display = f"机器人 **{removed_bot_user.name}** (`{target_bot_id}`)"
        except: pass

        await interaction.response.send_message(f"✅ {bot_name_display} 已成功从机器人白名单中移除。下次它加入时将被踢出（除非再次添加）。", ephemeral=True)
        print(f"[Whitelist] 服务器 {guild_id}: 所有者 {interaction.user.name} 从白名单移除了机器人ID {target_bot_id}。")
        save_bot_whitelist_to_file()

@bot_whitelist_group.command(name="list", description="[服主专用] 查看当前机器人白名单列表。")
async def whitelist_list_cmd(interaction: discord.Interaction): # Renamed function
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("🚫 只有服务器所有者才能管理机器人白名单。", ephemeral=True)
        return

    guild_id = interaction.guild_id
    guild_whitelist = bot.approved_bot_whitelist.get(guild_id, set())

    embed = discord.Embed(title=f"机器人白名单 - {interaction.guild.name}", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    if not guild_whitelist:
        embed.description = "目前没有机器人被添加到白名单。"
    else:
        description_lines = ["以下机器人ID被允许加入本服务器："]
        if not guild_whitelist:
            description_lines.append("列表为空。")
        else:
            for bot_id in guild_whitelist:
                try:
                    b_user = await bot.fetch_user(bot_id)
                    description_lines.append(f"- **{b_user.name if b_user else '未知用户'}** (`{bot_id}`) {'(Bot)' if b_user and b_user.bot else '(Not a Bot - Should be removed?)' if b_user else ''}")
                except discord.NotFound:
                    description_lines.append(f"- 未知机器人 (`{bot_id}`)")
                except Exception:
                    description_lines.append(f"- ID `{bot_id}` (获取信息失败)")
        embed.description = "\n".join(description_lines)
    embed.set_footer(text="注意：此白名单存储在内存中，机器人重启后会清空（除非实现持久化存储）。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- 机器人白名单管理指令结束 ---

# ==========================================================
# == ↓↓↓ 在这里粘贴新的 /recharge 指令组 ↓↓↓
# ==========================================================

# --- 充值系统指令组 ---
recharge_group = app_commands.Group(name="recharge", description="金币充值操作")

@recharge_group.command(name="request", description="请求充值金币并获取支付二维码")
@app_commands.describe(amount="您希望充值的金额 (单位: 元，例如 30.00)")
async def recharge_request(interaction: discord.Interaction, amount: app_commands.Range[float, 1.0, 10000.0]):
    await interaction.response.defer(ephemeral=True)

    if not alipay_client:
        await interaction.followup.send("❌ 抱歉，支付功能当前未配置或不可用，请联系管理员。", ephemeral=True)
        return

    out_trade_no = f"GJTRC-{interaction.guild.id}-{interaction.user.id}-{int(time.time()*1000)}"
    
    # 在数据库创建初始记录
    db_req_id = database.db_create_initial_recharge_request(
        guild_id=interaction.guild.id,
        user_id=interaction.user.id,
        requested_cny_amount=amount,
        out_trade_no=out_trade_no
    )
    if not db_req_id:
        await interaction.followup.send("❌ 创建充值请求时发生内部错误，请稍后再试。", ephemeral=True)
        return

    # 调用支付宝API
    model = AlipayTradePrecreateRequest()
    model.notify_url = ALIPAY_NOTIFY_URL
    model.biz_content = {
        "out_trade_no": out_trade_no,
        "total_amount": f"{amount:.2f}",
        "subject": f"GJ服务器 - 金币充值 ({interaction.user.name})",
        "timeout_express": "5m"
    }

    try:
        response_str = await bot.loop.run_in_executor(None, lambda: alipay_client.execute(model))
        response_data = json.loads(response_str)
        alipay_resp = response_data.get("alipay_trade_precreate_response", {})

        if alipay_resp.get("code") == "10000":
            qr_code_url = alipay_resp.get("qr_code")
            
            # 生成二维码图片
            qr_img = qrcode.make(qr_code_url)
            img_byte_arr = io.BytesIO()
            qr_img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            qr_file = discord.File(fp=img_byte_arr, filename="alipay_qr.png")

            embed = discord.Embed(
                title="掃描二維碼支付",
                description=f"請使用支付寶掃描下方二維碼支付 **{amount:.2f} 元**。\n\n**訂單號:** `{out_trade_no}`\n此二維碼將在 **5 分鐘** 後失效。",
                color=discord.Color.blue()
            )
            embed.set_image(url="attachment://alipay_qr.png")
            await interaction.followup.send(embed=embed, file=qr_file, ephemeral=True)
        else:
            error_msg = alipay_resp.get("sub_msg", "未知支付宝错误")
            await interaction.followup.send(f"❌ 生成支付二维码失败: {error_msg}", ephemeral=True)
            
    except Exception as e:
        logging.error(f"Error creating Alipay order: {e}", exc_info=True)
        await interaction.followup.send("❌ 调用支付宝时发生未知错误，请联系管理员。", ephemeral=True)

# ==========================================================
# == ↑↑↑ /recharge 指令组粘贴结束 ↑↑↑
# ==========================================================

# --- Temporary Voice Channel Command Group ---
voice_group = app_commands.Group(name="语音声道", description="临时语音频道相关指令")

@voice_group.command(name="设定母频道", description="设置一个语音频道，用户加入后会自动创建临时频道 (需管理频道权限)。")
@app_commands.describe(master_channel="选择一个语音频道作为创建入口 (母频道)。", category="(可选) 选择一个分类，新创建的临时频道将放置在此分类下。")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, move_members=True, view_channel=True) # Added view_channel
async def voice_set_master(interaction: discord.Interaction, master_channel: discord.VoiceChannel, category: Optional[discord.CategoryChannel] = None):
    guild_id = interaction.guild_id
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)
    bot_member = guild.me
    if not master_channel.permissions_for(bot_member).view_channel: await interaction.followup.send(f"❌ 设置失败：机器人无法看到母频道 {master_channel.mention}！", ephemeral=True); return
    target_category = category if category else master_channel.category
    if not target_category: await interaction.followup.send(f"❌ 设置失败：找不到有效的分类 (母频道 {master_channel.mention} 可能不在分类下，且未指定)。", ephemeral=True); return
    cat_perms = target_category.permissions_for(bot_member)
    missing_perms = [p for p, needed in {"管理频道": cat_perms.manage_channels, "移动成员": cat_perms.move_members, "查看频道": cat_perms.view_channel}.items() if not needed]
    if missing_perms: await interaction.followup.send(f"❌ 设置失败：机器人在分类 **{target_category.name}** 中缺少权限: {', '.join(missing_perms)}！", ephemeral=True); return

    set_setting(temp_vc_settings, guild_id, "master_channel_id", master_channel.id)
    set_setting(temp_vc_settings, guild_id, "category_id", target_category.id)
    cat_name_text = f" 在分类 **{target_category.name}** 下"
    await interaction.followup.send(f"✅ 临时语音频道的母频道已成功设置为 {master_channel.mention}{cat_name_text}。", ephemeral=True)
    print(f"[临时语音] 服务器 {guild_id}: 母频道={master_channel.id}, 分类={target_category.id}")

def is_temp_vc_owner(interaction: discord.Interaction) -> bool:
    if not interaction.user.voice or not interaction.user.voice.channel: return False
    user_vc = interaction.user.voice.channel
    return user_vc.id in temp_vc_owners and temp_vc_owners.get(user_vc.id) == interaction.user.id

@voice_group.command(name="设定权限", description="(房主专用) 修改你创建的临时语音频道中某个成员或身份组的权限。")
@app_commands.describe(target="要修改权限的目标用户或身份组。", allow_connect="(可选) 是否允许连接？", allow_speak="(可选) 是否允许说话？", allow_stream="(可选) 是否允许直播？", allow_video="(可选) 是否允许开启摄像头？")
async def voice_set_perms(interaction: discord.Interaction, target: Union[discord.Member, discord.Role], allow_connect: Optional[bool]=None, allow_speak: Optional[bool]=None, allow_stream: Optional[bool]=None, allow_video: Optional[bool]=None):
    await interaction.response.defer(ephemeral=True)
    user_vc = interaction.user.voice.channel if interaction.user.voice else None
    if not user_vc or not is_temp_vc_owner(interaction): await interaction.followup.send("❌ 此命令只能在你创建的临时语音频道中使用。", ephemeral=True); return
    if not user_vc.permissions_for(interaction.guild.me).manage_permissions: await interaction.followup.send(f"⚙️ 操作失败：机器人缺少在频道 {user_vc.mention} 中 '管理权限' 的能力。", ephemeral=True); return
    if target == interaction.user: await interaction.followup.send("❌ 你不能修改自己的权限。", ephemeral=True); return
    if isinstance(target, discord.Role) and target == interaction.guild.default_role: await interaction.followup.send("❌ 不能修改 `@everyone` 的权限。", ephemeral=True); return

    overwrites = user_vc.overwrites_for(target); perms_changed = []
    if allow_connect is not None: overwrites.connect = allow_connect; perms_changed.append(f"连接: {'✅' if allow_connect else '❌'}")
    if allow_speak is not None: overwrites.speak = allow_speak; perms_changed.append(f"说话: {'✅' if allow_speak else '❌'}")
    if allow_stream is not None: overwrites.stream = allow_stream; perms_changed.append(f"直播: {'✅' if allow_stream else '❌'}")
    if allow_video is not None: overwrites.video = allow_video; perms_changed.append(f"视频: {'✅' if allow_video else '❌'}")
    if not perms_changed: await interaction.followup.send("⚠️ 你没有指定任何要修改的权限。", ephemeral=True); return

    try:
        await user_vc.set_permissions(target, overwrite=overwrites, reason=f"由房主 {interaction.user.name} 修改权限")
        target_mention = target.mention if isinstance(target, discord.Member) else f"`@ {target.name}`"
        await interaction.followup.send(f"✅ 已更新 **{target_mention}** 在频道 {user_vc.mention} 的权限：\n{', '.join(perms_changed)}", ephemeral=True)
        print(f"[临时语音] 房主 {interaction.user} 修改了频道 {user_vc.id} 中 {target} 的权限: {', '.join(perms_changed)}")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 设置权限失败：机器人权限不足或层级不够。", ephemeral=True)
    except Exception as e: print(f"执行 /语音 设定权限 时出错: {e}"); await interaction.followup.send(f"⚙️ 设置权限时发生未知错误: {e}", ephemeral=True)

@voice_group.command(name="转让", description="(房主专用) 将你创建的临时语音频道所有权转让给频道内的其他用户。")
@app_commands.describe(new_owner="选择要接收所有权的新用户 (该用户必须在频道内)。")
async def voice_transfer(interaction: discord.Interaction, new_owner: discord.Member):
    await interaction.response.defer(ephemeral=False)
    user = interaction.user; user_vc = user.voice.channel if user.voice else None
    if not user_vc or not is_temp_vc_owner(interaction): await interaction.followup.send("❌ 此命令只能在你创建的临时语音频道中使用。", ephemeral=True); return
    if new_owner.bot: await interaction.followup.send("❌ 不能转让给机器人。", ephemeral=True); return
    if new_owner == user: await interaction.followup.send("❌ 不能转让给自己。", ephemeral=True); return
    if not new_owner.voice or new_owner.voice.channel != user_vc: await interaction.followup.send(f"❌ 目标用户 {new_owner.mention} 必须在你的频道 ({user_vc.mention}) 内。", ephemeral=True); return
    if not user_vc.permissions_for(interaction.guild.me).manage_permissions: await interaction.followup.send(f"⚙️ 操作失败：机器人缺少 '管理权限' 能力。", ephemeral=True); return

    try:
        new_owner_overwrites = discord.PermissionOverwrite(manage_channels=True, manage_permissions=True, move_members=True,connect=True, speak=True, stream=True, use_voice_activation=True, priority_speaker=True, mute_members=True, deafen_members=True, use_embedded_activities=True)
        old_owner_overwrites = discord.PermissionOverwrite() # Clear old owner's special perms
        await user_vc.set_permissions(new_owner, overwrite=new_owner_overwrites, reason=f"所有权由 {user.name} 转让")
        await user_vc.set_permissions(user, overwrite=old_owner_overwrites, reason=f"所有权转让给 {new_owner.name}")
        temp_vc_owners[user_vc.id] = new_owner.id
        await interaction.followup.send(f"✅ 频道 {user_vc.mention} 的所有权已成功转让给 {new_owner.mention}！", ephemeral=False)
        print(f"[临时语音] 频道 {user_vc.id} 所有权从 {user.id} 转让给 {new_owner.id}")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 转让失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /语音 转让 时出错: {e}"); await interaction.followup.send(f"⚙️ 转让时发生未知错误: {e}", ephemeral=True)

@voice_group.command(name="房主", description="(成员使用) 如果原房主已离开频道，尝试获取该临时语音频道的所有权。")
async def voice_claim(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    user = interaction.user; user_vc = user.voice.channel if user.voice else None
    if not user_vc or user_vc.id not in temp_vc_created: await interaction.followup.send("❌ 此命令只能在临时语音频道中使用。", ephemeral=True); return

    current_owner_id = temp_vc_owners.get(user_vc.id)
    if current_owner_id == user.id: await interaction.followup.send("ℹ️ 你已经是房主了。", ephemeral=True); return

    owner_is_present = False; original_owner = None
    if current_owner_id:
        original_owner = interaction.guild.get_member(current_owner_id)
        if original_owner and original_owner.voice and original_owner.voice.channel == user_vc: owner_is_present = True
    if owner_is_present: await interaction.followup.send(f"❌ 无法获取所有权：原房主 {original_owner.mention} 仍在频道中。", ephemeral=True); return
    if not user_vc.permissions_for(interaction.guild.me).manage_permissions: await interaction.followup.send(f"⚙️ 操作失败：机器人缺少 '管理权限' 能力。", ephemeral=True); return

    try:
        new_owner_overwrites = discord.PermissionOverwrite(manage_channels=True, manage_permissions=True, move_members=True, connect=True, speak=True, stream=True, use_voice_activation=True, priority_speaker=True, mute_members=True, deafen_members=True, use_embedded_activities=True)
        await user_vc.set_permissions(user, overwrite=new_owner_overwrites, reason=f"由 {user.name} 获取房主权限")
        if original_owner: # Reset old owner perms if they existed
             try: await user_vc.set_permissions(original_owner, overwrite=None, reason="原房主离开，重置权限")
             except Exception as reset_e: print(f"   - 重置原房主 {original_owner.id} 权限时出错: {reset_e}")
        temp_vc_owners[user_vc.id] = user.id
        await interaction.followup.send(f"✅ 恭喜 {user.mention}！你已成功获取频道 {user_vc.mention} 的房主权限！", ephemeral=False)
        print(f"[临时语音] 用户 {user.id} 获取了频道 {user_vc.id} 的房主权限 (原房主: {current_owner_id})")
    except discord.Forbidden: await interaction.followup.send(f"⚙️ 获取房主权限失败：机器人权限不足。", ephemeral=True)
    except Exception as e: print(f"执行 /语音 房主 时出错: {e}"); await interaction.followup.send(f"⚙️ 获取房主权限时发生未知错误: {e}", ephemeral=True)

# --- 经济系统斜杠指令组 ---
eco_group = app_commands.Group(name="eco", description=f"与{ECONOMY_CURRENCY_NAME}和商店相关的指令。")

@eco_group.command(name="balance", description=f"查看你或其他用户的{ECONOMY_CURRENCY_NAME}余额。")
@app_commands.describe(user=f"(可选) 要查看其余额的用户。")
async def eco_balance(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    target_user = user if user else interaction.user
    guild_id = interaction.guild_id

    if not guild_id:
        await interaction.response.send_message("此命令只能在服务器中使用。", ephemeral=True)
        return
        
    if target_user.bot:
        await interaction.response.send_message(f"🤖 机器人没有{ECONOMY_CURRENCY_NAME}余额。", ephemeral=True)
        return

    # 从数据库获取最新的余额
    balance = database.db_get_user_balance(guild_id, target_user.id, ECONOMY_DEFAULT_BALANCE) 
    
    print(f"[COMMAND /eco balance] Fetched balance for {target_user.id} in guild {guild_id}: {balance}") # 新增调试

    embed = discord.Embed(
        title=f"{ECONOMY_CURRENCY_SYMBOL} {target_user.display_name}的余额",
        description=f"**{balance}** {ECONOMY_CURRENCY_NAME}", # 确保这里用的是从数据库获取的 balance
        color=discord.Color.gold()
    )
    if target_user.avatar:
        embed.set_thumbnail(url=target_user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed, ephemeral=True if user else False)

@eco_group.command(name="transfer", description=f"向其他用户转账{ECONOMY_CURRENCY_NAME}。")
@app_commands.describe(
    receiver=f"接收{ECONOMY_CURRENCY_NAME}的用户。",
    amount=f"要转账的{ECONOMY_CURRENCY_NAME}数量。"
)
async def eco_transfer(interaction: discord.Interaction, receiver: discord.Member, amount: app_commands.Range[int, ECONOMY_MIN_TRANSFER_AMOUNT, None]):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild_id
    sender = interaction.user

    if not guild_id:
        await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return
    if sender.id == receiver.id:
        await interaction.followup.send(f"❌ 你不能给自己转账。", ephemeral=True); return
    if receiver.bot:
        await interaction.followup.send(f"❌ 你不能向机器人转账。", ephemeral=True); return
    if amount <= 0:
        await interaction.followup.send(f"❌ 转账金额必须大于0。", ephemeral=True); return

    sender_balance = get_user_balance(guild_id, sender.id)
    
    tax_amount = 0
    if ECONOMY_TRANSFER_TAX_PERCENT > 0:
        tax_amount = int(amount * (ECONOMY_TRANSFER_TAX_PERCENT / 100))
        if tax_amount < 1 and amount > 0 : tax_amount = 1 # 如果启用了手续费且金额为正，则手续费至少为1

    total_deduction = amount + tax_amount

    if sender_balance < total_deduction:
        await interaction.followup.send(f"❌ 你的{ECONOMY_CURRENCY_NAME}不足以完成转账（需要 {total_deduction} {ECONOMY_CURRENCY_NAME}，包含手续费）。", ephemeral=True)
        return

    if update_user_balance(guild_id, sender.id, -total_deduction) and \
       update_user_balance(guild_id, receiver.id, amount):
        save_economy_data() # 成功交易后保存
        
        response_msg = f"✅ 你已成功向 {receiver.mention} 转账 **{amount}** {ECONOMY_CURRENCY_NAME}。"
        if tax_amount > 0:
            response_msg += f"\n手续费: **{tax_amount}** {ECONOMY_CURRENCY_NAME}。"
        await interaction.followup.send(response_msg, ephemeral=True)

        try:
            dm_embed = discord.Embed(
                title=f"{ECONOMY_CURRENCY_SYMBOL} 你收到一笔转账！",
                description=f"{sender.mention} 向你转账了 **{amount}** {ECONOMY_CURRENCY_NAME}。",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            dm_embed.set_footer(text=f"来自服务器: {interaction.guild.name}")
            await receiver.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.followup.send(f"ℹ️ 已成功转账，但无法私信通知 {receiver.mention} (TA可能关闭了私信)。",ephemeral=True)
        except Exception as e:
            print(f"[经济系统错误] 发送转账私信给 {receiver.id} 时出错: {e}")
        
        print(f"[经济系统] 转账: {sender.id} -> {receiver.id}, 金额: {amount}, 手续费: {tax_amount}, 服务器: {guild_id}")
    else:
        await interaction.followup.send(f"❌ 转账失败，发生内部错误。请重试或联系管理员。", ephemeral=True)

# --- 修改 /eco shop 指令 ---
@eco_group.command(name="shop", description=f"查看可用物品的商店。")
async def eco_shop(interaction: discord.Interaction):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("此命令只能在服务器中使用。", ephemeral=True)
        return

    # guild_shop_items = shop_items.get(guild_id, {}) # 如果使用内存字典
    guild_shop_items = database.db_get_shop_items(guild_id) # 如果使用数据库

    if not guild_shop_items:
        await interaction.response.send_message(f"商店目前是空的。让管理员添加一些物品吧！", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"{ECONOMY_CURRENCY_SYMBOL} {interaction.guild.name} 商店",
        color=discord.Color.blurple()
    )
    # 你可以在这里设置商店的通用插图
    # embed.set_image(url="你的商店插图URL") # 例如
    # embed.set_thumbnail(url="你的商店缩略图URL")

    description_parts = []
    items_for_view = {} # 存储当前页面/所有物品以便创建按钮

    # 简单实现，先显示所有物品的描述，按钮会根据这些物品创建
    # 如果物品过多，这里也需要分页逻辑来决定哪些物品放入 items_for_view
    # 暂时我们假设物品数量不多
    for slug, item in guild_shop_items.items():
        stock_info = f"(库存: {item['stock']})" if item.get('stock', -1) != -1 else "(无限库存)"
        role_name_info = ""
        if item.get("role_id"):
            role = interaction.guild.get_role(item['role_id'])
            if role:
                role_name_info = f" (奖励身份组: **{role.name}**)"
        
        description_parts.append(
            f"🛍️ **{item['name']}** - {ECONOMY_CURRENCY_SYMBOL}**{item['price']}** {stock_info}\n"
            f"   📝 *{item.get('description', '无描述')}*{role_name_info}\n"
            # f"   ID: `{slug}`\n" # 用户不需要看到slug，按钮会处理它
        )
        items_for_view[slug] = item # 添加到用于视图的字典

    if not description_parts:
        await interaction.response.send_message(f"商店中没有可显示的物品。", ephemeral=True)
        return

    embed.description = "\n".join(description_parts[:ECONOMY_MAX_SHOP_ITEMS_PER_PAGE * 2]) # 限制描述长度
    if len(description_parts) > ECONOMY_MAX_SHOP_ITEMS_PER_PAGE * 2:
        embed.description += "\n\n*还有更多物品...*"

    embed.set_footer(text=f"点击下方按钮直接购买物品。")
    
    # 创建并发送带有按钮的视图
    view = ShopItemBuyView(items_for_view, guild_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


@eco_group.command(name="buy", description=f"从商店购买一件物品。")
@app_commands.describe(item_identifier=f"要购买的物品的名称或ID (商店列表中的`ID`)。")
async def eco_buy(interaction: discord.Interaction, item_identifier: str):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild_id
    user = interaction.user

    if not guild_id:
        await interaction.followup.send("此命令只能在服务器中使用。", ephemeral=True); return

    guild_shop_items = shop_items.get(guild_id, {})
    item_slug_to_buy = get_item_slug(item_identifier) # 首先尝试 slug
    item_to_buy_data = guild_shop_items.get(item_slug_to_buy)

    if not item_to_buy_data: # 如果通过 slug 未找到，则尝试精确名称（不太可靠）
        for slug, data_val in guild_shop_items.items():
            if data_val['name'].lower() == item_identifier.lower():
                item_to_buy_data = data_val
                item_slug_to_buy = slug
                break
    
    if not item_to_buy_data:
        await interaction.followup.send(f"❌ 未在商店中找到名为或ID为 **'{item_identifier}'** 的物品。", ephemeral=True)
        return

    item_price = item_to_buy_data['price']
    user_balance = get_user_balance(guild_id, user.id)

    if user_balance < item_price:
        await interaction.followup.send(f"❌ 你的{ECONOMY_CURRENCY_NAME}不足以购买 **{item_to_buy_data['name']}** (需要 {item_price}，你有 {user_balance})。", ephemeral=True)
        return

    # 检查库存
    item_stock = item_to_buy_data.get("stock", -1)
    if item_stock == 0: # 显式为 0 表示已售罄
        await interaction.followup.send(f"❌ 抱歉，物品 **{item_to_buy_data['name']}** 已售罄。", ephemeral=True)
        return

    # 如果物品授予身份组，检查用户是否已拥有
    granted_role_id = item_to_buy_data.get("role_id")
    if granted_role_id and isinstance(user, discord.Member): # 确保 user 是 Member 对象
        if discord.utils.get(user.roles, id=granted_role_id):
            await interaction.followup.send(f"ℹ️ 你已经拥有物品 **{item_to_buy_data['name']}** 关联的身份组了。", ephemeral=True)
            return


    if update_user_balance(guild_id, user.id, -item_price):
        # 如果不是无限库存，则更新库存
        if item_stock != -1:
            shop_items[guild_id][item_slug_to_buy]["stock"] = item_stock - 1
        
        save_economy_data() # 成功购买并更新库存后保存

        await grant_item_purchase(interaction, user, item_to_buy_data) # 处理身份组授予和自定义消息
        
        await interaction.followup.send(f"🎉 恭喜！你已成功购买 **{item_to_buy_data['name']}**！", ephemeral=True)
        print(f"[经济系统] 购买: 用户 {user.id} 在服务器 {guild_id} 以 {item_price} 购买了 '{item_to_buy_data['name']}'。")
    else:
        await interaction.followup.send(f"❌ 购买失败，发生内部错误。请重试或联系管理员。", ephemeral=True)

@eco_group.command(name="leaderboard", description=f"显示服务器中{ECONOMY_CURRENCY_NAME}排行榜。")
async def eco_leaderboard(interaction: discord.Interaction):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("此命令只能在服务器中使用。", ephemeral=True)
        return

    guild_balances = user_balances.get(guild_id, {})
    if not guild_balances:
        await interaction.response.send_message(f"本服务器还没有人拥有{ECONOMY_CURRENCY_NAME}记录。", ephemeral=True)
        return

    # 按余额降序排序用户。items() 返回 (user_id, balance)
    sorted_users = sorted(guild_balances.items(), key=lambda item: item[1], reverse=True)
    
    embed = discord.Embed(
        title=f"{ECONOMY_CURRENCY_SYMBOL} {interaction.guild.name} {ECONOMY_CURRENCY_NAME}排行榜",
        color=discord.Color.gold()
    )
    
    description_lines = []
    rank_emojis = ["🥇", "🥈", "🥉"] 
    
    for i, (user_id, balance) in enumerate(sorted_users[:ECONOMY_MAX_LEADERBOARD_USERS]):
        member = interaction.guild.get_member(user_id)
        member_display = member.mention if member else f"用户ID({user_id})"
        rank_prefix = rank_emojis[i] if i < len(rank_emojis) else f"**{i+1}.**"
        description_lines.append(f"{rank_prefix} {member_display} - {ECONOMY_CURRENCY_SYMBOL} **{balance}**")
        
    if not description_lines:
        embed.description = "排行榜当前为空。"
    else:
        embed.description = "\n".join(description_lines)
        
    embed.set_footer(text=f"显示前 {ECONOMY_MAX_LEADERBOARD_USERS} 名。")
    await interaction.response.send_message(embed=embed, ephemeral=False)


# --- 管理员经济系统指令组 (/管理 的子指令组) ---
eco_admin_group = app_commands.Group(name="eco_admin", description=f"管理员经济系统管理指令。", parent=manage_group)

@eco_admin_group.command(name="give", description=f"给予用户指定数量的{ECONOMY_CURRENCY_NAME}。")
@app_commands.describe(user="要给予货币的用户。", amount=f"要给予的{ECONOMY_CURRENCY_NAME}数量。")
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_give(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, None]):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    guild_id = interaction.guild_id
    if not guild_id: # 通常对于斜杠命令 guild_id 存在
        await interaction.response.send_message("此命令只能在服务器内执行。", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message(f"❌ 不能给机器人{ECONOMY_CURRENCY_NAME}。", ephemeral=True)
        return
    
    if amount <= 0: # 确保给予的金额是正数
        await interaction.response.send_message(f"❌ 给予的金额必须大于0。", ephemeral=True)
        return

    print(f"[COMMAND /eco_admin give] User {interaction.user.id} attempting to give {amount} to target_user {user.id} in guild {guild_id}")

    # 调用数据库函数进行更新，is_delta=True 表示增加余额
    # ECONOMY_DEFAULT_BALANCE 作为 db_get_user_balance (被 db_update_user_balance 调用) 的备用初始值
    update_success = database.db_update_user_balance(
        guild_id, 
        user.id, 
        amount, 
        is_delta=True, # 明确这是增量操作
        default_balance=ECONOMY_DEFAULT_BALANCE 
    )

    if update_success:
        # 更新成功后，我们再次从数据库获取余额以确认并显示给用户
        final_balance = database.db_get_user_balance(guild_id, user.id, ECONOMY_DEFAULT_BALANCE) # 使用默认值以防万一
        
        print(f"[COMMAND /eco_admin give] db_update_user_balance returned success. Final balance for {user.id} is {final_balance}")

        await interaction.response.send_message(f"✅ 已成功给予 {user.mention} **{amount}** {ECONOMY_CURRENCY_NAME}。\n其新余额为: **{final_balance}** {ECONOMY_CURRENCY_NAME}。", ephemeral=False)
        print(f"[经济系统管理员] {interaction.user.id} 在服务器 {guild_id} 成功给予了用户 {user.id} {amount} {ECONOMY_CURRENCY_NAME}。新数据库余额: {final_balance}")
    else:
        # 如果 db_update_user_balance 返回 False，可能是因为尝试使余额为负（虽然这里是给予，不太可能）或数据库错误
        await interaction.response.send_message(f"❌ 操作失败，无法在数据库中更新用户 {user.mention} 的余额。请检查日志。", ephemeral=True)
        print(f"[经济系统管理员] 给予用户 {user.id} (guild: {guild_id}) {amount} {ECONOMY_CURRENCY_NAME} 失败 (db_update_user_balance 返回 False)。")

@eco_admin_group.command(name="take", description=f"从用户处移除指定数量的{ECONOMY_CURRENCY_NAME}。")
@app_commands.describe(user="要移除其货币的用户。", amount=f"要移除的{ECONOMY_CURRENCY_NAME}数量。")
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_take(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, None]):
    if not ECONOMY_ENABLED: await interaction.response.send_message("经济系统当前未启用。", ephemeral=True); return
    guild_id = interaction.guild_id
    if user.bot: await interaction.response.send_message(f"❌ 机器人没有{ECONOMY_CURRENCY_NAME}。", ephemeral=True); return

    current_bal = get_user_balance(guild_id, user.id)
    if current_bal < amount :
        # 选项：只拿走他们拥有的？还是失败？为了明确，我们选择失败。
        await interaction.response.send_message(f"❌ 用户 {user.mention} 只有 {current_bal} {ECONOMY_CURRENCY_NAME}，无法移除 {amount}。", ephemeral=True)
        return

    if update_user_balance(guild_id, user.id, -amount):
        save_economy_data()
        await interaction.response.send_message(f"✅ 已成功从 {user.mention} 处移除 **{amount}** {ECONOMY_CURRENCY_NAME}。\n其新余额为: {get_user_balance(guild_id, user.id)} {ECONOMY_CURRENCY_NAME}。", ephemeral=False)
        print(f"[经济系统管理员] {interaction.user.id} 在服务器 {guild_id} 从 {user.id} 处移除了 {amount} {ECONOMY_CURRENCY_NAME}。")
    else: await interaction.response.send_message(f"❌ 操作失败。", ephemeral=True)


@eco_admin_group.command(name="set", description=f"设置用户{ECONOMY_CURRENCY_NAME}为指定数量。")
@app_commands.describe(user="要设置其余额的用户。", amount=f"要设置的{ECONOMY_CURRENCY_NAME}数量。")
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_set(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 0, None]):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    guild_id = interaction.guild_id
    if not guild_id: # 对于斜杠命令通常 guild_id 存在
        await interaction.response.send_message("此命令只能在服务器内执行。", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message(f"❌ 机器人没有{ECONOMY_CURRENCY_NAME}。", ephemeral=True)
        return

    print(f"[COMMAND /eco_admin set] User {interaction.user.id} attempting to set balance for target_user {user.id} to {amount} in guild {guild_id}")

    # 调用数据库函数进行更新，is_delta=False 表示直接设置值
    # ECONOMY_DEFAULT_BALANCE 在这里作为 db_get_user_balance (被 db_update_user_balance 调用) 的备用值，
    # 但由于 is_delta=False，它实际上不影响最终写入的 new_balance。
    update_success = database.db_update_user_balance(
        guild_id, 
        user.id, 
        amount, 
        is_delta=False, 
        default_balance=ECONOMY_DEFAULT_BALANCE 
    )

    if update_success:
        # 更新成功后，我们再次从数据库获取余额以确认并显示给用户
        # 确保这里的 default_balance 与 /eco balance 命令中使用的 default_balance 一致
        # 并且与购买逻辑中获取余额时使用的 default_balance 一致
        final_balance = database.db_get_user_balance(guild_id, user.id, ECONOMY_DEFAULT_BALANCE)
        
        print(f"[COMMAND /eco_admin set] db_update_user_balance returned success. Attempting to display final_balance: {final_balance}")

        response_message = f"✅ 已成功将 {user.mention} 的余额设置为 **{final_balance}** {ECONOMY_CURRENCY_NAME}。"
        if final_balance != amount: # 如果读取到的最终余额和我们设置的不一样，添加一个警告
            response_message += f"\n⚠️ **注意：**设置值为 {amount}，但从数据库读取到的最终余额为 {final_balance}。请检查日志。"
            print(f"🚨 [COMMAND /eco_admin set] BALANCE MISMATCH! Set to {amount}, but db_get_user_balance returned {final_balance} for user {user.id}")

        await interaction.response.send_message(response_message, ephemeral=False)
        print(f"[经济系统管理员] {interaction.user.id} 在服务器 {guild_id} 尝试将用户 {user.id} 的余额设置为 {amount}。数据库最终确认余额为: {final_balance}")
    else:
        await interaction.response.send_message(f"❌ 操作失败，无法在数据库中更新用户 {user.mention} 的余额。", ephemeral=True)
        print(f"[经济系统管理员] 设置用户 {user.id} (guild: {guild_id}) 余额为 {amount} 失败 (db_update_user_balance 返回 False)。")

@eco_admin_group.command(name="config_chat_earn", description="配置聊天获取货币的金额和冷却时间。")
@app_commands.describe(
    amount=f"每条符合条件的聊天消息奖励的{ECONOMY_CURRENCY_NAME}数量 (0禁用)。",
    cooldown_seconds="两次聊天奖励之间的冷却时间 (秒)。"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_config_chat_earn(interaction: discord.Interaction, amount: app_commands.Range[int, 0, None], cooldown_seconds: app_commands.Range[int, 5, None]):
    if not ECONOMY_ENABLED: await interaction.response.send_message("经济系统当前未启用。", ephemeral=True); return
    guild_id = interaction.guild_id
    
    guild_economy_settings[guild_id] = {
        "chat_earn_amount": amount,
        "chat_earn_cooldown": cooldown_seconds
    }
    save_economy_data()
    status = "启用" if amount > 0 else "禁用"
    await interaction.response.send_message(
        f"✅ 聊天赚取{ECONOMY_CURRENCY_NAME}已配置：\n"
        f"- 状态: **{status}**\n"
        f"- 每条消息奖励: **{amount}** {ECONOMY_CURRENCY_NAME}\n"
        f"- 冷却时间: **{cooldown_seconds}** 秒",
        ephemeral=True
    )
    print(f"[经济系统管理员] 服务器 {guild_id} 聊天赚钱配置已由 {interaction.user.id} 更新：金额={amount}, 冷却={cooldown_seconds}")

@eco_admin_group.command(name="add_shop_item", description="向商店添加新物品。")
@app_commands.describe(
    name="物品的名称 (唯一，将用于生成ID)。",
    price=f"物品的价格 ({ECONOMY_CURRENCY_NAME})。",
    description="物品的简短描述。",
    role="(可选) 购买此物品后授予的身份组。",
    stock="(可选) 物品的库存数量 (-1 表示无限，默认为无限)。",
    purchase_message="(可选) 购买成功后私信给用户的额外消息。"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_add_shop_item(
    interaction: discord.Interaction, 
    name: str, 
    price: app_commands.Range[int, 0, None], 
    description: str,
    role: Optional[discord.Role] = None,
    stock: Optional[int] = -1, # 确保默认值与数据库函数预期一致
    purchase_message: Optional[str] = None
):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    guild_id = interaction.guild_id
    if not guild_id: # 对于斜杠命令，guild_id 应该总是存在
        await interaction.response.send_message("此命令似乎不在服务器上下文中执行。", ephemeral=True)
        return

    item_slug = get_item_slug(name) # 生成物品的唯一ID/slug

    # 调试打印 (可选，但在调试时有用)
    print(f"[COMMAND /eco_admin add_shop_item] Attempting to add: guild_id={guild_id}, slug='{item_slug}', name='{name}'")

    # 首先检查物品是否已存在于数据库中，避免重复添加导致 IntegrityError（虽然数据库层面会处理）
    # 这一步是可选的，因为 database.db_add_shop_item 内部也会处理 IntegrityError，
    # 但在这里先检查可以提供更友好的用户反馈。
    existing_item_check = database.db_get_shop_item(guild_id, item_slug)
    if existing_item_check:
        await interaction.response.send_message(f"❌ 商店中已存在名为/ID为 **'{name}'** (`{item_slug}`) 的物品。", ephemeral=True)
        return

    # 调用数据库函数来添加物品
    # 假设 database.db_add_shop_item 返回一个元组 (success: bool, message: str)
    # 如果它只返回 bool，你需要相应调整下面的反馈逻辑
    success, db_message = database.db_add_shop_item(
        guild_id=guild_id,
        item_slug=item_slug,
        name=name, # 传递原始名称给数据库
        price=price,
        description=description,
        role_id=role.id if role else None,
        stock=stock if stock is not None else -1, # 处理 Optional[int] 为 int
        purchase_message=purchase_message
    )

    if success:
        await interaction.response.send_message(f"✅ 物品 **{name}** (`{item_slug}`) 已成功添加到商店！", ephemeral=True)
        print(f"[经济系统管理员] 服务器 {guild_id} 物品已添加: {name} (Slug: {item_slug})，操作者: {interaction.user.id}")
    else:
        # db_message 应该包含来自数据库函数的具体错误信息
        # 如果 db_add_shop_item 返回的 db_message 为空或不友好，你可能需要在这里构造一个更通用的错误消息
        error_feedback = f"❌ 添加物品 **{name}** 到商店失败。"
        if db_message and "可能物品已存在" in db_message: # 这是基于 db_add_shop_item 中 IntegrityError 的反馈
             error_feedback = f"❌ 商店中已存在名为/ID为 **'{name}'** (`{item_slug}`) 的物品。"
        elif db_message:
            error_feedback += f" 原因: {db_message}"
        else:
            error_feedback += " 可能发生数据库错误或物品已存在。"
        
        await interaction.response.send_message(error_feedback, ephemeral=True)
        print(f"[经济系统管理员] 添加物品失败: {name} (Slug: {item_slug}), Guild: {guild_id}, Reason from DB: {db_message}")


@eco_admin_group.command(name="remove_shop_item", description="从商店移除物品。")
@app_commands.describe(item_identifier="要移除的物品的名称或ID。")
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_remove_shop_item(interaction: discord.Interaction, item_identifier: str):
    if not ECONOMY_ENABLED: await interaction.response.send_message("经济系统当前未启用。", ephemeral=True); return
    guild_id = interaction.guild_id
    item_slug_to_remove = get_item_slug(item_identifier)
    
    item_removed_data = None
    if guild_id in shop_items and item_slug_to_remove in shop_items[guild_id]:
        item_removed_data = shop_items[guild_id].pop(item_slug_to_remove)
    else: # 如果通过 slug 未找到，则尝试名称
        found_by_name = False
        for slug, data_val in shop_items.get(guild_id, {}).items():
            if data_val['name'].lower() == item_identifier.lower():
                item_removed_data = shop_items[guild_id].pop(slug)
                item_slug_to_remove = slug # 更新 slug 以便记录
                found_by_name = True
                break
        if not found_by_name:
             await interaction.response.send_message(f"❌ 未在商店中找到名为或ID为 **'{item_identifier}'** 的物品。", ephemeral=True)
             return

    if item_removed_data:
        if not shop_items[guild_id]: # 如果移除了最后一个物品，则删除服务器条目
            del shop_items[guild_id]
        save_economy_data()
        await interaction.response.send_message(f"✅ 物品 **{item_removed_data['name']}** (`{item_slug_to_remove}`) 已成功从商店移除。", ephemeral=True)
        print(f"[经济系统管理员] 服务器 {guild_id} 物品已移除: {item_removed_data['name']} (Slug: {item_slug_to_remove})，操作者: {interaction.user.id}")
    # else 情况已在上面的检查中处理

@eco_admin_group.command(name="edit_shop_item", description="编辑商店中现有物品的属性。")
@app_commands.describe(
    item_identifier="要编辑的物品的当前名称或ID。",
    new_price=f"(可选) 新的价格 ({ECONOMY_CURRENCY_NAME})。",
    new_description="(可选) 新的描述。",
    new_stock="(可选) 新的库存数量 (-1 表示无限)。",
    new_purchase_message="(可选) 新的购买成功私信消息。"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def eco_admin_edit_shop_item(
    interaction: discord.Interaction,
    item_identifier: str,
    new_price: Optional[app_commands.Range[int, 0, None]] = None,
    new_description: Optional[str] = None,
    new_stock: Optional[int] = None,
    new_purchase_message: Optional[str] = None
):
    if not ECONOMY_ENABLED:
        await interaction.response.send_message("经济系统当前未启用。", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild_id

    if new_price is None and new_description is None and new_stock is None and new_purchase_message is None:
        await interaction.followup.send("❌ 你至少需要提供一个要修改的属性。", ephemeral=True)
        return

    guild_shop = shop_items.get(guild_id, {})
    item_slug_to_edit = get_item_slug(item_identifier)
    item_data = guild_shop.get(item_slug_to_edit)

    if not item_data: # 尝试通过名称查找
        for slug, data_val in guild_shop.items():
            if data_val['name'].lower() == item_identifier.lower():
                item_data = data_val
                item_slug_to_edit = slug
                break
    
    if not item_data:
        await interaction.followup.send(f"❌ 未在商店中找到名为或ID为 **'{item_identifier}'** 的物品。", ephemeral=True)
        return

    updated_fields = []
    if new_price is not None:
        item_data["price"] = new_price
        updated_fields.append(f"价格为 {new_price} {ECONOMY_CURRENCY_NAME}")
    if new_description is not None:
        item_data["description"] = new_description
        updated_fields.append("描述")
    if new_stock is not None:
        item_data["stock"] = new_stock
        updated_fields.append(f"库存为 {'无限' if new_stock == -1 else new_stock}")
    if new_purchase_message is not None: # 允许设置为空字符串以移除消息
        item_data["purchase_message"] = new_purchase_message if new_purchase_message.strip() else None
        updated_fields.append("购买后消息")
    
    shop_items[guild_id][item_slug_to_edit] = item_data # 更新物品
    save_economy_data()

    await interaction.followup.send(f"✅ 物品 **{item_data['name']}** (`{item_slug_to_edit}`) 已更新以下属性：{', '.join(updated_fields)}。", ephemeral=True)
    print(f"[经济系统管理员] 服务器 {guild_id} 物品 '{item_data['name']}' 已由 {interaction.user.id} 编辑。字段: {', '.join(updated_fields)}")

# --- (经济系统管理员指令结束) ---

# 将新的指令组添加到机器人树
# 这应该与其他 bot.tree.add_command 调用一起完成
# bot.tree.add_command(eco_group) # 将在末尾添加
# manage_group 已添加，eco_admin_group 作为其子级会自动随 manage_group 添加。

# --- Add the command groups to the bot tree ---
bot.tree.add_command(manage_group)
bot.tree.add_command(voice_group)
bot.tree.add_command(ai_group)
bot.tree.add_command(faq_group)
bot.tree.add_command(relay_msg_group)
bot.tree.add_command(eco_group) # 添加新的面向用户的经济系统指令组
bot.tree.add_command(recharge_group)

# role_manager_bot.py (从网页管理面板部分开始)

# role_manager_bot.py (from the web panel section to the end)

# ==========================================================
# ==              网页管理面板 (FLASK)                    ==
# ==========================================================
try:
    from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
    from flask_socketio import SocketIO, join_room, disconnect
    from werkzeug.middleware.proxy_fix import ProxyFix
    import threading
    
    # 【核心修复第一步】添加猴子补丁
    # 这必须在导入标准库（如 socket, ssl）之前执行
    
    import requests as req
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("⚠️ 警告: 未安装 'Flask', 'Flask-SocketIO', 或 'eventlet'。Web管理面板将不可用。")

# --- 从环境变量加载新配置 ---
WEB_ADMIN_PASSWORD = os.environ.get("WEB_ADMIN_PASSWORD")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
if DISCORD_CLIENT_ID and DISCORD_REDIRECT_URI:
    DISCORD_OAUTH2_URL = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={urllib.parse.quote(DISCORD_REDIRECT_URI)}&response_type=code&scope=identify%20guilds"
else:
    DISCORD_OAUTH2_URL = "#"

def _get_socketio_allowed_origins():
    origins = []
    configured = os.environ.get("WEB_ALLOWED_ORIGINS", "")
    origins.extend(origin.strip() for origin in configured.split(",") if origin.strip())
    if DISCORD_REDIRECT_URI:
        parsed = urllib.parse.urlparse(DISCORD_REDIRECT_URI)
        if parsed.scheme and parsed.netloc:
            origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return sorted(set(origins)) or None

def _redact_mapping_for_log(mapping, sensitive_keys=None):
    sensitive = {key.lower() for key in (sensitive_keys or {'sign', 'passback_params'})}
    redacted = {}
    for key, value in mapping.items():
        if key.lower() in sensitive:
            redacted[key] = '<redacted>'
        else:
            redacted[key] = value
    return redacted

# --- 定义所有可用的Web面板权限点 (支持标签页) ---
AVAILABLE_PERMISSIONS = {
    "page_guild_management": {
        "name": "服务器管理 (总览页)",
        "tabs": {
            "tab_members": "成员列表",
            "tab_roles": "身份组列表",
            "tab_economy": "经济系统",
            "tab_tickets": "票据系统",
            "tab_ai_faq": "AI & FAQ",
            "tab_music": "音乐点歌台",
        }
    },
    "page_settings": { 
        "name": "机器人设置"
    },
    "page_moderation": {
        "name": "禁言/审核"
    },
    "page_announcements": {
        "name": "公告发布"
    },
    "page_channel_control": {
        "name": "信道控制"
    },
    "page_audit_core": {
        "name": "内容审查"
    },
    "page_warnings": {
        "name": "纪律协议"
    },
    "page_permissions": {
        "name": "权限管理 (仅服主/开发者)"
    }
}

# --- Web面板权限系统 ---
web_permissions = {}

# 新增：用于存储欢迎消息设置的内存字典
welcome_message_settings = {}

if FLASK_AVAILABLE:
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    web_app = Flask(
        __name__,
        template_folder=os.path.join(_project_root, "templates"),
        static_folder=os.path.join(_project_root, "static"),
    )

    # 自定义Jinja2过滤器，用于在模板中格式化Unix时间戳
    def format_timestamp(timestamp, fmt='%Y-%m-%d %H:%M:%S'):
        if timestamp is None:
            return "N/A"
        try:
            # 将Unix时间戳转换为datetime对象
            dt_object = datetime.datetime.fromtimestamp(int(timestamp))
            return dt_object.strftime(fmt)
        except (ValueError, TypeError):
            # 如果转换失败，返回原始值
            return str(timestamp)

    # 注册自定义过滤器，使其在模板中可用
    web_app.jinja_env.filters['strftime'] = format_timestamp
    
    web_app.jinja_env.filters['strftime'] = format_timestamp

    # ==========================================
    # === ↓↓↓ 核心配置修复 (必须包含) ↓↓↓ ===
    # ==========================================

    # 1. 设置 Secret Key (防止重启掉线)
    _flask_secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not _flask_secret_key:
        logging.critical("FLASK_SECRET_KEY is required for the Web panel.")
    else:
        web_app.secret_key = _flask_secret_key
    
    # 2. 设置 Cookie 安全性 (Lax 比 None 更安全且支持 CSRF)
    web_app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' 
    web_app.config['SESSION_COOKIE_SECURE'] = True 
    web_app.config['SESSION_COOKIE_HTTPONLY'] = True 

    # 3. 【修复报错的关键】初始化 CSRF 保护
    csrf = CSRFProtect(web_app)

    # 4. 代理修正
    web_app.wsgi_app = ProxyFix(
        web_app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

    # ==========================================

    socketio = SocketIO(
        web_app, 
        async_mode='eventlet', 
        cors_allowed_origins=_get_socketio_allowed_origins(),
        path='my-custom-socket-path'
    )
    
#------------------------------------
# ------------------------------------
    # 音乐控制指令处理 (Lavalink + 歌单适配版)
    # ------------------------------------
    @socketio.on('music_command')
    def handle_music_command_socket(data):
        """处理来自网页的音乐控制指令"""
        action = data.get('action') if isinstance(data, dict) else None
        requested_guild_id = data.get('guild_id') if isinstance(data, dict) else None
        sid = request.sid
        logging.warning(
            "[Music Socket] received action=%s guild_id=%s sid=%s",
            action,
            requested_guild_id,
            sid,
        )

        guild_id = _socket_check_auth(data, required_permission="tab_music")
        if guild_id is None:
            logging.warning(
                "[Music Socket] auth failed action=%s guild_id=%s sid=%s",
                action,
                requested_guild_id,
                sid,
            )
            return
        
        user_info = session.get('user', {})
        
        user_id_raw = user_info.get('id')
        # 尝试转换用户ID，如果是 SUPERUSER 则设为 None 或特定处理，这里主要用于数据库存取歌单
        db_user_id = int(user_id_raw) if user_id_raw and str(user_id_raw).isdigit() else 0

        # 2. 异步执行逻辑
        async def execute_music_logic():
            try:
                music_cog = bot.get_cog("音乐播放")
                if not music_cog:
                    if socketio:
                        socketio.emit('music_error', {'message': '音乐模块尚未加载，请检查 MusicCog/Lavalink 启动状态。'}, room=sid)
                    return

                guild = bot.get_guild(guild_id)
                if not guild:
                    if socketio:
                        socketio.emit('music_error', {'message': '服务器未找到。'}, room=sid)
                    return

                player = music_cog.get_player(guild)

                async def connect_music_player(channel):
                    nonlocal player
                    logging.warning(
                        "[Music Socket] connecting player guild=%s channel=%s action=%s",
                        guild_id,
                        getattr(channel, "id", None),
                        action,
                    )
                    player = await music_cog.connect_player(channel)
                    return player

                def music_player_ready(candidate):
                    if not isinstance(candidate, wavelink.Player):
                        return False
                    if not getattr(candidate, "connected", False) or not getattr(candidate, "channel", None):
                        return False
                    try:
                        return candidate.node.status == wavelink.NodeStatus.CONNECTED
                    except Exception:
                        return False

                if player and not music_player_ready(player):
                    player = None

                # === 歌单相关操作 (无需 Player 连接也可以查看/删除，但保存/加载需要) ===
                
                if action == 'playlist_list':
                    import database
                    playlists = database.db_get_user_playlists(db_user_id)
                    if socketio:
                        socketio.emit('playlist_list_update', {'playlists': playlists}, room=sid)
                    return

                elif action == 'playlist_delete':
                    name = data.get('name')
                    import database
                    if database.db_delete_playlist(db_user_id, name):
                        if socketio:
                            socketio.emit('music_error', {'message': f'歌单 "{name}" 已删除', 'type': 'success'}, room=sid)
                            # 刷新列表
                            playlists = database.db_get_user_playlists(db_user_id)
                            socketio.emit('playlist_list_update', {'playlists': playlists}, room=sid)
                    return

                # --- 以下操作需要 Player 存在 ---
                if action == 'playlist_save':
                    if not player or (player.queue.is_empty and not player.current):
                        if socketio: socketio.emit('music_error', {'message': '队列为空，无法保存'}, room=sid)
                        return
                    
                    name = data.get('name')
                    if not name: return

                    # 收集歌曲信息
                    tracks_to_save = []
                    if player.current:
                        tracks_to_save.append({'uri': player.current.uri, 'title': player.current.title, 'author': player.current.author})
                    for track in player.queue:
                        tracks_to_save.append({'uri': track.uri, 'title': track.title, 'author': track.author})

                    import database
                    success, msg = database.db_save_queue_to_playlist(db_user_id, name, tracks_to_save)
                    
                    type_str = 'success' if success else 'error'
                    if socketio: socketio.emit('music_error', {'message': msg, 'type': type_str}, room=sid)
                    return

                elif action == 'playlist_load':
                    name = data.get('name')
                    
                    # 如果未连接，先尝试自动加入
                    if not player:
                        target_channel_id = data.get('target_channel_id') # 前端需要传这个，或者后端自动找
                        if target_channel_id:
                            try:
                                ch = guild.get_channel(int(target_channel_id))
                            except (TypeError, ValueError):
                                ch = None
                            if ch and isinstance(ch, discord.VoiceChannel):
                                player = await connect_music_player(ch)

                        # 如果还没连接上 (且没传ID或ID无效)，尝试找第一个有人的频道
                        if not player:
                             for vc in guild.voice_channels:
                                if len(vc.members) > 0:
                                    player = await connect_music_player(vc)
                                    break
                    
                    if not player:
                        if socketio: socketio.emit('music_error', {'message': '请先让机器人加入语音频道'}, room=sid)
                        return

                    import database
                    track_uris = database.db_load_playlist_tracks(db_user_id, name)
                    if not track_uris:
                        if socketio: socketio.emit('music_error', {'message': '歌单为空或不存在'}, room=sid)
                        return

                    if socketio: socketio.emit('music_error', {'message': f'正在加载歌单 "{name}" ({len(track_uris)} 首)...', 'type': 'success'}, room=sid)

                    # 异步加载
                    count = 0
                    for uri in track_uris:
                        try:
                            tracks = await music_cog.search_tracks(uri)
                            if tracks:
                                t = tracks[0] if isinstance(tracks, list) else tracks.tracks[0]
                                await player.queue.put_wait(t)
                                count += 1
                        except: continue
                    
                    if player.paused:
                        await player.pause(False)
                    if (not player.current or not music_cog.is_effectively_playing(player)) and not player.queue.is_empty:
                        next_track = player.queue.get()
                        logging.warning(
                            "[Music Socket] starting playlist track guild=%s title=%s",
                            guild_id,
                            getattr(next_track, "title", "unknown"),
                        )
                        await player.play(next_track)
                        music_cog.schedule_playback_health_check(guild_id, "web_playlist_load")
                    elif player.current:
                        logging.warning(
                            "[Music Socket] playlist loaded while current active guild=%s current=%s queue_size=%s",
                            guild_id,
                            getattr(player.current, "title", "unknown"),
                            len(player.queue),
                        )
                        music_cog.schedule_playback_health_check(guild_id, "web_playlist_existing")

                    await music_cog.broadcast_music_state(guild_id)
                    return


                # === 播放控制操作 ===
                
                if action == 'join':
                    target_channel_id = data.get('target_channel_id')
                    if not target_channel_id:
                        if socketio:
                            socketio.emit('music_error', {'message': '请选择一个语音频道。'}, room=sid)
                        return
                    channel = guild.get_channel(int(target_channel_id))
                    if not channel or not isinstance(channel, discord.VoiceChannel):
                        if socketio:
                            socketio.emit('music_error', {'message': '找不到选中的语音频道。'}, room=sid)
                        return

                    bot_member = guild.me or guild.get_member(bot.user.id)
                    if not bot_member:
                        if socketio:
                            socketio.emit('music_error', {'message': '无法获取机器人在服务器中的成员状态，请稍后重试。'}, room=sid)
                        return
                    permissions = channel.permissions_for(bot_member)
                    missing_permissions = []
                    if not permissions.connect:
                        missing_permissions.append('连接')
                    if not permissions.speak:
                        missing_permissions.append('说话')
                    if missing_permissions:
                        if socketio:
                            socketio.emit(
                                'music_error',
                                {'message': f'机器人在 #{channel.name} 缺少权限: {", ".join(missing_permissions)}。'},
                                room=sid,
                            )
                        return

                    player = await connect_music_player(channel)
                    if socketio:
                        socketio.emit('music_error', {'message': f'已加入 #{channel.name}', 'type': 'success', 'action': 'join'}, room=sid)
                    await music_cog.broadcast_music_state(guild_id)

                elif action == 'play':
                    query = (data.get('query') or '').strip()
                    if not query:
                        if socketio: socketio.emit('music_error', {'message': '请输入要播放的歌曲或链接'}, room=sid)
                        return
                    if not player:
                        if socketio: socketio.emit('music_error', {'message': '请先在右上角选择频道并点击“加入”'}, room=sid)
                        return

                    tracks = await music_cog.search_tracks(query)

                    if not tracks:
                        if socketio: socketio.emit('music_error', {'message': '未找到歌曲'}, room=sid)
                        return

                    if isinstance(tracks, wavelink.Playlist):
                        await player.queue.put_wait(tracks)
                    else:
                        track = tracks[0]
                        await player.queue.put_wait(track)

                    if player.paused:
                        await player.pause(False)
                    if (not player.current or not music_cog.is_effectively_playing(player)) and not player.queue.is_empty:
                        next_track = player.queue.get()
                        logging.warning(
                            "[Music Socket] starting track guild=%s title=%s",
                            guild_id,
                            getattr(next_track, "title", "unknown"),
                        )
                        await player.play(next_track)
                        music_cog.schedule_playback_health_check(guild_id, "web_play")
                    elif player.current:
                        logging.warning(
                            "[Music Socket] queued track while current active guild=%s current=%s queue_size=%s",
                            guild_id,
                            getattr(player.current, "title", "unknown"),
                            len(player.queue),
                        )
                        music_cog.schedule_playback_health_check(guild_id, "web_play_existing")

                    await music_cog.broadcast_music_state(guild_id)

                elif action == 'skip':
                    if player and player.playing: await player.skip(force=True)

                elif action == 'stop':
                    if player:
                        music_cog.clear_playback_warning(guild_id)
                        music_cog.cancel_playback_health_check(guild_id)
                        player.queue.clear()
                        await player.skip(force=True)
                        await player.disconnect()
                        await music_cog.broadcast_music_state(guild_id)

                elif action == 'volume':
                    level = int(data.get('level', 100))
                    if player:
                        await player.set_volume(level)
                        await music_cog.broadcast_music_state(guild_id)

                elif action == 'loop':
                    if player:
                        # 循环切换: Off -> Song -> Queue -> Off
                        current = player.queue.mode
                        nxt = wavelink.QueueMode.normal
                        if current == wavelink.QueueMode.normal: nxt = wavelink.QueueMode.loop
                        elif current == wavelink.QueueMode.loop: nxt = wavelink.QueueMode.loop_all
                        
                        player.queue.mode = nxt
                        await music_cog.broadcast_music_state(guild_id)

                elif action == 'get_state':
                    await music_cog.broadcast_music_state(guild_id)

            except RuntimeError as e:
                logging.warning("[Music Socket] Action '%s' failed: %s", action, e)
                if socketio:
                    socketio.emit('music_error', {'message': str(e)}, room=sid)
            except Exception as e:
                logging.exception(f"[Music Socket] Failed to handle action '{action}': {e}")
                if socketio:
                    socketio.emit('music_error', {'message': f'音乐操作失败: {e}'}, room=sid)

        asyncio.run_coroutine_threadsafe(execute_music_logic(), bot.loop)

    # ==========================================
    # ==  ↓↓↓ 新增：网页语音指挥官逻辑 ↓↓↓  ==
    # ==========================================
    # 注意：下面所有代码都要有缩进，与上面的 socketio 对齐

# 1. 控制机器人进出语音 (带调试日志修复版)
    @socketio.on('voice_control_join')
    def handle_voice_join(data):
        guild_id = _socket_check_auth(data, required_permission="page_channel_control")
        channel_id = _parse_socket_int(data, 'channel_id')
        sid = request.sid
        if guild_id is None or channel_id is None:
            if socketio:
                socketio.emit('voice_control_error', {'message': '鉴权失败或频道ID无效。'}, room=sid)
            return
        print(f"\n[DEBUG SOCKET] >>> 收到 voice_control_join 请求: guild={guild_id}, channel={channel_id}")

        async def join_task():
            print(f"[DEBUG SOCKET] 开始执行 join_task (Guild: {guild_id}, Channel: {channel_id})")
            guild = bot.get_guild(guild_id)
            if not guild:
                if socketio:
                    socketio.emit('voice_control_error', {'message': '找不到服务器对象。'}, room=sid)
                return
                
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                if socketio:
                    socketio.emit('voice_control_error', {'message': '找不到选中的语音频道。'}, room=sid)
                return

            try:
                # Channel Control is for TTS/recorded broadcasts, so use native Discord voice.
                bot_member = guild.me or guild.get_member(bot.user.id)
                if not bot_member:
                    if socketio:
                        socketio.emit('voice_control_error', {'message': '无法获取机器人在服务器中的成员状态，请稍后重试。'}, room=sid)
                    return

                permissions = channel.permissions_for(bot_member)
                missing_permissions = []
                if not permissions.connect:
                    missing_permissions.append('连接')
                if not permissions.speak:
                    missing_permissions.append('说话')
                if missing_permissions:
                    if socketio:
                        socketio.emit(
                            'voice_control_error',
                            {'message': f'机器人在 #{channel.name} 缺少权限: {", ".join(missing_permissions)}。'},
                            room=sid,
                        )
                    return

                voice_ok, voice_message = ensure_discord_voice_runtime()
                if not voice_ok:
                    logging.error("[VOICE_RUNTIME] Native voice unavailable before join: %s", voice_message)
                    if socketio:
                        socketio.emit('voice_control_error', {'message': f'Discord 语音依赖不可用: {voice_message}'}, room=sid)
                    return
                logging.warning(
                    "[VOICE_RUNTIME] before_join has_nacl=%s status=%s",
                    discord_voice_client.has_nacl,
                    voice_message,
                )

                if isinstance(guild.voice_client, wavelink.Player):
                    await guild.voice_client.disconnect()
                    await channel.connect()
                elif guild.voice_client:
                    await guild.voice_client.move_to(channel)
                else:
                    await channel.connect()
                print("[DEBUG SOCKET] ✅ 原生语音连接成功")

                # 通知前端状态更新
                if socketio:
                    socketio.emit('voice_status_update', {'status': 'connected', 'channel_name': channel.name}, room=f'voice_{guild_id}')
                    socketio.emit('voice_control_status', {'message': f'已连接到 #{channel.name}'}, room=sid)
                    
            except Exception as e:
                logging.exception(f"[Voice Control] Failed to join voice channel {channel_id}: {e}")
                if socketio:
                    socketio.emit('voice_control_error', {'message': f'连接语音频道失败: {e}'}, room=sid)

        # 提交任务到 Discord 事件循环
        if bot.loop and not bot.loop.is_closed():
            asyncio.run_coroutine_threadsafe(join_task(), bot.loop)
        else:
            print("[DEBUG SOCKET] ❌ 致命错误：Bot 事件循环未运行或已关闭")

    @socketio.on('voice_control_leave')
    def handle_voice_leave(data):
        guild_id = _socket_check_auth(data, required_permission="page_channel_control")
        sid = request.sid
        if guild_id is None:
            return
        async def leave_task():
            guild = bot.get_guild(guild_id)
            if not guild or not guild.voice_client:
                if socketio:
                    socketio.emit('voice_control_error', {'message': '机器人当前未连接语音频道。'}, room=sid)
                return
            await guild.voice_client.disconnect()
            
            if socketio:
                socketio.emit('voice_status_update', {'status': 'disconnected'}, room=f'voice_{guild_id}')
                socketio.emit('voice_control_status', {'message': '已断开语音连接。'}, room=sid)
                
        asyncio.run_coroutine_threadsafe(leave_task(), bot.loop)

    # 2. TTS 说话 (文字转语音)
    @socketio.on('voice_control_tts')
    def handle_voice_tts(data):
        guild_id = _socket_check_auth(data, required_permission="page_channel_control")
        sid = request.sid
        if guild_id is None:
            return
        text = (data.get('text') or '').strip()
        if not text:
            if socketio:
                socketio.emit('voice_control_error', {'message': '请输入要朗读的文字。'}, room=sid)
            return
        
        async def play_tts():
            guild = bot.get_guild(guild_id)
            if not guild or not guild.voice_client or not guild.voice_client.is_connected():
                if socketio:
                    socketio.emit('voice_control_error', {'message': '请先让机器人加入一个语音频道。'}, room=sid)
                return # 未连接语音

            filename = None
            try:
                # 生成 TTS 文件
                voice = "zh-CN-XiaoxiaoNeural" # 微软高质量女声
                communicate = edge_tts.Communicate(text, voice)
                filename = f"tts_{guild_id}_{int(time.time())}.mp3"
                await communicate.save(filename)

                # 播放
                if guild.voice_client.is_playing():
                    guild.voice_client.stop()
                
                # 使用 FFmpeg 播放
                guild.voice_client.play(discord.FFmpegPCMAudio(filename), after=lambda e: os.remove(filename) if os.path.exists(filename) else None)
                if socketio:
                    socketio.emit('voice_control_status', {'message': 'TTS 已发送。'}, room=sid)
            except Exception as e:
                logging.exception(f"[Voice Control] TTS playback failed: {e}")
                if filename and os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except OSError:
                        pass
                if socketio:
                    socketio.emit('voice_control_error', {'message': f'TTS 播放失败: {e}'}, room=sid)

        asyncio.run_coroutine_threadsafe(play_tts(), bot.loop)

    # 3. 发送语音 (浏览器录音上传)
    @socketio.on('voice_control_blob')
    def handle_voice_blob(data):
        guild_id = _socket_check_auth(data, required_permission="page_channel_control")
        sid = request.sid
        if guild_id is None:
            return
        audio_data = data.get('audio_blob') 
        if not audio_data:
            if socketio:
                socketio.emit('voice_control_error', {'message': '没有收到录音数据。'}, room=sid)
            return
        
        async def play_blob():
            guild = bot.get_guild(guild_id)
            if not guild or not guild.voice_client or not guild.voice_client.is_connected():
                if socketio:
                    socketio.emit('voice_control_error', {'message': '请先让机器人加入一个语音频道。'}, room=sid)
                return

            filename = None
            try:
                # 保存为临时文件
                filename = f"rec_{guild_id}_{int(time.time())}.webm"
                with open(filename, "wb") as f:
                    f.write(audio_data)

                if guild.voice_client.is_playing():
                    guild.voice_client.stop()

                # FFmpeg 可以直接播放 WebM
                guild.voice_client.play(discord.FFmpegPCMAudio(filename), after=lambda e: os.remove(filename) if os.path.exists(filename) else None)
                if socketio:
                    socketio.emit('voice_control_status', {'message': '语音广播已发送。'}, room=sid)
            except Exception as e:
                logging.exception(f"[Voice Control] Recorded voice playback failed: {e}")
                if filename and os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except OSError:
                        pass
                if socketio:
                    socketio.emit('voice_control_error', {'message': f'语音广播播放失败: {e}'}, room=sid)

        asyncio.run_coroutine_threadsafe(play_blob(), bot.loop)

    # ==========================================
    # ==  ↑↑↑ 新增代码结束 ↑↑↑  ==
    # ==========================================

    # --- 新的辅助函数，用于在后端计算用户权限 ---
    def get_user_permissions(user_info, guild_id):
        if not user_info or not guild_id:
            return []
        
        all_possible_perms = list(AVAILABLE_PERMISSIONS.keys())
        for data in AVAILABLE_PERMISSIONS.values():
            if "tabs" in data:
                all_possible_perms.extend(data["tabs"].keys())

        if user_info.get('is_superuser'):
            return all_possible_perms
        
        if user_info.get('is_sub_account'):
            perms = user_info.get('permissions', {})
            granted_perms = set(perms.get('global_permissions', []))
            
            if perms.get('can_manage_all_guilds'):
                return all_possible_perms
            elif str(guild_id) in perms.get('guilds', []):
                # 副账号如果能访问服务器，则授予其下所有标签页权限 (这是针对副账号的特定逻辑)
                granted_perms.add("page_guild_management")
                granted_perms.update(AVAILABLE_PERMISSIONS["page_guild_management"]["tabs"].keys())
            
            return list(granted_perms)

        # --- 普通 Discord 用户权限计算 ---
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return []
        
        user_id = user_info.get('id')
        if not user_id:
            return []
        try:
            member = guild.get_member(int(user_id))
        except (ValueError, TypeError):
            return []
            
        if not member:
            return []

        # 服务器所有者或管理员拥有所有权限
        if member.id == guild.owner_id or member.guild_permissions.administrator:
            return all_possible_perms

        user_role_ids = {str(role.id) for role in member.roles}
        guild_web_perms = web_permissions.get(guild_id, {})
        
        # 1. 直接从角色配置中获取所有授予的权限
        granted_perms = set()
        for role_id in user_role_ids:
            if role_id in guild_web_perms:
                granted_perms.update(guild_web_perms[role_id].get("permissions", []))
        
        # 2. 【【【核心修复】】】如果用户拥有任何一个子标签页的权限，则自动为他们添加父页面的访问权，
        # 这样他们才能看到父级导航菜单。但反之则不然。
        if any(p.startswith("tab_") for p in granted_perms):
             granted_perms.add("page_guild_management")
        
        return list(granted_perms)

    # --- 只有在 Flask 可用时才定义路由 ---
    def check_auth(guild_id=None, required_permission=None):
        if 'user' not in session or 'id' not in session.get('user', {}):
            return False, ("会话无效或已过期，请重新登录。", 401)
        
        user_info = session.get('user', {})
        if user_info.get('is_superuser'):
            return True, None
        
        if user_info.get('is_sub_account'):
            if guild_id is None and required_permission is None:
                return True, None
            
            perms = user_info.get('permissions', {})
            can_manage_all = perms.get('can_manage_all_guilds', False)
            allowed_guilds = perms.get('guilds', [])
            
            if guild_id and not can_manage_all and str(guild_id) not in allowed_guilds:
                return False, (f"副账号无权访问服务器 {guild_id}", 403)
    
            if required_permission:
                user_granted_perms = get_user_permissions(user_info, guild_id)
                if required_permission not in user_granted_perms:
                    perm_name = "未知页面"
                    for page_id, page_data in AVAILABLE_PERMISSIONS.items():
                        if page_id == required_permission: perm_name = page_data['name']; break
                        if 'tabs' in page_data and required_permission in page_data['tabs']: perm_name = page_data['tabs'][required_permission]; break
                    return False, (f"您没有访问 '{perm_name}' 的权限。", 403)
            return True, None
        
        else: # 普通 Discord 用户
            user_id_str = str(user_info.get('id'))
            if guild_id is None:
                return True, None
            guild = bot.get_guild(guild_id)
            if not guild:
                return False, ("机器人不在该服务器中或服务器ID无效。", 404)
            try: member = guild.get_member(int(user_id_str))
            except (ValueError, TypeError): return False, ("无效的用户ID格式。", 400)
            if not member: return False, ("您不是该服务器的成员。", 403)
            if member.id == guild.owner_id or member.guild_permissions.administrator: return True, None
            if required_permission is None: return True, None
            granted_perms_discord = get_user_permissions(user_info, guild_id)
            if required_permission in granted_perms_discord: return True, None
        
        perm_name = "未知页面"
        for page_id, page_data in AVAILABLE_PERMISSIONS.items():
            if page_id == required_permission: perm_name = page_data['name']; break
            if 'tabs' in page_data and required_permission in page_data['tabs']: perm_name = page_data['tabs'][required_permission]; break
        return False, (f"您没有访问 '{perm_name}' 的权限。", 403)

    def _parse_socket_int(data, key):
        try:
            return int(data.get(key))
        except (TypeError, ValueError, AttributeError):
            return None

    def _socket_check_auth(data, required_permission=None, emit_event='music_error'):
        guild_id = _parse_socket_int(data, 'guild_id')
        if guild_id is None:
            socketio.emit(emit_event, {'message': '请求缺少有效的服务器ID。'}, room=request.sid)
            return None
        is_authed, error = check_auth(guild_id, required_permission=required_permission)
        if not is_authed:
            message = error[0] if error else '权限不足。'
            socketio.emit(emit_event, {'message': message}, room=request.sid)
            return None
        return guild_id

    _login_failures = {}
    _LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
    _LOGIN_RATE_LIMIT_MAX_FAILURES = 8

    def _login_rate_limit_key(kind):
        remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        remote_addr = remote_addr.split(",", 1)[0].strip()
        return f"{kind}:{remote_addr}"

    def _is_login_rate_limited(kind):
        now = time.time()
        key = _login_rate_limit_key(kind)
        failures = [
            ts for ts in _login_failures.get(key, [])
            if now - ts < _LOGIN_RATE_LIMIT_WINDOW_SECONDS
        ]
        _login_failures[key] = failures
        return len(failures) >= _LOGIN_RATE_LIMIT_MAX_FAILURES

    def _record_login_failure(kind):
        key = _login_rate_limit_key(kind)
        _login_failures.setdefault(key, []).append(time.time())

    def _clear_login_failures(kind):
        _login_failures.pop(_login_rate_limit_key(kind), None)

    @web_app.context_processor
    def inject_permissions_checker():
        return dict(check_user_web_permissions=get_user_permissions)

    @web_app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(self), geolocation=()",
        )
        return response

    # =======================
    # == OAuth2 & 登录/登出
    # =======================
    @web_app.route('/')
    def index():
        if 'user' in session: 
            return redirect(url_for('dashboard'))
        # 【关键修复】显式传入 user=None 和 guild=None，防止 base.html 报错
        return render_template('index.html', client_id=DISCORD_CLIENT_ID, user=None, guild=None)

    @web_app.route('/login')
    def login_page():
        if 'user' in session: 
            return redirect(url_for('dashboard'))
        oauth_url = DISCORD_OAUTH2_URL
        if DISCORD_CLIENT_ID and DISCORD_REDIRECT_URI:
            oauth_state = secrets.token_urlsafe(32)
            session['oauth_state'] = oauth_state
            oauth_url = (
                "https://discord.com/api/oauth2/authorize?"
                f"client_id={DISCORD_CLIENT_ID}"
                f"&redirect_uri={urllib.parse.quote(DISCORD_REDIRECT_URI)}"
                "&response_type=code"
                "&scope=identify%20guilds"
                f"&state={oauth_state}"
            )
        # 【关键修复】显式传入 user=None 和 guild=None，防止 base.html 报错
        return render_template('login.html', oauth_url=oauth_url, user=None, guild=None)

    @web_app.route('/superuser_login', methods=['POST'])
    def superuser_login():
        if _is_login_rate_limited("superuser"):
            flash('登录尝试过多，请稍后再试。', 'danger')
            return redirect(url_for('login_page'))
        supplied_password = request.form.get('password') or ""
        expected_password = WEB_ADMIN_PASSWORD or ""
        if expected_password and hmac.compare_digest(supplied_password, expected_password):
            _clear_login_failures("superuser")
            session.clear()
            session['user'] = {'id': 'SUPERUSER', 'username': '应用开发者', 'avatar': bot.user.display_avatar.url, 'is_superuser': True}
            return redirect(url_for('dashboard'))
        
        _record_login_failure("superuser")
        flash('开发者密码错误。', 'danger')
        return redirect(url_for('login_page')) 

    @web_app.route('/sub_account_login', methods=['POST'])
    def sub_account_login():
        if _is_login_rate_limited("sub_account"):
            flash('登录尝试过多，请稍后再试。', 'danger')
            return redirect(url_for('login_page'))
        access_key = request.form.get('access_key')
        if not access_key:
            _record_login_failure("sub_account")
            flash('请输入访问密钥。', 'warning')
            return redirect(url_for('login_page'))
        
        account_data = database.db_validate_access_key(access_key)
        if account_data:
            _clear_login_failures("sub_account")
            session.clear()
            session['user'] = {
                'id': f"sub_{account_data['id']}",
                'username': account_data['account_name'],
                'avatar': bot.user.display_avatar.url,
                'is_sub_account': True,
                'permissions': account_data['permissions']
            }
            return redirect(url_for('dashboard'))
        else:
            _record_login_failure("sub_account")
            flash('无效的访问密钥。', 'danger')
            return redirect(url_for('login_page'))

    @web_app.route('/callback')
    def callback():
        code = request.args.get('code')
        if not code: return "授权错误", 400
        callback_state = request.args.get('state')
        expected_state = session.pop('oauth_state', None)
        if not expected_state or not callback_state or callback_state != expected_state:
            logging.warning("OAuth callback rejected because state validation failed.")
            return "授权状态无效，请重新登录。", 400
        
        token_data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET,'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI}
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            token_r = req.post('https://discord.com/api/oauth2/token', data=token_data, headers=headers)
            if token_r.status_code != 200:
                logging.warning(f"Discord OAuth token exchange failed with status {token_r.status_code}.")
                return "获取Token失败，请重新登录。", 500
            
            user_headers = {'Authorization': f"Bearer {token_r.json()['access_token']}"}
            user_r = req.get('https://discord.com/api/users/@me', headers=user_headers)
            user_guilds_r = req.get('https://discord.com/api/users/@me/guilds', headers=user_headers)
            
            if user_r.status_code != 200 or user_guilds_r.status_code != 200: return "获取用户信息失败", 500
            
            user_info, user_guilds_from_api = user_r.json(), user_guilds_r.json()
            user_id = int(user_info['id'])
            
            bot_guild_ids = {g.id for g in bot.guilds}
            managed_guilds = []

            for g_api in user_guilds_from_api:
                guild_id = int(g_api['id'])
                
                # 筛选逻辑
                if guild_id not in bot_guild_ids: continue
                
                has_admin = int(g_api['permissions']) & 0x8
                has_web_perm = False
                
                if not has_admin:
                    guild_web_perms = web_permissions.get(guild_id, {})
                    if guild_web_perms:
                        guild_obj = bot.get_guild(guild_id)
                        if guild_obj:
                            member = guild_obj.get_member(user_id)
                            if member:
                                member_role_ids = {str(role.id) for role in member.roles}
                                if any(role_id in guild_web_perms for role_id in member_role_ids):
                                    has_web_perm = True

                if has_admin or has_web_perm:
                    managed_guilds.append(g_api)

            session.clear()
            session['user'] = { 
                'id': user_info['id'], 
                'username': user_info['username'], 
                'avatar': f"https://cdn.discordapp.com/avatars/{user_info['id']}/{user_info['avatar']}.png", 
                'is_superuser': False, 
                'guilds': managed_guilds 
            }
            return redirect(url_for('dashboard'))
        except Exception as e:
            logging.error(f"Callback error: {e}")
            return "登录过程中发生错误", 500

    @web_app.route('/logout')
    def logout():
        session.clear()
        flash('您已成功登出。', 'success')
        return redirect(url_for('index'))

    # =======================
    # == 页面渲染
    # =======================

    @web_app.route('/superuser/broadcast')
    def superuser_broadcast_page():
        user_info = session.get('user', {})
        if not user_info.get('is_superuser'):
            flash("您无权访问此页面。", "danger")
            return redirect(url_for('dashboard'))
    
        all_guilds = [{'id': g.id, 'name': g.name} for g in bot.guilds]
        return render_template('superuser_broadcast.html', title="全局广播", user=user_info, guilds=all_guilds)
    
    @web_app.route('/dashboard')
    def dashboard():
        is_authed, error = check_auth()
        if not is_authed:
            if error: flash(error[0], 'danger')
            return redirect(url_for('index'))
        user_info = session['user']
        guilds_data = []
        if user_info.get('is_superuser'):
            guilds_data = sorted([{'id': g.id, 'name': g.name} for g in bot.guilds], key=lambda x: x['name'])
        elif user_info.get('is_sub_account'):
            perms = user_info.get('permissions', {})
            if perms.get('can_manage_all_guilds'):
                guilds_data = sorted([{'id': g.id, 'name': g.name} for g in bot.guilds], key=lambda x: x['name'])
            else:
                allowed_ids = {int(gid) for gid in perms.get('guilds', [])}
                guilds_data = sorted([{'id': g.id, 'name': g.name} for g in bot.guilds if g.id in allowed_ids], key=lambda x: x['name'])
        else:
            guilds_data = sorted(user_info.get('guilds', []), key=lambda x: x['name'])
        config_status = { 'deepseek_ok': bool(DEEPSEEK_API_KEY), 'alipay_sdk_ok': ALIPAY_SDK_AVAILABLE, 'alipay_client_ok': alipay_client is not None, 'restart_pass_ok': bool(RESTART_PASSWORD) }
        return render_template('dashboard.html', title="仪表盘", user=user_info, guilds=guilds_data, config_status=config_status)

    @web_app.route('/guild/<int:guild_id>')
    def guild_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_guild_management")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        members_data = [{'id': str(m.id), 'name': m.display_name, 'avatar_url': str(m.display_avatar.url), 'joined_at': m.joined_at.strftime('%Y-%m-%d') if m.joined_at else 'N/A'} for m in guild.members if not m.bot][:10000]
        members_data.sort(key=lambda x: x['name'].lower())
        roles_data = sorted([{'id': str(r.id), 'name': r.name, 'color': str(r.color), 'member_count': len(r.members)} for r in guild.roles if r.name != '@everyone'], key=lambda x: x['name'].lower())
        return render_template('guild.html', title=guild.name, user=user_info, guild=guild, members=members_data, roles=roles_data, user_perms=user_perms, DISCORD_PERMISSIONS=DISCORD_PERMISSIONS)

    @web_app.route('/guild/<int:guild_id>/settings')
    def settings_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_settings")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        roles_data = sorted([{'id': str(r.id), 'name': r.name} for r in guild.roles if r.name != "@everyone"], key=lambda x: x.get('name', '').lower())
        text_channels_data = sorted(guild.text_channels, key=lambda c: c.name)
        voice_channels_data = sorted(guild.voice_channels, key=lambda c: c.name)
        categories_data = sorted(guild.categories, key=lambda c: c.name)
        settings_data = {
            'ticket': ticket_settings.get(guild_id, {}), 
            'general': general_settings.get(guild_id, {}),
            'temp_vc': temp_vc_settings.get(guild_id, {})
        }
        is_owner = (not user_info.get('is_sub_account') and not user_info.get('is_superuser') and str(user_info.get('id')) == str(guild.owner_id)) or user_info.get('is_superuser')
        return render_template('settings.html', title="机器人设置", user=user_info, guild=guild, roles=roles_data, text_channels=text_channels_data, voice_channels=voice_channels_data, categories=categories_data, settings=settings_data, is_owner=is_owner, user_perms=user_perms)

    @web_app.route('/guild/<int:guild_id>/moderation')
    def moderation_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_moderation")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        members_data = sorted([m for m in guild.members if not m.bot], key=lambda m: m.display_name)
        return render_template('moderation.html', title="禁言/审核", user=user_info, guild=guild, members=members_data, user_perms=user_perms)

    
    @web_app.route('/guild/<int:guild_id>/tickets')
    def tickets_page(guild_id):
        # 【核心修复】将权限检查从 'page_settings' 改为 'tab_tickets'
        is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
        if not is_authed:
            flash(error[0], 'danger')
            return redirect(url_for('dashboard'))
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return "服务器未找到", 404
        
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)

        # 渲染新的 tickets.html 模板
        return render_template('tickets.html', title="票据系统", user=user_info, guild=guild, user_perms=user_perms)   
        
    @web_app.route('/guild/<int:guild_id>/music')
    def music_control_page(guild_id):
        # 1. 权限检查
        is_authed, error = check_auth(guild_id, required_permission="tab_music")
        if not is_authed:
            flash(error[0], 'danger')
            return redirect(url_for('dashboard'))
        
        # 2. 获取服务器对象
        guild = bot.get_guild(guild_id)
        if not guild:
            return "服务器未找到", 404
        
        # 3. 获取用户信息和权限
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)

        # 4. 获取并排序语音频道列表 (用于网页手动加入功能)
        voice_channels = sorted(
            [vc for vc in guild.voice_channels], 
            key=lambda c: c.position
        )

        # 5. 渲染 music.html 模板 (传入 voice_channels)
        return render_template('music.html', title="音乐点歌台", user=user_info, guild=guild, user_perms=user_perms, voice_channels=voice_channels)
        
        
    
    @web_app.route('/guild/<int:guild_id>/announcements')
    def announcements_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_announcements")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        text_channels_data = sorted(guild.text_channels, key=lambda c: c.name)
        roles_data = sorted([{'id': str(r.id), 'name': r.name} for r in guild.roles if r.name != "@everyone"], key=lambda x: x.get('name', '').lower())
        return render_template('announcements.html', title="公告", user=user_info, guild=guild, text_channels=text_channels_data, roles=roles_data, user_perms=user_perms)
    
    @web_app.route('/channel_control/<int:guild_id>')
    def channel_control_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_channel_control")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        welcome_settings = welcome_message_settings.get(str(guild_id), {})
        text_channels_data = sorted(guild.text_channels, key=lambda c: c.name)
        members_data = sorted([m for m in guild.members if not m.bot], key=lambda m: m.display_name)
        return render_template('channel_control.html', title="信道控制", user=user_info, guild=guild, text_channels=text_channels_data, members=members_data, welcome_settings=welcome_settings, owner_id=str(guild.owner_id), user_perms=user_perms)

    @web_app.route('/audit_core/<int:guild_id>')
    def audit_core_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_audit_core")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        exempt_users_list = [user for uid in exempt_users_from_ai_check if (user := bot.get_user(uid))]
        exempt_channels_list = [channel for cid in exempt_channels_from_ai_check if (channel := guild.get_channel(cid))]
        all_text_channels = sorted(guild.text_channels, key=lambda c: c.name)
        all_members = sorted([m for m in guild.members if not m.bot], key=lambda m: m.display_name)
        return render_template('audit_core.html', title="内容审查核心", user=user_info, guild=guild, exempt_users=exempt_users_list, exempt_channels=exempt_channels_list, all_text_channels=all_text_channels, all_members=all_members, user_perms=user_perms)

    @web_app.route('/warnings/<int:guild_id>')
    def warnings_page(guild_id):
        is_authed, error = check_auth(guild_id, required_permission="page_warnings")
        if not is_authed: flash(error[0], 'danger'); return redirect(url_for('dashboard'))
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        user_info = session['user']
        user_perms = get_user_permissions(user_info, guild_id)
        all_members = sorted([m for m in guild.members if not m.bot], key=lambda m: m.display_name)
        return render_template('warnings.html', title="纪律协议", user=user_info, guild=guild, members=all_members, user_perms=user_perms)
    
    @web_app.route('/permissions/<int:guild_id>')
    def permissions_page(guild_id):
        user_info = session.get('user', {})
        guild = bot.get_guild(guild_id)
        if not guild: return "服务器未找到", 404
        
        is_discord_owner = (not user_info.get('is_sub_account') and not user_info.get('is_superuser') and str(user_info.get('id')) == str(guild.owner_id))
        if not user_info.get('is_superuser') and not is_discord_owner:
            flash("您无权访问此页面。", "danger")
            return redirect(url_for('dashboard'))
        
        user_perms = get_user_permissions(user_info, guild_id)
        roles_data = sorted(
            [{'id': str(r.id), 'name': r.name} for r in guild.roles if r.name != "@everyone" and not r.managed],
            key=lambda x: x['name'].lower()
        )
        return render_template('permissions.html', title="权限管理", user=user_info, guild=guild, roles=roles_data, available_permissions=AVAILABLE_PERMISSIONS, user_perms=user_perms)

    @web_app.route('/guild/<int:guild_id>/backup')
    def backup_page(guild_id):
        user_info = session.get('user', {})
        guild = bot.get_guild(guild_id)
        if not guild:
            return "服务器未找到", 404

        # 权限检查：只有服务器所有者或超级用户才能访问
        is_owner = (not user_info.get('is_sub_account') and str(user_info.get('id')) == str(guild.owner_id))
        if not user_info.get('is_superuser') and not is_owner:
            flash("只有服务器所有者才能访问备份与恢复功能。", "danger")
            return redirect(url_for('dashboard'))

        user_perms = get_user_permissions(user_info, guild_id) # 用于导航栏
        return render_template('backup.html', title="备份与恢复", user=user_info, guild=guild, user_perms=user_perms)
    
    
    @web_app.route('/superuser/accounts')
    def superuser_accounts_page():
        user_info = session.get('user', {})
        if not user_info.get('is_superuser'):
            flash("您无权访问此页面。", "danger")
            return redirect(url_for('dashboard'))
        
        all_guilds = [{'id': g.id, 'name': g.name} for g in bot.guilds]
        return render_template('superuser_accounts.html', title="副账号管理", user=user_info, guilds=all_guilds)

    # =======================
    # == API & SocketIO
    # =======================

    @socketio.on('start_restore')
    def handle_start_restore(data):
        """
        处理由前端发起的恢复请求的Socket.IO事件。
        【V5 - 最终健壮性修复版】
        - 由后端直接解析JSON字符串，彻底避免JS数字精度问题。
        - 在找不到缓存时，主动从API获取服务器对象。
        - 使用 asyncio.run_coroutine_threadsafe 在 eventlet 线程中安全地调度 asyncio 任务。
        """
        # 使用 with web_app.app_context() 来确保可以安全访问 Flask 的 session
        with web_app.app_context():
            print('\n[DEBUG-RESTORE] 1. 后端 @socketio.on("start_restore") 事件处理器【已触发】！')
        
        # --- 变量获取与验证 ---
        sid = request.sid
        user_info = session.get('user', {})
        if not user_info:
            socketio.emit('restore_progress', {'message': '错误：会话无效，请重新登录。', 'type': 'error'}, room=sid)
            return
        
        try:
            # 【重要】从前端接收到的 guild_id 已经是正确的字符串了，这里直接用
            guild_id_str = data.get('guild_id')
            if not guild_id_str or not guild_id_str.isdigit():
                 raise ValueError("请求中缺少有效的服务器ID字符串。")
            guild_id = int(guild_id_str)

            # 从新的字段 backup_data_str 获取文件字符串
            backup_data_str = data.get('backup_data_str')
            if not backup_data_str:
                raise ValueError("请求中缺少备份文件内容字符串。")
            
            # 由Python后端来解析JSON，Python没有JS的数字精度问题
            backup_data = json.loads(backup_data_str)
            
            confirmation = data.get('confirmation')
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
            msg = f"错误：从前端接收到的数据格式不正确或JSON解析失败。({e})"
            print(f"[DEBUG-RESTORE] {msg}")
            socketio.emit('restore_progress', {'message': msg, 'type': 'error'}, room=sid)
            return

        print(f"[DEBUG-RESTORE] > 收到的 Guild ID: {guild_id}")

        # --- 【核心】检查缓存，如果找不到则主动从API获取 ---
        guild = bot.get_guild(guild_id)
        if not guild:
            print(f"[DEBUG-RESTORE] > 缓存中未找到服务器 {guild_id}。正在尝试从 Discord API 主动获取...")
            try:
                # 我们在一个同步函数中，所以需要用 run_coroutine_threadsafe 来调用异步的 fetch_guild
                future = asyncio.run_coroutine_threadsafe(bot.fetch_guild(guild_id), bot.loop)
                guild = future.result(timeout=10) # 等待最多10秒
                print(f"[DEBUG-RESTORE] > 从 API 成功获取到服务器: {guild.name}")
            except Exception as e:
                msg = f"错误：无法从缓存或API中找到服务器ID {guild_id}。请确保机器人在此服务器中且Intents配置正确。错误: {e}"
                print(f"[DEBUG-RESTORE] {msg}")
                socketio.emit('restore_progress', {'message': msg, 'type': 'error'}, room=sid)
                return
        else:
            print(f"[DEBUG-RESTORE] > 从缓存中成功找到服务器: {guild.name}")

        # --- 权限检查 ---
        is_owner = (not user_info.get('is_sub_account') and str(user_info.get('id')) == str(guild.owner_id))
        if not user_info.get('is_superuser') and not is_owner:
            msg = "错误：权限不足，只有服务器所有者或超级用户才能执行此操作。"
            print(f"[DEBUG-RESTORE] {msg} (用户: {user_info.get('username')})")
            socketio.emit('restore_progress', {'message': msg, 'type': 'error'}, room=sid)
            return
            
        expected_confirmation = f"{guild.name}/RESTORE"
        if not confirmation or confirmation.strip() != expected_confirmation.strip():
            msg = "错误：确认短语不匹配！"
            print(f"[DEBUG-RESTORE] {msg} (需要: '{expected_confirmation}', 收到: '{confirmation.strip()}')")
            socketio.emit('restore_progress', {'message': msg, 'type': 'error'}, room=sid)
            return
            
        # --- 【【【核心修复点】】】 ---
        # 启动后台任务。不再使用 socketio.start_background_task
        # 而是使用 asyncio.run_coroutine_threadsafe 将 asyncio 任务提交给 discord.py 的事件循环
        print(f'[DEBUG-RESTORE] 验证全部通过，准备将恢复任务提交到 asyncio 事件循环...')
        asyncio.run_coroutine_threadsafe(
            _perform_restore_async(
                guild_id=guild_id, 
                backup_data=backup_data, 
                sid=sid
            ), 
            bot.loop  # bot.loop 就是 discord.py 正在运行的 asyncio 事件循环
        )
        print('[DEBUG-RESTORE] 恢复任务已成功提交。')
        # --- 【【【核心修复点结束】】】 ---


    
    @socketio.on('connect')
    def handle_connect():
        if 'user' in session:
            print(f"Socket.IO authenticated user '{session['user'].get('username', 'Unknown')}'.")
        else:
            print("No 'user' in session. Disconnecting socket.")
            disconnect()

    @socketio.on('disconnect')
    def handle_disconnect():
        pass

    @socketio.on('join_audit_room')
    def handle_join_room(data):
        guild_id = _parse_socket_int(data, 'guild_id')
        if guild_id is None:
            socketio.emit('ticket_error', {'message': '请求缺少有效的服务器ID。'}, room=request.sid)
            return
        is_authed, error = check_auth(guild_id, required_permission="page_audit_core")
        if not is_authed:
            socketio.emit('ticket_error', {'message': error[0] if error else '权限不足。'}, room=request.sid)
            return
        join_room(f'audit_{guild_id}')

    @socketio.on('join_tickets_room')
    def handle_join_tickets_room(data):
        guild_id = _parse_socket_int(data, 'guild_id')
        if guild_id is None:
            socketio.emit('ticket_error', {'message': '请求缺少有效的服务器ID。'}, room=request.sid)
            return
        is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
        if not is_authed:
            socketio.emit('ticket_error', {'message': error[0] if error else '权限不足。'}, room=request.sid)
            return
        join_room(f'tickets_{guild_id}')

    @socketio.on('join_music_room')
    def handle_join_music_room(data):
        guild_id = _socket_check_auth(data, required_permission="tab_music", emit_event='music_error')
        if guild_id is None:
            return
        join_room(f'music_{guild_id}')

    @socketio.on('join_voice_room')
    def handle_join_voice_room(data):
        guild_id = _socket_check_auth(data, required_permission="page_channel_control", emit_event='music_error')
        if guild_id is None:
            return
        join_room(f'voice_{guild_id}')

    @socketio.on('join_ticket_room')
    def handle_join_ticket_room(data):
        channel_id = _parse_socket_int(data, 'channel_id')
        if channel_id is None:
            socketio.emit('ticket_error', {'message': '请求缺少有效的频道ID。'}, room=request.sid)
            return
        ticket_info = database.db_get_ticket_by_channel(channel_id)
        if not ticket_info:
            socketio.emit('ticket_error', {'message': '票据不存在。'}, room=request.sid)
            return
        guild_id = int(ticket_info['guild_id'])
        is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
        if not is_authed:
            socketio.emit('ticket_error', {'message': error[0] if error else '权限不足。'}, room=request.sid)
            return
        join_room(f'ticket_{channel_id}')
        
    @socketio.on('send_ticket_reply')
    def handle_send_ticket_reply(data):
        with web_app.app_context():
           print(f"--- Received 'send_ticket_reply' event ---")

           try:
               guild_id_int = int(data.get('guild_id'))
               channel_id_int = int(data.get('channel_id'))
           except (ValueError, TypeError):
               print(f"[Socket.IO Auth Error] Invalid guild_id/channel_id received.")
               return
  
           is_authed, error = check_auth(guild_id_int, required_permission="tab_tickets")

           if not is_authed:
               print(f"[Socket.IO Auth Error] User '{session.get('user',{}).get('username')}' failed to send ticket reply. Reason: {error[0] if error else 'Unknown'}")
               return

           ticket_info = database.db_get_ticket_by_channel(channel_id_int)
           if not ticket_info or int(ticket_info.get('guild_id')) != guild_id_int:
               print(f"[Socket.IO Auth Error] Ticket channel {channel_id_int} is not in guild {guild_id_int}.")
               socketio.emit('ticket_error', {'message': '票据频道无效或不属于当前服务器。'}, room=request.sid)
               return
             
           print("[Ticket Reply] Authentication successful. Calling send_reply_to_discord...")
        # 【重要】确保这里也传递整数类型的 guild_id
           asyncio.run_coroutine_threadsafe(send_reply_to_discord(guild_id_int, channel_id_int, session.get('user', {}), data.get('content')), bot.loop)
        

    @web_app.route('/api/stats')
    def api_stats():
        is_authed, _ = check_auth()
        if not is_authed: return jsonify(error="未授权"), 401
        if not bot.is_ready(): return jsonify(guilds=0, users=0, latency=0, commands=0)
        return jsonify({ 'guilds': len(bot.guilds), 'users': sum(g.member_count for g in bot.guilds if g.member_count), 'latency': round(bot.latency * 1000), 'commands': len(bot.tree.get_commands()) })

    @web_app.route('/api/guild/<int:guild_id>/member/<int:member_id>/roles')
    def api_get_member_roles(guild_id, member_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        member = guild.get_member(member_id)
        if not member: return jsonify(status="error", message="成员未找到"), 404
        return jsonify(status="success", roles=[str(r.id) for r in member.roles if r.name != "@everyone"])

    @web_app.route('/api/guild/<int:guild_id>/voice_states')
    def api_get_voice_states(guild_id):
        # 1. 鉴权
        is_authed, error = check_auth(guild_id, required_permission="page_channel_control")
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        
        # 2. 获取服务器
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        
        # 3. 【核心修复】安全地获取机器人当前的语音状态
        bot_channel_id = None
        try:
            bot_vc = guild.voice_client
            # 增加多重检查，防止 AttributeError
            if bot_vc and bot_vc.is_connected():
                # 尝试获取 channel 属性 (兼容 Wavelink 和原生)
                ch = getattr(bot_vc, 'channel', None)
                if ch:
                    bot_channel_id = str(ch.id)
        except Exception as e:
            # 如果获取机器人状态出错，仅打印日志，不中断请求
            logging.error(f"[API Error] Getting bot voice state failed: {e}")
            bot_channel_id = None

        # 4. 【优化】拆解复杂的列表推导式，防止因单个成员数据异常导致整个 API 500 崩溃
        voice_channels_data = []
        try:
            for vc in guild.voice_channels:
                # 只处理有人的频道
                if not vc.members: 
                    continue

                members_data = []
                for m in vc.members:
                    try:
                        # 安全获取语音状态
                        is_muted = False
                        is_deafened = False
                        if m.voice:
                            is_muted = m.voice.self_mute or m.voice.mute
                            is_deafened = m.voice.self_deaf or m.voice.deaf

                        members_data.append({
                            'id': str(m.id), 
                            'name': m.display_name, 
                            'avatar_url': str(m.display_avatar.url), 
                            'is_muted': is_muted, 
                            'is_deafened': is_deafened
                        })
                    except Exception as member_err:
                        logging.warning(f"[API Warning] Skipping member {m.id} in voice state: {member_err}")
                        continue
                
                voice_channels_data.append({
                    'id': str(vc.id), 
                    'name': vc.name, 
                    'members': members_data
                })
        except Exception as e:
            logging.error(f"[API Error] Building voice channel list failed: {e}")
            # 如果列表构建失败，返回空列表而不是 500
            return jsonify(status="error", message=f"处理语音列表时出错: {str(e)}"), 500

        # 5. 返回数据
        return jsonify(
            status="success", 
            voice_channels=voice_channels_data, 
            bot_channel_id=bot_channel_id
        )
    
    @web_app.route('/api/guild/<int:guild_id>/muted_users', methods=['GET'])
    def api_get_muted_users(guild_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        active_mutes_from_db = database.db_get_all_active_mutes(guild_id)
        muted_users_list = []
        for mute_log in active_mutes_from_db:
            member = guild.get_member(mute_log['target_user_id'])
            user_info = {"id": str(member.id), "name": member.display_name, "avatar_url": str(member.display_avatar.url)} if member else {"id": str(mute_log['target_user_id']), "name": f"未知/已离开 ({mute_log['target_user_id']})", "avatar_url": 'https://cdn.discordapp.com/embed/avatars/0.png'}
            muted_users_list.append({"user": user_info, "reason": mute_log['reason'], "expires_at": mute_log['expires_at'], "log_id": mute_log['log_id']})
        return jsonify(status="success", muted_users=muted_users_list)
    
    @web_app.route('/api/guild/<int:guild_id>/audit_history')
    def api_get_audit_history(guild_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        events_from_db = database.db_get_pending_audit_events(guild_id, limit=50)
        formatted_events = [{'event_id': e['event_id'], 'user': {'id': str(e['user_id']), 'name': u.display_name if (u := bot.get_user(e['user_id'])) else f"未知({e['user_id']})", 'avatar_url': str(u.display_avatar.url) if u else ''}, 'message': {'id': str(e['message_id']), 'content': e['message_content'], 'channel_id': str(e['channel_id']), 'channel_name': c.name if (c := guild.get_channel(e['channel_id'])) else '未知', 'jump_url': e['jump_url']}, 'violation_type': e['violation_type'], 'timestamp': datetime.datetime.fromtimestamp(e['timestamp'], tz=datetime.timezone.utc).isoformat(), 'auto_deleted': bool(e['auto_deleted'])} for e in events_from_db]
        return jsonify(status="success", events=formatted_events)
    
    @web_app.route('/api/guild/<int:guild_id>/warnings')
    def api_get_warnings(guild_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        guild_warnings = user_warnings.get(guild.id, {})
        warned_users_list = [{"id": str(uid), "name": m.display_name if (m := guild.get_member(uid)) else f"未知({uid})", "avatar_url": str(m.display_avatar.url) if m else '', "warn_count": c} for uid, c in guild_warnings.items() if c > 0]
        warned_users_list.sort(key=lambda x: x['warn_count'], reverse=True)
        return jsonify(status="success", warned_users=warned_users_list)
    
    @web_app.route('/api/guild/<int:guild_id>/audit_action', methods=['POST'])
    def audit_action(guild_id):
        # 1. 权限检查
        is_authed, error = check_auth(guild_id, required_permission='page_audit_core')
        if not is_authed: 
            return jsonify(status="error", message=error[0]), error[1]
        
        # 2. 获取请求数据
        data = request.json
        moderator_name = session.get('user', {}).get('username', '未知管理员')
        
        # 3. 提交异步任务
        future = asyncio.run_coroutine_threadsafe(
            process_audit_action(guild_id, data, moderator_name), 
            bot.loop
        )
        
        try:
            # 等待异步任务完成并返回其结果（一个JSON响应）
            result_json, status_code = future.result(timeout=20)
            return jsonify(result_json), status_code
        except Exception as e:
            logging.error(f"Error in audit_action future: {e}", exc_info=True)
            return jsonify(status="error", message=f"内部错误: {e}"), 500
    
    @web_app.route('/api/guild/<int:guild_id>/data/<data_type>')
    def api_guild_data(guild_id, data_type):
        is_authed, error = check_auth(guild_id)
        if not is_authed: 
            return jsonify(status="error", message=error[0]), error[1]
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return jsonify(status="error", message="服务器未找到"), 404

        # --- 知识库数据 ---
        if data_type == 'kb': 
            return jsonify(kb=database.db_get_knowledge_base(guild_id))
        
        # --- FAQ 数据 ---
        if data_type == 'faq': 
            return jsonify(faq=server_faqs.get(guild_id, {}))
        
        # --- 机器人白名单数据 ---
        if data_type == 'bot_whitelist':
            whitelist_ids = bot.approved_bot_whitelist.get(guild_id, set())
            bots_info = []
            for b_id in whitelist_ids:
                bot_user = bot.get_user(b_id)
                bots_info.append({
                    'id': str(b_id), 
                    'name': bot_user.name if bot_user else f"未知机器人 ({b_id})"
                })
            return jsonify(whitelist=bots_info)
        
        # --- 【新】AI审查豁免用户数据 ---
        if data_type == 'exempt_users':
            users_info = []
            for user_id in exempt_users_from_ai_check:
                user = guild.get_member(user_id)
                if user and user.guild.id == guild_id: # 确保用户还在这个服务器
                    users_info.append({'id': str(user.id), 'name': user.display_name})
            return jsonify(users=users_info)

        # --- 【新】AI审查豁免频道数据 ---
        if data_type == 'exempt_channels':
            channels_info = []
            for channel_id in exempt_channels_from_ai_check:
                channel = guild.get_channel(channel_id)
                if channel and channel.guild.id == guild_id: # 确保频道属于这个服务器
                    channels_info.append({'id': str(channel.id), 'name': channel.name})
            return jsonify(channels=channels_info)
            
        # --- AI 直接对话频道数据 ---
        if data_type == 'ai_dep_channels':
            guild_dep_channels = []
            for ch_id, config in ai_dep_channels_config.items():
                channel = bot.get_channel(ch_id)
                if channel and channel.guild.id == guild_id:
                    guild_dep_channels.append({
                        'id': str(ch_id), 
                        'name': channel.name, 
                        'model': config.get("model", "未知")
                    })
            return jsonify(channels=guild_dep_channels)
            
        
        # --- AI 直接对话频道数据 ---
        if data_type == 'ai_dep_channels':
            guild_dep_channels = []
            for ch_id, config in ai_dep_channels_config.items():
                channel = bot.get_channel(ch_id)
                if channel and channel.guild.id == guild_id:
                    guild_dep_channels.append({
                        'id': str(ch_id), 
                        'name': channel.name, 
                        'model': config.get("model", "未知")
                    })
            return jsonify(channels=guild_dep_channels)
        
        # --- 如果没有匹配的数据类型 ---
        return jsonify(status="error", message=f"无效的数据类型请求: {data_type}"), 400
    
    @web_app.route('/api/guild/<int:guild_id>/shop/items')
    def api_get_shop_items(guild_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        items = database.db_get_shop_items(guild_id)
        items_list = [{'item_slug': slug, **item_data} for slug, item_data in items.items()]
        return jsonify(items=items_list)
    
    @web_app.route('/superuser/bot_profile', methods=['GET', 'POST'])
    def bot_profile_page():
        user_info = session.get('user', {})
        if not user_info.get('is_superuser'):
            flash("您无权访问此页面。", "danger")
            return redirect(url_for('dashboard'))

        if not bot.is_ready() or not bot.user:
            flash("机器人尚未完全准备好，请稍后再试。", "warning")
            return render_template(
                'bot_profile.html',
                title="机器人活动状态设置",
                user=user_info,
                current_description="机器人正在连接...",
                is_ready=False 
            )

        with web_app.app_context():
            if request.method == 'POST':
                new_description = request.form.get('description', '').strip()
                # Discord活动状态限制为128字符
                if len(new_description) > 128:
                    flash("错误：活动状态内容不能超过128个字符。", "danger")
                    return redirect(url_for('bot_profile_page'))

                async def edit_profile():
                    try:
                        # 【核心修复】将修改简介改为修改机器人的活动状态
                        # 这是机器人可以编程控制的，并且所有用户都能看到
                        new_activity_name = new_description if new_description else "/help 显示帮助"
                        await bot.change_presence(activity=discord.Game(name=new_activity_name))
                        
                        print(f"[Bot Profile] 应用开发者 '{user_info.get('username')}' 已更新机器人活动状态。")
                        return "success", "机器人活动状态已成功更新！"
                    except Exception as e:
                        print(f"[Bot Profile Error] 更新机器人状态时出错: {e}")
                        return "danger", f"更新失败: {e}"
                
                future = asyncio.run_coroutine_threadsafe(edit_profile(), bot.loop)
                try:
                    category, message = future.result(timeout=10) 
                    flash(message, category)
                except Exception as e:
                    flash(f"执行更新时发生超时或未知错误: {e}", "danger")

                return redirect(url_for('bot_profile_page'))

            # 【核心修复】GET请求时，获取机器人当前的活动状态并显示
            current_activity_text = ""
            if bot.activity and isinstance(bot.activity, discord.Game):
                current_activity_text = bot.activity.name

            return render_template(
                'bot_profile.html', 
                title="机器人活动状态设置", 
                user=user_info,
                current_description=current_activity_text, 
                is_ready=True
            )
    
    @web_app.route('/api/guild/<int:guild_id>/shop/action', methods=['POST'])
    def api_shop_action(guild_id):
        # 权限检查：确保用户有权管理经济系统
        is_authed, error = check_auth(guild_id, required_permission="tab_economy")
        if not is_authed: 
            return jsonify(status="error", message=error[0]), error[1]
        
        data = request.json
        action = data.get('action')
        item_slug = data.get('item_slug')

        if not action or not item_slug:
            return jsonify(status="error", message="请求中缺少 'action' 或 'item_slug'。"), 400

        # 处理删除操作
        if action == 'delete':
            # 调用数据库函数来删除物品
            # 假设 db_remove_shop_item 成功时返回 True，失败时返回 False
            success = database.db_remove_shop_item(guild_id, item_slug)
            
            if success:
                print(f"[Shop Admin] 管理员从服务器 {guild_id} 的商店中移除了物品 (slug: {item_slug})。")
                return jsonify(status="success", message=f"物品 '{item_slug}' 已成功从商店移除。")
            else:
                return jsonify(status="error", message=f"从数据库移除物品 '{item_slug}' 失败，可能是物品不存在。"), 404
        
        return jsonify(status="error", message=f"未知的商店操作: {action}"), 400
    
    @web_app.route('/api/guild/<int:guild_id>/economy_stats')
    def api_get_economy_stats(guild_id):
        is_authed, error = check_auth(guild_id)
        if not is_authed: return jsonify(status="error", message=error[0]), error[1]
        guild = bot.get_guild(guild_id)
        if not guild: return jsonify(status="error", message="服务器未找到"), 404
        stats = database.db_get_economy_stats(guild_id)
        user_ids = [user['user_id'] for user in stats['top_users']]
        user_map = {user.id: user.display_name for user in guild.members if user.id in user_ids}
        for user_stat in stats['top_users']:
            user_stat['username'] = user_map.get(user_stat['user_id'], f"未知用户({user_stat['user_id']})")
        return jsonify(status="success", stats=stats)
    
@web_app.route('/api/guild/<int:guild_id>/tickets', methods=['GET'])
def api_get_tickets(guild_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    
    # 1. 从数据库获取基础票据信息
    tickets_from_db = database.db_get_open_tickets(guild_id)
    
    # 2. 【核心修改】将数据增强任务提交到异步事件循环
    future = asyncio.run_coroutine_threadsafe(
        enrich_ticket_data_with_last_message(tickets_from_db, session.get('user', {})), 
        bot.loop
    )
    try:
        # 3. 等待结果并返回
        enriched_tickets = future.result(timeout=20) # 增加超时以应对大量票据

        # 确保所有 ID 都是字符串，防止 JS 精度丢失
        for ticket in enriched_tickets:
            for key in ['ticket_id', 'guild_id', 'channel_id', 'creator_id', 'department_id', 'claimed_by_id']:
                if key in ticket and ticket[key] is not None:
                    ticket[key] = str(ticket[key])

        # 按最后活动时间排序
        sorted_tickets = sorted(enriched_tickets, key=lambda x: x.get('last_activity_ts', 0), reverse=True)
        return jsonify(status="success", tickets=sorted_tickets)
        
    except Exception as e:
        logging.error(f"Enriching ticket data failed: {e}", exc_info=True)
        return jsonify(status="error", message="获取票据数据时发生内部错误。"), 500
    
# [ 新增代码块 ] - 添加在 role_manager_bot.py 的 superuser_accounts_page 函数之后

async def enrich_ticket_data_with_last_message(tickets: List[Dict], user_info: Dict) -> List[Dict]:
    """
    异步辅助函数，用于填充票据数据，并获取最后一条消息和新消息状态。
    """
    enriched_tickets = []
    user_id = int(user_info.get('id', 0)) if user_info.get('id', '0').isdigit() else 0

    for ticket in tickets:
        try:
            guild = bot.get_guild(ticket['guild_id'])
            channel = guild.get_channel(ticket['channel_id']) if guild else None
            if not channel:
                continue

            # 1. 获取创建者和认领者信息
            try:
                creator = await bot.fetch_user(ticket['creator_id'])
                ticket['creator_name'] = creator.display_name
            except discord.NotFound:
                ticket['creator_name'] = f"未知({ticket['creator_id']})"
            
            if ticket.get('claimed_by_id'):
                try:
                    claimer = await bot.fetch_user(ticket['claimed_by_id'])
                    ticket['claimed_by_name'] = claimer.display_name
                except discord.NotFound:
                    ticket['claimed_by_name'] = f"未知({ticket['claimed_by_id']})"
            
            # 2. 【新增】获取最后一条消息
            last_message = None
            async for msg in channel.history(limit=1):
                last_message = msg
            
            if last_message:
                ticket['last_message_content'] = last_message.content if last_message.content else f"({len(last_message.embeds)}个嵌入)"
                ticket['last_message_author'] = last_message.author.name
                ticket['last_activity_ts'] = last_message.created_at.timestamp()
                # 【新增】判断是否有新消息 (最后一条消息不是当前登录用户发的，且不是机器人发的)
                ticket['has_new_message'] = (last_message.author.id != user_id and not last_message.author.bot)
            else:
                ticket['last_message_content'] = "(无消息)"
                ticket['last_activity_ts'] = ticket.get('created_at', 0)
                ticket['has_new_message'] = True # 新票据视为有新消息

            enriched_tickets.append(ticket)
        except Exception as e:
            print(f"Error enriching ticket {ticket.get('ticket_id')}: {e}")
    
    return enriched_tickets


# 【新增】API：获取所有员工列表
@web_app.route('/api/guild/<int:guild_id>/staff_members')
def api_get_staff_members(guild_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(status="error", message="服务器未找到"), 404

    # 从所有部门收集员工角色ID
    departments = database.db_get_ticket_departments(guild_id)
    all_staff_role_ids = set(chain.from_iterable(d.get('staff_role_ids', []) for d in departments))
    
    staff_members = set()
    for role_id in all_staff_role_ids:
        role = guild.get_role(role_id)
        if role:
            for member in role.members:
                if not member.bot:
                    staff_members.add(member)
    
    staff_list = sorted([{'id': str(m.id), 'name': m.display_name} for m in staff_members], key=lambda x: x['name'])
    return jsonify(status="success", staff=staff_list)

# 【新增】API：分配负责人
@web_app.route('/api/guild/<int:guild_id>/ticket/<int:ticket_id>/assign', methods=['POST'])
def api_assign_ticket(guild_id, ticket_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    data = request.json
    new_assignee_id = data.get('assignee_id')
    if not new_assignee_id:
        return jsonify(status="error", message="必须提供新的负责人ID。"), 400

    # 使用新的数据库函数
    if database.db_update_ticket_assignee(ticket_id, int(new_assignee_id)):
        # 成功后，在后台发送通知
        future = asyncio.run_coroutine_threadsafe(
            notify_ticket_assignment(ticket_id, session.get('user', {}), int(new_assignee_id)),
            bot.loop
        )
        # 我们可以不等通知发完就立即响应前端
        return jsonify(status="success", message="负责人已更新。")
    else:
        return jsonify(status="error", message="分配失败，可能票据不存在或数据库错误。"), 500

# 【新增】异步辅助函数：发送分配通知
async def notify_ticket_assignment(ticket_id: int, assigner_info: dict, new_assignee_id: int):
    ticket_info = database.db_get_ticket_by_id(ticket_id)
    if not ticket_info: return

    try:
        guild = await bot.fetch_guild(ticket_info['guild_id'])
        channel = await guild.fetch_channel(ticket_info['channel_id'])
        new_assignee = await bot.fetch_user(new_assignee_id)
        assigner_name = assigner_info.get('username', '系统')

        # 1. 广播 Socket.IO 事件
        if socketio:
            socketio.emit('ticket_status_changed', {
                'ticket_id': str(ticket_id),
                'new_status': 'CLAIMED',
                'claimed_by_id': str(new_assignee_id),
                'claimed_by_name': new_assignee.display_name
            }, room=f'tickets_{guild.id}')

        # 2. 在票据频道内发送通知
        embed_channel = discord.Embed(
            description=f"✅ **{assigner_name}** 已将此票据分配给 **{new_assignee.display_name}**。",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed_channel)

        # 3. 私信通知新的负责人
        embed_dm = discord.Embed(
            title="🎫 新的票据分配",
            description=f"**{assigner_name}** 将一个票据分配给了你。\n\n**服务器:** {guild.name}\n**频道:** [点击跳转]({channel.jump_url})",
            color=discord.Color.green()
        )
        await new_assignee.send(embed=embed_dm)

    except Exception as e:
        logging.error(f"发送票据分配通知时出错 (Ticket ID: {ticket_id}): {e}", exc_info=True)

@web_app.route('/api/superuser/accounts', methods=['GET', 'POST'])
def api_superuser_accounts():
    # 权限检查：确保只有超级用户可以访问
    user_info = session.get('user', {})
    if not user_info.get('is_superuser'):
        return jsonify(status="error", message="无权访问"), 403

    # 处理 GET 请求 (获取所有副账号)
    if request.method == 'GET':
        try:
            accounts = database.db_get_all_sub_accounts()
            return jsonify(status="success", accounts=accounts)
        except Exception as e:
            logging.error(f"获取副账号列表时出错: {e}", exc_info=True)
            return jsonify(status="error", message="获取副账号列表时发生服务器内部错误。"), 500

    # 处理 POST 请求 (创建、更新、删除)
    if request.method == 'POST':
        try:
            data = request.json
            action = data.get('action')

            if action == 'create' or action == 'update':
                account_name = data.get('account_name')
                permissions = data.get('permissions', {})
                if not account_name:
                    return jsonify(status="error", message="账号名称不能为空"), 400
                
                if action == 'create':
                    access_key = database.db_create_sub_account(account_name, permissions)
                    if access_key:
                        return jsonify(status="success", message=f"账号 '{account_name}' 已创建！", access_key=access_key)
                    else:
                        return jsonify(status="error", message="创建失败，可能是账号名称已存在"), 409
                else: # action == 'update'
                    account_id = data.get('account_id')
                    if not account_id:
                        return jsonify(status="error", message="缺少账号ID"), 400
                    if database.db_update_sub_account_permissions(int(account_id), permissions):
                        return jsonify(status="success", message="权限已更新！")
                    else:
                        return jsonify(status="error", message="更新失败"), 500

            elif action == 'delete':
                account_id = data.get('account_id')
                if not account_id:
                    return jsonify(status="error", message="缺少账号ID"), 400
                if database.db_delete_sub_account(int(account_id)):
                    return jsonify(status="success", message="账号已删除！")
                else:
                    return jsonify(status="error", message="删除失败"), 500
            
            return jsonify(status="error", message="未知的操作"), 400
        except Exception as e:
            logging.error(f"处理副账号POST请求时出错: {e}", exc_info=True)
            return jsonify(status="error", message="处理请求时发生服务器内部错误。"), 500
        
# [ 结束新增代码块 ]
    
# =========================================
# == 票据系统 - Web API 端点
# =========================================

@web_app.route('/api/guild/<int:guild_id>/ticket_departments', methods=['GET', 'POST'])
def api_ticket_departments(guild_id):
    # 权限检查：确保用户有权管理服务器设置
    is_authed, error = check_auth(guild_id, required_permission="page_settings")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    # 处理 GET 请求 (获取所有部门)
    if request.method == 'GET':
        departments = database.db_get_ticket_departments(guild_id)
        return jsonify(status="success", departments=departments)

    # 处理 POST 请求 (创建或更新部门)
    if request.method == 'POST':
        data = request.json
        if not data.get('name') or not data.get('staff_role_ids'):
            return jsonify(status="error", message="部门名称和员工身份组为必填项。"), 400

        # 后端需要整数列表，前端可能传来字符串列表
        data['staff_role_ids'] = [int(r) for r in data['staff_role_ids'] if str(r).isdigit()]
        
        success, msg = database.db_create_or_update_department(guild_id, data)
        
        if success:
            return jsonify(status="success", message=msg)
        else:
            return jsonify(status="error", message=msg), 500

@web_app.route('/api/guild/<int:guild_id>/ticket_department/<int:department_id>', methods=['DELETE'])
def api_delete_ticket_department(guild_id, department_id):
    is_authed, error = check_auth(guild_id, required_permission="page_settings")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    
    if database.db_delete_department(department_id, guild_id):
        return jsonify(status="success", message="部门已成功删除。")
    else:
        return jsonify(status="error", message="删除部门失败，可能该部门不存在或发生数据库错误。"), 500



async def enrich_ticket_data(tickets: List[Dict]) -> List[Dict]:
    """异步辅助函数，用于填充票据数据中的用户名和头像。"""
    for ticket in tickets:
        # 获取创建者信息
        try:
            creator = await bot.fetch_user(ticket['creator_id'])
            ticket['creator_name'] = creator.display_name
            ticket['creator_avatar_url'] = str(creator.display_avatar.url)
        except discord.NotFound:
            ticket['creator_name'] = f"未知用户({ticket['creator_id']})"
            ticket['creator_avatar_url'] = "https://cdn.discordapp.com/embed/avatars/0.png"
        
        # 获取认领者信息
        if ticket.get('claimed_by_id'):
            try:
                claimer = await bot.fetch_user(ticket['claimed_by_id'])
                ticket['claimed_by_name'] = claimer.display_name
            except discord.NotFound:
                ticket['claimed_by_name'] = f"未知管理员({ticket['claimed_by_id']})"
        else:
            ticket['claimed_by_name'] = None
            
    return tickets



@web_app.route('/guild/<int:guild_id>/transcripts')
def transcripts_page(guild_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        flash(error[0], 'danger')
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    if not guild:
        return "服务器未找到", 404
        
    # 从数据库获取票据信息，而不是直接扫描文件系统
    closed_tickets = database.db_get_closed_tickets_with_transcripts(guild_id)

    # 异步获取创建者信息以丰富列表
    future = asyncio.run_coroutine_threadsafe(
        enrich_ticket_data(closed_tickets),
        bot.loop
    )
    try:
        enriched_tickets = future.result(timeout=15)
    except Exception as e:
        logging.error(f"Enriching closed ticket data failed: {e}", exc_info=True)
        enriched_tickets = closed_tickets # Fallback to un-enriched data

    return render_template('transcripts.html', title="聊天记录", user=session.get('user', {}), guild=guild, transcripts=enriched_tickets)

# [ 新增代码块 ] - 添加在 role_manager_bot.py 的 transcripts_page 函数之后

@web_app.route('/guild/<int:guild_id>/transcript/<path:filename>')
def view_transcript(guild_id, filename):
    # 权限检查：确保用户有权访问此服务器的票据系统
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        # 对于API端点，可以直接返回错误信息或重定向
        return "权限不足", 403

    # 安全性检查：确保文件名是安全的，并且路径在我们预期的文件夹内
    from werkzeug.utils import secure_filename
    secure_name = secure_filename(filename)
    
    # 获取绝对路径以进行安全比较
    transcript_dir = os.path.abspath("transcripts")
    file_path = os.path.join(transcript_dir, secure_name)

    # 再次确认最终路径仍在我们的 transcripts 目录内，防止 ".." 等路径遍历攻击
    if not os.path.abspath(file_path).startswith(transcript_dir):
        return "禁止访问", 403
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return "文件未找到", 404
    
    # 使用 send_file，但移除 as_attachment=True，并明确 mimetype，以便在浏览器中直接显示
    response = send_file(file_path, mimetype='text/html')
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; "
        "img-src https: data:; "
        "style-src 'unsafe-inline'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    )
    return response

# [ 结束新增代码块 ]





@web_app.route('/api/guild/<int:guild_id>/ticket/<int:ticket_id>/claim', methods=['POST'])
def api_claim_ticket(guild_id, ticket_id):
    # 1. 权限检查
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    
    user_info = session.get('user', {})
    admin_id_str = user_info.get('id')
    
    # 2. 获取操作者 ID
    admin_id = None
    if user_info.get('is_superuser'):
        admin_id = bot.user.id
    elif user_info.get('is_sub_account'):
        admin_id = bot.user.id # 副账号认领时，显示为机器人操作
    else:
        try:
            admin_id = int(admin_id_str)
        except (ValueError, TypeError):
            return jsonify(status="error", message="无效的管理员用户ID。"), 400

    if admin_id is None:
        return jsonify(status="error", message="无法确定管理员ID。"), 400

    # 3. 【核心修改】调用新的数据库函数来更新负责人
    if database.db_update_ticket_assignee(ticket_id, admin_id):
        
        # 4. 【核心修改】在后台异步发送所有通知 (频道内消息, DM, Socket.IO)
        future = asyncio.run_coroutine_threadsafe(
            notify_ticket_assignment(ticket_id, user_info, admin_id),
            bot.loop
        )
        # 不需要等待 future.result()，立即响应前端
        
        return jsonify(status="success", message="票据已成功认领。")
    else:
        # 如果数据库操作失败 (例如票据已被他人认领或不存在)
        return jsonify(status="error", message="认领失败，可能票据已被认领或不存在。"), 409


# [ 新增代码块 1 ] - 添加在 api_claim_ticket 函数之后

@web_app.route('/api/guild/<int:guild_id>/ticket/<int:ticket_id>/close', methods=['POST'])
def api_close_ticket(guild_id, ticket_id):
    # 权限检查
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    user_info = session.get('user', {})
    
    # 将关闭逻辑提交到机器人的事件循环中执行
    future = asyncio.run_coroutine_threadsafe(
        close_ticket_from_web(int(ticket_id), user_info),
        bot.loop
    )

    try:
        # 等待异步任务完成并返回结果
        result_json, status_code = future.result(timeout=30)
        return jsonify(result_json), status_code
    except Exception as e:
        logging.error(f"关闭票据 {ticket_id} 时发生超时或未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

# 同时，在 role_manager_bot.py 中添加处理关闭逻辑的异步辅助函数
async def close_ticket_from_web(ticket_id: int, closer_info: dict):
    """从Web面板触发的关闭票据的异步逻辑。"""
    ticket_info = database.db_get_ticket_by_id(ticket_id)
    if not ticket_info:
        return {'status': 'error', 'message': '票据未找到'}, 404

    guild_id = ticket_info['guild_id']
    channel_id = ticket_info['channel_id']
    
    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(channel_id) if guild else None

    if not channel:
        # 如果频道已被删除，我们只需更新数据库状态
        database.db_close_ticket(ticket_id, "频道已不存在，由Web面板强制关闭", None)
        if socketio:
            socketio.emit('ticket_closed', {'channel_id': str(channel_id)}, room=f'tickets_{guild_id}')
        return {'status': 'success', 'message': '票据频道已不存在，记录已更新'}, 200

    # 与 on_interaction 中关闭票据的逻辑几乎完全相同
    closer_name = closer_info.get('username', 'Web管理员')
    
    await channel.send(f"⏳ {closer_name} 已从Web面板请求关闭此票据。正在生成聊天记录并归档...")

    transcript_content = await generate_ticket_transcript_html(channel)
    transcript_filename = f"transcript-{guild.id}-{channel.id}-{int(time.time())}.html"
    transcript_folder = "transcripts"
    os.makedirs(transcript_folder, exist_ok=True)
    transcript_path = os.path.join(transcript_folder, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript_content)

    admin_log_channel_id = PUBLIC_WARN_LOG_CHANNEL_ID
    admin_log_channel = guild.get_channel(admin_log_channel_id)
    if admin_log_channel:
        try:
            await admin_log_channel.send(f"票据 `#{channel.name}` 已由 {closer_name} (Web) 关闭。", file=discord.File(transcript_path))
        except Exception as e:
            logging.warning(f"无法发送票据日志到管理员频道: {e}")

    try:
        creator = await bot.fetch_user(ticket_info['creator_id'])
        await creator.send(f"您在服务器 **{guild.name}** 的票据 `#{channel.name}` 已被关闭。", file=discord.File(transcript_path))
    except Exception as e:
        logging.warning(f"无法私信票据记录给用户 {ticket_info['creator_id']}: {e}")

    database.db_close_ticket(ticket_id, f"由 {closer_name} (Web) 关闭", transcript_filename)
    
    if socketio:
        socketio.emit('ticket_closed', {'channel_id': str(channel.id)}, room=f'tickets_{guild.id}')
    
    await asyncio.sleep(2)
    await channel.delete(reason=f"票据关闭，操作者: {closer_name} (Web)")
    
    return {'status': 'success', 'message': '票据已成功关闭和归档'}, 200

# [ 结束新增代码块 1 ]


async def _get_ticket_history_for_ai(channel: discord.TextChannel, creator_id: int) -> str:
    """获取票据的聊天记录并格式化为AI可读的字符串。"""
    history_lines = []
    async for message in channel.history(limit=50, oldest_first=True):
        if message.author.bot and not message.embeds:
            continue # 忽略没有嵌入内容的机器人消息
        
        # 确定发言者身份
        speaker = "User"
        if message.author.id != creator_id:
            speaker = "Staff" if not message.author.bot else "System"

        # 格式化消息内容
        content = message.clean_content
        if message.embeds and message.embeds[0].description:
            # 如果是嵌入消息，也附上其描述
            content += f" [Embed: {message.embeds[0].description}]"
        
        if content.strip():
            history_lines.append(f"{speaker} ({message.author.name}): {content.strip()}")

    return "\n".join(history_lines)

@web_app.route('/api/guild/<int:guild_id>/ticket/<int:ticket_id>/ai_suggest', methods=['POST'])
def api_ticket_ai_suggest(guild_id, ticket_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    future = asyncio.run_coroutine_threadsafe(
        _ticket_ai_suggest_async(guild_id, ticket_id),
        bot.loop
    )
    try:
        result_json, status_code = future.result(timeout=120) # 增加超时时间以应对复杂的AI请求
        return jsonify(result_json), status_code
    except Exception as e:
        logging.error(f"AI建议功能超时或发生未知错误 (Ticket ID: {ticket_id}): {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

async def _ticket_ai_suggest_async(guild_id: int, ticket_id: int):
    """处理票据AI回复建议的异步核心逻辑。"""
    if not DEEPSEEK_API_KEY:
        return {'status': 'error', 'message': '未配置DeepSeek API密钥。'}, 400

    ticket_info = database.db_get_ticket_by_id(ticket_id)
    if not ticket_info or ticket_info['guild_id'] != guild_id:
        return {'status': 'error', 'message': '票据未找到。'}, 404

    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(ticket_info['channel_id']) if guild else None
    if not channel or not isinstance(channel, discord.TextChannel):
        return {'status': 'error', 'message': '票据频道未找到或已删除。'}, 404

    try:
        history_str = await _get_ticket_history_for_ai(channel, ticket_info['creator_id'])
        if not history_str:
            return {'status': 'error', 'message': '票据中没有足够的内容可供分析。'}, 400

        # 准备给AI的提示
        system_prompt_parts = [
            "You are a professional, friendly, and helpful customer support assistant for a Discord server.",
            "Your task is to analyze the provided conversation history from a support ticket and suggest a suitable reply to the user's latest query.",
            "You MUST adhere to the information provided in the server's knowledge base. If the knowledge base has relevant information, prioritize it in your answer."
        ]
        
        # 加入服务器知识库
        knowledge_base = database.db_get_knowledge_base(guild_id)
        if knowledge_base:
            system_prompt_parts.append("\n--- SERVER KNOWLEDGE BASE (Use this for context) ---")
            system_prompt_parts.extend(knowledge_base)
            system_prompt_parts.append("--- END KNOWLEDGE BASE ---")
        
        final_system_prompt = "\n".join(system_prompt_parts)

        user_prompt = f"""
        Here is the conversation history:
        --- TICKET HISTORY ---
        {history_str}
        --- END HISTORY ---

        Based on the entire conversation history and the knowledge base, please provide a helpful and concise reply to the user's latest message.
        - Your response should directly address their issue.
        - Be polite and professional.
        - Do not include greetings like "Hello" or your signature. Just provide the raw text for the reply.
        """
        
        api_messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 使用现有的函数调用DeepSeek API
        async with aiohttp.ClientSession() as session:
            display_response, final_content_hist, api_error = await get_deepseek_dialogue_response(
                session, DEEPSEEK_API_KEY, "deepseek-chat", api_messages
            )

        if api_error:
            return {'status': 'error', 'message': f'AI API调用失败: {api_error}'}, 500
        
        if not final_content_hist:
            return {'status': 'error', 'message': 'AI未能生成有效的回复内容。'}, 500

        return {'status': 'success', 'suggestion': final_content_hist.strip()}, 200

    except Exception as e:
        logging.error(f"生成AI票据建议时发生严重错误 (Ticket ID: {ticket_id}): {e}", exc_info=True)
        return {'status': 'error', 'message': f'处理AI建议时发生内部错误: {type(e).__name__}'}, 500
# [ 结束新增代码块 ]

async def handle_ai_ticket_reply(message: discord.Message):
    """
    一个独立的函数，用于处理对AI托管票据中用户消息的自动回复。
    【V6 - 已修复 NameError】
    """
    channel = message.channel
    guild = message.guild
    guild_id = guild.id
    ticket_info = database.db_get_ticket_by_channel(channel.id)
    if not ticket_info:
        logging.error(f"[AI Reply] 无法在 handle_ai_ticket_reply 中找到票据信息 (Channel: {channel.id})")
        return

    if not ticket_info.get('is_ai_managed'):
        logging.warning(f"[AI Reply] 票据 {ticket_info['ticket_id']} 已非AI托管模式，取消本次AI回复。")
        return

    logging.info(f"[AI Reply] 开始为票据 {ticket_info['ticket_id']} 生成AI回复...")

    try:
        async with channel.typing():
            logging.info(f"[AI Reply] 正在获取票据 {ticket_info['ticket_id']} 的历史记录...")
            history_str = await _get_ticket_history_for_ai(channel, ticket_info['creator_id'])
            if not history_str:
                logging.warning(f"[AI Reply] 票据 {ticket_info['ticket_id']} 历史记录为空，无法生成回复。")
                return

            logging.info(f"[AI Reply] 正在为票据 {ticket_info['ticket_id']} 构建AI提示...")
            
            system_prompt_parts = [
                "You are a professional, friendly, and helpful customer support assistant for a Discord server.",
                "Your primary task is to understand the user's intent from their latest message.",
                
                # 【核心修改】定义所有可能的意图
                "First, analyze the user's last message to determine their intent. The possible intents are: 'CONTINUE_CONVERSATION', 'CLOSE_TICKET', 'ESCALATE_TO_STAFF', or 'PERMISSION_REQUEST'.",
    
                # 【核心修改】描述新意图的触发条件
                "If the user's message indicates a desire to obtain roles, permissions, or become an admin/moderator (e.g., 'how can I become an admin', 'I want a moderator role', 'apply for staff'), the intent is 'PERMISSION_REQUEST'.",
                
                "If the user explicitly asks to contact a developer, staff, admin, or requires human help (e.g., 'contact developer', 'talk to a real person', 'I need human help'), the intent is 'ESCALATE_TO_STAFF'.",
                "If the user asks a general question, needs help with a known issue, or provides more information, the intent is 'CONTINUE_CONVERSATION'.",
                "If the user explicitly asks to close the ticket, says they are done, or expresses that their issue is resolved (e.g., 'thanks, that's all', 'problem solved', 'you can close this now'), the intent is 'CLOSE_TICKET'.",
                
                "You MUST respond in a specific JSON format: {\"intent\": \"<INTENT_HERE>\", \"reply\": \"<YOUR_REPLY_HERE>\"}.",
                
                "For 'CONTINUE_CONVERSATION', the 'reply' should be a helpful answer to the user's question.",
                "For 'CLOSE_TICKET', the 'reply' should be a friendly closing message.",
                "For 'ESCALATE_TO_STAFF', the 'reply' should inform the user that you have notified the staff and they will be in touch shortly.",
    
                # 【核心修改】为新意图定义回复要求
                "For 'PERMISSION_REQUEST', the 'reply' should inform the user that their application has been forwarded to the server owner for review."
            ]
            
            knowledge_base = database.db_get_knowledge_base(guild.id)
            if knowledge_base:
                system_prompt_parts.append("\n--- SERVER KNOWLEDGE BASE (Use this for context when replying) ---")
                system_prompt_parts.extend(knowledge_base)
                system_prompt_parts.append("--- END KNOWLEDGE BASE ---")
            
            final_system_prompt = "\n".join(system_prompt_parts)

            user_prompt = f"""
            Here is the conversation history:
            --- TICKET HISTORY ---
            {history_str}
            --- END HISTORY ---
            
            Analyze the last message from the user based on the rules and provide your response in the required JSON format.
            """

            api_messages = [
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            logging.info(f"[AI Reply] 正在为票据 {ticket_info['ticket_id']} 调用DeepSeek API进行意图识别...")
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
                payload = {"model": "deepseek-chat", "messages": api_messages, "response_format": {"type": "json_object"}}
                
                async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        ai_raw_content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                        api_error = None
                    else:
                        ai_raw_content = None
                        api_error = f"API Error, Status: {response.status}, Body: {await response.text()}"

            final_check_ticket_info = database.db_get_ticket_by_channel(channel.id)
            if not final_check_ticket_info or not final_check_ticket_info.get('is_ai_managed'):
                logging.warning(f"[AI Reply] 在AI生成回复后，票据 {ticket_info['ticket_id']} 状态已变为人工模式。取消发送AI消息。")
                return

            if ai_raw_content and not api_error:
                logging.info(f"[AI Reply] API调用成功，原始JSON响应: {ai_raw_content}")
                try:
                    ai_decision = json.loads(ai_raw_content)
                    intent = ai_decision.get("intent")
                    reply_text = ai_decision.get("reply")

                    if intent == "ESCALATE_TO_STAFF":
                        logging.info(f"[AI Reply] 识别到上报人工意图 (票据: {ticket_info['ticket_id']})。")
                        
                        # 1. 停止 AI 托管
                        database.db_set_ticket_ai_managed_status(ticket_info['ticket_id'], False)
                        if socketio:
                            socketio.emit('ticket_ai_status_changed', {'ticket_id': str(ticket_info['ticket_id']), 'is_ai_managed': False}, room=f'tickets_{guild_id}')
                        
                        # 2. 在频道内通知用户，并@客服组
                        embed_to_user = discord.Embed(description=reply_text, color=discord.Color.orange())
                        embed_to_user.set_author(name="AI客服助理", icon_url=bot.user.display_avatar.url)
                        await channel.send(embed=embed_to_user)
                        
                        # 3. 发送带按钮的交互式消息给客服
                        departments = database.db_get_ticket_departments(guild.id)
                        target_dept = next((d for d in departments if d['department_id'] == ticket_info.get('department_id')), None)
                        
                        mention_content = ""
                        if target_dept and target_dept.get('staff_role_ids'):
                            mention_content = " ".join([f"<@&{role_id}>" for role_id in target_dept['staff_role_ids']])
                        
                        escalate_embed = discord.Embed(
                            title="🚨 AI 请求人工介入",
                            description=f"用户 **{message.author.name}** 请求人工客服协助。请处理：",
                            color=discord.Color.red()
                        )
                        await channel.send(content=mention_content, embed=escalate_embed, view=EscalateTicketView(ticket_info['ticket_id']))

                    # ==========================================
                    # ==  ↓↓↓ 在这里粘贴新的代码块 ↓↓↓  ==
                    # ==========================================
                    elif intent == "PERMISSION_REQUEST":
                        logging.info(f"[AI Reply] 识别到权限申请意图 (票据: {ticket_info['ticket_id']})。")
                        
                        # 1. 停止 AI 托管
                        database.db_set_ticket_ai_managed_status(ticket_info['ticket_id'], False)
                        if socketio:
                            socketio.emit('ticket_ai_status_changed', {'ticket_id': str(ticket_info['ticket_id']), 'is_ai_managed': False}, room=f'tickets_{guild_id}')
                        
                        # 2. 在票据频道内回复用户
                        embed_to_user = discord.Embed(description=reply_text, color=discord.Color.blue())
                        embed_to_user.set_author(name="AI助理", icon_url=bot.user.display_avatar.url)
                        await channel.send(embed=embed_to_user)
                        
                        # 3. 私信通知服务器所有者
                        if guild.owner:
                            try:
                                owner_embed = discord.Embed(
                                    title="📬 新的权限申请",
                                    description=f"用户 **{message.author.name}** 在票据 {channel.mention} 中提交了权限申请。\n\n**申请内容:**\n```{message.content}```\n\n请前往频道审核。",
                                    color=discord.Color.gold()
                                )
                                await guild.owner.send(embed=owner_embed)
                                logging.info(f"[AI Reply] 已成功私信通知服主 {guild.owner.name}。")
                            except discord.Forbidden:
                                logging.warning(f"[AI Reply] 无法私信通知服主，可能其关闭了私信。")
                        else:
                            logging.warning(f"[AI Reply] 无法找到服务器所有者来发送权限申请。")
                    # ==========================================
                    # ==  ↑↑↑ 新代码粘贴结束 ↑↑↑  ==
                    # ==========================================
                    
                    elif intent == "CLOSE_TICKET":
                        logging.info(f"[AI Reply] 识别到关闭意图，准备关闭票据 {ticket_info['ticket_id']}。")
                        embed = discord.Embed(description=f"{reply_text}\n\n*(票据将在5秒后自动关闭)*", color=discord.Color.green())
                        embed.set_author(name="AI客服助理", icon_url=bot.user.display_avatar.url)
                        embed.set_footer(text="如果需要人工服务，请明确提出。")
                        await channel.send(embed=embed)
                        await asyncio.sleep(5)
                        await close_ticket_from_web(ticket_info['ticket_id'], {'username': 'AI客服助理'})
                        logging.info(f"[AI Reply] 票据 {ticket_info['ticket_id']} 已被AI自动关闭。")

                    elif intent == "CONTINUE_CONVERSATION":
                        logging.info(f"[AI Reply] 识别到继续对话意图，准备在频道 {channel.id} 发送回复。")
                        embed = discord.Embed(description=reply_text, color=discord.Color.purple())
                        embed.set_author(name="AI客服助理", icon_url=bot.user.display_avatar.url)
                        embed.set_footer(text="如果需要人工服务，请明确提出。")
                        
                        sent_message = await channel.send(embed=embed)
                        
                        if socketio:
                            msg_data_for_web = {
                                'id': str(sent_message.id),
                                'author': { 'id': str(bot.user.id), 'name': "AI客服助理", 'avatar_url': str(bot.user.display_avatar.url), 'is_bot': True },
                                'content': '',
                                'embeds': [embed.to_dict()],
                                'timestamp': sent_message.created_at.isoformat(),
                                'channel_id': str(channel.id)
                            }
                            socketio.emit('new_ticket_message', msg_data_for_web, room=f'ticket_{channel.id}')
                    else:
                        logging.warning(f"[AI Reply] AI返回了未知的意图: '{intent}'")

                except json.JSONDecodeError:
                    logging.error(f"[AI Reply] 解析AI返回的JSON失败: {ai_raw_content}")

            elif api_error:
                logging.error(f"[AI Reply] AI自动回复票据 {ticket_info['ticket_id']} 失败: {api_error}")

    except Exception as e:
        logging.error(f"[AI Reply] 处理AI自动回复时发生严重错误 (Ticket ID: {ticket_info['ticket_id']}): {e}", exc_info=True)


# === 【临时调试路由】 ===
    @web_app.route('/test_route')
    def test_route():
        print("!!!!!!!!!! /test_route 已被访问 !!!!!!!!!!")
        return "Test route is working!"
    # ==========================

@web_app.route('/api/guild/<int:guild_id>/ticket/<int:ticket_id>/toggle_ai_assist', methods=['POST'])
def api_toggle_ai_assist(guild_id, ticket_id):
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    future = asyncio.run_coroutine_threadsafe(
        _toggle_ai_assist_async(guild_id, ticket_id),
        bot.loop
    )
    try:
        result_json, status_code = future.result(timeout=120)
        return jsonify(result_json), status_code
    except Exception as e:
        logging.error(f"切换AI托管模式时发生错误 (Ticket ID: {ticket_id}): {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

async def _toggle_ai_assist_async(guild_id, ticket_id):
    ticket_info = database.db_get_ticket_by_id(ticket_id)
    if not ticket_info or ticket_info['guild_id'] != guild_id:
        return {'status': 'error', 'message': '票据未找到。'}, 404

    current_status = bool(ticket_info.get('is_ai_managed', 0))
    new_status = not current_status
    
    # 无论开启还是关闭，都先更新数据库
    if database.db_set_ticket_ai_managed_status(ticket_id, new_status):
        logging.info(f"[AI Toggle] 票据 {ticket_id} 的AI托管状态已从 {current_status} 切换为 {new_status}。")
        
        # 【核心修复】只有在从“关闭”变为“开启”时，才触发一次AI回复
        if new_status:
            channel = bot.get_channel(ticket_info['channel_id'])
            if channel:
                # 找到用户的最后一条消息来回复
                last_user_message = None
                async for msg in channel.history(limit=20):
                    if msg.author.id == ticket_info['creator_id']:
                        last_user_message = msg
                        break
                
                if last_user_message:
                    await handle_ai_ticket_reply(last_user_message)
        
        # 无论如何，都返回成功和新的状态
        return {'status': 'success', 'is_ai_managed': new_status}, 200
        
    else:
        logging.error(f"[AI Toggle] 更新票据 {ticket_id} 的数据库状态失败。")
        return {'status': 'error', 'message': '数据库更新失败。'}, 500

async def notify_ticket_claim(ticket_id: int, admin_user_info: dict):
    """
    在Discord频道内发送票据被认领的通知。
    【V4 - 修复 guild.me 为 None 的问题】
    - 强制从API获取Guild和Channel对象，避免缓存问题。
    - 在检查权限前，显式获取机器人自身的Member对象。
    - 增加了详细的日志记录，便于未来调试。
    """
    logging.info(f"[NotifyClaim] 开始处理 ticket_id: {ticket_id} 的认领通知...")

    try:
        # 1. 从数据库获取最原始的票据数据
        ticket_data = database.db_get_ticket_by_id(ticket_id) 
        if not ticket_data:
            logging.error(f"[NotifyClaim] 无法在数据库中找到 ticket_id: {ticket_id}。")
            return

        guild_id = ticket_data.get('guild_id')
        channel_id = ticket_data.get('channel_id')

        if not guild_id or not channel_id:
            logging.error(f"[NotifyClaim] ticket_id: {ticket_id} 的数据库记录缺少 guild_id 或 channel_id。")
            return

        # 2. 强制从API获取服务器和频道对象
        guild = await bot.fetch_guild(guild_id)
        if not guild:
            logging.error(f"[NotifyClaim] 无法通过API获取 Guild: {guild_id}。")
            return

        channel = await guild.fetch_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            logging.error(f"[NotifyClaim] 无法通过API获取有效的文本频道: {channel_id}。")
            return
            
        logging.info(f"[NotifyClaim] 成功获取频道: #{channel.name} ({channel.id})")

        # 3. 准备并发送消息
        admin_name = admin_user_info.get('username', '一位管理员')
        embed = discord.Embed(
            description=f"✅ 此客服票据已由 **{admin_name}** 对接并开始处理。",
            color=discord.Color.gold()
        )
        
        # 【【【核心修复】】】
        # 在检查权限前，先显式获取机器人自身的Member对象，避免 guild.me 为 None。
        bot_member = await guild.fetch_member(bot.user.id)
        if not bot_member:
            logging.error(f"[NotifyClaim] 无法获取机器人自身的成员对象，无法检查权限。")
            return
        
        # 使用获取到的 bot_member 对象来检查权限
        if not channel.permissions_for(bot_member).send_messages or not channel.permissions_for(bot_member).embed_links:
            logging.error(f"[NotifyClaim] 机器人缺少在频道 #{channel.name} 发送消息或嵌入链接的权限。")
            return
        # 【【【修复结束】】】

        await channel.send(embed=embed)
        logging.info(f"[NotifyClaim] 已成功发送认领通知到频道 #{channel.name}。")

    except discord.NotFound:
        logging.error(f"[NotifyClaim] 处理票据 {ticket_id} 时发生 NotFound 错误，可能是服务器或频道已被删除。")
    except discord.Forbidden:
        logging.error(f"[NotifyClaim] 处理票据 {ticket_id} 时发生 Forbidden 权限错误。")
    except Exception as e:
        logging.error(f"[NotifyClaim] 发送票据认领通知时发生未知错误 (Ticket ID: {ticket_id}): {e}", exc_info=True)

# 你可能需要一个新的DB函数来通过ticket_id获取票据，请在database.py中添加
def db_get_ticket_by_id(ticket_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {TABLE_TICKETS} WHERE ticket_id = ?", (ticket_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 获取票据信息失败 (ticket_id: {ticket_id}): {e}")
        return None
    finally:
        conn.close()

# =========================================    

    
    @web_app.route('/api/guild/<int:guild_id>/audit_action', methods=['POST'])
    def audit_action(guild_id):
        # 1. 权限检查
        is_authed, error = check_auth(guild_id, required_permission='page_audit_core')
        if not is_authed: 
            return jsonify(status="error", message=error[0]), error[1]
        
        # 2. 获取请求数据
        data = request.json
        moderator_name = session.get('user', {}).get('username', '未知管理员')
        
        # 3. 提交异步任务
        future = asyncio.run_coroutine_threadsafe(
            process_audit_action(guild_id, data, moderator_name), 
            bot.loop
        )
        
        try:
            return jsonify(future.result(timeout=20))
        except Exception as e:
            logging.error(f"Error in audit_action future: {e}", exc_info=True)
            return jsonify(status="error", message=f"内部错误: {e}"), 500


@web_app.route('/api/guild/<int:guild_id>/action/deploy_ticket_panel', methods=['POST'])
def api_deploy_ticket_panel(guild_id):
    # 权限检查
    is_authed, error = check_auth(guild_id, required_permission="page_settings")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]

    # 从请求中获取数据
    data = request.json
    
    # 将处理逻辑交给异步辅助函数
    future = asyncio.run_coroutine_threadsafe(
        _deploy_ticket_panel_async(guild_id, data), 
        bot.loop
    )
    try:
        # 等待结果并返回
        return future.result(timeout=20)
    except Exception as e:
        logging.error(f"部署票据面板时发生超时或未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部服务器错误: {e}"), 500

async def _deploy_ticket_panel_async(guild_id: int, data: dict):
    """一个专门用于从Web面板部署票据面板的异步辅助函数。"""
    panel_channel_id = data.get('panel_channel_id')
    ticket_category_id = data.get('ticket_category_id')

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(status="error", message="服务器未找到"), 404

    # 安全地转换ID
    try:
        panel_channel = guild.get_channel(int(panel_channel_id))
        ticket_category = guild.get_channel(int(ticket_category_id))
    except (ValueError, TypeError):
        return jsonify(status="error", message="无效的频道或分类ID。"), 400

    if not panel_channel or not isinstance(panel_channel, discord.TextChannel):
        return jsonify(status="error", message="无效的面板频道。"), 400
    if not ticket_category or not isinstance(ticket_category, discord.CategoryChannel):
        return jsonify(status="error", message="无效的票据分类。"), 400

    # 保存设置
    set_setting(ticket_settings, guild.id, "category_id", ticket_category.id)
    set_setting(ticket_settings, guild.id, "panel_channel_id", panel_channel.id)
    save_server_settings()

    # 检查是否有部门
    departments = database.db_get_ticket_departments(guild.id)
    if not departments:
        return jsonify(status="error", message="部署失败：请先创建至少一个票据部门。"), 400

    # 创建Embed和View
    embed = discord.Embed(
        title=f"🎫 {guild.name} 服务台",
        description="**需要帮助或有任何疑问吗？**\n\n请从下方的菜单中选择与您问题最相关的部门，以创建一个专属的私人支持频道。\n\n我们的专业团队将在票据频道中为您提供帮助。",
        color=discord.Color.blue()
    )
    embed.set_footer(text="请从下方选择一个部门开始")
    
    # 使用正确的持久化视图
    view = PersistentTicketCreationView()
    
    try:
        # 发送到频道
        await panel_channel.send(embed=embed, view=view)
        return jsonify(status="success", message=f"面板已成功部署到 #{panel_channel.name}！")
    except discord.Forbidden:
        return jsonify(status="error", message=f"部署失败：机器人缺少在 #{panel_channel.name} 的权限。"), 403
    except Exception as e:
        logging.error(f"API部署票据面板时发生错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"部署时发生未知错误: {e}"), 500

# [ 结束替换代码块 ]
    
# [ 新增代码块 ] - 添加在 role_manager_bot.py 的 api_guild_action 函数之前

@web_app.route('/api/guild/<int:guild_id>/generate_invite', methods=['POST'])
def api_generate_invite(guild_id):
    # 为这个专属路由进行独立的权限检查
    user_info = session.get('user', {})
    if not user_info.get('is_superuser'):
        return jsonify(status="error", message="权限不足"), 403

    # 将生成邀请的逻辑提交到机器人的事件循环中执行
    future = asyncio.run_coroutine_threadsafe(
        _generate_invite_async(guild_id),
        bot.loop
    )
    try:
        # 等待异步任务完成并返回结果
        return future.result(timeout=15)
    except Exception as e:
        logging.error(f"为服务器 {guild_id} 生成邀请时发生超时或未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部服务器错误: {e}"), 500

async def _generate_invite_async(guild_id: int):
    """一个专门用于生成邀请链接的异步辅助函数"""
    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(status="error", message="服务器未找到"), 404
        
    # 尝试寻找一个可以创建邀请的频道
    channel_to_invite = None
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            channel_to_invite = channel
            break
    
    if not channel_to_invite:
        return jsonify(status="error", message="机器人缺少在任何频道创建邀请链接的权限。"), 403

    try:
        # 创建一个永不过期、无限次数的邀请
        invite = await channel_to_invite.create_invite(max_age=0, max_uses=0, reason="全局广播需要")
        return jsonify(status="success", invite_url=invite.url)
    except Exception as e:
        logging.error(f"为服务器 {guild.id} 创建邀请时出错: {e}")
        return jsonify(status="error", message=f"创建邀请时发生错误: {e}"), 500

# [ 结束新增代码块 ]    
# [ 新增代码块 1.2 ] - 添加在 role_manager_bot.py 的 api_guild_action 函数之前

@web_app.route('/api/guild/<int:guild_id>/roles/create_or_edit', methods=['POST'])
def api_create_or_edit_role(guild_id):
    # 权限检查：需要管理身份组的权限
    is_authed, error = check_auth(guild_id, required_permission="tab_roles")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    
    # 将请求对象直接传递给异步辅助函数
    future = asyncio.run_coroutine_threadsafe(
        _create_or_edit_role_async(guild_id, request, session),
        bot.loop
    )
    try:
        # 等待异步任务完成并返回其结果 (一个Flask响应)
        return future.result(timeout=20)
    except Exception as e:
        logging.error(f"创建/编辑身份组时发生超时或未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部服务器错误: {e}"), 500

async def _create_or_edit_role_async(guild_id: int, request_obj, session_obj):
    """一个专门用于创建或编辑身份组的异步辅助函数"""
    try:
        guild = bot.get_guild(guild_id)
        if not guild:
            return jsonify(status="error", message="服务器未找到"), 404

        form_data = request_obj.form
        role_id = form_data.get('role_id')
        role_name = form_data.get('name')
        if not role_name:
            return jsonify(status="error", message="身份组名称不能为空。"), 400

        # 1. 处理权限
        permissions_list = form_data.getlist('permissions')
        perms = discord.Permissions()
        for p_name in permissions_list:
            if hasattr(perms, p_name):
                setattr(perms, p_name, True)
        
        # 2. 处理颜色
        color_hex = form_data.get('color', '#000000').lstrip('#')
        role_color = discord.Color(int(color_hex, 16))

        # 3. 处理布尔值
        hoist = form_data.get('hoist') == 'on'
        mentionable = form_data.get('mentionable') == 'on'
        
        # 4. 处理图标
        icon_bytes = None
        if 'icon' in request_obj.files and request_obj.files['icon'].filename != '':
            icon_file = request_obj.files['icon']
            if icon_file.content_length > 256 * 1024:
                return jsonify(status="error", message="图标文件不能超过 256KB。"), 400
            icon_bytes = await icon_file.read()

        # 组合所有参数
        kwargs = {
            'name': role_name,
            'permissions': perms,
            'color': role_color,
            'hoist': hoist,
            'mentionable': mentionable,
            'reason': f"由 {session_obj.get('user', {}).get('username', 'Web管理员')} 操作"
        }
        if icon_bytes:
            kwargs['icon'] = icon_bytes

        if role_id: # --- 编辑现有身份组 ---
            role = guild.get_role(int(role_id))
            if not role:
                return jsonify(status="error", message="未找到要编辑的身份组。"), 404
            await role.edit(**kwargs)
            message = f"身份组 '{role_name}' 已成功更新。"
        else: # --- 创建新身份组 ---
            await guild.create_role(**kwargs)
            message = f"身份组 '{role_name}' 已成功创建。"

        return jsonify(status="success", message=message)

    except discord.Forbidden:
        return jsonify(status="error", message="机器人权限不足，无法创建或编辑此身份组。请检查层级和权限。"), 403
    except discord.HTTPException as e:
        return jsonify(status="error", message=f"Discord API 错误: {e.text}"), 500
    except Exception as e:
        logging.error(f"处理身份组操作时发生未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"发生内部错误: {e}"), 500
# [ 结束新增代码块 1.2 ]

    
@web_app.route('/api/guild/<int:guild_id>/action/<path:action>', methods=['POST'])
def api_guild_action(guild_id, action):
    # 这个函数现在只负责接收请求和分发任务
    data = request.json
    future = asyncio.run_coroutine_threadsafe(perform_action(guild_id, action, data, session), bot.loop)
    try:
        return future.result(timeout=30)
    except Exception as e:
        logging.error(f"Error in api_guild_action future: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

# [ 新增代码块 ] - 添加在 role_manager_bot.py 的 handle_form_submission 函数之前

@web_app.route('/api/guild/<int:guild_id>/form_submit', methods=['POST'])
def api_form_submit(guild_id):
    # 这个函数接收所有简单的表单提交
    data = request.json
    # 将处理逻辑交给您已有的异步辅助函数
    future = asyncio.run_coroutine_threadsafe(handle_form_submission(guild_id, data, session), bot.loop)
    try:
        # 等待结果并返回
        return future.result(timeout=30)
    except Exception as e:
        logging.error(f"Error in api_form_submit future: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

# [ 结束新增代码块 ]
            
    @web_app.route('/api/guild/<int:guild_id>/bulk_action', methods=['POST'])
    def api_bulk_action(guild_id):
        data = request.get_json(silent=True) or {}
        bulk_action_permissions = {
            'bulk_add_role': 'tab_roles',
            'bulk_remove_role': 'tab_roles',
            'bulk_kick': 'tab_members',
        }
        action = data.get('action')
        required_permission = bulk_action_permissions.get(action)
        if required_permission is None:
            return jsonify(status="error", message="未知的批量操作。"), 400
        is_authed, error = check_auth(guild_id, required_permission=required_permission)
        if not is_authed:
            return jsonify(status="error", message=error[0]), error[1]
        future = asyncio.run_coroutine_threadsafe(perform_bulk_action(guild_id, data, session), bot.loop)
        try:
            return future.result(timeout=60)
        except Exception as e:
            logging.error(f"Error in api_bulk_action future: {e}", exc_info=True)
            return jsonify(status="error", message=f"内部错误: {e}"), 500

@web_app.route('/api/guild/<int:guild_id>/permissions', methods=['GET', 'POST'])
def api_guild_permissions(guild_id):
    # 权限检查：只有服务器所有者或超级用户才能访问
    user_info = session.get('user', {})
    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(status="error", message="服务器未找到"), 404

    is_discord_owner = (not user_info.get('is_sub_account') and not user_info.get('is_superuser') and str(user_info.get('id')) == str(guild.owner_id))
    if not user_info.get('is_superuser') and not is_discord_owner:
        return jsonify(status="error", message="您无权访问此功能。"), 403

    # 处理 GET 请求 (获取数据)
    if request.method == 'GET':
        # 从内存字典中获取当前服务器的权限设置
        guild_perms = web_permissions.get(guild_id, {})
        return jsonify(status="success", permissions=guild_perms)

    # 处理 POST 请求 (保存或删除数据)
    if request.method == 'POST':
        data = request.json
        action = data.get('action')
        role_id_str = data.get('role_id')
        if not role_id_str or not role_id_str.isdigit():
            return jsonify(status="error", message="缺少有效的身份组ID。"), 400
        
        role_id = int(role_id_str)
        role = guild.get_role(role_id)
        if not role:
            return jsonify(status="error", message="未找到该身份组。"), 404

        # 确保服务器的权限字典存在
        if guild_id not in web_permissions:
            web_permissions[guild_id] = {}

        # 保存/更新权限
        if action == 'save':
            permissions_list = data.get('permissions', [])
            # 存储权限数据
            web_permissions[guild_id][str(role.id)] = {
                "name": role.name,
                "permissions": permissions_list
            }
            save_server_settings() # 持久化到文件
            return jsonify(status="success", message=f"已成功保存身份组 '{role.name}' 的权限。", permissions=web_permissions.get(guild_id, {}))

        # 删除权限
        elif action == 'delete':
            if str(role.id) in web_permissions[guild_id]:
                del web_permissions[guild_id][str(role.id)]
                if not web_permissions[guild_id]: # 如果删除了最后一个，则移除服务器键
                    del web_permissions[guild_id]
                save_server_settings() # 持久化到文件
                return jsonify(status="success", message=f"已成功删除身份组 '{role.name}' 的权限组。", permissions=web_permissions.get(guild_id, {}))
            else:
                return jsonify(status="error", message="未找到该身份组的权限配置。"), 404
        
        return jsonify(status="error", message="未知的操作。"), 400 
    
@web_app.route('/api/guild/<int:guild_id>/ticket/<int:channel_id>/history')
def api_get_ticket_history(guild_id, channel_id):
    # 权限检查
    is_authed, error = check_auth(guild_id, required_permission="tab_tickets")
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    
    # 使用 run_coroutine_threadsafe 在 eventlet 线程中安全地调度 asyncio 任务
    future = asyncio.run_coroutine_threadsafe(
        _get_ticket_history_async(guild_id, channel_id), 
        bot.loop
    )
    try:
        # 等待异步任务完成并获取结果
        result_data, status_code = future.result(timeout=20)
        return jsonify(result_data), status_code
    except Exception as e:
        logging.error(f"获取票据历史记录时发生超时或未知错误: {e}", exc_info=True)
        return jsonify(status="error", message=f"内部错误: {e}"), 500

# 我们需要将获取历史记录的逻辑封装在一个异步辅助函数中



# 我们需要将获取历史记录的逻辑封装在一个异步辅助函数中
async def _get_ticket_history_async(guild_id, channel_id):
    try:
        # 【最终修复】使用 fetch_guild 强制从API获取服务器对象，不再依赖缓存
        try:
            guild = await bot.fetch_guild(guild_id)
        except (discord.NotFound, discord.Forbidden):
            # 如果服务器不存在或机器人被踢了，则直接返回错误
            return {'status': 'error', 'message': '服务器未找到或机器人不在该服务器中'}, 404
        
        # 使用 fetch_channel 强制从API获取频道对象
        try:
            channel = await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return {'status': 'error', 'message': '票据频道未找到或已删除'}, 404
        
        # 验证这确实是一个文本频道
        if not isinstance(channel, discord.TextChannel):
            return {'status': 'error', 'message': '目标ID不是一个有效的文本频道'}, 400

        # 使用数据库验证该频道是否为一个有效的、开启的票据
        ticket_info = database.db_get_ticket_by_channel(channel_id)
        if not ticket_info or ticket_info['status'] not in ['OPEN', 'CLAIMED']:
            return {'status': 'error', 'message': '非法的票据频道ID或该票据已关闭'}, 403

        # (后续的聊天记录获取逻辑保持不变)
        history = []
        async for message in channel.history(limit=100, oldest_first=True):
            safe_embeds = []
            for embed in message.embeds:
                safe_embed = {
                    'title': getattr(embed, 'title', None),
                    'description': getattr(embed, 'description', None),
                    'color': embed.color.value if embed.color else None,
                    'author': {'name': embed.author.name} if getattr(embed, 'author', None) and getattr(embed.author, 'name', None) else None,
                    'footer': {'text': embed.footer.text} if getattr(embed, 'footer', None) and getattr(embed.footer, 'text', None) else None
                }
                safe_embeds.append(safe_embed)
            
            history.append({
                'id': str(message.id),
                'author': {
                    'id': str(message.author.id),
                    'name': message.author.display_name,
                    'avatar_url': str(message.author.display_avatar.url),
                    'is_bot': message.author.bot
                },
                'content': message.clean_content,
                'embeds': safe_embeds,
                'timestamp': message.created_at.isoformat()
            })
            
        return {'status': 'success', 'history': history}, 200
    except discord.Forbidden:
        return {'status': 'error', 'message': '机器人缺少读取此频道历史记录的权限。'}, 403
    except Exception as e:
        logging.error(f"CRITICAL ERROR in _get_ticket_history_async for G:{guild_id} C:{channel_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': f'处理历史记录时发生严重的内部错误: {type(e).__name__}'}, 500



async def _create_backup_async(guild_id):
    """
    异步辅助函数，用于创建服务器备份数据。
    【V6 - 权限增强版】
    - 备份所有可管理角色的通用权限。
    - 备份所有频道和分类的权限覆盖(overwrites)。
    - 确保所有ID都为字符串，防止JS精度问题。
    """
    guild = bot.get_guild(guild_id)
    if not guild:
        return None

    backup_data = {
        "version": 2, # 版本号提升，表明包含权限数据
        "timestamp": discord.utils.utcnow().isoformat(),
        "guild_info": {
            "name": guild.name,
            "id": str(guild.id)
        },
        "roles": [],
        "categories": [],
        "text_channels": [],
        "voice_channels": []
    }

    # 按位置顺序备份身份组 (从高到低)，这样恢复时可以保持大致的层级顺序
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if role.is_default() or role.is_bot_managed() or role.is_integration() or role.is_premium_subscriber():
            continue

        backup_data["roles"].append({
            "original_id": str(role.id),
            "name": role.name,
            "color": role.color.value,
            "permissions": role.permissions.value, # 【新增】备份通用权限
            "hoist": role.hoist,
            "mentionable": role.mentionable
        })

    # 将所有频道一次性获取，然后分类处理
    all_guild_channels = guild.channels
    
    # 备份分类及其权限覆盖
    for channel in sorted(all_guild_channels, key=lambda c: c.position):
        if not isinstance(channel, discord.CategoryChannel):
            continue

        overwrites_data = []
        # 【新增】遍历权限覆盖
        for target, overwrite in channel.overwrites.items():
            if not isinstance(target, (discord.Role, discord.Member)): continue # 仅处理角色和成员
            # 排除 @everyone，因为它将在恢复时特殊处理
            if isinstance(target, discord.Role) and target.is_default(): continue
                
            allow, deny = overwrite.pair()
            overwrites_data.append({
                "target_original_id": str(target.id),
                "target_type": "role" if isinstance(target, discord.Role) else "member",
                "allow": allow.value,
                "deny": deny.value
            })
        
        backup_data["categories"].append({
            "original_id": str(channel.id),
            "name": channel.name,
            "overwrites": overwrites_data # 【新增】保存权限覆盖
        })

    # 备份文本和语音频道及其权限覆盖
    for channel in sorted(all_guild_channels, key=lambda c: c.position):
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            continue
            
        overwrites_data = []
        # 【新增】遍历权限覆盖
        for target, overwrite in channel.overwrites.items():
            if not isinstance(target, (discord.Role, discord.Member)): continue
            if isinstance(target, discord.Role) and target.is_default(): continue
            
            allow, deny = overwrite.pair()
            overwrites_data.append({
                "target_original_id": str(target.id),
                "target_type": "role" if isinstance(target, discord.Role) else "member",
                "allow": allow.value,
                "deny": deny.value
            })

        channel_info = {
            "name": channel.name,
            "category_original_id": str(channel.category.id) if channel.category else None,
            "overwrites": overwrites_data # 【新增】保存权限覆盖
        }

        if isinstance(channel, discord.TextChannel):
            channel_info["topic"] = channel.topic
            backup_data["text_channels"].append(channel_info)
        elif isinstance(channel, discord.VoiceChannel):
            channel_info["user_limit"] = channel.user_limit
            channel_info["bitrate"] = channel.bitrate
            backup_data["voice_channels"].append(channel_info)

    return backup_data




@web_app.route('/api/guild/<int:guild_id>/backup', methods=['GET'])
def api_create_backup(guild_id):
    # 权限检查
    user_info = session.get('user', {})
    guild = bot.get_guild(guild_id)
    if not guild: return jsonify(status="error", message="服务器未找到"), 404
    is_owner = (not user_info.get('is_sub_account') and str(user_info.get('id')) == str(guild.owner_id))
    if not user_info.get('is_superuser') and not is_owner: return jsonify(status="error", message="无权访问"), 403
    
    future = asyncio.run_coroutine_threadsafe(_create_backup_async(guild_id), bot.loop)
    try:
        backup_data = future.result(timeout=30)
        if backup_data is None:
            return jsonify(status="error", message="创建备份失败，服务器未找到"), 404

        backup_json = json.dumps(backup_data, indent=4, ensure_ascii=False)
        filename = f"backup-{guild.name.replace(' ', '_')}-{datetime.datetime.now().strftime('%Y%m%d')}.json"
        
        # 使用 BytesIO 在内存中创建文件，避免磁盘读写
        str_io = io.BytesIO(backup_json.encode('utf-8'))
        
        return send_file(str_io,
                         mimetype='application/json',
                         as_attachment=True,
                         download_name=filename)

    except Exception as e:
        logging.error(f"创建备份时出错 (Guild {guild_id}): {e}", exc_info=True)
        return jsonify(status="error", message=f"创建备份时发生内部错误: {e}"), 500

async def _perform_restore_async(guild_id, backup_data, sid):
    """
    【V6 - 权限增强版】长时间运行的恢复任务。
    - 恢复所有角色及其通用权限。
    - 恢复所有频道和分类。
    - 在所有结构创建完毕后，统一恢复所有频道的权限覆盖。
    """
    # 辅助函数，用于向前端发送日志
    def log_progress(message, type='info'):
        print(f"[恢复 G:{guild_id}] {message}")
        socketio.emit('restore_progress', {'message': message, 'type': type}, room=sid)
        socketio.sleep(0) # 谦让给 eventlet，确保消息能及时发出

    try:
        guild = bot.get_guild(guild_id)
        if not guild:
            log_progress(f"错误：在异步任务开始时找不到服务器 {guild_id}。", 'error')
            socketio.emit('restore_finished', {'status': 'error'}, room=sid)
            return

        log_progress('恢复进程已启动...', 'info')
        
        # --- 阶段 1: 删除现有结构 ---
        log_progress('--- 阶段 1: 删除现有结构 (此过程可能需要几分钟，请耐心等待) ---', 'warn')
        
        log_progress(f"开始删除服务器中的 {len(guild.channels)} 个频道...")
        for channel in guild.channels:
            try:
                log_progress(f"  正在删除频道: #{channel.name}...")
                await channel.delete(reason="服务器恢复")
                await asyncio.sleep(1.2)
            except discord.HTTPException as e:
                log_progress(f"  警告：删除频道 #{channel.name} 失败 (可能是必要频道或权限问题): {e}", 'warn')

        log_progress(f"开始删除服务器中的 {len(guild.roles)} 个身份组...")
        for role in sorted(guild.roles, key=lambda r: r.position):
             if not role.is_default() and not role.is_bot_managed() and not role.is_integration() and not role.is_premium_subscriber():
                try:
                    log_progress(f"  正在删除身份组: @{role.name}...")
                    await role.delete(reason="服务器恢复")
                    await asyncio.sleep(1.2)
                except discord.HTTPException as e:
                    log_progress(f"  警告：删除身份组 @{role.name} 失败 (可能是层级问题): {e}", 'warn')

        log_progress('阶段 1 完成。', 'success')
        
        # --- 阶段 2: 创建新结构 (角色与频道) ---
        log_progress('--- 阶段 2: 创建新结构 ---', 'warn')
        role_map = {} # { old_id_str: new_role_object }
        
        # 从上到下创建身份组 (因为备份时是从高到低存的，所以用reversed)
        for role_data in reversed(backup_data.get('roles', [])):
            log_progress(f"  正在创建身份组: @{role_data['name']}...")
            new_role = await guild.create_role(
                name=role_data['name'],
                permissions=discord.Permissions(role_data['permissions']),
                color=discord.Color(role_data['color']),
                hoist=role_data['hoist'],
                mentionable=role_data['mentionable'],
                reason="服务器恢复"
            )
            role_map[role_data['original_id']] = new_role
            await asyncio.sleep(1.2)

        category_map = {} # { old_id_str: new_category_object }
        for cat_data in backup_data.get('categories', []):
            log_progress(f"  正在创建分类: {cat_data['name']}...")
            new_cat = await guild.create_category(name=cat_data['name'], reason="服务器恢复")
            category_map[cat_data['original_id']] = new_cat
            await asyncio.sleep(1.2)
        
        # 创建文本和语音频道
        for chan_data in backup_data.get('text_channels', []):
            category = category_map.get(chan_data.get('category_original_id'))
            log_progress(f"  正在创建文本频道: #{chan_data['name']}...")
            await guild.create_text_channel(name=chan_data['name'], topic=chan_data.get('topic'), category=category, reason="服务器恢复")
            await asyncio.sleep(1.2)
            
        for chan_data in backup_data.get('voice_channels', []):
            category = category_map.get(chan_data.get('category_original_id'))
            log_progress(f"  正在创建语音频道: #{chan_data['name']}...")
            await guild.create_voice_channel(name=chan_data['name'], user_limit=chan_data.get('user_limit',0), bitrate=chan_data.get('bitrate', 64000), category=category, reason="服务器恢复")
            await asyncio.sleep(1.2)
        log_progress('阶段 2 完成。', 'success')

        # --- 【【【新增/增强】】】 阶段 3: 应用权限 ---
        log_progress('--- 阶段 3: 应用权限 (这可能需要一些时间) ---', 'warn')
        log_progress('等待Discord同步新创建的频道和身份组...', 'info')
        await asyncio.sleep(5) # 给Discord一点时间处理所有创建操作
        
        # 重新获取所有频道和身份组以确保我们有最新的对象
        fresh_channels = {c.name: c for c in await guild.fetch_channels()}
        fresh_roles = {r.name: r for r in await guild.fetch_roles()}
        
        # 更新role_map和category_map，使用新的、新鲜的对象
        for old_id, old_role_obj in list(role_map.items()):
            if old_role_obj.name in fresh_roles:
                role_map[old_id] = fresh_roles[old_role_obj.name]
        for old_id, old_cat_obj in list(category_map.items()):
            if old_cat_obj.name in fresh_channels:
                 category_map[old_id] = fresh_channels[old_cat_obj.name]

        all_channels_data = backup_data.get('categories', []) + backup_data.get('text_channels', []) + backup_data.get('voice_channels', [])
        for chan_data in all_channels_data:
            channel = fresh_channels.get(chan_data['name'])
            if not channel:
                log_progress(f"警告：找不到频道/分类 '{chan_data['name']}' 来应用权限。", 'warn')
                continue
            
            for overwrite_data in chan_data.get('overwrites', []):
                if overwrite_data['target_type'] == 'role':
                    target_role = role_map.get(overwrite_data['target_original_id'])
                    if not target_role: continue
                    
                    overwrite = discord.PermissionOverwrite()
                    overwrite.update(allow=discord.Permissions(overwrite_data['allow']), deny=discord.Permissions(overwrite_data['deny']))
                    
                    try:
                        await channel.set_permissions(target_role, overwrite=overwrite, reason="服务器恢复")
                        log_progress(f"  已应用权限到 '{channel.name}' for '@{target_role.name}'")
                        await asyncio.sleep(0.8) # 权限更新也需要慢一点
                    except Exception as perm_err:
                        log_progress(f"  错误: 应用权限到 '{channel.name}' for '@{target_role.name}' 失败: {perm_err}", 'error')
                # (暂时不处理成员的特定权限覆盖，以简化流程)

        log_progress('✅ 服务器恢复完成！', 'success')
        socketio.emit('restore_finished', {'status': 'success'}, room=sid)

    except Exception as e:
        log_progress(f'恢复过程中发生严重错误: {e}', 'error')
        logging.error(f"恢复服务器 {guild_id} 时出错: {e}", exc_info=True)
        socketio.emit('restore_finished', {'status': 'error'}, room=sid)

@web_app.route('/api/guild/<int:guild_id>/restore', methods=['POST'])
def api_restore_from_backup(guild_id):
    # 再次检查权限
    user_info = session.get('user', {})
    guild = bot.get_guild(guild_id)
    if not guild: return jsonify(status="error", message="服务器未找到"), 404
    is_owner = (not user_info.get('is_sub_account') and str(user_info.get('id')) == str(guild.owner_id))
    if not user_info.get('is_superuser') and not is_owner: return jsonify(status="error", message="无权访问"), 403
    
    # request.sid 只有在 socketio 请求上下文中才存在，普通http请求没有
    # 我们需要在前端连接socket之后，再通过socket事件来触发这个
    # 或者，我们可以假设前端在发送这个HTTP请求的同时，已经连接了socket
    # 我们这里采用后者，因为更简单。但请注意，request.sid 可能为 None
    # 【修正】让前端在连接socket之后，再通过一个socket事件来请求恢复
    # 但为了简化，我们先用HTTP启动，然后通过session id或类似方式通信，但最简单的还是直接用socketio
    # 我们这里修改为直接从HTTP请求启动后台任务，并使用请求的sid来通信
    
    if 'file' not in request.files:
        return jsonify(status="error", message="请求中缺少文件。"), 400
    
    file = request.files['file']
    confirmation = request.form.get('confirmation')

    if file.filename == '':
        return jsonify(status="error", message="未选择文件。"), 400
        
    if not confirmation or confirmation != f"{guild.name}/RESTORE":
        return jsonify(status="error", message="确认短语不匹配！"), 400
    
    try:
        backup_data = json.load(file.stream)
    except json.JSONDecodeError:
        return jsonify(status="error", message="文件不是有效的JSON格式。"), 400
    
    # 【重要】sid 是socket.io的会话ID，普通http请求没有。
    # 这里我们需要让前端在连接socket后，再通过socket事件来触发这个任务。
    # 但为了让当前代码能跑，我们假设前端会先连接socket。这是一个常见的实现模式。
    # 如果你的前端是先发送HTTP再连接socket，这里会失败。
    # 我们将修改JS部分来确保先连接socket。
    sid = request.sid # 这在普通的Flask HTTP请求中是None
                     # 必须在SocketIO事件处理函数中获取

    # 因为HTTP请求无法获取sid，我们将这个接口改为纯粹的socketio事件
    # 但是为了保持RESTful风格，我们让前端先传文件，后端验证后，前端再发socket事件开始任务
    # 这个逻辑有点复杂，我们先简化：假设这个接口仅用于验证，真正启动通过socket
    
    # 简化版：直接启动后台任务。我们需要客户端的socket ID
    # 这是一个鸡生蛋蛋生鸡问题。我们换一种思路：
    # 前端发送HTTP请求 -> 后端返回"OK, 准备就绪" -> 前端连接Socket -> 前端发送"start"事件 -> 后端在事件处理函数中获取sid并启动任务
    
    # 最简单的实现：HTTP请求直接启动后台任务，但我们无法简单地将进度发回给这个请求。
    # 因此，使用SocketIO是必须的。
    
    # 我们修改流程：前端直接通过Socket.IO发送恢复请求
    # (见下面的JS修改)
    # 这个HTTP端点将不再被直接用于启动恢复

    return jsonify(status="error", message="此端点已弃用，请通过Socket.IO启动恢复。"), 405


# --- 异步处理函数 ---


async def send_reply_to_discord(guild_id, channel_id, user_info, content):
    guild = bot.get_guild(int(guild_id))
    if not guild: return
    channel = guild.get_channel(int(channel_id))
    if not channel: return
    try:
        embed = discord.Embed(description=content, color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        moderator_name = user_info.get('username', '管理员')
        moderator_avatar = user_info.get('avatar', bot.user.display_avatar.url)
        embed.set_author(name=f"来自Web面板的回复 - {moderator_name}", icon_url=moderator_avatar)
        
        sent_message = await channel.send(embed=embed)

        # 【【【新增代码，请确保这部分逻辑被添加或修改】】】
        ticket_info = database.db_get_ticket_by_channel(int(channel_id))
        if ticket_info:
            # 只要人工回复，就关闭AI托管
            database.db_set_ticket_ai_managed_status(ticket_info['ticket_id'], False)
            # 通过socket通知前端，AI状态已改变
            if socketio:
                socketio.emit('ticket_ai_status_changed', {
                    'ticket_id': str(ticket_info['ticket_id']),
                    'is_ai_managed': False
                }, room=f'tickets_{guild_id}')
        # 【【【新增代码结束】】】

        if socketio:
            msg_data_for_web = {
                'id': str(sent_message.id),
                'author': {
                    'id': str(user_info.get('id', 'web_user')),
                    'name': moderator_name,
                    'avatar_url': moderator_avatar,
                    'is_bot': False
                },
                'content': sent_message.clean_content,
                'embeds': [e.to_dict() for e in sent_message.embeds],
                'timestamp': sent_message.created_at.isoformat(),
                'channel_id': str(channel.id)
            }
            socketio.emit('new_ticket_message', msg_data_for_web, room=f'ticket_{channel.id}')

    except Exception as e:
        print(f"从Web面板发送票据回复到频道 {channel_id} 时出错: {e}")

async def perform_bulk_action(guild_id, data, user_session):
    guild = bot.get_guild(guild_id)
    if not guild: return jsonify(status="error", message="服务器未找到"), 404
    bulk_action_permissions = {
        'bulk_add_role': 'tab_roles',
        'bulk_remove_role': 'tab_roles',
        'bulk_kick': 'tab_members',
    }
    required_permission = bulk_action_permissions.get(data.get('action'))
    if required_permission is None:
        return jsonify(status="error", message="未知的批量操作。"), 400
    is_authed, error = check_auth(guild_id, required_permission=required_permission)
    if not is_authed:
        return jsonify(status="error", message=error[0]), error[1]
    user_info = user_session.get('user', {})
    moderator_display_name = user_info.get('username', '未知管理员')
    moderator_member = None
    if not user_info.get('is_sub_account') and not user_info.get('is_superuser'):
        try: moderator_member = await guild.fetch_member(int(user_info.get('id')))
        except (ValueError, TypeError, discord.NotFound): return jsonify(status="error", message="无法验证管理员身份。"), 403
    action = data.get('action'); target_ids = data.get('target_ids', []); role_id_str = data.get('role_id')
    if not all([action, target_ids]): return jsonify(status="error", message="请求中缺少 'action' 或 'target_ids'。"), 400
    if action in ['bulk_add_role', 'bulk_remove_role'] and not role_id_str: return jsonify(status="error", message="批量添加/移除身份组需要 'role_id'。"), 400
    role = guild.get_role(int(role_id_str)) if role_id_str else None
    if action in ['bulk_add_role', 'bulk_remove_role'] and not role: return jsonify(status="error", message="未找到指定的身份组。"), 404
    bot_member = guild.me
    if role and role >= bot_member.top_role and guild.owner_id != bot_member.id: return jsonify(status="error", message=f"无法操作身份组 '{role.name}'，层级过高。"), 403
    success_count = 0; fail_count = 0
    reason = f"由 {moderator_display_name} 从Web面板批量操作"
    for user_id in target_ids:
        try:
            member = await guild.fetch_member(int(user_id))
            if moderator_member and member.top_role >= moderator_member.top_role and guild.owner_id != moderator_member.id:
                fail_count += 1; continue
            if action == 'bulk_add_role': await member.add_roles(role, reason=reason)
            elif action == 'bulk_remove_role': await member.remove_roles(role, reason=reason)
            elif action == 'bulk_kick':
                 if member.id != guild.owner_id: await member.kick(reason=reason)
                 else: fail_count += 1; continue
            success_count += 1
            await asyncio.sleep(0.2)
        except Exception as e: fail_count += 1; logging.warning(f"批量操作失败 (用户: {user_id}, 操作: {action}): {e}")
    return jsonify(status="success", message=f"批量操作完成！成功 {success_count} 个，失败 {fail_count} 个。")

async def process_audit_action(guild_id, data, moderator_name):
    guild = bot.get_guild(guild_id)
    if not guild: 
        return {'status': 'error', 'message': '未找到服务器'}, 404

    action = data.get('action')
    target_user_id = int(data.get('target_user_id'))
    message_id = int(data.get('message_id'))
    channel_id = int(data.get('channel_id'))
    event_id = data.get('event_id')
    channel = guild.get_channel(channel_id)
    
    try: 
        member = await guild.fetch_member(target_user_id)
    except discord.NotFound: 
        return {'status': 'error', 'message': f'未在服务器中找到ID为 {target_user_id} 的用户。'}, 404
    except Exception as e: 
        return {'status': 'error', 'message': f'获取用户信息时出错: {e}'}, 500

    reason = f"由 {moderator_name} 从Web审核面板处理"
    
    def update_db_status(new_status):
        if event_id:
            handler_id_str = session.get('user', {}).get('id')
            handler_id = None
            if isinstance(handler_id_str, str) and not handler_id_str.isdigit(): 
                handler_id = None
            elif handler_id_str:
                try: 
                    handler_id = int(handler_id_str)
                except (ValueError, TypeError): 
                    handler_id = None
            database.db_update_audit_status(int(event_id), new_status.upper(), handler_id)
            print(f"[DB Audit] Event ID {event_id} status updated to {new_status.upper()} by {handler_id or moderator_name}")

    try:
        if action == 'audit_ignore':
            update_db_status('ignored')
            return {'status': 'success', 'message': f'已忽略对 {member.display_name} 的事件。'}, 200

        elif action == 'audit_delete':
            if channel:
                try: 
                    await (await channel.fetch_message(message_id)).delete()
                    update_db_status('handled')
                    return {'status': 'success', 'message': f'已删除 {member.display_name} 的消息。'}, 200
                except discord.NotFound: 
                    update_db_status('handled')
                    return {'status': 'success', 'message': '消息已被删除。'}, 200
            else: 
                return {'status': 'error', 'message': '找不到原始频道，无法删除消息。'}, 404

        elif action == 'audit_warn' or action == 'audit_warn_and_delete':
            guild_warnings = user_warnings.setdefault(guild.id, {})
            guild_warnings[target_user_id] = guild_warnings.get(target_user_id, 0) + 1
            count = guild_warnings[target_user_id]
            log_embed = discord.Embed(title="⚠️ Web面板手动警告", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
            log_embed.add_field(name="被警告用户", value=f"{member.mention} ({member.id})", inline=False).add_field(name="执行管理员", value=moderator_name, inline=False).add_field(name="原因", value="内容审查", inline=False).add_field(name="当前警告次数", value=f"{count}/{KICK_THRESHOLD}", inline=False)
            
            if count >= KICK_THRESHOLD:
                log_embed.title = "🚨 警告已达上限 - 自动踢出 🚨"
                log_embed.color = discord.Color.red()
                if guild.me.guild_permissions.kick_members and guild.me.top_role > member.top_role:
                    await member.kick(reason=f"自动踢出: 警告达到{KICK_THRESHOLD}次 (Web审核操作)")
                    log_embed.add_field(name="踢出状态", value="✅ 成功")
                    guild_warnings[member.id] = 0
                else: 
                    log_embed.add_field(name="踢出状态", value="❌ 失败 (权限/层级不足)")
            
            await send_to_public_log(guild, log_embed, "Web-Audit Warn")
            success_message = f'已警告用户 {member.display_name}。'
            
            if action == 'audit_warn_and_delete' and channel:
                try: 
                    await (await channel.fetch_message(message_id)).delete()
                    success_message = f'已警告用户 {member.display_name} 并删除了其消息。'
                except discord.NotFound: 
                    success_message += ' (消息已被删除)'
            
            update_db_status('handled')
            return {'status': 'success', 'message': success_message}, 200

    except discord.Forbidden as e: 
        return {'status': 'error', 'message': f'操作被禁止: {e.text}'}, 403
    except discord.HTTPException as e: 
        return {'status': 'error', 'message': f'Discord API 错误: {e.text} (代码: {e.code})'}, 500
    except Exception as e: 
        logging.exception("Error processing audit action")
        return {'status': 'error', 'message': f'内部错误: {e}'}, 500

    return {'status': 'error', 'message': '未知的审核操作'}, 400

async def perform_action(guild_id, action, data, user_session):
    # 动作与所需权限的映射关系 (这个字典是完整的)
    ACTION_PERMISSIONS = {
        'manage_roles': 'tab_roles', 'warn': 'page_warnings', 'unwarn': 'page_warnings', 
        'vc_kick': 'page_channel_control', 'vc_mute': 'page_channel_control', 'vc_unmute': 'page_channel_control', 
        'vc_deafen': 'page_channel_control', 'vc_undeafen': 'page_channel_control', 
        'kick': 'tab_members', 'ban': 'tab_members', 'unmute': 'page_moderation', 'delete_role': 'tab_roles',
        'ai_exempt_remove_user': 'page_audit_core',
        'ai_exempt_remove_channel': 'page_audit_core',
        'ai_dep_channel_remove': 'page_settings',
        'kb_remove': 'tab_ai_faq'
    }
    
    # 提取基础动作名 (例如 'action/vc_mute' -> 'vc_mute')
    base_action = action.split('/')[-1]
    required_permission = ACTION_PERMISSIONS.get(base_action)
    if required_permission is None:
        return jsonify(status="error", message=f"未知或未授权的操作: {action}"), 400
    
    # --- 完整的权限检查 ---
    if required_permission == 'is_superuser_only':
        if not user_session.get('user', {}).get('is_superuser'):
            return jsonify(status="error", message="权限不足"), 403
    elif required_permission: # 如果动作需要权限
        is_authed, error = check_auth(guild_id, required_permission=required_permission)
        if not is_authed: 
            return jsonify(status="error", message=error[0]), error[1]
    
    guild = bot.get_guild(guild_id)
    if not guild: 
        return jsonify(status="error", message="服务器未找到"), 404
    
    
    base_action = action.split('/')[-1] # 我们在这里也获取一下 base_action
    

    
    
    
    user_info = user_session.get('user', {})
    moderator_display_name = user_info.get('username', '未知管理员')
    moderator_member = None
    
    if not user_info.get('is_sub_account') and not user_info.get('is_superuser'):
        try:
            moderator_id = int(user_info.get('id'))
            moderator_member = await guild.fetch_member(moderator_id)
        except (ValueError, TypeError, discord.NotFound):
            return jsonify(status="error", message="无法验证管理员身份。"), 403

    reason = data.get('reason', f"由 {moderator_display_name} 从Web面板操作")
    
    try:
        target_id_str = data.get('target_id') or data.get('member_id')
        if not target_id_str: 
            return jsonify(status="error", message="请求中缺少目标ID"), 400
        target_id = int(target_id_str)

        # --- 不需要成员对象的操作 ---
        if base_action == 'delete_role':
            role = guild.get_role(target_id)
            if not role: return jsonify(status="error", message="未找到该身份组。"), 404
            if role.is_integration() or role.is_premium_subscriber() or role.managed or role >= guild.me.top_role:
                return jsonify(status="error", message=f"无法删除特殊身份组或层级过高的身份组 '{role.name}'。"), 400
            await role.delete(reason=reason)
            return jsonify(status="success", message=f"已删除身份组 {role.name}。")

        elif base_action == 'kb_remove':
            entry_order_to_remove = target_id # target_id 就是前端传来的序号
            success = database.db_remove_knowledge_base_entry_by_order(guild.id, entry_order_to_remove)
            if success:
                return jsonify(status="success", message=f"已成功删除知识库条目 #{entry_order_to_remove}。")
            else:
                return jsonify(status="error", message=f"删除知识库条目 #{entry_order_to_remove} 失败，可能序号无效。"), 400

        
        if base_action == 'ai_exempt_remove_user':
            exempt_users_from_ai_check.discard(target_id)
            print(f"[AI豁免] 管理员 {moderator_display_name} 从Web面板移除了用户 {target_id} 的豁免。")
            return jsonify(status="success", message=f"已从AI豁免列表移除用户 {target_id}。")

        if base_action == 'ai_exempt_remove_channel':
            exempt_channels_from_ai_check.discard(target_id)
            channel = guild.get_channel(target_id)
            print(f"[AI豁免] 管理员 {moderator_display_name} 从Web面板移除了频道 #{channel.name if channel else target_id} 的豁免。")
            return jsonify(status="success", message=f"已从AI豁免列表移除频道 {target_id}。")

        if base_action == 'ai_dep_channel_remove':
            channel_id_to_remove = int(target_id)
            if channel_id_to_remove in ai_dep_channels_config:
                del ai_dep_channels_config[channel_id_to_remove]
                save_server_settings()
                channel_name = guild.get_channel(channel_id_to_remove)
                print(f"[AI Settings] 管理员 {moderator_display_name} 从Web面板移除了AI频道 #{channel_name if channel_name else target_id}。")
                return jsonify(status="success", message=f"已成功移除AI频道设置。")
            else:
                return jsonify(status="error", message="该频道不是AI频道。"), 404
        
        # --- 需要成员对象的操作 ---
        try:
            member = await guild.fetch_member(target_id)
        except discord.NotFound:
            # 对于ban操作，即使用户不在服务器内也可以执行
            if base_action == 'ban':
                member = None 
            else:
                return jsonify(status="error", message=f"在服务器中未找到ID为 {target_id} 的成员。"), 404

        # 仅当成员在服务器内时才进行层级检查
        if member:
            if target_id == guild.owner_id and (not moderator_member or moderator_member.id != guild.owner_id):
                return jsonify(status="error", message="操作失败：不能对服务器所有者执行管理操作。"), 403
            if moderator_member and member.top_role >= moderator_member.top_role and guild.owner_id != moderator_member.id:
                return jsonify(status="error", message="权限不足，无法对该成员操作。"), 403
        
        # --- 【新增】处理 'kick' 和 'ban' 操作 ---
        if base_action == 'kick':
            if not member: return jsonify(status="error", message="无法踢出不在服务器内的用户。"), 404
            await member.kick(reason=reason)
            database.db_log_moderation_action(guild.id, member.id, moderator_member.id if moderator_member else None, 'kick', reason, int(time.time()))
            return jsonify(status="success", message=f"已成功踢出用户 {member.display_name}。")

        # ↓↓↓↓ 在这里粘贴新增的 ban 逻辑 ↓↓↓↓
        elif base_action == 'ban':
            # 封禁操作可以针对不在服务器内的用户ID执行，所以我们用 target_id
            user_to_ban_obj = discord.Object(id=target_id)
            await guild.ban(user_to_ban_obj, reason=reason, delete_message_days=0)
            
            # 记录到数据库
            database.db_log_moderation_action(guild.id, target_id, moderator_member.id if moderator_member else None, 'ban', reason, int(time.time()))
            
            # 准备友好的返回信息
            user_display = member.display_name if member else f"用户ID {target_id}"
            return jsonify(status="success", message=f"已成功封禁用户 {user_display}。")
        # ↑↑↑ 新增逻辑结束 ↑↑↑

        elif base_action == 'warn':
            guild_warnings = user_warnings.setdefault(guild.id, {})
            current_warnings = guild_warnings.get(member.id, 0) + 1
            guild_warnings[member.id] = current_warnings
            
            log_embed = discord.Embed(title="⚠️ Web面板手动警告", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
            log_embed.add_field(name="被警告用户", value=f"{member.mention} ({member.id})", inline=False)
            log_embed.add_field(name="执行管理员", value=moderator_display_name, inline=False)
            log_embed.add_field(name="原因", value=reason, inline=False)
            log_embed.add_field(name="当前警告次数", value=f"{current_warnings}/{KICK_THRESHOLD}", inline=False)
            
            kick_message = ""
            if current_warnings >= KICK_THRESHOLD:
                log_embed.title = "🚨 警告已达上限 - 自动踢出 🚨"
                log_embed.color = discord.Color.red()
                if guild.me.guild_permissions.kick_members and (not member.top_role >= guild.me.top_role or guild.me.id == guild.owner_id):
                    try:
                        await member.kick(reason=f"自动踢出: 警告达到{KICK_THRESHOLD}次 (Web操作)")
                        log_embed.add_field(name="踢出状态", value="✅ 成功")
                        guild_warnings[member.id] = 0 # 重置警告
                        kick_message = f" 用户已达到警告上限并被踢出！"
                    except discord.Forbidden:
                        log_embed.add_field(name="踢出状态", value="❌ 失败 (权限不足)")
                        kick_message = f" 用户已达到警告上限，但踢出失败（权限不足）！"
                else:
                    log_embed.add_field(name="踢出状态", value="❌ 失败 (层级不足)")
                    kick_message = f" 用户已达到警告上限，但踢出失败（层级不足）！"

            await send_to_public_log(guild, log_embed, "Web Warn")
            return jsonify(status="success", message=f"已成功警告用户 {member.display_name}。{kick_message}")

        elif base_action == 'unwarn':
            guild_warnings = user_warnings.setdefault(guild.id, {})
            current_warnings = guild_warnings.get(member.id, 0)
            if current_warnings > 0:
                guild_warnings[member.id] = current_warnings - 1
                log_embed = discord.Embed(title="✅ Web面板撤销警告", color=discord.Color.green(), timestamp=discord.utils.utcnow())
                log_embed.add_field(name="用户", value=f"{member.mention} ({member.id})", inline=False)
                log_embed.add_field(name="操作管理员", value=moderator_display_name, inline=False)
                log_embed.add_field(name="原因", value=reason, inline=False)
                log_embed.add_field(name="新的警告次数", value=f"{guild_warnings[member.id]}/{KICK_THRESHOLD}", inline=False)
                await send_to_public_log(guild, log_embed, "Web Unwarn")
                return jsonify(status="success", message=f"已为用户 {member.display_name} 撤销一次警告。")
            else:
                return jsonify(status="error", message=f"用户 {member.display_name} 没有警告记录可以撤销。"), 400
        
        elif base_action == 'vc_kick':
            if not member.voice or not member.voice.channel:
                return jsonify(status="error", message="用户不在任何语音频道中。"), 400
            await member.move_to(None, reason=reason)
            return jsonify(status="success", message=f"已将 {member.display_name} 踢出语音频道。")

        elif base_action == 'vc_mute':
            if not member.voice or not member.voice.channel:
                return jsonify(status="error", message="用户不在任何语音频道中。"), 400
            await member.edit(mute=True, reason=reason)
            return jsonify(status="success", message=f"已将 {member.display_name} 在语音中禁麦。")
            
        elif base_action == 'vc_unmute':
            if not member.voice or not member.voice.channel:
                return jsonify(status="error", message="用户不在任何语音频道中。"), 400
            await member.edit(mute=False, reason=reason)
            return jsonify(status="success", message=f"已为 {member.display_name} 解除语音禁麦。")

        elif base_action == 'vc_deafen':
            if not member.voice or not member.voice.channel:
                return jsonify(status="error", message="用户不在任何语音频道中。"), 400
            await member.edit(deafen=True, reason=reason)
            return jsonify(status="success", message=f"已将 {member.display_name} 在语音中设为禁听。")

        elif base_action == 'vc_undeafen':
            if not member.voice or not member.voice.channel:
                return jsonify(status="error", message="用户不在任何语音频道中。"), 400
            await member.edit(deafen=False, reason=reason)
            return jsonify(status="success", message=f"已为 {member.display_name} 解除禁听。")

        elif base_action == 'unmute':
            if not member: return jsonify(status="error", message="无法解除不在服务器内用户的禁言。"), 404
            await member.timeout(None, reason=reason)
            active_log = database.db_get_latest_active_log_for_user(guild.id, target_id, 'mute')
            if active_log:
                handler_id = moderator_member.id if moderator_member else None
                database.db_deactivate_log(active_log['log_id'], reason, handler_id)
            database.db_log_moderation_action(guild.id, target_id, moderator_member.id if moderator_member else None, 'unmute', reason, int(time.time()))
            return jsonify(status="success", message=f"已解除用户 {member.display_name} 的禁言。")

        # 如果所有条件都不匹配，则返回未知操作
        return jsonify(status="error", message=f"未知的操作: {action}"), 400

    except discord.Forbidden as e: 
        return jsonify(status="error", message=f"操作被禁止: {e.text}"), 403
    except discord.HTTPException as e: 
        return jsonify(status="error", message=f"Discord API 错误: {e.text} (代码: {e.code})"), 500
    except Exception as e: 
        logging.exception(f"API Action Error for action '{action}'")
        return jsonify(status="error", message=f"发生内部服务器错误: {e}"), 500

async def handle_form_submission(guild_id, data, user_session):
    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(status="error", message="服务器未找到"), 404
    
    user_info = user_session.get('user', {})
    moderator_display_name = user_info.get('username', '未知管理员')
    moderator_id_for_db = None
    
    user_id_str = user_info.get('id')
    if user_id_str and user_id_str.isdigit():
        try:
            moderator_id_for_db = int(user_id_str)
        except (ValueError, TypeError):
            moderator_id_for_db = None

    form_id = data.pop('form_id', None)
    if not form_id:
        return jsonify(status="error", message="请求中缺少 form_id。"), 400

    try:
        # --- 公告表单 ---
        if form_id == 'announce-form':
            is_authed, error = check_auth(guild_id, 'page_announcements')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            channel_id_str = data.get('channel_id')
            title = data.get('title')
            message = data.get('message')
            if not all([channel_id_str, title, message]):
                return jsonify(status="error", message="频道、标题和消息内容都是必填项。"), 400
            
            channel = guild.get_channel(int(channel_id_str))
            if not channel or not isinstance(channel, discord.TextChannel):
                return jsonify(status="error", message="未找到有效的文本频道。"), 404
            
            if not channel.permissions_for(guild.me).send_messages or not channel.permissions_for(guild.me).embed_links:
                return jsonify(status="error", message=f"机器人在频道 #{channel.name} 缺少权限。"), 403
            
            color_str = data.get('color', '#5865F2').lstrip('#')
            embed_color = discord.Color.blue()
            try:
                embed_color = discord.Color(int(color_str, 16))
            except ValueError: pass
            
            embed = discord.Embed(title=f"**{title}**", description=data['message'].replace('\\n', '\n'), color=embed_color, timestamp=discord.utils.utcnow())
            embed.set_footer(text=f"由 {moderator_display_name} 发布 | {guild.name}", icon_url=user_info.get('avatar', ''))
            if image_url := data.get('image_url'):
                embed.set_image(url=image_url)
            
            ping_content = None
            if (role_id_str := data.get('role_id')) and role_id_str.isdigit():
                if role := guild.get_role(int(role_id_str)):
                    ping_content = role.mention
            
            await channel.send(content=ping_content, embed=embed)
            return jsonify(status="success", message=f"公告已成功发送到 #{channel.name}。")

        
        # --- (新增) 公共日志设置表单 ---
        elif form_id == 'general-log-settings-form':
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            
            log_channel_id_str = data.get('log_channel_id')
            
            # 确保存储字典存在
            if guild_id not in general_settings:
                general_settings[guild_id] = {}
            
            if log_channel_id_str and log_channel_id_str.isdigit():
                general_settings[guild_id]['log_channel_id'] = int(log_channel_id_str)
            else:
                # 如果用户选了“不发送”，或者是空的，则设为 None
                general_settings[guild_id]['log_channel_id'] = None
            
            save_server_settings() # 保存到 json 文件
            return jsonify(status="success", message="公共日志频道设置已更新。")
        
        # --- 成员身份组表单 ---
        elif form_id == 'member-roles-form':
            is_authed, error = check_auth(guild_id, 'tab_roles')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            member = await guild.fetch_member(int(data['member_id']))
            bot_member = guild.me
            give_ids = [r for r in data.get('roles_to_give', []) if isinstance(r, str) and r.isdigit()]
            take_ids = [r for r in data.get('roles_to_take', []) if isinstance(r, str) and r.isdigit()]
            roles_to_give = [guild.get_role(int(r)) for r in give_ids if guild.get_role(int(r))]
            roles_to_take = [guild.get_role(int(r)) for r in take_ids if guild.get_role(int(r))]
            for role in roles_to_give + roles_to_take:
                if role and role >= bot_member.top_role and guild.owner_id != bot_member.id:
                    return jsonify(status="error", message=f"无法操作身份组 '{role.name}'，层级过高。"), 403
            if roles_to_give:
                await member.add_roles(*roles_to_give, reason=f"由 {moderator_display_name} 从Web面板操作")
            if roles_to_take:
                await member.remove_roles(*roles_to_take, reason=f"由 {moderator_display_name} 从Web面板操作")
            return jsonify(status="success", message=f"已更新 {member.name} 的身份组。")

        # --- 禁言表单 ---
        elif form_id == 'mute-form':
            is_authed, error = check_auth(guild_id, 'page_moderation')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            member = await guild.fetch_member(int(data['target_id']))
            duration_minutes = int(data.get('duration_minutes', 0))
            duration = datetime.timedelta(minutes=duration_minutes) if duration_minutes > 0 else datetime.timedelta(days=28)
            await member.timeout(duration, reason=f"由 {moderator_display_name} 从Web面板操作")
            database.db_log_moderation_action(guild.id, member.id, moderator_id_for_db, 'mute', data.get('reason'), int(time.time()), duration.total_seconds(), int((discord.utils.utcnow() + duration).timestamp()))
            return jsonify(status="success", message=f"已禁言用户 {member.display_name}。")

        # --- 经济系统余额表单 ---
        elif form_id == 'balance-form':
            is_authed, error = check_auth(guild_id, 'tab_economy')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            user_id = int(data['user_id'])
            amount = int(data['amount'])
            sub_action = data.get('sub_action')
            op_amount = -amount if sub_action == 'take' else amount
            database.db_update_user_balance(guild.id, user_id, op_amount, is_delta=(sub_action != 'set'), default_balance=ECONOMY_DEFAULT_BALANCE)
            return jsonify(status="success", message="用户余额已更新。")

        # --- 票据系统设置表单 ---
        elif form_id.startswith('ticket-settings-form'):
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            if not all(k in data and data[k] for k in ['button_channel_id', 'ticket_category_id']):
                return jsonify(status="error", message="按钮频道和票据分类是必填项。"), 400
            
            set_setting(ticket_settings, guild_id, "setup_channel_id", int(data['button_channel_id']))
            set_setting(ticket_settings, guild_id, "category_id", int(data['ticket_category_id']))
            set_setting(ticket_settings, guild_id, "staff_role_ids", [int(r) for r in data.get('staff_role_ids', []) if r.isdigit()])
            set_setting(ticket_settings, guild_id, "embed_title", data.get('ticket_embed_title'))
            set_setting(ticket_settings, guild_id, "embed_description", data.get('ticket_embed_description'))
            set_setting(ticket_settings, guild_id, "welcome_embed_title", data.get('welcome_embed_title'))
            set_setting(ticket_settings, guild_id, "welcome_embed_description", data.get('welcome_embed_description'))
            
            save_server_settings()
            load_server_settings() # 【核心修复】保存后立刻重新加载，确保全局变量同步

            if form_id == 'ticket-settings-form-deploy':
                # 这部分可以调用一个辅助函数来执行与 /管理 票据设定 指令相同的部署逻辑
                pass 
            return jsonify(status="success", message="票据系统设置已成功保存。")
        
        # --- 临时语音频道设置表单 ---
        elif form_id == 'temp-vc-settings-form':
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            master_id_str = data.get('master_channel_id')
            if not master_id_str or not master_id_str.isdigit():
                return jsonify(status="error", message="必须选择一个有效的母频道。"), 400
            category_id_str = data.get('category_id')
            set_setting(temp_vc_settings, guild_id, "master_channel_id", int(master_id_str))
            set_setting(temp_vc_settings, guild_id, "category_id", int(category_id_str) if category_id_str and category_id_str.isdigit() else None)
            save_server_settings()
            return jsonify(status="success", message="临时语音频道设置已保存。")

        # --- 欢迎消息设置表单 ---
        elif form_id == 'welcome-settings-form':
            is_authed, error = check_auth(guild_id, 'page_channel_control')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            welcome_message_settings[str(guild_id)] = {
                'channel_id': int(data['welcome_channel_id']) if data.get('welcome_channel_id', '').isdigit() else None,
                'rules_channel_id': int(data['rules_channel_id']) if data.get('rules_channel_id', '').isdigit() else None,
                'roles_info_channel_id': int(data['roles_info_channel_id']) if data.get('roles_info_channel_id', '').isdigit() else None,
                'verification_channel_id': int(data['verification_channel_id']) if data.get('verification_channel_id', '').isdigit() else None,
                'title': data.get('title'), 
                'description': data.get('description')
            }
            save_server_settings()
            return jsonify(status="success", message="欢迎系统设置已成功保存。")
            
        # --- 商店物品编辑/添加表单 ---
        elif form_id == 'edit-item-form':
            is_authed, error = check_auth(guild_id, 'tab_economy')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            action_type = data.get('action')
            if action_type == 'add':
                success, msg = database.db_add_shop_item(guild_id, get_item_slug(data['name']), data['name'], int(data['price']), data.get('description', ''), int(data['role_id']) if data.get('role_id') else None, int(data['stock']), data.get('purchase_message'))
            elif action_type == 'edit':
                updates = { "price": int(data['price']), "description": data.get('description', ''), "role_id": int(data['role_id']) if data.get('role_id') else None, "stock": int(data['stock']), "purchase_message": data.get('purchase_message') }
                success = database.db_edit_shop_item(guild_id, data['item_slug'], updates)
                msg = "物品更新成功。" if success else "物品更新失败。"
            else: success, msg = False, "未知的商店操作"
            return jsonify(status="success" if success else "error", message=msg)

        # --- AI知识库添加表单 ---
        elif form_id == 'kb-add-form':
            is_authed, error = check_auth(guild_id, 'tab_ai_faq')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            content = data.get('content', '').strip()
            if not content: return jsonify(status="error", message="内容不能为空。")
            success, msg = database.db_add_knowledge_base_entry(guild_id, content, MAX_KB_ENTRIES_PER_GUILD)
            return jsonify(status="success" if success else "error", message=msg)

        # --- FAQ添加表单 ---
        elif form_id == 'faq-add-form':
            is_authed, error = check_auth(guild_id, 'tab_ai_faq')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            keyword = data.get('keyword', '').lower().strip()
            answer = data.get('answer', '').strip()
            if not keyword or not answer: return jsonify(status="error", message="关键词和答案都不能为空。")
            server_faqs.setdefault(guild.id, {})[keyword] = answer
            save_server_settings()
            return jsonify(status="success", message="FAQ条目已添加。")

        # --- 机器人白名单表单 ---
        elif form_id == 'bot-whitelist-form':
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            is_discord_owner = (not user_info.get('is_sub_account') and not user_info.get('is_superuser') and str(user_info.get('id')) == str(guild.owner_id))
            if not user_info.get('is_superuser') and not is_discord_owner: return jsonify(status="error", message="只有服务器所有者可以修改。"), 403
            bot_id_str = data.get('bot_id')
            if not bot_id_str or not bot_id_str.isdigit(): return jsonify(status="error", message="无效的机器人ID。"), 400
            bot.approved_bot_whitelist.setdefault(guild_id, set()).add(int(bot_id_str))
            save_bot_whitelist_to_file()
            return jsonify(status="success", message="机器人白名单已更新。")

        # --- AI对话频道表单 ---
        elif form_id == 'ai-dep-form':
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            channel_id = data.get('channel_id')
            if not channel_id or not channel_id.isdigit(): return jsonify(status="error", message="无效的频道ID。"), 400
            ai_dep_channels_config[int(channel_id)] = {"model": DEFAULT_AI_DIALOGUE_MODEL, "system_prompt": None, "history_key": f"ai_dep_channel_{channel_id}"}
            save_server_settings()
            return jsonify(status="success", message="AI频道设置已更新。")
        
        # --- AI审查豁免 - 用户表单 ---
        elif form_id == 'exempt-user-form':
            is_authed, error = check_auth(guild_id, 'page_audit_core')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            user_id_str = data.get('user_id')
            if not user_id_str or not user_id_str.isdigit():
                return jsonify(status="error", message="请选择一个有效的用户。"), 400
            user_id = int(user_id_str)
            user = guild.get_member(user_id)
            if not user:
                 return jsonify(status="error", message="在服务器中未找到该用户。"), 404
            exempt_users_from_ai_check.add(user_id)
            print(f"[AI豁免] 管理员 {moderator_display_name} 从Web面板添加了用户 {user.display_name}({user_id}) 到豁免列表。")
            return jsonify(status="success", message=f"已将用户 {user.display_name} 添加到AI审查豁免列表。")

        # --- AI审查豁免 - 频道表单 ---
        elif form_id == 'exempt-channel-form':
            is_authed, error = check_auth(guild_id, 'page_audit_core')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            channel_id_str = data.get('channel_id')
            if not channel_id_str or not channel_id_str.isdigit():
                return jsonify(status="error", message="请选择一个有效的频道。"), 400
            channel_id = int(channel_id_str)
            channel = guild.get_channel(channel_id)
            if not channel:
                return jsonify(status="error", message="在服务器中未找到该频道。"), 404
            exempt_channels_from_ai_check.add(channel_id)
            print(f"[AI豁免] 管理员 {moderator_display_name} 从Web面板添加了频道 #{channel.name}({channel_id}) 到豁免列表。")
            return jsonify(status="success", message=f"已将频道 #{channel.name} 添加到AI审查豁免列表。")

        # --- AI对话频道表单 ---
        elif form_id == 'ai-dep-form':
            is_authed, error = check_auth(guild_id, 'page_settings')
            if not is_authed: return jsonify(status="error", message=error[0]), error[1]
            channel_id = data.get('channel_id')
            if not channel_id or not channel_id.isdigit(): return jsonify(status="error", message="无效的频道ID。"), 400
            ai_dep_channels_config[int(channel_id)] = {"model": DEFAULT_AI_DIALOGUE_MODEL, "system_prompt": None, "history_key": f"ai_dep_channel_{channel_id}"}
            save_server_settings()
            return jsonify(status="success", message="AI频道设置已更新。")
        
        # --- 未知表单处理 ---
        else:
            return jsonify(status="error", message=f"未知的表单提交: {form_id}"), 400

    except discord.Forbidden as e:
        return jsonify(status="error", message=f"操作被禁止: {e.text}"), 403
    except discord.HTTPException as e:
        return jsonify(status="error", message=f"Discord API 错误: {e.text} (代码: {e.code})"), 500
    except Exception as e:
        logging.error(f"处理表单 '{form_id}' 时发生错误", exc_info=True)
        return jsonify(status="error", message=f"发生内部服务器错误: {e}"), 500

# --- 启动流程 ---
def run_web_server():
    if not web_app or not socketio:
        print("Web服务器组件未初始化，跳过启动。")
        return
    if not web_app.secret_key:
        logging.critical("Web panel not started because FLASK_SECRET_KEY is missing.")
        return
    
    flask_port = int(os.environ.get("PORT", 5000))
    print(f"Flask+SocketIO 服务器正在启动，由 eventlet 提供服务，地址: http://0.0.0.0:{flask_port}")
    
    try:
        # 这是 eventlet 推荐的生产环境启动方式
        # 它会用 eventlet 的方式来运行您的 Flask 应用 (web_app)
        # 您的 socketio 对象会自动附加到 web_app 上并正常工作
        eventlet.wsgi.server(eventlet.listen(('', flask_port)), web_app)
    except Exception as e:
        logging.critical(f"启动 eventlet WSGI 服务器失败: {e}", exc_info=True)


# =======================
# == 全局广播功能
# =======================
@socketio.on('start_global_broadcast')
def handle_start_global_broadcast(data):
    with web_app.app_context():
        user_info = session.get('user', {})
        if not user_info.get('is_superuser'):
            socketio.emit('broadcast_log', {'message': '错误：权限不足！', 'type': 'error'}, room=request.sid)
            socketio.emit('broadcast_finished', {'status': 'error'}, room=request.sid)
            return

        # 使用 run_coroutine_threadsafe 安全地启动异步任务
        asyncio.run_coroutine_threadsafe(
            perform_global_broadcast(data, request.sid),
            bot.loop
        )

async def perform_global_broadcast(data, sid):
    """
    执行全局广播的异步后台任务。
    """
    def log_progress(message, type='info'):
        # 这个内部函数帮助我们将日志发送回前端
        socketio.emit('broadcast_log', {'message': message, 'type': type}, room=sid)
        socketio.sleep(0)

    title = data.get('title')
    message_template = data.get('message')
    invite_url = data.get('invite_url')
    # 【新增】获取目标服务器信息
    broadcast_to_all = data.get('broadcast_to_all', False)
    target_guild_ids = {int(gid) for gid in data.get('target_guilds', []) if gid.isdigit()}

    if not title or not message_template:
        log_progress('错误：标题和消息内容不能为空。', 'error')
        socketio.emit('broadcast_finished', {'status': 'error'}, room=sid)
        return

    log_progress('全局广播任务已启动...', 'info')
    
    # 【修改】根据前端传来的数据筛选目标服务器
    if broadcast_to_all:
        target_guilds = bot.guilds
        log_progress('目标: 所有服务器。', 'warn')
    else:
        target_guilds = [g for g in bot.guilds if g.id in target_guild_ids]
        log_progress(f'目标: {len(target_guilds)} 个特定服务器。', 'info')

    if not target_guilds:
        log_progress('错误：找不到任何目标服务器进行广播。', 'error')
        socketio.emit('broadcast_finished', {'status': 'error'}, room=sid)
        return
    
    sent_count = 0
    fail_count = 0
    
    all_members_to_dm = []
    # 【修改】从筛选后的服务器列表中收集成员
    for guild in target_guilds:
        if not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except Exception as e:
                log_progress(f"警告：无法获取服务器 '{guild.name}' 的完整成员列表: {e}", 'warn')
        all_members_to_dm.extend(list(guild.members))

    # 使用集合去重，防止同一用户在多个目标服务器中被重复广播
    unique_members = {member.id: member for member in all_members_to_dm}.values()

    total_users = len(unique_members)
    log_progress(f"将在 {len(target_guilds)} 个服务器中，向 {total_users} 名独立用户发送广播。", 'info')

    for i, member in enumerate(unique_members):
        if member.bot:
            continue

        message_content = message_template.replace('{user_name}', member.display_name).replace('{server_name}', member.guild.name)
        
        embed = discord.Embed(
            title=title,
            description=message_content,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if invite_url:
            embed.add_field(name="专属邀请", value=f"点击这里加入我们的社区：\n{invite_url}", inline=False)
        
        if bot.user.avatar:
            embed.set_footer(text=f"来自 {bot.user.name} 开发团队", icon_url=bot.user.avatar.url)

        try:
            await member.send(embed=embed)
            sent_count += 1
            log_progress(f"({i+1}/{total_users}) 成功发送到: {member.name} ({member.guild.name})", 'info')
        except discord.Forbidden:
            fail_count += 1
            log_progress(f"({i+1}/{total_users}) 发送失败 (Forbidden): {member.name} ({member.guild.name})", 'warn')
        except Exception as e:
            fail_count += 1
            log_progress(f"({i+1}/{total_users}) 发送失败 (Error: {type(e).__name__}): {member.name}", 'error')

        # 速率限制
        await asyncio.sleep(1.5)

    log_progress(f"广播任务完成！成功: {sent_count}, 失败: {fail_count}。", 'success')
    socketio.emit('broadcast_finished', {'status': 'success'}, room=sid)

if __name__ == "__main__":
    from gjbot.runtime import start_legacy_runtime

    start_legacy_runtime(globals())
