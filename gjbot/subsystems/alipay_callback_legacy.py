# alipay_callback_handler.py
from flask import Flask, request, jsonify # jsonify可能用不上，但先留着
import logging
import datetime
import os 
import base64
import json 
import urllib.parse

# 确保您的项目结构允许这样导入，或者调整PYTHONPATH
# 例如，如果 alipay_callback_handler.py 和 database.py 都在 GJTEAM- 目录下
try:
    import database 
except ImportError:
    logging.critical("CRITICAL: Failed to import 'database.py'. Ensure it's in the same directory or PYTHONPATH.")
    # 如果 database.py 导入失败，后续所有数据库操作都会失败
    # 定义一个假的 database 模块，让脚本至少能启动并记录更详细的错误
    class FakeDB:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                logging.error(f"Database module not loaded. Call to '{name}' failed.")
                if name == "db_update_user_balance": return False
                if name.startswith("db_get_") or name.startswith("db_is_"): return None
                return False # 或者 None，取决于函数期望
            return method
    database = FakeDB()


# 导入支付宝SDK的验签工具
# 我们将使用 alipay-sdk-python (官方SDK) 的验签方法
try:
    from alipay.aop.api.util.SignatureUtils import verify_with_rsa
    ALIPAY_SDK_VERIFY_AVAILABLE = True
except ImportError:
    logging.critical("CRITICAL: Failed to import verify_with_rsa from alipay.aop.api.util.SignatureUtils. "
                  "Ensure alipay-sdk-python is installed in the correct virtual environment. "
                  "Signature verification will FAIL.")
    ALIPAY_SDK_VERIFY_AVAILABLE = False
    def verify_with_rsa(content_bytes, sign_bytes, public_key_str, sign_type="RSA2"): # Fake function
        logging.error("verify_with_rsa is not available due to import error. Signature verification will ALWAYS FAIL.")
        return False

app = Flask(__name__)

# 配置日志记录
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

# --- 配置变量 ---
# 【重要】支付宝公钥字符串 - 用于验证支付宝回调的签名
# 从支付宝开放平台获取，确保是纯Base64编码的字符串 (不含头尾标记和换行)
# 或者，如果是从PEM文件读取，确保此变量在被 verify_with_rsa 使用时是纯Base64格式
ALIPAY_PUBLIC_KEY_STR = os.environ.get("ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY") 
if not ALIPAY_PUBLIC_KEY_STR:
    ALIPAY_PUBLIC_KEY_STR = "请在这里替换为您的支付宝公钥的纯Base64字符串(用于回调验签)"
    logging.warning("ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY environment variable not set. Using placeholder. THIS WILL FAIL VERIFICATION.")

# 【重要】您的支付宝应用的APPID - 用于核对回调
MY_APP_ID = os.environ.get("ALIPAY_APP_ID")
if not MY_APP_ID:
    MY_APP_ID = "请在这里替换为您的支付宝应用APPID"
    logging.warning("ALIPAY_APP_ID environment variable not set. Using placeholder.")


# Discord机器人经济系统的默认初始余额 (与 role_manager_bot.py 中的值保持一致)
ECONOMY_DEFAULT_BALANCE = int(os.environ.get("ECONOMY_DEFAULT_BALANCE", "100"))
# 您的经济货币与人民币的兑换比例，例如 1 CNY = 100 个游戏币
# 如果您的经济单位就是CNY，则设为 1
RECHARGE_CONVERSION_RATE = int(os.environ.get("RECHARGE_CONVERSION_RATE", "100")) 

if ALIPAY_PUBLIC_KEY_STR == "请在这里替换为您的支付宝公钥的纯Base64字符串(用于回调验签)":
    logging.critical("FATAL: ALIPAY_PUBLIC_KEY_STR is not configured! Callback verification will fail.")
if MY_APP_ID == "请在这里替换为您的支付宝应用APPID":
    logging.critical("FATAL: MY_APP_ID is not configured! Callback verification will fail.")

# --- 辅助函数 ---
def check_and_process_order(data_form: dict) -> bool:
    """
    处理已验签的订单数据，更新数据库并给用户上分。
    返回 True 表示业务处理逻辑已执行（无论最终是否成功上分，只要我们按预期处理了通知），
    返回 False 表示发生了阻止我们按预期处理通知的严重错误（例如关键数据缺失）。
    支付宝通常期望一直收到 "success"，除非是协议级别的错误。
    """
    out_trade_no = data_form.get('out_trade_no')
    total_amount_str = data_form.get('total_amount') 
    alipay_trade_no = data_form.get('trade_no')     
    passback_params_encoded = data_form.get('passback_params') # 这是URL编码后的

    logging.info(f"Processing verified order: out_trade_no='{out_trade_no}', total_amount='{total_amount_str}', alipay_trade_no='{alipay_trade_no}'")

    if not (out_trade_no and total_amount_str and alipay_trade_no):
        logging.error(f"CRITICAL DATA MISSING from Alipay callback for out_trade_no (or other field): '{out_trade_no}'. Data: {data_form}")
        return False # 指示关键数据缺失，这不应该发生在一个合法的已验签回调中

    # 1. 解析 passback_params (如果存在且需要) 以获取 discord_user_id, guild_id, expected_amount
    discord_user_id = None
    discord_guild_id = None
    expected_cny_amount_from_passback = None # 这是用户当初请求的CNY金额

    if passback_params_encoded:
        try:
            decoded_passback_params = urllib.parse.unquote_plus(passback_params_encoded)
            passback_data = json.loads(decoded_passback_params)
            discord_user_id = int(passback_data.get("discord_user_id"))
            discord_guild_id = int(passback_data.get("discord_guild_id"))
            expected_cny_amount_from_passback = float(passback_data.get("expected_amount_cny"))
            logging.info(f"Parsed passback_params for {out_trade_no}: user_id={discord_user_id}, guild_id={discord_guild_id}, expected_amount={expected_cny_amount_from_passback}")
        except Exception as e_pb:
            logging.error(f"Error parsing passback_params '{passback_params_encoded}' for {out_trade_no}: {e_pb}. Will try to find order by out_trade_no only.")
            # 如果解析失败，我们将依赖仅通过 out_trade_no 查找订单
    else:
        logging.warning(f"No passback_params received for out_trade_no '{out_trade_no}'. Will rely solely on out_trade_no for order lookup.")

    # 2. 根据 out_trade_no 从数据库查找原始充值请求记录
    #    这个函数需要在 database.py 中实现
    recharge_req_db = database.db_get_recharge_request_by_out_trade_no(out_trade_no)

    if not recharge_req_db:
        logging.error(f"Order with out_trade_no '{out_trade_no}' NOT FOUND in our database. Ignoring notification, but this is unusual for a verified callback.")
        return True # 我们“处理”了通知（即决定忽略它）

    logging.info(f"Found original request in DB for out_trade_no '{out_trade_no}': {dict(recharge_req_db)}")
    internal_request_id = recharge_req_db['request_id'] # 获取数据库中的主键ID

    # 3. 检查订单状态，防止重复处理基于内部订单状态
    if recharge_req_db['status'] in ['PAID', 'COMPLETED']:
        logging.info(f"Order out_trade_no '{out_trade_no}' (DB ID: {internal_request_id}) "
                     f"is already in status '{recharge_req_db['status']}'. Alipay trade_no: {alipay_trade_no}. Likely a duplicate notification.")
        return True 

    # 4. (更严格的防重) 检查此支付宝交易号是否已被其他订单处理过
    #    这需要 database.db_is_alipay_trade_no_processed(alipay_trade_no)
    if database.db_is_alipay_trade_no_processed(alipay_trade_no): # 注意：这个函数需要确保只检查 PAID 或 COMPLETED 状态的
        logging.warning(f"CRITICAL: Alipay trade_no '{alipay_trade_no}' has ALREADY BEEN PROCESSED for another order. "
                        f"Current out_trade_no: '{out_trade_no}'. This indicates a serious issue or misuse. NOT crediting.")
        # 即使是重复的支付宝交易号，也可能需要更新当前订单的状态为某种错误状态
        # database.db_update_recharge_status(internal_request_id, 'DUPLICATE_ALIPAY_TRADE', admin_note=f"Alipay trade_no {alipay_trade_no} already used.")
        return True 

    # 5. 核对金额
    try:
        paid_cny_amount_float = float(total_amount_str)
        expected_cny_amount_db = float(recharge_req_db['requested_cny_amount'])

        if abs(paid_cny_amount_float - expected_cny_amount_db) > 0.01: # 允许0.01元误差
            logging.error(f"AMOUNT MISMATCH for out_trade_no '{out_trade_no}'. "
                          f"DB Expected: {expected_cny_amount_db:.2f} CNY, Alipay Paid: {paid_cny_amount_float:.2f} CNY. "
                          f"Order will NOT be credited with mismatched amount. Marking as 'AMOUNT_ISSUE'.")
            database.db_update_recharge_request_status( # 使用管理员更新状态的函数，但admin_id设为0或系统ID
                request_id=internal_request_id, 
                new_status='AMOUNT_ISSUE', 
                admin_id=0, # 0 代表系统自动处理
                admin_note=f"金额不符: 期望 {expected_cny_amount_db:.2f}, 实付 {paid_cny_amount_float:.2f}. 支付宝交易号: {alipay_trade_no}"
            )
            return True 
    except (ValueError, TypeError) as e_amount:
        logging.error(f"Invalid amount format for comparison. out_trade_no '{out_trade_no}'. "
                      f"DB Expected: '{recharge_req_db['requested_cny_amount']}', Alipay Paid: '{total_amount_str}'. Error: {e_amount}")
        return False # 关键数据转换失败

    # 6. 将订单标记为“已支付”，并记录支付宝交易信息
    #    passback_params_from_alipay 应该是未URL编码的JSON字符串（如果机器人端传了）
    marked_as_paid = database.db_mark_recharge_as_paid(
        request_id=internal_request_id,
        alipay_trade_no=alipay_trade_no,
        paid_cny_amount=paid_cny_amount_float,
        passback_params_received=decoded_passback_params if passback_params_encoded else None 
    )

    if not marked_as_paid:
        logging.error(f"Failed to mark order out_trade_no '{out_trade_no}' (DB ID: {internal_request_id}) as PAID in database. "
                      "This could be due to IntegrityError (alipay_trade_no already exists and db_is_alipay_trade_no_processed check failed) or other DB issue.")
        return False 

    # 7. 给用户上分
    # 从数据库记录中获取user_id和guild_id，而不是依赖可能解析失败的passback_params
    db_user_id = int(recharge_req_db['user_id'])
    db_guild_id = int(recharge_req_db['guild_id'])
    
    amount_to_credit_internal_units = int(paid_cny_amount_float * RECHARGE_CONVERSION_RATE) 

    logging.info(f"Attempting to credit {amount_to_credit_internal_units} internal units (from {paid_cny_amount_float:.2f} CNY) "
                 f"to user {db_user_id} in guild {db_guild_id}.")
    
    balance_updated = database.db_update_user_balance(
        guild_id=db_guild_id, 
        user_id=db_user_id, 
        amount=amount_to_credit_internal_units, 
        is_delta=True, 
        default_balance=ECONOMY_DEFAULT_BALANCE
    )

    if balance_updated:
        logging.info(f"Successfully credited {amount_to_credit_internal_units} internal units to user {db_user_id} "
                     f"for out_trade_no '{out_trade_no}' (Alipay trade_no: {alipay_trade_no}).")
        # 8. 将订单状态更新为最终的 'COMPLETED'
        database.db_mark_recharge_as_completed(internal_request_id)
        
        # TODO: 实现通知Discord用户充值成功的逻辑 (例如写入消息队列或调用机器人API)
        logging.info(f"Placeholder: Notify Discord user {db_user_id} in guild {db_guild_id} about successful recharge of {amount_to_credit_internal_units} units.")
    else:
        logging.error(f"CRITICAL: FAILED to update balance for user {db_user_id} "
                      f"for out_trade_no '{out_trade_no}' (Alipay trade_no: {alipay_trade_no}) "
                      f"AFTER payment was confirmed and marked as PAID. Manual intervention required!")
        # 订单已标记为PAID，但上分失败。需要人工处理。不应改变PAID状态。
        return False # 指示上分业务失败
            
    return True # 所有核心步骤成功


@app.route('/alipay/notify', methods=['POST'])
def alipay_notify_route():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"--- Alipay Notify Received at {timestamp} (IP: {request.remote_addr}) ---")
    
    try:
        data_form = request.form.to_dict()
        logging.info(f"Received Form Data: {data_form}")

        if not ALIPAY_SDK_VERIFY_AVAILABLE:
            logging.critical("Alipay SDK for verification is not available. CANNOT VERIFY SIGNATURE. Ignoring callback.")
            return "failure", 200 # 返回 "failure" 但给支付宝200 OK避免重试，因为是服务器配置问题

        sign = data_form.pop('sign', None)
        sign_type = data_form.pop('sign_type', None) 

        if not sign or not sign_type:
            logging.error("Signature (sign) or sign_type not found in callback data. Data: {data_form}")
            return "failure", 200 

        if sign_type.upper() != "RSA2":
            logging.error(f"Unsupported sign_type: {sign_type}. Expected RSA2. Data: {data_form}")
            return "failure", 200
        
        if not ALIPAY_PUBLIC_KEY_STR or "请在这里替换" in ALIPAY_PUBLIC_KEY_STR:
            logging.critical("ALIPAY_PUBLIC_KEY_STR (for callback verification) is not configured!")
            return "failure", 200 

        params_to_sign_list = []
        for key, value in sorted(data_form.items()):
            if value is not None and value != '': 
                params_to_sign_list.append(f"{key}={value}")
        
        message_to_verify = "&".join(params_to_sign_list)
        # logging.debug(f"Message to verify for signature: {message_to_verify}")
        # logging.debug(f"Signature from Alipay: {sign}")

        verify_success = False
        try:
            verify_success = verify_with_rsa(
                message_to_verify.encode('utf-8'), 
                base64.b64decode(sign), 
                ALIPAY_PUBLIC_KEY_STR,
                "RSA2" 
            )
            logging.info(f"Signature verification result: {verify_success}")
        except Exception as e_verify:
            logging.error(f"Exception during signature verification: {e_verify}", exc_info=True)
            verify_success = False
                    
        if not verify_success:
            logging.error("Alipay notification signature verification FAILED! Notification will be ignored.")
            return "success", 200 

        # 验签成功，处理业务逻辑
        logging.info("Signature VERIFIED successfully.")
        
        app_id_callback = data_form.get('app_id')
        if MY_APP_ID and app_id_callback != MY_APP_ID:
            logging.error(f"APP ID mismatch in callback! Expected '{MY_APP_ID}', got '{app_id_callback}'. Notification ignored.")
            return "success", 200

        trade_status = data_form.get('trade_status')
        if trade_status in ['TRADE_SUCCESS', 'TRADE_FINISHED']:
            business_logic_ok = check_and_process_order(data_form.copy()) # 传递副本
            if business_logic_ok:
                logging.info(f"Business logic for trade_status '{trade_status}' processed for out_trade_no '{data_form.get('out_trade_no')}'.")
            else:
                logging.error(f"Critical error during business logic processing for out_trade_no '{data_form.get('out_trade_no')}'. Manual check required.")
        else:
            logging.info(f"Received Alipay notification with trade_status '{trade_status}' for out_trade_no '{data_form.get('out_trade_no')}'. Not a final success state, no crediting action taken for this notification.")

        return "success", 200 
    
    except Exception as e:
        logging.error(f"Unhandled top-level error in alipay_notify_route: {e}", exc_info=True)
        # 即使发生未知严重错误，也向支付宝返回"success"以避免它不断重试，但内部必须记录此错误。
        return "success", 200 

# GET路由用于测试连通性
@app.route('/alipay/notify', methods=['GET'])
def alipay_notify_get_test():
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    logging.info(f"Received GET request to /alipay/notify from {client_ip}. Responding with simple OK for test.")
    return "OK (GET request received by Alipay callback server. Actual notifications are POST.)", 200

if __name__ == '__main__':
    # 确保在启动时能访问到 database.py 中的函数
    try:
        database.get_db_connection().close() # 测试一下数据库连接是否基本正常
        logging.info("Database module seems accessible.")
    except Exception as e_db_test:
        logging.critical(f"Failed to perform a test DB connection: {e_db_test}. "
                         "Ensure database.py is correctly set up and accessible.")

    logging.info(f"Starting Alipay Callback Handler on port 8080. "
                 f"APP_ID (for check): {MY_APP_ID}, "
                 f"Alipay Public Key for verify (configured): {not ('请在这里替换' in ALIPAY_PUBLIC_KEY_STR)}, "
                 f"RECHARGE_CONVERSION_RATE: {RECHARGE_CONVERSION_RATE}")
    
    # 对于生产环境，应使用更健壮的WSGI服务器如 Gunicorn 或 uWSGI
    app.run(host='0.0.0.0', port=8080, debug=False) # debug=False for production/systemd