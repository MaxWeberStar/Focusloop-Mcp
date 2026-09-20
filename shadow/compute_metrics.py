"""从人工标注计算准确率、误报率、漏报率。"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def compute_metrics(labels_path: Path) -> dict[str, float | int]:
    """
    从 labels.jsonl 读取人工标注，计算统计指标。
    
    每行格式：{"observation_id": "...", "label": "correct|false_positive|false_negative", "note": "..."}
    """
    if not labels_path.exists():
        return {
            "total": 0,
            "correct": 0,
            "false_positive": 0,
            "false_negative": 0,
            "accuracy": 0.0,
            "false_positive_rate": 0.0,
            "false_negative_rate": 0.0
        }
    
    labels = []
    with open(labels_path) as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    
    total = len(labels)
    correct = sum(1 for item in labels if item.get("label") == "correct")
    false_positive = sum(1 for item in labels if item.get("label") == "false_positive")
    false_negative = sum(1 for item in labels if item.get("label") == "false_negative")
    
    accuracy = correct / total if total > 0 else 0.0
    fp_rate = false_positive / total if total > 0 else 0.0
    fn_rate = false_negative / total if total > 0 else 0.0
    
    return {
        "total": total,
        "correct": correct,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "accuracy": round(accuracy, 3),
        "false_positive_rate": round(fp_rate, 3),
        "false_negative_rate": round(fn_rate, 3)
    }


if __name__ == "__main__":
    labels_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("labels.jsonl")
    metrics = compute_metrics(labels_file)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    
    print("\n决策建议:", file=sys.stderr)
    if metrics["total"] < 10:
        print(f"  ⚠ 样本数不足（{metrics['total']}/10），继续收集", file=sys.stderr)
    elif metrics["false_positive_rate"] < 0.2 and metrics["false_negative_rate"] < 0.3:
        print(f"  ✓ 准确率 {metrics['accuracy']*100:.1f}%，误报 {metrics['false_positive_rate']*100:.1f}%，漏报 {metrics['false_negative_rate']*100:.1f}%", file=sys.stderr)
        print("  建议：可在高置信场景启用主动询问", file=sys.stderr)
    else:
        print(f"  ✗ 误报率 {metrics['false_positive_rate']*100:.1f}% 或漏报率 {metrics['false_negative_rate']*100:.1f}% 过高", file=sys.stderr)
        print("  建议：继续改进判断或保持纯观察模式", file=sys.stderr)
