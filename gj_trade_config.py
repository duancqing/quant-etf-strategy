# -*- coding: utf-8 -*-
"""
国金证券 V8.7.1 交易版配置
================================
基于原 V8.7.1 策略配置，新增国金证券自动交易参数。

使用方式:
  BROKER_TYPE = "manual"   → 手动模式 (原版行为，生成信号 + PushPlus推送)
  BROKER_TYPE = "qmt"      → QMT 自动交易 (需本地运行 QMT 客户端)
  BROKER_TYPE = "ptrade"   → PTrade 信号桥接 (本地生成信号 → PTrade 云端执行)
"""
import datetime
import os


class Config:

    # ========================================
    # 🔌 券商交易配置 (国金版新增)
    # ========================================

    # 券商类型: "manual" | "qmt" | "ptrade"
    BROKER_TYPE = os.environ.get("GJ_BROKER_TYPE", "manual")

    # 是否自动执行交易 (True=自动下单, False=仅生成信号+推送)
    AUTO_TRADE = os.environ.get("GJ_AUTO_TRADE", "false").lower() == "true"

    # --- QMT 配置 ---
    # 国金 QMT 客户端路径 (本地运行 QMT 时需要)
    QMT_PATH = os.environ.get("QMT_PATH", r"C:\国金QMT\userdata_mini")

    # QMT 会话 ID (一般用默认值 1)
    QMT_SESSION_ID = int(os.environ.get("QMT_SESSION_ID", "1"))

    # QMT 资金账号
    QMT_ACCOUNT_ID = os.environ.get("QMT_ACCOUNT_ID", "")

    # --- PTrade 配置 ---
    # PTrade 信号文件路径 (需要是 PTrade 云端策略可访问的路径)
    PTRADE_SIGNAL_PATH = os.environ.get("PTRADE_SIGNAL_PATH", "ptrade_signal.json")

    # ========================================
    # 📱 微信推送配置
    # ========================================
    PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

    # ========================================
    # 📅 数据日期范围
    # ========================================
    START_DATE = "20240101"
    END_DATE = datetime.datetime.now().strftime("%Y%m%d")

    # ========================================
    # 🌟 核心动量参数
    # ========================================
    N_DAYS = 18
    RSRS_THRESHOLD = 0.05
    TOP_N = 2
    SIGNAL_LAG_DAYS = 1

    # ========================================
    # 🌐 宏观风控参数
    # ========================================
    US10Y_STOOQ_SYMBOL = "10yusy.b"
    MACRO_DRIFT = 0.05
    HALF_CRISIS_ENABLED = True
    HALF_CRISIS_RISK_WEIGHT = 0
    HALF_CRISIS_APPLY_TO_PURE = True
    MIN_REBAL_ENABLED = True
    MIN_REBAL_TURNOVER = 0.03

    # ========================================
    # 🛑 硬止损 & 熔断参数
    # ========================================
    HARD_STOP_ENABLED = False
    SINGLE_POSITION_STOP = -0.08
    PORTFOLIO_DRAWDOWN_STOP = -0.12
    COOLDOWN_WEEKS = 2
    AUTO_SAVE_STATE = True

    # ========================================
    # 📊 资产池
    # ========================================
    RISK_POOL = {
        "510880": "红利ETF",
        "510300": "沪深300",
        "510500": "中证500",
        "512100": "中证1000",
        "588000": "科创50",
        "513500": "标普500",
        "513100": "纳指100",
        "513030": "德国DAX",
        "513520": "日经225",
        "513400": "道琼斯",
    }

    # ========================================
    # 💡 高溢价平替池
    # ========================================
    SUBSTITUTES = {
        "513520": {"code": "513880", "name": "日经ETF(华安)"},
        "513100": {"code": "159941", "name": "纳指ETF(广发)"},
        "513030": {"code": "159561", "name": "德国DAX(嘉实)"},
        "513500": {"code": "159655", "name": "标普500(天弘)"},
        "513400": {"code": "159655", "name": "标普500(天弘)"},
    }

    GOLD_CODE = "518880"
    BOND_10Y_CODE = "511260"
    SAFE_POOL = {GOLD_CODE: "黄金ETF", BOND_10Y_CODE: "10年国债"}
    EXCLUDE_GOLD_IN_CRISIS = True

    CASH_CODE = "511880"
    CASH_NAME = "银华日利"
    ALL_POOL = {**RISK_POOL, **SAFE_POOL}

    MARKET_ANCHOR = "513500"

    # ========================================
    # 💰 账户 & 订单参数
    # ========================================
    INITIAL_CAPITAL = 100000.0
    PORTFOLIO_STATE_PATH = "portfolio_state.json"
    DEFAULT_LOT_SIZE = 100
    LOT_SIZE_BY_CODE = {"511880": 100, "511260": 100, "518880": 100}
    USE_REALTIME_PRICE = True
    MIN_ORDER_NOTIONAL = 2000.0

    # ========================================
    # ⚠️ 国金版交易安全参数
    # ========================================

    # 单笔最大买入金额 (防止误操作大额下单)
    MAX_SINGLE_BUY_AMOUNT = float(os.environ.get("GJ_MAX_BUY", "50000"))

    # 下单前确认等待秒数 (仅 QMT 模式，给予人工检查时间)
    CONFIRM_DELAY_SECONDS = int(os.environ.get("GJ_CONFIRM_DELAY", "0"))

    # 市价单溢价比例 (买入在参考价基础上上浮，卖出下浮)
    BUY_PRICE_PREMIUM = 0.001   # 买入 +0.1%
    SELL_PRICE_DISCOUNT = 0.001  # 卖出 -0.1%

    # QMT 下单间隔 (秒，避免触发风控限制)
    QMT_ORDER_INTERVAL = float(os.environ.get("QMT_ORDER_INTERVAL", "0.5"))

    # PTrade 信号文件同步间隔 (秒)
    PTRADE_SYNC_INTERVAL = int(os.environ.get("PTRADE_SYNC_INTERVAL", "30"))