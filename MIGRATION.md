# 小鹅通 Scraper 迁移提示词

将此提示词发给新电脑上的 WorkBuddy Agent，完成 skill 安装和依赖配置。

---

## 提示词（直接复制发送）

```
请帮我安装和配置「小鹅通圈子内容抓取」skill。步骤如下：

### 1. 安装 Skill 文件
将 xiaoetong-scraper skill 目录复制到当前用户的 skill 目录下：
- 目标路径：~/.workbuddy/skills/xiaoetong-scraper/
- 确保目录结构为：
  ~/.workbuddy/skills/xiaoetong-scraper/
  ├── SKILL.md
  ├── MIGRATION.md
  └── scripts/
      ├── scraper.py
      ├── browser.py
      ├── api_interceptor.py
      ├── content_parser.py
      ├── output.py
      └── video_downloader.py

### 2. 安装 Python 依赖
使用 WorkBuddy 管理的 Python 环境（或系统 Python 3.10+）安装：

```bash
<python_path> -m pip install playwright pyyaml pycryptodome requests
```

其中 `<python_path>` 替换为实际 Python 路径：
- WorkBuddy 管理 Python：~/.workbuddy/binaries/python/envs/default/Scripts/python.exe（Windows）或 ~/.workbuddy/binaries/python/envs/default/bin/python（macOS/Linux）
- 系统 Python：直接用 python3

### 3. 安装 Playwright Chromium 浏览器

```bash
<python_path> -m playwright install chromium
```

这一步会下载约 150MB 的 Chromium 浏览器，需等待完成。

⚠️ 如果电脑需要代理才能联网，先设置代理再安装：
```bash
# Windows（临时设置）
set HTTPS_PROXY=http://127.0.0.1:端口号
set HTTP_PROXY=http://127.0.0.1:端口号

# macOS/Linux
export HTTPS_PROXY=http://127.0.0.1:端口号
export HTTP_PROXY=http://127.0.0.1:端口号
```

如果代理下载仍然慢，可以用国内镜像：
```bash
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright  # Windows
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright  # macOS/Linux
<python_path> -m playwright install chromium
```

### 4. 验证安装
运行以下命令验证依赖安装成功：

```bash
cd ~/.workbuddy/skills/xiaoetong-scraper/scripts
<python_path> -c "import playwright, yaml, Crypto, requests; print('依赖安装成功')"
<python_path> -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop(); print('Chromium 启动成功')"
```

### 5. 配置代理（重要！）
根据新电脑的网络环境，确认是否需要代理访问小鹅通网站：

**情况 A — 直连（无需代理）：**
配置文件中 proxy 留空即可，脚本自动直连。

**情况 B — 有代理（如公司网络、VPN）：**
在 xiaoetong.yaml 的 login.proxy 字段填写代理地址：
```yaml
login:
  proxy: "http://127.0.0.1:15556"   # 替换为实际代理地址和端口
```

**情况 C — 有环境变量代理（HTTP_PROXY/HTTPS_PROXY 已设置）：**
proxy 留空，脚本会自动检测并使用环境变量中的代理。

脚本启动时会打印代理状态，方便确认：
- `使用配置代理: http://...` — 使用了 yaml 中的 proxy
- `检测到环境代理: http://...` — 使用了环境变量
- `无代理配置（直连模式）` — 无代理

### 6. 创建配置文件
在 Obsidian Vault 根目录创建 `xiaoetong.yaml`（与 `sources.yaml` 同级）：

```yaml
circles:
  - name: "圈子名称"
    community_id: "c_xxx_xxx"       # 从圈子 URL 提取
    app_id: "appxxxx"               # 小鹅通店铺 app_id
    enabled: true

output:
  staging_path: "Cubox/Staging/"
  attachments_subdir: "attachments/"
  video_dir: "videos/"

login:
  cookie_file: ".xiaoetong-cookies.json"
  headless: false
  proxy: ""                         # 代理地址，如 http://127.0.0.1:15556
                                    # 留空 = 自动检测环境变量
                                    # 无环境变量 = 直连

scrape:
  download_images: true
  download_videos: true
  download_audio: true
  include_comments: true
  max_posts: 0
  delay_range: [1.0, 3.0]

incremental:
  state_file: ".xiaoetong-state.json"
```

如何获取 community_id 和 app_id：
1. 登录小鹅通圈子 PC 端 quanzi.xiaoe-tech.com
2. 进入圈子，URL 格式为 https://quanzi.xiaoe-tech.com/c_xxx_xxx/feed_list?app_id=appxxxx
3. c_xxx_xxx 是 community_id，appxxxx 是 app_id

### 7. 首次运行测试
```bash
cd ~/.workbuddy/skills/xiaoetong-scraper/scripts
<python_path> scraper.py --max-posts 2
```

首次运行会弹出浏览器窗口，显示微信扫码登录界面。扫码登录后，Cookie 自动保存到 Vault 根目录的 .xiaoetong-cookies.json，后续运行无需再扫。

⚠️ 运行时注意观察代理状态打印，确认网络连通性。如果页面打不开或超时，检查代理配置。

### 8.（可选）安装 ffmpeg 用于视频下载
```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

不安装 ffmpeg 不影响图文抓取，脚本会自动跳过视频。

---

### 常见问题排查

**Q: Playwright Chromium 下载失败/超时**
A: 需要代理联网。先设置 HTTPS_PROXY 环境变量再重试。或用国内镜像：
```bash
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright  # Windows
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright  # macOS/Linux
<python_path> -m playwright install chromium
```

**Q: 浏览器启动后白屏/崩溃**
A: 检查是否有 NODE_OPTIONS 环境变量干扰。脚本已自动清除 NODE_OPTIONS，但如果仍有问题，手动 unset：
```bash
unset NODE_OPTIONS   # macOS/Linux
set NODE_OPTIONS=    # Windows
```

**Q: 浏览器启动后页面打不开/超时**
A: 检查代理配置！脚本启动时会打印代理状态。如果是「无代理配置」但实际需要代理，在 xiaoetong.yaml 的 login.proxy 字段填入代理地址。如果是「检测到环境代理」但代理地址不对，检查环境变量 HTTPS_PROXY/HTTP_PROXY 是否正确。

**Q: 直接访问课程 URL 跳到店铺页面**
A: 必须先登录再导航。脚本已处理此逻辑：先访问登录页 → 扫码 → 再导航到目标 URL。

**Q: Windows 终端中文乱码**
A: 脚本已内置 UTF-8 stdout/stderr 重包装。如果仍有问题，手动设置：
```bash
set PYTHONIOENCODING=utf-8
chcp 65001
```
```

---

## 使用方式

1. 将整个 `xiaoetong-scraper/` skill 目录（含 SKILL.md + MIGRATION.md + scripts/）拷贝到新电脑
2. 在新电脑的 WorkBuddy 中发送上面的提示词
3. Agent 会按步骤安装依赖、配置 Playwright Chromium、创建配置文件
4. **特别注意第 5 步**：根据新电脑网络环境配置代理（直连/yaml 配置/环境变量）
5. 首次运行时手动扫码登录即可
