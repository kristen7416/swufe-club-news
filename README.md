# SWUFE 社团活动

西南财经大学社团活动资讯聚合平台。

自动爬取各社团微信公众号的活动信息，提供统一的浏览/搜索/筛选界面。

## 地址
https://kristen7416.github.io/swufe-club-news/

## 功能

- 📰 自动爬取 200+ 社团公众号的最新活动
- 🔍 按分类、状态、关键词筛选活动
- 📱 响应式设计，手机/桌面均可用
- 🆓 全免费架构 (GitHub Pages + GitHub Actions)

## 项目结构

```
├── .github/workflows/
│   └── crawl-and-deploy.yml   # 爬虫 + 部署流水线
├── scripts/
│   ├── crawl_wechat.py         # 公众号爬虫
│   ├── extract_activity.py     # 活动信息提取
│   ├── merge_data.py           # 数据合并
│   └── sync_from_sheets.py     # Google Sheets 同步 (可选)
├── site/
│   ├── index.html              # 首页
│   ├── css/style.css           # 样式
│   ├── js/app.js               # 前端逻辑
│   └── data/
│       ├── activities.json     # 活动数据 (自动生成)
│       └── clubs.json          # 社团清单 (手动维护)
└── README.md
```

## 部署

1. Fork 或 clone 本仓库
2. 在 `site/data/clubs.json` 中填写社团信息和 `__biz`
3. 在 GitHub 仓库 Settings → Pages 中开启 GitHub Pages（Source: GitHub Actions）
4. （可选）在仓库 Settings → Secrets 中添加 `WECHAT_COOKIE` 提高爬虫成功率

## 添加社团

在 `clubs.json` 中添加：
```json
{
  "id": "club_xxx",
  "name": "社团名称",
  "biz": "公众号__biz参数",
  "category": "学术科技",
  "is_active": true
}
```

## 数据来源

各社团微信公众号公开文章。

## License

MIT
