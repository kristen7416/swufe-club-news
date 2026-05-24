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
import time
import random
import asyncio
import html as html_mod
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from utils import load_json, save_json
from wechat_to_md import fetch_markdown


def safe_print(*args, **kwargs):
    """终端兼容打印（处理 GBK 无法编码的字符）"""
    text = " ".join(str(a) for a in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        # 编码为终端编码，替换无法显示的字符
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), **kwargs)

# ===== 配置 =====
CONFIG = {
    "clubs_path": "site/data/clubs.json",
    "raw_path": "site/data/raw_articles.json",
    "output_path": "site/data/extracted_activities.json",
    "mode": "ai",  # "rule" 或 "ai"
    "ai": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "endpoint": "https://api.deepseek.com/chat/completions",
        "timeout": 30,
        "max_text_length": 3000,
        "retry_count": 1,
        "retry_delay": 3,
    },
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path):
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


# ===== 文章内容抓取 =====

FETCH_CONFIG = {
    "enabled": True,
    "method": "auto",  # "auto" (先 Camoufox 后 requests), "requests", "camoufox"
    "delay_min": 3,
    "delay_max": 6,
    "timeout": 15,
    "max_retries": 2,
}

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def extract_text_from_article_html(html_text: str) -> str:
    """从微信文章 HTML 中提取纯文本正文"""
    if not html_text:
        return ""

    for pattern in [
        r'class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script',
        r'id="js_content"[^>]*>(.*?)</div>\s*<script',
    ]:
        m = re.search(pattern, html_text, re.DOTALL)
        if m:
            content = m.group(1)
            content = re.sub(r'<br\s*/?>', '\n', content)
            content = re.sub(r'</p>', '\n</p>', content)
            content = re.sub(r'</section>', '\n</section>', content)
            content = re.sub(r'<[^>]+>', '', content)
            content = html_mod.unescape(content)
            content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = re.sub(r'[ \t]{2,}', ' ', content)
            content = content.strip()
            if content:
                return content
    return ""


def fetch_article_markdown(url: str) -> str:
    """使用 Camoufox 反检测浏览器 + Markdownify 获取文章 Markdown 文本"""
    if not url or "mp.weixin.qq.com" not in url:
        return ""

    try:
        result = asyncio.run(fetch_markdown(url))
        if result:
            print(f"    [抓取-Camoufox] 获取 Markdown {len(result)} 字符")
        else:
            print(f"    [抓取-Camoufox] 未能提取内容")
        return result
    except Exception as e:
        print(f"    [抓取-Camoufox] 异常: {e}")
        return ""


def fetch_article_text(url: str) -> str:
    """抓取微信文章 HTML 并提取正文文本，支持 Camoufox + requests 双引擎"""
    if not url or "mp.weixin.qq.com" not in url:
        return ""

    # Camoufox 模式：直接使用浏览器引擎
    if FETCH_CONFIG["method"] == "camoufox":
        return fetch_article_markdown(url)

    # "auto" 模式：先试 Camoufox，失败则降级 requests
    if FETCH_CONFIG["method"] == "auto":
        md_text = fetch_article_markdown(url)
        if md_text:
            return md_text
        print(f"    [抓取] Camoufox 失败，降级到 requests")

    # requests 模式（默认/降级）
    for attempt in range(FETCH_CONFIG["max_retries"] + 1):
        try:
            r = requests.get(url, headers=FETCH_HEADERS, timeout=FETCH_CONFIG["timeout"])
            r.encoding = "utf-8"

            if r.status_code != 200:
                print(f"    [抓取] HTTP {r.status_code}, 跳过: {url[:50]}...")
                return ""

            if "访问异常" in r.text or "js_verify" in r.text:
                if attempt < FETCH_CONFIG["max_retries"]:
                    wait = (attempt + 1) * 5
                    print(f"    [抓取] 验证页, {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                print(f"    [抓取] 验证页无法绕过, 跳过: {url[:50]}...")
                return ""

            text = extract_text_from_article_html(r.text)
            if text:
                return text

            print(f"    [抓取] 未能提取正文, 跳过: {url[:50]}...")
            return ""

        except requests.RequestException as e:
            if attempt < FETCH_CONFIG["max_retries"]:
                wait = (attempt + 1) * 3
                print(f"    [抓取] 请求失败: {e}, {wait}s 后重试...")
                time.sleep(wait)
                continue
            print(f"    [抓取] 请求失败已达最大重试: {e}")
            return ""

    return ""


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
    re.compile(r"(?:地点|地址|位置|活动地点|会场)[：:]\s*([^，。,\s；;]{2,12})"),
    re.compile(r"(?:在|于)\s*([^，。,\s]{2,10}(?:楼|馆|厅|堂|中心|教室|室|广场|操场|场|报告厅))"),
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


# ===== 西南财经大学校园地点库 =====

# 校园地点按长度降序（优先匹配最长具体名称）
KNOWN_LOCATIONS = sorted([
    # ---- 柳林校区 - 教学楼 ----
    "经世楼A区", "经世楼B区", "经世楼C区",
    "颐德楼H区", "颐德楼I区",
    "经世楼", "颐德楼", "通博楼", "明德楼", "格致楼", "诚正楼", "弘远楼",
    # ---- 柳林校区 - 食堂 ----
    "一粟堂", "三味堂", "五谷堂",
    # ---- 柳林校区 - 宿舍 ----
    "梅园", "兰园", "竹园", "菊园", "松园", "榕园", "智园", "慧园", "信园", "敏园",
    # ---- 柳林校区 - 体育 ----
    "晨曦体育场", "朝晖体育场",
    # ---- 柳林校区 - 其他 ----
    "学生活动中心", "济民广场", "经世楼草坪", "钟楼", "待书轩",
    # ---- 光华校区 - 教学楼 ----
    "光华楼", "励志楼", "文渊楼",
    # ---- 光华校区 - 宿舍 ----
    "博学园", "明辨园", "笃行园", "致知园", "住友苑",
    # ---- 光华校区 - 体育 ----
    "光华体育馆", "光华运动场",
    # ---- 光华校区 - 其他 ----
    "光华会堂", "光华门",
    # ---- 通用跨校区 ----
    "图书馆", "体育馆",
], key=len, reverse=True)

# 教学楼楼名列表（用于匹配楼名+房间号）
CAMPUS_BUILDINGS = [
    "经世楼", "颐德楼", "通博楼", "明德楼", "格致楼", "诚正楼", "弘远楼",
    "光华楼", "励志楼", "文渊楼",
]

# 楼名+房间号模式：如 "经世楼E101" "颐德楼I304"
BUILDING_ROOM_RE = re.compile(
    r"(?:" + "|".join(re.escape(b) for b in CAMPUS_BUILDINGS) + r")"
    r"[A-Za-z]\d{3,4}\b"
)


def match_campus_location(text: str) -> str:
    """在文本中匹配西南财大已知地点，返回最具体的匹配"""
    if not text:
        return ""

    # 1. 优先匹配楼名+房间号（最精确，如"颐德楼I304"）
    m = BUILDING_ROOM_RE.search(text)
    if m:
        return m.group(0).strip()

    # 2. 匹配已知地点名称（按长度降序，最长匹配优先）
    #    避免过长文本中大量不相关匹配，仅在前 300 字内搜索
    search_area = text[:300]
    for loc in KNOWN_LOCATIONS:
        if loc in search_area:
            return loc

    return ""


# ===== DeepSeek AI 提取 =====

DEEPSEEK_SYSTEM_PROMPT = """你是一个专门从中文社团活动推文中提取结构化信息的助手。
请从给定的文章文本中提取活动信息，严格按照 JSON 格式返回。

提取规则：
1. title: 活动标题，清理多余空格和特殊字符，保持简洁
2. description: 活动描述，50-200字摘要
3. location: 活动地点，如明确提及则提取，否则为空字符串
4. start_time: 开始时间，ISO 8601 格式 YYYY-MM-DDTHH:MM:SS+08:00，使用北京时间
5. end_time: 结束时间，ISO 8601 格式 YYYY-MM-DDTHH:MM:SS+08:00，使用北京时间。**务必从文章中的时间范围描述（如"14:00-16:00""X点至X点"）提取结束时间**
6. contact: 联系方式（QQ群、微信群、电话、邮箱等），如 "QQ群: 123456" 或 "微信: abc123"
7. status: 活动状态，**基于文章中的时间描述推断活动状态**："upcoming"（活动尚未开始）, "ongoing"（活动正在进行或包含"进行时"等表述）, "ended"（活动已结束或包含"圆满""回顾"等表述）
8. category: 活动分类，从以下选择：学术科技, 文化艺术, 体育竞技, 志愿服务, 创新创业, 其他

注意：
- 如果某字段无法从文本中提取，设为空字符串
- 时间必须使用北京时间时区 +08:00
- **end_time 是关键字段，请仔细从时间范围描述中提取。如果明确提到活动时间段（如"下午2:00至4:00"），务必填充 end_time**
- **status 应优先从文本中的时间描述和关键词推断，而非仅靠文章发布时间**
- 只返回 JSON 对象，不要包含其他文字说明"""

DEEPSEEK_USER_PROMPT_TEMPLATE = """请从以下社团活动文章中提取结构化信息：

标题：{title}

文章正文：
{text}

请返回 JSON 对象，包含：title, description, location, start_time, end_time, contact, status, category

要求：
- end_time 必须从时间范围中提取（如 "14:00-16:00" → 提取结束时间）
- status 根据文章内容推断（ended/ongoing/upcoming），特别是标题含"圆满""回顾"等词应为 ended"""


def extract_with_deepseek(title: str, text: str) -> dict:
    """调用 DeepSeek API 从文章文本中提取结构化活动信息

    Args:
        title: 文章标题
        text: 文章正文文本（将被截断至 max_text_length）

    Returns:
        dict: 结构化活动信息，API 失败时返回空 dict
    """
    api_key = CONFIG["ai"]["api_key"]
    if not api_key:
        print("    [DeepSeek] 未配置 API key，跳过 AI 提取")
        return {}

    truncated = text[:CONFIG["ai"]["max_text_length"]]

    payload = {
        "model": CONFIG["ai"]["model"],
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {"role": "user", "content": DEEPSEEK_USER_PROMPT_TEMPLATE.format(
                title=title, text=truncated
            )},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(CONFIG["ai"]["retry_count"] + 1):
        try:
            resp = requests.post(
                CONFIG["ai"]["endpoint"],
                json=payload,
                headers=headers,
                timeout=CONFIG["ai"]["timeout"],
            )
            if resp.status_code != 200:
                print(f"    [DeepSeek] HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt < CONFIG["ai"]["retry_count"]:
                    time.sleep(CONFIG["ai"]["retry_delay"])
                    continue
                return {}

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                print("    [DeepSeek] 响应为空")
                return {}

            result = json.loads(content)
            validated = {}
            for field in ["title", "description", "location", "start_time",
                          "end_time", "contact", "status", "category"]:
                val = result.get(field, "")
                validated[field] = str(val).strip() if val else ""

            print(f"    [DeepSeek] 提取成功: {validated.get('title', '')[:30]}")
            return validated

        except requests.Timeout:
            print(f"    [DeepSeek] 请求超时")
            if attempt < CONFIG["ai"]["retry_count"]:
                time.sleep(CONFIG["ai"]["retry_delay"])
                continue
            return {}
        except requests.RequestException as e:
            print(f"    [DeepSeek] 请求异常: {e}")
            return {}
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"    [DeepSeek] 响应解析失败: {e}")
            return {}

    return {}


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


def extract_time(text: str, ref_time: str = "") -> str:
    """从文本中提取时间，返回 ISO 格式字符串

    Args:
        text: 要提取的文本
        ref_time: 参考时间（如文章 publish_time），用于推断只有月日无年份的时间
    """
    if not text:
        return ""

    # 解析参考时间
    ref_dt = None
    if ref_time:
        try:
            ref_dt = datetime.fromisoformat(ref_time)
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=BEIJING_TZ)
        except (ValueError, TypeError):
            pass

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
                    m, d, h, mi = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                    if ref_dt:
                        y = ref_dt.year if m >= ref_dt.month else ref_dt.year + 1
                    else:
                        now = datetime.now(BEIJING_TZ)
                        y = now.year if m >= now.month else now.year + 1
                    return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:00+08:00"
                elif len(groups) == 2:
                    m, d = int(groups[0]), int(groups[1])
                    if ref_dt:
                        y = ref_dt.year if m >= ref_dt.month else ref_dt.year + 1
                    else:
                        now = datetime.now(BEIJING_TZ)
                        y = now.year if m >= now.month else now.year + 1
                    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+08:00"
                else:
                    return match.group(0).strip()
            except (ValueError, IndexError):
                return match.group(0).strip()

    return ""


def extract_location(text: str) -> str:
    """从文本中提取地点，优先使用 SWUFE 校园地点库，其次正则"""
    if not text:
        return ""

    # 1. 显式"地点："标签正则（最高精度，明确标注的地址）
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            location = match.group(1).strip().rstrip("。，,.;；：:")
            location = location[:10]
            if len(location) < 2:
                continue
            if any(kw in location for kw in ["时间", "电话", "QQ", "微信", "http", "邮箱"]):
                continue
            return location

    # 2. 校园地点库匹配（楼名+房间号 / 已知名称，覆盖正则遗漏的情况）
    campus_loc = match_campus_location(text)
    if campus_loc:
        return campus_loc

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


def extract_activity_fallback(title: str, description: str, article_body: str = "", publish_time: str = "") -> dict:
    """
    从文章的标题和描述中提取活动信息
    支持 rule 和 ai 两种模式，AI 失败时自动降级到规则模式
    """
    text = f"{title} {description}"

    # ---- AI 模式 ----
    if CONFIG["mode"] == "ai":
        print(f"    [提取] AI 模式")
        ai_body = article_body or text
        ai_result = extract_with_deepseek(title, ai_body)
        if ai_result:
            # 用规则提取器补齐 AI 缺失的关键字段
            if not ai_result.get("location"):
                ai_result["location"] = extract_location(text)
            if not ai_result.get("contact"):
                ai_result["contact"] = extract_contact(text)
            if not ai_result.get("start_time"):
                ai_result["start_time"] = extract_time(text, publish_time)
            if not ai_result.get("end_time") and ai_result.get("start_time"):
                ai_result["end_time"] = extract_end_time(text, ai_result["start_time"])
            return ai_result
        else:
            print(f"    [提取] AI 提取失败，回退到规则模式")

    # ---- 规则模式（默认） ----
    start_time = extract_time(text, publish_time)

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
    优先从文章 URL 抓取正文进行提取，其次使用摘要
    """
    title = article.get("title", "")
    description = article.get("description", "")
    content = article.get("content", "")
    article_url = article.get("article_url", "")

    # 尝试抓取文章正文
    article_body = ""
    if FETCH_CONFIG["enabled"] and article_url:
        print(f"    [抓取] {article_url[:60]}...")
        article_body = fetch_article_text(article_url)
        if article_body:
            print(f"    [抓取] 获取正文 {len(article_body)} 字符")
        else:
            print(f"    [抓取] 未获取到正文")
        # 请求间隔
        time.sleep(random.uniform(FETCH_CONFIG["delay_min"], FETCH_CONFIG["delay_max"]))

    # 合并文本源：全文 > 摘要
    full_text = title + "\n" + (article_body or description or "")
    if content and not article_body:
        full_text += "\n" + content[:2000]

    extracted = extract_activity_fallback(title, full_text, article_body, article.get("publish_time", ""))

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
        "status": _resolve_status(extracted, title),
        "created_at": datetime.now(BEIJING_TZ).isoformat(),
    }

    return activity


BEIJING_TZ = timezone(timedelta(hours=8))


def compute_status(start_time: str, end_time: str = "", publish_time: str = "") -> str:
    """根据开始/结束时间计算活动状态（北京时间 UTC+8），支持三状态"""
    now = datetime.now(BEIJING_TZ)

    try:
        start_dt = datetime.fromisoformat(start_time) if start_time else None
    except (ValueError, TypeError):
        start_dt = None

    try:
        end_dt = datetime.fromisoformat(end_time) if end_time else None
    except (ValueError, TypeError):
        end_dt = None

    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=BEIJING_TZ)
    if end_dt and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=BEIJING_TZ)

    # 年份合理性检查：如果 start_time 年份 > 发布年份且修正后在过去，说明推断错误
    if start_dt and publish_time:
        try:
            pub_dt = datetime.fromisoformat(publish_time)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=BEIJING_TZ)
            if start_dt.year > pub_dt.year and start_dt > now and pub_dt < now:
                try:
                    corrected = start_dt.replace(year=pub_dt.year)
                except ValueError:
                    corrected = None
                if corrected and corrected < now:
                    start_dt = None
        except (ValueError, TypeError):
            pass

    if end_dt and end_dt < now:
        return "ended"
    if start_dt and start_dt <= now:
        if not end_dt or end_dt > now:
            if end_dt:
                return "ongoing"
            if (now - start_dt).days > 7:
                return "ended"
            return "ongoing"
        return "ended"
    if start_dt and start_dt > now:
        return "upcoming"

    # 启发式：发布时间 > 7天 且 开始时间 > 1天前 → 已结束
    if publish_time and start_dt:
        try:
            pub_dt = datetime.fromisoformat(publish_time)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=BEIJING_TZ)
            if (now - pub_dt).days > 7 and (now - start_dt).days > 1:
                return "ended"
        except (ValueError, TypeError):
            pass

    return "upcoming"


# 标题关键词 → 状态推断
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


def _resolve_status(extracted: dict, title: str) -> str:
    """三级状态推断：time-based → title-based → default"""
    # 1. 优先从时间推断
    status = compute_status(
        extracted.get("start_time", ""),
        extracted.get("end_time", ""),
    )
    # 如果有准确的时间数据，直接返回
    if extracted.get("start_time") or extracted.get("end_time"):
        return status
    # 2. 无时间数据时，从标题推断
    title_status = infer_status_from_title(title)
    if title_status:
        return title_status
    # 3. 默认
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


def enrich_existing_activities():
    """读取现有 activities.json，抓取文章正文补全缺失字段"""
    activities_path = resolve("site/data/activities.json")
    data = load_json(activities_path, {"activities": []})
    activities = data.get("activities", [])

    if not activities:
        print("[enrich] 没有活动需要补全")
        return

    # 加载社团信息用于分类
    clubs_data = load_json(resolve(CONFIG["clubs_path"]), {"clubs": []})
    clubs_map = {c["id"]: c for c in clubs_data.get("clubs", []) if c.get("id")}

    updated = 0
    for act in activities:
        # 检查哪些字段缺失
        missing = []
        if not act.get("contact"):
            missing.append("contact")
        if not act.get("location"):
            missing.append("location")
        if not act.get("start_time"):
            missing.append("start_time")
        if not act.get("end_time"):
            missing.append("end_time")
        if not act.get("description") or len(act.get("description", "")) < 20:
            missing.append("description")

        if not missing:
            continue

        url = act.get("article_url", "")
        if not url:
            continue

        title_clean = act['title'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')[:40]
        safe_print(f"\n  [enrich] {act['id']} {title_clean}")
        safe_print(f"           缺失: {', '.join(missing)}")
        safe_print(f"           文章: {url[:60]}...")

        article_text = fetch_article_text(url)
        if not article_text:
            continue

        safe_print(f"           获取正文 {len(article_text)} 字符")

        # 对缺失字段逐一提取
        title = act.get("title", "")
        text = f"{title}\n{article_text}"

        if not act.get("contact"):
            contact = extract_contact(text)
            if contact:
                act["contact"] = contact
                safe_print(f"           提取联系方式: {contact}")

        if not act.get("location"):
            location = extract_location(text)
            if location:
                act["location"] = location
                safe_print(f"           提取地点: {location}")

        if not act.get("start_time"):
            start_time = extract_time(text, act.get("publish_time", ""))
            if start_time:
                act["start_time"] = start_time
                act["status"] = compute_status(start_time)
                safe_print(f"           提取开始时间: {start_time}")

        if not act.get("end_time"):
            end_time = extract_end_time(text, act.get("start_time", ""))
            if end_time:
                act["end_time"] = end_time
                safe_print(f"           提取结束时间: {end_time}")

        if not act.get("description") or len(act.get("description", "")) < 20:
            # 使用文章正文前 200 字作为描述
            desc = article_text[:200].strip()
            if desc:
                act["description"] = desc
                safe_print(f"           更新描述: {desc[:40]}...")

        updated += 1
        time.sleep(random.uniform(FETCH_CONFIG["delay_min"], FETCH_CONFIG["delay_max"]))

    # 保存
    if updated > 0:
        data["last_updated"] = datetime.now(BEIJING_TZ).isoformat()
        # 更新统计
        status_counts = {"upcoming": 0, "ongoing": 0, "ended": 0}
        for a in activities:
            s = a.get("status", "upcoming")
            if s in status_counts:
                status_counts[s] += 1
        data["status_counts"] = status_counts
        data["total_count"] = len(activities)

        save_json(activities_path, data)
        safe_print(f"\n[enrich] 完成! 更新 {updated}/{len(activities)} 个活动")
    else:
        safe_print("\n[enrich] 所有活动字段已完整，无需更新")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="活动信息提取模块")
    parser.add_argument("--enrich", action="store_true", help="补全现有 activities.json 的缺失字段")
    parser.add_argument("--no-fetch", action="store_true", help="禁用文章正文抓取")
    args = parser.parse_args()

    if args.no_fetch:
        FETCH_CONFIG["enabled"] = False
        print("[extract_activity] 文章正文抓取已禁用")

    if args.enrich:
        print(f"[extract_activity] 补全模式 | {datetime.now(BEIJING_TZ).isoformat()}")
        enrich_existing_activities()
        return

    if CONFIG["mode"] == "ai":
        key_status = "已配置" if CONFIG["ai"]["api_key"] else "未配置 API key"
        print(f"[extract_activity] 提取模式 | mode=ai | {key_status}")
    else:
        print("[extract_activity] 提取模式 | mode=rule")

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
