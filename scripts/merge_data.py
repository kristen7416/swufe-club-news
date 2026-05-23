"""
数据合并模块

合并全局数据：
1. 爬虫提取的活动 (extracted_activities.json)
2. 人工提交的活动 (人工数据可选)
3. 已有的活动数据 (activities.json)

去重逻辑: 以 article_url 为唯一键
合并后更新 site/data/activities.json
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import load_json, save_json

CONFIG = {
    "activities_path": "site/data/activities.json",
    "extracted_path": "site/data/extracted_activities.json",
    "manual_path": "site/data/manual_activities.json",  # 人工提交数据 (可选)
    "output_path": "site/data/activities.json",
    "clubs_path": "site/data/clubs.json",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path):
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


def compute_status(activity: dict) -> str:
    """重新计算活动状态"""
    from datetime import timezone
    now = datetime.now().astimezone()  # offset-aware

    start = activity.get("start_time")
    end = activity.get("end_time")

    try:
        start_dt = datetime.fromisoformat(start) if start else None
    except (ValueError, TypeError):
        start_dt = None

    try:
        end_dt = datetime.fromisoformat(end) if end else None
    except (ValueError, TypeError):
        end_dt = None

    # 统一为 offset-aware 以便比较
    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    if end_dt and end_dt < now:
        return "ended"
    if start_dt and start_dt <= now:
        if not end_dt or end_dt > now:
            return "ongoing"
        return "ended"
    if start_dt and start_dt > now:
        return "upcoming"
    return "upcoming"


def merge_activities(existing: list, extracted: list, manual: list) -> list:
    """
    合并三个来源的活动数据

    优先级 (从高到低):
    1. 人工提交 (manual)
    2. 爬虫提取 (extracted)
    3. 已有数据 (existing)

    去重键: article_url
    """
    merged = {}

    # 1. 已有数据
    for act in existing:
        key = act.get("article_url", "") or act.get("id", "")
        if key:
            merged[key] = dict(act)

    # 2. 爬虫数据
    for act in extracted:
        key = act.get("article_url", "") or act.get("id", "")
        if not key:
            continue
        if key in merged:
            existing_act = merged[key]
            # 保留人工提交的字段
            if existing_act.get("source") == "manual":
                act.setdefault("location",
                    existing_act.get("location") or act.get("location", ""))
                act.setdefault("start_time",
                    existing_act.get("start_time") or act.get("start_time", ""))
                act.setdefault("contact",
                    existing_act.get("contact", ""))
        act["status"] = compute_status(act)
        merged[key] = act

    # 3. 人工数据
    for act in manual:
        key = act.get("article_url", "") or act.get("id", "")
        if not key:
            continue
        act["source"] = "manual"
        act["status"] = compute_status(act)
        merged[key] = act

    # 转为列表，按时间倒序
    activities = list(merged.values())
    activities.sort(key=lambda x: (
        {"ongoing": 0, "upcoming": 1, "ended": 2}.get(x.get("status", ""), 99),
        x.get("start_time") or "",
    ))

    return activities


def main():
    print(f"[merge_data] 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 加载各数据源
    existing = load_json(resolve(CONFIG["activities_path"]), {})
    extracted = load_json(resolve(CONFIG["extracted_path"]), {})
    manual = load_json(resolve(CONFIG["manual_path"]), {})

    existing_list = existing.get("activities", [])
    extracted_list = extracted.get("activities", [])
    manual_list = manual.get("activities", [])

    print(f"  现有活动: {len(existing_list)}")
    print(f"  爬虫新提取: {len(extracted_list)}")
    print(f"  人工提交: {len(manual_list)}")

    # 合并
    merged_list = merge_activities(existing_list, extracted_list, manual_list)

    # 统计
    status_counts = {"upcoming": 0, "ongoing": 0, "ended": 0}
    for act in merged_list:
        s = act.get("status", "upcoming")
        status_counts[s] = status_counts.get(s, 0) + 1

    output = {
        "activities": merged_list,
        "last_updated": datetime.now().isoformat(),
        "total_count": len(merged_list),
        "status_counts": status_counts,
    }

    save_json(resolve(CONFIG["output_path"]), output)

    print(f"[merge_data] 完成!")
    print(f"  合并后活动总数: {len(merged_list)}")
    print(f"  即将开始: {status_counts.get('upcoming', 0)}")
    print(f"  进行中: {status_counts.get('ongoing', 0)}")
    print(f"  已结束: {status_counts.get('ended', 0)}")


if __name__ == "__main__":
    main()
