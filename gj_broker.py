# -*- coding: utf-8 -*-
"""
国金证券交易券商抽象层
支持三种模式:
  1. QMT (xtquant)  - 本地 QMT 客户端自动下单
  2. PTrade          - 信号文件桥接模式 (本地生成信号 → PTrade云端执行)
  3. Manual          - 手动模式 (输出指令 + PushPlus推送，原版行为)

架构设计:
  BaseBroker (抽象基类)
    ├── QmtBroker      →  xtquant SDK 直连 QMT 客户端
    ├── PtradeBroker   →  信号文件 + PTrade 监听策略
    └── ManualBroker   →  纯信号输出 (原版模式)
"""

import os
import json
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# 订单数据结构
# ============================================================
class Order:
    """统一订单结构"""
    def __init__(self, code: str, side: str, shares: int, price: float,
                 market: str = "CN", name: str = ""):
        self.code = code          # 6位代码，如 "510300"
        self.side = side.upper()  # "BUY" / "SELL"
        self.shares = shares      # 股数 (必须是100的整数倍)
        self.price = price        # 参考价格
        self.market = market      # "SH" / "SZ"
        self.name = name          # 标的名称
        self.notional = round(shares * price, 2)

    def __repr__(self):
        return (f"Order({self.side} {self.code} {self.name} "
                f"{self.shares}股 @{self.price:.4f} ≈¥{self.notional:,.2f})")

    def to_qmt_code(self) -> str:
        """转为 QMT 格式: 510300.SH / 159941.SZ"""
        return f"{self.code}.{self.market}"

    def to_ptrade_code(self) -> str:
        """转为 PTrade 格式: 510300.XSHG / 159941.XSHE"""
        suffix = "XSHG" if self.market == "SH" else "XSHE"
        return f"{self.code}.{suffix}"


# ============================================================
# 抽象基类
# ============================================================
class BaseBroker(ABC):
    """券商交易接口抽象基类"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.name = self.__class__.__name__

    @abstractmethod
    def connect(self) -> bool:
        """连接券商交易系统，返回是否成功"""
        ...

    @abstractmethod
    def query_positions(self) -> dict:
        """查询当前持仓 {code: shares}"""
        ...

    @abstractmethod
    def query_cash(self) -> float:
        """查询可用资金"""
        ...

    @abstractmethod
    def place_order(self, order: Order) -> bool:
        """
        下单 (同步阻塞)
        返回是否成功提交
        """
        ...

    @abstractmethod
    def cancel_all_orders(self) -> int:
        """撤销所有未成交订单，返回撤单数量"""
        ...

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        ...

    def execute_orders(self, orders: list[Order]) -> dict:
        """
        批量执行订单 (先卖后买)
        返回 {"success": int, "failed": int, "details": list}
        """
        result = {"success": 0, "failed": 0, "details": []}

        # 先卖后买
        sells = [o for o in orders if o.side == "SELL"]
        buys = [o for o in orders if o.side == "BUY"]

        for order in sells + buys:
            try:
                ok = self.place_order(order)
                if ok:
                    result["success"] += 1
                    result["details"].append(f"✅ {order}")
                else:
                    result["failed"] += 1
                    result["details"].append(f"❌ {order} - 下单失败")
            except Exception as e:
                result["failed"] += 1
                result["details"].append(f"❌ {order} - 异常: {e}")

        return result


# ============================================================
# QMT (xtquant) 实现
# ============================================================
class QmtBroker(BaseBroker):
    """
    国金证券 QMT xtquant 交易通道

    前置条件:
      1. 本地安装 QMT 客户端并登录
      2. pip install xtquant
      3. QMT 设置中开启"极速模式"和"Python策略权限"

    使用方法:
      broker = QmtBroker(account_id="YOUR_ACCOUNT")
      broker.connect()
      broker.place_order(order)
      broker.disconnect()
    """

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.account_id = self.config.get("qmt_account_id", "")
        self.trader = None
        self.xt_trader = None
        self._connected = False
        self._acc_callback_done = False

    def connect(self) -> bool:
        """连接 QMT 客户端"""
        try:
            from xtquant import xtdata
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
            from xtquant import xtconstant

            self.xtconstant = xtconstant

            # 连接 QMT mini 客户端 (默认端口 58610)
            path = self.config.get("qmt_path", r"C:\国金QMT\userdata_mini")
            session_id = self.config.get("qmt_session_id", 1)

            self.xt_trader = XtQuantTrader(path, session_id)
            self.xt_trader.start()

            # 连接状态回调
            connect_result = self.xt_trader.connect()
            if connect_result != 0:
                logger.error(f"QMT 连接失败: 错误码 {connect_result}")
                return False

            # 订阅账户
            self.account = StockAccount(self.account_id)
            self.xt_trader.subscribe(self.account)

            # 等待账户推送就绪
            time.sleep(1)

            self._connected = True
            logger.info(f"✅ QMT 连接成功: account={self.account_id}")
            return True

        except ImportError:
            logger.error("❌ xtquant 未安装，请执行: pip install xtquant")
            return False
        except Exception as e:
            logger.error(f"❌ QMT 连接异常: {e}")
            return False

    def query_positions(self) -> dict:
        """查询 QMT 持仓"""
        if not self._connected or not self.xt_trader:
            return {}
        try:
            positions = self.xt_trader.query_stock_positions(self.account)
            result = {}
            for pos in positions:
                if pos.volume > 0:
                    code = pos.stock_code.split(".")[0]
                    result[code] = int(pos.volume)
            return result
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return {}

    def query_cash(self) -> float:
        """查询 QMT 可用资金"""
        if not self._connected or not self.xt_trader:
            return 0.0
        try:
            asset = self.xt_trader.query_stock_asset(self.account)
            return float(getattr(asset, "available", 0.0))
        except Exception as e:
            logger.error(f"查询资金失败: {e}")
            return 0.0

    def place_order(self, order: Order) -> bool:
        """
        QMT 下单 (限价单)
        ETF 不设涨跌停限制，直接用限价单
        """
        if not self._connected or not self.xt_trader:
            logger.error("QMT 未连接，无法下单")
            return False

        try:
            stock_code = order.to_qmt_code()
            order_type = self.xtconstant.STOCK_BUY if order.side == "BUY" else self.xtconstant.STOCK_SELL
            price_type = self.xtconstant.FIX_PRICE  # 限价单

            # 价格微调：买入略高0.1%确保成交，卖出略低0.1%
            if order.side == "BUY":
                limit_price = round(order.price * 1.001, 3)
            else:
                limit_price = round(order.price * 0.999, 3)

            # 下单
            order_id = self.xt_trader.order_stock(
                self.account,
                stock_code,
                order_type,
                order.shares,
                price_type,
                limit_price,
                "ETF轮动策略",
                order.shares
            )

            logger.info(f"✅ QMT下单成功: {order} → order_id={order_id}")
            return order_id != -1

        except Exception as e:
            logger.error(f"❌ QMT下单失败: {order} → {e}")
            return False

    def cancel_all_orders(self) -> int:
        """撤销所有未成交订单"""
        if not self._connected:
            return 0
        try:
            orders = self.xt_trader.query_stock_orders(self.account, cancelable_only=True)
            count = 0
            for od in orders:
                order_id = getattr(od, "order_id", 0)
                self.xt_trader.cancel_order_stock(self.account, order_id)
                count += 1
                time.sleep(0.1)
            logger.info(f"✅ 撤单完成: {count} 笔")
            return count
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return 0

    def disconnect(self):
        """断开 QMT"""
        if self.xt_trader:
            try:
                self.xt_trader.stop()
            except Exception:
                pass
        self._connected = False
        logger.info("QMT 已断开连接")


# ============================================================
# PTrade 信号文件桥接实现
# ============================================================
class PtradeBroker(BaseBroker):
    """
    国金证券 PTrade 云端交易通道 (信号文件桥接模式)

    工作原理:
      1. 本地策略生成信号 → 写入 JSON 信号文件
      2. 信号文件放在 PTrade 能访问的路径 (云同步盘/本地目录)
      3. PTrade 云端运行监听策略，定时读取信号文件并执行下单

    前置条件:
      1. 国金证券开通 PTrade 权限
      2. 在 PTrade 中部署监听策略 (见 ptrade_listener.py)
      3. 信号文件存放路径与 PTrade 策略约定的路径一致

    PTrade 下单 API:
      - order(security, amount)            # amount>0买入, <0卖出
      - order_value(security, value)       # 按金额下单
      - order_target_value(security, value) # 调整到目标市值
    """

    SIGNAL_FILE = "ptrade_signal.json"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.signal_path = Path(self.config.get("ptrade_signal_path", self.SIGNAL_FILE))
        self._connected = True  # PTrade 不需要本地连接

    def connect(self) -> bool:
        logger.info(f"✅ PTrade 信号模式已就绪，信号文件: {self.signal_path}")
        return True

    def query_positions(self) -> dict:
        """从 PTrade 信号文件读取上次同步的持仓"""
        return self._read_signal_file().get("synced_positions", {})

    def query_cash(self) -> float:
        return self._read_signal_file().get("synced_cash", 0.0)

    def place_order(self, order: Order) -> bool:
        """
        写入信号文件 (PTrade 监听策略会读取并执行)
        注意: 此方法不真正下单，只是写入信号文件
        """
        try:
            signal_data = self._read_signal_file()

            # 追加新信号
            signals = signal_data.get("pending_signals", [])
            signals.append({
                "code": order.to_ptrade_code(),
                "side": order.side,
                "shares": order.shares,
                "price_ref": order.price,
                "name": order.name,
                "timestamp": datetime.now().isoformat(),
                "status": "pending"
            })

            signal_data["pending_signals"] = signals
            signal_data["last_updated"] = datetime.now().isoformat()
            signal_data["broker"] = "ptrade"

            self._write_signal_file(signal_data)
            logger.info(f"✅ PTrade 信号已写入: {order}")
            return True

        except Exception as e:
            logger.error(f"❌ PTrade 信号写入失败: {e}")
            return False

    def cancel_all_orders(self) -> int:
        """清空待执行信号"""
        signal_data = self._read_signal_file()
        count = len(signal_data.get("pending_signals", []))
        signal_data["pending_signals"] = []
        signal_data["canceled_at"] = datetime.now().isoformat()
        self._write_signal_file(signal_data)
        return count

    def execute_orders(self, orders: list[Order]) -> dict:
        """
        批量写入信号 (PTrade 模式一次性写入所有信号)
        """
        result = {"success": 0, "failed": 0, "details": []}
        try:
            signal_data = self._read_signal_file()
            signal_data["pending_signals"] = []

            sells = [o for o in orders if o.side == "SELL"]
            buys = [o for o in orders if o.side == "BUY"]

            for order in sells + buys:
                signal_data["pending_signals"].append({
                    "code": order.to_ptrade_code(),
                    "side": order.side,
                    "shares": order.shares,
                    "price_ref": order.price,
                    "name": order.name,
                    "timestamp": datetime.now().isoformat(),
                    "status": "pending"
                })
                result["success"] += 1
                result["details"].append(f"✅ {order}")

            signal_data["last_updated"] = datetime.now().isoformat()
            signal_data["broker"] = "ptrade"
            self._write_signal_file(signal_data)

            logger.info(f"✅ PTrade 批量信号已写入: {result['success']} 笔")
        except Exception as e:
            result["failed"] = len(orders)
            result["details"].append(f"❌ PTrade 批量写入失败: {e}")

        return result

    def disconnect(self):
        pass

    def _read_signal_file(self) -> dict:
        if self.signal_path.exists():
            try:
                return json.loads(self.signal_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _write_signal_file(self, data: dict):
        self.signal_path.parent.mkdir(parents=True, exist_ok=True)
        self.signal_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


# ============================================================
# 手动模式 (保留原版行为)
# ============================================================
class ManualBroker(BaseBroker):
    """
    手动模式 (原版行为)
    生成订单但不自动执行，仅通过 PushPlus 推送 + 终端输出
    """

    def connect(self) -> bool:
        return True

    def query_positions(self) -> dict:
        state_path = self.config.get("state_path", "portfolio_state.json")
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            return state.get("positions", {})
        except Exception:
            return {}

    def query_cash(self) -> float:
        state_path = self.config.get("state_path", "portfolio_state.json")
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            return float(state.get("cash_cny", 0))
        except Exception:
            return 0.0

    def place_order(self, order: Order) -> bool:
        # 手动模式不真正下单
        return True

    def cancel_all_orders(self) -> int:
        return 0

    def disconnect(self):
        pass

    def execute_orders(self, orders: list[Order]) -> dict:
        return {"success": 0, "failed": 0, "details": ["[手动模式] 请按以下指令在佣金宝App操作"]}


# ============================================================
# 工厂函数
# ============================================================
def create_broker(broker_type: str, config: dict = None) -> BaseBroker:
    """
    创建券商实例

    Args:
        broker_type: "qmt" / "ptrade" / "manual"
        config: 配置字典

    Returns:
        BaseBroker 实例
    """
    broker_map = {
        "qmt": QmtBroker,
        "ptrade": PtradeBroker,
        "manual": ManualBroker,
    }

    broker_cls = broker_map.get(broker_type.lower())
    if broker_cls is None:
        logger.warning(f"未知券商类型 '{broker_type}'，回退到手动模式")
        broker_cls = ManualBroker

    return broker_cls(config)