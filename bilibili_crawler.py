from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from tqdm import tqdm


MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


class BilibiliCrawlerError(RuntimeError):
    """Bilibili crawler error."""


@dataclass(frozen=True)
class CrawlerConfig:
    up_mid: str = ""
    up_mids: list[str] = field(default_factory=list)
    cookies_str: str = ""
    bili_jct: str = ""
    output_dir: str = "outputs"
    output_format: str = "both"
    page_size: int = 30
    max_pages: int | None = None
    request_interval_seconds: float = 10.0
    request_interval_jitter_seconds: float = 5.0
    detail_request_interval_seconds: float = 3.0
    detail_request_interval_jitter_seconds: float = 2.0
    timeout_seconds: int = 20
    max_retries: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
    order: str = "pubdate"
    tid: int = 0
    keyword: str = ""
    fetch_video_detail: bool = True
    failed_pages_file: str = "outputs/failed_pages.jsonl"
    stop_on_page_error: bool = False
    continue_on_detail_error: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> "CrawlerConfig":
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file:
            raw_config = json.load(file)

        old_cookie = raw_config.pop("cookie", "")
        for legacy_key in (
            "browser_headless",
            "browser_user_data_dir",
            "login_check_timeout_seconds",
            "keep_browser_open",
        ):
            raw_config.pop(legacy_key, None)

        raw_config.setdefault("cookies_str", old_cookie)
        raw_config.setdefault("bili_jct", "")
        if isinstance(raw_config.get("up_mids"), str):
            raw_config["up_mids"] = split_mids(raw_config["up_mids"])
        return cls(**raw_config)

    def target_mids(self) -> list[str]:
        mids = [mid.strip() for mid in self.up_mids if str(mid).strip()]
        if self.up_mid.strip():
            mids.insert(0, self.up_mid.strip())
        return list(dict.fromkeys(mids))


class BilibiliCrawler:
    nav_api = "https://api.bilibili.com/x/web-interface/nav"
    space_video_api = "https://api.bilibili.com/x/space/wbi/arc/search"
    video_detail_api = "https://api.bilibili.com/x/web-interface/view"

    def __init__(self, config: CrawlerConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self._mixin_key: str | None = None
        self._setup_session()

    def _setup_session(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Cookie": self.normalized_cookie(),
                "Origin": "https://space.bilibili.com",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }
        )

    def normalized_cookie(self) -> str:
        cookies_str = self.config.cookies_str.strip()
        if not cookies_str or cookies_str == "写入您的cookies":
            raise BilibiliCrawlerError("请先在 config.json 的 cookies_str 中填入浏览器 Cookie。")

        bili_jct = self.config.bili_jct.strip()
        if bili_jct and "bili_jct=" not in cookies_str:
            cookies_str = f"{cookies_str.rstrip('; ')}; bili_jct={bili_jct}"

        if not bili_jct and "bili_jct=" not in cookies_str:
            raise BilibiliCrawlerError("请先在 config.json 的 bili_jct 中填入 Cookie 里的 bili_jct。")

        return cookies_str

    def ensure_logged_in(self) -> None:
        nav_data = self.request_json(self.nav_api)
        if not nav_data.get("data", {}).get("isLogin"):
            raise BilibiliCrawlerError(
                "Cookie 未登录或已失效。请重新从浏览器复制完整 Cookie 到 config.json。"
            )

        uname = nav_data.get("data", {}).get("uname", "")
        print(f"已检测到 Bilibili 登录状态：{uname}" if uname else "已检测到 Bilibili 登录状态。")

    def crawl_all(self) -> list[dict[str, Any]]:
        target_mids = self.config.target_mids()
        if not target_mids:
            raise BilibiliCrawlerError("请在 config.json 中配置 up_mid 或 up_mids。")

        self.ensure_logged_in()
        all_videos: list[dict[str, Any]] = []
        for index, mid in enumerate(target_mids, start=1):
            if index > 1:
                self.sleep_between_pages()
            print(f"开始爬取 UP {mid} ({index}/{len(target_mids)})")
            all_videos.extend(self.crawl_mid(mid))
        return all_videos

    def crawl_mid(self, mid: str) -> list[dict[str, Any]]:
        self.update_referer(mid)
        self.warm_up_space_page(mid)

        try:
            first_page = self.fetch_video_page(mid=mid, page_number=1)
        except BilibiliCrawlerError as exc:
            self.record_failed_page(mid, 1, exc)
            if self.config.stop_on_page_error:
                raise
            return []

        videos = self.parse_videos(first_page, fallback_mid=mid)
        videos = self.enrich_videos_with_detail(videos)
        total_count = self.get_total_count(first_page, len(videos))
        total_pages = self.calculate_total_pages(total_count)

        if self.config.max_pages is not None:
            total_pages = min(total_pages, self.config.max_pages)

        seen_bvids = {item["bvid"] for item in videos if item.get("bvid")}
        progress = tqdm(total=total_pages, initial=1, desc=f"UP {mid}", unit="page")

        for page_number in range(2, total_pages + 1):
            self.sleep_between_pages()
            try:
                page_data = self.fetch_video_page(mid=mid, page_number=page_number)
                page_videos = self.parse_videos(page_data, fallback_mid=mid)
                page_videos = self.enrich_videos_with_detail(page_videos)
            except BilibiliCrawlerError as exc:
                self.record_failed_page(mid, page_number, exc)
                progress.update(1)
                if self.config.stop_on_page_error:
                    progress.close()
                    raise
                continue

            if not page_videos:
                progress.update(1)
                break

            for video in page_videos:
                bvid = video.get("bvid")
                if bvid and bvid in seen_bvids:
                    continue
                if bvid:
                    seen_bvids.add(bvid)
                videos.append(video)

            progress.update(1)

        progress.close()
        return videos

    def rerun_failed_pages(self, failed_pages_file: str | Path | None = None) -> list[dict[str, Any]]:
        path = Path(failed_pages_file or self.config.failed_pages_file)
        entries = self.read_failed_pages(path)
        if not entries:
            return []

        self.ensure_logged_in()
        videos: list[dict[str, Any]] = []
        seen_pages: set[tuple[str, int]] = set()

        for entry in tqdm(entries, desc="Rerun failed pages", unit="page"):
            mid = str(entry.get("mid", "")).strip()
            page_number = self.to_int(entry.get("page_number"))
            if not mid or page_number <= 0:
                continue
            key = (mid, page_number)
            if key in seen_pages:
                continue
            seen_pages.add(key)

            self.sleep_between_pages()
            try:
                self.update_referer(mid)
                page_data = self.fetch_video_page(mid=mid, page_number=page_number)
                page_videos = self.parse_videos(page_data, fallback_mid=mid)
                videos.extend(self.enrich_videos_with_detail(page_videos))
            except BilibiliCrawlerError as exc:
                self.record_failed_page(mid, page_number, exc)

        return videos

    def update_referer(self, mid: str) -> None:
        self.session.headers["Referer"] = f"https://space.bilibili.com/{mid}/video"

    def warm_up_space_page(self, mid: str) -> None:
        try:
            self.session.get(
                f"https://space.bilibili.com/{mid}/video",
                timeout=self.config.timeout_seconds,
            )
            time.sleep(random.uniform(1.0, 3.0))
        except requests.RequestException:
            return

    def sleep_between_pages(self) -> None:
        delay = self.config.request_interval_seconds + random.uniform(
            0,
            max(0.0, self.config.request_interval_jitter_seconds),
        )
        time.sleep(delay)

    def sleep_between_details(self) -> None:
        delay = self.config.detail_request_interval_seconds + random.uniform(
            0,
            max(0.0, self.config.detail_request_interval_jitter_seconds),
        )
        time.sleep(delay)

    def fetch_video_page(self, mid: str, page_number: int) -> dict[str, Any]:
        params = {
            "mid": mid,
            "pn": page_number,
            "ps": self.config.page_size,
            "tid": self.config.tid,
            "keyword": self.config.keyword,
            "order": self.config.order,
            "platform": "web",
            "web_location": "1550101",
            "order_avoided": "true",
        }
        return self.request_json(self.space_video_api, params=self.sign_wbi_params(params))

    def fetch_video_detail(self, bvid: str) -> dict[str, Any]:
        return self.request_json(self.video_detail_api, params={"bvid": bvid})

    def enrich_videos_with_detail(self, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.config.fetch_video_detail:
            return videos

        for index, video in enumerate(videos):
            bvid = video.get("bvid")
            if not bvid:
                continue
            if index > 0:
                self.sleep_between_details()
            try:
                detail_data = self.fetch_video_detail(str(bvid))
                self.apply_video_detail(video, detail_data.get("data", {}))
            except BilibiliCrawlerError as exc:
                if not self.config.continue_on_detail_error:
                    raise
                video["detail_error"] = str(exc)
        return videos

    @staticmethod
    def apply_video_detail(video: dict[str, Any], detail: dict[str, Any]) -> None:
        stat = detail.get("stat", {})
        owner = detail.get("owner", {})

        video.update(
            {
                "like_count": BilibiliCrawler.to_int(stat.get("like")),
                "coin_count": BilibiliCrawler.to_int(stat.get("coin")),
                "favorite_count": BilibiliCrawler.to_int(stat.get("favorite")),
                "share_count": BilibiliCrawler.to_int(stat.get("share")),
                "danmaku_count": BilibiliCrawler.to_int(stat.get("danmaku")),
                "reply_count": BilibiliCrawler.to_int(stat.get("reply")),
                "copyright": detail.get("copyright", ""),
                "category_id": detail.get("tid", ""),
                "category_name": detail.get("tname", ""),
                "owner_name": owner.get("name", ""),
                "owner_mid": owner.get("mid", ""),
            }
        )

        if detail.get("duration"):
            video["duration_seconds"] = BilibiliCrawler.to_int(detail.get("duration"))
        if stat.get("view") is not None:
            video["view_count"] = BilibiliCrawler.to_int(stat.get("view"))
        if stat.get("reply") is not None:
            video["comment_count"] = BilibiliCrawler.to_int(stat.get("reply"))

    def sign_wbi_params(self, params: dict[str, Any]) -> dict[str, Any]:
        mixin_key = self.get_mixin_key()
        signed_params = dict(params)
        signed_params["wts"] = int(time.time())

        clean_params = {
            key: re.sub(r"[!'()*]", "", str(value))
            for key, value in signed_params.items()
            if value is not None
        }
        query = urlencode(dict(sorted(clean_params.items())))
        signed_params["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode("utf-8")).hexdigest()
        return signed_params

    def get_mixin_key(self) -> str:
        if self._mixin_key is not None:
            return self._mixin_key

        nav_data = self.request_json(self.nav_api)
        wbi_img = nav_data.get("data", {}).get("wbi_img", {})
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        if not img_url or not sub_url:
            raise BilibiliCrawlerError("获取 WBI 密钥失败，请检查 Cookie 是否有效或接口是否变化。")

        raw_key = self.extract_key_from_url(img_url) + self.extract_key_from_url(sub_url)
        self._mixin_key = "".join(raw_key[index] for index in MIXIN_KEY_ENC_TAB)[:32]
        return self._mixin_key

    @staticmethod
    def extract_key_from_url(url: str) -> str:
        filename = url.rsplit("/", 1)[-1]
        return filename.split(".", 1)[0]

    def request_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                code = payload.get("code")
                if code != 0:
                    message = payload.get("message", "unknown error")
                    if code == -101:
                        raise BilibiliCrawlerError("账号未登录或 Cookie 已失效。请重新复制浏览器 Cookie。")
                    if code in {-352, -412}:
                        raise BilibiliCrawlerError(
                            f"请求可能触发风控 code={code}, message={message}。"
                            "建议增大 request_interval_seconds，并稍后再试。"
                        )
                    raise BilibiliCrawlerError(
                        f"Bilibili 接口返回错误 code={code}, message={message}"
                    )
                return payload
            except (requests.RequestException, ValueError, BilibiliCrawlerError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2 * attempt, 8))

        raise BilibiliCrawlerError(f"请求失败：{last_error}") from last_error

    def parse_videos(self, page_data: dict[str, Any], fallback_mid: str) -> list[dict[str, Any]]:
        vlist = page_data.get("data", {}).get("list", {}).get("vlist", [])
        videos = []
        for item in vlist:
            bvid = item.get("bvid", "")
            created_timestamp = int(item.get("created") or 0)
            duration = item.get("length", "")
            videos.append(
                {
                    "bvid": bvid,
                    "aid": item.get("aid", ""),
                    "title": item.get("title", ""),
                    "publish_time": self.format_timestamp(created_timestamp),
                    "publish_timestamp": created_timestamp,
                    "video_url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                    "view_count": self.to_int(item.get("play")),
                    "comment_count": self.to_int(item.get("comment")),
                    "duration": duration,
                    "duration_seconds": self.duration_to_seconds(duration),
                    "description": item.get("description", ""),
                    "cover_url": item.get("pic", ""),
                    "author": item.get("author", ""),
                    "mid": str(item.get("mid") or fallback_mid),
                    "like_count": "",
                    "coin_count": "",
                    "favorite_count": "",
                    "share_count": "",
                    "danmaku_count": "",
                    "reply_count": "",
                    "copyright": "",
                    "category_id": "",
                    "category_name": "",
                    "owner_name": "",
                    "owner_mid": "",
                    "detail_error": "",
                }
            )
        return videos

    @staticmethod
    def get_total_count(page_data: dict[str, Any], fallback: int) -> int:
        page_info = page_data.get("data", {}).get("page", {})
        return int(page_info.get("count") or fallback)

    def calculate_total_pages(self, total_count: int) -> int:
        if total_count <= 0:
            return 1
        return max(1, math.ceil(total_count / self.config.page_size))

    def record_failed_page(self, mid: str, page_number: int, error: Exception) -> None:
        path = Path(self.config.failed_pages_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "mid": str(mid),
            "page_number": int(page_number),
            "error": str(error),
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def read_failed_pages(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise BilibiliCrawlerError(f"失败页记录文件不存在：{path}")

        entries = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    @staticmethod
    def format_timestamp(timestamp: int) -> str:
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def duration_to_seconds(duration: str) -> int:
        if not duration:
            return 0
        parts = duration.split(":")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return 0
        if len(numbers) == 2:
            minutes, seconds = numbers
            return minutes * 60 + seconds
        if len(numbers) == 3:
            hours, minutes, seconds = numbers
            return hours * 3600 + minutes * 60 + seconds
        return 0

    @staticmethod
    def to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def save(self, videos: list[dict[str, Any]], name_prefix: str = "bilibili_videos") -> list[Path]:
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{name_prefix}_{timestamp}"
        output_format = self.config.output_format.lower()
        saved_files: list[Path] = []

        if output_format in {"csv", "both"}:
            saved_files.append(self.save_csv(videos, output_dir / f"{base_name}.csv"))
        if output_format in {"json", "both"}:
            saved_files.append(self.save_json(videos, output_dir / f"{base_name}.json"))
        if output_format not in {"csv", "json", "both"}:
            raise BilibiliCrawlerError("output_format 只能是 csv、json 或 both。")

        return saved_files

    @staticmethod
    def save_csv(videos: list[dict[str, Any]], output_path: Path) -> Path:
        fieldnames = [
            "mid",
            "author",
            "bvid",
            "aid",
            "title",
            "publish_time",
            "publish_timestamp",
            "video_url",
            "view_count",
            "comment_count",
            "like_count",
            "coin_count",
            "favorite_count",
            "share_count",
            "danmaku_count",
            "reply_count",
            "duration",
            "duration_seconds",
            "description",
            "cover_url",
            "category_id",
            "category_name",
            "copyright",
            "owner_name",
            "owner_mid",
            "detail_error",
        ]
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(videos)
        return output_path

    @staticmethod
    def save_json(videos: list[dict[str, Any]], output_path: Path) -> Path:
        with output_path.open("w", encoding="utf-8") as file:
            json.dump(videos, file, ensure_ascii=False, indent=2)
        return output_path


def split_mids(value: str) -> list[str]:
    return [mid.strip() for mid in value.split(",") if mid.strip()]
