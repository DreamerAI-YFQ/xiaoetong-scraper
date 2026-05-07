---
name: xiaoetong-scraper
description: "小鹅通鹅圈子内容抓取工具。从付费圈子抓取图文帖子、视频、音频、评论等全部内容，输出为 Staging 格式 Markdown。当用户提到小鹅通抓取、圈子内容下载、鹅圈子导出、小鹅通备份等场景时触发。"
version: 1.2.0
agent_created: true
---

# 小鹅通圈子内容抓取

从小鹅通「鹅圈子」PC 网页版抓取付费圈子内容，输出 Staging 格式 Markdown，接入 Obsidian 知识管理管道。

## 架构概览

```
小鹅通网页 → Playwright 浏览器自动化 → API 拦截 + DOM 兜底
                                         ↓
                              content_parser (解析)
                                         ↓
                              output.py (Staging Markdown + 图片/音视频下载)
                                         ↓
                              Obsidian Vault / Cubox / Staging /
```

**脚本结构**（`scripts/` 目录下）：

| 文件 | 职责 |
|------|------|
| `scraper.py` | 主入口：参数解析、流程编排、登录、DOM 图片兜底 |
| `browser.py` | Playwright 浏览器管理：启动、登录（微信扫码）、Cookie 持久化、页面操作 |
| `api_interceptor.py` | 网络请求拦截：捕获圈子/课程相关 API 响应，支持发现模式 |
| `content_parser.py` | 内容解析：4 层图片提取、HTML→Markdown、评论解析 |
| `output.py` | 输出管理：Staging 格式 Markdown、图片/音频下载、增量状态 |
| `video_downloader.py` | 视频下载：M3U8 双层解密 + TS 下载 + ffmpeg 合并（需 ffmpeg） |

## 运行方式

### 前置条件

- **Python 3.10+**（WorkBuddy 管理环境或系统 Python 均可）
- **依赖包**：`playwright pyyaml pycryptodome requests`
- **Playwright Chromium**：`playwright install chromium`
- **ffmpeg**（可选）：视频下载需要，无则自动跳过视频
- **网络**：需能访问小鹅通域名；支持三种代理模式（见下方配置说明）

### 基本用法

```bash
cd <skill_dir>/scripts && <python> scraper.py
```

首次运行弹出浏览器 → 微信扫码登录 → Cookie 自动保存 → 后续运行免登录。

配置文件 `xiaoetong.yaml` 自动查找（当前目录向上递归 + `~/Documents/Obsidian Vault`），也可用 `--config <path>` 指定。

### 常用参数

| 参数 | 说明 |
|------|------|
| （无参数） | 增量抓取所有启用的圈子 |
| `--full` | 强制全量抓取（忽略增量状态） |
| `--max-posts N` | 每圈最多 N 条（测试用） |
| `--circle ID` | 只抓指定圈子 |
| `--no-video` | 跳过视频下载 |
| `--no-image` | 跳过图片下载 |
| `--headless` | 无头模式（首次登录不建议） |
| `--config PATH` | 指定 xiaoetong.yaml 路径 |
| `--discover` | 发现模式：拦截 API 端点并记录 |
| `--discover --url URL` | 发现模式：先登录，再导航到指定 URL（如课程页面）拦截 API |

### 典型场景

**1. 日常增量抓取圈子帖子：**
```bash
<python> scraper.py
```

**2. 首次测试（只抓 3 条）：**
```bash
<python> scraper.py --max-posts 3
```

**3. 发现课程页面的 API 端点：**
```bash
<python> scraper.py --discover --url "https://appl2m4pcpu3553.h5.xiaoeknow.com/p/course/big_column/p_xxx"
```
先弹出扫码登录 → 登录后自动导航到课程页面 → 浏览器保持打开 → 用户手动操作浏览内容 → Ctrl+C 结束 → 生成 API 发现报告

**4. 强制全量重新抓取：**
```bash
<python> scraper.py --full
```

## 配置文件

在 Obsidian Vault 根目录创建 `xiaoetong.yaml`（与 `sources.yaml` 同级）：

```yaml
circles:
  - name: "圈子名称"
    community_id: "c_xxx_xxx"       # 从圈子 URL 提取
    app_id: "appxxxx"               # 小鹅通店铺 app_id
    enabled: true

output:
  staging_path: "Cubox/Staging/"    # 相对 Vault 根目录
  attachments_subdir: "attachments/"
  video_dir: "videos/"

login:
  cookie_file: ".xiaoetong-cookies.json"
  headless: false
  proxy: ""                         # 代理地址，如 http://127.0.0.1:15556
                                    # 留空 = 自动检测环境变量（HTTP_PROXY/HTTPS_PROXY）
                                    # 无环境变量 = 直连

scrape:
  download_images: true
  download_videos: true
  download_audio: true
  include_comments: true
  max_posts: 0                      # 0=全部
  delay_range: [1.0, 3.0]

incremental:
  state_file: ".xiaoetong-state.json"
```

### 获取 community_id 和 app_id

1. 登录小鹅通圈子 PC 端（`quanzi.xiaoe-tech.com`）
2. 进入圈子，URL 格式：`https://quanzi.xiaoe-tech.com/c_xxx_xxx/feed_list?app_id=appxxxx`
3. 其中 `c_xxx_xxx` 即 `community_id`，`appxxxx` 即 `app_id`

## 输出格式

Staging 格式 Markdown（与 Source Normalizer 统一 schema）：

```yaml
---
title: "帖子标题"
created: "2026-05-07 10:30:00"
origin: xiaoetong
source_path: "xiaoetong-圈子名-feeds_id.md"
tags: [xiaoetong, 圈子名]
url: "https://quanzi.xiaoe-tech.com/..."
author: "作者名"
---
```

图片下载到 `Staging/attachments/`，正文内联引用改为本地路径。

## 代理配置

脚本启动时会打印当前代理状态（`使用配置代理` / `检测到环境代理` / `无代理配置（直连模式）`）。

三种模式，优先级从高到低：

| 优先级 | 方式 | 适用场景 |
|--------|------|----------|
| 1 | `xiaoetong.yaml` 中 `login.proxy` | 代理固定、不想依赖环境变量 |
| 2 | 环境变量 `HTTPS_PROXY` / `HTTP_PROXY` | 代理随系统切换、多工具共用 |
| 3 | 直连（无代理） | 公司/家庭网络无需代理 |

**换电脑时注意**：新电脑的网络环境可能不同，请根据实际情况设置 `proxy` 字段或环境变量。

## 已知限制

- **登录**：需手动微信扫码，脚本不自动填入凭证
- **视频**：小鹅通视频为双层加密 M3U8，需 ffmpeg 解密合并；部分课程视频可能因权限不足无法获取播放地址
- **编码**：脚本已处理 Windows GBK 终端编码问题（UTF-8 stdout/stderr 重包装）

## 注意

- 输出 `origin=xiaoetong`，与 Source Normalizer 统一 schema 对齐
- 仅供个人学习归档，请尊重创作者版权
