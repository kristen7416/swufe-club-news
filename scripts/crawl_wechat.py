"""
微信公众号爬虫 - 基于 cgi-bin/appmsgpublish API

通过公众号的 __biz (fakeid) 参数，调用微信公众平台 cgi-bin/appmsgpublish 接口
获取公众号最近发布的文章列表。

用法:
    python crawl_wechat.py
"""

import json
import time
import random
import os
import sys
import re
from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))

import requests

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import load_json, save_json

# ===== 配置 =====
CONFIG = {
    "clubs_path": "site/data/clubs.json",
    "activities_path": "site/data/activities.json",
    "raw_output_path": "site/data/raw_articles.json",
    "cookie": os.environ.get("WECHAT_COOKIE", ""),
    "min_delay": 5,             # 每次请求最小延迟 (秒)
    "max_delay": 15,            # 每次请求最大延迟 (秒)
    "batch_size": 20,           # 每批处理数量
    "batch_interval": 60,       # 批次间隔 (秒)
    "max_articles_per_club": 20, # 每个公众号最多获取文章数
    "request_timeout": 15,
    "max_age_days": 10,          # 仅爬取近 N 天内的文章
}

# 脚本所在目录的上级 (项目根目录)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(relative_path: str) -> str:
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(PROJECT_ROOT, relative_path)


def get_session_and_token(cookie_str: str) -> tuple:
    """创建 Session 并获取 token"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://mp.weixin.qq.com/",
    })
    # 设置 cookie
    for kv in cookie_str.split("; "):
        name, _, val = kv.partition("=")
        if name and val:
            s.cookies.set(name.strip(), val.strip(), domain=".qq.com", path="/")

    # 获取首页 token
    r = s.get("https://mp.weixin.qq.com/", timeout=CONFIG["request_timeout"])
    tokens = re.findall(r'token["\']?\s*[:=]\s*["\']?(\d+)["\']?', r.text)
    token = tokens[0] if tokens else ""

    if not token:
        print("[!] 未能获取到 token，请检查 cookie 是否有效")
        return None, ""

    return s, token


def crawl_club_articles(session, token: str, biz: str, max_count: int = 20) -> list:
    """
    爬取单个公众号的所有文章

    Args:
        session: requests.Session (已登录)
        token: 从首页获取的 token
        biz: 公众号 __biz / fakeid
        max_count: 最大获取数量

    Returns:
        文章列表 [{title, link, cover, create_time, update_time, digest, aid}]
    """
    all_articles = []
    begin = 0
    count = min(max_count, 20)  # API 单次最多返回 20 条

    while len(all_articles) < max_count:
        params = {
            "sub": "list",
            "sub_action": "list_ex",
            "begin": begin,
            "count": count,
            "fakeid": biz,
            "token": token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }

        try:
            r = session.get(
                "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
                params=params,
                timeout=CONFIG["request_timeout"],
            )
            data = r.json()
        except Exception as e:
            print(f"    [错误] 请求失败: {e}")
            break

        ret = data.get("base_resp", {}).get("ret", -1)
        err_msg = data.get("base_resp", {}).get("errmsg", "")

        if ret == 200013:
            print("    [警告] 触发频率限制，暂停...")
            time.sleep(30)
            continue
        if ret == 200003:
            print("    [错误] Session 无效，需要重新登录")
            break
        if ret != 0:
            print(f"    [警告] API 错误: {err_msg} (ret={ret})")
            break

        # 解析文章列表
        try:
            publish_page = json.loads(data.get("publish_page", "{}"))
        except json.JSONDecodeError:
            print("    [错误] 解析 publish_page 失败")
            break

        publish_list = publish_page.get("publish_list", [])
        if not publish_list:
            break  # 没有更多文章了

        for pub in publish_list:
            pub_info = pub.get("publish_info", {})
            if isinstance(pub_info, str):
                try:
                    pub_info = json.loads(pub_info)
                except json.JSONDecodeError:
                    continue

            for art in pub_info.get("appmsgex", []):
                link = art.get("link", "")
                aid = art.get("aid", "")
                title = art.get("title", "")

                if not link or not title:
                    continue

                create_time = art.get("create_time", 0)
                # 过滤超过 max_age_days 的旧文章
                if create_time and create_time > 1000000000:
                    cutoff_ts = (datetime.now(BEIJING_TZ) - timedelta(days=CONFIG["max_age_days"])).timestamp()
                    if create_time < cutoff_ts:
                        continue

                article = {
                    "aid": aid,
                    "title": title,
                    "link": link,
                    "cover": art.get("cover", ""),
                    "create_time": create_time,
                    "update_time": art.get("update_time", 0),
                    "digest": art.get("digest", ""),
                    "copyright_stat": art.get("copyright_stat", 0),
                }

                if article not in all_articles:
                    all_articles.append(article)

                if len(all_articles) >= max_count:
                    break
            if len(all_articles) >= max_count:
                break

        # 检查是否还有更多页
        total_count = publish_page.get("total_count", 0)
        begin += len(publish_list)
        if begin >= total_count or begin >= max_count:
            break

        # 翻页延迟
        time.sleep(random.uniform(1, 3))

    return all_articles


def match_club_by_title(title: str, club_names_sorted: list, club_name_map: dict) -> str:
    """根据文章标题匹配社团名称，返回 club_id。未匹配返回空字符串"""
    if not title:
        return ""
    for cname in club_names_sorted:
        if cname in title:
            return club_name_map[cname]
    return ""


def load_existing_article_ids() -> set:
    """加载已存在的文章 ID 集合"""
    data = load_json(resolve_path(CONFIG["activities_path"]), {})
    return {a.get("link", a.get("article_url", "")) for a in data.get("activities", []) if a.get("link") or a.get("article_url")}


def main():
    print("=" * 60)
    print(f"微信爬虫启动 | {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
    print(f"API: cgi-bin/appmsgpublish")
    print("=" * 60)

    # 0. 检查 cookie
    cookie = CONFIG["cookie"]
    if not cookie:
        print("[!] 未配置 WECHAT_COOKIE 环境变量")
        print("   请在 GitHub Secrets 中设置 WECHAT_COOKIE")
        # 生成空输出
        save_json(resolve_path(CONFIG["raw_output_path"]), {"articles": [], "crawled_at": datetime.now(BEIJING_TZ).isoformat()})
        return

    # 1. 登录并获取 token
    print("\n[1/5] 登录微信公众平台...")
    session, token = get_session_and_token(cookie)
    if not session or not token:
        print("[!] 登录失败")
        save_json(resolve_path(CONFIG["raw_output_path"]), {"articles": [], "crawled_at": datetime.now(BEIJING_TZ).isoformat()})
        return
    print(f"      登录成功! token: {token}")

    # 2. 加载社团列表
    print("\n[2/5] 加载社团列表...")
    clubs_data = load_json(resolve_path(CONFIG["clubs_path"]), {})
    all_clubs = clubs_data.get("clubs", [])
    clubs = [c for c in all_clubs if c.get("biz") and c.get("is_active") is not False]
    print(f"      待爬取公众号: {len(clubs)} 个 (含聚合账号)")

    # 构建社团名称 → club_id 映射（用于聚合账号的文章匹配）
    club_name_map = {}
    for c in all_clubs:
        name = c.get("name", "")
        if name:
            club_name_map[name] = c.get("id", "")
        # 公众号名称也作为匹配键
        wname = c.get("wechat_name", "")
        if wname and wname != name:
            club_name_map[wname] = c.get("id", "")
        # 短名称（去掉"西南财经大学"前缀）
        short = name.replace("西南财经大学", "").replace("swufe", "").replace("SWUFE", "").strip()
        if short and short not in club_name_map:
            club_name_map[short] = c.get("id", "")
    # 按名称长度降序排序，优先匹配最长名称
    club_names_sorted = sorted(club_name_map.keys(), key=len, reverse=True)

    if not clubs:
        save_json(resolve_path(CONFIG["raw_output_path"]), {"articles": [], "crawled_at": datetime.now(BEIJING_TZ).isoformat()})
        return

    # 3. 加载已有文章 ID (增量)
    print("\n[3/5] 加载已有文章...")
    existing_ids = load_existing_article_ids()
    print(f"      已有文章: {len(existing_ids)} 篇")

    # 4. 分批爬取
    print("\n[4/5] 开始爬取...")
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
            club_id = club.get("id", "?")
            is_aggregator = club.get("is_aggregator", False)

            if is_aggregator:
                print(f"  [{club_id}] {name} (聚合账号, 将按标题匹配社团)")

            try:
                articles = crawl_club_articles(session, token, biz, CONFIG["max_articles_per_club"])
                total_crawled += len(articles)

                # 增量过滤
                new_count = 0
                for a in articles:
                    url_key = a["link"]
                    if url_key not in existing_ids:
                        # 聚合账号：按标题匹配到具体社团
                        if is_aggregator:
                            matched_id = match_club_by_title(a.get("title", ""), club_names_sorted, club_name_map)
                            if matched_id:
                                a["club_id"] = matched_id
                            else:
                                continue  # 未匹配到任何社团则跳过
                        else:
                            a["club_id"] = club_id
                        all_new_articles.append(a)
                        existing_ids.add(url_key)
                        new_count += 1

                if is_aggregator:
                    print(f"    -> 获取 {len(articles)} 篇, 匹配到 {new_count} 篇")
                else:
                    print(f"    -> 获取 {len(articles)} 篇, 新 {new_count} 篇")

            except Exception as e:
                total_errors += 1
                print(f"    [错误] 爬取失败: {e}")

            # 随机延迟
            delay = random.randint(CONFIG["min_delay"], CONFIG["max_delay"])
            time.sleep(delay)

        # 批次间休息
        if batch_idx < batch_count - 1:
            print(f"\n批次间休息 {CONFIG['batch_interval']}s...")
            time.sleep(CONFIG["batch_interval"])

    # 5. 输出
    print("\n[5/5] 保存结果...")
    output = {
        "articles": all_new_articles,
        "crawled_at": datetime.now(BEIJING_TZ).isoformat(),
        "stats": {
            "total_clubs": len(clubs),
            "total_crawled": total_crawled,
            "new_articles": len(all_new_articles),
            "errors": total_errors,
        },
    }

    save_json(resolve_path(CONFIG["raw_output_path"]), output)

    print(f"\n{'=' * 60}")
    print(f"爬取完成!")
    print(f"  处理公众号: {len(clubs)}")
    print(f"  获取文章: {total_crawled}")
    print(f"  新文章: {len(all_new_articles)}")
    print(f"  错误: {total_errors}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
