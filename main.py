#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت متجر الاشتراكات والذكاء الاصطناعي | GoPro Store Telegram Bot
---------------------------------------------------------------
الميزات:
1. هيكلية موحدة للمنتجات والباقات مع فئات فرعية وصور.
2. نظام رتب ثلاثي للأسعار (عميل، تاجر، صديق) مع تخصيص كامل.
3. تجربة عميل متميزة: دعم فني، سجل مشتريات، إدخال إيميل إجباري، رقم مرجعي فريد.
4. نظام كوبونات متقدم مع تتبع المؤثرين والإحصائيات وتخصيص الخصم للباقات.
5. لوحة تحكم وإحصائيات شاملة للأدمن مع مراجعة الاشتراكات المعلقة وبيانات العملاء.
"""

import os
import re
import io
import json
import random
import string
import sqlite3
import datetime
import threading
import traceback
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

import telebot
from telebot import types

try:
    from keep_alive import keep_alive
except ImportError:
    def keep_alive():
        pass

# ================= Configuration =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8891794386:AAGsDFvqhE-2OogWcbXDKhKQYnwTdB5Okho")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5152178321"))
VODAFONE_CASH = os.getenv("VODAFONE_CASH", "01060348550")
SUPPORT_WHATSAPP = "01220146907"
SUPPORT_TELEGRAM = "@gopro_store_team"
REQUIRED_GROUP = os.getenv("REQUIRED_GROUP", "@gopro_store_group")
REQUIRED_GROUP_URL = os.getenv("REQUIRED_GROUP_URL", "https://t.me/gopro_store_group")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("SHOP_BOT_DB_PATH", os.path.join(BASE_DIR, "shop_bot.sqlite3"))
STORE_DATA_PATH = os.path.join(BASE_DIR, "store_data.json")
USER_ROLES_PATH = os.path.join(BASE_DIR, "user_roles.json")
RESELLERS_PATH = os.path.join(BASE_DIR, "resellers.json")
COUPONS_PATH = os.path.join(BASE_DIR, "coupons.json")
WAITLIST_PATH = os.path.join(BASE_DIR, "waitlist.json")
ADMINS_PATH = os.path.join(BASE_DIR, "admins.json")

_db_lock = threading.RLock()
_store_lock = threading.RLock()
_roles_lock = threading.RLock()
_coupons_lock = threading.RLock()
_admins_lock = threading.RLock()

user_states = {}
admin_action_states = {}

def safe_callback(func):
    """Decorator that ensures answer_callback_query is always called, preventing infinite spinning."""
    def wrapper(call):
        try:
            user_id = call.from_user.id
            track_user_activity(call.from_user)
            if call.data != "check_join" and not is_admin(user_id) and not is_user_subscribed(user_id):
                try:
                    bot.answer_callback_query(call.id, "⚠️ يجب الاشتراك في جروب المتجر أولاً للاستمرار!", show_alert=True)
                except Exception:
                    pass
                send_force_join_message(call.message.chat.id)
                return
            func(call)
        except Exception as e:
            print(f"Error in callback handler {func.__name__}: {e}")
            traceback.print_exc()
            try:
                bot.answer_callback_query(call.id, "❌ حدث خطأ غير متوقع، يرجى المحاولة لاحقاً.", show_alert=True)
            except Exception:
                pass
    wrapper.__name__ = func.__name__
    return wrapper

def safe_edit_message_text(call, text, reply_markup=None):
    """
    Safely edit a message (text or photo caption), handling:
    - "message is not modified" errors (ignored silently)
    - Photo messages (attempts edit_message_caption first, falls back to delete + send_message)
    - Normal text messages (edit_message_text, falls back to delete + send_message)
    """
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    is_photo = bool(getattr(call.message, 'photo', None) or getattr(call.message, 'content_type', None) == 'photo')

    if is_photo:
        if len(text) <= 1024:
            try:
                bot.edit_message_caption(
                    caption=text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup
                )
                return
            except Exception as e:
                error_str = str(e).lower()
                if "message is not modified" in error_str:
                    return
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as send_err:
            print(f"Error sending fallback message: {send_err}")
        return

    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup
        )
    except Exception as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str:
            return
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as send_err:
            print(f"Error sending fallback message: {send_err}")

# ================= Database Helpers =================
@contextmanager
def database_connection():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def generate_order_ref():
    chars = "".join(random.choices(string.digits, k=5))
    return f"ORD-{chars}"

def initialize_database()

# ================= User Tracking & Profile Helpers =================
def save_or_update_user(user_id, username=None, first_name=None, last_name=None):
    if not user_id:
        return
    now_str = utc_now()
    clean_username = username.lstrip("@").lower() if username else None
    try:
        with database_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, date_joined, last_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    last_active = excluded.last_active
            """, (user_id, clean_username, first_name, last_name, now_str, now_str))
    except Exception as e:
        print(f"Error in save_or_update_user: {e}")

def track_user_activity(from_user):
    if not from_user:
        return
    save_or_update_user(
        user_id=from_user.id,
        username=getattr(from_user, 'username', None),
        first_name=getattr(from_user, 'first_name', None),
        last_name=getattr(from_user, 'last_name', None)
    )
:
    with database_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_ref TEXT UNIQUE,
                user_id INTEGER NOT NULL,
                product_key TEXT NOT NULL,
                package_key TEXT,
                package_name TEXT,
                status TEXT NOT NULL,
                step TEXT NOT NULL,
                receipt_file_id TEXT,
                phone_number TEXT,
                customer_email TEXT,
                customer_username TEXT,
                customer_first_name TEXT,
                customer_last_name TEXT,
                user_role TEXT NOT NULL DEFAULT 'customer',
                pricing_tier TEXT,
                unit_price TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                discount_amount TEXT DEFAULT '0ج',
                coupon_code TEXT,
                total_amount TEXT,
                admin_chat_id INTEGER,
                admin_message_id INTEGER,
                admin_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Ensure any missing columns from older versions are added safely
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(payment_requests)").fetchall()}
        additions = {
            "order_ref": "TEXT UNIQUE",
            "package_key": "TEXT",
            "package_name": "TEXT",
            "customer_email": "TEXT",
            "user_role": "TEXT NOT NULL DEFAULT 'customer'",
            "pricing_tier": "TEXT",
            "unit_price": "TEXT",
            "quantity": "INTEGER NOT NULL DEFAULT 1",
            "discount_amount": "TEXT DEFAULT '0ج'",
            "coupon_code": "TEXT",
            "total_amount": "TEXT",
            "admin_notes": "TEXT",
            "admin_chat_id": "INTEGER",
            "admin_message_id": "INTEGER",
            "wallet_used": "REAL DEFAULT 0.0",
            "cashback_earned": "REAL DEFAULT 0.0"
        }
        for col, col_type in additions.items():
            if col not in columns:
                try:
                    conn.execute(f"ALTER TABLE payment_requests ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                request_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (request_id) REFERENCES payment_requests(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_user ON payment_requests(user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_ref ON payment_requests(order_ref)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications_log(user_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon_usages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_code TEXT NOT NULL,
                order_ref TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                customer_name TEXT,
                product_name TEXT NOT NULL,
                package_name TEXT NOT NULL,
                original_amount TEXT NOT NULL,
                discount_amount TEXT NOT NULL,
                final_amount TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupon_usages_code ON coupon_usages(coupon_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupon_usages_ref ON coupon_usages(order_ref)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_wallets (
                user_id INTEGER PRIMARY KEY,
                balance REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                date_joined TEXT NOT NULL,
                last_active TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_ref TEXT,
                trans_type TEXT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_trans_user ON wallet_transactions(user_id)")

        # Restore in-memory user states
        states = {
            row["user_id"]: json.loads(row["state_json"])
            for row in conn.execute("SELECT user_id, state_json FROM user_states").fetchall()
        }
        user_states.clear()
        user_states.update(states)

initialize_database()

# ================= Storage & JSON Helpers =================
def load_json_file(file_path, default_factory):
    if not os.path.exists(file_path):
        data = default_factory()
        save_json_file(file_path, data)
        return data
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default_factory()

def save_json_file(file_path, data):
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
        f.write("\n")
    os.replace(tmp_path, file_path)

def get_store_data():
    with _store_lock:
        return load_json_file(STORE_DATA_PATH, dict)

def update_store_data(new_data):
    with _store_lock:
        save_json_file(STORE_DATA_PATH, new_data)

def get_user_roles():
    with _roles_lock:
        return load_json_file(USER_ROLES_PATH, dict)

def update_user_roles(roles):
    with _roles_lock:
        save_json_file(USER_ROLES_PATH, roles)
        # Sync resellers.json for backwards compatibility
        reseller_ids = [int(uid) for uid, info in roles.items() if info.get("role") == "reseller" and uid.isdigit()]
        save_json_file(RESELLERS_PATH, sorted(reseller_ids))

# ================= Admins Management (Multi-Admin System) =================
def get_admins():
    with _admins_lock:
        admins = load_json_file(ADMINS_PATH, dict)
        owner_id_str = str(ADMIN_ID)
        # Ensure owner is always present and marked as owner
        if owner_id_str not in admins:
            admins[owner_id_str] = {
                "role": "admin",
                "name": "المدير العام (المالك)",
                "username": "admin",
                "is_owner": True,
                "added_at": utc_now()
            }
            save_json_file(ADMINS_PATH, admins)
        else:
            admins[owner_id_str]["is_owner"] = True
            admins[owner_id_str]["role"] = "admin"
        return admins

def update_admins(admins):
    with _admins_lock:
        owner_id_str = str(ADMIN_ID)
        if owner_id_str not in admins:
            admins[owner_id_str] = {
                "role": "admin",
                "name": "المدير العام (المالك)",
                "username": "admin",
                "is_owner": True,
                "added_at": utc_now()
            }
        admins[owner_id_str]["is_owner"] = True
        save_json_file(ADMINS_PATH, admins)

        # Synchronize with user_roles.json
        roles = get_user_roles()
        for uid, ainfo in admins.items():
            roles[uid] = {
                "role": "admin",
                "name": ainfo.get("name", "مشرف"),
                "username": ainfo.get("username", ""),
                "updated_at": utc_now()
            }
        for uid in list(roles.keys()):
            if roles[uid].get("role") == "admin" and uid not in admins and uid != owner_id_str:
                del roles[uid]
        update_user_roles(roles)

def is_admin(user_id):
    if not user_id:
        return False
    try:
        if int(user_id) == ADMIN_ID:
            return True
    except (ValueError, TypeError):
        pass
    uid_str = str(user_id)
    admins = get_admins()
    if uid_str in admins:
        return True
    roles = get_user_roles()
    uinfo = roles.get(uid_str)
    if uinfo and isinstance(uinfo, dict) and uinfo.get("role") == "admin":
        return True
    return False

def get_all_admin_ids():
    admins = {ADMIN_ID}
    for uid_str in get_admins():
        if uid_str.isdigit():
            admins.add(int(uid_str))
    for uid_str, info in get_user_roles().items():
        if info.get("role") == "admin" and uid_str.isdigit():
            admins.add(int(uid_str))
    return sorted(list(admins))

def add_new_admin(user_id, name="مشرف", username=""):
    uid_str = str(user_id)
    admins = get_admins()
    if uid_str in admins:
        return False, "هذا المستخدم مسجل بالفعل كأدمن."
    admins[uid_str] = {
        "role": "admin",
        "name": name or "مشرف",
        "username": username or "",
        "is_owner": False,
        "added_at": utc_now()
    }
    update_admins(admins)
    return True, "تمت إضافة المشرف بنجاح."

def remove_existing_admin(user_id):
    uid_str = str(user_id)
    if uid_str == str(ADMIN_ID):
        return False, "لا يمكن حذف المالك الأساسي للنظام."
    admins = get_admins()
    if uid_str not in admins:
        return False, "المشرف غير موجود في قائمة الإدارة."
    if admins[uid_str].get("is_owner"):
        return False, "لا يمكن حذف المالك الأساسي للنظام."
    del admins[uid_str]
    update_admins(admins)
    return True, "تم حذف المشرف بنجاح."

# ================= Mandatory Channel / Group Subscription =================
def is_user_subscribed(user_id):
    if is_admin(user_id):
        return True
    try:
        member = bot.get_chat_member(REQUIRED_GROUP, user_id)
        if member.status in ("member", "administrator", "creator", "restricted"):
            return True
        return False
    except Exception as e:
        err_msg = str(e).lower()
        if "user not found" in err_msg or "user_not_participant" in err_msg or "participant" in err_msg:
            return False
        # Fail open if bot is not in group or group is inaccessible to avoid locking everyone out
        print(f"Warning in is_user_subscribed for user {user_id}: {e}")
        return True

def get_force_join_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 انضمام إلى الجروب", url=REQUIRED_GROUP_URL),
        types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_join")
    )
    return markup

def send_force_join_message(chat_id):
    text = (
        "⚠️ <b>عذراً عزيزي، يجب عليك أولاً الانضمام إلى جروب المتجر الرسمي لتتمكن من استخدام البوت والاستفادة من خدماتنا!</b>\n\n"
        "👇 انضم الآن ثم اضغط على زر التحقق بالأسفل:"
    )
    bot.send_message(chat_id, text, reply_markup=get_force_join_markup(), disable_web_page_preview=True)

# ================= Wallet & Cashback Helpers =================
def get_user_wallet_balance(user_id):
    """إجمالي الرصيد الفعلي المخزن في محفظة المستخدم"""
    with database_connection() as conn:
        row = conn.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return Decimal(str(row["balance"]))
        return Decimal("0.0")

def get_user_pending_wallet_usage(user_id, exclude_request_id=None):
    """الرصيد المحجوز حالياً في طلبات معلقة قيد المعالجة (لم يوافق عليها أو يرفضها الأدمن بعد)"""
    with database_connection() as conn:
        query = """
            SELECT COALESCE(SUM(wallet_used), 0) as reserved
            FROM payment_requests
            WHERE user_id = ?
              AND status IN ('awaiting_quantity', 'awaiting_custom_qty', 'awaiting_coupon', 'awaiting_coupon_code', 'awaiting_wallet', 'awaiting_receipt', 'awaiting_phone', 'awaiting_email', 'awaiting_admin')
        """
        params = [user_id]
        if exclude_request_id:
            query += " AND id != ?"
            params.append(exclude_request_id)
        row = conn.execute(query, tuple(params)).fetchone()
        return Decimal(str(row["reserved"])) if row else Decimal("0.0")

def get_user_available_wallet_balance(user_id, current_request_id=None):
    """الرصيد المتاح للاستخدام الفوري (الرصيد الكلي مطروحاً منه أي حجوزات معلقة)"""
    total = get_user_wallet_balance(user_id)
    pending = get_user_pending_wallet_usage(user_id, exclude_request_id=current_request_id)
    avail = total - pending
    return max(Decimal("0.0"), avail)

def add_wallet_transaction(user_id, trans_type, amount, description, order_ref=None):
    """تعديل رصيد المحفظة وتسجيل المعاملة في جدول الحركات"""
    with database_connection() as conn:
        row = conn.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
        current_bal = Decimal(str(row["balance"])) if row else Decimal("0.0")
        new_bal = max(Decimal("0.0"), current_bal + Decimal(str(amount)))

        conn.execute("""
            INSERT INTO user_wallets (user_id, balance, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = excluded.balance,
                updated_at = excluded.updated_at
        """, (user_id, float(new_bal), utc_now()))

        conn.execute("""
            INSERT INTO wallet_transactions (user_id, order_ref, trans_type, amount, balance_after, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, order_ref, trans_type, float(amount), float(new_bal), description, utc_now()))

        return new_bal

def get_user_wallet_transactions(user_id, limit=10):
    with database_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM wallet_transactions
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return rows

def get_package_cashback(package, user_id=None):
    if not package:
        return Decimal("0.0")
    if user_id:
        role = get_user_role(user_id)
        if role != "customer":
            return Decimal("0.0")
    val = package.get("cashback") or package.get("cashback_amount") or "0"
    amt = parse_price_amount(str(val))
    return amt or Decimal("0.0")

def get_coupons():
    with _coupons_lock:
        return load_json_file(COUPONS_PATH, dict)

def update_coupons(coupons):
    with _coupons_lock:
        save_json_file(COUPONS_PATH, coupons)

_waitlist_lock = threading.RLock()

def get_waitlist():
    with _waitlist_lock:
        return load_json_file(WAITLIST_PATH, dict)

def update_waitlist(waitlist):
    with _waitlist_lock:
        save_json_file(WAITLIST_PATH, waitlist)

# ================= User Roles and Pricing =================
# Roles: 'customer' (عميل), 'reseller' (تاجر), 'friend' (صديق), 'admin' (أدمن)
def get_user_role(user_id):
    if is_admin(user_id):
        return "admin"
    roles = get_user_roles()
    user_info = roles.get(str(user_id))
    if user_info and isinstance(user_info, dict):
        return user_info.get("role", "customer")
    return "customer"

def set_user_role(user_id, role, name=None, username=None):
    roles = get_user_roles()
    uid = str(user_id)
    if role == "customer":
        if uid in roles and uid != str(ADMIN_ID):
            del roles[uid]
    else:
        roles[uid] = {
            "role": role,
            "name": name or roles.get(uid, {}).get("name", "مستخدم"),
            "username": username or roles.get(uid, {}).get("username", ""),
            "updated_at": utc_now()
        }
    update_user_roles(roles)

def role_badge_display(role):
    if role == "admin":
        return "👑 مدير النظام"
    elif role == "reseller":
        return "💼 تاجر / مسوق معتمد"
    elif role == "friend":
        return "🤝 صديق معتمد"
    else:
        return "👤 عميل"

def parse_price_amount(price_str):
    if not price_str:
        return None
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    clean = price_str.translate(trans)
    match = re.search(r"(\d+(\.\d+)?)", clean.replace(",", ""))
    if match:
        try:
            return Decimal(match.group(1))
        except InvalidOperation:
            return None
    return None

def format_currency(amount):
    if amount is None:
        return "0ج"
    if isinstance(amount, (int, float)):
        amount = Decimal(str(amount))
    formatted = f"{amount:,.0f}".replace(",", "،") if amount == int(amount) else f"{amount:,.2f}".replace(",", "،")
    return f"{formatted}ج"

def get_package_price_for_user(package, user_id):
    role = get_user_role(user_id)
    retail = package.get("retail_price", "0ج")
    reseller = package.get("reseller_price") or retail
    friend = package.get("friend_price") or retail

    if role == "admin":
        return {
            "display": f"العميل: {retail} | التاجر: {reseller} | الصديق: {friend}",
            "unit_price": retail,
            "tier_name": "المدير",
            "amount": parse_price_amount(retail) or Decimal("0")
        }
    elif role == "reseller":
        return {
            "display": f"سعر التجار والمسوقين: {reseller}",
            "unit_price": reseller,
            "tier_name": "تاجر",
            "amount": parse_price_amount(reseller) or Decimal("0")
        }
    elif role == "friend":
        return {
            "display": f"سعر الأصدقاء: {friend}",
            "unit_price": friend,
            "tier_name": "صديق",
            "amount": parse_price_amount(friend) or Decimal("0")
        }
    else:
        # Normal customer: show "السعر:" ONLY without any "عميل عادي"
        return {
            "display": f"السعر: {retail}",
            "unit_price": retail,
            "tier_name": "عميل",
            "amount": parse_price_amount(retail) or Decimal("0")
        }

# ================= ChatGPT Business Dynamic Info =================
def get_chatgpt_business_info():
    today = datetime.date.today()
    if today.day <= 23:
        target_date = datetime.date(today.year, today.month, 23)
    elif today.month == 12:
        target_date = datetime.date(today.year + 1, 1, 23)
    else:
        target_date = datetime.date(today.year, today.month + 1, 23)
    remaining_days = (target_date - today).days
    return remaining_days, target_date.strftime("%d-%m-%Y")

# ================= Keyboards =================
def get_main_menu_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    browse_btn = types.KeyboardButton("🛍 تصفح المنتجات")
    orders_btn = types.KeyboardButton("📦 سجل مشترياتي")
    wallet_btn = types.KeyboardButton("💰 محفظتي")
    account_btn = types.KeyboardButton("👤 بيانات حسابي / ID")
    support_btn = types.KeyboardButton("💬 الدعم الفني")
    markup.add(browse_btn, orders_btn)
    markup.add(wallet_btn, account_btn)
    markup.add(support_btn)
    if is_admin(user_id):
        markup.add(types.KeyboardButton("🛠 لوحة الإدارة"))
    return markup

def build_products_inline_menu(user_id):
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for prod_key, prod in store.items():
        is_avail = prod.get("available", True)
        if is_avail:
            btn_text = f"🟢 {prod['name']}"
        else:
            btn_text = f"🔴 {prod['name']} | (غير متوفر)"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"prod_{prod_key}"))
    return markup

def build_subcategories_or_packages_keyboard(prod_key, user_id, selected_subcat=None):
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        return types.InlineKeyboardMarkup()
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    subcategories = prod.get("subcategories")
    
    if subcategories and not selected_subcat:
        for subcat in subcategories:
            markup.add(types.InlineKeyboardButton(
                f"📂 {subcat['name']}",
                callback_data=f"subcat_{prod_key}_{subcat['id']}"
            ))
        markup.add(types.InlineKeyboardButton("🔙 رجوع لقائمة المنتجات", callback_data="back_to_products"))
        return markup

    packages = prod.get("packages", [])
    if selected_subcat:
        packages = [p for p in packages if p.get("subcategory") == selected_subcat]

    for pkg in packages:
        label = pkg["label"]
        if prod_key == "chatgpt" and pkg["id"] == "biz_remaining":
            days, end_date = get_chatgpt_business_info()
            label = f"الأيام المتبقية ({days} يوم حتى {end_date})"

        if not pkg.get("available", True):
            markup.add(types.InlineKeyboardButton(
                f"🔴 {label} | (غير متوفر)",
                callback_data=f"pkg_unavailable_{prod_key}_{pkg['id']}"
            ))
            continue
        price_info = get_package_price_for_user(pkg, user_id)
        btn_text = f"🟢 {label} | {price_info['unit_price']}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"pkg_{prod_key}_{pkg['id']}"))

    if selected_subcat:
        markup.add(types.InlineKeyboardButton("🔙 رجوع لاختيار الباقة الرئيسية", callback_data=f"prod_{prod_key}"))
    else:
        markup.add(types.InlineKeyboardButton("🔙 رجوع لقائمة المنتجات", callback_data="back_to_products"))
    return markup

def build_quantity_keyboard(request_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    quantities = [1, 2, 3, 5, 10, 20]
    btns = [types.InlineKeyboardButton(str(q), callback_data=f"qty_{request_id}_{q}") for q in quantities]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🔢 كمية أخرى خاصة", callback_data=f"qty_{request_id}_custom"))
    markup.add(types.InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"cancel_order_{request_id}"))
    return markup

def build_coupon_decision_keyboard(request_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎟 لدي كود خصم", callback_data=f"use_coupon_{request_id}"),
        types.InlineKeyboardButton("⏩ تخطي ومتابعة", callback_data=f"skip_coupon_{request_id}")
    )
    markup.add(types.InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"cancel_order_{request_id}"))
    return markup

def build_coupon_product_selection_keyboard(admin_id):
    state = admin_action_states.get(admin_id, {})
    selected = state.get("selected_products", [])
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for prod_key, prod in store.items():
        prefix = "✅ " if prod_key in selected else "☐ "
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{prod['name']}",
            callback_data=f"adm_cpn_sel_{prod_key}"
        ))
    all_mark = "✅ " if selected == [] else "☐ "
    markup.add(types.InlineKeyboardButton(f"{all_mark}الكل (جميع المنتجات)", callback_data="adm_cpn_sel_all"))
    markup.add(types.InlineKeyboardButton("➡️ التالي: اختيار الباقات", callback_data="adm_cpn_to_tiers"))
    return markup

def build_coupon_tier_selection_keyboard(admin_id):
    state = admin_action_states.get(admin_id, {})
    selected_products = state.get("selected_products", [])
    selected_tiers = state.get("selected_tiers", [])
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)

    # If no products selected, show all
    products_to_show = store if not selected_products else {k: v for k, v in store.items() if k in selected_products}

    for prod_key, prod in products_to_show.items():
        for pkg in prod.get("packages", []):
            tier_key = f"{prod_key}_{pkg['id']}"
            prefix = "✅ " if tier_key in selected_tiers else "☐ "
            markup.add(types.InlineKeyboardButton(
                f"{prefix}{prod['name']} — {pkg['label']}",
                callback_data=f"adm_cpn_tier_{tier_key}"
            ))

    all_mark = "✅ " if not selected_tiers else "☐ "
    markup.add(types.InlineKeyboardButton(f"{all_mark}الكل (جميع الباقات)", callback_data="adm_cpn_tier_all"))
    markup.add(types.InlineKeyboardButton("✅ تأكيد وإنشاء الكوبون", callback_data="adm_cpn_confirm"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للمنتجات", callback_data="adm_cpn_back_to_products"))
    return markup

# ================= Order Lifecycle & State Management =================
def save_db_user_state(user_id, state):
    with database_connection() as conn:
        conn.execute("""
            INSERT INTO user_states (user_id, request_id, state_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                request_id = excluded.request_id,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
        """, (user_id, state["request_id"], json.dumps(state, ensure_ascii=False), utc_now()))
    user_states[user_id] = state

def clear_db_user_state(user_id):
    with database_connection() as conn:
        conn.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
    user_states.pop(user_id, None)

def start_new_order(user_id, prod_key, pkg_id):
    store = get_store_data() or {}
    prod = store.get(prod_key)
    if not prod or not prod.get("available", True):
        return None
    pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None)
    if not pkg or not pkg.get("available", True):
        return None

    role = get_user_role(user_id)
    price_info = get_package_price_for_user(pkg, user_id)
    order_ref = generate_order_ref()
    cb_unit = float(get_package_cashback(pkg, user_id=user_id)) if role == "customer" else 0.0

    with database_connection() as conn:
        # Cancel any previous active order in creation step
        conn.execute("""
            UPDATE payment_requests
            SET status = 'cancelled', updated_at = ?
            WHERE user_id = ? AND status IN ('awaiting_quantity', 'awaiting_custom_qty', 'awaiting_coupon', 'awaiting_coupon_code', 'awaiting_wallet', 'awaiting_receipt', 'awaiting_phone', 'awaiting_email')
        """, (utc_now(), user_id))

        cursor = conn.execute("""
            INSERT INTO payment_requests (
                order_ref, user_id, product_key, package_key, package_name,
                status, step, user_role, pricing_tier, unit_price,
                quantity, discount_amount, total_amount, wallet_used, cashback_earned, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'awaiting_quantity', 'awaiting_quantity', ?, ?, ?, 1, '0ج', ?, 0.0, ?, ?, ?)
        """, (
            order_ref, user_id, prod_key, pkg_id, pkg["label"],
            role, price_info["tier_name"], price_info["unit_price"],
            format_currency(price_info["amount"]), cb_unit, utc_now(), utc_now()
        ))
        request_id = cursor.lastrowid

    state = {
        "request_id": request_id,
        "order_ref": order_ref,
        "product_key": prod_key,
        "package_key": pkg_id,
        "package_name": pkg["label"],
        "step": "awaiting_quantity",
        "requires_email": pkg.get("requires_email", False),
        "user_role": role,
        "unit_price": price_info["unit_price"],
        "unit_amount": float(price_info["amount"]),
        "cashback_unit": cb_unit,
        "quantity": 1,
        "discount_amount": 0,
        "coupon_code": None,
        "wallet_used": 0.0,
        "total_amount": float(price_info["amount"])
    }
    save_db_user_state(user_id, state)
    return state

# ================= Bot Handlers =================
@bot.message_handler(commands=["start"])
def handle_start(message):
    user_id = message.from_user.id
    track_user_activity(message.from_user)
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    name = message.from_user.first_name or "عزيزنا العميل"
    role = get_user_role(user_id)
    
    role_note = ""
    if role == "reseller":
        role_note = "💼 <b>حساب تاجر معتمد</b> (تُطبق لك أسعار خاصة بالتجار والمسوقين)\n\n"
    elif role == "friend":
        role_note = "🤝 <b>حساب صديق</b> (تُطبق لك أسعار خاصة بالأصدقاء)\n\n"
    elif role == "admin":
        role_note = "👑 <b>حساب المدير العام</b>\n\n"
    # للعميل العادي: لا تذكر أي كلمة تشير للرتبة وتبدأ بالترحيب والخدمات مباشرة
    
    welcome_text = (
        f"👋 أهلاً بك يا <b>{name}</b> في متجر الاشتراكات والذكاء الاصطناعي 🚀\n\n"
        + role_note +
        "✨ نوفر لك أفضل اشتراكات الذكاء الاصطناعي، التصميم، والمونتاج بأسعار منافسة وتسليم رسمي سريع ومضمون.\n\n"
        "اختر ما تريد من القائمة بالأسفل:"
    )
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=get_main_menu_keyboard(user_id)
    )

@bot.message_handler(func=lambda msg: msg.text == "🛍 تصفح المنتجات")
def handle_browse_products(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    role = get_user_role(user_id)
    
    role_header = ""
    if role == "reseller":
        role_header = "💼 <b>حساب تاجر معتمد:</b> (الأسعار المعروضة بأسعار التجار المخفضة)\n\n"
    elif role == "friend":
        role_header = "🤝 <b>حساب صديق:</b> (الأسعار المعروضة بأسعار الأصدقاء الخاصة)\n\n"
    elif role == "admin":
        role_header = "👑 <b>لوحة المدير:</b> (تظهر لك كافة فئات الأسعار)\n\n"
    # للعميل العادي: بدون أي إشارة للرتبة نهائياً
    
    bot.send_message(
        message.chat.id,
        f"🛍 <b>قائمة المنتجات والاشتراكات المتاحة</b>\n\n"
        + role_header +
        "اضغط على أي منتج لعرض باقاته وتفاصيل الشراء:",
        reply_markup=build_products_inline_menu(user_id)
    )

@bot.message_handler(func=lambda msg: msg.text == "💬 الدعم الفني")
def handle_support(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    try:
        support_text = (
            "🛠 <b>مركز المساعدة والدعم الفني | GoPro Store Team</b>\n\n"
            "فريقنا متواجد دائماً لمساعدتك في الاستفسار أو تفعيل ومتابعة طلباتك:\n\n"
            f"📱 <b>واتساب:</b> <code>{SUPPORT_WHATSAPP}</code>\n"
            f"✈️ <b>تيليجرام:</b> {SUPPORT_TELEGRAM}\n"
            "⏰ مواعيد العمل: متواجدون على مدار 24 ساعة للرد السريع."
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💬 مراسلة واتساب", url=f"https://wa.me/2{SUPPORT_WHATSAPP}"),
            types.InlineKeyboardButton("✈️ مراسلة تيليجرام", url="https://t.me/gopro_store_team")
        )
        bot.send_message(message.chat.id, support_text, reply_markup=markup)
    except Exception as e:
        print(f"Error in support handler: {e}")
        traceback.print_exc()
        bot.send_message(message.chat.id, "⚠️ حدث خطأ في عرض معلومات الدعم الفني. يرجى المحاولة لاحقاً.")

@bot.callback_query_handler(func=lambda c: c.data == "support")
@safe_callback
def handle_support_callback(call):
    try:
        support_text = (
            "🛠 <b>مركز المساعدة والدعم الفني | GoPro Store Team</b>\n\n"
            "فريقنا متواجد دائماً لمساعدتك:\n\n"
            f"📱 <b>واتساب:</b> <code>{SUPPORT_WHATSAPP}</code>\n"
            f"✈️ <b>تيليجرام:</b> {SUPPORT_TELEGRAM}\n"
            "⏰ مواعيد العمل: متواجدون على مدار 24 ساعة."
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💬 مراسلة واتساب", url=f"https://wa.me/2{SUPPORT_WHATSAPP}"),
            types.InlineKeyboardButton("✈️ مراسلة تيليجرام", url="https://t.me/gopro_store_team")
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, support_text, reply_markup=markup)
    except Exception as e:
        print(f"Error in support callback: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ حدث خطأ. يرجى المحاولة لاحقاً.", show_alert=True)
        except Exception:
            pass

# ================= Customer Wallet UI =================
def format_wallet_display(user_id, user_first_name="عزيزنا العميل"):
    bal = get_user_wallet_balance(user_id)
    pending = get_user_pending_wallet_usage(user_id)
    avail = get_user_available_wallet_balance(user_id)
    txs = get_user_wallet_transactions(user_id, limit=8)

    text = (
        f"💰 <b>محفظة الكاش باك | GoPro Wallet</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>صاحب المحفظة:</b> {user_first_name}\n"
        f"💵 <b>الرصيد المتاح للاستخدام:</b> <b>{format_currency(avail)}</b>\n"
    )
    if pending > Decimal("0"):
        text += f"⏳ <b>رصيد محجوز لطلبات قيد المراجعة:</b> {format_currency(pending)}\n"
        text += f"💼 <b>إجمالي رصيد المحفظة:</b> {format_currency(bal)}\n"

    text += "━━━━━━━━━━━━━━━━━━━\n"

    if not txs:
        text += "📜 <b>سجل العمليات:</b>\n<i>لا توجد عمليات سابقة في المحفظة حتى الآن. يمكنك كسب الكاش باك عند شراء الباقات المؤهلة!</i>\n"
    else:
        text += "📜 <b>آخر المعاملات في المحفظة:</b>\n"
        for t in txs:
            dt = t["created_at"][:16].replace("T", " ")
            amt = Decimal(str(t["amount"]))
            if amt > Decimal("0"):
                sign = f"🟢 +{format_currency(amt)}"
            else:
                sign = f"🔴 {format_currency(amt)}"
            text += f"• {sign} | {t['description']} (<i>{dt}</i>)\n"

    text += "\n💡 <i>ملاحظة: يتم عرض خيار خصم رصيدك تلقائياً عند إجراء أي طلب شراء جديد!</i>"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛍 تصفح المنتجات", callback_data="back_to_products"),
        types.InlineKeyboardButton("🔄 تحديث الرصيد", callback_data="refresh_wallet")
    )
    markup.add(
        types.InlineKeyboardButton("👤 بيانات حسابي / ID", callback_data="my_account_info")
    )
    return text, markup


# ================= Customer Account Info / Chat ID Display =================
def format_user_account_info(user_id, first_name=None, last_name=None, username=None):
    bal = get_user_wallet_balance(user_id)
    role = get_user_role(user_id)
    role_names = {
        "admin": "👑 مدير النظام (Admin)",
        "reseller": "💼 تاجر معتمد (Reseller)",
        "friend": "🤝 صديق معتمد (Friend)",
        "customer": "👤 عميل (Customer)"
    }
    role_str = role_names.get(role, "عميل")
    username_str = f"@{username}" if username else "غير محدد"
    fn = first_name or "عزيزنا العميل"
    ln = f" {last_name}" if last_name else ""
    account_name = f"{fn}{ln}".strip()

    text = (
        "👤 <b>بيانات حسابك | Account Details</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>معرف التليجرام الخاص بك (Chat ID):</b>\n"
        f"<code>{user_id}</code>\n"
        "👆 <i>(اضغط على الرقم لنسخه بنقرة واحدة)</i>\n\n"
        f"📛 <b>اسم الحساب:</b> {account_name}\n"
        f"🌐 <b>اسم المستخدم:</b> {username_str}\n"
        f"💰 <b>رصيد المحفظة الحالي:</b> <b>{format_currency(bal)} EGP</b>\n"
        f"🎖 <b>الرتبة الحالية:</b> <b>{role_str}</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>يمكنك إرسال الـ Chat ID لخدمة العملاء عند الاستفسار أو تفعيل الحسابات والترقيات.</i>"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 عرض محفظتي", callback_data="refresh_wallet"),
        types.InlineKeyboardButton("🛍 تصفح المنتجات", callback_data="back_to_products")
    )
    return text, markup

@bot.message_handler(func=lambda msg: msg.text in ("👤 بيانات حسابي / ID", "بيانات حسابي / ID", "بيانات حسابي", "/id", "/account"))
def handle_account_info_command(message):
    user_id = message.from_user.id
    track_user_activity(message.from_user)
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    text, markup = format_user_account_info(
        user_id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        username=message.from_user.username
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "my_account_info")
@safe_callback
def handle_my_account_info_callback(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    text, markup = format_user_account_info(
        user_id,
        first_name=call.from_user.first_name,
        last_name=call.from_user.last_name,
        username=call.from_user.username
    )
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in ("💰 محفظتي", "/wallet", "محفظتي"))
def handle_my_wallet(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    name = message.from_user.first_name or "العميل"
    text, markup = format_wallet_display(user_id, name)
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "refresh_wallet")
@safe_callback
def handle_refresh_wallet(call):
    user_id = call.from_user.id
    name = call.from_user.first_name or "العميل"
    text, markup = format_wallet_display(user_id, name)
    safe_edit_message_text(call, text, reply_markup=markup)
    bot.answer_callback_query(call.id, "تم تحديث الرصيد!")

@bot.message_handler(func=lambda msg: msg.text == "📦 سجل مشترياتي")
def handle_my_orders(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_user_subscribed(user_id):
        send_force_join_message(message.chat.id)
        return
    with database_connection() as conn:
        orders = conn.execute("""
            SELECT * FROM payment_requests
            WHERE user_id = ? AND status IN ('awaiting_admin', 'accepted', 'rejected')
            ORDER BY id DESC LIMIT 15
        """, (user_id,)).fetchall()

    if not orders:
        bot.send_message(
            message.chat.id,
            "📦 <b>سجل مشترياتك فارغ حالياً.</b>\n\nتصفح المنتجات واختر باقتك المفضلة لبدء أول طلب!"
        )
        return

    text = "📋 <b>سجل طلباتك ومشترياتك السابقة:</b>\n\n"
    status_map = {
        "awaiting_admin": "⏳ قيد المراجعة والتأكيد",
        "accepted": "✅ تم القبول والتفعيل",
        "rejected": "❌ تم الرفض"
    }
    for ord_row in orders:
        st_text = status_map.get(ord_row["status"], ord_row["status"])
        email_line = f"📧 الإيميل: <code>{ord_row['customer_email']}</code>\n" if ord_row["customer_email"] else ""
        date_str = ord_row["created_at"][:16].replace("T", " ")
        text += (
            f"🔹 <b>طلب رقم:</b> <code>#{ord_row['order_ref'] or ord_row['id']}</code>\n"
            f"🛍 <b>المنتج:</b> {ord_row['product_key']} ({ord_row['package_name'] or 'باقة عامة'})\n"
            f"🔢 <b>الكمية:</b> {ord_row['quantity']} | 💰 <b>الإجمالي:</b> {ord_row['total_amount']}\n"
            f"{email_line}"
            f"📌 <b>الحالة:</b> <b>{st_text}</b>\n"
            f"📅 <b>التاريخ:</b> {date_str}\n"
            "---------------------------\n"
        )
    bot.send_message(message.chat.id, text)


# ================= Callback Query: Check Group Subscription =================
@bot.callback_query_handler(func=lambda c: c.data == "check_join")
def handle_check_join_callback(call):
    user_id = call.from_user.id
    track_user_activity(call.from_user)
    if is_user_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ تم التحقق بنجاح، مرحباً بك في المتجر!", show_alert=False)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        role = get_user_role(user_id)
        role_note = ""
        if role == "reseller":
            role_note = "💼 <b>حساب تاجر معتمد</b> (تُطبق لك أسعار خاصة بالتجار والمسوقين)\n\n"
        elif role == "friend":
            role_note = "🤝 <b>حساب صديق</b> (تُطبق لك أسعار خاصة بالأصدقاء)\n\n"
        elif role == "admin":
            role_note = "👑 <b>حساب المدير العام</b>\n\n"
        name = call.from_user.first_name or "عزيزنا العميل"
        welcome_text = (
            f"👋 أهلاً بك يا <b>{name}</b> في متجر الاشتراكات والذكاء الاصطناعي 🚀\n\n"
            + role_note +
            "✨ نوفر لك أفضل اشتراكات الذكاء الاصطناعي، التصميم، والمونتاج بأسعار منافسة وتسليم رسمي سريع ومضمون.\n\n"
            "اختر ما تريد من القائمة بالأسفل:"
        )
        bot.send_message(call.message.chat.id, welcome_text, reply_markup=get_main_menu_keyboard(user_id))
    else:
        bot.answer_callback_query(call.id, "❌ لم تقم بالانضمام بعد! يرجى الانضمام للجروب أولاً", show_alert=True)

# ================= Inline Callbacks: Product & Package Browsing =================
@bot.callback_query_handler(func=lambda c: c.data == "back_to_products")
@safe_callback
def handle_back_to_products_callback(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    role = get_user_role(user_id)
    badge = role_badge_display(role)
    safe_edit_message_text(
        call,
        f"🛍 <b>قائمة المنتجات المتاحة</b>\n"
        f"حسابك: <b>{badge}</b>\n\n"
        "اضغط على أي منتج لعرض باقاته وتفاصيل الشراء:",
        reply_markup=build_products_inline_menu(user_id)
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("prod_"))
@safe_callback
def handle_product_click(call):
    bot.answer_callback_query(call.id)
    try:
        user_id = call.from_user.id
        prod_key = call.data.replace("prod_", "")
        store = get_store_data() or {}
        prod = store.get(prod_key)
        if not prod:
            bot.answer_callback_query(call.id, "المنتج غير موجود!", show_alert=True)
            return

        if not prod.get("available", True):
            bot.answer_callback_query(call.id, "⚠️ عذراً، هذا المنتج غير متوفر حالياً!", show_alert=True)
            return

        # Check if product has subcategories (like ChatGPT)
        subcategories = prod.get("subcategories")
        if subcategories:
            desc = (
                f"<b>{prod['name']}</b>\n\n"
                f"{prod.get('description', '')}\n\n"
                "👇 اختر القسم المطلوب:"
            )
            markup = build_subcategories_or_packages_keyboard(prod_key, user_id)
            if prod.get("photo"):
                try:
                    bot.send_photo(call.message.chat.id, prod["photo"], caption=desc, reply_markup=markup)
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                    bot.answer_callback_query(call.id)
                    return
                except Exception as photo_err:
                    print(f"Error sending product photo for {prod_key}: {photo_err}")
                    traceback.print_exc()
            safe_edit_message_text(call, desc, reply_markup=markup)
            bot.answer_callback_query(call.id)
            return

        # Product has direct packages
        desc = (
            f"<b>{prod['name']}</b>\n\n"
            f"{prod.get('description', '')}\n\n"
            "👇 اختر الباقة المناسبة:"
        )
        markup = build_subcategories_or_packages_keyboard(prod_key, user_id)
        if prod.get("photo"):
            try:
                bot.send_photo(call.message.chat.id, prod["photo"], caption=desc, reply_markup=markup)
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id)
                return
            except Exception as photo_err:
                print(f"Error sending product photo for {prod_key}: {photo_err}")
                traceback.print_exc()
        safe_edit_message_text(call, desc, reply_markup=markup)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Critical error in handle_product_click: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ حدث خطأ في تحميل المنتج. يرجى المحاولة لاحقاً.", show_alert=True)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("subcat_"))
@safe_callback
def handle_subcategory_click(call):
    bot.answer_callback_query(call.id)
    try:
        user_id = call.from_user.id
        parts = call.data.split("_", 2)
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "خطأ في بيانات الطلب.", show_alert=True)
            return
        prod_key = parts[1]
        subcat_id = parts[2]
        store = get_store_data() or {}
        prod = store.get(prod_key)
        if not prod:
            bot.answer_callback_query(call.id, "المنتج غير موجود.")
            return

        subcategories = prod.get("subcategories") or []
        subcat = next((s for s in subcategories if s.get("id") == subcat_id), None)
        subcat_name = subcat.get("name", "الباقات المتاحة") if subcat else "الباقات المتاحة"
        subcat_desc = subcat.get("description", "") if subcat else ""

        text = f"<b>{prod.get('name', '')}</b> — <b>{subcat_name}</b>\n\n{subcat_desc}\n\n👇 اختر الباقة المطلوبة:"
        markup = build_subcategories_or_packages_keyboard(prod_key, user_id, selected_subcat=subcat_id)
        safe_edit_message_text(call, text, reply_markup=markup)
    except Exception as e:
        print(f"Error in handle_subcategory_click: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ حدث خطأ في تحميل الباقات.", show_alert=True)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("pkg_") and not c.data.startswith("pkg_unavailable_"))
@safe_callback
def handle_package_view(call):
    bot.answer_callback_query(call.id)
    try:
        user_id = call.from_user.id
        parts = call.data.split("_", 2)
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "خطأ في بيانات الباقة.", show_alert=True)
            return
        _, prod_key, pkg_id = parts
        store = get_store_data() or {}
        prod = store.get(prod_key)
        if not prod:
            bot.answer_callback_query(call.id, "المنتج غير موجود.")
            return

        packages = prod.get("packages") or []
        pkg = next((p for p in packages if p.get("id") == pkg_id), None)
        if not pkg:
            bot.answer_callback_query(call.id, "الباقة غير موجودة.")
            return

        price_info = get_package_price_for_user(pkg, user_id)
        photo_to_send = pkg.get("photo") or prod.get("photo")

        label = pkg.get("label", "باقة")
        extra_info = ""
        if prod_key == "chatgpt" and pkg_id == "biz_remaining":
            days, end_date = get_chatgpt_business_info()
            extra_info = f"\n📅 التجديد يوم 23 من كل شهر\n⏳ متبقي في الدورة الحالية: {days} يوم (حتى {end_date})"

        email_notice = "\n📧 <i>تنويه: هذه الباقة تتطلب إدخال بريدك الإلكتروني للتفعيل المباشر.</i>" if pkg.get("requires_email") else ""

        role = get_user_role(user_id)
        cashback_amt = get_package_cashback(pkg, user_id=user_id) if role == "customer" else Decimal("0")
        cashback_notice = f"\n🎁 <b>كاش باك فوري:</b> {format_currency(cashback_amt)} يُضاف لمحفظتك بعد تأكيد الطلب!\n" if (cashback_amt > Decimal("0") and role == "customer") else ""

        pkg_desc = pkg.get("desc") or pkg.get("description") or ""

        caption = (
            f"🛍 <b>{prod.get('name', '')}</b>\n"
            f"📦 الباقة: <b>{label}</b>\n\n"
            f"💰 <b>{price_info.get('display', '')}</b>\n"
            f"{extra_info}"
            f"{cashback_notice}"
            f"📝 <b>الوصف والضمان:</b>\n{pkg_desc}\n"
            f"{email_notice}"
        )

        subcat_id = pkg.get("subcategory")
        back_cb = f"subcat_{prod_key}_{subcat_id}" if subcat_id else f"prod_{prod_key}"

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💳 شراء الآن", callback_data=f"buy_{prod_key}_{pkg_id}"),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=back_cb)
        )

        if photo_to_send:
            try:
                bot.send_photo(call.message.chat.id, photo_to_send, caption=caption, reply_markup=markup)
                bot.delete_message(call.message.chat.id, call.message.message_id)
                return
            except Exception as photo_err:
                print(f"Error sending package photo for {prod_key}/{pkg_id}: {photo_err}")
                traceback.print_exc()

        safe_edit_message_text(call, caption, reply_markup=markup)
    except Exception as e:
        print(f"Critical error in handle_package_view: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ حدث خطأ في تحميل تفاصيل الباقة.", show_alert=True)
        except Exception:
            pass

# ================= Purchase Flow =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
@safe_callback
def handle_buy_click(call):
    user_id = call.from_user.id
    parts = call.data.split("_", 2)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "خطأ في بيانات الطلب.", show_alert=True)
        return
    _, prod_key, pkg_id = parts
    store = get_store_data() or {}
    prod = store.get(prod_key)
    if not prod or not prod.get("available", True):
        bot.answer_callback_query(call.id, "⚠️ عذراً، هذا المنتج غير متوفر حالياً!", show_alert=True)
        return
    pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None)
    if not pkg or not pkg.get("available", True):
        bot.answer_callback_query(call.id, "⚠️ عذراً، هذه الباقة غير متوفرة حالياً!", show_alert=True)
        return
    state = start_new_order(user_id, prod_key, pkg_id)
    if not state:
        bot.answer_callback_query(call.id, "تعذر بدء الطلب، يرجى المحاولة لاحقاً.", show_alert=True)
        return

    text = (
        f"🛒 <b>طلب جديد: #{state['order_ref']}</b>\n\n"
        f"📦 المنتج: <b>{state['package_name']}</b>\n"
        f"💰 سعر القطعة: <b>{state['unit_price']}</b>\n\n"
        "👇 حدد الكمية المطلوبة بالضغط على الأزرار:"
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=build_quantity_keyboard(state["request_id"])
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_order_"))
@safe_callback
def handle_cancel_order(call):
    user_id = call.from_user.id
    request_id = int(call.data.replace("cancel_order_", ""))
    with database_connection() as conn:
        conn.execute("UPDATE payment_requests SET status = 'cancelled', updated_at = ? WHERE id = ?", (utc_now(), request_id))
    clear_db_user_state(user_id)
    bot.edit_message_text("❌ تم إلغاء الطلب بنجاح. يمكنك بدء طلب جديد في أي وقت.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id, "تم الإلغاء")

@bot.callback_query_handler(func=lambda c: c.data.startswith("qty_"))
@safe_callback
def handle_quantity_click(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    request_id = int(parts[1])
    qty_choice = parts[2]

    state = user_states.get(user_id)
    if not state or state.get("request_id") != request_id:
        bot.answer_callback_query(call.id, "انتهت صلاحية هذه الجلسة، ابدأ من جديد.", show_alert=True)
        return

    if qty_choice == "custom":
        state["step"] = "awaiting_custom_qty"
        save_db_user_state(user_id, state)
        bot.send_message(call.message.chat.id, "🔢 اكتب الكمية المطلوبة بالأرقام (مثال: 4 أو 15):")
        bot.answer_callback_query(call.id)
        return

    quantity = int(qty_choice)
    proceed_with_quantity(user_id, state, quantity, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def proceed_with_quantity(user_id, state, quantity, chat_id, message_id=None):
    unit_amt = Decimal(str(state["unit_amount"]))
    total = unit_amt * Decimal(str(quantity))
    state["quantity"] = quantity
    state["total_amount"] = float(total)
    user_role = get_user_role(user_id)

    # Exclude reseller and friend from coupon flow (they already have special discounted tier pricing)
    if user_role in ("reseller", "friend"):
        state["step"] = "awaiting_wallet"
        save_db_user_state(user_id, state)
        proceed_to_payment_or_wallet(user_id, state, chat_id, message_id)
        return

    state["step"] = "awaiting_coupon"
    save_db_user_state(user_id, state)

    text = (
        f"✅ الكمية المختارة: <b>{quantity}</b>\n"
        f"💵 المجموع الحالي: <b>{format_currency(total)}</b>\n\n"
        "🎟 <b>هل لديك كود خصم أو كوبون ترغب في استخدامه؟</b>"
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=build_coupon_decision_keyboard(state["request_id"]))
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=build_coupon_decision_keyboard(state["request_id"]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("use_coupon_"))
@safe_callback
def handle_use_coupon_click(call):
    user_id = call.from_user.id
    user_role = get_user_role(user_id)
    request_id = int(call.data.replace("use_coupon_", ""))
    state = user_states.get(user_id)
    if not state or state.get("request_id") != request_id:
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return

    if user_role in ("reseller", "friend"):
        bot.answer_callback_query(call.id, "⚠️ عذراً، أكواد الخصم مخصصة للعملاء فقط (حسابك يتمتع بأسعار خاصة بالفعل)", show_alert=True)
        proceed_to_payment_or_wallet(user_id, state, call.message.chat.id, call.message.message_id)
        return

    state["step"] = "awaiting_coupon_code"
    save_db_user_state(user_id, state)
    bot.send_message(call.message.chat.id, "🎟 أرسل كود الخصم الآن في رسالة:")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("skip_coupon_"))
@safe_callback
def handle_skip_coupon_click(call):
    user_id = call.from_user.id
    request_id = int(call.data.replace("skip_coupon_", ""))
    state = user_states.get(user_id)
    if not state or state.get("request_id") != request_id:
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return

    proceed_to_payment_or_wallet(user_id, state, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def proceed_to_payment_or_wallet(user_id, state, chat_id, message_id=None):
    avail_wallet = get_user_available_wallet_balance(user_id, current_request_id=state.get("request_id"))
    current_total = Decimal(str(state.get("total_amount", 0)))

    if avail_wallet > Decimal("0") and current_total > Decimal("0"):
        usable = min(avail_wallet, current_total)
        state["step"] = "awaiting_wallet"
        save_db_user_state(user_id, state)

        text = (
            f"💰 <b>رصيد المحفظة متاح:</b> لديك <b>{format_currency(avail_wallet)}</b> في محفظتك كاش باك!\n\n"
            f"💵 إجمالي الفاتورة الحالي: <b>{format_currency(current_total)}</b>\n\n"
            f"هل ترغب في استخدام رصيدك لخصم <b>{format_currency(usable)}</b> من قيمة هذا الطلب؟"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(f"✅ نعم، استخدام {format_currency(usable)} من الرصيد", callback_data=f"wallet_yes_{state['request_id']}"),
            types.InlineKeyboardButton("⏩ لا، المتابعة بالدفع المباشر", callback_data=f"wallet_skip_{state['request_id']}"),
            types.InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"cancel_order_{state['request_id']}")
        )
        if message_id:
            try:
                bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
                return
            except Exception:
                pass
        bot.send_message(chat_id, text, reply_markup=markup)
    else:
        show_payment_instructions(user_id, state, chat_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet_yes_"))
@safe_callback
def handle_wallet_yes(call):
    user_id = call.from_user.id
    request_id = int(call.data.replace("wallet_yes_", ""))
    state = user_states.get(user_id)
    if not state or state.get("request_id") != request_id:
        bot.answer_callback_query(call.id, "انتهت صلاحية الجلسة.")
        return

    avail_wallet = get_user_available_wallet_balance(user_id, current_request_id=request_id)
    current_total = Decimal(str(state.get("total_amount", 0)))
    usable = min(avail_wallet, current_total)
    new_total = max(Decimal("0"), current_total - usable)

    state["wallet_used"] = float(usable)
    state["total_amount"] = float(new_total)
    save_db_user_state(user_id, state)

    with database_connection() as conn:
        conn.execute("""
            UPDATE payment_requests
            SET wallet_used = ?, total_amount = ?, updated_at = ?
            WHERE id = ?
        """, (float(usable), format_currency(new_total), utc_now(), request_id))

    bot.answer_callback_query(call.id, f"تم خصم {format_currency(usable)} من الطلب!")
    try:
        bot.edit_message_text(
            f"✅ <b>تم تطبيق خصم المحفظة بنجاح! (-{format_currency(usable)})</b>\n"
            f"💰 المبلغ المتبقي المطلوب تحويله: <b>{format_currency(new_total)}</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    except Exception:
        pass

    show_payment_instructions(user_id, state, call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet_skip_"))
@safe_callback
def handle_wallet_skip(call):
    user_id = call.from_user.id
    request_id = int(call.data.replace("wallet_skip_", ""))
    state = user_states.get(user_id)
    if not state or state.get("request_id") != request_id:
        bot.answer_callback_query(call.id, "انتهت صلاحية الجلسة.")
        return

    state["wallet_used"] = 0.0
    save_db_user_state(user_id, state)
    with database_connection() as conn:
        conn.execute("UPDATE payment_requests SET wallet_used = 0.0, updated_at = ? WHERE id = ?", (utc_now(), request_id))

    bot.answer_callback_query(call.id, "المتابعة بالدفع المباشر.")
    show_payment_instructions(user_id, state, call.message.chat.id)

def apply_coupon_to_order(user_id, state, code, chat_id):
    user_role = get_user_role(user_id)
    if user_role in ("reseller", "friend"):
        bot.send_message(chat_id, "⚠️ عذراً، أكواد الخصم مخصصة للعملاء فقط (حسابك يتمتع بأسعار خاصة بالفعل)")
        proceed_to_payment_or_wallet(user_id, state, chat_id)
        return

    coupons = get_coupons()
    code_upper = code.strip().upper()
    coupon = coupons.get(code_upper)

    if not coupon or not coupon.get("active", True):
        bot.send_message(chat_id, "⚠️ كود الخصم غير صالح أو منتهي الصلاحية.\nيمكنك كتابة كود آخر أو إرسال /skip للمتابعة بدون كود.")
        return

    max_uses = coupon.get("max_uses", 999999)
    used_count = coupon.get("used_count", 0)
    if used_count >= max_uses:
        bot.send_message(chat_id, "⚠️ تم الوصول للحد الأقصى لاستخدام هذا الكود.\nأرسل كود آخر أو /skip للمتابعة.")
        return

    applicable_products = coupon.get("applicable_products")
    if applicable_products and state.get("product_key") not in applicable_products:
        bot.send_message(chat_id, "⚠️ عذراً، هذا الكوبون غير متاح لهذا المنتج!\nأرسل كود آخر أو /skip للمتابعة.")
        return

    # Check tier-level restrictions
    applicable_tiers = coupon.get("applicable_tiers")
    if applicable_tiers:
        current_tier_key = f"{state.get('product_key')}_{state.get('package_key')}"
        if current_tier_key not in applicable_tiers:
            bot.send_message(chat_id, "⚠️ عذراً، هذا الكوبون غير متاح لهذه الباقة!\nأرسل كود آخر أو /skip للمتابعة.")
            return

    # Calculate discount
    pkg_key = state.get("package_key")
    pkg_discounts = coupon.get("package_discounts", {})
    fixed_discount = Decimal(str(coupon.get("fixed_discount", 0)))
    
    discount = Decimal("0")
    if pkg_key and pkg_key in pkg_discounts:
        discount = Decimal(str(pkg_discounts[pkg_key])) * Decimal(str(state["quantity"]))
    elif fixed_discount > 0:
        discount = fixed_discount * Decimal(str(state["quantity"]))
    else:
        discount = Decimal("20") * Decimal(str(state["quantity"]))

    current_total = Decimal(str(state["total_amount"]))
    final_total = max(Decimal("0"), current_total - discount)

    state["discount_amount"] = float(discount)
    state["coupon_code"] = code_upper
    state["total_amount"] = float(final_total)

    bot.send_message(
        chat_id,
        f"🎉 <b>تم تطبيق كود الخصم بنجاح! ({code_upper})</b>\n"
        f"🏷 برعاية: <b>{coupon.get('influencer', 'عرض ترويجي')}</b>\n"
        f"✂️ قيمة الخصم: <b>-{format_currency(discount)}</b>\n"
        f"💵 الإجمالي بعد الخصم: <b>{format_currency(final_total)}</b>"
    )
    proceed_to_payment_or_wallet(user_id, state, chat_id)

def show_payment_instructions(user_id, state, chat_id):
    total_amt = Decimal(str(state.get("total_amount", 0)))
    total_str = format_currency(total_amt)
    discount_line = f"✂️ الخصم المطبق (كود): {format_currency(Decimal(str(state['discount_amount'])))} (كود: {state['coupon_code']})\n" if state.get("coupon_code") else ""
    wallet_line = f"🪙 الخصم من المحفظة: -{format_currency(Decimal(str(state['wallet_used'])))}\n" if state.get("wallet_used") else ""

    if total_amt <= Decimal("0"):
        state["step"] = "awaiting_phone"
        save_db_user_state(user_id, state)
        with database_connection() as conn:
            conn.execute("UPDATE payment_requests SET step = 'awaiting_phone', updated_at = ? WHERE id = ?", (utc_now(), state["request_id"]))
        instructions = (
            f"🎉 <b>تم تغطية كامل قيمة الطلب من رصيد محفظتك!</b>\n\n"
            f"🔢 <b>رقم الطلب:</b> <code>#{state['order_ref']}</code>\n"
            f"🛍 <b>المنتج:</b> <b>{state['package_name']}</b>\n"
            f"🔢 <b>الكمية:</b> <b>{state['quantity']}</b>\n"
            f"{discount_line}"
            f"{wallet_line}"
            f"💰 <b>المبلغ المطلوب تحويله:</b> <b>0ج</b>\n\n"
            "📱 <b>الخطوة التالية:</b>\n"
            "يرجى إرسال <b>رقم هاتفك</b> للتواصل ومتابعة تسليم وتفعيل الطلب:"
        )
        bot.send_message(chat_id, instructions)
        return

    state["step"] = "awaiting_receipt"
    save_db_user_state(user_id, state)

    instructions = (
        f"💳 <b>بيانات الدفع والتحويل | طلب رقم #{state['order_ref']}</b>\n\n"
        f"🛍 المنتج: <b>{state['package_name']}</b>\n"
        f"🔢 الكمية: <b>{state['quantity']}</b>\n"
        f"{discount_line}"
        f"{wallet_line}"
        f"💰 <b>المبلغ المطلوب تحويله: {total_str}</b>\n\n"
        f"📲 <b>رقم فودافون كاش للتحويل:</b>\n"
        f"<code>{VODAFONE_CASH}</code>\n"
        "<i>(اضغط على الرقم لنسخه مباشرة)</i>\n\n"
        "📸 <b>الخطوة التالية:</b>\n"
        "بعد إتمام التحويل، يرجى إرسال <b>صورة إيصال التحويل (Screenshot)</b> هنا مباشرة."
    )
    bot.send_message(chat_id, instructions)

# ================= Receipt & Information Collection Handlers =================
@bot.message_handler(content_types=["photo"])
def handle_receipt_photo(message):
    user_id = message.from_user.id

    # Admin broadcast photo
    admin_state = admin_action_states.get(user_id)
    if admin_state and admin_state.get("action") in ("broadcast_text", "broadcast_photo") and is_admin(user_id):
        admin_action_states.pop(user_id, None)
        photo_id = message.photo[-1].file_id
        caption = message.caption or ""

        # Get all user IDs from database
        user_ids = set()
        with database_connection() as conn:
            rows = conn.execute("SELECT DISTINCT user_id FROM payment_requests").fetchall()
            for row in rows:
                user_ids.add(row["user_id"])
        # Also add from user_roles
        roles = get_user_roles()
        for uid in roles.keys():
            if uid.isdigit():
                user_ids.add(int(uid))

        sent_count = 0
        failed_count = 0
        for uid in user_ids:
            try:
                bot.send_photo(uid, photo_id, caption=caption, parse_mode="HTML")
                sent_count += 1
            except Exception:
                failed_count += 1

        bot.reply_to(
            message,
            f"📊 <b>تقرير الإذاعة الجماعية (صورة)</b>\n\n"
            f"✅ تم الإرسال بنجاح: <b>{sent_count}</b> مستخدم\n"
            f"❌ فشل الإرسال: <b>{failed_count}</b> مستخدم\n"
            f"👥 إجمالي المحاولات: <b>{sent_count + failed_count}</b>"
        )
        return

    # Admin new product photo upload
    if admin_state and admin_state.get("action") == "add_product_photo" and is_admin(user_id):
        product_name = admin_state.get("product_name", "منتج جديد")
        product_key = admin_state.get("product_key", "new_product")
        description = admin_state.get("description", "")
        admin_action_states.pop(user_id, None)

        photo_id = message.photo[-1].file_id
        store = get_store_data()
        store[product_key] = {
            "name": product_name,
            "available": True,
            "photo": photo_id,
            "description": description,
            "packages": []
        }
        update_store_data(store)

        bot.reply_to(
            message,
            f"✅ تم إضافة المنتج <b>{product_name}</b> بنجاح مع الصورة!\n\n"
            f"🔑 المفتاح: <code>{product_key}</code>\n"
            f"🖼️ الصورة: تم حفظها\n"
            f"📦 الباقات: 0 (يمكنك إضافة باقات لاحقاً)\n\n"
            "💡 استخدم <b>➕ إضافة باقة جديدة</b> لإضافة باقات لهذا المنتج."
        )
        return

    # Admin product photo upload (update existing)
    if admin_state and admin_state.get("action") == "update_product_photo" and is_admin(user_id):
        prod_key = admin_state["prod_key"]
        admin_action_states.pop(user_id, None)

        photo_id = message.photo[-1].file_id
        store = get_store_data()
        prod = store.get(prod_key)
        if not prod:
            bot.reply_to(message, "⚠️ المنتج غير موجود.")
            return

        prod["photo"] = photo_id
        # Also update photo for all packages that don't have their own photo
        for pkg in prod.get("packages", []):
            if not pkg.get("photo"):
                pkg["photo"] = photo_id
        update_store_data(store)

        bot.reply_to(
            message,
            f"✅ تم تحديث صورة المنتج <b>{prod['name']}</b> بنجاح!\n\n"
            f"🖼️ سيتم عرض هذه الصورة عند تصفح المنتج وباقاته."
        )
        return

    state = user_states.get(user_id)
    if not state or state.get("step") != "awaiting_receipt":
        return

    photo_id = message.photo[-1].file_id
    state["receipt_file_id"] = photo_id
    state["step"] = "awaiting_phone"
    save_db_user_state(user_id, state)

    with database_connection() as conn:
        conn.execute("""
            UPDATE payment_requests
            SET receipt_file_id = ?, status = 'awaiting_phone', step = 'awaiting_phone', updated_at = ?
            WHERE id = ?
        """, (photo_id, utc_now(), state["request_id"]))

    bot.reply_to(
        message,
        "✅ <b>تم استلام صورة الإيصال بنجاح.</b>\n\n"
        "📱 الآن يرجى كتابة وإرسال <b>رقم المحفظة / الهاتف</b> الذي قمت بالتحويل منه:"
    )

@bot.message_handler(content_types=["text"])
def handle_text_messages(message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    if text.startswith("/wallet"):
        handle_my_wallet(message)
        return

    # Admin command intercept
    if text.startswith("/admin"):
        handle_admin_panel(message)
        return

    if text.startswith("/cancel"):
        if user_id in user_states:
            clear_db_user_state(user_id)
            bot.reply_to(message, "تم إلغاء طلبك الحالي بنجاح.")
        if user_id in admin_action_states:
            admin_action_states.pop(user_id, None)
            bot.reply_to(message, "تم إلغاء إجراء الإدارة.")
        return

    if user_id in admin_action_states:
        handle_admin_text_inputs(message)
        return

    state = user_states.get(user_id)
    if not state:
        return

    step = state.get("step")

    # Step: custom quantity
    if step == "awaiting_custom_qty":
        clean_num = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        if not clean_num.isdigit() or int(clean_num) <= 0 or int(clean_num) > 10000:
            bot.reply_to(message, "⚠️ يرجى كتابة رقم صحيح وموجب بين 1 و 10000:")
            return
        proceed_with_quantity(user_id, state, int(clean_num), message.chat.id)
        return

    # Step: coupon code
    if step == "awaiting_coupon_code":
        if text.startswith("/skip"):
            show_payment_instructions(user_id, state, message.chat.id)
            return
        apply_coupon_to_order(user_id, state, text, message.chat.id)
        return

    # Step: receipt awaiting reminder
    if step == "awaiting_receipt":
        bot.reply_to(message, "⚠️ يرجى إرسال <b>صورة إيصال التحويل (Photo)</b> أولاً قبل إرسال النصوص.")
        return

    # Step: phone number
    if step == "awaiting_phone":
        clean_phone = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace(" ", "").replace("-", "")
        if len(clean_phone) < 8 or not re.search(r"\d", clean_phone):
            bot.reply_to(message, "⚠️ يرجى إدخال رقم هاتف صحيح تم التحويل منه:")
            return

        state["phone_number"] = clean_phone
        
        # Check if product requires email
        if state.get("requires_email"):
            state["step"] = "awaiting_email"
            save_db_user_state(user_id, state)
            with database_connection() as conn:
                conn.execute("""
                    UPDATE payment_requests
                    SET phone_number = ?, status = 'awaiting_email', step = 'awaiting_email', updated_at = ?
                    WHERE id = ?
                """, (clean_phone, utc_now(), state["request_id"]))

            bot.reply_to(
                message,
                "✅ <b>تم استلام رقم الهاتف.</b>\n\n"
                "📧 <b>خطوة إجبارية أخيرة:</b>\n"
                "هذا المنتج يعتمد على دعوة أو تفعيل شخصي.\n"
                "يرجى كتابة وإرسال <b>البريد الإلكتروني (Gmail)</b> المراد التفعيل عليه بدقة:"
            )
            return
        else:
            finalize_order_submission(message, state, customer_email=None)
            return

    # Step: email for email-based products (Gemini, Canva, etc.)
    if step == "awaiting_email":
        email_clean = text.strip()
        email_regex = r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_regex, email_clean):
            bot.reply_to(message, "⚠️ صيغة البريد الإلكتروني غير صحيحة.\nيرجى كتابة بريد إلكتروني صالح مثل: <code>example@gmail.com</code>")
            return
        finalize_order_submission(message, state, customer_email=email_clean)
        return

def finalize_order_submission(message, state, customer_email=None):
    user_id = message.from_user.id
    request_id = state["request_id"]
    order_ref = state["order_ref"]
    phone = state.get("phone_number", "")
    customer = message.from_user
    coupon_code = state.get("coupon_code")
    discount_amount = state.get("discount_amount", 0)
    total_amount = state.get("total_amount", 0)

    # Update coupons usage count if coupon applied
    if coupon_code:
        coupons = get_coupons()
        if coupon_code in coupons:
            coupons[coupon_code]["used_count"] = coupons[coupon_code].get("used_count", 0) + 1
            if "usage_history" not in coupons[coupon_code]:
                coupons[coupon_code]["usage_history"] = []
            coupons[coupon_code]["usage_history"].append({
                "order_ref": order_ref,
                "user_id": user_id,
                "username": customer.username or "",
                "total": total_amount,
                "date": utc_now()
            })
            update_coupons(coupons)

    user_role = get_user_role(user_id)
    wallet_used = state.get("wallet_used", 0.0)
    cashback_unit = float(state.get("cashback_unit", 0)) if user_role == "customer" else 0.0
    cashback_earned = (cashback_unit * state.get("quantity", 1)) if user_role == "customer" else 0.0

    # Save to SQLite
    with database_connection() as conn:
        conn.execute("""
            UPDATE payment_requests
            SET status = 'awaiting_admin', step = 'awaiting_admin',
                phone_number = ?, customer_email = ?,
                customer_username = ?, customer_first_name = ?, customer_last_name = ?,
                quantity = ?, discount_amount = ?, coupon_code = ?,
                total_amount = ?, wallet_used = ?, cashback_earned = ?, updated_at = ?
            WHERE id = ?
        """, (
            phone, customer_email,
            customer.username or "", customer.first_name or "", customer.last_name or "",
            state["quantity"], format_currency(discount_amount), coupon_code,
            format_currency(total_amount), float(wallet_used), float(cashback_earned), utc_now(), request_id
        ))

    clear_db_user_state(user_id)

    # 1. إرسال تأكيد فوري للعميل مع تنبيه بصوت واهتزاز
    confirm_text = (
        "🎉 <b>تم استلام طلبك وإشعار الإدارة فوراً!</b> 🔔\n\n"
        f"🔢 <b>رقم الطلب المرجعي:</b> <code>#{order_ref}</code>\n"
        f"🛍 <b>المنتج:</b> {state['package_name']}\n"
        f"💰 <b>الإجمالي:</b> {format_currency(total_amount)}\n"
        + (f"📧 <b>الإيميل المرفق:</b> <code>{customer_email}</code>\n" if customer_email else "") +
        "\n⚡️ تم إرسال تنبيه عاجل لفريق المراجعة، وسيصلك إشعار لحظي هنا فور تأكيد وتفعيل اشتراكك!"
    )
    send_instant_notification(
        message.chat.id,
        confirm_text,
        notification_type="customer_order_submitted",
        loud=True
    )

    # 2. إرسال تنبيه عاجل للأدمن مع تفاصيل الإيصال وأزرار القبول والرفض
    notify_admins_new_order(request_id)

# ================= Notification Engine =================
def log_notification(user_id, notification_type, content, status):
    """تسجيل الإشعار في قاعدة البيانات لمتابعة الإحصائيات وسجل التنبيهات"""
    try:
        with database_connection() as conn:
            conn.execute("""
                INSERT INTO notifications_log (user_id, notification_type, content, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, notification_type, content[:500], status, utc_now()))
    except Exception as e:
        print(f"Error logging notification: {e}")

def get_all_admin_ids():
    """جلب جميع معرفات المدراء المسجلين لإرسال التنبيهات لهم"""
    admins = {ADMIN_ID}
    for uid_str in get_admins():
        if uid_str.isdigit():
            admins.add(int(uid_str))
    for uid_str, info in get_user_roles().items():
        if info.get("role") == "admin" and uid_str.isdigit():
            admins.add(int(uid_str))
    return sorted(list(admins))

def send_instant_notification(chat_id, text, reply_markup=None, photo_id=None, notification_type="general", loud=True):
    """
    إرسال تنبيه فوري عالي الأولوية باستخدام دوال تيليجرام
    مع تفعيل الصوت والاهتزاز صراحة (disable_notification=False)
    """
    try:
        if photo_id:
            msg = bot.send_photo(
                chat_id,
                photo_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_notification=not loud
            )
        else:
            msg = bot.send_message(
                chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_notification=not loud
            )
        log_notification(chat_id, notification_type, text, "delivered")
        return msg
    except Exception as e:
        print(f"Error sending notification to {chat_id}: {e}")
        log_notification(chat_id, notification_type, text, f"failed: {e}")
        return None

def notify_admins_new_order(request_id):
    """
    تنبيه فوري لجميع المدراء عند استلام طلب شراء جديد مع صورة الإيصال وأزرار الإجراء
    """
    with database_connection() as conn:
        row = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        return

    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ قبول وتأكيد", callback_data=f"adm_acc_{request_id}"),
        types.InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_rej_{request_id}")
    )
    admin_markup.add(
        types.InlineKeyboardButton("👤 بيانات العميل", callback_data=f"adm_cust_{row['user_id']}"),
        types.InlineKeyboardButton("💬 مراسلة العميل", url=f"tg://user?id={row['user_id']}")
    )

    alert_caption = (
        "🚨 <b>تنبيه فوري: طلب شراء جديد وارد الآن!</b> 🔔\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>رقم الطلب:</b> <code>#{row['order_ref']}</code>\n"
        f"👤 <b>العميل:</b> {row['customer_first_name']} {row['customer_last_name'] or ''} (@{row['customer_username'] or 'بدون'})\n"
        f"🆔 <b>Telegram ID:</b> <code>{row['user_id']}</code>\n"
        f"🎖 <b>الرتبة:</b> {role_badge_display(row['user_role'])}\n"
        f"🛍 <b>المنتج:</b> {row['product_key']} ({row['package_name']})\n"
        f"🔢 <b>الكمية:</b> {row['quantity']}\n"
        f"💵 <b>سعر القطعة:</b> {row['unit_price']}\n"
        + (f"🎟 <b>الكوبون:</b> {row['coupon_code']} (خصم: {row['discount_amount']})\n" if row['coupon_code'] else "")
        + (f"🪙 <b>خصم المحفظة (معلق):</b> {format_currency(Decimal(str(row['wallet_used'])))}\n" if row['wallet_used'] and float(row['wallet_used']) > 0 else "")
        + (f"🎁 <b>كاش باك مؤهل عند القبول:</b> {format_currency(Decimal(str(row['cashback_earned'])))}\n" if row['cashback_earned'] and float(row['cashback_earned']) > 0 else "")
        + f"💰 <b>الإجمالي المطلوب تحويله:</b> <b>{row['total_amount']}</b>\n"
        f"📱 <b>رقم المحول منه:</b> <code>{row['phone_number']}</code>\n"
        + (f"📧 <b>إيميل التفعيل:</b> <code>{row['customer_email']}</code>\n" if row['customer_email'] else "") +
        f"⏰ <b>التوقيت:</b> {row['created_at'][:16].replace('T', ' ')}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚡️ <i>راجع إيصال التحويل المرفق واضغط على أحد الأزرار لاتخاذ الإجراء فوراً:</i>"
    )

    admin_ids = get_all_admin_ids()
    for admin_id in admin_ids:
        msg = send_instant_notification(
            admin_id,
            alert_caption,
            reply_markup=admin_markup,
            photo_id=row["receipt_file_id"],
            notification_type="admin_new_order_alert",
            loud=True
        )
        if msg and admin_id == ADMIN_ID:
            with database_connection() as conn:
                conn.execute(
                    "UPDATE payment_requests SET admin_chat_id = ?, admin_message_id = ? WHERE id = ?",
                    (admin_id, msg.message_id, request_id)
                )

def notify_customer_status_change(order_row, new_status, reason=None):
    """
    إرسال تنبيه فوري مصحوب بصوت للعميل عند قبول أو رفض طلبه
    """
    user_id = order_row["user_id"]
    order_ref = order_row["order_ref"]
    pkg_name = order_row["package_name"]
    total = order_row["total_amount"]

    if new_status == "accepted":
        wallet_notes = ""
        wallet_used = Decimal(str(order_row["wallet_used"] or 0))
        cashback_earned = Decimal(str(order_row["cashback_earned"] or 0))
        if wallet_used > Decimal("0"):
            wallet_notes += f"\n🪙 <b>خصم المحفظة المطبق:</b> -{format_currency(wallet_used)}"
        user_role = order_row["user_role"] if "user_role" in order_row.keys() else get_user_role(user_id)
        if cashback_earned > Decimal("0") and user_role == "customer":
            wallet_notes += f"\n🎁 <b>كاش باك مكتسب:</b> +{format_currency(cashback_earned)} (تم إيداعه في محفظتك!)"
        current_wallet_bal = get_user_wallet_balance(user_id)
        wallet_notes += f"\n💰 <b>رصيد محفظتك الحالي:</b> <b>{format_currency(current_wallet_bal)}</b>"

        customer_msg = (
            "🎉 <b>تنبيه فوري: تم قبول وتأكيد طلبك بنجاح!</b> ✅\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 <b>رقم الطلب:</b> <code>#{order_ref}</code>\n"
            f"🛍 <b>المنتج:</b> <b>{pkg_name}</b>\n"
            f"💰 <b>المبلغ المدفوع:</b> {total}\n"
            + (f"📧 <b>الإيميل المعتمد:</b> <code>{order_row['customer_email']}</code>\n" if order_row['customer_email'] else "") +
            "📌 <b>الحالة:</b> <b>✅ تم القبول والتفعيل</b>\n"
            + wallet_notes + "\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🚀 سيتم تسليمك تفاصيل الحساب أو إرسال الدعوة لبريدك حالاً.\n"
            "❤️ شكراً لثقتك بمتجرنا!"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💬 الدعم الفني", url="https://t.me/gopro_store_team")
        )
        send_instant_notification(
            user_id,
            customer_msg,
            reply_markup=markup,
            notification_type="customer_order_accepted",
            loud=True
        )

    elif new_status == "rejected":
        wallet_rel_note = ""
        wallet_used = Decimal(str(order_row["wallet_used"] or 0))
        if wallet_used > Decimal("0"):
            wallet_rel_note = f"\n🪙 <b>تنويه:</b> تم إلغاء حجز رصيد المحفظة ({format_currency(wallet_used)}) وهو متاح في محفظتك بالكامل للاستخدام.\n"

        customer_msg = (
            "⚠️ <b>تنبيه فوري: تحديث بشأن طلبك رقم #{order_ref}</b> ❌\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🛍 <b>المنتج:</b> {pkg_name}\n"
            "📌 <b>الحالة:</b> <b>نعتذر، لم يتم تأكيد هذا الطلب</b>\n\n"
            f"📝 <b>السبب:</b> {reason or 'تعذر التحقق من وصول مبلغ التحويل أو مطابقة بيانات الإيصال المرسل.'}\n"
            + wallet_rel_note +
            "━━━━━━━━━━━━━━━━━━━\n"
            "💬 إذا قمت بالتحويل بالفعل، يرجى التواصل مع فريق الدعم الفني للمراجعة الفورية:"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("💬 مراسلة الدعم الفني", url="https://t.me/gopro_store_team")
        )
        send_instant_notification(
            user_id,
            customer_msg,
            reply_markup=markup,
            notification_type="customer_order_rejected",
            loud=True
        )

def record_coupon_usage_on_acceptance(order_row):
    """
    تحديث سجلات واستخدام الكوبونات تلقائياً في قاعدة البيانات وفي coupons.json
    فور قبول واعتماد الطلب من الأدمن، مع حفظ كافة تفاصيل العملية.
    """
    code = order_row["coupon_code"]
    if not code:
        return
    code_upper = code.strip().upper()
    coupons = get_coupons()
    if code_upper not in coupons:
        return

    final_num = parse_price_amount(order_row["total_amount"]) or Decimal("0")
    discount_num = parse_price_amount(order_row["discount_amount"]) or Decimal("0")
    original_num = final_num + discount_num

    cust_name = f"{order_row['customer_first_name']} {order_row['customer_last_name'] or ''}".strip() or "عميل"
    pkg_display = f"{order_row['product_key']} — {order_row['package_name'] or 'باقة عامة'}"

    usage_entry = {
        "order_ref": order_row["order_ref"],
        "user_id": order_row["user_id"],
        "username": order_row["customer_username"] or "",
        "customer_name": cust_name,
        "product_name": order_row["product_key"],
        "package_name": order_row["package_name"] or order_row["product_key"],
        "original_amount": format_currency(original_num),
        "discount_amount": order_row["discount_amount"] or format_currency(discount_num),
        "final_amount": order_row["total_amount"],
        "date": utc_now()[:16].replace("T", " ")
    }

    # تحديث ملف coupons.json
    if "usage_history" not in coupons[code_upper]:
        coupons[code_upper]["usage_history"] = []

    # تجنب التكرار لنفس الطلب
    if not any(u.get("order_ref") == order_row["order_ref"] for u in coupons[code_upper]["usage_history"]):
        coupons[code_upper]["usage_history"].append(usage_entry)
        coupons[code_upper]["used_count"] = len(coupons[code_upper]["usage_history"])
        update_coupons(coupons)

    # تحديث جدول coupon_usages في SQLite
    try:
        with database_connection() as conn:
            exists = conn.execute("SELECT id FROM coupon_usages WHERE order_ref = ?", (order_row["order_ref"],)).fetchone()
            if not exists:
                conn.execute("""
                    INSERT INTO coupon_usages (
                        coupon_code, order_ref, user_id, username, customer_name,
                        product_name, package_name, original_amount, discount_amount,
                        final_amount, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code_upper,
                    order_row["order_ref"],
                    order_row["user_id"],
                    order_row["customer_username"] or "",
                    cust_name,
                    order_row["product_key"],
                    order_row["package_name"] or order_row["product_key"],
                    format_currency(original_num),
                    order_row["discount_amount"] or format_currency(discount_num),
                    order_row["total_amount"],
                    utc_now()
                ))
    except Exception as e:
        print(f"Error inserting into coupon_usages: {e}")

# ================= Admin Decision Callbacks =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_acc_"))
@safe_callback
def handle_admin_accept(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "غير مصرح لك.", show_alert=True)
        return
    request_id = int(call.data.replace("adm_acc_", ""))
    with database_connection() as conn:
        row = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
        if not row or row["status"] != "awaiting_admin":
            bot.answer_callback_query(call.id, "تم التعامل مع هذا الطلب مسبقاً من قبل مسؤول آخر.", show_alert=True)
            return
        conn.execute("UPDATE payment_requests SET status = 'accepted', updated_at = ? WHERE id = ?", (utc_now(), request_id))

    # تسجيل استخدام الكوبون تلقائياً في قاعدة البيانات فور قبول الطلب
    record_coupon_usage_on_acceptance(row)

    # معالجة المحفظة والكاش باك
    user_id = row["user_id"]
    order_ref = row["order_ref"]
    wallet_used = Decimal(str(row["wallet_used"] or 0))
    cashback_earned = Decimal(str(row["cashback_earned"] or 0))

    if wallet_used > Decimal("0"):
        add_wallet_transaction(
            user_id,
            "wallet_discount",
            -wallet_used,
            f"خصم من رصيد المحفظة للطلب #{order_ref}",
            order_ref=order_ref
        )

    user_role = row["user_role"] if "user_role" in row.keys() else get_user_role(user_id)
    if cashback_earned > Decimal("0") and user_role == "customer":
        add_wallet_transaction(
            user_id,
            "cashback_earned",
            cashback_earned,
            f"كاش باك مكتسب من طلب #{order_ref}",
            order_ref=order_ref
        )

    # إرسال تنبيه فوري مصحوب بصوت للعميل
    notify_customer_status_change(row, "accepted")

    # إظهار تنبيه Popup فوري للأدمن
    bot.answer_callback_query(
        call.id, 
        text=f"🔔 تم قبول الطلب #{row['order_ref']} بنجاح وتم تحديث المحفظة وإشعار العميل!", 
        show_alert=True
    )

    try:
        admin_name = call.from_user.first_name or "المشرف"
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n✅ <b>تم قبول الطلب واعتماده بواسطة: {admin_name}</b>"
        )
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_rej_"))
@safe_callback
def handle_admin_reject(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "غير مصرح لك.", show_alert=True)
        return
    request_id = int(call.data.replace("adm_rej_", ""))
    with database_connection() as conn:
        row = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
        if not row or row["status"] != "awaiting_admin":
            bot.answer_callback_query(call.id, "تم التعامل مع هذا الطلب مسبقاً من قبل مسؤول آخر.", show_alert=True)
            return
        conn.execute("UPDATE payment_requests SET status = 'rejected', updated_at = ? WHERE id = ?", (utc_now(), request_id))

    # إرسال تنبيه فوري للعميل بسبب الرفض (إلغاء حجز المحفظة تلقائي)
    notify_customer_status_change(row, "rejected")

    # إظهار تنبيه Popup فوري للأدمن
    bot.answer_callback_query(
        call.id, 
        text=f"⚠️ تم رفض الطلب #{row['order_ref']} وإشعار العميل وإلغاء أي حجز للرصيد.", 
        show_alert=True
    )

    try:
        admin_name = call.from_user.first_name or "المشرف"
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n❌ <b>تم رفض الطلب بواسطة: {admin_name} وإشعار العميل فوراً.</b>"
        )
    except Exception:
        pass

# ================= Admin Panel & Features =================
def build_admin_main_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⏳ مراجعة الطلبات المعلقة", callback_data="adm_view_pending"),
        types.InlineKeyboardButton("📊 إحصائيات المبيعات", callback_data="adm_view_stats")
    )
    markup.add(
        types.InlineKeyboardButton("📊 إحصائيات واستخدام الكوبونات", callback_data="adm_coupon_stats"),
        types.InlineKeyboardButton("🎟 إنشاء وحذف الكوبونات", callback_data="adm_view_coupons")
    )
    markup.add(
        types.InlineKeyboardButton("👥 إدارة الرتب (تجار / أصدقاء)", callback_data="adm_view_roles"),
        types.InlineKeyboardButton("🏷 تعديل الأسعار الثلاثية", callback_data="adm_edit_prices")
    )
    markup.add(
        types.InlineKeyboardButton("👑 إدارة المشرفين (Admins)", callback_data="adm_manage_admins")
    )
    markup.add(
        types.InlineKeyboardButton("🔍 مراجعة بيانات عميل", callback_data="adm_lookup_customer"),
        types.InlineKeyboardButton("🔔 مركز وسجل التنبيهات", callback_data="adm_view_notifications")
    )
    markup.add(
        types.InlineKeyboardButton("📦 حالة توفر المنتجات", callback_data="adm_toggle_products"),
        types.InlineKeyboardButton("✏️ تعديل وصف المنتجات", callback_data="adm_edit_descriptions")
    )
    markup.add(
        types.InlineKeyboardButton("🖼️ إضافة/تعديل صورة المنتج", callback_data="adm_manage_photos"),
        types.InlineKeyboardButton("🎛️ توفر الباقات الفردية", callback_data="adm_tier_availability")
    )
    markup.add(
        types.InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm_broadcast")
    )
    markup.add(
        types.InlineKeyboardButton("➕ إضافة منتج جديد", callback_data="adm_add_product"),
        types.InlineKeyboardButton("🗑️ حذف منتج", callback_data="adm_delete_product")
    )
    markup.add(
        types.InlineKeyboardButton("➕ إضافة باقة جديدة", callback_data="adm_add_tier"),
        types.InlineKeyboardButton("🗑️ حذف باقة", callback_data="adm_delete_tier")
    )
    markup.add(
        types.InlineKeyboardButton("📋 قائمة الانتظار (Waitlist)", callback_data="adm_view_waitlist")
    )
    return markup

@bot.message_handler(func=lambda msg: msg.text == "🛠 لوحة الإدارة")
def handle_admin_panel_button(message):
    if not is_admin(message.from_user.id):
        return
    handle_admin_panel(message)

def handle_admin_panel(message):
    if not is_admin(message.from_user.id):
        return
    bot.send_message(
        message.chat.id,
        "🛠 <b>لوحة تحكم وإدارة المتجر (Admin Dashboard)</b>\n\nاختر من الأقسام التالية:",
        reply_markup=build_admin_main_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm_back_to_main")
@safe_callback
def handle_adm_back_to_main(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    safe_edit_message_text(
        call,
        "🛠 <b>لوحة تحكم وإدارة المتجر (Admin Dashboard)</b>\n\nاختر من الأقسام التالية:",
        reply_markup=build_admin_main_keyboard()
    )

# 1. Pending orders review
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_pending")
@safe_callback
def handle_adm_view_pending(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    with database_connection() as conn:
        pending = conn.execute("""
            SELECT * FROM payment_requests WHERE status = 'awaiting_admin' ORDER BY id ASC LIMIT 10
        """).fetchall()

    if not pending:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
        safe_edit_message_text(call, "✅ لا توجد أي اشتراكات معلقة حالياً! جميع الطلبات تم التعامل معها.", reply_markup=markup)
        return

    bot.send_message(call.message.chat.id, f"📋 يوجد <b>{len(pending)}</b> طلب معلق قيد المراجعة:")
    for row in pending:
        notify_admins_new_order(row["id"])

# 2. Sales Statistics
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_stats")
@safe_callback
def handle_adm_view_stats(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    with database_connection() as conn:
        accepted = conn.execute("SELECT * FROM payment_requests WHERE status = 'accepted'").fetchall()

    total_orders = len(accepted)
    total_income = Decimal("0")
    prod_stats = {}
    role_stats = {"customer": 0, "reseller": 0, "friend": 0, "admin": 0}

    for ord_row in accepted:
        amt = parse_price_amount(ord_row["total_amount"]) or Decimal("0")
        total_income += amt
        pkey = ord_row["product_key"]
        prod_stats[pkey] = prod_stats.get(pkey, 0) + (ord_row["quantity"] or 1)
        role = ord_row["user_role"]
        role_stats[role] = role_stats.get(role, 0) + 1

    prod_breakdown = "\n".join([f"• <b>{k}</b>: {v} مبيعة" for k, v in prod_stats.items()]) or "لا توجد مبيعات بعد"

    text = (
        "📊 <b>تقرير وإحصائيات المبيعات الشاملة</b>\n\n"
        f"✅ <b>إجمالي الطلبات الناجحة:</b> {total_orders} طلب\n"
        f"💰 <b>إجمالي الدخل المحقق:</b> <b>{format_currency(total_income)}</b>\n\n"
        f"👥 <b>توزيع المبيعات حسب الرتب:</b>\n"
        f"• عملاء: {role_stats.get('customer', 0)}\n"
        f"• تجار ومسوقين: {role_stats.get('reseller', 0)}\n"
        f"• أصدقاء: {role_stats.get('friend', 0)}\n\n"
        f"📦 <b>مبيعات المنتجات بالتفصيل:</b>\n{prod_breakdown}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, text, reply_markup=markup)

# 3. Roles Management
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_roles")
@safe_callback
def handle_adm_view_roles(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    roles = get_user_roles()
    resellers = [f"• ID: <code>{uid}</code> | {info.get('name')} (@{info.get('username', 'بدون')})" for uid, info in roles.items() if info.get("role") == "reseller"]
    friends = [f"• ID: <code>{uid}</code> | {info.get('name')} (@{info.get('username', 'بدون')})" for uid, info in roles.items() if info.get("role") == "friend"]

    resellers_text = "\n".join(resellers) if resellers else "لا يوجد تجار مسجلين"
    friends_text = "\n".join(friends) if friends else "لا يوجد أصدقاء مسجلين"

    text = (
        "👥 <b>إدارة الرتب (تجار / أصدقاء)</b>\n\n"
        f"💼 <b>قائمة التجار المعتمدين:</b>\n{resellers_text}\n\n"
        f"🤝 <b>قائمة الأصدقاء:</b>\n{friends_text}\n\n"
        "لترقية مستخدم أو سحب رتبته، اضغط على أحد الأزرار بالأسفل:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ ترقية إلى تاجر", callback_data="adm_role_set_reseller"),
        types.InlineKeyboardButton("➕ ترقية إلى صديق", callback_data="adm_role_set_friend")
    )
    markup.add(
        types.InlineKeyboardButton("➖ سحب رتبة (إرجاع كعميل)", callback_data="adm_role_set_customer")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_role_set_"))
@safe_callback
def handle_adm_role_prompt(call):
    if not is_admin(call.from_user.id):
        return
    target_role = call.data.replace("adm_role_set_", "")
    role_names = {"reseller": "تاجر", "friend": "صديق", "customer": "عميل"}
    admin_action_states[call.from_user.id] = {"action": "set_role", "target_role": target_role}
    bot.send_message(
        call.message.chat.id,
        f"أرسل الآن <b>Telegram ID</b> أو <b>@username</b> الخاص بالمستخدم لتعيين رتبته كـ <b>{role_names.get(target_role)}</b>\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

# 4. 3-tier Price Editing
@bot.callback_query_handler(func=lambda c: c.data == "adm_edit_prices")
@safe_callback
def handle_adm_edit_prices_select_prod(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(p["name"], callback_data=f"adm_price_prod_{k}") for k, p in store.items()]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, "🏷 <b>تعديل الأسعار الثلاثية</b>\nاختر المنتج الذي ترغب في تعديل أسعار باقاته:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_price_prod_"))
@safe_callback
def handle_adm_edit_prices_select_pkg(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    prod_key = call.data.replace("adm_price_prod_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for pkg in prod.get("packages", []):
        cb_txt = f" ك:{pkg.get('cashback', '0ج')}" if pkg.get('cashback') else ""
        text = f"{pkg['label']} | ع:{pkg.get('retail_price')} ت:{pkg.get('reseller_price')} ص:{pkg.get('friend_price')}{cb_txt}"
        markup.add(types.InlineKeyboardButton(text, callback_data=f"adm_pkg_tier:{prod_key}:{pkg['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للمنتجات", callback_data="adm_edit_prices"))
    safe_edit_message_text(call, f"اختر الباقة المراد تعديل أسعارها في <b>{prod['name']}</b>:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_pkg_tier:") or c.data.startswith("adm_pkg_tier_"))
@safe_callback
def handle_adm_choose_price_tier(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    if ":" in call.data:
        _, prod_key, pkg_id = call.data.split(":", 2)
    else:
        raw = call.data.replace("adm_pkg_tier_", "")
        store = get_store_data()
        found_prod, found_pkg = None, None
        for pk in store:
            if raw.startswith(pk + "_"):
                found_prod = pk
                found_pkg = raw[len(pk) + 1:]
                break
        prod_key = found_prod or "chatgpt"
        pkg_id = found_pkg or raw

    store = get_store_data()
    prod = store.get(prod_key)
    pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None) if prod else None
    if not pkg:
        bot.answer_callback_query(call.id, "الباقة غير موجودة.", show_alert=True)
        return

    text = (
        f"📦 <b>{prod['name']} — {pkg['label']}</b>\n\n"
        f"1️⃣ سعر العميل: <b>{pkg.get('retail_price', '0ج')}</b>\n"
        f"2️⃣ سعر التاجر: <b>{pkg.get('reseller_price', '0ج')}</b>\n"
        f"3️⃣ سعر الصديق: <b>{pkg.get('friend_price', '0ج')}</b>\n"
        f"🎁 كاش باك الباقة: <b>{pkg.get('cashback', '0ج')}</b>\n\n"
        "اختر أي فئة تريد تعديلها بشكل منفصل:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ تعديل سعر العميل (Customer)", callback_data=f"adm_setprice:{prod_key}:{pkg_id}:retail_price"),
        types.InlineKeyboardButton("💼 تعديل سعر التاجر (Reseller)", callback_data=f"adm_setprice:{prod_key}:{pkg_id}:reseller_price"),
        types.InlineKeyboardButton("🤝 تعديل سعر الصديق (Friend)", callback_data=f"adm_setprice:{prod_key}:{pkg_id}:friend_price"),
        types.InlineKeyboardButton("🎁 تعديل كاش باك الباقة (Cashback)", callback_data=f"adm_setprice:{prod_key}:{pkg_id}:cashback"),
        types.InlineKeyboardButton("🔙 رجوع للباقات", callback_data=f"adm_price_prod_{prod_key}")
    )
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_setprice:") or c.data.startswith("adm_setprice_"))
@safe_callback
def handle_adm_setprice_prompt(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    if ":" in call.data:
        _, prod_key, pkg_id, tier_field = call.data.split(":", 3)
    else:
        raw = call.data.replace("adm_setprice_", "")
        known_fields = ["retail_price", "reseller_price", "friend_price", "cashback"]
        matched_field = None
        for kf in known_fields:
            if raw.endswith("_" + kf):
                matched_field = kf
                raw = raw[:-len("_" + kf)]
                break
        tier_field = matched_field or "retail_price"
        store = get_store_data()
        found_prod, found_pkg = None, None
        for pk in store:
            if raw.startswith(pk + "_"):
                found_prod = pk
                found_pkg = raw[len(pk) + 1:]
                break
        prod_key = found_prod or "chatgpt"
        pkg_id = found_pkg or raw

    tier_names = {
        "retail_price": "سعر العميل",
        "reseller_price": "سعر التاجر",
        "friend_price": "سعر الصديق",
        "cashback": "قيمة الكاش باك"
    }

    admin_action_states[call.from_user.id] = {
        "action": "update_price",
        "prod_key": prod_key,
        "pkg_id": pkg_id,
        "field": tier_field
    }
    bot.send_message(
        call.message.chat.id,
        f"أرسل الآن القيمة الجديدة لـ <b>{tier_names.get(tier_field, tier_field)}</b> (مثال: <code>350ج</code> أو <code>350</code>)، أو /cancel للإلغاء:"
    )

# 5. Coupon System Management
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_coupons")
@safe_callback
def handle_adm_view_coupons(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    coupons = get_coupons()
    lines = []
    for code, c in coupons.items():
        status = "✅ نشط" if c.get("active", True) else "❌ معطل"
        applicable = c.get("applicable_products")
        applicable_tiers = c.get("applicable_tiers")
        if applicable:
            scope = f"📦 {', '.join(applicable)}"
        else:
            scope = "📦 جميع المنتجات"
        if applicable_tiers:
            tier_scope = f"🏷️ {len(applicable_tiers)} باقة محددة"
        else:
            tier_scope = "🏷️ جميع الباقات"
        lines.append(
            f"🎟 <b>{code}</b> ({c.get('influencer', 'بدون')}) - {status}\n"
            f"   استخدامات: {c.get('used_count', 0)} / {c.get('max_uses', 'غير محدود')} | خصم ثابت: {c.get('fixed_discount', 0)}ج\n"
            f"   {scope} | {tier_scope}"
        )
    coupons_text = "\n\n".join(lines) if lines else "لا توجد كوبونات منشأة حالياً."

    text = f"🎟 <b>نظام الكوبونات والمؤثرين</b>\n\n{coupons_text}"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إنشاء كوبون جديد", callback_data="adm_coupon_create"),
        types.InlineKeyboardButton("🗑 حذف كوبون", callback_data="adm_coupon_delete")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_coupon_create")
@safe_callback
def handle_adm_coupon_create_prompt(call):
    if not is_admin(call.from_user.id):
        return
    admin_action_states[call.from_user.id] = {"action": "create_coupon_step1"}
    bot.send_message(
        call.message.chat.id,
        "🎟 <b>إنشاء كوبون جديد</b>\n\n"
        "أرسل كود الكوبون واسم المؤثر وقيمة الخصم بالجنيه مفصولين بفاصلة:\n"
        "مثال: <code>SUMMER50, يوتيوبر تقني, 50</code>\n\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_coupon_delete")
@safe_callback
def handle_adm_coupon_delete_prompt(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    coupons = get_coupons()
    if not coupons:
        bot.answer_callback_query(call.id, "لا توجد كوبونات لحذفها.", show_alert=True)
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(f"❌ {c}", callback_data=f"adm_del_coup_{c}") for c in coupons]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_view_coupons"))
    safe_edit_message_text(call, "اختر الكوبون المراد حذفه نهائياً:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_coup_"))
@safe_callback
def handle_adm_confirm_delete_coupon(call):
    if not is_admin(call.from_user.id):
        return
    code = call.data.replace("adm_del_coup_", "")
    coupons = get_coupons()
    if code in coupons:
        del coupons[code]
        update_coupons(coupons)
    bot.answer_callback_query(call.id, f"تم حذف الكوبون {code}")
    # Reuse the view handler to refresh the list (it will answer callback again, but that's fine)
    handle_adm_view_coupons(call)

# ================= Coupon Product Selection Callbacks =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_cpn_sel_all")
@safe_callback
def handle_adm_cpn_select_all(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    state["selected_products"] = []
    admin_action_states[call.from_user.id] = state
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_coupon_product_selection_keyboard(call.from_user.id)
    )
    bot.answer_callback_query(call.id, "تم اختيار جميع المنتجات")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_cpn_sel_") and c.data != "adm_cpn_sel_all")
@safe_callback
def handle_adm_cpn_toggle_product(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    prod_key = call.data.replace("adm_cpn_sel_", "")
    selected = state.get("selected_products", [])
    if prod_key in selected:
        selected.remove(prod_key)
    else:
        selected.append(prod_key)
    state["selected_products"] = selected
    admin_action_states[call.from_user.id] = state
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_coupon_product_selection_keyboard(call.from_user.id)
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_cpn_to_tiers")
@safe_callback
def handle_adm_cpn_to_tiers(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    state["selected_tiers"] = []
    admin_action_states[call.from_user.id] = state
    bot.answer_callback_query(call.id)
    safe_edit_message_text(
        call,
        "🏷️ <b>اختيار الباقات (اختياري)</b>\n\n"
        "يمكنك اختيار باقات محددة لتقييد الكوبون عليها، أو اضغط <b>الكل</b> لجميع الباقات:\n\n"
        "💡 إذا لم تختر أي باقة، سيطبق الكوبون على جميع الباقات في المنتجات المحددة.",
        reply_markup=build_coupon_tier_selection_keyboard(call.from_user.id)
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm_cpn_back_to_products")
@safe_callback
def handle_adm_cpn_back_to_products(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    bot.answer_callback_query(call.id)
    safe_edit_message_text(
        call,
        "📦 <b>اختر المنتجات التي ينطبق عليها الكوبون:</b>",
        reply_markup=build_coupon_product_selection_keyboard(call.from_user.id)
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm_cpn_tier_all")
@safe_callback
def handle_adm_cpn_tier_select_all(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    state["selected_tiers"] = []
    admin_action_states[call.from_user.id] = state
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_coupon_tier_selection_keyboard(call.from_user.id)
    )
    bot.answer_callback_query(call.id, "تم اختيار جميع الباقات")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_cpn_tier_") and c.data not in ("adm_cpn_tier_all",))
@safe_callback
def handle_adm_cpn_toggle_tier(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    tier_key = call.data.replace("adm_cpn_tier_", "")
    selected_tiers = state.get("selected_tiers", [])
    if tier_key in selected_tiers:
        selected_tiers.remove(tier_key)
    else:
        selected_tiers.append(tier_key)
    state["selected_tiers"] = selected_tiers
    admin_action_states[call.from_user.id] = state
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_coupon_tier_selection_keyboard(call.from_user.id)
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_cpn_confirm")
@safe_callback
def handle_adm_cpn_confirm_creation(call):
    if not is_admin(call.from_user.id):
        return
    state = admin_action_states.get(call.from_user.id)
    if not state or state.get("action") != "create_coupon_step2":
        bot.answer_callback_query(call.id, "انتهت الجلسة.")
        return
    admin_action_states.pop(call.from_user.id, None)

    code = state["code"]
    influencer = state["influencer"]
    discount = state["discount"]
    selected = state.get("selected_products", [])
    selected_tiers = state.get("selected_tiers", [])
    applicable = selected if selected else []

    coupons = get_coupons()
    coupons[code] = {
        "code": code,
        "influencer": influencer,
        "discount_type": "fixed",
        "fixed_discount": discount,
        "package_discounts": {},
        "max_uses": 500,
        "used_count": 0,
        "active": True,
        "created_at": utc_now(),
        "usage_history": []
    }
    if applicable:
        coupons[code]["applicable_products"] = applicable
    if selected_tiers:
        coupons[code]["applicable_tiers"] = selected_tiers
    update_coupons(coupons)

    if applicable:
        products_label = ", ".join(applicable)
        scope_msg = f"📦 المنتجات المحددة: <b>{products_label}</b>"
    else:
        scope_msg = "📦 ينطبق على: <b>جميع المنتجات</b>"

    if selected_tiers:
        tiers_display = []
        store = get_store_data()
        for tier_key in selected_tiers:
            parts = tier_key.split("_", 1)
            if len(parts) == 2:
                p_key, p_id = parts
                prod = store.get(p_key)
                pkg = next((p for p in prod.get("packages", []) if p["id"] == p_id), None) if prod else None
                if prod and pkg:
                    tiers_display.append(f"{prod['name']} — {pkg['label']}")
        tiers_label = "\n".join([f"  • {t}" for t in tiers_display])
        tier_msg = f"\n🏷️ <b>الباقات المحددة:</b>\n{tiers_label}"
    else:
        tier_msg = "\n🏷️ ينطبق على: <b>جميع الباقات</b>"

    bot.edit_message_text(
        f"✅ تم إنشاء الكوبون <b>{code}</b> بنجاح!\n"
        f"🏷 برعاية: <b>{influencer}</b>\n"
        f"✂️ قيمة الخصم: <b>{discount}ج</b>\n"
        f"{scope_msg}"
        f"{tier_msg}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id, "تم إنشاء الكوبون بنجاح!")

# ================= 5.1 Detailed Coupon Statistics & Reports =================
def send_chunked_messages(chat_id, text, reply_markup=None):
    """
    تقسيم الرسائل الطويلة تلقائياً لتجنب تجاوز حد تيليجرام (4096 حرف)
    وإرسالها بشكل مريح ومرتب للمستخدم.
    """
    max_len = 3800
    if len(text) <= max_len:
        bot.send_message(chat_id, text, reply_markup=reply_markup)
        return

    parts = []
    lines = text.split("\n")
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_len:
            parts.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk.strip():
        parts.append(current_chunk)

    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        markup = reply_markup if is_last else None
        bot.send_message(chat_id, part.strip(), reply_markup=markup)

def format_coupon_detailed_report(code, c):
    """صياغة تقرير منظم وتفصيلي لكوبون محدد مع تفاصيل كل عملية شراء"""
    history = c.get("usage_history", [])
    used_count = len(history)

    total_discount = Decimal("0")
    total_revenue = Decimal("0")

    ops_lines = []
    for idx, u in enumerate(reversed(history), 1):
        d_val = parse_price_amount(u.get("discount_amount", "0")) or Decimal("0")
        f_val = parse_price_amount(u.get("final_amount", "0")) or Decimal("0")
        total_discount += d_val
        total_revenue += f_val

        ops_lines.append(
            f"🔹 <b>عملية #{idx} — طلب:</b> <code>#{u.get('order_ref', 'N/A')}</code>\n"
            f"   🛍 <b>الباقة المستخدم عليها:</b> {u.get('product_name', '')} ({u.get('package_name', '')})\n"
            f"   👤 <b>العميل:</b> {u.get('customer_name', 'عميل')} (@{u.get('username') or 'بدون'}) | ID: <code>{u.get('user_id')}</code>\n"
            f"   💵 <b>المبالغ:</b> الأصلي: {u.get('original_amount', '0ج')} | الخصم: {u.get('discount_amount', '0ج')} | <b>المدفوع: {u.get('final_amount', '0ج')}</b>\n"
            f"   📅 <b>التوقيت:</b> {u.get('date', 'غير محدد')}"
        )

    # معلومات قيمة الخصم
    if c.get("discount_type") == "package_specific":
        pkg_discounts_str = ", ".join([f"{k}: {v}ج" for k, v in c.get("package_discounts", {}).items()])
        val_str = f"مخصص للباقات ({pkg_discounts_str})"
    else:
        val_str = f"خصم ثابت {c.get('fixed_discount', 0)}ج"

    status_str = "✅ نشط وفعال" if c.get("active", True) else "❌ معطل"
    history_text = "\n\n".join(ops_lines) if ops_lines else "<i>لا توجد عمليات شراء معتمدة ومكتملة بهذا الكوبون حتى الآن.</i>"

    applicable = c.get("applicable_products")
    if applicable:
        scope_str = f"📦 <b>المنتجات المحددة:</b> {', '.join(applicable)}\n"
    else:
        scope_str = "📦 <b>ينطبق على:</b> جميع المنتجات\n"

    applicable_tiers = c.get("applicable_tiers")
    if applicable_tiers:
        store = get_store_data()
        tiers_display = []
        for tier_key in applicable_tiers:
            parts = tier_key.split("_", 1)
            if len(parts) == 2:
                p_key, p_id = parts
                prod = store.get(p_key)
                pkg = next((p for p in prod.get("packages", []) if p["id"] == p_id), None) if prod else None
                if prod and pkg:
                    tiers_display.append(f"{prod['name']} — {pkg['label']}")
        if tiers_display:
            tier_str = f"🏷️ <b>الباقات المحددة:</b> {', '.join(tiers_display)}\n"
        else:
            tier_str = "🏷️ <b>ينطبق على:</b> جميع الباقات\n"
    else:
        tier_str = "🏷️ <b>ينطبق على:</b> جميع الباقات\n"

    report = (
        f"🎟 <b>تقرير الكوبون:</b> <code>{code}</code>\n"
        f"🏷 <b>المؤثر / الجهة:</b> <b>{c.get('influencer', 'عام')}</b>\n"
        f"📌 <b>الحالة:</b> {status_str}\n"
        f"✂️ <b>قيمة الكوبون:</b> {val_str}\n"
        f"{scope_str}"
        f"{tier_str}"
        f"📊 <b>إجمالي مرات الاستخدام:</b> {used_count} من {c.get('max_uses', 'غير محدود')}\n"
        f"💰 <b>إجمالي الخصم الممنوح:</b> {format_currency(total_discount)}\n"
        f"💵 <b>إجمالي المبيعات المحققة منه:</b> {format_currency(total_revenue)}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>سجل العمليات الدقيقة التي استخدم فيها الكوبون:</b>\n\n"
        f"{history_text}"
    )
    return report, total_discount, total_revenue, used_count

@bot.callback_query_handler(func=lambda c: c.data == "adm_coupon_stats")
@safe_callback
def handle_adm_coupon_stats_menu(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    coupons = get_coupons()
    if not coupons:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main"))
        safe_edit_message_text(
            call,
            "📊 <b>إحصائيات واستخدام الكوبونات</b>\n\nلا توجد أي كوبونات مسجلة في النظام حالياً.",
            reply_markup=markup
        )
        return

    total_coupons = len(coupons)
    total_usages_all = 0
    total_discount_all = Decimal("0")
    total_revenue_all = Decimal("0")

    markup = types.InlineKeyboardMarkup(row_width=1)

    for code, c in coupons.items():
        history = c.get("usage_history", [])
        u_count = len(history)
        total_usages_all += u_count
        for u in history:
            total_discount_all += parse_price_amount(u.get("discount_amount", "0")) or Decimal("0")
            total_revenue_all += parse_price_amount(u.get("final_amount", "0")) or Decimal("0")

        btn_label = f"🎟 {code} ({u_count} استخدام) — {c.get('influencer', 'مؤثر')}"
        markup.add(types.InlineKeyboardButton(btn_label, callback_data=f"adm_cpstat_{code}"))

    markup.add(
        types.InlineKeyboardButton("📑 التقرير الشامل لجميع الكوبونات", callback_data="adm_cpstat_all"),
        types.InlineKeyboardButton("📤 تصدير تقرير الكوبونات كملف (TXT)", callback_data="adm_export_coupons"),
        types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
    )

    overview_text = (
        "📊 <b>مركز إحصائيات واستخدام الكوبونات</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 <b>عدد الكوبونات المسجلة:</b> {total_coupons} كوبون\n"
        f"🔄 <b>إجمالي مرات الاستخدام:</b> {total_usages_all} عملية مؤكدة\n"
        f"✂️ <b>إجمالي الخصومات الممنوحة:</b> {format_currency(total_discount_all)}\n"
        f"💰 <b>إجمالي مبيعات طلبات الكوبونات:</b> {format_currency(total_revenue_all)}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>اختر كود الكوبون لعرض تفاصيل عملياته الدقيقة:</b>"
    )
    safe_edit_message_text(call, overview_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_cpstat_") and c.data != "adm_cpstat_all")
@safe_callback
def handle_adm_single_coupon_detail(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    code = call.data.replace("adm_cpstat_", "")
    coupons = get_coupons()
    c = coupons.get(code)
    if not c:
        bot.answer_callback_query(call.id, "الكوبون غير موجود.", show_alert=True)
        return

    report_text, _, _, _ = format_coupon_detailed_report(code, c)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔙 رجوع لقائمة الكوبونات", callback_data="adm_coupon_stats")
    )

    send_chunked_messages(call.message.chat.id, report_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_cpstat_all")
@safe_callback
def handle_adm_all_coupons_report(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    coupons = get_coupons()
    if not coupons:
        bot.answer_callback_query(call.id, "لا توجد كوبونات مسجلة.", show_alert=True)
        return

    full_reports = []
    full_reports.append("📑 <b>التقرير الشامل لجميع كوبونات المتجر والمؤثرين:</b>\n" + "═" * 28)
    for code, c in coupons.items():
        rep, _, _, _ = format_coupon_detailed_report(code, c)
        full_reports.append(rep)
        full_reports.append("═" * 28)

    full_text = "\n\n".join(full_reports)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع لإحصائيات الكوبونات", callback_data="adm_coupon_stats"))

    send_chunked_messages(call.message.chat.id, full_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_export_coupons")
@safe_callback
def handle_adm_export_coupons_file(call):
    if not is_admin(call.from_user.id):
        return
    coupons = get_coupons()
    now_str = utc_now()[:19].replace("T", " ")

    lines = [
        "===========================================================",
        "        GoPro Store Bot - تقرير واستخدام الكوبونات         ",
        f"                  تاريخ التصدير: {now_str}                  ",
        "===========================================================",
        ""
    ]

    for code, c in coupons.items():
        history = c.get("usage_history", [])
        lines.append(f"الكود: {code}")
        lines.append(f"المؤثر: {c.get('influencer', 'عام')}")
        lines.append(f"مرات الاستخدام: {len(history)} / {c.get('max_uses', 'غير محدود')}")
        lines.append(f"الخصم: {c.get('fixed_discount', 0)}ج")
        lines.append("تفاصيل العمليات:")
        if not history:
            lines.append("  - لا توجد عمليات بعد.")
        else:
            for idx, u in enumerate(history, 1):
                lines.append(f"  [{idx}] طلب: #{u.get('order_ref')} | الباقة: {u.get('product_name')} - {u.get('package_name')}")
                lines.append(f"      العميل: {u.get('customer_name')} (@{u.get('username')}) | ID: {u.get('user_id')}")
                lines.append(f"      الأصلي: {u.get('original_amount')} | الخصم: {u.get('discount_amount')} | المدفوع: {u.get('final_amount')}")
                lines.append(f"      التاريخ: {u.get('date')}")
        lines.append("-----------------------------------------------------------")

    file_content = "\n".join(lines).encode("utf-8")
    doc_file = io.BytesIO(file_content)
    doc_file.name = f"coupons_report_{datetime.date.today().strftime('%Y_%m_%d')}.txt"

    bot.send_document(
        call.message.chat.id,
        doc_file,
        caption="📊 <b>تم تصدير تقرير إحصائيات واستخدام الكوبونات الكامل بنجاح كملف نصي منظم.</b>"
    )
    bot.answer_callback_query(call.id, "تم التصدير بنجاح")

# 6. Customer Profile Lookup
@bot.callback_query_handler(func=lambda c: c.data == "adm_lookup_customer")
@safe_callback
def handle_adm_lookup_customer_prompt(call):
    bot.answer_callback_query(call.id)
    if not is_admin(call.from_user.id):
        return
    admin_action_states[call.from_user.id] = {"action": "lookup_customer"}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 إلغاء", callback_data="adm_cancel_lookup"))
    safe_edit_message_text(
        call,
        "🔍 <b>يرجى إرسال ID العميل أو اسم المستخدم (Username) للبحث عن بياناته:</b>\n\n"
        "💡 يدعم البحث برقم الـ ID مباشرة أو باسم المستخدم (مع @ أو بدونها وبأي صيغة أحرف).\n\n"
        "أو اضغط زر الإلغاء للرجوع:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm_cancel_lookup")
@safe_callback
def handle_adm_cancel_lookup(call):
    bot.answer_callback_query(call.id, "تم الإلغاء")
    admin_action_states.pop(call.from_user.id, None)
    handle_adm_back_to_main(call)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_cust_"))
@safe_callback
def handle_adm_customer_shortcut(call):
    bot.answer_callback_query(call.id)
    if not is_admin(call.from_user.id):
        return
    target_id = int(call.data.replace("adm_cust_", ""))
    report, _ = generate_customer_report_detailed(target_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    bot.send_message(call.message.chat.id, report, reply_markup=markup)

def generate_customer_report_detailed(query):
    query = str(query).strip()
    target_uid = None
    user_record = None

    with database_connection() as conn:
        if query.isdigit():
            target_uid = int(query)
            user_row = conn.execute("SELECT * FROM users WHERE user_id = ?", (target_uid,)).fetchone()
            if user_row:
                user_record = dict(user_row)
        else:
            clean_u = query.lstrip("@").lower()
            user_row = conn.execute("SELECT * FROM users WHERE LOWER(username) = ?", (clean_u,)).fetchone()
            if user_row:
                user_record = dict(user_row)
                target_uid = user_record["user_id"]

        # Fallback search in payment_requests
        if not target_uid:
            if query.isdigit():
                p_row = conn.execute("SELECT * FROM payment_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1", (int(query),)).fetchone()
                if p_row:
                    target_uid = p_row["user_id"]
                    user_record = {
                        "user_id": target_uid,
                        "username": p_row["customer_username"],
                        "first_name": p_row["customer_first_name"],
                        "last_name": p_row["customer_last_name"],
                        "date_joined": p_row["created_at"]
                    }
            else:
                clean_u = query.lstrip("@").lower()
                p_row = conn.execute("SELECT * FROM payment_requests WHERE LOWER(customer_username) = ? ORDER BY id DESC LIMIT 1", (clean_u,)).fetchone()
                if p_row:
                    target_uid = p_row["user_id"]
                    user_record = {
                        "user_id": target_uid,
                        "username": p_row["customer_username"],
                        "first_name": p_row["customer_first_name"],
                        "last_name": p_row["customer_last_name"],
                        "date_joined": p_row["created_at"]
                    }

        # Fallback search in user_roles.json
        if not target_uid:
            roles = get_user_roles()
            if query.isdigit() and str(query) in roles:
                target_uid = int(query)
                rinfo = roles[str(query)]
                user_record = {
                    "user_id": target_uid,
                    "username": rinfo.get("username"),
                    "first_name": rinfo.get("name", "مستخدم"),
                    "last_name": "",
                    "date_joined": rinfo.get("updated_at", "غير مسجل")
                }
            else:
                clean_u = query.lstrip("@").lower()
                for uid_str, rinfo in roles.items():
                    if rinfo.get("username", "").lower() == clean_u and uid_str.isdigit():
                        target_uid = int(uid_str)
                        user_record = {
                            "user_id": target_uid,
                            "username": rinfo.get("username"),
                            "first_name": rinfo.get("name", "مستخدم"),
                            "last_name": "",
                            "date_joined": rinfo.get("updated_at", "غير مسجل")
                        }
                        break

        if not target_uid:
            return (
                f"❌ <b>لم يتم العثور على العميل!</b>\n\n"
                f"لم نتمكن من العثور على أي حساب مسجل بالمعرف أو اسم المستخدم: <code>{query}</code>\n"
                f"تأكد من صحة الـ ID أو اسم المستخدم وحاول مرة أخرى.",
                False
            )

        orders = conn.execute("SELECT * FROM payment_requests WHERE user_id = ? ORDER BY id DESC", (target_uid,)).fetchall()
        total_orders = len(orders)
        accepted_count = sum(1 for o in orders if o["status"] == "accepted")
        pending_count = sum(1 for o in orders if o["status"] == "awaiting_admin")
        rejected_count = sum(1 for o in orders if o["status"] == "rejected")

        total_spent = Decimal("0")
        for o in orders:
            if o["status"] == "accepted":
                amt = parse_price_amount(o["total_amount"]) or Decimal("0")
                total_spent += amt

    bal = get_user_wallet_balance(target_uid)
    role = get_user_role(target_uid)
    badge = role_badge_display(role)

    first_n = user_record.get("first_name") or "عميل"
    last_n = user_record.get("last_name") or ""
    full_name = f"{first_n} {last_n}".strip()
    u_name = user_record.get("username")
    username_display = f"@{u_name}" if u_name else "غير محدد"
    date_joined = user_record.get("date_joined", "غير مسجل")
    if date_joined and len(date_joined) >= 10:
        date_joined = date_joined[:10]

    history_lines = []
    for o in orders[:5]:
        st_icon = "✅" if o["status"] == "accepted" else ("⏳" if o["status"] == "awaiting_admin" else "❌")
        history_lines.append(f"• {st_icon} #{o['order_ref']} | {o['package_name']} | {o['total_amount']}")
    history_text = "\n".join(history_lines) if history_lines else "<i>لا توجد طلبات مسجلة حتى الآن</i>"

    report_text = (
        "👤 <b>بطاقة بيانات العميل الشاملة</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📛 <b>الاسم:</b> {full_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{target_uid}</code> <i>(اضغط للنسخ)</i>\n"
        f"🌐 <b>اسم المستخدم:</b> {username_display}\n"
        f"🎖 <b>الرتبة الحالية:</b> <b>{badge}</b>\n"
        f"💰 <b>رصيد المحفظة:</b> <b>{format_currency(bal)} EGP</b>\n"
        f"📅 <b>تاريخ الانضمام:</b> {date_joined}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>إحصائيات الطلبات:</b>\n"
        f"• إجمالي الطلبات: <b>{total_orders}</b>\n"
        f"• مكتملة ومقبولة: <b>{accepted_count}</b>\n"
        f"• معلقة قيد المراجعة: <b>{pending_count}</b>\n"
        f"• مرفوضة / ملغاة: <b>{rejected_count}</b>\n"
        f"💵 <b>إجمالي المشتريات:</b> <b>{format_currency(total_spent)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>آخر الطلبات:</b>\n{history_text}"
    )
    return report_text, True

def generate_customer_report(user_id=None, username=None):
    query = str(user_id) if user_id is not None else (str(username) if username else "")
    report, _ = generate_customer_report_detailed(query)
    return report

# 7. Product Stock Toggle
@bot.callback_query_handler(func=lambda c: c.data == "adm_toggle_products")
@safe_callback
def handle_adm_toggle_products_view(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        status = "✅ متوفر" if p.get("available", True) else "❌ غير متوفر"
        markup.add(types.InlineKeyboardButton(f"{status} - {p['name']}", callback_data=f"adm_tog_{k}"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, "اضغط على أي منتج لتغيير حالة توفره الفوري:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_tog_"))
@safe_callback
def handle_adm_toggle_product_status(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_tog_", "")
    store = get_store_data()
    if prod_key in store:
        store[prod_key]["available"] = not store[prod_key].get("available", True)
        update_store_data(store)
    bot.answer_callback_query(call.id, "تم تحديث حالة المنتج")
    # Reuse the view handler to refresh the list
    handle_adm_toggle_products_view(call)

# 7.1 Product Description Editing
@bot.callback_query_handler(func=lambda c: c.data == "adm_edit_descriptions")
@safe_callback
def handle_adm_edit_descriptions_view(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        desc_preview = (p.get("description", "")[:40] + "...") if len(p.get("description", "")) > 40 else p.get("description", "بدون وصف")
        markup.add(types.InlineKeyboardButton(
            f"✏️ {p['name']}",
            callback_data=f"adm_edit_desc_{k}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(
        call,
        "✏️ <b>تعديل وصف المنتجات</b>\n\nاختر المنتج الذي ترغب في تعديل وصفه:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_edit_desc_"))
@safe_callback
def handle_adm_edit_desc_prompt(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_edit_desc_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    admin_action_states[call.from_user.id] = {"action": "edit_description", "prod_key": prod_key}
    current_desc = prod.get("description", "بدون وصف")
    bot.send_message(
        call.message.chat.id,
        f"✏️ <b>تعديل وصف المنتج:</b> <b>{prod['name']}</b>\n\n"
        f"📝 <b>الوصف الحالي:</b>\n{current_desc}\n\n"
        "أرسل الآن الوصف الجديد للمنتج:\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

# 7.2 Product Photo Management
@bot.callback_query_handler(func=lambda c: c.data == "adm_manage_photos")
@safe_callback
def handle_adm_manage_photos_view(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        has_photo = "🖼️" if p.get("photo") else "📷"
        markup.add(types.InlineKeyboardButton(
            f"{has_photo} {p['name']}",
            callback_data=f"adm_photo_{k}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(
        call,
        "🖼️ <b>إدارة صور المنتجات</b>\n\n"
        "اختر المنتج الذي ترغب في إضافة أو تعديل صورته:\n"
        "🖼️ = صورة موجودة | 📷 = بدون صورة",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_photo_"))
@safe_callback
def handle_adm_photo_product_selected(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_photo_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return

    current_photo = prod.get("photo", "")
    photo_status = f"✅ الصورة الحالية: <code>{current_photo[:50]}...</code>" if current_photo else "❌ لا توجد صورة حالياً"

    markup = types.InlineKeyboardMarkup(row_width=1)
    if current_photo:
        markup.add(types.InlineKeyboardButton("🗑 حذف الصورة الحالية", callback_data=f"adm_del_photo_{prod_key}"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_manage_photos"))

    admin_action_states[call.from_user.id] = {"action": "update_product_photo", "prod_key": prod_key}
    bot.send_message(
        call.message.chat.id,
        f"🖼️ <b>تعديل صورة المنتج:</b> <b>{prod['name']}</b>\n\n"
        f"{photo_status}\n\n"
        "أرسل الآن صورة جديدة للمنتج (كبصورة Photo مباشرة):\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_photo_"))
@safe_callback
def handle_adm_delete_product_photo(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_del_photo_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return

    prod.pop("photo", None)
    update_store_data(store)

    # Also remove photo from packages
    for pkg in prod.get("packages", []):
        pkg.pop("photo", None)
    update_store_data(store)

    bot.answer_callback_query(call.id, "تم حذف الصورة بنجاح!")
    bot.edit_message_text(
        f"✅ تم حذف صورة المنتج <b>{prod['name']}</b> بنجاح!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_manage_photos")
        )
    )

# 8. Notifications Center & Test
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_notifications")
@safe_callback
def handle_adm_view_notifications(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    with database_connection() as conn:
        total_logs = conn.execute("SELECT COUNT(*) AS c FROM notifications_log").fetchone()["c"]
        recent = conn.execute("""
            SELECT * FROM notifications_log ORDER BY id DESC LIMIT 5
        """).fetchall()

    recent_text_list = []
    for r in recent:
        time_str = r["created_at"][11:16]
        recent_text_list.append(
            f"• <b>[{time_str}]</b> إشعار لـ <code>{r['user_id']}</code> ({r['notification_type']}):\n"
            f"  {r['content'][:60]}..."
        )
    recent_text = "\n\n".join(recent_text_list) if recent_text_list else "لا توجد إشعارات مسجلة بعد"

    text = (
        "🔔 <b>مركز وسجل نظام التنبيهات الفورية</b>\n\n"
        f"📊 <b>إجمالي التنبيهات المرسلة:</b> {total_logs} تنبيه\n\n"
        f"📝 <b>آخر التنبيهات المسجلة:</b>\n{recent_text}\n\n"
        "يمكنك إجراء اختبار فوري لإرسال تنبيه أو مراسلة مستخدم محدد:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 إرسال تنبيه تجريبي لهاتفي الآن", callback_data="adm_test_alert"),
        types.InlineKeyboardButton("📨 إرسال إشعار فوري لمستخدم محدد", callback_data="adm_send_user_alert"),
        types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
    )
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_test_alert")
@safe_callback
def handle_adm_test_alert(call):
    if not is_admin(call.from_user.id):
        return
    test_text = (
        "🔔 <b>تنبيه اختباري فوري!</b> ⚡️\n\n"
        "هذا تنبيه صوتي تجريبي للتأكد من عمل نظام التنبيهات الفورية (Push Alerts) للأدمن والعملاء بكفاءة تامة بدون أي تأخير."
    )
    send_instant_notification(
        call.from_user.id,
        test_text,
        notification_type="admin_test_alert",
        loud=True
    )
    bot.answer_callback_query(call.id, "✅ تم إرسال التنبيه التجريبي لهاتفك بصوت واهتزاز!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "adm_send_user_alert")
@safe_callback
def handle_adm_send_user_alert_prompt(call):
    if not is_admin(call.from_user.id):
        return
    admin_action_states[call.from_user.id] = {"action": "send_custom_notification"}
    bot.send_message(
        call.message.chat.id,
        "📨 <b>إرسال إشعار فوري لمستخدم</b>\n\n"
        "أرسل Telegram ID للمستخدم ثم نص الرسالة مفصولين بـ | (مثال):\n"
        "<code>1049281 | مرحباً بك، تم تفعيل اشتراكك وجاهز للاستخدام!</code>\n\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "btn_my_orders")
@safe_callback
def handle_notification_my_orders(call):
    handle_my_orders(call.message)
    bot.answer_callback_query(call.id)

# ================= Unavailable Package Handler =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("pkg_unavailable_"))
@safe_callback
def handle_unavailable_package_click(call):
    try:
        parts = call.data.replace("pkg_unavailable_", "").split("_", 1)
        if len(parts) < 2:
            bot.answer_callback_query(call.id, "⚠️ عذراً، هذه الباقة غير متوفرة حالياً.", show_alert=True)
            return
        prod_key = parts[0]
        pkg_id = parts[1]
        store = get_store_data()
        prod = store.get(prod_key)
        pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None) if prod else None
        label = pkg["label"] if pkg else "الباقة"

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔔 احجز / أبلغني عند التوفر", callback_data=f"waitlist_{prod_key}_{pkg_id}"),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=f"prod_{prod_key}")
        )
        bot.answer_callback_query(call.id)
        safe_edit_message_text(
            call,
            f"⚠️ <b>{label}</b> غير متوفرة حالياً.\n\n"
            "يمكنك الضغط على زر <b>🔔 احجز / أبلغني</b> وسيتم إشعارك فور توفرها!",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Error in handle_unavailable_package_click: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "⚠️ عذراً، هذه الباقة غير متوفرة حالياً.", show_alert=True)
        except Exception:
            pass

# ================= Waitlist / Backorder Handler =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("waitlist_"))
@safe_callback
def handle_waitlist_request(call):
    try:
        user_id = call.from_user.id
        parts = call.data.replace("waitlist_", "").split("_", 1)
        if len(parts) < 2:
            bot.answer_callback_query(call.id, "خطأ في البيانات.", show_alert=True)
            return
        prod_key = parts[0]
        pkg_id = parts[1]

        store = get_store_data()
        prod = store.get(prod_key)
        pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None) if prod else None
        label = pkg["label"] if pkg else "الباقة"
        prod_name = prod["name"] if prod else prod_key

        waitlist = get_waitlist()
        wl_key = f"{prod_key}_{pkg_id}"
        if wl_key not in waitlist:
            waitlist[wl_key] = []

        # Check if user already in waitlist
        if any(entry.get("user_id") == user_id for entry in waitlist[wl_key]):
            bot.answer_callback_query(call.id, "✅ أنت مسجل بالفعل في قائمة الانتظار لهذه الباقة!", show_alert=True)
            return

        customer = call.from_user
        waitlist[wl_key].append({
            "user_id": user_id,
            "username": customer.username or "",
            "first_name": customer.first_name or "",
            "added_at": utc_now()
        })
        update_waitlist(waitlist)

        bot.answer_callback_query(call.id, "✅ تم تسجيلك في قائمة الانتظار بنجاح!", show_alert=True)

        # Notify user
        try:
            bot.send_message(
                user_id,
                f"✅ <b>تم تسجيلك في قائمة الانتظار</b>\n\n"
                f"📦 المنتج: <b>{prod_name}</b>\n"
                f"🏷️ الباقة: <b>{label}</b>\n\n"
                "سيتم إشعارك فور توفر هذه الباقة! 🔔"
            )
        except Exception:
            pass

        # Notify admin about demand
        demand_count = len(waitlist[wl_key])
        admin_msg = (
            f"🔔 <b>طلب حجز جديد على قائمة الانتظار</b>\n\n"
            f"📦 المنتج: <b>{prod_name}</b>\n"
            f"🏷️ الباقة: <b>{label}</b>\n"
            f"👤 العميل: @{customer.username or 'بدون'} (ID: <code>{user_id}</code>)\n"
            f"📊 إجمالي المنتظرين: <b>{demand_count}</b> شخص"
        )
        send_instant_notification(
            ADMIN_ID,
            admin_msg,
            notification_type="waitlist_request",
            loud=False
        )
    except Exception as e:
        print(f"Error in handle_waitlist_request: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ حدث خطأ. يرجى المحاولة لاحقاً.", show_alert=True)
        except Exception:
            pass

# ================= Granular Tier Availability Management =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_tier_availability")
@safe_callback
def handle_adm_tier_availability_view(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        markup.add(types.InlineKeyboardButton(
            f"📦 {p['name']}",
            callback_data=f"adm_tier_prod_{k}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(
        call,
        "🎛️ <b>إدارة توفر الباقات الفردية</b>\n\nاختر المنتج للتحكم في توفر كل باقة على حدة:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_tier_prod_"))
@safe_callback
def handle_adm_tier_select_product(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    prod_key = call.data.replace("adm_tier_prod_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for pkg in prod.get("packages", []):
        status = "🟢" if pkg.get("available", True) else "🔴"
        avail_text = "متوفر" if pkg.get("available", True) else "غير متوفر"
        markup.add(types.InlineKeyboardButton(
            f"{status} {pkg['label']} — {avail_text}",
            callback_data=f"adm_tier_toggle_{prod_key}_{pkg['id']}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_tier_availability"))
    safe_edit_message_text(
        call,
        f"🎛️ <b>توفر باقات:</b> <b>{prod['name']}</b>\n\n"
        "🟢 = متوفر | 🔴 = غير متوفر\n"
        "اضغط على أي باقة لتغيير حالتها:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_tier_toggle_"))
@safe_callback
def handle_adm_tier_toggle(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.replace("adm_tier_toggle_", "").split("_", 1)
    prod_key = parts[0]
    pkg_id = parts[1]

    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return

    pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None)
    if not pkg:
        bot.answer_callback_query(call.id, "الباقة غير موجودة.", show_alert=True)
        return

    pkg["available"] = not pkg.get("available", True)
    update_store_data(store)

    new_status = "متوفرة ✅" if pkg["available"] else "غير متوفرة ❌"
    bot.answer_callback_query(call.id, f"تم تحديث حالة الباقة إلى: {new_status}")

    # Refresh the view
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in prod.get("packages", []):
        status = "🟢" if p.get("available", True) else "🔴"
        avail_text = "متوفر" if p.get("available", True) else "غير متوفر"
        markup.add(types.InlineKeyboardButton(
            f"{status} {p['label']} — {avail_text}",
            callback_data=f"adm_tier_toggle_{prod_key}_{p['id']}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_tier_availability"))
    safe_edit_message_text(
        call,
        f"🎛️ <b>توفر باقات:</b> <b>{prod['name']}</b>\n\n"
        "🟢 = متوفر | 🔴 = غير متوفر\n"
        "اضغط على أي باقة لتغيير حالتها:",
        reply_markup=markup
    )

# ================= Broadcast / Mass Messaging =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_broadcast")
@safe_callback
def handle_adm_broadcast_prompt(call):
    if not is_admin(call.from_user.id):
        return
    admin_action_states[call.from_user.id] = {"action": "broadcast_text"}
    bot.send_message(
        call.message.chat.id,
        "📢 <b>الإذاعة الجماعية</b>\n\n"
        "أرسل الآن نص الرسالة التي تريد إرسالها لجميع المستخدمين المسجلين.\n\n"
        "💡 يمكنك إرسال:\n"
        "• نص عادي\n"
        "• صورة مع تعليق (أرسل الصورة مباشرة)\n\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

# ================= Product CRUD (Add/Delete) =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_add_product")
@safe_callback
def handle_adm_add_product_start(call):
    if not is_admin(call.from_user.id):
        return
    admin_action_states[call.from_user.id] = {"action": "add_product_name"}
    bot.send_message(
        call.message.chat.id,
        "➕ <b>إضافة منتج جديد</b>\n\n"
        "أرسل الآن <b>اسم المنتج</b> (مثال: <code>نتفليكس Netflix</code>):\n\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_delete_product")
@safe_callback
def handle_adm_delete_product_list(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    if not store:
        safe_edit_message_text(call, "❌ لا توجد منتجات في المتجر حالياً.", reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main")
        ))
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        pkg_count = len(p.get("packages", []))
        markup.add(types.InlineKeyboardButton(
            f"🗑️ {p['name']} ({pkg_count} باقة)",
            callback_data=f"adm_del_prod_{k}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, "🗑️ <b>حذف منتج</b>\n\nاختر المنتج الذي تريد حذفه نهائياً:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_prod_"))
@safe_callback
def handle_adm_delete_product_confirm(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_del_prod_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    pkg_count = len(prod.get("packages", []))
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ نعم، احذف", callback_data=f"adm_confirm_del_prod_{prod_key}"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="adm_delete_product")
    )
    safe_edit_message_text(
        call,
        f"⚠️ <b>تأكيد الحذف</b>\n\n"
        f"هل أنت متأكد من حذف المنتج التالي نهائياً؟\n\n"
        f"📦 <b>{prod['name']}</b>\n"
        f"📊 عدد الباقات: <b>{pkg_count}</b>\n\n"
        f"⚠️ <b>تحذير:</b> لا يمكن التراجع عن هذا الإجراء!",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_confirm_del_prod_"))
@safe_callback
def handle_adm_delete_product_execute(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_confirm_del_prod_", "")
    store = get_store_data()
    if prod_key not in store:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    prod_name = store[prod_key]["name"]
    del store[prod_key]
    update_store_data(store)
    bot.answer_callback_query(call.id, f"تم حذف {prod_name} بنجاح!")
    safe_edit_message_text(
        call,
        f"✅ تم حذف المنتج <b>{prod_name}</b> وجميع باقاته بنجاح!\n\n"
        f"📊 إجمالي المنتجات المتبقية: <b>{len(store)}</b>",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
        )
    )

# ================= Tier CRUD (Add/Delete) =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_add_tier")
@safe_callback
def handle_adm_add_tier_select_product(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    if not store:
        safe_edit_message_text(call, "❌ لا توجد منتجات. أضف منتجاً أولاً.", reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main")
        ))
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        pkg_count = len(p.get("packages", []))
        markup.add(types.InlineKeyboardButton(
            f"📦 {p['name']} ({pkg_count} باقة)",
            callback_data=f"adm_add_tier_{k}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, "➕ <b>إضافة باقة جديدة</b>\n\nاختر المنتج الذي تريد إضافة باقة له:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_add_tier_") and c.data != "adm_add_tier")
@safe_callback
def handle_adm_add_tier_start(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_add_tier_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    admin_action_states[call.from_user.id] = {
        "action": "add_tier_label",
        "prod_key": prod_key
    }
    bot.send_message(
        call.message.chat.id,
        f"➕ <b>إضافة باقة جديدة لـ:</b> <b>{prod['name']}</b>\n\n"
        "أرسل الآن <b>اسم/عنوان الباقة</b> (مثال: <code>حساب خاص 3 شهور</code>):\n\n"
        "أو أرسل /cancel للإلغاء:"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_delete_tier")
@safe_callback
def handle_adm_delete_tier_select_product(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    store = get_store_data()
    if not store:
        safe_edit_message_text(call, "❌ لا توجد منتجات في المتجر.", reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main")
        ))
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for k, p in store.items():
        pkg_count = len(p.get("packages", []))
        if pkg_count > 0:
            markup.add(types.InlineKeyboardButton(
                f"📦 {p['name']} ({pkg_count} باقة)",
                callback_data=f"adm_del_tier_{k}"
            ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, "🗑️ <b>حذف باقة</b>\n\nاختر المنتج الذي تريد حذف باقة منه:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_tier_") and not c.data.startswith("adm_del_tier_conf_"))
@safe_callback
def handle_adm_delete_tier_select_tier(call):
    if not is_admin(call.from_user.id):
        return
    prod_key = call.data.replace("adm_del_tier_", "")
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    packages = prod.get("packages", [])
    if not packages:
        safe_edit_message_text(call, f"❌ لا توجد باقات في منتج <b>{prod['name']}</b>.", reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_delete_tier")
        ))
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for pkg in packages:
        markup.add(types.InlineKeyboardButton(
            f"🗑️ {pkg['label']} ({pkg.get('retail_price', '?')})",
            callback_data=f"adm_del_tier_conf_{prod_key}_{pkg['id']}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_delete_tier"))
    safe_edit_message_text(
        call,
        f"🗑️ <b>حذف باقة من:</b> <b>{prod['name']}</b>\n\nاختر الباقة المراد حذفها:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_tier_conf_"))
@safe_callback
def handle_adm_delete_tier_confirm(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.replace("adm_del_tier_conf_", "").split("_", 1)
    prod_key = parts[0]
    pkg_id = parts[1]
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    pkg = next((p for p in prod.get("packages", []) if p["id"] == pkg_id), None)
    if not pkg:
        bot.answer_callback_query(call.id, "الباقة غير موجودة.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ نعم، احذف", callback_data=f"adm_exec_del_tier_{prod_key}_{pkg_id}"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data=f"adm_del_tier_{prod_key}")
    )
    safe_edit_message_text(
        call,
        f"⚠️ <b>تأكيد حذف الباقة</b>\n\n"
        f"هل أنت متأكد من حذف الباقة التالية نهائياً؟\n\n"
        f"📦 المنتج: <b>{prod['name']}</b>\n"
        f"🏷️ الباقة: <b>{pkg['label']}</b>\n"
        f"💰 السعر: <b>{pkg.get('retail_price', '?')}</b>\n\n"
        f"⚠️ <b>تحذير:</b> لا يمكن التراجع عن هذا الإجراء!",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_exec_del_tier_"))
@safe_callback
def handle_adm_delete_tier_execute(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.replace("adm_exec_del_tier_", "").split("_", 1)
    prod_key = parts[0]
    pkg_id = parts[1]
    store = get_store_data()
    prod = store.get(prod_key)
    if not prod:
        bot.answer_callback_query(call.id, "المنتج غير موجود.", show_alert=True)
        return
    packages = prod.get("packages", [])
    pkg = next((p for p in packages if p["id"] == pkg_id), None)
    if not pkg:
        bot.answer_callback_query(call.id, "الباقة غير موجودة.", show_alert=True)
        return
    pkg_label = pkg["label"]
    packages.remove(pkg)
    update_store_data(store)
    remaining = len(packages)
    bot.answer_callback_query(call.id, f"تم حذف الباقة {pkg_label} بنجاح!")
    safe_edit_message_text(
        call,
        f"✅ تم حذف الباقة <b>{pkg_label}</b> من منتج <b>{prod['name']}</b> بنجاح!\n\n"
        f"📊 عدد الباقات المتبقية: <b>{remaining}</b>",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
        )
    )

# ================= Waitlist Management =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_view_waitlist")
@safe_callback
def handle_adm_view_waitlist(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    waitlist = get_waitlist()
    if not waitlist:
        safe_edit_message_text(
            call,
            "📋 <b>قائمة الانتظار</b>\n\nلا يوجد أي طلبات حجز حالياً.",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main")
            )
        )
        return

    store = get_store_data()
    lines = []
    for wl_key, entries in waitlist.items():
        if not entries:
            continue
        parts = wl_key.split("_", 1)
        if len(parts) == 2:
            p_key, p_id = parts
            prod = store.get(p_key)
            pkg = next((p for p in prod.get("packages", []) if p["id"] == p_id), None) if prod else None
            label = f"{prod['name']} — {pkg['label']}" if prod and pkg else wl_key
        else:
            label = wl_key
        lines.append(f"🔴 <b>{label}</b>: {len(entries)} منتظرين")

    text = "📋 <b>قائمة الانتظار (Waitlist)</b>\n\n" + "\n".join(lines)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📢 إشعار جميع المنتظرين (تحديث المخزون)", callback_data="adm_notify_waitlist"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_notify_waitlist")
@safe_callback
def handle_adm_notify_waitlist_prompt(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    waitlist = get_waitlist()
    if not waitlist:
        bot.answer_callback_query(call.id, "لا يوجد طلبات حجز.", show_alert=True)
        return

    store = get_store_data()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for wl_key, entries in waitlist.items():
        if not entries:
            continue
        parts = wl_key.split("_", 1)
        if len(parts) == 2:
            p_key, p_id = parts
            prod = store.get(p_key)
            pkg = next((p for p in prod.get("packages", []) if p["id"] == p_id), None) if prod else None
            label = f"{prod['name']} — {pkg['label']}" if prod and pkg else wl_key
        else:
            label = wl_key
        markup.add(types.InlineKeyboardButton(
            f"📢 إشعار {len(entries)} منتظرين — {label}",
            callback_data=f"adm_notify_wl_{wl_key}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_view_waitlist"))
    safe_edit_message_text(call, "📢 <b>اختر الباقة التي تريد إشعار منتظريها:</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_notify_wl_"))
@safe_callback
def handle_adm_notify_waitlist_execute(call):
    if not is_admin(call.from_user.id):
        return
    wl_key = call.data.replace("adm_notify_wl_", "")
    waitlist = get_waitlist()
    entries = waitlist.get(wl_key, [])
    if not entries:
        bot.answer_callback_query(call.id, "لا يوجد منتظرين لهذه الباقة.", show_alert=True)
        return

    store = get_store_data()
    parts = wl_key.split("_", 1)
    if len(parts) == 2:
        p_key, p_id = parts
        prod = store.get(p_key)
        pkg = next((p for p in prod.get("packages", []) if p["id"] == p_id), None) if prod else None
        label = f"{prod['name']} — {pkg['label']}" if prod and pkg else wl_key
    else:
        label = wl_key

    sent_count = 0
    for entry in entries:
        try:
            bot.send_message(
                entry["user_id"],
                f"🎉 <b>خبر سار! الباقة أصبحت متوفرة الآن!</b>\n\n"
                f"📦 <b>{label}</b>\n\n"
                "💳 يمكنك الآن الشراء مباشرة من المتجر!\n"
                "👇 اضغط على زر تصفح المنتجات للبدء:",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🛍 تصفح المنتجات", callback_data="back_to_products")
                )
            )
            sent_count += 1
        except Exception:
            pass

    # Clear the waitlist for this product/tier
    waitlist[wl_key] = []
    update_waitlist(waitlist)

    bot.answer_callback_query(call.id, f"تم إشعار {sent_count} مستخدم بنجاح!", show_alert=True)
    safe_edit_message_text(
        call,
        f"✅ <b>تم إشعار المنتظرين بنجاح!</b>\n\n"
        f"📦 الباقة: <b>{label}</b>\n"
        f"👥 تم إشعار: <b>{sent_count}</b> من <b>{len(entries)}</b>\n\n"
        "تم مسح قائمة الانتظار لهذه الباقة.",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_view_waitlist")
        )
    )


# ================= Multi-Admin Panel Handlers =================
@bot.callback_query_handler(func=lambda c: c.data == "adm_manage_admins")
@safe_callback
def handle_adm_manage_admins(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    admins = get_admins()

    text = "👑 <b>إدارة المشرفين والمدراء (Multi-Admin System)</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
    text += "قائمة المشرفين الحاليين المصرح لهم بإدارة المتجر واستقبال الطلبات:\n\n"

    idx = 1
    owner_str = str(ADMIN_ID)
    if owner_str in admins:
        o = admins[owner_str]
        text += f"{idx}. 👑 <b>{o.get('name', 'المدير العام')} (المالك الأساسي)</b>\n"
        text += f"   🆔 ID: <code>{owner_str}</code>\n"
        if o.get("username"):
            text += f"   👤 المعرف: @{o['username']}\n"
        text += "\n"
        idx += 1

    for uid, ainfo in admins.items():
        if uid == owner_str:
            continue
        u_name = ainfo.get("name", "مشرف")
        u_uname = f"@{ainfo['username']}" if ainfo.get("username") else "بدون معرف"
        added_date = (ainfo.get("added_at") or "")[:10]
        date_str = f" | تاريخ الإضافة: {added_date}" if added_date else ""
        text += f"{idx}. 🛡 <b>{u_name}</b>\n"
        text += f"   🆔 ID: <code>{uid}</code>\n"
        text += f"   👤 المعرف: {u_uname}{date_str}\n\n"
        idx += 1

    text += "━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة مشرف جديد", callback_data="adm_add_admin_prompt"),
        types.InlineKeyboardButton("🗑️ حذف مشرف", callback_data="adm_del_admin_menu")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main"))
    safe_edit_message_text(call, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "adm_add_admin_prompt")
@safe_callback
def handle_adm_add_admin_prompt(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    admin_action_states[call.from_user.id] = {"action": "add_admin_id"}
    safe_edit_message_text(
        call,
        "➕ <b>إضافة مشرف جديد</b>\n\n"
        "أرسل الآن <b>معرف المستخدم (Telegram Chat ID / User ID)</b> الخاص به (أرقام فقط، مثال: <code>123456789</code>):\n\n"
        "💡 يمكن للمستخدم معرفة الـ ID الخاص به عبر الدخول للبوت والضغط على /start أو عبر بوت @userinfobot.\n\n"
        "أو أرسل /cancel للإلغاء.",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع لقائمة المشرفين", callback_data="adm_manage_admins")
        )
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm_del_admin_menu")
@safe_callback
def handle_adm_del_admin_menu(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    admins = get_admins()
    owner_str = str(ADMIN_ID)
    other_admins = {k: v for k, v in admins.items() if k != owner_str}

    if not other_admins:
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_manage_admins")
        )
        safe_edit_message_text(
            call,
            "ℹ️ <b>لا يوجد مشرفين إضافيين حالياً لحذفهم.</b>\n(يوجد فقط المالك الأساسي للنظام وهو محمي من الحذف).",
            reply_markup=markup
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for uid, ainfo in other_admins.items():
        name = ainfo.get("name", "مشرف")
        markup.add(types.InlineKeyboardButton(
            f"🗑️ {name} ({uid})",
            callback_data=f"adm_del_adm_conf_{uid}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_manage_admins"))
    safe_edit_message_text(call, "🗑️ <b>اختر المشرف المراد حذفه من النظام:</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_adm_conf_"))
@safe_callback
def handle_adm_del_admin_conf(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    target_uid = call.data.replace("adm_del_adm_conf_", "")
    admins = get_admins()
    ainfo = admins.get(target_uid, {})
    name = ainfo.get("name", "مشرف")

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ نعم، احذف المشرف", callback_data=f"adm_del_adm_exec_{target_uid}"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="adm_manage_admins")
    )
    safe_edit_message_text(
        call,
        f"⚠️ <b>تأكيد حذف المشرف</b>\n\n"
        f"هل أنت متأكد من حذف المشرف <b>{name}</b> (<code>{target_uid}</code>)؟\n"
        f"سيتم سحب كافة صلاحيات لوحة التحكم منه وإيقاف وصول إشعارات الطلبات له فوراً.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_adm_exec_"))
@safe_callback
def handle_adm_del_admin_exec(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    target_uid = call.data.replace("adm_del_adm_exec_", "")
    success, msg_text = remove_existing_admin(target_uid)
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🔙 رجوع لقائمة المشرفين", callback_data="adm_manage_admins")
    )
    if success:
        safe_edit_message_text(
            call,
            f"✅ <b>تم حذف المشرف بنجاح!</b>\n🆔 المعرف: <code>{target_uid}</code>\nتم إلغاء صلاحياته الإدارية فوراً.",
            reply_markup=markup
        )
    else:
        safe_edit_message_text(
            call,
            f"❌ <b>تعذر الحذف:</b> {msg_text}",
            reply_markup=markup
        )

# ================= Admin Text Input Router =================
def handle_admin_text_inputs(message):
    admin_id = message.from_user.id
    state = admin_action_states.get(admin_id)
    if not state:
        return

    action = state.get("action")
    text = (message.text or "").strip()

    if action == "set_role":
        target_role = state["target_role"]
        admin_action_states.pop(admin_id, None)

        # Look up by ID or Username
        target_uid = None
        target_name = "مستخدم"
        target_username = ""

        if text.isdigit():
            target_uid = int(text)
        else:
            clean_u = text.replace("@", "")
            with database_connection() as conn:
                row = conn.execute("SELECT user_id, customer_first_name, customer_username FROM payment_requests WHERE customer_username = ? LIMIT 1", (clean_u,)).fetchone()
                if row:
                    target_uid = row["user_id"]
                    target_name = row["customer_first_name"]
                    target_username = row["customer_username"]

        if not target_uid:
            bot.reply_to(message, "⚠️ لم يتم العثور على هذا المستخدم في سجلات المتجر أو الرقم غير صالح.")
            return

        set_user_role(target_uid, target_role, name=target_name, username=target_username)
        role_names = {"reseller": "تاجر / مسوق معتمد", "friend": "صديق معتمد", "customer": "عميل عادي"}
        bot.reply_to(message, f"✅ تم تعيين رتبة المستخدم <code>{target_uid}</code> بنجاح إلى: <b>{role_names.get(target_role)}</b>")

        # Notify user if possible
        try:
            bot.send_message(
                target_uid,
                f"🎉 <b>تهانينا! تم تحديث رتبتك في المتجر إلى: {role_names.get(target_role)}</b>\n\n"
                "تم تفعيل فئة الأسعار الخاصة برتبتك تلقائياً على جميع المنتجات والباقات!"
            )
        except Exception:
            pass
        return

    if action == "add_admin_id":
        admin_action_states.pop(admin_id, None)
        clean_id = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()
        if not clean_id.isdigit():
            bot.reply_to(message, "⚠️ معرف المشرف يجب أن يتكون من أرقام فقط (Telegram ID).")
            return

        target_uid = int(clean_id)
        cand_name = "مشرف جديد"
        cand_username = ""
        with database_connection() as conn:
            row = conn.execute("SELECT customer_first_name, customer_username FROM payment_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1", (target_uid,)).fetchone()
            if row:
                cand_name = row["customer_first_name"] or cand_name
                cand_username = row["customer_username"] or cand_username

        roles = get_user_roles()
        if str(target_uid) in roles:
            cand_name = roles[str(target_uid)].get("name") or cand_name
            cand_username = roles[str(target_uid)].get("username") or cand_username

        success, msg_text = add_new_admin(target_uid, name=cand_name, username=cand_username)
        if success:
            bot.reply_to(
                message,
                f"✅ <b>تمت إضافة المشرف بنجاح!</b>\n\n"
                f"👤 الاسم: <b>{cand_name}</b>\n"
                f"🆔 Chat ID: <code>{target_uid}</code>\n"
                f"📱 المعرف: @{cand_username or 'بدون'}\n\n"
                "👑 يمتلك الآن كافة صلاحيات لوحة التحكم واستقبال إشعارات وتأكيد طلبات الشراء."
            )
            try:
                bot.send_message(
                    target_uid,
                    "🎉 <b>تم تعيينك كمشرف (Admin) في متجر GoPro Store!</b>\n\n"
                    "يمكنك الآن استخدام أمر /admin أو زر لوحة الإدارة لإدارة المتجر واستقبال وإدارة طلبات الشراء فوراً."
                )
            except Exception:
                pass
        else:
            bot.reply_to(message, f"⚠️ {msg_text}")
        return

    if action == "update_price":
        prod_key = state["prod_key"]
        pkg_id = state["pkg_id"]
        field = state["field"]
        admin_action_states.pop(admin_id, None)

        clean_price = text
        if not clean_price.endswith("ج"):
            clean_price += "ج"

        store = get_store_data()
        prod = store.get(prod_key)
        updated_pkg = None
        if prod:
            for pkg in prod.get("packages", []):
                if pkg["id"] == pkg_id:
                    pkg[field] = clean_price
                    updated_pkg = pkg
                    break
            if updated_pkg is not None:
                update_store_data(store)

        tier_names = {
            "retail_price": "سعر العميل",
            "reseller_price": "سعر التاجر",
            "friend_price": "سعر الصديق",
            "cashback": "كاش باك الباقة"
        }
        if updated_pkg is not None:
            bot.reply_to(message, f"✅ تم تحديث <b>{tier_names.get(field, field)}</b> لباقة <b>{updated_pkg.get('label', pkg_id)}</b> بنجاح إلى: <b>{clean_price}</b>")
        else:
            bot.reply_to(message, f"❌ تعذر التحديث: لم يتم العثور على الباقة <code>{pkg_id}</code> ضمن منتج <code>{prod_key}</code>.")
        return

    if action == "edit_description":
        prod_key = state["prod_key"]
        admin_action_states.pop(admin_id, None)

        new_desc = text
        store = get_store_data()
        prod = store.get(prod_key)
        if not prod:
            bot.reply_to(message, "⚠️ المنتج غير موجود.")
            return

        prod["description"] = new_desc
        update_store_data(store)
        bot.reply_to(
            message,
            f"✅ تم تحديث وصف المنتج <b>{prod['name']}</b> بنجاح!\n\n"
            f"📝 <b>الوصف الجديد:</b>\n{new_desc}"
        )
        return

    if action == "create_coupon_step1":
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ تنسيق غير صحيح. يرجى إرسال: الكود, اسم المؤثر, قيمة الخصم")
            return

        code = parts[0].upper()
        influencer = parts[1]
        try:
            discount = float(parts[2].replace("ج", "").strip())
        except ValueError:
            bot.reply_to(message, "⚠️ قيمة الخصم يجب أن تكون رقماً.")
            return

        admin_action_states[admin_id] = {
            "action": "create_coupon_step2",
            "code": code,
            "influencer": influencer,
            "discount": discount,
            "selected_products": []
        }
        bot.reply_to(
            message,
            f"🎟 <b>إنشاء كوبون: {code}</b>\n"
            f"🏷 المؤثر: <b>{influencer}</b> | الخصم: <b>{discount}ج</b>\n\n"
            "👇 اختر المنتجات التي ينطبق عليها هذا الكوبون، أو اضغط <b>الكل</b> لجميع المنتجات:",
            reply_markup=build_coupon_product_selection_keyboard(admin_id)
        )
        return

    if action == "lookup_customer":
        query = text.strip()
        if query == "/cancel":
            admin_action_states.pop(admin_id, None)
            bot.reply_to(message, "تم إلغاء البحث.", reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
            ))
            return

        report, found = generate_customer_report_detailed(query)
        markup = types.InlineKeyboardMarkup(row_width=2)
        if not found:
            markup.add(
                types.InlineKeyboardButton("🔍 بحث عن عميل آخر", callback_data="adm_lookup_customer"),
                types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
            )
            bot.reply_to(message, report, reply_markup=markup)
            return

        admin_action_states.pop(admin_id, None)
        markup.add(
            types.InlineKeyboardButton("🔍 بحث جديد", callback_data="adm_lookup_customer"),
            types.InlineKeyboardButton("🔙 رجوع للوحة الإدارة", callback_data="adm_back_to_main")
        )
        bot.reply_to(message, report, reply_markup=markup)
        return

    if action == "send_custom_notification":
        admin_action_states.pop(admin_id, None)
        if "|" not in text:
            bot.reply_to(message, "⚠️ يرجى استخدام الفاصل | بين المعرف والرسالة (مثال: 1049281 | نص التنبيه).")
            return
        target_uid_str, msg_content = [p.strip() for p in text.split("|", 1)]
        if not target_uid_str.isdigit():
            bot.reply_to(message, "⚠️ المعرف يجب أن يكون رقماً صحيحاً (Telegram ID).")
            return
        target_uid = int(target_uid_str)
        formatted_alert = (
            "🔔 <b>إشعار رسمي من إدارة المتجر:</b>\n\n"
            f"{msg_content}\n\n"
            "💬 للتواصل أو الاستفسار: @gopro_store_team"
        )
        sent = send_instant_notification(target_uid, formatted_alert, notification_type="admin_direct_message", loud=True)
        if sent:
            bot.reply_to(message, f"✅ تم إرسال التنبيه الفوري بنجاح إلى المستخدم <code>{target_uid}</code>!")
        else:
            bot.reply_to(message, f"❌ تعذر إرسال التنبيه إلى <code>{target_uid}</code> (قد يكون المستخدم لم يبدأ البوت بعد).")
        return

    if action == "broadcast_text":
        admin_action_states.pop(admin_id, None)
        if not text:
            bot.reply_to(message, "⚠️ النص فارغ. يرجى إرسال نص الرسالة.")
            return

        # Get all user IDs from database
        user_ids = set()
        with database_connection() as conn:
            rows = conn.execute("SELECT DISTINCT user_id FROM payment_requests").fetchall()
            for row in rows:
                user_ids.add(row["user_id"])
        # Also add from user_roles
        roles = get_user_roles()
        for uid in roles.keys():
            if uid.isdigit():
                user_ids.add(int(uid))

        sent_count = 0
        failed_count = 0
        for uid in user_ids:
            try:
                bot.send_message(uid, text, parse_mode="HTML")
                sent_count += 1
            except Exception:
                failed_count += 1

        bot.reply_to(
            message,
            f"📊 <b>تقرير الإذاعة الجماعية (نص)</b>\n\n"
            f"✅ تم الإرسال بنجاح: <b>{sent_count}</b> مستخدم\n"
            f"❌ فشل الإرسال: <b>{failed_count}</b> مستخدم\n"
            f"👥 إجمالي المحاولات: <b>{sent_count + failed_count}</b>"
        )
        return

    # ---- Add Product Flow ----
    if action == "add_product_name":
        if len(text) < 2 or len(text) > 100:
            bot.reply_to(message, "⚠️ اسم المنتج يجب أن يكون بين 2 و 100 حرف. أرسل الاسم مرة أخرى:")
            return
        admin_action_states[admin_id] = {
            "action": "add_product_key",
            "product_name": text
        }
        bot.reply_to(
            message,
            f"✅ اسم المنتج: <b>{text}</b>\n\n"
            "أرسل الآن <b>المفتاح الفريد</b> للمنتج (بالإنجليزية، بدون مسافات):\n"
            "مثال: <code>netflix</code> أو <code>spotify</code>\n\n"
            "أو أرسل /cancel للإلغاء:"
        )
        return

    if action == "add_product_key":
        clean_key = text.lower().replace(" ", "_")
        if not re.match(r'^[a-z0-9_]+$', clean_key):
            bot.reply_to(message, "⚠️ المفتاح يجب أن يحتوي على أحرف إنجلية صغيرة وأرقام وشرطة سفلية فقط. أرسل مرة أخرى:")
            return
        store = get_store_data()
        if clean_key in store:
            bot.reply_to(message, f"⚠️ المفتاح <code>{clean_key}</code> مستخدم بالفعل. أرسل مفتاحاً آخر:")
            return
        product_name = state.get("product_name", "منتج جديد")
        admin_action_states[admin_id] = {
            "action": "add_product_desc",
            "product_name": product_name,
            "product_key": clean_key
        }
        bot.reply_to(
            message,
            f"✅ المفتاح: <code>{clean_key}</code>\n\n"
            "أرسل الآن <b>وصف المنتج</b>:\n\n"
            "أو أرسل /cancel للإلغاء:"
        )
        return

    if action == "add_product_desc":
        product_name = state.get("product_name", "منتج جديد")
        product_key = state.get("product_key", "new_product")
        admin_action_states[admin_id] = {
            "action": "add_product_photo",
            "product_name": product_name,
            "product_key": product_key,
            "description": text
        }
        bot.reply_to(
            message,
            f"✅ الوصف تم حفظه.\n\n"
            "🖼️ أرسل الآن <b>صورة للمنتج</b> (كبصورة Photo مباشرة):\n\n"
            "أو أرسل <code>/skip</code> لتخطي إضافة الصورة:\n"
            "أو أرسل /cancel للإلغاء:"
        )
        return

    if action == "add_product_photo":
        if text.lower() == "/skip":
            product_name = state.get("product_name", "منتج جديد")
            product_key = state.get("product_key", "new_product")
            description = state.get("description", "")
            admin_action_states.pop(admin_id, None)

            store = get_store_data()
            store[product_key] = {
                "name": product_name,
                "available": True,
                "photo": "",
                "description": description,
                "packages": []
            }
            update_store_data(store)

            bot.reply_to(
                message,
                f"✅ تم إضافة المنتج <b>{product_name}</b> بنجاح!\n\n"
                f"🔑 المفتاح: <code>{product_key}</code>\n"
                f"📦 الباقات: 0 (يمكنك إضافة باقات لاحقاً)\n\n"
                "💡 استخدم <b>➕ إضافة باقة جديدة</b> لإضافة باقات لهذا المنتج."
            )
            return
        else:
            bot.reply_to(message, "⚠️ يرجى إرسال صورة (كبصورة Photo) أو إرسال /skip للتخطي:")
            return

    # ---- Add Tier Flow ----
    if action == "add_tier_label":
        if len(text) < 2 or len(text) > 100:
            bot.reply_to(message, "⚠️ اسم الباقة يجب أن يكون بين 2 و 100 حرف. أرسل مرة أخرى:")
            return
        prod_key = state.get("prod_key")
        admin_action_states[admin_id] = {
            "action": "add_tier_prices",
            "prod_key": prod_key,
            "tier_label": text
        }
        bot.reply_to(
            message,
            f"✅ اسم الباقة: <b>{text}</b>\n\n"
            "أرسل الآن الأسعار بالتنسيق التالي:\n"
            "<code>سعر_العميل, سعر_التاجر, سعر_الصديق</code>\n"
            "أو مع تحديد قيمة الكاش باك:\n"
            "<code>سعر_العميل, سعر_التاجر, سعر_الصديق, كاش_باك</code>\n\n"
            "مثال: <code>300ج, 250ج, 220ج, 20ج</code>\n\n"
            "أو أرسل /cancel للإلغاء:"
        )
        return

    if action == "add_tier_prices":
        prod_key = state.get("prod_key")
        tier_label = state.get("tier_label", "باقة جديدة")
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ يرجى إرسال 3 أسعار على الأقل مفصولين بفاصلة:\n<code>سعر_العميل, سعر_التاجر, سعر_الصديق [, كاش_باك]</code>")
            return

        retail_price = parts[0].strip()
        reseller_price = parts[1].strip()
        friend_price = parts[2].strip()
        cashback_val = parts[3].strip() if len(parts) >= 4 else "0ج"

        if not retail_price.endswith("ج"):
            retail_price += "ج"
        if not reseller_price.endswith("ج"):
            reseller_price += "ج"
        if not friend_price.endswith("ج"):
            friend_price += "ج"
        if not cashback_val.endswith("ج"):
            cashback_val += "ج"

        store = get_store_data()
        prod = store.get(prod_key)
        if not prod:
            admin_action_states.pop(admin_id, None)
            bot.reply_to(message, "⚠️ المنتج غير موجود. ربما تم حذفه.")
            return

        # Generate unique tier ID
        existing_ids = {p["id"] for p in prod.get("packages", [])}
        base_id = prod_key + "_custom"
        counter = 1
        tier_id = f"{base_id}_{counter}"
        while tier_id in existing_ids:
            counter += 1
            tier_id = f"{base_id}_{counter}"

        new_package = {
            "id": tier_id,
            "label": tier_label,
            "retail_price": retail_price,
            "reseller_price": reseller_price,
            "friend_price": friend_price,
            "cashback": cashback_val,
            "requires_email": False,
            "desc": "",
            "available": True
        }

        if "packages" not in prod:
            prod["packages"] = []
        prod["packages"].append(new_package)
        update_store_data(store)

        admin_action_states.pop(admin_id, None)
        bot.reply_to(
            message,
            f"✅ تم إضافة الباقة بنجاح!\n\n"
            f"📦 المنتج: <b>{prod['name']}</b>\n"
            f"🏷️ الباقة: <b>{tier_label}</b>\n"
            f"🆔 المفتاح: <code>{tier_id}</code>\n"
            f"💰 سعر العميل: <b>{retail_price}</b>\n"
            f"💼 سعر التاجر: <b>{reseller_price}</b>\n"
            f"🤝 سعر الصديق: <b>{friend_price}</b>\n"
            f"🎁 كاش باك الباقة: <b>{cashback_val}</b>\n\n"
            f"📊 إجمالي باقات المنتج: <b>{len(prod['packages'])}</b>"
        )
        return

# ================= Entry Point =================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 GoPro Store Telegram Bot is starting...")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"💰 Vodafone Cash: {VODAFONE_CASH}")
    print("=" * 60)
    keep_alive()
    bot.infinity_polling(skip_pending=True)
