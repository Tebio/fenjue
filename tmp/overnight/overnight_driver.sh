#!/bin/bash
# overnight_driver.sh — 焚诀夜间流水线驱动（2026-09-18）
# 确定性计算跑脚本，阶段间由 webhook 唤起 agent 分析并生成追加实验队列。
# 终止条件：S1+S2 固定阶段 + 最多 3 轮 followup（每轮最多读一次队列）→ final。
set -u
cd /opt/data/fenjue
HOOK=http://localhost:8644/webhooks/fenjue-overnight
HOOKF=http://localhost:8644/webhooks/fenjue-overnight-final
Q=tmp/overnight/followup_queue.sh
LOG=tmp/overnight/driver.log
mkdir -p tmp/overnight
: > "$Q"
echo "[$(date '+%F %T')] driver start" >> "$LOG"

SECRET=$(cat tmp/overnight/hook_secret)

post() { # hook stage rc log
  local body="{\"stage\":\"$2\",\"rc\":$3,\"log\":\"/opt/data/fenjue/tmp/overnight/$2.log\"}"
  local sig=$(echo -n "$body" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')
  curl -s -m 30 -X POST "$1" -H 'Content-Type: application/json' \
    -H "X-Hub-Signature-256: sha256=$sig" -d "$body" >> "$LOG" 2>&1
}

wait_done() { # stage — 等 agent 写 done 标记，最多 20 分钟
  local t=0
  while [ ! -f "tmp/overnight/done_$1" ] && [ $t -lt 1200 ]; do sleep 20; t=$((t+20)); done
  rm -f "tmp/overnight/done_$1"
}

run_stage() { # name cmd...
  local name="$1"; shift
  echo "[$(date '+%F %T')] $name start: $*" >> "$LOG"
  "$@" > "tmp/overnight/$name.log" 2>&1
  local rc=$?
  echo "[$(date '+%F %T')] $name done rc=$rc" >> "$LOG"
  post "$HOOK" "$name" "$rc"
  wait_done "$name"
}

run_stage S1_exitgrid .venv/bin/python engine/exit_rule_grid.py
run_stage S2_confluence .venv/bin/python engine/law_pipeline.py submit \
  组合_跌停低_缩量_剔亏ST 组合_跌停低_输家_超跌20_缩量 组合_跌停低_三连阴_缩量 \
  组合_跌停低_避雷针_缩量 组合_跌停低_输家_超跌20_剔亏ST 组合_缺口低开_低位_剔亏ST

for r in 1 2 3; do
  if [ -s "$Q" ]; then
    mv "$Q" "$Q.round$r"
    i=0
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      i=$((i+1)); [ $i -gt 2 ] && break
      run_stage "F${r}_$i" bash -c "$line"
    done < "$Q.round$r"
  else
    echo "[$(date '+%F %T')] round $r: queue empty" >> "$LOG"
  fi
done

echo "[$(date '+%F %T')] final hook" >> "$LOG"
FBODY='{"stage":"final","rc":0,"log":"/opt/data/fenjue/tmp/overnight/driver.log"}'
FSIG=$(echo -n "$FBODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')
curl -s -m 30 -X POST "$HOOKF" -H 'Content-Type: application/json' \
  -H "X-Hub-Signature-256: sha256=$FSIG" -d "$FBODY" >> "$LOG" 2>&1
echo "[$(date '+%F %T')] driver end" >> "$LOG"
