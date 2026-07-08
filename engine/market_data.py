"""
实时行情数据层 — 通过腾讯 API (qt.gtimg.cn) 获取 A 股实时价格。
单例模式，内置缓存。用 subprocess curl 绕过 Python 代理问题。
"""
from __future__ import annotations
import subprocess, time
from typing import Any


class MarketData:
    """实时行情获取器。用法: MarketData().get_quote('600141')"""

    _instance: MarketData | None = None
    _cache: dict[str, dict[str, Any] | None] = {}
    _cache_ts: float = 0
    _TTL: float = 60.0

    def __new__(cls) -> MarketData:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _curl(url: str) -> str:
        """subprocess curl, immune to Python proxy issues."""
        r = subprocess.run(
            ["curl", "-s", "--max-time", "10", "-H", "User-Agent: Mozilla/5.0", url],
            capture_output=True, timeout=12
        )
        try:
            return r.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return r.stdout.decode("gbk", errors="replace")

    def get_quote(self, code: str) -> dict[str, Any] | None:
        """返回单只股票实时行情。
        腾讯 API 数据位:
          [0]名称 [1]代码 [3]最新价 [5]昨收 [31]涨跌幅 [32]最高 [33]最低
          [37]成交量 [38]换手率 [39]PE [43]今开 [44]振幅
        """
        now = time.time()
        if code in self._cache and self._cache[code] is not None and (now - self._cache_ts) < self._TTL:
            return self._cache[code]

        prefix = "sh" if code.startswith("6") else "sz"
        raw = self._curl(f"https://qt.gtimg.cn/q={prefix}{code}")
        if not raw or '"' not in raw:
            self._cache[code] = None
            return None

        try:
            f = raw.split('"')[1].split("~")
            if len(f) < 40:
                self._cache[code] = None
                return None
            quote = {
                "code":       code,
                "name":       str(f[1]),
                "price":      float(f[3] or 0),
                "preclose":   float(f[4] or 0),
                "change_pct": float(f[32] or 0),
                "high":       float(f[33] or 0),
                "low":        float(f[34] or 0),
                "volume":     float(f[6] or 0),
                "turnover":   float(f[38] or 0),
                "pe":         float(f[39]) if f[39] and f[39] != "0" else None,
                "open":       float(f[5] or 0),
                "timestamp":  now,
            }
            self._cache[code] = quote
            self._cache_ts = now
            return quote
        except (ValueError, IndexError) as e:
            print(f"[MarketData] parse {code} failed: {e}")
            self._cache[code] = None
            return None

    def get_batch(self, codes: list[str]) -> dict[str, dict[str, Any] | None]:
        """批量获取：拼接多个 code 一次请求。"""
        now = time.time()
        if all(c in self._cache for c in codes) and (now - self._cache_ts) < self._TTL:
            return {c: self._cache.get(c) for c in codes}

        # 腾讯支持逗号分隔的多股票查询
        prefixed = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes]
        raw = self._curl(f"https://qt.gtimg.cn/q={','.join(prefixed)}")
        result: dict[str, dict[str, Any] | None] = {}

        for code in codes:
            prefix = "sh" if code.startswith("6") else "sz"
            try:
                # Parse the line for this specific stock
                needle = f'v_{prefix}{code}="'
                idx = raw.find(needle)
                if idx < 0:
                    result[code] = None
                    continue
                line = raw[idx:].split('"')[1]
                f = line.split("~")
                if len(f) < 40:
                    result[code] = None
                    continue
                quote = {
                    "code":       code,
                    "name":       str(f[1]),
                    "price":      float(f[3] or 0),
                    "preclose":   float(f[4] or 0),
                    "change_pct": float(f[32] or 0),
                    "high":       float(f[33] or 0),
                    "low":        float(f[34] or 0),
                    "volume":     float(f[6] or 0),
                    "turnover":   float(f[38] or 0),
                    "pe":         float(f[39]) if f[39] and f[39] != "0" else None,
                    "open":       float(f[5] or 0),
                    "timestamp":  now,
                }
                result[code] = quote
                self._cache[code] = quote
            except (ValueError, IndexError):
                result[code] = None
                self._cache[code] = None

        self._cache_ts = now
        return result

    def invalidate(self):
        self._cache.clear()
        self._cache_ts = 0
