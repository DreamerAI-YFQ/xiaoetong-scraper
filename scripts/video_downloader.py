"""视频下载器：M3U8 双层解密 + TS 下载 + ffmpeg 合并。"""

import os
import re
import struct
import shutil
import tempfile
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES


# 小鹅通自定义加密的默认密钥
XIAOE_DEFAULT_KEY = "appbgzjnopv1917"


class VideoDownloader:
    """下载小鹅通加密 M3U8 视频并合并为 MP4。"""

    def __init__(self, output_dir: str, max_workers: int = 8):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quanzi.xiaoe-tech.com/",
        })
        self.ffmpeg_available = shutil.which("ffmpeg") is not None

    def download_video(self, m3u8_url: str, filename: str, cookies: dict = None) -> str | None:
        """下载视频并合并为 MP4。

        Args:
            m3u8_url: M3U8 播放地址
            filename: 输出文件名（不含扩展名）
            cookies: 请求时携带的 Cookie

        Returns:
            输出文件路径，失败返回 None
        """
        if not self.ffmpeg_available:
            print("    ⚠️ ffmpeg 未安装，无法合并视频。请安装 ffmpeg 后重试。")
            print("    下载方式: winget install ffmpeg 或 https://ffmpeg.org/download.html")
            return None

        if cookies:
            self.session.cookies.update(cookies)

        output_path = self.output_dir / f"{filename}.mp4"

        if output_path.exists():
            print(f"    视频已存在，跳过: {output_path}")
            return str(output_path)

        with tempfile.TemporaryDirectory(prefix="xiaoetong_") as tmpdir:
            tmppath = Path(tmpdir)

            try:
                # Step 1: 下载 M3U8 内容
                print(f"    下载 M3U8: {m3u8_url[:80]}...")
                m3u8_content = self._download_text(m3u8_url)
                if not m3u8_content:
                    print("    ❌ M3U8 下载失败")
                    return None

                # Step 2: 检查是否需要小鹅通自定义解密
                if m3u8_content.startswith("[xiaoe]"):
                    print("    检测到小鹅通自定义加密，执行第一层解密...")
                    m3u8_content = self._decrypt_xiaoe(m3u8_content)
                    if not m3u8_content:
                        print("    ❌ 小鹅通自定义解密失败")
                        return None

                # Step 3: 解析 M3U8
                m3u8_info = self._parse_m3u8(m3u8_content, m3u8_url)
                if not m3u8_info["segments"]:
                    print("    ❌ M3U8 解析失败：未找到 TS 片段")
                    return None

                # Step 4: 获取 AES 密钥（如有加密）
                aes_key = None
                aes_iv = b'\x00' * 16  # 默认 IV
                if m3u8_info.get("key_uri"):
                    print(f"    获取 AES 密钥: {m3u8_info['key_uri'][:80]}...")
                    aes_key = self._download_key(m3u8_info["key_uri"])
                    if not aes_key:
                        print("    ❌ AES 密钥获取失败")
                        return None

                # Step 5: 并发下载 TS 片段
                print(f"    下载 {len(m3u8_info['segments'])} 个 TS 片段...")
                ts_files = self._download_segments(
                    m3u8_info["segments"], aes_key, aes_iv, tmppath
                )

                if not ts_files:
                    print("    ❌ TS 片段下载失败")
                    return None

                # Step 6: ffmpeg 合并
                print(f"    合并 {len(ts_files)} 个片段为 MP4...")
                success = self._merge_ts_to_mp4(ts_files, output_path)

                if success:
                    print(f"    ✅ 视频已保存: {output_path}")
                    return str(output_path)
                else:
                    print("    ❌ ffmpeg 合并失败")
                    return None

            except Exception as e:
                print(f"    ❌ 视频下载异常: {e}")
                return None

    def _download_text(self, url: str) -> str | None:
        """下载文本内容。"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"    下载失败: {e}")
            return None

    def _download_key(self, url: str) -> bytes | None:
        """下载 AES 密钥。"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            print(f"    密钥下载失败: {e}")
            return None

    def _decrypt_xiaoe(self, encrypted_content: str) -> str | None:
        """小鹅通自定义解密（第一层）。

        加密格式：[xiaoe] + Base64编码的自定义加密数据
        解密逻辑参考 xiaoedown 项目
        """
        try:
            # 去除 [xiaoe] 前缀
            encrypted = encrypted_content[7:]

            # Base64 解码
            import base64
            decoded = base64.b64decode(encrypted)

            # 小鹅通自定义解密
            # 使用默认密钥生成解密映射
            key = XIAOE_DEFAULT_KEY
            key_md5 = hashlib.md5(key.encode()).hexdigest()

            # 字符替换解密
            result = bytearray()
            for i, b in enumerate(decoded):
                key_byte = ord(key[i % len(key)])
                result.append(b ^ key_byte)

            decrypted = result.decode("utf-8", errors="ignore")

            # 验证是否为有效的 M3U8
            if "#EXTM3U" in decrypted or "#EXT-X-" in decrypted:
                return decrypted

            # 尝试另一种解密方式：MD5 映射
            result2 = bytearray()
            for i, b in enumerate(decoded):
                key_byte = ord(key_md5[i % len(key_md5)])
                result2.append(b ^ key_byte)

            decrypted2 = result2.decode("utf-8", errors="ignore")
            if "#EXTM3U" in decrypted2 or "#EXT-X-" in decrypted2:
                return decrypted2

            # 如果都不行，返回原始解码尝试
            return decrypted if decrypted else decrypted2

        except Exception as e:
            print(f"    小鹅通解密异常: {e}")
            return None

    def _parse_m3u8(self, content: str, base_url: str) -> dict:
        """解析 M3U8 文件，提取 TS 片段 URL 和加密信息。"""
        info = {
            "segments": [],
            "key_uri": None,
            "key_method": None,
            "key_iv": None,
        }

        lines = content.strip().split("\n")

        # 解析基础 URL
        from urllib.parse import urljoin
        base = base_url.rsplit("/", 1)[0] + "/"

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 加密密钥信息
            if line.startswith("#EXT-X-KEY:"):
                attrs = self._parse_m3u8_attributes(line)
                info["key_method"] = attrs.get("METHOD")
                key_uri = attrs.get("URI", "").strip('"')
                if key_uri:
                    if not key_uri.startswith("http"):
                        key_uri = urljoin(base, key_uri)
                    info["key_uri"] = key_uri
                iv = attrs.get("IV")
                if iv:
                    # IV 格式: 0xHHHH...
                    iv_hex = iv.replace("0x", "").replace("0X", "")
                    info["key_iv"] = bytes.fromhex(iv_hex)

            # TS 片段 URL（非 # 开头的行）
            elif line and not line.startswith("#"):
                segment_url = line
                if not segment_url.startswith("http"):
                    segment_url = urljoin(base, segment_url)
                info["segments"].append(segment_url)

            i += 1

        return info

    def _parse_m3u8_attributes(self, line: str) -> dict:
        """解析 M3U8 属性行。"""
        attrs = {}
        # 去除 #EXT-X-KEY: 前缀
        attr_str = line.split(":", 1)[1] if ":" in line else ""

        # 匹配 KEY=VALUE 或 KEY="VALUE" 格式
        pattern = re.compile(r'([A-Z0-9-]+)=("([^"]*)"|([^,]*))')
        for match in pattern.finditer(attr_str):
            key = match.group(1)
            value = match.group(3) if match.group(3) is not None else match.group(4)
            attrs[key] = value

        return attrs

    def _download_segments(self, segments: list[str], aes_key: bytes | None,
                          aes_iv: bytes, tmpdir: Path) -> list[str]:
        """并发下载 TS 片段。"""
        ts_files = []

        def download_one(index_url):
            index, url = index_url
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.content

                # AES 解密
                if aes_key:
                    cipher = AES.new(aes_key, AES.MODE_CBC, iv=aes_iv)
                    data = cipher.decrypt(data)
                    # 去除 PKCS7 填充
                    pad_len = data[-1]
                    if 0 < pad_len <= 16:
                        data = data[:-pad_len]

                ts_path = tmpdir / f"seg_{index:05d}.ts"
                ts_path.write_bytes(data)
                return str(ts_path)
            except Exception as e:
                print(f"      片段 {index} 下载失败: {e}")
                return None

        # 并发下载
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(download_one, (i, url)): i
                for i, url in enumerate(segments)
            }

            results = [None] * len(segments)
            completed = 0
            for future in as_completed(futures):
                idx = futures[future]
                result = future.result()
                results[idx] = result
                completed += 1
                if completed % 20 == 0 or completed == len(segments):
                    print(f"      进度: {completed}/{len(segments)}")

        # 按顺序收集成功的文件
        ts_files = [r for r in results if r is not None]
        return ts_files

    def _merge_ts_to_mp4(self, ts_files: list[str], output_path: Path) -> bool:
        """使用 ffmpeg 合并 TS 片段为 MP4。"""
        # 创建文件列表
        list_path = output_path.parent / f"{output_path.stem}_filelist.txt"
        try:
            with open(list_path, "w", encoding="utf-8") as f:
                for ts_file in ts_files:
                    # ffmpeg 文件列表中使用正斜杠
                    ts_path = ts_file.replace("\\", "/")
                    f.write(f"file '{ts_path}'\n")

            # 执行 ffmpeg 合并
            import subprocess
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-c", "copy",
                str(output_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                print(f"    ffmpeg 错误: {result.stderr[-300:]}")
                return False

            return True

        except subprocess.TimeoutExpired:
            print("    ffmpeg 合并超时")
            return False
        except Exception as e:
            print(f"    合并异常: {e}")
            return False
        finally:
            # 清理文件列表
            if list_path.exists():
                list_path.unlink()
