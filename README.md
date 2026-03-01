<div align="center">

# 🤖 AI News V1-Lite

**智能 AI 新闻聚合工具 | 每日精选 AI 与编程资讯**

[![Python](https://img.shields.io/badge/Python-3.13%2B-blue?style=flat-square&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Code style](https://img.shields.io/badge/code%20style-black-black?style=flat-square)]()

</div>

---

## ✨ 功能特性

- **📡 多源数据采集** — 支持 RSS、GitHub Trending、Hacker News 等多种数据源
- **🎯 智能内容评分** — 基于关键词匹配、热度指标、时效性的综合评分算法
- **🔄 自动去重机制** — URL、标题、内容哈希三重去重保障
- **🏷️ 智能标签分类** — 自动识别核心工具、机制、工程等关键词标签
- **📊 结构化输出** — 生成 JSON 原始数据与 Markdown 可读报告
- **⚙️ 灵活配置** — JSON 配置文件管理数据源，支持自定义关键词与权重

---

## 🚀 快速开始

### 环境要求

- Python 3.13 或更高版本

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/ai-news-lite.git
cd ai-news-lite

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 基本用法

```bash
# 运行昨日数据抓取（默认）
python -m ai_news run

# 抓取今日数据
python -m ai_news run --relative today

# 指定日期抓取
python -m ai_news run --date 2026-03-01

# 干运行模式（仅预览，不保存）
python -m ai_news run --dry-run

# 自定义输出目录和数量
python -m ai_news run --out ./output --top-n 20
```

---

## 📁 项目结构

```
ai-news-lite/
├── ai_news/                 # 核心代码包
│   ├── __init__.py
│   ├── main.py             # CLI 入口
│   ├── pipeline.py         # 数据处理管道
│   ├── fetchers.py         # 数据抓取器
│   └── source_config.py    # 源配置管理
├── config/
│   └── sources.json        # 数据源配置文件
├── docs/
│   ├── input/              # 输入文档
│   └── output/             # 输出报告 (YYYY-MM-DD/)
│       ├── raw.json        # 原始数据
│       └── top.md          # Top N 精选
├── requirements.txt
├── LICENSE
└── README.md
```

---

## 🔧 配置说明

编辑 `config/sources.json` 自定义数据源：

```json
{
  "global": {
    "request_timeout": 20
  },
  "sources": [
    {
      "id": "smol_rss",
      "type": "rss",
      "enabled": true,
      "params": {
        "urls": ["https://news.smol.ai/rss.xml"]
      }
    },
    {
      "id": "github_trending_main",
      "type": "github_trending",
      "enabled": true,
      "params": {
        "languages": ["python", "cpp", "jupyter-notebook"],
        "since": "daily"
      }
    },
    {
      "id": "hn_ai",
      "type": "hackernews",
      "enabled": true,
      "params": {
        "feeds": ["top", "best", "new"],
        "keywords": ["ai", "llm", "gpt", "agent"]
      }
    }
  ]
}
```

### 支持的源类型

| 类型 | 说明 | 参数 |
|------|------|------|
| `rss` | RSS 订阅源 | `urls`: 订阅地址列表 |
| `github_trending` | GitHub 趋势 | `languages`: 语言列表, `since`: daily/weekly/monthly |
| `hackernews` | Hacker News | `feeds`: 榜单类型, `keywords`: 过滤关键词 |

---

## 📊 评分算法

综合评分 = 源权重 + 关键词得分 + 热度得分 + 时效性得分

| 维度 | 权重范围 | 说明 |
|------|---------|------|
| **源权重** | 10-34 | RSS(34) > GitHub(28) > HN(24) |
| **关键词** | 0-25 | 核心/工具/机制/工程/中文 五组关键词 |
| **热度** | 0-20 | Stars、HN Score、Comments 等指标 |
| **时效性** | 1-15 | 24h内(15) > 48h(12) > 72h(10) > 一周(6) > 一月(3) |

---

## 📝 输出示例

生成的 `top.md` 报告示例：

```markdown
# AI 资讯 Top 10 - 2026-03-01

- 抓取总数: 156
- 去重后数量: 142
- 阈值以上数量: 28
- 分数阈值: 45.0

## 1. Claude Code 发布重大更新
- 来源: RSS
- 分数: 87.5
- 发布时间: 2026-03-01T08:30:00Z
- 标签: claude code, ai coding, code assistant
- 链接: https://example.com/article
- 摘要: Anthropic 发布了 Claude Code 的最新版本...
```

---

## 🛠️ 开发计划

- [x] 核心数据采集管道
- [x] 多源数据聚合 (RSS/GitHub/HN)
- [x] 智能评分与去重
- [x] 结构化输出 (JSON/Markdown)
- [ ] Web 界面展示
- [ ] 定时任务调度
- [ ] 邮件/推送通知
- [ ] 更多数据源支持 (Twitter/Reddit)

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

<div align="center">

**Made with ❤️ by Owen**

[🌟 Star 本项目](https://github.com/yourusername/ai-news-lite) | [🐛 提交 Issue](https://github.com/yourusername/ai-news-lite/issues)

</div>
