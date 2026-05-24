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
from datetime import datetime, timedelta, timezone

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


BEIJING_TZ = timezone(timedelta(hours=8))

# 标题关键词 → 状态推断（与 extract_activity.py 保持一致）
STATUS_TITLE_HINTS = {
    "ended": ["圆满结束", "圆满落幕", "圆满", "精彩回顾", "活动总结",
              "回顾", "落幕", "收官", "成功举办", "顺利举办",
              "顺利举行", "顺利结束", "顺利闭幕", "圆满完成"],
    "upcoming": ["预告", "倒计时", "即将", "敬请期待",
                 "抢鲜", "预热", "剧透", "通知", "报名"],
}


def infer_status_from_title(title: str) -> str:
    """当 start_time/end_time 无法确定时，通过标题关键词推断活动状态"""
    if not title:
        return ""
    for status, keywords in STATUS_TITLE_HINTS.items():
        for kw in keywords:
            if kw in title:
                return status
    return ""


def compute_status(activity: dict) -> str:
    """重新计算活动状态（北京时间 UTC+8），无时间时降级到标题推断"""
    now = datetime.now(BEIJING_TZ)

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

    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=BEIJING_TZ)
    if end_dt and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=BEIJING_TZ)

    # 年份合理性检查：如果 start_time 年份 >= 发布年份且修正后在过去，说明推断错误
    pub_str = activity.get("publish_time", "")
    if start_dt and pub_str:
        try:
            pub_dt = datetime.fromisoformat(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=BEIJING_TZ)
            if start_dt.year > pub_dt.year and start_dt > now and pub_dt < now:
                # 尝试用发布年份修正，若结果在过去则说明推断错误
                try:
                    corrected = start_dt.replace(year=pub_dt.year)
                except ValueError:
                    corrected = None
                if corrected and corrected < now:
                    start = None
                    end = None
                    start_dt = None
                    end_dt = None
        except (ValueError, TypeError):
            pass

    if end_dt and end_dt < now:
        return "ended"
    if start_dt and start_dt <= now:
        if not end_dt or end_dt > now:
            if end_dt:
                return "ongoing"  # 结束时间在未来
            # 无结束时间：开始时间超过7天前 → 已结束（而非进行中）
            if (now - start_dt).days > 7:
                return "ended"
            return "ongoing"
        return "ended"
    if start_dt and start_dt > now:
        return "upcoming"

    # 启发式：发布时间 > 7天 且 开始时间 > 1天前 → 已结束
    pub_str = activity.get("publish_time", "")
    if pub_str and start_dt:
        try:
            pub_dt = datetime.fromisoformat(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=BEIJING_TZ)
            days_since_pub = (now - pub_dt).days
            days_since_start = (now - start_dt).days
            if days_since_pub > 7 and days_since_start > 1:
                return "ended"
        except (ValueError, TypeError):
            pass

    # 无有效时间数据 → 降级推断
    if not start_dt and not end_dt:
        # 1. 标题关键词推断（仅接受 "ended"，不信任 "upcoming" 标题推断）
        title_status = infer_status_from_title(activity.get("title", ""))
        if title_status == "ended":
            return "ended"

        # 2. 发布时间 > 30天 → 已结束（年份推断被清除 / 时间未提取到的旧活动）
        if activity.get("publish_time"):
            try:
                pub_dt = datetime.fromisoformat(activity.get("publish_time"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=BEIJING_TZ)
                if (now - pub_dt).days > 30:
                    return "ended"
            except (ValueError, TypeError):
                pass

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
            # 保留已有数据的非空字段（人工 / 补全）
            enrich_fields = ["location", "contact", "start_time", "end_time", "description"]
            for field in enrich_fields:
                if existing_act.get(field) and not act.get(field):
                    act[field] = existing_act[field]
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

    # 4. 全局重算状态（确保已有活动也应用标题推断）
    for key in merged:
        merged[key]["status"] = compute_status(merged[key])

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
        "last_updated": datetime.now(BEIJING_TZ).isoformat(),
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
