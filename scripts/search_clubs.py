"""
搜索西南财经大学社团公众号并输出结果
用法: WECHAT_COOKIE="xxx" python scripts/search_clubs.py
"""
import json, re, os, sys, requests

cookie = os.environ.get("WECHAT_COOKIE", "")
if not cookie:
    print("[!] 请设置 WECHAT_COOKIE 环境变量")
    sys.exit(1)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://mp.weixin.qq.com/",
})
for kv in cookie.split("; "):
    name, _, val = kv.partition("=")
    if name and val:
        s.cookies.set(name.strip(), val.strip(), domain=".qq.com", path="/")

r = s.get("https://mp.weixin.qq.com/", timeout=15)
tokens = re.findall(r'token["\']?\s*[:=]\s*["\']?(\d+)["\']?', r.text)
token = tokens[0] if tokens else ""

keywords = ["西南财经大学", "西财", "SWUFE", "社团", "西财社团"]

seen = {}
for kw in keywords:
    print(f"\n=== 搜索: {kw} ===")
    params = {
        "action": "search_biz",
        "begin": 0, "count": 20, "query": kw,
        "token": token, "lang": "zh_CN", "f": "json", "ajax": "1",
    }
    r2 = s.get("https://mp.weixin.qq.com/cgi-bin/searchbiz", params=params, timeout=10)
    try:
        data = r2.json()
        for item in data.get("list", []):
            fid = item.get("fakeid", "")
            nickname = item.get("nickname", "")
            if fid not in seen:
                seen[fid] = item
                print(f"  [{fid}] {nickname}")
                print(f"    微信号: {item.get('alias','')}")
                print(f"    简介: {item.get('signature','')[:60]}")
                print(f"    验证: {item.get('verify_status','')}")
    except Exception as e:
        print(f"  解析失败: {e}")

# 输出可添加到 clubs.json 的格式
print(f"\n\n=== 共发现 {len(seen)} 个公众号 ===")
print(json.dumps([{"fakeid": v["fakeid"], "nickname": v["nickname"], "alias": v.get("alias",""), "signature": v.get("signature","")[:60]} for v in seen.values()], ensure_ascii=False, indent=2))
