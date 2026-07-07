"""
实时行情数据层 — 通过 akShare 获取 A 股实时价格和基础行情指标。
单例模式，内置缓存，避免重复请求。
"""
from __future__ import annotations
import time
from typing import Any


class MarketData:
    """实时行情获取器。用法: MarketData().get_quote('600141')"""

    _instance: MarketData | None = None
    _cache: dict[str, dict[str, Any]] = {}
    _cache_ts: float = 0
    _TTL: float = 60.0  # 缓存 60 秒

    def __new__(cls) -> MarketData:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_quote(self, code: str) -> dict[str, Any] | None:
        """返回单只股票的实时行情。

        Returns:
            {code, name, price, turnover, volume, change_pct, high, low, open,
             preclose, pct_20d(默认None), timestamp}
            或 None（获取失败）
        """
        now = time.time()
        if code in self._cache and (now - self._cache_ts) < self._TTL:
            return self._cache[code]

        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == code]
            if row.empty:
                self._cache[code] = None
                return None
            r = row.iloc[0]
            quote = {
                "code":       code,
                "name":       str(r.get("名称", "")),
                "price":      float(r.get("最新价", 0)),
                "turnover":   float(r.get("换手率", 0)),
                "volume":     float(r.get("成交量", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
                "high":       float(r.get("最高", 0)),
                "low":        float(r.get("最低", 0)),
                "open":       float(r.get("今开", 0)),
                "preclose":   float(r.get("昨收", 0)),
                "pct_20d":    None,  # 需要历史数据，单独调
                "timestamp":  now,
            }
            self._cache[code] = quote
            self._cache_ts = now
            return quote
        except Exception as e:
            print(f"[MarketData] fetch {code} failed: {e}")
            self._cache[code] = None
            return None

    def get_batch(self, codes: list[str]) -> dict[str, dict[str, Any] | None]:
        """批量获取，一次请求返回所有股票的行情。"""
        now = time.time()
        # 如果缓存有效，直接返回
        if all(c in self._cache for c in codes) and (now - self._cache_ts) < self._TTL:
            return {c: self._cache.get(c) for c in codes}

        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            result: dict[str, dict[str, Any] | None] = {}
            for code in codes:
                row = df[df["代码"] == code]
                if row.empty:
                    result[code] = None
                    self._cache[code] = None
                    continue
                r = row.iloc[0]
                quote = {
                    "code":       code,
                    "name":       str(r.get("名称", "")),
                    "price":      float(r.get("最新价", 0)),
                    "turnover":   float(r.get("换手率", 0)),
                    "volume":     float(r.get("成交量", 0)),
                    "change_pct": float(r.get("涨跌幅", 0)),
                    "high":       float(r.get("最高", 0)),
                    "low":        float(r.get("最低", 0)),
                    "open":       float(r.get("今开", 0)),
                    "preclose":   float(r.get("昨收", 0)),
                    "pct_20d":    None,
                    "timestamp":  now,
                }
                result[code] = quote
                self._cache[code] = quote
            self._cache_ts = now
            return result
        except Exception as e:
            print(f"[MarketData] batch fetch failed: {e}")
            return {c: self._cache.get(c) for c in codes}

    def invalidate(self):
        """清空缓存，强制下次重新拉取。"""
        self._cache.clear()
        self._cache_ts = 0
