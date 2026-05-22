"""
微信公众号爬虫 - 基于 profile_ext API

通过公众号的 __biz 参数，调用微信公众平台的 profile_ext 接口
获取公众号最近发布的文章列表。

用法:
    python crawl_wechat.py
"""

import json
import time
import random
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    request_with_retry,
    parse_timestamp,
    extract_article_id,
    load_json,
    save_json,
    default_headers,
)

# ===== 配置 =====
CONFIG = {
    "clubs_path": "site/data/clubs.json",
    "activities_path": "site/data/activities.json",
    "raw_output_path": "site/data/raw_articles.json",
    "cookie": os.environ.get("WECHAT_COOKIE", ""),
    "min_delay": 10,         # 每次请求最小延迟 (秒)
    "max_delay": 30,         # 每次请求最大延迟 (秒)
    "batch_size": 20,        # 每批处理数量
    "batch_interval": 120,   # 批次间隔 (秒)
    "max_retries": 3,
    "request_timeout": 15,
}

# 脚本所在目录的上级 (项目根目录)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(relative_path: str) -> str:
    """将相对路径解析为绝对路径"""
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(PROJECT_ROOT, relative_path)


def build_profile_ext_url(biz: str, offset: int = 0, count: int = 10) -> str:
    """构造 profile_ext API 请求 URL"""
    return (
        f"https://mp.weixin.qq.com/mp/profile_ext"
        f"?action=home&__biz={biz}"
        f"&scene=124&offset={offset}&count={count}"
    )


def parse_article_list(html: str, biz: str) -> list:
    """
    从 profile_ext 返回的 HTML 中解析文章列表

    注意：微信的 HTML 结构可能变化，需要根据实际情况调整选择器
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    articles = []

    # 尝试多种选择器 (不同版本的微信可能结构不同)
    article_items = (
        soup.select("div.weui_media_box")
        or soup.select(".js_article_list .weui_media_box")
        or soup.select(".mp_profile_article_list .weui_media_box")
        or soup.select(".profile_article_list .weui_media_box")
        or soup.select("[data-article_id]")
    )

    if not article_items:
        # 尝试查找所有包含文章信息的数据属性
        for item in soup.find_all(attrs={"data-article_id": True}):
            articles.append({
                "title": item.get("data-title", ""),
                "description": item.get("data-digest", ""),
                "publish_time": parse_timestamp(item.get("data-publish_time", "")),
                "article_id": item.get("data-article_id", ""),
                "article_url": f"https://mp.weixin.qq.com/s/{item.get('data-article_id', '')}",
                "cover_url": item.get("data-cover", ""),
                "biz": biz,
                "crawled_at": datetime.now().isoformat(),
            })
        return articles

    for item in article_items:
        title_el = item.select_one("h4.weui_media_title, .article_title, [data-title]")
        desc_el = item.select_one("p.weui_media_desc, .article_summary, [data-digest]")
        time_el = item.select_one("span.weui_media_extra_info, .publish_time, [data-publish_time]")
        link_el = item.select_one("a")
        cover_el = item.select_one("img.weui_media_thumb, .article_thumb img")

        title = ""
        if title_el:
            title = title_el.get_text(strip=True)
        elif item.get("data-title"):
            title = item.get("data-title", "")

        if not title:
            continue

        article = {
            "title": title,
            "description": desc_el.get_text(strip=True) if desc_el else "",
            "publish_time": parse_timestamp(time_el.get_text(strip=True)) if time_el else "",
            "article_id": "",
            "article_url": "",
            "cover_url": cover_el.get("data-src", "") if cover_el else "",
            "biz": biz,
            "crawled_at": datetime.now().isoformat(),
        }

        # 提取文章链接
        if link_el and link_el.get("href"):
            href = link_el["href"]
            article["article_url"] = f"https://mp.weixin.qq.com{href}" if href.startswith("/") else href
            article["article_id"] = extract_article_id(href)
        elif item.get("data-article_id"):
            article["article_id"] = item["data-article_id"]
            article["article_url"] = f"https://mp.weixin.qq.com/s/{item['data-article_id']}"

        if article["article_id"]:
            articles.append(article)

    return articles


def crawl_single_club(biz: str) -> list:
    """
    爬取单个公众号的文章列表

    Args:
        biz: 公众号 __biz 参数

    Returns:
        文章列表 [{title, description, publish_time, article_id, article_url, ...}]
    """
    if not biz:
        return []

    url = build_profile_ext_url(biz, offset=0, count=10)

    resp = request_with_retry(
        url,
        cookie=CONFIG["cookie"],
        max_retries=CONFIG["max_retries"],
        timeout=CONFIG["request_timeout"],
    )

    if resp is None:
        return []

    articles = parse_article_list(resp.text, biz)
    print(f"    -> 解析到 {len(articles)} 篇文章")
    return articles


def load_existing_article_ids() -> set:
    """加载已存在的文章 ID 集合，用于增量判断"""
    data = load_json(resolve_path(CONFIG["activities_path"]), {})
    activities = data.get("activities", [])
    return {a.get("article_id", "") for a in activities if a.get("article_id")}


def main():
    print("=" * 60)
    print(f"微信爬虫启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 加载社团列表
    clubs_data = load_json(resolve_path(CONFIG["clubs_path"]), {})
    clubs = [c for c in clubs_data.get("clubs", []) if c.get("biz") and c.get("is_active") is not False]
    print(f"待爬取公众号: {len(clubs)} 个")

    if not clubs:
        print("[!] 没有配置公众号 __biz，请在 clubs.json 中补充")
        # 生成空输出，避免下游脚本报错
        save_json(resolve_path(CONFIG["raw_output_path"]), {"articles": [], "crawled_at": datetime.now().isoformat()})
        return

    # 2. 加载已有文章 ID (增量)
    existing_ids = load_existing_article_ids()
    print(f"已有文章: {len(existing_ids)} 篇")

    # 3. 分批爬取
    all_new_articles = []
    total_crawled = 0
    total_errors = 0
    batch_count = (len(clubs) + CONFIG["batch_size"] - 1) // CONFIG["batch_size"]

    for batch_idx in range(batch_count):
        start = batch_idx * CONFIG["batch_size"]
        end = min(start + CONFIG["batch_size"], len(clubs))
        batch = clubs[start:end]

        print(f"\n--- 批次 {batch_idx + 1}/{batch_count} ({start + 1}-{end}) ---")

        for club in batch:
            name = club.get("name", "未知")
            biz = club["biz"]
            print(f"  [{club.get('id', '?')}] {name}")

            articles = crawl_single_club(biz)
            total_crawled += len(articles)

            # 增量过滤
            new_articles = [a for a in articles if a["article_id"] not in existing_ids]
            if new_articles:
                print(f"    -> 新文章: {len(new_articles)} 篇")
                for a in new_articles:
                    a["club_id"] = club["id"]
                all_new_articles.extend(new_articles)

            if articles and not new_articles:
                print(f"    -> 无新文章")

            # 随机延迟
            delay = random.randint(CONFIG["min_delay"], CONFIG["max_delay"])
            time.sleep(delay)

        # 批次间休息
        if batch_idx < batch_count - 1:
            print(f"\n批次间休息 {CONFIG['batch_interval']}s...")
            time.sleep(CONFIG["batch_interval"])

    # 4. 输出
    output = {
        "articles": all_new_articles,
        "crawled_at": datetime.now().isoformat(),
        "stats": {
            "total_clubs": len(clubs),
            "total_crawled": total_crawled,
            "new_articles": len(all_new_articles),
        },
    }

    save_json(resolve_path(CONFIG["raw_output_path"]), output)

    print(f"\n{'=' * 60}")
    print(f"爬取完成!")
    print(f"  处理公众号: {len(clubs)}")
    print(f"  获取文章: {total_crawled}")
    print(f"  新文章: {len(all_new_articles)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
