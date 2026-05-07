"""小鹅通圈子内容抓取器 — 主入口。

用法:
  python scraper.py                        # 增量抓取所有启用的圈子
  python scraper.py --discover             # 发现模式：拦截 API 端点
  python scraper.py --circle c_xxx_xxx     # 只抓指定圈子
  python scraper.py --max-posts 10         # 限制每圈最多10条
  python scraper.py --full                 # 强制全量抓取
  python scraper.py --no-video             # 跳过视频下载
"""

import argparse
import json
import os
import sys
import time
import random
from pathlib import Path

# 修复 Windows 输出编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 将脚本所在目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import yaml

from browser import BrowserManager, BASE_URL
from api_interceptor import APIInterceptor
from content_parser import ContentParser
from output import OutputManager


def _find_vault_root() -> str:
    """自动查找 Vault 根目录（xiaoetong.yaml 所在目录）。

    查找顺序：
    1. 当前工作目录及向上递归 3 层
    2. 常见 Vault 路径（~/Documents/Obsidian Vault）
    3. 找不到则返回空字符串，由调用方报错
    """
    # 从当前目录向上查找
    search_dir = Path.cwd()
    for _ in range(4):
        if (search_dir / "xiaoetong.yaml").exists():
            return str(search_dir)
        parent = search_dir.parent
        if parent == search_dir:
            break
        search_dir = parent

    # 常见路径
    common_paths = [
        Path.home() / "Documents" / "Obsidian Vault",
        Path.home() / "Obsidian Vault",
    ]
    for p in common_paths:
        if p.exists() and (p / "xiaoetong.yaml").exists():
            return str(p)

    return ""


def load_config(config_path: str = None) -> tuple[dict, str]:
    """加载 xiaoetong.yaml 配置。

    Args:
        config_path: xiaoetong.yaml 的完整路径。如果为 None，自动查找。

    Returns:
        (config_dict, vault_root_str)
    """
    if config_path:
        config_file = Path(config_path)
    else:
        vault_root = _find_vault_root()
        if not vault_root:
            print("❌ 找不到 xiaoetong.yaml 配置文件")
            print("   请使用 --config 参数指定路径，或在 Vault 根目录下创建 xiaoetong.yaml")
            sys.exit(1)
        config_file = Path(vault_root) / "xiaoetong.yaml"

    if not config_file.exists():
        print(f"❌ 配置文件不存在: {config_file}")
        sys.exit(1)

    # Vault 根目录 = 配置文件所在目录
    vault_root = str(config_file.parent)

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 补全默认值
    config.setdefault("output", {})
    config["output"].setdefault("staging_path", "Cubox/Staging/")
    config["output"].setdefault("attachments_subdir", "attachments/")
    config["output"].setdefault("video_dir", "videos/")

    config.setdefault("login", {})
    config["login"].setdefault("cookie_file", ".xiaoetong-cookies.json")
    config["login"].setdefault("headless", False)
    config["login"].setdefault("proxy", "")  # 显式代理，如 http://127.0.0.1:15556，留空则自动检测环境变量

    config.setdefault("scrape", {})
    config["scrape"].setdefault("include_comments", True)
    config["scrape"].setdefault("include_likes", True)
    config["scrape"].setdefault("download_videos", True)
    config["scrape"].setdefault("download_audio", True)
    config["scrape"].setdefault("download_images", True)
    config["scrape"].setdefault("max_posts", 0)
    config["scrape"].setdefault("delay_range", [1.0, 3.0])

    config.setdefault("incremental", {})
    config["incremental"].setdefault("state_file", ".xiaoetong-state.json")
    config["incremental"].setdefault("track_by", "feeds_id")

    return config, vault_root


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否可用。"""
    import shutil
    return shutil.which("ffmpeg") is not None


def _extract_images_from_dom(page) -> list[str]:
    """从页面 DOM 提取所有图片 URL（支持 src 和 data-src 懒加载）。"""
    images = []
    try:
        # 用 JS 提取所有 img 元素的 src 和 data-src
        img_data = page.evaluate("""() => {
            const imgs = document.querySelectorAll('img');
            const results = [];
            for (const img of imgs) {
                // 跳过小图标、头像、logo 等
                const w = img.naturalWidth || img.width || 0;
                const h = img.naturalHeight || img.height || 0;
                const cls = (img.className || '').toLowerCase();
                const alt = (img.alt || '').toLowerCase();

                // 跳过明显的小图标
                if (w > 0 && w < 50 && h > 0 && h < 50) continue;
                if (cls.includes('avatar') || cls.includes('logo') || cls.includes('icon')) continue;
                if (alt.includes('avatar') || alt.includes('logo')) continue;

                // 优先取 data-src（懒加载），其次 data-original，最后 src
                const url = img.dataset.src || img.dataset.original || img.src || '';
                if (url && !url.startsWith('data:') && !url.includes('avatar') && !url.includes('emoji')) {
                    results.push(url);
                }
            }
            // 也提取 background-image
            const allEls = document.querySelectorAll('[style*="background-image"]');
            for (const el of allEls) {
                const style = el.style.backgroundImage || '';
                const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
                if (match && match[1] && !match[1].startsWith('data:')) {
                    results.push(match[1]);
                }
            }
            return results;
        }""")

        if img_data and isinstance(img_data, list):
            images = [url for url in img_data if isinstance(url, str) and url.startswith("http")]
    except Exception:
        pass

    return images


def _save_debug_feed_data(feed_data: dict, feeds_id: str, vault_root: str):
    """保存帖子的原始 API 数据用于调试。"""
    debug_dir = Path(vault_root) / ".xiaoetong-debug"
    debug_dir.mkdir(exist_ok=True)
    debug_path = debug_dir / f"{feeds_id}.json"
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(feed_data, f, ensure_ascii=False, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="小鹅通圈子内容抓取器")
    parser.add_argument("--discover", action="store_true", help="发现模式：拦截并记录 API 端点")
    parser.add_argument("--circle", type=str, help="只抓指定圈子 ID")
    parser.add_argument("--max-posts", type=int, default=0, help="每个圈子最多抓取帖子数（0=全部）")
    parser.add_argument("--full", action="store_true", help="强制全量抓取（忽略增量状态）")
    parser.add_argument("--no-video", action="store_true", help="跳过视频下载")
    parser.add_argument("--no-image", action="store_true", help="跳过图片下载")
    parser.add_argument("--headless", action="store_true", help="无头模式（首次登录不建议使用）")
    parser.add_argument("--config", type=str, default=None, help="xiaoetong.yaml 配置文件路径（默认自动查找）")
    parser.add_argument("--url", type=str, default=None, help="发现模式：直接导航到指定 URL（如课程页面）")
    args = parser.parse_args()

    print("=" * 60)
    print("  小鹅通圈子内容抓取器 v1.2")
    print("=" * 60)

    # 加载配置（自动查找或指定路径）
    config, vault_root = load_config(args.config)

    # 检查 ffmpeg
    has_ffmpeg = check_ffmpeg()
    if not has_ffmpeg and config["scrape"]["download_videos"] and not args.no_video:
        print("\n⚠️  ffmpeg 未安装，视频下载将不可用")
        print("   安装方式: winget install ffmpeg")
        print("   或从 https://ffmpeg.org/download.html 下载")
        print("   继续抓取图文内容...\n")

    # 过滤启用的圈子
    circles = [c for c in config.get("circles", []) if c.get("enabled", True)]
    if args.circle:
        circles = [c for c in circles if c["community_id"] == args.circle]

    if not circles:
        print("❌ 没有启用的圈子。请在 xiaoetong.yaml 中配置。")
        print(f"   配置文件: {Path(vault_root) / 'xiaoetong.yaml'}")
        sys.exit(1)

    # 初始化组件
    delay_range = tuple(config["scrape"]["delay_range"])
    cookie_path = str(Path(vault_root) / config["login"]["cookie_file"])
    headless = args.headless or config["login"]["headless"]

    # 从第一个圈子获取 app_id
    app_id = ""
    if circles:
        app_id = circles[0].get("app_id", "")

    browser = BrowserManager(
        cookie_path=cookie_path,
        headless=headless,
        delay_range=delay_range,
        app_id=app_id,
        proxy=config["login"].get("proxy", ""),
    )

    interceptor = APIInterceptor(discover_mode=args.discover)
    content_parser = ContentParser()
    output = OutputManager(
        staging_path=config["output"]["staging_path"],
        vault_root=vault_root,
        attachments_subdir=config["output"]["attachments_subdir"],
        video_dir=config["output"]["video_dir"],
        state_file=config["incremental"]["state_file"],
    )

    # 视频下载器（按需创建）
    video_downloader = None
    if has_ffmpeg and config["scrape"]["download_videos"] and not args.no_video:
        from video_downloader import VideoDownloader
        video_downloader = VideoDownloader(
            output_dir=str(output.video_dir),
        )

    try:
        # Step 1: 启动浏览器
        print("\n📱 启动浏览器...")
        browser.start()

        # Step 2: 挂载 API 拦截器
        interceptor.attach(browser.page)

        # Step 3: 登录
        # 即使使用 --url 直接访问课程页面，也需要先建立登录态
        # 因为 h5.xiaoeknow.com 需要 Cookie 认证，没有登录态会被重定向到店铺页
        print("\n🔐 检查登录状态...")
        if not browser.ensure_login():
            print("❌ 登录失败，退出")
            return

        # Step 4: 发现模式
        if args.discover:
            print("\n🔍 发现模式：开始拦截 API 端点...")
            print("   请在浏览器中浏览内容（滚动、点击帖子/课程等）")
            print("   按 Ctrl+C 结束发现模式\n")

            try:
                # 导航到指定 URL 或圈子列表
                if args.url:
                    print(f"  导航到: {args.url}")
                    browser.page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                elif circles:
                    first_circle = circles[0]
                    browser.navigate_to_circle(first_circle["community_id"])
                    browser.scroll_to_load_more(max_scrolls=5)

                # 等待用户操作
                print("   浏览器保持打开，请在浏览器中操作...")
                print("   脚本将持续监听网络请求")
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                print("\n   结束发现模式")

            # 生成报告
            report_path = str(Path(vault_root) / "xiaoetong-api-discovery.txt")
            interceptor.save_discovery_report(report_path)

            # 输出已捕获的 API 类型
            print("\n📊 捕获到的 API 类型:")
            for api_type, responses in interceptor.captured.items():
                print(f"   {api_type}: {len(responses)} 个响应")

            browser.stop()
            return

        # Step 5: 正式抓取
        max_posts = args.max_posts or config["scrape"]["max_posts"]
        total_posts = 0
        total_new = 0
        new_files = []

        for circle in circles:
            circle_name = circle.get("name", circle["community_id"])
            community_id = circle["community_id"]

            print(f"\n{'─' * 50}")
            print(f"📂 圈子: {circle_name} ({community_id})")
            print(f"{'─' * 50}")

            # 导航到圈子
            if not browser.navigate_to_circle(community_id):
                print(f"  ⚠️ 无法访问圈子，跳过")
                continue

            # 拦截 feedList API 获取帖子列表
            interceptor.clear()
            browser.scroll_to_load_more(max_scrolls=100)

            # 从拦截的数据提取帖子列表
            feed_list = interceptor.get_feed_list_data()

            if not feed_list:
                print("  ⚠️ 未捕获到帖子列表数据")
                print("  提示: 尝试用 --discover 模式先发现 API 端点")
                continue

            print(f"  共发现 {len(feed_list)} 条帖子")

            # 过滤已处理的帖子
            new_feeds = []
            for feed in feed_list:
                feeds_id = str(feed.get("feeds_id") or feed.get("feed_id") or feed.get("id") or "")
                if not feeds_id:
                    continue
                if not args.full and output.is_post_processed(feeds_id):
                    continue
                new_feeds.append(feed)

            print(f"  新帖子: {len(new_feeds)} 条")

            if not new_feeds:
                print("  无新内容，跳过")
                continue

            # 限制数量
            if max_posts > 0:
                new_feeds = new_feeds[:max_posts]
                print(f"  限制抓取: {len(new_feeds)} 条")

            # 逐帖抓取
            for idx, feed in enumerate(new_feeds, 1):
                feeds_id = str(feed.get("feeds_id") or feed.get("feed_id") or feed.get("id") or f"unknown_{idx}")
                print(f"\n  [{idx}/{len(new_feeds)}] 处理帖子 {feeds_id}...")

                # 从列表数据解析基本字段
                post = content_parser.parse_feed_from_api(feed, community_id)

                # 保存原始 API 数据用于调试
                _save_debug_feed_data(feed, feeds_id, vault_root)

                # 诊断：打印图片提取结果
                if post.post_type == "图文":
                    img_count = len(post.images)
                    if img_count == 0:
                        # 检查原始数据中是否有图片相关字段
                        img_keys = [k for k in feed.keys() if any(kw in k.lower() for kw in ["img", "image", "pic", "cover", "media"])]
                        content = feed.get("content", "")
                        has_img_tag = "<img" in str(content).lower() if content else False
                        print(f"    ⚠️ 图文帖子无图片 | 图片字段: {img_keys} | content含img标签: {has_img_tag}")
                    else:
                        print(f"    📷 提取到 {img_count} 张图片")

                # 尝试进入帖子详情获取完整内容
                if post.url:
                    try:
                        interceptor.clear()
                        browser.page.goto(post.url, wait_until="networkidle", timeout=15000)
                        time.sleep(random.uniform(*delay_range))

                        # 从详情页 API 响应补充数据
                        detail_data = interceptor.get_feed_detail_data()
                        if detail_data:
                            # 保存详情页 debug 数据
                            _save_debug_feed_data(detail_data[0], f"{feeds_id}_detail", vault_root)

                            detail_post = content_parser.parse_feed_from_api(detail_data[0], community_id)
                            # 合并详情数据（覆盖列表数据）
                            if detail_post.content_markdown and not post.content_markdown:
                                post.content_markdown = detail_post.content_markdown
                                post.content_html = detail_post.content_html
                                post.content_text = detail_post.content_text
                            # 图片合并：详情页可能有更多/更完整的图片
                            if detail_post.images:
                                existing = set(post.images)
                                for img in detail_post.images:
                                    if img not in existing:
                                        post.images.append(img)
                                        existing.add(img)
                            if detail_post.video_url and not post.video_url:
                                post.video_url = detail_post.video_url
                            if detail_post.audio_url and not post.audio_url:
                                post.audio_url = detail_post.audio_url

                        # 获取播放地址（视频）
                        play_url_data = interceptor.get_play_url_data()
                        if play_url_data:
                            play_info = play_url_data[0]
                            m3u8_url = ""
                            if isinstance(play_info, dict):
                                # 尝试多种字段路径
                                play_list = play_info.get("play_list") or play_info.get("play_url") or {}
                                if isinstance(play_list, dict):
                                    m3u8_url = play_list.get("play_url") or play_list.get("url") or ""
                                elif isinstance(play_list, str):
                                    m3u8_url = play_list
                                if not m3u8_url:
                                    m3u8_url = play_info.get("play_url") or play_info.get("url") or ""
                            if m3u8_url:
                                post.video_m3u8 = m3u8_url

                        # 获取评论
                        if config["scrape"]["include_comments"]:
                            comment_data = interceptor.get_comment_data()
                            if comment_data:
                                post.comments = content_parser.parse_comments(comment_data)

                    except Exception as e:
                        print(f"    详情页访问失败: {e}")

                    # 无论 API 是否成功，都用 DOM 补充图片（图文帖子经常图片在 DOM 而非 API）
                    try:
                        # 等待图片加载
                        browser.page.wait_for_selector("img", timeout=5000)
                        time.sleep(0.5)
                    except Exception:
                        pass

                    try:
                        dom_images = _extract_images_from_dom(browser.page)
                        if dom_images:
                            existing = set(post.images)
                            added = 0
                            for img_url in dom_images:
                                if img_url not in existing:
                                    post.images.append(img_url)
                                    existing.add(img_url)
                                    added += 1
                            if added:
                                print(f"    从 DOM 补充 {added} 张图片")
                    except Exception as e:
                        print(f"    DOM 图片提取失败: {e}")

                    # 如果帖子类型是图文但仍然没有图片，尝试等待懒加载
                    if not post.images and post.post_type == "图文":
                        try:
                            browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            time.sleep(1)
                            dom_images = _extract_images_from_dom(browser.page)
                            if dom_images:
                                existing = set(post.images)
                                for img_url in dom_images:
                                    if img_url not in existing:
                                        post.images.append(img_url)
                                        existing.add(img_url)
                                if post.images:
                                    print(f"    懒加载后补充 {len(post.images)} 张图片")
                        except Exception:
                            pass

                # 下载图片
                if config["scrape"]["download_images"] and not args.no_image and post.images:
                    print(f"    下载 {len(post.images)} 张图片...")
                    output.download_images(post)

                # 下载视频
                if video_downloader and post.video_m3u8:
                    print(f"    下载视频...")
                    video_downloader.download_video(
                        post.video_m3u8,
                        post.feeds_id,
                        cookies=dict(browser.context.cookies()) if browser.context else None,
                    )
                elif post.video_url and not post.video_m3u8:
                    print(f"    ⚠️ 有视频但未获取到 M3U8 地址")

                # 下载音频
                if config["scrape"]["download_audio"] and post.audio_url:
                    output.download_audio(post)

                # 输出 Markdown
                filepath = output.write_post(post, circle_name)
                print(f"    ✅ 已保存: {Path(filepath).name}")
                new_files.append(filepath)
                total_new += 1

                total_posts += 1

                # 返回列表页
                if idx < len(new_feeds):
                    browser.go_back()

            print(f"\n  圈子 {circle_name} 抓取完成: {len(new_feeds)} 条新内容")

        # Step 6: 输出新文章清单
        if new_files:
            output.write_new_articles_list(new_files)

        # 总结
        print(f"\n{'=' * 60}")
        print(f"  抓取完成！")
        print(f"  总帖子: {total_posts}")
        print(f"  新内容: {total_new}")
        print(f"  输出目录: {output.staging_path}")
        print(f"{'=' * 60}")

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断抓取")
    except Exception as e:
        print(f"\n❌ 抓取异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        browser.stop()


if __name__ == "__main__":
    main()
