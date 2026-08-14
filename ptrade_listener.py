# -*- coding: utf-8 -*-
"""
PTrade 云端监听策略
===================
部署在国金 PTrade 平台上运行，定时读取本地策略生成的信号文件并执行下单。

使用方法:
  1. 登录国金 PTrade 平台
  2. 新建策略 → 粘贴此文件内容
  3. 设置运行周期: 每分钟 (或 5 分钟)
  4. 设置信号文件路径与本地策略一致

PTrade 下单 API:
  - order(security, amount)          # amount>0买入, <0卖出
  - order_target_value(security, v)  # 调整到目标市值
  - get_position(security)           # 获取持仓
  - get_orders()                     # 获取订单列表
"""

import json
import os
import time
from datetime import datetime

# ============================================================
# 配置区 (在 PTrade 中修改这些参数)
# ============================================================

# 信号文件路径 (与本地策略 gj_trade_config.py 中的 PTRADE_SIGNAL_PATH 一致)
SIGNAL_FILE = "ptrade_signal.json"

# 是否启用 PTrade 日志
ENABLE_LOG = True

# 已处理信号的最大保留天数
MAX_SIGNAL_AGE_DAYS = 7

# 下单前检查: 单笔最大金额 (防止误操作)
MAX_ORDER_AMOUNT = 100000


def log(msg):
    """PTrade 日志输出"""
    if ENABLE_LOG:
        print(f"[PTrade-Listener {datetime.now().strftime('%H:%M:%S')}] {msg}")


def read_signals():
    """读取信号文件"""
    try:
        if not os.path.exists(SIGNAL_FILE):
            return None

        with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data
    except Exception as e:
        log(f"读取信号文件失败: {e}")
        return None


def write_signals(data):
    """回写信号文件 (更新状态)"""
    try:
        with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"回写信号文件失败: {e}")


def parse_ptrade_code(code_str):
    """
    解析 PTrade 代码格式
    例如: "510300.XSHG" → ("510300", "XSHG")
    """
    if "." in code_str:
        return code_str.split(".")
    return code_str, ""


def execute_order(signal):
    """
    执行单笔订单
    使用 PTrade 的 order() 函数 (amount>0买入, <0卖出)
    """
    code = signal["code"]
    side = signal["side"]
    shares = signal["shares"]
    price_ref = signal.get("price_ref", 0)
    name = signal.get("name", "")

    try:
        # 获取当前持仓和价格
        pos = get_position(code) if "get_position" in dir() else None
        current_shares = pos.amount if pos else 0

        # 数量校验
        if side == "SELL":
            if current_shares < shares:
                log(f"❌ 卖出 {code} {name}: 持仓不足 (持仓{current_shares} < 卖出{shares})")
                return False
            # PTrade order: 负数表示卖出
            order_id = order(code, -shares)
        else:
            # 买入金额校验
            est_amount = shares * price_ref
            if est_amount > MAX_ORDER_AMOUNT:
                log(f"❌ 买入 {code} {name}: 金额 {est_amount:.0f} 超过上限 {MAX_ORDER_AMOUNT}")
                return False

            # PTrade order: 正数表示买入
            order_id = order(code, shares)

        if order_id:
            log(f"✅ 下单成功: {side} {code} {name} {shares}股 → order_id={order_id}")
            return True
        else:
            log(f"❌ 下单失败: {side} {code} {name} {shares}股")
            return False

    except Exception as e:
        log(f"❌ 下单异常: {side} {code} {name} → {e}")
        return False


def sync_positions(data):
    """同步当前持仓信息到信号文件"""
    try:
        positions = {}
        # PTrade 无法直接遍历所有持仓，需要手动指定关注的标的
        watch_codes = [
            "510880.XSHG", "510300.XSHG", "510500.XSHG", "512100.XSHG",
            "588000.XSHG", "513500.XSHG", "513100.XSHG", "513030.XSHG",
            "513520.XSHG", "513400.XSHG", "518880.XSHG", "511260.XSHG",
            "511880.XSHG", "513880.XSHG", "159941.XSHE", "159561.XSHE",
            "159655.XSHE",
        ]

        for code in watch_codes:
            try:
                pos = get_position(code)
                if pos and pos.amount > 0:
                    short_code = code.split(".")[0]
                    positions[short_code] = int(pos.amount)
            except Exception:
                pass

        data["synced_positions"] = positions
        data["synced_at"] = datetime.now().isoformat()
        return True
    except Exception as e:
        log(f"同步持仓失败: {e}")
        return False


def cleanup_old_signals(data):
    """清理过期信号"""
    if "pending_signals" not in data:
        return data

    cutoff = datetime.now().timestamp() - MAX_SIGNAL_AGE_DAYS * 86400
    kept = []
    cleaned = 0

    for sig in data.get("pending_signals", []):
        if sig.get("status") == "done":
            try:
                ts = datetime.fromisoformat(sig.get("timestamp", "")).timestamp()
                if ts < cutoff:
                    cleaned += 1
                    continue
            except Exception:
                pass
        kept.append(sig)

    if cleaned > 0:
        log(f"清理过期信号: {cleaned} 条")
        data["pending_signals"] = kept

    return data


# ============================================================
# PTrade 策略入口函数
# ============================================================

def initialize():
    """PTrade 策略初始化"""
    log("=" * 60)
    log("🚀 国金 ETF 动量轮动 PTrade 监听策略启动")
    log(f"   信号文件: {SIGNAL_FILE}")
    log(f"   单笔金额上限: {MAX_ORDER_AMOUNT}")
    log("=" * 60)


def handle_data(context, data):
    """
    PTrade 主循环 (每次定时触发时执行)
    """
    # 1. 读取信号文件
    signal_data = read_signals()
    if signal_data is None:
        return

    pending = signal_data.get("pending_signals", [])
    if not pending:
        return

    # 2. 检查是否有未处理信号
    new_signals = [s for s in pending if s.get("status") == "pending"]
    if not new_signals:
        return

    log(f"发现 {len(new_signals)} 条待处理信号")

    # 3. 按顺序执行 (先卖后买)
    changed = False
    for signal in new_signals:
        success = execute_order(signal)
        if success:
            signal["status"] = "done"
            signal["executed_at"] = datetime.now().isoformat()
            changed = True
        else:
            signal["status"] = "failed"
            signal["failed_at"] = datetime.now().isoformat()
            changed = True

    # 4. 回写信号文件
    if changed:
        signal_data["last_processed"] = datetime.now().isoformat()
        sync_positions(signal_data)
        signal_data = cleanup_old_signals(signal_data)
        write_signals(signal_data)
        log("信号文件已更新")


def after_trading_end(context, data):
    """收盘后处理"""
    signal_data = read_signals()
    if signal_data:
        sync_positions(signal_data)
        signal_data = cleanup_old_signals(signal_data)
        write_signals(signal_data)
        log("收盘后: 持仓已同步，过期信号已清理")