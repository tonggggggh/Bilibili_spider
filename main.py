from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from bilibili_crawler import BilibiliCrawler, CrawlerConfig, split_mids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="爬取 Bilibili 指定 UP 主公开投稿视频信息")
    parser.add_argument(
        "--config",
        default="config.json",
        help="配置文件路径，默认 config.json",
    )
    parser.add_argument(
        "--mid",
        help="目标 UP 主 mid。支持逗号分隔多个 mid，会覆盖 config.json 中的 up_mid/up_mids",
    )
    parser.add_argument(
        "--mids",
        nargs="+",
        help="目标 UP 主 mid 列表，会覆盖 config.json 中的 up_mid/up_mids",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="不请求视频详情接口，只保存投稿列表接口字段",
    )
    parser.add_argument(
        "--rerun-failed",
        nargs="?",
        const="",
        help="只重跑失败页记录。可传入失败页 JSONL 文件路径，默认使用 config.json 中的 failed_pages_file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = CrawlerConfig.from_file(args.config)

    cli_mids = []
    if args.mid:
        cli_mids.extend(split_mids(args.mid))
    if args.mids:
        cli_mids.extend(args.mids)
    if cli_mids:
        config = replace(config, up_mid="", up_mids=cli_mids)
    if args.no_detail:
        config = replace(config, fetch_video_detail=False)

    crawler = BilibiliCrawler(config)
    if args.rerun_failed is not None:
        failed_file = args.rerun_failed or config.failed_pages_file
        videos = crawler.rerun_failed_pages(Path(failed_file))
        saved_files = crawler.save(videos, name_prefix="bilibili_failed_rerun")
    else:
        videos = crawler.crawl_all()
        saved_files = crawler.save(videos)

    print(f"抓取完成，共 {len(videos)} 条视频。")
    for path in saved_files:
        print(f"已保存：{path}")


if __name__ == "__main__":
    main()
