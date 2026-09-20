#!/bin/bash
# 影子运行助手：在小任务后生成摘要并运行影子审查

set -e

DB_PATH="${DB_PATH:-.focusloop/state.sqlite3}"
PROJECT="${PROJECT:-focusloop-v1}"

echo "=== FocusLoop 影子运行助手 ==="
echo "当前项目: $PROJECT"
echo "数据库: $DB_PATH"
echo ""

# 检查是否有已确认目标
CURRENT_VERSION=$(python3 -c "
import sys
sys.path.insert(0, '.')
from focusloop import Store
from pathlib import Path
store = Store(Path('$DB_PATH'), '$PROJECT')
print(store.version())
store.close()
")

if [ "$CURRENT_VERSION" = "0" ]; then
    echo "错误：尚无已确认目标。请先运行："
    echo "  python3 focusloop.py propose <goal.json> --source <来源>"
    echo "  python3 focusloop.py confirm <version> --expected 0 --source <来源>"
    exit 1
fi

echo "当前目标版本: $CURRENT_VERSION"
echo ""

# 生成摘要并保存到临时文件
echo "生成事件摘要..."
SUMMARY_FILE=$(mktemp /tmp/focusloop-summary.XXXXXX.json)
trap "rm -f $SUMMARY_FILE" EXIT

python3 summarize.py "$DB_PATH" "$PROJECT" > "$SUMMARY_FILE"
echo "摘要: $(cat $SUMMARY_FILE)"
echo ""

# 创建观察（直接使用 JSON 文件）
OBS_ID="manual-$(date +%s)"
echo "创建观察 $OBS_ID"
python3 focusloop.py --db "$DB_PATH" observe-json "$OBS_ID" "$SUMMARY_FILE"
echo ""

# 运行影子审查
echo "运行影子审查..."
REVIEW=$(python3 focusloop.py --db "$DB_PATH" review "$OBS_ID")
echo "审查结果:"
echo "$REVIEW" | python3 -m json.tool
echo ""

echo "=== 请人工标注此次判断是否正确 ==="
echo "判断: $(echo "$REVIEW" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("verdict"))')"
echo "类别: $(echo "$REVIEW" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("category"))')"
echo ""
echo "标注方式："
echo "  正确  - echo '{\"observation_id\": \"'$OBS_ID'\", \"label\": \"correct\", \"note\": \"...\"}' >> labels.jsonl"
echo "  误报  - echo '{\"observation_id\": \"'$OBS_ID'\", \"label\": \"false_positive\", \"note\": \"...\"}' >> labels.jsonl"
echo "  漏报  - echo '{\"observation_id\": \"'$OBS_ID'\", \"label\": \"false_negative\", \"note\": \"...\"}' >> labels.jsonl"
