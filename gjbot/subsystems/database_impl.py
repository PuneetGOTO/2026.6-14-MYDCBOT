# database.py
import sqlite3
import os
import logging
from typing import Dict, Any, Optional, List, Tuple 
import time
import json # For extra_data
import datetime # For audit log timestamp conversion
import secrets # For generating secure access keys
import hashlib
import hmac

# 数据库文件名
DATABASE_FILE = "gjteam_bot.db"

# --- 表名常量 ---
TABLE_USER_BALANCES = "user_balances"
TABLE_SHOP_ITEMS = "shop_items"
TABLE_GUILD_ECONOMY_SETTINGS = "guild_economy_settings"
TABLE_GUILD_KNOWLEDGE_BASE = "guild_knowledge_base"
TABLE_MODERATION_ACTIONS = "moderation_actions"
TABLE_RECHARGE_REQUESTS = "recharge_requests"
TABLE_AUDIT_LOG = "audit_log"
TABLE_WEB_SUB_ACCOUNTS = "web_sub_accounts"
TABLE_PLAYLISTS = "user_playlists"
TABLE_PLAYLIST_TRACKS = "playlist_tracks"

# 【【【新增代码】】】
TABLE_TICKET_DEPARTMENTS = "ticket_departments"
TABLE_TICKETS = "tickets"

ACCESS_KEY_HASH_PREFIX = "pbkdf2_sha256"
ACCESS_KEY_HASH_ITERATIONS = 260_000


def _coerce_balance(value: Any, default: int = 0) -> int:
    """Return a Python big integer from any stored balance representation."""

    if value is None:
        return int(default)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        logging.warning("[DB Economy] Invalid stored balance %r; using default %s.", value, default)
        return int(default)


def _balance_to_storage(value: int) -> str:
    """Store balances as decimal text so they can exceed SQLite INTEGER limits."""

    return str(max(0, int(value)))


def _safe_chart_number(value: int) -> int:
    """Return a JS-safe chart value while preserving the exact display balance separately."""

    return min(max(0, int(value)), 9_007_199_254_740_991)


def _hash_access_key(access_key: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        access_key.encode("utf-8"),
        salt.encode("ascii"),
        ACCESS_KEY_HASH_ITERATIONS,
    )
    return f"{ACCESS_KEY_HASH_PREFIX}${ACCESS_KEY_HASH_ITERATIONS}${salt}${digest.hex()}"


def _verify_access_key(access_key: str, stored_value: str) -> bool:
    if stored_value.startswith(f"{ACCESS_KEY_HASH_PREFIX}$"):
        try:
            _, iterations_raw, salt, expected_digest = stored_value.split("$", 3)
            iterations = int(iterations_raw)
        except (TypeError, ValueError):
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            access_key.encode("utf-8"),
            salt.encode("ascii"),
            iterations,
        ).hex()
        return hmac.compare_digest(actual_digest, expected_digest)
    return hmac.compare_digest(access_key, stored_value)

# 【【【新增代码结束】】】

def get_db_connection() -> sqlite3.Connection:
    """获取并返回一个数据库连接对象。"""
    db_dir = os.path.dirname(os.path.abspath(DATABASE_FILE))
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            print(f"[Database] Created directory for database: {db_dir}")
        except OSError as e:
            print(f"[Database Error] Could not create directory {db_dir}: {e}")

    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """初始化数据库，创建所有必要的表，并为旧表添加新列（如果需要）。"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- 一个辅助函数，用于安全地添加新列 ---
    def add_column_if_not_exists(table_name, column_name, column_def):
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row['name'] for row in cursor.fetchall()]
            if column_name not in columns:
                logging.warning(f"[DB Migration] 表 '{table_name}' 缺少列 '{column_name}'。正在添加...")
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
                logging.warning(f"[DB Migration] 列 '{column_name}' 已成功添加到表 '{table_name}'。")
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"[DB Migration Error] 尝试向表 '{table_name}' 添加列 '{column_name}' 时失败: {e}")


    
    # --- 用户歌单表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_PLAYLISTS} (
        playlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at INTEGER,
        UNIQUE(user_id, name)
    )
    """)

    # --- 歌单歌曲表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_PLAYLIST_TRACKS} (
        track_id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id INTEGER NOT NULL,
        uri TEXT NOT NULL,
        title TEXT,
        author TEXT,
        FOREIGN KEY (playlist_id) REFERENCES {TABLE_PLAYLISTS}(playlist_id) ON DELETE CASCADE
    )
    """)
    
    # --- 用户余额表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_USER_BALANCES} (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        balance TEXT NOT NULL DEFAULT '0',
        PRIMARY KEY (guild_id, user_id)
    )
    """)

    cursor.execute(f"PRAGMA table_info({TABLE_USER_BALANCES})")
    balance_columns = {row["name"]: row for row in cursor.fetchall()}
    balance_column = balance_columns.get("balance")
    if balance_column and (balance_column["type"] or "").upper() != "TEXT":
        logging.warning("[DB Migration] Converting user balance storage to TEXT for big integer support.")
        temp_table = f"{TABLE_USER_BALANCES}_bigint_migration"
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table}")
        cursor.execute(f"""
        CREATE TABLE {temp_table} (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            balance TEXT NOT NULL DEFAULT '0',
            PRIMARY KEY (guild_id, user_id)
        )
        """)
        cursor.execute(
            f"""
            INSERT INTO {temp_table} (guild_id, user_id, balance)
            SELECT guild_id, user_id, CAST(balance AS TEXT)
            FROM {TABLE_USER_BALANCES}
            """
        )
        cursor.execute(f"DROP TABLE {TABLE_USER_BALANCES}")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {TABLE_USER_BALANCES}")

    # --- 商店物品表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_SHOP_ITEMS} (
        guild_id INTEGER NOT NULL,
        item_slug TEXT NOT NULL,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        description TEXT,
        role_id INTEGER,
        stock INTEGER DEFAULT -1, -- -1 for infinite
        purchase_message TEXT,
        PRIMARY KEY (guild_id, item_slug)
    )
    """)

    # --- 服务器经济设置表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_GUILD_ECONOMY_SETTINGS} (
        guild_id INTEGER PRIMARY KEY,
        chat_earn_amount INTEGER,
        chat_earn_cooldown INTEGER
    )
    """)

    # --- 服务器 AI 知识库表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_GUILD_KNOWLEDGE_BASE} (
        guild_id INTEGER NOT NULL,
        entry_order INTEGER NOT NULL, 
        entry_text TEXT NOT NULL,
        PRIMARY KEY (guild_id, entry_order) 
    )
    """)
    
    # --- 审核操作记录表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_MODERATION_ACTIONS} (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        target_user_id INTEGER NOT NULL,
        moderator_user_id INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        reason TEXT,
        created_at INTEGER NOT NULL,
        duration_seconds INTEGER,
        expires_at INTEGER,
        extra_data TEXT,
        active INTEGER NOT NULL DEFAULT 1
    )
    """)

    # --- 充值请求表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_RECHARGE_REQUESTS} ( 
        request_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        out_trade_no TEXT UNIQUE NOT NULL,      
        requested_cny_amount REAL NOT NULL,     
        paid_cny_amount REAL,                   
        alipay_trade_no TEXT UNIQUE,            
        status TEXT NOT NULL DEFAULT 'PENDING_PAYMENT', 
        payment_proof_url TEXT, 
        user_provided_payment_info TEXT, 
        user_note TEXT,
        admin_id INTEGER, 
        admin_note TEXT,
        requested_at INTEGER NOT NULL, 
        processed_at INTEGER,
        passback_params_received TEXT           
    )
    """)
    
    # --- 待审核事件表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_AUDIT_LOG} (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        message_content TEXT NOT NULL,
        violation_type TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        jump_url TEXT,
        auto_deleted INTEGER DEFAULT 0,
        handled_by_id INTEGER,
        handled_at INTEGER
    )
    """)

    # --- Web副账号权限表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_WEB_SUB_ACCOUNTS} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_name TEXT UNIQUE NOT NULL,
        access_key TEXT UNIQUE NOT NULL,
        permissions_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_used_at INTEGER
    )
    """)

    # --- 票据部门表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_TICKET_DEPARTMENTS} (
        department_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        staff_role_ids_json TEXT NOT NULL,
        welcome_message_json TEXT,
        button_label TEXT,
        button_emoji TEXT,
        UNIQUE(guild_id, name)
    )
    """)
    
    # --- 票据记录表 ---
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_TICKETS} (
        ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER UNIQUE,
        creator_id INTEGER NOT NULL,
        department_id INTEGER,
        claimed_by_id INTEGER,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at INTEGER NOT NULL,
        closed_at INTEGER,
        close_reason TEXT,
        transcript_filename TEXT,
        FOREIGN KEY (department_id) REFERENCES {TABLE_TICKET_DEPARTMENTS}(department_id)
    )
    """)
    
    

    # 【【【核心修复：在这里检查并添加 is_ai_managed 列】】】
    add_column_if_not_exists(TABLE_TICKETS, 'is_ai_managed', 'INTEGER DEFAULT 0')
    # 【【【修复结束】】】

    # --- 创建所有索引 ---
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_moderation_actions_user_guild_type ON {TABLE_MODERATION_ACTIONS} (guild_id, target_user_id, action_type, active)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_recharge_requests_out_trade_no ON {TABLE_RECHARGE_REQUESTS} (out_trade_no)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_recharge_requests_alipay_trade_no ON {TABLE_RECHARGE_REQUESTS} (alipay_trade_no)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_audit_log_guild_status ON {TABLE_AUDIT_LOG} (guild_id, status)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_sub_accounts_key ON {TABLE_WEB_SUB_ACCOUNTS} (access_key)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON {TABLE_TICKETS} (guild_id, status)")

    conn.commit()
    conn.close()
    print("[Database] 数据库初始化完毕 (所有核心表和列已确认存在)。")

# =========================================
# == 经济系统 - 余额操作
# =========================================
def db_get_user_balance(guild_id: int, user_id: int, default_balance: int) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    balance_to_return = default_balance 
    try:
        cursor.execute(f"SELECT balance FROM {TABLE_USER_BALANCES} WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        row = cursor.fetchone()
        if row:
            balance_to_return = _coerce_balance(row["balance"], default_balance)
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] Error querying balance for user {user_id} in guild {guild_id}: {e}")
    finally:
        if conn:
            conn.close()
    return balance_to_return

def db_update_user_balance(guild_id: int, user_id: int, amount: int, is_delta: bool = True, default_balance: int = 0) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        current_balance_for_delta_calc = 0
        if is_delta:
            current_balance_for_delta_calc = db_get_user_balance(guild_id, user_id, default_balance) 

        new_balance = (current_balance_for_delta_calc + amount) if is_delta else amount
        
        if new_balance < 0:
            return False

        cursor.execute(f"""
        INSERT INTO {TABLE_USER_BALANCES} (guild_id, user_id, balance) VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = excluded.balance
        """, (guild_id, user_id, _balance_to_storage(new_balance)))
        
        conn.commit()
        return True
            
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] SQLite Error updating balance for user {user_id} (guild: {guild_id}): {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def db_apply_user_balance_delta(guild_id: int, user_id: int, delta: int, default_balance: int = 0) -> bool:
    """Atomically apply a balance delta without allowing the balance below zero."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            f"""
            INSERT INTO {TABLE_USER_BALANCES} (guild_id, user_id, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO NOTHING
            """,
            (guild_id, user_id, _balance_to_storage(default_balance)),
        )
        cursor.execute(
            f"SELECT balance FROM {TABLE_USER_BALANCES} WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        current_balance = _coerce_balance(row["balance"], default_balance) if row else int(default_balance)
        new_balance = current_balance + int(delta)
        if new_balance < 0:
            conn.rollback()
            return False
        cursor.execute(
            f"""
            UPDATE {TABLE_USER_BALANCES}
            SET balance = ?
            WHERE guild_id = ?
              AND user_id = ?
            """,
            (_balance_to_storage(new_balance), guild_id, user_id),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(
            f"[DB Economy Error] Atomic balance delta failed for user {user_id} "
            f"(guild: {guild_id}, delta: {delta}): {e}"
        )
        conn.rollback()
        return False
    finally:
        conn.close()

def db_set_user_balance(guild_id: int, user_id: int, balance: int) -> bool:
    """Atomically set a user's balance, clamping negative values to zero."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if balance < 0:
            balance = 0
        cursor.execute(
            f"""
            INSERT INTO {TABLE_USER_BALANCES} (guild_id, user_id, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = excluded.balance
            """,
            (guild_id, user_id, _balance_to_storage(balance)),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(
            f"[DB Economy Error] Atomic balance set failed for user {user_id} "
            f"(guild: {guild_id}, balance: {balance}): {e}"
        )
        conn.rollback()
        return False
    finally:
        conn.close()

def db_get_leaderboard(guild_id: int, limit: int) -> List[Tuple[int, int]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT user_id, balance FROM {TABLE_USER_BALANCES} WHERE guild_id = ?", (guild_id,))
    leaderboard = [
        (row["user_id"], _coerce_balance(row["balance"], 0))
        for row in cursor.fetchall()
    ]
    conn.close()
    return sorted(leaderboard, key=lambda item: item[1], reverse=True)[:limit]

# =========================================
# == 经济系统 - 服务器设置
# =========================================
def db_get_guild_chat_earn_config(guild_id: int, default_amount: int, default_cooldown: int) -> Dict[str, int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT chat_earn_amount, chat_earn_cooldown FROM {TABLE_GUILD_ECONOMY_SETTINGS} WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row["chat_earn_amount"] is not None and row["chat_earn_cooldown"] is not None:
        return {"amount": row["chat_earn_amount"], "cooldown": row["chat_earn_cooldown"]}
    return {"amount": default_amount, "cooldown": default_cooldown}

def db_set_guild_chat_earn_config(guild_id: int, amount: int, cooldown: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
        INSERT INTO {TABLE_GUILD_ECONOMY_SETTINGS} (guild_id, chat_earn_amount, chat_earn_cooldown) VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET chat_earn_amount = excluded.chat_earn_amount, chat_earn_cooldown = excluded.chat_earn_cooldown
        """, (guild_id, amount, cooldown))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] 设置服务器聊天赚钱配置失败 (guild: {guild_id}): {e}")
    finally:
        conn.close()

# =========================================
# == 经济系统 - 商店操作
# =========================================
def db_get_shop_items(guild_id: int) -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT item_slug, name, price, description, role_id, stock, purchase_message FROM {TABLE_SHOP_ITEMS} WHERE guild_id = ?", (guild_id,))
    items = {row["item_slug"]: dict(row) for row in cursor.fetchall()}
    conn.close()
    return items

def db_get_shop_item(guild_id: int, item_slug: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT item_slug, name, price, description, role_id, stock, purchase_message FROM {TABLE_SHOP_ITEMS} WHERE guild_id = ? AND item_slug = ?", (guild_id, item_slug))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def db_add_shop_item(guild_id: int, item_slug: str, name: str, price: int, description: Optional[str],
                       role_id: Optional[int], stock: int, purchase_message: Optional[str]) -> Tuple[bool, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
        INSERT INTO {TABLE_SHOP_ITEMS} (guild_id, item_slug, name, price, description, role_id, stock, purchase_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, item_slug, name, price, description, role_id, stock, purchase_message))
        conn.commit()
        return True, "物品已成功添加到数据库。"
    except sqlite3.IntegrityError:
        msg = f"可能物品ID '{item_slug}' 已存在。"
        logging.warning(f"[DB Economy Error] db_add_shop_item: IntegrityError (guild: {guild_id}, slug: {item_slug}): {msg}")
        return False, msg
    except sqlite3.Error as e:
        msg = f"数据库错误: {e}"
        logging.error(f"[DB Economy Error] db_add_shop_item: SQLite Error (guild: {guild_id}, slug: {item_slug}): {msg}")
        return False, msg
    finally:
        conn.close()

def db_remove_shop_item(guild_id: int, item_slug: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DELETE FROM {TABLE_SHOP_ITEMS} WHERE guild_id = ? AND item_slug = ?", (guild_id, item_slug))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] 移除商店物品失败 (guild: {guild_id}, slug: {item_slug}): {e}")
        return False
    finally:
        conn.close()

def db_update_shop_item_stock(guild_id: int, item_slug: str, new_stock: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if new_stock < -1: new_stock = 0 
        cursor.execute(f"UPDATE {TABLE_SHOP_ITEMS} SET stock = ? WHERE guild_id = ? AND item_slug = ?", (new_stock, guild_id, item_slug))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] 更新商店物品库存失败 (guild: {guild_id}, slug: {item_slug}): {e}")
        return False
    finally:
        conn.close()

def db_decrement_shop_item_stock(guild_id: int, item_slug: str, quantity: int = 1) -> bool:
    """Atomically decrement finite shop stock; infinite stock (-1) is unchanged."""
    if quantity <= 0:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            f"""
            UPDATE {TABLE_SHOP_ITEMS}
            SET stock = CASE
                WHEN stock = -1 THEN stock
                ELSE stock - ?
            END
            WHERE guild_id = ?
              AND item_slug = ?
              AND (stock = -1 OR stock >= ?)
            """,
            (quantity, guild_id, item_slug, quantity),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(
            f"[DB Economy Error] Atomic stock decrement failed "
            f"(guild: {guild_id}, slug: {item_slug}, quantity: {quantity}): {e}"
        )
        conn.rollback()
        return False
    finally:
        conn.close()

def db_edit_shop_item(guild_id: int, item_slug: str, updates: Dict[str, Any]) -> bool:
    if not updates: return False
    set_clauses = [f"{key} = ?" for key in updates.keys() if key in ["name", "price", "description", "role_id", "stock", "purchase_message"]]
    if not set_clauses: return False
    
    values = [updates[key] for key in updates.keys() if key in ["name", "price", "description", "role_id", "stock", "purchase_message"]]
    values.extend([guild_id, item_slug])
    
    sql = f"UPDATE {TABLE_SHOP_ITEMS} SET {', '.join(set_clauses)} WHERE guild_id = ? AND item_slug = ?"
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(values))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Economy Error] 编辑商店物品失败 (guild: {guild_id}, slug: {item_slug}): {e}")
        return False
    finally:
        conn.close()

# =========================================
# == AI 知识库操作
# =========================================
def db_get_knowledge_base(guild_id: int) -> List[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT entry_text FROM {TABLE_GUILD_KNOWLEDGE_BASE} WHERE guild_id = ? ORDER BY entry_order ASC", (guild_id,))
    entries = [row["entry_text"] for row in cursor.fetchall()]
    conn.close()
    return entries

def db_add_knowledge_base_entry(guild_id: int, entry_text: str, max_entries: int) -> Tuple[bool, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) as count FROM {TABLE_GUILD_KNOWLEDGE_BASE} WHERE guild_id = ?", (guild_id,))
        current_count = cursor.fetchone()["count"]
        if current_count >= max_entries:
            return False, "知识库已满。"

        cursor.execute(f"SELECT MAX(entry_order) as max_order FROM {TABLE_GUILD_KNOWLEDGE_BASE} WHERE guild_id = ?", (guild_id,))
        max_order_row = cursor.fetchone()
        next_order = (max_order_row["max_order"] if max_order_row and max_order_row["max_order"] is not None else 0) + 1
        
        cursor.execute(f"INSERT INTO {TABLE_GUILD_KNOWLEDGE_BASE} (guild_id, entry_order, entry_text) VALUES (?, ?, ?)",
                       (guild_id, next_order, entry_text))
        conn.commit()
        return True, "添加成功。"
    except sqlite3.Error as e:
        logging.error(f"[DB KB Error] 添加知识库条目失败 (guild: {guild_id}): {e}")
        conn.rollback()
        return False, f"数据库错误: {e}"
    finally:
        conn.close()

def db_remove_knowledge_base_entry_by_order(guild_id: int, entry_order_to_remove: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN")
        cursor.execute(f"DELETE FROM {TABLE_GUILD_KNOWLEDGE_BASE} WHERE guild_id = ? AND entry_order = ?",
                       (guild_id, entry_order_to_remove))
        if cursor.rowcount == 0:
            conn.rollback()
            return False
        cursor.execute(f"UPDATE {TABLE_GUILD_KNOWLEDGE_BASE} SET entry_order = entry_order - 1 WHERE guild_id = ? AND entry_order > ?",
                       (guild_id, entry_order_to_remove))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(f"[DB KB Error] 按序号移除知识库条目失败 (guild: {guild_id}, order: {entry_order_to_remove}): {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def db_clear_knowledge_base(guild_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DELETE FROM {TABLE_GUILD_KNOWLEDGE_BASE} WHERE guild_id = ?", (guild_id,))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(f"[DB KB Error] 清空知识库失败 (guild: {guild_id}): {e}")
        return False
    finally:
        conn.close()

# =========================================
# == 审核操作记录
# =========================================
def db_log_moderation_action(guild_id: int, target_user_id: int, moderator_user_id: int, action_type: str, reason: Optional[str], created_at: int, duration_seconds: Optional[int] = None, expires_at: Optional[int] = None, extra_data: Optional[Dict[str, Any]] = None) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    extra_data_json = json.dumps(extra_data) if extra_data else None
    try:
        cursor.execute(f"""
        INSERT INTO {TABLE_MODERATION_ACTIONS} 
        (guild_id, target_user_id, moderator_user_id, action_type, reason, created_at, duration_seconds, expires_at, extra_data, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, target_user_id, moderator_user_id, action_type, reason, created_at, duration_seconds, expires_at, extra_data_json, 1))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logging.error(f"[DB Moderation Error] Logging action failed for user {target_user_id} in guild {guild_id}: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def db_get_latest_active_log_for_user(guild_id: int, target_user_id: int, action_type: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    current_timestamp = int(time.time())
    query = f"SELECT * FROM {TABLE_MODERATION_ACTIONS} WHERE guild_id = ? AND target_user_id = ? AND action_type = ? AND active = 1"
    params = [guild_id, target_user_id, action_type]
    if action_type == "mute":
        query += " AND (expires_at IS NULL OR expires_at > ?)"
        params.append(current_timestamp)
    query += " ORDER BY created_at DESC LIMIT 1"
    try:
        cursor.execute(query, tuple(params))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"[DB Moderation Error] Fetching active log for user {target_user_id} ({action_type}) in guild {guild_id}: {e}")
        return None
    finally:
        conn.close()

def db_deactivate_log(log_id: int, deactivation_reason: Optional[str] = None, deactivator_id: Optional[int] = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE {TABLE_MODERATION_ACTIONS} SET active = 0 WHERE log_id = ?", (log_id,))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"[DB Moderation] Deactivated log ID: {log_id}. Reason (meta): {deactivation_reason}, By (meta): {deactivator_id}")
            return True
        return False
    except sqlite3.Error as e:
        logging.error(f"[DB Moderation Error] Deactivating log ID {log_id} failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def db_get_all_active_mutes(guild_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    current_timestamp = int(time.time())
    active_mutes = []
    try:
        cursor.execute(
            f"SELECT * FROM {TABLE_MODERATION_ACTIONS} WHERE guild_id = ? AND action_type = 'mute' AND active = 1 AND expires_at > ?",
            (guild_id, current_timestamp)
        )
        for row in cursor.fetchall():
            active_mutes.append(dict(row))
    except sqlite3.Error as e:
        logging.error(f"[DB Moderation Error] 获取所有活动禁言记录失败 (guild: {guild_id}): {e}")
    finally:
        conn.close()
    return active_mutes

# =========================================
# == 充值请求操作
# =========================================
def db_create_initial_recharge_request(guild_id: int, user_id: int, requested_cny_amount: float, out_trade_no: str, passback_params_json_str: Optional[str] = None) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    requested_at = int(time.time())
    try:
        cursor.execute(f"""
        INSERT INTO {TABLE_RECHARGE_REQUESTS} 
        (guild_id, user_id, requested_cny_amount, out_trade_no, status, requested_at, passback_params_received)
        VALUES (?, ?, ?, ?, 'PENDING_PAYMENT', ?, ?)
        """, (guild_id, user_id, requested_cny_amount, out_trade_no, requested_at, passback_params_json_str))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        logging.error(f"[DB Recharge Error] IntegrityError creating initial request for out_trade_no '{out_trade_no}': {e}")
        conn.rollback()
        return None
    except sqlite3.Error as e:
        logging.error(f"[DB Recharge Error] Creating initial recharge request failed for out_trade_no '{out_trade_no}': {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def db_get_recharge_request_by_out_trade_no(out_trade_no: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {TABLE_RECHARGE_REQUESTS} WHERE out_trade_no = ?", (out_trade_no,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"[DB Recharge Error] Fetching recharge request by out_trade_no '{out_trade_no}' failed: {e}")
        return None
    finally:
        conn.close()

def db_is_alipay_trade_no_processed(alipay_trade_no: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT 1 FROM {TABLE_RECHARGE_REQUESTS} WHERE alipay_trade_no = ? AND status IN ('PAID', 'COMPLETED')", (alipay_trade_no,))
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logging.error(f"[DB Recharge Error] Checking if alipay_trade_no '{alipay_trade_no}' processed failed: {e}")
        return True
    finally:
        conn.close()

def db_mark_recharge_as_paid(request_id: int, alipay_trade_no: str, paid_cny_amount: float, passback_params_received: Optional[str] = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    processed_at = int(time.time())
    try:
        sql = f"UPDATE {TABLE_RECHARGE_REQUESTS} SET status = 'PAID', alipay_trade_no = ?, paid_cny_amount = ?, processed_at = ?"
        params = [alipay_trade_no, paid_cny_amount, processed_at]
        if passback_params_received:
            sql += ", passback_params_received = ?"
            params.append(passback_params_received)
        sql += " WHERE request_id = ? AND status = 'PENDING_PAYMENT'"
        params.append(request_id)
        
        cursor.execute(sql, tuple(params))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"[DB Recharge] Marked request ID {request_id} as PAID.")
            return True
        else:
            logging.warning(f"[DB Recharge Warn] Could not mark request ID {request_id} as PAID (not found or not PENDING_PAYMENT).")
            return False
    except sqlite3.IntegrityError as e_int:
         logging.error(f"[DB Recharge Error] IntegrityError marking request ID {request_id} as PAID (duplicate alipay_trade_no): {e_int}")
         conn.rollback()
         return False
    except sqlite3.Error as e:
        logging.error(f"[DB Recharge Error] Marking request ID {request_id} as PAID failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def db_mark_recharge_as_completed(request_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE {TABLE_RECHARGE_REQUESTS} SET status = 'COMPLETED' WHERE request_id = ? AND status = 'PAID'", (request_id,))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"[DB Recharge] Marked request ID {request_id} as COMPLETED.")
            return True
        else:
            logging.warning(f"[DB Recharge Warn] Could not mark request ID {request_id} as COMPLETED (not found or not PAID).")
            return False
    except sqlite3.Error as e:
        logging.error(f"[DB Recharge Error] Marking request ID {request_id} as COMPLETED failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def db_complete_recharge_and_credit_balance(
    request_id: int,
    alipay_trade_no: str,
    paid_cny_amount: float,
    guild_id: int,
    user_id: int,
    amount_to_credit: int,
    default_balance: int = 0,
    passback_params_received: Optional[str] = None,
) -> bool:
    """Atomically mark a recharge completed and credit the user balance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    processed_at = int(time.time())
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            f"""
            SELECT request_id, status
            FROM {TABLE_RECHARGE_REQUESTS}
            WHERE alipay_trade_no = ?
              AND request_id != ?
              AND status IN ('PAID', 'COMPLETED')
            """,
            (alipay_trade_no, request_id),
        )
        if cursor.fetchone():
            conn.rollback()
            logging.error(
                f"[DB Recharge Error] Duplicate alipay_trade_no {alipay_trade_no!r} "
                f"while completing request {request_id}."
            )
            return False

        cursor.execute(
            f"""
            INSERT INTO {TABLE_USER_BALANCES} (guild_id, user_id, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO NOTHING
            """,
            (guild_id, user_id, _balance_to_storage(default_balance)),
        )
        cursor.execute(
            f"SELECT balance FROM {TABLE_USER_BALANCES} WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        current_balance = _coerce_balance(row["balance"], default_balance) if row else int(default_balance)
        new_balance = current_balance + int(amount_to_credit)
        if new_balance < 0:
            conn.rollback()
            logging.error(
                f"[DB Recharge Error] Failed to credit balance for request {request_id}."
            )
            return False
        cursor.execute(
            f"""
            UPDATE {TABLE_USER_BALANCES}
            SET balance = ?
            WHERE guild_id = ?
              AND user_id = ?
            """,
            (_balance_to_storage(new_balance), guild_id, user_id),
        )

        sql = (
            f"UPDATE {TABLE_RECHARGE_REQUESTS} "
            "SET status = 'COMPLETED', alipay_trade_no = ?, paid_cny_amount = ?, processed_at = ?"
        )
        params: List[Any] = [alipay_trade_no, paid_cny_amount, processed_at]
        if passback_params_received is not None:
            sql += ", passback_params_received = ?"
            params.append(passback_params_received)
        sql += " WHERE request_id = ? AND status = 'PENDING_PAYMENT'"
        params.append(request_id)

        cursor.execute(sql, tuple(params))
        if cursor.rowcount == 0:
            conn.rollback()
            logging.warning(
                f"[DB Recharge Warn] Could not complete request {request_id}; "
                "it may no longer be pending."
            )
            return False

        conn.commit()
        logging.info(f"[DB Recharge] Completed and credited request ID {request_id}.")
        return True
    except sqlite3.IntegrityError as e:
        logging.error(
            f"[DB Recharge Error] IntegrityError completing request {request_id}: {e}"
        )
        conn.rollback()
        return False
    except sqlite3.Error as e:
        logging.error(
            f"[DB Recharge Error] Completing request {request_id} atomically failed: {e}"
        )
        conn.rollback()
        return False
    finally:
        conn.close()

def db_update_recharge_request_status(
    request_id: int,
    status: str,
    admin_note: Optional[str] = None,
    admin_id: Optional[int] = None,
) -> bool:
    """Update recharge status for exceptional payment paths."""
    conn = get_db_connection()
    cursor = conn.cursor()
    processed_at = int(time.time())
    try:
        cursor.execute(
            f"""
            UPDATE {TABLE_RECHARGE_REQUESTS}
            SET status = ?,
                admin_note = COALESCE(?, admin_note),
                admin_id = COALESCE(?, admin_id),
                processed_at = COALESCE(processed_at, ?)
            WHERE request_id = ?
            """,
            (status, admin_note, admin_id, processed_at, request_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(
            f"[DB Recharge Error] Updating request ID {request_id} "
            f"to status {status!r} failed: {e}"
        )
        conn.rollback()
        return False
    finally:
        conn.close()

# =========================================
# == 审核事件日志 (Audit Log)
# =========================================

def db_log_audit_event(event_data: Dict[str, Any]) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        ts_iso = event_data['timestamp']
        ts_dt = datetime.datetime.fromisoformat(ts_iso.replace('Z', '+00:00'))
        ts_unix = int(ts_dt.timestamp())
        
        cursor.execute(f"""
        INSERT INTO {TABLE_AUDIT_LOG}
        (guild_id, user_id, channel_id, message_id, message_content, violation_type, timestamp, jump_url, auto_deleted, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """, (
            int(event_data['guild']['id']), 
            int(event_data['user']['id']), 
            int(event_data['message']['channel_id']),
            int(event_data['message']['id']), 
            event_data['message']['content'], 
            event_data['violation_type'],
            ts_unix, 
            event_data['message']['jump_url'], 
            1 if event_data['auto_deleted'] else 0
        ))
        conn.commit()
        event_id = cursor.lastrowid
        return event_id
    except (sqlite3.Error, KeyError, ValueError) as e:
        logging.error(f"[DB Audit Error] Logging audit event failed: {e}", exc_info=True)
        conn.rollback()
        return None
    finally:
        conn.close()

def db_get_pending_audit_events(guild_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    events = []
    try:
        cursor.execute(
            f"SELECT * FROM {TABLE_AUDIT_LOG} WHERE guild_id = ? AND status = 'PENDING' ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit)
        )
        for row in cursor.fetchall():
            events.append(dict(row))
    except sqlite3.Error as e:
        logging.error(f"[DB Audit Error] Fetching pending audit events for guild {guild_id} failed: {e}")
    finally:
        conn.close()
    return events

def db_update_audit_status(event_id: int, new_status: str, handler_id: Optional[int] = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE {TABLE_AUDIT_LOG} SET status = ?, handled_by_id = ?, handled_at = ? WHERE event_id = ?",
            (new_status, handler_id, int(time.time()), event_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Audit Error] Updating audit event {event_id} status failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# =========================================
# == 数据统计 (用于图表)
# =========================================
def db_get_economy_stats(guild_id: int) -> Dict[str, Any]:
    """获取指定服务器的经济统计数据，用于图表展示。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {
        "top_users": [],
        "total_currency": 0,
        "user_count": 0
    }
    try:
        cursor.execute(
            f"SELECT user_id, balance FROM {TABLE_USER_BALANCES} WHERE guild_id = ?",
            (guild_id,)
        )
        balances = [
            {"user_id": row["user_id"], "balance": _coerce_balance(row["balance"], 0)}
            for row in cursor.fetchall()
        ]
        balances.sort(key=lambda item: item["balance"], reverse=True)
        stats["top_users"] = [
            {
                "user_id": item["user_id"],
                "balance": str(item["balance"]),
                "balance_display": str(item["balance"]),
                "balance_chart": _safe_chart_number(item["balance"]),
            }
            for item in balances[:10]
        ]
        total_currency = sum(item["balance"] for item in balances)
        stats["total_currency"] = str(total_currency)
        stats["total_currency_display"] = str(total_currency)
        stats["total_currency_chart"] = _safe_chart_number(total_currency)
        stats["user_count"] = len(balances)
            
    except sqlite3.Error as e:
        logging.error(f"[DB Stats Error] Failed to get economy stats for guild {guild_id}: {e}")
    finally:
        conn.close()
        
    return stats

# =========================================
# == Web 副账号与权限系统
# =========================================
def db_get_all_sub_accounts() -> List[Dict[str, Any]]:
    """获取所有副账号的信息（不包括密钥）。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT id, account_name, permissions_json, created_at, last_used_at FROM {TABLE_WEB_SUB_ACCOUNTS}")
        accounts = [dict(row) for row in cursor.fetchall()]
        for acc in accounts:
            acc['permissions'] = json.loads(acc['permissions_json'])
        return accounts
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] 获取所有副账号失败: {e}")
        return []
    finally:
        conn.close()

def db_create_sub_account(account_name: str, permissions: Dict) -> Optional[str]:
    """创建新的副账号，并返回生成的 access_key。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    access_key = secrets.token_urlsafe(32)
    access_key_hash = _hash_access_key(access_key)
    permissions_json = json.dumps(permissions)
    created_at = int(time.time())
    try:
        cursor.execute(
            f"INSERT INTO {TABLE_WEB_SUB_ACCOUNTS} (account_name, access_key, permissions_json, created_at) VALUES (?, ?, ?, ?)",
            (account_name, access_key_hash, permissions_json, created_at)
        )
        conn.commit()
        return access_key
    except sqlite3.IntegrityError:
        logging.warning(f"[DB SubAccounts Error] 尝试创建同名副账号 '{account_name}'")
        return None
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] 创建副账号 '{account_name}' 失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def db_update_sub_account_permissions(account_id: int, permissions: Dict) -> bool:
    """更新指定副账号的权限。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    permissions_json = json.dumps(permissions)
    try:
        cursor.execute(
            f"UPDATE {TABLE_WEB_SUB_ACCOUNTS} SET permissions_json = ? WHERE id = ?",
            (permissions_json, account_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] 更新副账号 {account_id} 权限失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def db_delete_sub_account(account_id: int) -> bool:
    """删除指定的副账号。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DELETE FROM {TABLE_WEB_SUB_ACCOUNTS} WHERE id = ?", (account_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] 删除副账号 {account_id} 失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def _db_validate_access_key_legacy_unused(access_key: str) -> Optional[Dict[str, Any]]:
    """验证 access_key 并返回账号信息和权限。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT id, account_name, permissions_json FROM {TABLE_WEB_SUB_ACCOUNTS} WHERE access_key = ?", (access_key,))
        row = cursor.fetchone()
        if not row:
            return None
        
        account_data = dict(row)
        account_data['permissions'] = json.loads(account_data['permissions_json'])
        
        # 更新 last_used_at
        cursor.execute(f"UPDATE {TABLE_WEB_SUB_ACCOUNTS} SET last_used_at = ? WHERE id = ?", (int(time.time()), account_data['id']))
        conn.commit()

        return account_data
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] 验证 access_key 时失败: {e}")
        return None
    finally:
        conn.close()

def db_validate_access_key(access_key: str) -> Optional[Dict[str, Any]]:
    """Validate a sub-account access key and upgrade legacy plaintext keys."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = None
        cursor.execute(
            f"SELECT id, account_name, access_key, permissions_json FROM {TABLE_WEB_SUB_ACCOUNTS}"
        )
        for candidate in cursor.fetchall():
            if _verify_access_key(access_key, candidate["access_key"]):
                row = candidate
                break
        if not row:
            return None

        account_data = dict(row)
        account_data["permissions"] = json.loads(account_data["permissions_json"])
        account_data.pop("access_key", None)

        last_used_at = int(time.time())
        stored_key = row["access_key"]
        if stored_key.startswith(f"{ACCESS_KEY_HASH_PREFIX}$"):
            cursor.execute(
                f"UPDATE {TABLE_WEB_SUB_ACCOUNTS} SET last_used_at = ? WHERE id = ?",
                (last_used_at, account_data["id"]),
            )
        else:
            cursor.execute(
                f"UPDATE {TABLE_WEB_SUB_ACCOUNTS} SET last_used_at = ?, access_key = ? WHERE id = ?",
                (last_used_at, _hash_access_key(access_key), account_data["id"]),
            )
        conn.commit()
        return account_data
    except sqlite3.Error as e:
        logging.error(f"[DB SubAccounts Error] Validating access_key failed: {e}")
        return None
    finally:
        conn.close()

def db_get_ticket_departments(guild_id: int) -> List[Dict[str, Any]]:
    """获取指定服务器的所有票据部门。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {TABLE_TICKET_DEPARTMENTS} WHERE guild_id = ?", (guild_id,))
        departments = [dict(row) for row in cursor.fetchall()]
        # 解析 JSON 字段
        for dept in departments:
            if 'staff_role_ids_json' in dept:
                dept['staff_role_ids'] = json.loads(dept['staff_role_ids_json'])
            if 'welcome_message_json' in dept and dept['welcome_message_json']:
                dept['welcome_message'] = json.loads(dept['welcome_message_json'])
        return departments
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 获取票据部门失败 (guild: {guild_id}): {e}")
        return []
    finally:
        conn.close()

def db_create_or_update_department(guild_id: int, data: Dict[str, Any]) -> Tuple[bool, str]:
    """创建或更新一个票据部门。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    dept_id = data.get('department_id')
    name = data.get('name')
    description = data.get('description', '')
    staff_role_ids = data.get('staff_role_ids', [])
    welcome_message = data.get('welcome_message', {})
    button_label = data.get('button_label', name)
    button_emoji = data.get('button_emoji')

    staff_role_ids_json = json.dumps(staff_role_ids)
    welcome_message_json = json.dumps(welcome_message)

    try:
        if dept_id: # 更新
            cursor.execute(f"""
            UPDATE {TABLE_TICKET_DEPARTMENTS} SET 
            name = ?, description = ?, staff_role_ids_json = ?, welcome_message_json = ?, button_label = ?, button_emoji = ?
            WHERE department_id = ? AND guild_id = ?
            """, (name, description, staff_role_ids_json, welcome_message_json, button_label, button_emoji, dept_id, guild_id))
            msg = "部门已更新。"
        else: # 创建
            cursor.execute(f"""
            INSERT INTO {TABLE_TICKET_DEPARTMENTS} 
            (guild_id, name, description, staff_role_ids_json, welcome_message_json, button_label, button_emoji)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, name, description, staff_role_ids_json, welcome_message_json, button_label, button_emoji))
            msg = "部门已创建。"
        
        conn.commit()
        return True, msg
    except sqlite3.IntegrityError:
        return False, "创建失败，可能已存在同名部门。"
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 创建/更新部门失败: {e}")
        conn.rollback()
        return False, f"数据库错误: {e}"
    finally:
        conn.close()

def db_delete_department(department_id: int, guild_id: int) -> bool:
    """删除一个票据部门。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 在删除部门前，可能需要处理关联的票据（例如，将它们的 department_id 设为 NULL）
        # 为简化，这里我们只删除部门本身
        cursor.execute(f"DELETE FROM {TABLE_TICKET_DEPARTMENTS} WHERE department_id = ? AND guild_id = ?", (department_id, guild_id))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 删除部门 {department_id} 失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# =========================================
# == 票据系统 - 票据管理
# =========================================

def db_create_ticket(guild_id: int, channel_id: int, creator_id: int, department_id: int) -> Optional[int]:
    """创建一个新的票据记录。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at = int(time.time())
    try:
        cursor.execute(f"""
        INSERT INTO {TABLE_TICKETS} (guild_id, channel_id, creator_id, department_id, created_at, status)
        VALUES (?, ?, ?, ?, ?, 'OPEN')
        """, (guild_id, channel_id, creator_id, department_id, created_at))
        conn.commit()
        last_id = cursor.lastrowid
        # 【【【新增日志】】】
        logging.warning(f"[DB_TICKET_DEBUG] 成功创建票据记录: ticket_id={last_id}, channel_id={channel_id}")
        return last_id
    except sqlite3.Error as e:
        # 【【【修改日志级别】】】
        logging.error(f"[DB_TICKET_DEBUG] 创建票据记录失败 (channel: {channel_id}): {e}", exc_info=True)
        conn.rollback()
        return None
    finally:
        conn.close()

def db_get_open_tickets(guild_id: int) -> List[Dict[str, Any]]:
    """获取指定服务器所有开启的票据（OPEN 或 CLAIMED）。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 使用 LEFT JOIN 连接部门表以获取部门名称
        cursor.execute(f"""
        SELECT t.*, d.name as department_name 
        FROM {TABLE_TICKETS} t
        LEFT JOIN {TABLE_TICKET_DEPARTMENTS} d ON t.department_id = d.department_id
        WHERE t.guild_id = ? AND t.status IN ('OPEN', 'CLAIMED')
        ORDER BY t.created_at DESC
        """, (guild_id,))
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 获取开启的票据失败 (guild: {guild_id}): {e}")
        return []
    finally:
        conn.close()

def db_get_ticket_by_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """通过频道ID获取票据信息。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 【【【新增日志】】】
        logging.warning(f"[DB_TICKET_DEBUG] 正在通过 channel_id={channel_id} 查询票据...")
        cursor.execute(f"SELECT * FROM {TABLE_TICKETS} WHERE channel_id = ?", (channel_id,))
        row = cursor.fetchone()
        if row:
            logging.warning(f"[DB_TICKET_DEBUG] 查询成功: 找到了 ticket_id={row['ticket_id']} 的记录。")
            return dict(row)
        else:
            # 【【【新增日志】】】
            logging.warning(f"[DB_TICKET_DEBUG] 查询失败: 未找到 channel_id={channel_id} 的记录。")
            return None
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 获取票据信息失败 (channel: {channel_id}): {e}")
        return None
    finally:
        conn.close()

def db_update_ticket_assignee(ticket_id: int, admin_id: int) -> bool:
    """更新一个票据的负责人(claimed_by_id)，并确保其状态为 'CLAIMED'。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
        UPDATE {TABLE_TICKETS} SET status = 'CLAIMED', claimed_by_id = ? 
        WHERE ticket_id = ?
        """, (admin_id, ticket_id))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 更新票据 {ticket_id} 负责人失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def db_close_ticket(ticket_id: int, reason: Optional[str], transcript_filename: Optional[str]) -> bool:
    """关闭一个票据。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    closed_at = int(time.time())
    try:
        cursor.execute(f"""
        UPDATE {TABLE_TICKETS} SET status = 'CLOSED', closed_at = ?, close_reason = ?, transcript_filename = ?
        WHERE ticket_id = ?
        """, (closed_at, reason, transcript_filename, ticket_id))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 关闭票据 {ticket_id} 失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# [ 新增代码块 2 ] - 添加在 database.py 的 db_close_ticket 函数之后

def db_get_ticket_by_id(ticket_id: int) -> Optional[Dict[str, Any]]:
    """通过票据的数据库主键ID获取票据信息。"""
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

# [ 结束新增代码块 2 ]

# [ 新增代码块 ] - 添加在 database.py 的 db_close_ticket 函数之后

def db_get_closed_tickets_with_transcripts(guild_id: int) -> List[Dict[str, Any]]:
    """获取指定服务器所有已关闭且拥有聊天记录文件的票据。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 查询状态为'CLOSED'且transcript_filename不为空的票据
        cursor.execute(f"""
        SELECT * FROM {TABLE_TICKETS}
        WHERE guild_id = ? 
          AND status = 'CLOSED' 
          AND transcript_filename IS NOT NULL 
          AND transcript_filename != ''
        ORDER BY closed_at DESC
        """, (guild_id,))
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 获取已关闭的票据失败 (guild: {guild_id}): {e}")
        return []
    finally:
        conn.close()

# [ 结束新增代码块 ]

def db_set_ticket_ai_managed_status(ticket_id: int, is_managed: bool) -> bool:
    """设置一个票据的AI托管状态。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE {TABLE_TICKETS} SET is_ai_managed = ? WHERE ticket_id = ?", 
                       (1 if is_managed else 0, ticket_id))
        conn.commit()
        logging.info(f"[DB Ticket] Ticket ID {ticket_id} AI managed status set to {is_managed}.")
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"[DB Ticket Error] 设置AI托管状态失败 (ticket_id: {ticket_id}): {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
        
# =========================================
# == 音乐歌单系统
# =========================================

def db_create_playlist(user_id: int, name: str) -> Tuple[bool, str]:
    """创建空歌单"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"INSERT INTO {TABLE_PLAYLISTS} (user_id, name, created_at) VALUES (?, ?, ?)", 
                       (user_id, name, int(time.time())))
        conn.commit()
        return True, "歌单创建成功。"
    except sqlite3.IntegrityError:
        return False, "你已经有一个同名的歌单了。"
    except Exception as e:
        return False, f"数据库错误: {e}"
    finally:
        conn.close()

def db_delete_playlist(user_id: int, name: str) -> bool:
    """删除歌单"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 先获取ID
        cursor.execute(f"SELECT playlist_id FROM {TABLE_PLAYLISTS} WHERE user_id = ? AND name = ?", (user_id, name))
        row = cursor.fetchone()
        if not row: return False
        
        pid = row['playlist_id']
        # 删除歌曲 (如果有外键级联其实不需要这一步，但为了保险)
        cursor.execute(f"DELETE FROM {TABLE_PLAYLIST_TRACKS} WHERE playlist_id = ?", (pid,))
        # 删除歌单
        cursor.execute(f"DELETE FROM {TABLE_PLAYLISTS} WHERE playlist_id = ?", (pid,))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"删除歌单失败: {e}")
        return False
    finally:
        conn.close()

def db_get_user_playlists(user_id: int) -> List[Dict[str, Any]]:
    """获取用户的所有歌单"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT p.*, COUNT(t.track_id) as track_count 
        FROM {TABLE_PLAYLISTS} p 
        LEFT JOIN {TABLE_PLAYLIST_TRACKS} t ON p.playlist_id = t.playlist_id
        WHERE p.user_id = ? 
        GROUP BY p.playlist_id
    """, (user_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def db_save_queue_to_playlist(user_id: int, name: str, tracks: List[Dict[str, str]]) -> Tuple[bool, str]:
    """将当前队列保存到歌单 (如果歌单不存在则创建，存在则追加)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. 检查歌单是否存在
        cursor.execute(f"SELECT playlist_id FROM {TABLE_PLAYLISTS} WHERE user_id = ? AND name = ?", (user_id, name))
        row = cursor.fetchone()
        
        if row:
            playlist_id = row['playlist_id']
        else:
            # 创建新歌单
            cursor.execute(f"INSERT INTO {TABLE_PLAYLISTS} (user_id, name, created_at) VALUES (?, ?, ?)", 
                           (user_id, name, int(time.time())))
            playlist_id = cursor.lastrowid
        
        # 2. 批量插入歌曲
        track_data = [(playlist_id, t['uri'], t['title'], t['author']) for t in tracks]
        cursor.executemany(f"INSERT INTO {TABLE_PLAYLIST_TRACKS} (playlist_id, uri, title, author) VALUES (?, ?, ?, ?)", track_data)
        
        conn.commit()
        return True, f"成功保存 {len(tracks)} 首歌曲到歌单 '{name}'。"
    except Exception as e:
        conn.rollback()
        return False, f"保存失败: {e}"
    finally:
        conn.close()

def db_load_playlist_tracks(user_id: int, name: str) -> List[str]:
    """获取歌单里的所有歌曲 URI"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT t.uri 
            FROM {TABLE_PLAYLIST_TRACKS} t
            JOIN {TABLE_PLAYLISTS} p ON t.playlist_id = p.playlist_id
            WHERE p.user_id = ? AND p.name = ?
        """, (user_id, name))
        rows = cursor.fetchall()
        return [row['uri'] for row in rows]
    finally:
        conn.close()

if __name__ == "__main__":
    print("database.py 被直接运行。正在尝试初始化数据库...")
    initialize_database()
    print("数据库初始化（如果需要）已完成。")
