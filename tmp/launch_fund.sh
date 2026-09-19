#!/bin/bash
# 4 分片并发抓取基本面（2026-09-18）
cd /opt/data/fenjue
for k in 0 1 2 3; do
  nohup /opt/data/fenjue/.venv/bin/python engine/fetch_fundamentals.py - /tmp/fund_shard_$k.txt \
    > /tmp/fund_shard_$k.log 2>&1 &
done
sleep 25
for k in 0 1 2 3; do
  echo "shard$k pid=$(pgrep -f "fund_shard_$k.txt" | head -1) $(tail -1 /tmp/fund_shard_$k.log)"
done
echo "total files: $(ls /opt/data/fenjue/data/fund_cache/*.json | wc -l)"
