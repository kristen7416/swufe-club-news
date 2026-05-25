"""
Vercel Serverless Function: 活动发布 + 公众号身份验证

POST /api/submit-activity  — 提交活动
GET  /api/submit-activity   — 诊断
"""

import json, os, re, base64, uuid, sys, traceback
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "kristen7416/swufe-club-news"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATUS_TITLE_HINTS = {
    "ended": ["圆满结束", "圆满落幕", "圆满", "精彩回顾", "活动总结",
              "回顾", "落幕", "收官", "成功举办", "顺利举办",
              "顺利举行", "顺利结束", "顺利闭幕", "圆满完成"],
    "upcoming": ["预告", "倒计时", "即将", "敬请期待", "抢鲜", "预热", "剧透", "通知", "报名"],
}

# ---- helpers ----

def _respond(h, code, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    h.wfile.write(body)

def _read_body(h):
    length = int(h.headers.get("Content-Length", 0))
    return h.rfile.read(length).decode("utf-8")


# ---- 公众号名称提取 ----

def extract_wechat_name(article_url):
    try:
        import requests
        resp = requests.get(article_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except requests.Timeout:
        return None, "文章页面请求超时"
    except requests.HTTPError as e:
        return None, f"文章页面返回错误 (HTTP {e.response.status_code})"
    except Exception as e:
        cls = type(e).__name__
        return None, f"无法访问文章页面 [{cls}]: {str(e)[:80]}"

    patterns = [
        r'var nickname\s*=\s*htmlDecode\(["\']([^"\']+)["\']\)',
        r'var nickname\s*=\s*["\']([^"\']+)["\']',
        r'var nick_name\s*=\s*["\']([^"\']+)["\']',
        r'profile_nickname\s*=\s*["\']([^"\']+)["\']',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            return m.group(1).strip(), None

    # debug: show lines containing nickname
    debug_lines = [l.strip()[:150] for l in html.split("\n") if "nickname" in l.lower()][:5]
    return None, f"未找到公众号名称 (匹配行: {' | '.join(debug_lines)})"


def match_wechat_name(extracted, expected):
    if not extracted or not expected:
        return False
    extracted, expected = extracted.strip(), expected.strip()
    if extracted == expected:
        return True
    prefixes = ["西财", "SWUFE", "西南财大", "西南财经大学"]
    for p in prefixes:
        if expected.startswith(p):
            suffix = expected[len(p):]
            if suffix and suffix in extracted:
                return True
        if extracted.startswith(p):
            suffix = extracted[len(p):]
            if suffix and suffix in expected:
                return True
    if len(extracted) >= 2 and len(expected) >= 2:
        if extracted in expected or expected in extracted:
            return True
    return False


# ---- GitHub API ----

def gh_get(path):
    import requests
    url = f"{GITHUB_API}/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    raw = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(raw), data["sha"]


def gh_put(path, content, sha, message):
    import requests
    url = f"{GITHUB_API}/{path}"
    encoded = base64.b64encode(
        json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")
    body = {"message": message, "content": encoded}
    if sha:
        body["sha"] = sha
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.put(url, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---- 状态计算 ----

def compute_status(act):
    now = datetime.now(BEIJING_TZ)
    start, end = act.get("start_time"), act.get("end_time")
    try:
        sd = datetime.fromisoformat(start) if start else None
    except Exception:
        sd = None
    try:
        ed = datetime.fromisoformat(end) if end else None
    except Exception:
        ed = None
    if sd and sd.tzinfo is None:
        sd = sd.replace(tzinfo=BEIJING_TZ)
    if ed and ed.tzinfo is None:
        ed = ed.replace(tzinfo=BEIJING_TZ)
    if ed and ed < now:
        return "ended"
    if sd and sd <= now:
        if not ed or ed > now:
            return "ended" if ed is None and (now - sd).days > 7 else "ongoing"
        return "ended"
    if sd and sd > now:
        return "upcoming"
    for status, keywords in STATUS_TITLE_HINTS.items():
        for kw in keywords:
            if kw in act.get("title", ""):
                return status
    return "upcoming"


# ---- 合并 ----

def merge_activities(existing, manual):
    merged = {}
    for a in existing:
        k = a.get("article_url", "") or a.get("id", "")
        if k:
            merged[k] = dict(a)
    for a in manual:
        k = a.get("article_url", "") or a.get("id", "")
        if not k:
            continue
        a["source"] = "manual"
        a["status"] = compute_status(a)
        merged[k] = a
    result = list(merged.values())
    result.sort(key=lambda x: (
        {"ongoing": 0, "upcoming": 1, "ended": 2}.get(x.get("status", ""), 99),
        x.get("start_time") or "",
    ))
    return result


# ---- 社团 ----

def load_clubs():
    candidates = [
        os.path.join(PROJECT_ROOT, "site", "data", "clubs.json"),
        os.path.join(os.getcwd(), "site", "data", "clubs.json"),
        os.path.join(os.path.dirname(PROJECT_ROOT), "site", "data", "clubs.json"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("clubs", [])
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    # fallback: GitHub API
    try:
        data, _ = gh_get("site/data/clubs.json")
        if data:
            return data.get("clubs", [])
    except Exception:
        pass
    return []


# ---- Vercel Handler ----

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """诊断端点"""
        info = {
            "status": "alive",
            "python": sys.version,
            "cwd": os.getcwd(),
            "project_root": PROJECT_ROOT,
            "token_set": bool(GITHUB_TOKEN),
            "token_prefix": GITHUB_TOKEN[:10] + "..." if GITHUB_TOKEN else "",
        }
        # check requests
        try:
            import requests
            info["requests"] = requests.__version__
        except ImportError:
            info["requests"] = "NOT INSTALLED"
        # check clubs
        clubs = load_clubs()
        info["clubs_loaded"] = len(clubs)
        info["clubs_with_wechat"] = len([c for c in clubs if c.get("wechat_name")])
        _respond(self, 200, info)

    def do_POST(self):
        try:
            self._handle_post()
        except Exception as e:
            cls = type(e).__name__
            tb = traceback.format_exc()
            _respond(self, 500, {
                "success": False,
                "message": f"服务器内部错误 [{cls}]: {str(e)[:200]}",
            })
            # print to Vercel logs
            print(f"[ERROR] {cls}: {e}\n{tb}", file=sys.stderr)

    def _handle_post(self):
        # ---- parse body ----
        try:
            body = json.loads(_read_body(self))
        except Exception:
            _respond(self, 400, {"success": False, "message": "请求格式错误"})
            return

        # ---- validate ----
        club_id = (body.get("club_id") or "").strip()
        article_url = (body.get("article_url") or "").strip()
        title = (body.get("title") or "").strip()
        start_time = (body.get("start_time") or "").strip()

        if not club_id or not article_url or not title or not start_time:
            _respond(self, 400, {"success": False, "message": "请填写必填字段"})
            return
        if "mp.weixin.qq.com" not in article_url:
            _respond(self, 400, {"success": False, "message": "请填写有效的公众号文章链接"})
            return
        if len(title) > 100:
            _respond(self, 400, {"success": False, "message": "标题过长（最多100字）"})
            return

        # ---- club ----
        clubs = load_clubs()
        club = next((c for c in clubs if c["id"] == club_id), None)
        if not club:
            _respond(self, 400, {"success": False, "message": "无效的社团"})
            return
        expected_name = club.get("wechat_name", "")
        if not expected_name:
            _respond(self, 400, {"success": False, "message": f'社团 "{club["name"]}" 暂未配置公众号'})
            return

        # ---- verify wechat ----
        extracted_name, err = extract_wechat_name(article_url)
        if err:
            _respond(self, 400, {"success": False, "message": f"公众号验证失败: {err}"})
            return
        if not match_wechat_name(extracted_name, expected_name):
            _respond(self, 400, {"success": False, "message":
                f'公众号不匹配：文章来自"{extracted_name}"，社团"{club["name"]}"的公众号为"{expected_name}"'})
            return

        # ---- build activity ----
        now_dt = datetime.now(BEIJING_TZ)
        now_iso = now_dt.isoformat()
        activity_id = f"manual_{now_dt.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        new_act = {
            "id": activity_id,
            "club_id": club_id,
            "title": title,
            "description": (body.get("description") or "").strip(),
            "category": club.get("category", "其他"),
            "location": (body.get("location") or "").strip(),
            "start_time": start_time,
            "end_time": (body.get("end_time") or "").strip() or "",
            "article_url": article_url,
            "cover_url": "",
            "publish_time": now_iso,
            "contact": (body.get("contact") or "").strip(),
            "source": "manual",
            "status": "upcoming",
            "created_at": now_iso,
        }

        # ---- read GitHub ----
        try:
            manual_data, manual_sha = gh_get("site/data/manual_activities.json")
            if manual_data is None:
                manual_data = {"activities": []}
            act_data, act_sha = gh_get("site/data/activities.json")
            if act_data is None:
                act_data = {"activities": []}
        except Exception as e:
            _respond(self, 500, {"success": False, "message": f"读取数据失败: {e}"})
            return

        # ---- duplicate check ----
        existing_urls = [a.get("article_url", "") for a in manual_data.get("activities", [])]
        if article_url in existing_urls:
            _respond(self, 400, {"success": False, "message": "该文章链接已提交过"})
            return

        # ---- append & merge ----
        manual_data["activities"].append(new_act)
        merged = merge_activities(act_data.get("activities", []), manual_data["activities"])
        sc = {"upcoming": 0, "ongoing": 0, "ended": 0}
        for a in merged:
            s = a.get("status", "upcoming")
            sc[s] = sc.get(s, 0) + 1

        merged_output = {
            "activities": merged,
            "last_updated": now_iso,
            "total_count": len(merged),
            "status_counts": sc,
        }

        # ---- write ----
        msg = f'feat(manual): 新增活动 "{title}" by {club["name"]}'
        try:
            gh_put("site/data/manual_activities.json", manual_data, manual_sha, msg)
            # re-fetch sha
            _, new_sha = gh_get("site/data/activities.json")
            gh_put("site/data/activities.json", merged_output, new_sha or act_sha, msg)
        except Exception as e:
            _respond(self, 500, {"success": False, "message": f"写入数据失败: {e}"})
            return

        _respond(self, 200, {
            "success": True,
            "message": "发布成功！活动将在 30-60 秒后上线",
            "activity_id": activity_id,
        })

    # ---- CORS preflight ----
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
