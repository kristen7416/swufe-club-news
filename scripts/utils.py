"""
爬虫工具函数：User-Agent 轮换、时间解析、请求重试等
"""

import time
import random
import requests
from typing import Optional

# 移动端 User-Agent 池
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.6367.83 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Samsung S23) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148",
]


def random_ua() -> str:
    """随机返回一个移动端 User-Agent"""
    return random.choice(MOBILE_USER_AGENTS)


def default_headers(cookie: str = "") -> dict:
    """构造默认请求头"""
    headers = {
        "User-Agent": random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://mp.weixin.qq.com/",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def request_with_retry(
    url: str,
    session: Optional[requests.Session] = None,
    cookie: str = "",
    max_retries: int = 3,
    timeout: int = 15,
    delay: int = 60,
) -> Optional[requests.Response]:
    """
    带重试机制的 HTTP GET 请求

    Args:
        url: 请求地址
        session: requests Session (可选)
        cookie: Cookie 字符串
        max_retries: 最大重试次数
        timeout: 超时时间 (秒)
        delay: 失败后等待时间 (秒)

    Returns:
        Response 对象，失败返回 None
    """
    if session is None:
        session = requests.Session()

    for attempt in range(max_retries):
        try:
            session.headers.update(default_headers(cookie))
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()

            # 检测验证码拦截
            if "请输入验证码" in resp.text or len(resp.text) < 500:
                print(f"  [!] 触发验证码或返回内容过短 (长度: {len(resp.text)})")
                if attempt < max_retries - 1:
                    print(f"     等待 {delay}s 后重试...")
                    time.sleep(delay)
                    continue
                return None

            return resp

        except requests.exceptions.Timeout:
            print(f"  [!] 请求超时 ({timeout}s)")
        except requests.exceptions.HTTPError as e:
            print(f"  [!] HTTP 错误: {e}")
        except requests.exceptions.ConnectionError as e:
            print(f"  [!] 连接错误: {e}")
        except Exception as e:
            print(f"  [!] 未知错误: {e}")

        if attempt < max_retries - 1:
            print(f"     等待 {delay}s 后重试 ({attempt + 1}/{max_retries})...")
            time.sleep(delay)
        else:
            print(f"     [x] 已达最大重试次数，跳过")

    return None


def parse_timestamp(ts_str: str) -> str:
    """
    解析微信 HTML 中的时间戳

    微信文章列表中的时间格式可能是:
    - Unix 时间戳 (如 "1716388800")
    - 日期字符串 (如 "2025-05-22")
    """
    ts_str = ts_str.strip()
    if not ts_str:
        return ""

    # 尝试解析为 Unix 时间戳 (秒)
    try:
        ts = int(ts_str)
        if ts > 1000000000:  # 合理的时间戳范围
            from datetime import datetime
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except ValueError:
        pass

    # 直接返回原字符串 (可能是 "刚刚", "昨天" 等)
    return ts_str


def extract_article_id(url_or_path: str) -> str:
    """从 URL 或路径中提取文章 ID"""
    import re
    # /s/ABCDEFG12345
    match = re.search(r"/s/([A-Za-z0-9_-]+)", url_or_path)
    if match:
        return match.group(1)

    # 直接返回
    return url_or_path.strip().split("/")[-1].split("?")[0]


def load_json(path: str, default=None):
    """加载 JSON 文件，失败返回默认值"""
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[utils] 读取文件失败 {path}: {e}")
        return default if default is not None else {}


def save_json(path: str, data):
    """保存 JSON 文件"""
    import json
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[utils] 已保存: {path}")
