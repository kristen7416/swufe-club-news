"""
从 Google Sheets 同步人工提交的活动数据 (可选)

如果配置了 Google Form 作为补充提交通道，此脚本从 Sheet 拉取数据。
需先安装: pip install gspread oauth2client

用法:
    python sync_from_sheets.py
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import load_json, save_json

CONFIG = {
    "output_path": "site/data/manual_activities.json",
    # Google Sheets 配置 (可选)
    # "sheet_id": "YOUR_SHEET_ID",
    # "credentials_file": "path/to/credentials.json",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path):
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


def fetch_from_google_sheets() -> list:
    """
    从 Google Sheets 拉取数据

    需要:
    1. 在 Google Cloud Console 开启 Google Sheets API
    2. 下载服务账号凭据 JSON
    3. 将凭据与 Sheet 共享

    返回活动列表
    """
    sheet_id = CONFIG.get("sheet_id")
    if not sheet_id:
        print("[sync_from_sheets] 未配置 sheet_id，跳过")
        return []

    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
    except ImportError:
        print("[sync_from_sheets] 请安装依赖: pip install gspread oauth2client")
        return []

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CONFIG.get("credentials_file", "credentials.json"), scope
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(sheet_id).sheet1
    records = sheet.get_all_records()

    activities = []
    for row in records:
        activity = {
            "id": f"manual_{datetime.now().timestamp():.0f}_{len(activities)}",
            "club_id": row.get("社团ID", ""),
            "title": row.get("活动标题", ""),
            "description": row.get("活动描述", ""),
            "category": row.get("活动类别", "其他"),
            "location": row.get("地点", ""),
            "start_time": row.get("开始时间", ""),
            "end_time": row.get("结束时间", ""),
            "article_url": row.get("公众号文章链接", ""),
            "cover_url": row.get("海报图片链接", ""),
            "contact": row.get("联系方式", ""),
            "source": "manual",
            "created_at": datetime.now().isoformat(),
        }
        if activity["title"]:
            activities.append(activity)

    return activities


def main():
    print(f"[sync_from_sheets] 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    activities = fetch_from_google_sheets()

    if not activities:
        # 生成空文件，避免下游脚本报错
        save_json(resolve(CONFIG["output_path"]), {"activities": []})
        print("[sync_from_sheets] 无数据")
        return

    output = {"activities": activities}
    save_json(resolve(CONFIG["output_path"]), output)
    print(f"[sync_from_sheets] 完成: {len(activities)} 条人工提交活动")


if __name__ == "__main__":
    main()
