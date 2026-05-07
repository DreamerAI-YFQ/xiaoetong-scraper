"""Playwright 浏览器管理：登录、Cookie 持久化、页面操作。"""

import json
import os
import sys
import time
import random
from pathlib import Path
from typing import Optional

# 修复 Windows 输出编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ====== 关键：在 import playwright 之前清除 NODE_OPTIONS ======
# NODE_OPTIONS=--use-system-ca 会导致 Playwright 内置 Node.js 崩溃
# 但代理环境变量（HTTP_PROXY 等）必须保留，让 Chromium 子进程自然继承
os.environ.pop("NODE_OPTIONS", None)

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


BASE_URL = "https://quanzi.xiaoe-tech.com"
SIGN_IN_URL = f"{BASE_URL}/sign_in"


class BrowserManager:
    """管理 Playwright 浏览器实例和登录态。"""

    def __init__(self, cookie_path: str, headless: bool = False,
                 delay_range: tuple = (1.0, 3.0), app_id: str = "",
                 proxy: str = ""):
        self.cookie_path = Path(cookie_path)
        self.headless = headless
        self.delay_range = delay_range
        self.app_id = app_id
        self.proxy = proxy  # 显式代理地址，如 http://127.0.0.1:15556
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            raise RuntimeError("Browser not started or page closed. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context

    def _is_page_alive(self) -> bool:
        """检查页面是否存活。"""
        return self._page is not None and not self._page.is_closed()

    def start(self):
        """启动浏览器，尝试恢复登录态。"""
        self._playwright = sync_playwright().start()

        # 只删 NODE_OPTIONS，代理环境变量保留让 Chromium 自然继承
        os.environ.pop("NODE_OPTIONS", None)

        # 构建启动参数
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ]

        # 代理配置：优先使用 yaml 显式配置，其次环境变量
        proxy_config = None
        if self.proxy:
            # 显式代理（如 http://127.0.0.1:15556）
            proxy_config = {"server": self.proxy}
            print(f"  使用配置代理: {self.proxy}")
        else:
            # 检查环境变量，如果有则让 Chromium 自动继承
            env_proxy = (
                os.environ.get("HTTPS_PROXY")
                or os.environ.get("HTTP_PROXY")
                or os.environ.get("https_proxy")
                or os.environ.get("http_proxy")
                or ""
            )
            if env_proxy:
                print(f"  检测到环境代理: {env_proxy}")
            else:
                print("  无代理配置（直连模式）")

        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            proxy=proxy_config,
        )
        self._context = self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )

        # 注入 APPID（简单赋值，网站 JS 需要写入此属性）
        if self.app_id:
            self._context.add_init_script(f"""
                window.__app_id = '{self.app_id}';
                window.APPID = '{self.app_id}';
            """)
            print(f"  已注入 APPID: {self.app_id}")

        # 尝试加载已保存的 Cookie
        if self.cookie_path.exists():
            cookies = self._load_cookies()
            if cookies:
                self._context.add_cookies(cookies)
                print(f"  已加载 {len(cookies)} 个 Cookie")

        self._page = self._context.new_page()

        # 只监听关键 console 错误（过滤噪音）
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_pageerror)

        print("  浏览器已启动")

    def _on_console(self, msg):
        """处理 console 消息，过滤噪音。"""
        if msg.type == "error":
            text = msg.text
            noise_patterns = ["utils is not defined", "opts is not defined",
                            "seajs is not defined", "Aegis is not defined",
                            "skipping chrome loadtimes", "ERR_CONNECTION_CLOSED",
                            "rumt-zh.com"]
            if any(p in text for p in noise_patterns):
                return
            print(f"  [CONSOLE error] {text[:200]}")

    def _on_pageerror(self, err):
        """处理页面 JS 错误，过滤噪音。"""
        text = str(err)
        noise_patterns = ["utils is not defined", "opts is not defined",
                        "seajs is not defined", "Aegis is not defined",
                        "skipping chrome loadtimes", "file-obj is not exist"]
        if any(p in text for p in noise_patterns):
            return
        print(f"  [PAGE ERROR] {text[:300]}")

    def stop(self):
        """关闭浏览器。"""
        for obj, method in [
            (self._page, lambda p: p.close() if not p.is_closed() else None),
            (self._context, lambda c: c.close()),
            (self._browser, lambda b: b.close()),
            (self._playwright, lambda p: p.stop()),
        ]:
            try:
                if obj:
                    method(obj)
            except Exception:
                pass
        print("  浏览器已关闭")

    def _is_login_page(self) -> bool:
        """判断当前页面是否为登录页。"""
        if not self._is_page_alive():
            return False
        try:
            url = self.page.url
            if "sign_in" in url or "login" in url.lower():
                return True
            title = self.page.title()
            if "登录" in title or "login" in title.lower():
                return True
        except Exception:
            pass
        return False

    def _check_login_via_cookie(self) -> bool:
        """通过检查 Cookie 判断是否已登录（比 URL 检测更可靠）。"""
        try:
            cookies = self._context.cookies()
            # 小鹅通登录成功后会设置关键 Cookie
            auth_cookies = [c for c in cookies
                          if c.get("name") in ("token", "user_id", "xe_user_id",
                                                "community_user_id", "session_id")
                          and c.get("domain", "").find("xiaoe") >= 0]
            if auth_cookies:
                print(f"  检测到登录 Cookie: {[c['name'] for c in auth_cookies]}")
                return True
        except Exception:
            pass
        return False

    def ensure_login(self, timeout: int = 180) -> bool:
        """确保已登录。如未登录则等待用户手动登录。"""
        login_url = SIGN_IN_URL
        if self.app_id:
            login_url = f"{SIGN_IN_URL}?app_id={self.app_id}"

        print(f"  正在访问登录页: {login_url}")
        self.page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

        # 等待 SPA 渲染
        time.sleep(4)

        # 检查是否已登录（Cookie 或 URL 检测）
        if not self._is_login_page():
            print("  已登录（Cookie 有效）")
            self._save_cookies()
            return True

        if self._check_login_via_cookie():
            print("  已登录（Cookie 检测）")
            self._save_cookies()
            return True

        # 需要登录
        print(f"\n  ⚠️  需要登录，请在浏览器中扫码登录")
        print(f"  等待登录完成（最多 {timeout} 秒）...\n")

        # 轮询等待登录完成（同时检测 URL 变化和 Cookie 变化）
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(3)
            if not self._is_page_alive():
                print("  ❌ 页面被关闭")
                return False
            # 双重检测：URL 不再是登录页 OR 出现登录 Cookie
            if not self._is_login_page():
                elapsed = int(time.time() - start)
                print(f"  ✅ 登录成功！（耗时 {elapsed} 秒）")
                self._save_cookies()
                return True
            if self._check_login_via_cookie():
                elapsed = int(time.time() - start)
                print(f"  ✅ 登录成功！（Cookie 检测，耗时 {elapsed} 秒）")
                # 登录后主动跳转到圈子首页
                try:
                    self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(3)
                except Exception:
                    pass
                self._save_cookies()
                return True
            elapsed = int(time.time() - start)
            if elapsed % 15 == 0 and elapsed > 0:
                print(f"  等待登录中...（已等 {elapsed} 秒）")

        print("  ❌ 登录超时")
        return False

    def navigate_to_circle(self, community_id: str) -> bool:
        """导航到指定圈子的动态列表页。"""
        url = f"{BASE_URL}/{community_id}/feed_list"
        if self.app_id:
            url = f"{url}?app_id={self.app_id}"
        print(f"  导航到圈子: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # 确保圈子页面上 APPID 存在
            if self.app_id:
                try:
                    current_appid = self.page.evaluate("window.__app_id || window.APPID || ''")
                    if not current_appid:
                        self.page.evaluate(f"window.__app_id = '{self.app_id}'; window.APPID = '{self.app_id}';")
                        print(f"  重新注入 APPID: {self.app_id}")
                except Exception:
                    pass

            if not self._is_page_alive():
                print("  ❌ 页面已关闭，尝试重建...")
                self._page = self._context.new_page()
                self._page.on("console", self._on_console)
                self._page.on("pageerror", self._on_pageerror)
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)

            if self._is_login_page():
                print("  ⚠️ 登录态失效，请重新登录")
                return False

            try:
                title = self.page.title()
                print(f"  页面标题: {title}")
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"  ❌ 导航失败: {e}")
            return False

    def scroll_to_load_more(self, max_scrolls: int = 50, pause: float = 2.0) -> int:
        """滚动页面加载更多内容。"""
        scroll_count = 0
        prev_height = 0

        for i in range(max_scrolls):
            if not self._is_page_alive():
                print("    ⚠️ 页面已关闭，停止滚动")
                break

            try:
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                delay = random.uniform(*self.delay_range)
                time.sleep(delay)

                curr_height = self.page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    time.sleep(1)
                    curr_height = self.page.evaluate("document.body.scrollHeight")
                    if curr_height == prev_height:
                        break

                prev_height = curr_height
                scroll_count += 1

            except Exception as e:
                if "closed" in str(e).lower():
                    print(f"    ⚠️ 滚动时页面关闭")
                    break
                print(f"    ⚠️ 滚动异常: {e}")
                time.sleep(2)
                continue

            if (i + 1) % 10 == 0:
                print(f"    已滚动 {i + 1} 次...")

        print(f"    滚动完成，共 {scroll_count} 次")
        return scroll_count

    def click_post(self, post_selector: str) -> bool:
        """点击帖子进入详情页。"""
        try:
            self.page.click(post_selector)
            delay = random.uniform(*self.delay_range)
            time.sleep(delay)
            return True
        except Exception as e:
            print(f"    点击帖子失败: {e}")
            return False

    def go_back(self):
        """返回上一页。"""
        try:
            if self._is_page_alive():
                self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                delay = random.uniform(*self.delay_range)
                time.sleep(delay)
        except Exception as e:
            print(f"    返回上一页失败: {e}")

    def random_delay(self):
        """随机延迟（模拟人类操作）。"""
        delay = random.uniform(*self.delay_range)
        time.sleep(delay)

    # ---- Cookie 管理 ----

    def _load_cookies(self) -> list:
        """从文件加载 Cookie。"""
        try:
            with open(self.cookie_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Cookie 加载失败: {e}")
            return []

    def _save_cookies(self):
        """保存 Cookie 到文件。"""
        try:
            cookies = self._context.cookies()
            self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"  Cookie 已保存到 {self.cookie_path}（{len(cookies)} 个）")
        except Exception as e:
            print(f"  Cookie 保存失败: {e}")
