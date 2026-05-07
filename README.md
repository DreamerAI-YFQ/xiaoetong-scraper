# 小鹅通圈子内容抓取器 — 使用指南

从小鹅通「鹅圈子」抓取付费内容，保存为 Obsidian 可用的 Markdown 文件。

---

## 目录

1. [首次配置](#1-首次配置)
2. [抓取圈子帖子](#2-抓取圈子帖子)
3. [发现模式（探索课程 API）](#3-发现模式探索课程-api)
4. [配置文件详解](#4-配置文件详解)
5. [输出说明](#5-输出说明)
6. [参数速查](#6-参数速查)
7. [常见问题](#7-常见问题)

---

## 1. 首次配置

### 1.1 安装依赖

在 WorkBuddy 中运行（一次性操作）：

```bash
# 安装 Python 包
C:\Users\60920\.workbuddy\binaries\python\envs\default\Scripts\pip.exe install playwright pyyaml pycryptodome requests

# 安装 Chromium 浏览器（约 150MB，首次需要下载）
C:\Users\60920\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m playwright install chromium
```

> macOS/Linux 替换 Python 路径为 `~/.workbuddy/binaries/python/envs/default/bin/python`

### 1.2 创建配置文件

在 Obsidian Vault 根目录创建 `xiaoetong.yaml`（和 `sources.yaml` 同级）：

```yaml
circles:
  - name: "我的学习圈"
    community_id: "c_68afda25fc3aa_opARMaig2204"
    app_id: "appttaswqlt5080"
    enabled: true

login:
  cookie_file: ".xiaoetong-cookies.json"
  headless: false
  proxy: "http://127.0.0.1:15556"   # 没有代理就留空 ""

scrape:
  download_images: true
  download_videos: true
  download_audio: true
  include_comments: true
  max_posts: 0
  delay_range: [1.0, 3.0]

output:
  staging_path: "Cubox/Staging/"
  attachments_subdir: "attachments/"
  video_dir: "videos/"

incremental:
  state_file: ".xiaoetong-state.json"
```

### 1.3 获取 community_id 和 app_id

1. 用浏览器打开 https://quanzi.xiaoe-tech.com 并登录
2. 进入你想抓取的圈子
3. 看地址栏 URL，格式是：
   ```
   https://quanzi.xiaoe-tech.com/c_68afda25fc3aa_opARMaig2204/feed_list?app_id=appttaswqlt5080
   ```
4. `c_68afda25fc3aa_opARMaig2204` 就是 `community_id`
5. `appttaswqlt5080` 就是 `app_id`

### 1.4 代理配置

根据你的网络环境选择：

| 情况 | proxy 填什么 |
|------|-------------|
| 直连上网，无需代理 | `""` （留空） |
| 有代理软件（Clash/V2Ray 等） | `"http://127.0.0.1:端口号"` |
| 系统已设 HTTP_PROXY 环境变量 | `""` （自动检测） |

脚本启动时会打印代理状态，方便确认配置是否正确。

---

## 2. 抓取圈子帖子

### 2.1 基本抓取（日常用）

```bash
cd C:\Users\60920\.workbuddy\skills\xiaoetong-scraper\scripts
C:\Users\60920\.workbuddy\binaries\python\envs\default\Scripts\python.exe scraper.py
```

**会发生什么：**
1. 浏览器窗口弹出
2. 首次运行 → 显示微信扫码登录界面 → 你用手机扫码
3. 登录成功后，Cookie 自动保存（下次免登录）
4. 自动进入 xiaoetong.yaml 中启用的第一个圈子
5. 滚动页面加载帖子列表
6. 逐条进入帖子，抓取正文、图片、评论
7. 保存 Markdown 到 `Vault/Cubox/Staging/`
8. 只抓新帖子（增量模式，已抓过的跳过）

**整个过程大约每条帖子 3-5 秒，取决于网络和 delay_range 设置。**

### 2.2 首次测试

不确定能不能跑通？先抓 2 条试试：

```bash
python.exe scraper.py --max-posts 2
```

### 2.3 只抓某个圈子

yaml 里配了多个圈子，但只想抓一个：

```bash
python.exe scraper.py --circle c_68afda25fc3aa_opARMaig2204
```

### 2.4 强制全量重抓

默认增量模式只抓新的。想全部重新抓：

```bash
python.exe scraper.py --full
```

### 2.5 抓取时跳过图片/视频

```bash
# 只要文字内容，不下载图片
python.exe scraper.py --no-image

# 跳过视频（没有 ffmpeg 时自动跳过，也可手动指定）
python.exe scraper.py --no-video

# 都跳过，只抓文字
python.exe scraper.py --no-image --no-video
```

---

## 3. 发现模式（探索课程 API）

发现模式用于探索小鹅通课程页面的 API 接口，帮你了解课程数据的请求结构。

### 3.1 探索课程页面

```bash
python.exe scraper.py --discover --url "https://appl2m4pcpu3553.h5.xiaoeknow.com/p/course/big_column/p_60d9a84fe4b03a0070b531cb"
```

**会发生什么：**
1. 浏览器弹出，扫码登录（先建立登录态）
2. 登录后自动导航到你给的课程 URL
3. 浏览器保持打开，后台持续监听所有网络请求
4. **你在浏览器中手动操作**：点击课程章节、滚动内容等
5. 脚本会拦截并记录所有相关的 API 请求
6. 操作完毕按 **Ctrl+C** 结束
7. 在 Vault 根目录生成 `xiaoetong-api-discovery.txt` 报告

### 3.2 探索圈子页面

不指定 URL，就进入默认圈子：

```bash
python.exe scraper.py --discover
```

---

## 4. 配置文件详解

所有配置在 `xiaoetong.yaml` 中，位于 Obsidian Vault 根目录。

### circles — 圈子列表

```yaml
circles:
  - name: "学习圈A"                    # 显示名称（随意取）
    community_id: "c_xxx_xxx"          # 圈子 ID（从 URL 提取，必填）
    app_id: "appxxxx"                   # 店铺 app_id（必填）
    enabled: true                       # 是否启用

  - name: "学习圈B"                    # 可以配多个圈子
    community_id: "c_yyy_yyy"
    app_id: "appyyyy"
    enabled: false                      # 设为 false 临时禁用
```

### login — 登录设置

```yaml
login:
  cookie_file: ".xiaoetong-cookies.json"  # Cookie 保存位置（Vault 根目录下）
  headless: false                          # true=无头模式（不显示浏览器窗口）
  proxy: "http://127.0.0.1:15556"         # 代理地址，留空自动检测环境变量
```

- `headless`：首次登录必须 `false`（需要扫码），后续如果 Cookie 有效可以设 `true`
- `proxy`：见 [1.4 代理配置](#14-代理配置)

### scrape — 抓取设置

```yaml
scrape:
  download_images: true       # 下载图片到 attachments/
  download_videos: true       # 下载视频（需 ffmpeg + 播放权限）
  download_audio: true        # 下载音频
  include_comments: true      # 抓取评论
  include_likes: true         # 抓取点赞
  max_posts: 0                # 每圈最多抓多少条（0=全部）
  delay_range: [1.0, 3.0]    # 每步操作间随机延迟秒数（防反爬）
```

### output — 输出设置

```yaml
output:
  staging_path: "Cubox/Staging/"    # Markdown 输出目录（相对 Vault）
  attachments_subdir: "attachments/" # 图片/音频附件子目录
  video_dir: "videos/"              # 视频文件子目录
```

### incremental — 增量设置

```yaml
incremental:
  state_file: ".xiaoetong-state.json"  # 已抓帖子记录（Vault 根目录下）
  track_by: "feeds_id"                 # 追踪字段
```

---

## 5. 输出说明

### 文件结构

```
Obsidian Vault/
├── xiaoetong.yaml                    # 配置文件
├── .xiaoetong-cookies.json           # Cookie（自动生成）
├── .xiaoetong-state.json             # 增量状态（自动生成）
├── .xiaoetong-debug/                 # 调试数据（自动生成）
└── Cubox/
    └── Staging/
        ├── xiaoetong-学习圈A-f_12345.md    # 帖子 Markdown
        ├── xiaoetong-学习圈A-f_12346.md
        └── attachments/
            ├── xiaoetong-f_12345-img-001.jpg  # 帖子图片
            └── xiaoetong-f_12345-img-002.jpg
```

### Markdown 格式

每个帖子一个 `.md` 文件，frontmatter 与 Source Normalizer 统一：

```yaml
---
title: "帖子标题"
created: "2026-05-07 10:30:00"
origin: xiaoetong
source_path: "xiaoetong-学习圈A-f_12345.md"
tags: [xiaoetong, 学习圈A]
url: "https://quanzi.xiaoe-tech.com/..."
author: "作者名"
---

正文内容...

![图片](attachments/xiaoetong-f_12345-img-001.jpg)

更多正文...
```

### 增量机制

- 首次运行：抓取圈子里所有帖子
- 后续运行：只抓 `.xiaoetong-state.json` 中没有的新帖子
- `--full` 参数：忽略增量状态，全部重新抓取
- `--max-posts N`：限制每圈最多 N 条（测试用）

---

## 6. 参数速查

| 参数 | 说明 | 示例 |
|------|------|------|
| （无参数） | 增量抓取所有启用圈子 | `scraper.py` |
| `--max-posts N` | 每圈最多 N 条 | `--max-posts 3` |
| `--circle ID` | 只抓指定圈子 | `--circle c_xxx_xxx` |
| `--full` | 强制全量重抓 | `--full` |
| `--no-image` | 跳过图片下载 | `--no-image` |
| `--no-video` | 跳过视频下载 | `--no-video` |
| `--headless` | 无头模式（不显示浏览器） | `--headless` |
| `--config PATH` | 指定配置文件路径 | `--config /path/to/xiaoetong.yaml` |
| `--discover` | 发现模式（拦截 API） | `--discover` |
| `--discover --url URL` | 发现模式 + 导航到指定 URL | `--discover --url "https://..."` |

---

## 7. 常见问题

### 首次运行没有弹出扫码登录界面？

检查：
1. Chromium 是否安装成功：`python -m playwright install chromium`
2. 代理是否正确：启动时看打印的代理状态
3. xiaoetong.yaml 中 `headless` 是否为 `false`

### 扫码登录后页面空白/超时？

代理问题。检查 `xiaoetong.yaml` 中 `login.proxy` 是否正确：
- 有代理：填入 `"http://127.0.0.1:端口号"`
- 没代理：留空 `""`

### 图片抓不到？

脚本有 4 层图片提取 + DOM 兜底 + 懒加载重试，正常情况下图文帖子的图片都能抓到。如果仍然缺失：
1. 检查 `scrape.download_images` 是否为 `true`
2. 检查网络连通性（图片 CDN 可能需要代理）
3. 查看 `.xiaoetong-debug/` 下的原始 API 数据确认图片字段

### 视频下载不了？

视频下载需要同时满足：
1. 安装了 ffmpeg
2. 你有该视频的播放权限
3. 脚本能获取到 M3U8 播放地址

部分付费课程视频可能因权限限制无法获取播放地址，此时脚本会提示「有视频但未获取到 M3U8 地址」。

### Cookie 过期了？

删除 Vault 根目录下的 `.xiaoetong-cookies.json`，重新运行脚本，会再次弹出扫码登录。

### Windows 终端中文乱码？

脚本已内置 UTF-8 处理。如果仍有问题：
```bash
set PYTHONIOENCODING=utf-8
chcp 65001
```

### 想在另一台电脑上使用？

参见 `MIGRATION.md`（迁移提示词），复制粘贴给新电脑的 Agent 即可。
