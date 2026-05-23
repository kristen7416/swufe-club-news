"""
活动信息提取模块

从公众号文章中识别活动类内容，并提取结构化信息。
支持规则提取和 AI 提取两种模式。

用法:
    python extract_activity.py
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import load_json, save_json

# ===== 配置 =====
CONFIG = {
    "clubs_path": "site/data/clubs.json",
    "raw_path": "site/data/raw_articles.json",
    "output_path": "site/data/extracted_activities.json",
    "mode": "rule",  # "rule" 或 "ai"
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path):
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


# ===== 活动关键词 =====

ACTIVITY_KEYWORDS = [
    "活动", "报名", "讲座", "工作坊", "分享会", "沙龙",
    "比赛", "大赛", "论坛", "预告", "开幕", "通知",
    "邀请", "开启", "截至", "启动", "征集", "招募",
    "纳新", "招新", "见面会", "晚会", "演出", "展览",
    "培训", "课程", "课堂", "体验", "开放日", "峰会",
    "宣讲会", "研讨会", "交流会", "路演", "竞技",
    "投票", "评选", "公示", "通知公告", "活动预告",
    "活动总结", "回顾", "精彩回顾", "倒计时",
]

EXCLUDE_KEYWORDS = [
    "新年贺词", "放假通知", "停更", "声明", "致歉",
    "春节", "清明", "国庆",
]

# 时间提取正则
TIME_PATTERNS = [
    # 2025年6月1日 14:00
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*[:：]\s*(\d{2})"),
    # 6月1日 14:00
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*[:：]\s*(\d{2})"),
    # 2025-06-01 14:00
    re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})"),
    # 时间：xxxx
    re.compile(r"(?:时间|活动时间)[：:]\s*(.*?)(?:\n|$|。|；)"),
    # 6月1日
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
]

# 地点提取正则
LOCATION_PATTERNS = [
    re.compile(r"(?:地点|地址|位置|活动地点|会场)[：:]\s*(\S+)"),
    re.compile(r"(?:在|于)\s*(\S+(?:楼|馆|厅|堂|中心|教室|操场|场|室|报告厅|会议室))"),
]

# 联系方式提取正则
CONTACT_PATTERNS = [
    re.compile(r"(?:QQ群|群号|招新群)[：:]\s*(\d{5,12})"),
    re.compile(r"(?:QQ|QQ号)[：:]\s*(\d{5,12})"),
    re.compile(r"(?:微信|微信号)[：:]\s*([a-zA-Z][\w-]+)"),
    re.compile(r"(?:电话|手机|联系电话)[：:]\s*(1\d{10})"),
    re.compile(r"(?:邮箱|E[- ]?Mail)[：:]\s*([\w.@]+)"),
]

# 结束时间提取：匹配 "14:00-16:00" 中的结束时间
END_TIME_PATTERN = re.compile(r"(\d{1,2})[:：](\d{2})\s*[—\-～~至到]\s*(\d{1,2})[:：](\d{2})")


def is_activity_article(title: str) -> bool:
    """基于标题关键词判断是否为活动类文章"""
    if not title:
        return False

    title_lower = title.lower()

    # 排除
    for kw in EXCLUDE_KEYWORDS:
        if kw in title:
            return False

    # 匹配
    for kw in ACTIVITY_KEYWORDS:
        if kw in title:
            return True

    # 额外模式
    if re.search(r"\d{4}.*(?:年|年度).*(?:总结|计划|规划)", title):
        return False
    if re.search(r"招新|纳新|招募.*(?:成员|志愿者|干事)", title):
        return True

    return False


def extract_time(text: str) -> str:
    """从文本中提取时间，返回 ISO 格式字符串"""
    if not text:
        return ""

    for pattern in TIME_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 5 and all(g.isdigit() for g in groups if g):
                    y, m, d, h, mi = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4])
                    y = y if y > 100 else datetime.now(BEIJING_TZ).year
                    return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:00+08:00"
                elif len(groups) == 4 and all(g.isdigit() for g in groups if g):
                    now = datetime.now(BEIJING_TZ)
                    m, d, h, mi = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                    y = now.year if m >= now.month else now.year + 1  # 跨年处理
                    return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:00+08:00"
                elif len(groups) == 2:
                    now = datetime.now(BEIJING_TZ)
                    m, d = int(groups[0]), int(groups[1])
                    y = now.year if m >= now.month else now.year + 1
                    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+08:00"
                else:
                    return match.group(0).strip()
            except (ValueError, IndexError):
                return match.group(0).strip()

    return ""


def extract_location(text: str) -> str:
    """从文本中提取地点"""
    if not text:
        return ""
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            location = match.group(1).strip().rstrip("。，,.;；")
            if len(location) < 100:
                return location
    return ""


def extract_contact(text: str) -> str:
    """从文本中提取联系方式"""
    if not text:
        return ""
    results = []
    for pattern in CONTACT_PATTERNS:
        for match in pattern.finditer(text):
            val = match.group(1).strip()
            if val and len(val) < 200:
                prefix = match.group(0).split(":")[0].split("：")[0]
                results.append(f"{prefix}: {val}")
    return " | ".join(results[:3]) if results else ""


def extract_end_time(text: str, start_time: str) -> str:
    """从文本中提取结束时间，优先匹配时间范围格式"""
    if not text or not start_time:
        return ""
    m = END_TIME_PATTERN.search(text)
    if m:
        try:
            h, mi, eh, emi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            # 从 start_time 推断日期
            dt = datetime.fromisoformat(start_time)
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T{eh:02d}:{emi:02d}:00+08:00"
        except (ValueError, TypeError):
            pass
    return ""


def extract_activity_fallback(title: str, description: str) -> dict:
    """
    从文章的标题和描述中提取活动信息
    当无法从正文提取时，使用标题和摘要
    """
    text = f"{title} {description}"
    start_time = extract_time(text)

    return {
        "title": title,
        "description": (description.strip() or title).strip(),
        "location": extract_location(text),
        "contact": extract_contact(text),
        "start_time": start_time,
        "end_time": extract_end_time(text, start_time),
    }


def extract_activity(article: dict, club: dict) -> dict:
    """
    从文章对象中提取活动信息
    """
    title = article.get("title", "")
    description = article.get("description", "")
    content = article.get("content", "")

    # 合并文本源
    text = f"{title}\n{description}"
    if content:
        text += f"\n{content[:2000]}"

    desc_text = (description or "") + "\n" + (content or "")
    extracted = extract_activity_fallback(title, desc_text.strip())

    activity = {
        "id": f"act_{article.get('article_id', '')[:12]}" or f"act_{datetime.now(BEIJING_TZ).timestamp():.0f}",
        "club_id": article.get("club_id", club.get("id", "")),
        "title": extracted["title"],
        "description": extracted["description"],
        "category": club.get("category", "其他"),
        "location": extracted["location"],
        "start_time": extracted["start_time"],
        "end_time": extracted["end_time"],
        "article_url": article.get("article_url", ""),
        "article_id": article.get("article_id", ""),
        "cover_url": article.get("cover_url", ""),
        "publish_time": article.get("publish_time", ""),
        "contact": extracted["contact"],
        "source": "crawl",
        "status": compute_status(extracted["start_time"]),
        "created_at": datetime.now(BEIJING_TZ).isoformat(),
    }

    return activity


BEIJING_TZ = timezone(timedelta(hours=8))


def compute_status(start_time: str) -> str:
    """根据开始时间计算活动状态（北京时间 UTC+8）"""
    if not start_time:
        return "upcoming"
    try:
        start = datetime.fromisoformat(start_time)
        now = datetime.now(BEIJING_TZ)
        if start.tzinfo is None:
            start = start.replace(tzinfo=BEIJING_TZ)
        if start < now:
            return "ended"
        return "upcoming"
    except ValueError:
        return "upcoming"


def normalize_article(article: dict) -> dict:
    """统一新旧文章字段名，兼容 crawl_wechat.py 的新格式"""
    mapping = {
        "article_id": article.get("aid") or article.get("article_id", ""),
        "article_url": article.get("link") or article.get("article_url", ""),
        "cover_url": article.get("cover") or article.get("cover_url", ""),
        "description": article.get("digest") or article.get("description", ""),
    }
    # Unix 时间戳 → ISO 字符串
    create_ts = article.get("create_time", 0)
    if isinstance(create_ts, (int, float)) and create_ts > 1000000000:
        mapping["publish_time"] = datetime.fromtimestamp(create_ts, tz=BEIJING_TZ).isoformat()
    else:
        mapping["publish_time"] = article.get("publish_time", "")

    result = dict(article)
    result.update(mapping)
    return result


def main():
    print(f"[extract_activity] 启动 | mode={CONFIG['mode']}")

    # 加载爬虫原始数据
    raw_data = load_json(resolve(CONFIG["raw_path"]), {"articles": []})
    raw_articles = raw_data.get("articles", [])

    if not raw_articles:
        print("[extract_activity] 没有新文章需要处理")
        save_json(resolve(CONFIG["output_path"]), {"activities": []})
        return

    # 统一字段名
    articles = [normalize_article(a) for a in raw_articles]

    # 加载社团信息
    clubs_data = load_json(resolve(CONFIG["clubs_path"]), {"clubs": []})
    clubs_map = {}
    for club in clubs_data.get("clubs", []):
        clubs_map[club["id"]] = club

    # 提取活动
    activities = []
    for article in articles:
        club = clubs_map.get(article.get("club_id", ""), {})

        if not is_activity_article(article.get("title", "")):
            continue

        activity = extract_activity(article, club)
        activities.append(activity)

    # 输出
    output = {"activities": activities}
    save_json(resolve(CONFIG["output_path"]), output)

    print(f"[extract_activity] 完成: {len(activities)} 个活动 (共 {len(articles)} 篇文章)")


if __name__ == "__main__":
    main()
