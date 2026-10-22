# SWUFE 社团活动

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

西南财经大学社团活动资讯聚合平台。

自动爬取各社团微信公众号的活动信息，提供统一的浏览/搜索/筛选界面。

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

1. Fork 或 clone 本仓库（**仅限非商业用途**，详见下方「License / 许可」）
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

## License / 许可

本项目采用 **CC BY-NC 4.0**（Creative Commons Attribution-NonCommercial 4.0 International，
知识共享“署名—非商业性使用”4.0 国际）许可协议，**禁止商业使用**。

| | 说明 |
|---|---|
| ✅ 允许 | 非商业目的下的复制、分发、修改与再创作（须署名作者、附许可链接并注明是否修改） |
| ❌ 禁止 | 任何以商业获利为目的的使用，如售卖、付费课程/训练营、商业产品集成、广告或导流变现、商业外包交付 |
| 🏢 商用授权 | 需事先取得书面许可，请联系 [@kristen7416](https://github.com/kristen7416) |

- 协议全文（英文法律文本，具有约束力）：[LICENSE](LICENSE)
- 官方中文摘要（仅供参考，以英文原文为准）：[creativecommons.org/licenses/by-nc/4.0/deed.zh-hans](https://creativecommons.org/licenses/by-nc/4.0/deed.zh-hans)

### 第三方内容说明

- `site/js/qrcode.min.js`、`site/js/html2canvas.min.js` 等第三方库遵循其各自原始许可（MIT），
  不在本项目许可范围内。
- 各社团微信公众号文章的文字、图片及其他内容，版权归原公众号及原作者所有；本项目仅作
  链接与信息聚合，不对上述内容主张任何权利。
