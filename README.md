<<<<<<< HEAD
# Bilibili UP 投稿视频信息爬取

一个用于爬取 Bilibili UP 主公开投稿视频信息的 Python 工具。支持单个或多个 UP 主批量爬取，可补充视频详情数据，并能记录失败页用于后续重跑。

> 只处理公开接口返回的数据，不绕过付费、权限或平台限制。请控制请求频率，合理使用自己的账号 Cookie。

## 功能

- 支持单个 UP 主和多个 UP 主批量爬取
- 获取投稿列表字段：标题、发布时间、链接、播放量、评论数、时长等
- 可调用视频详情接口补充：点赞、投币、收藏、分享、弹幕、分区等字段
- 自动生成 Bilibili WBI 请求签名
- 支持 CSV、JSON 或同时导出
- 支持固定间隔 + 随机等待，降低连续高频请求
- 自动记录失败页到 JSONL 文件
- 支持按失败页记录重跑

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制示例配置：

```bash
copy config.example.json config.json
```

编辑 `config.json`：

```json
{
  "up_mids": ["123456789", "987654321"],
  "cookies_str": "写入您的cookies",
  "bili_jct": "cookie中的bili_jct"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `up_mid` | 单个 UP 主 mid，兼容旧配置 |
| `up_mids` | 多个 UP 主 mid 列表 |
| `cookies_str` | 从浏览器复制的完整 Cookie |
| `bili_jct` | Cookie 中的 `bili_jct` 值 |
| `fetch_video_detail` | 是否请求视频详情接口补充点赞、投币、收藏等字段 |
| `request_interval_seconds` | 投稿列表翻页基础等待秒数 |
| `request_interval_jitter_seconds` | 投稿列表翻页随机增加秒数 |
| `detail_request_interval_seconds` | 视频详情请求基础等待秒数 |
| `detail_request_interval_jitter_seconds` | 视频详情请求随机增加秒数 |
| `failed_pages_file` | 失败页记录文件 |
| `stop_on_page_error` | 单页失败时是否立即停止 |

Cookie 等同于登录凭据，不要提交到 GitHub。项目的 `.gitignore` 默认忽略 `config.json` 和输出目录。

## 如何获取 Cookie

1. 在浏览器登录 Bilibili。
2. 打开任意 Bilibili 页面。
3. 打开开发者工具，进入 Network。
4. 刷新页面，点开任意请求。
5. 在 Request Headers 中复制完整 `Cookie`。
6. 把完整 Cookie 填入 `config.json` 的 `cookies_str`。
7. 从 Cookie 中找到 `bili_jct=...`，把值单独填入 `bili_jct`。

## 使用

按配置文件爬取：

```bash
python main.py --config config.json
```

临时指定单个 UP 主：

```bash
python main.py --mid 123456789
```

临时指定多个 UP 主：

```bash
python main.py --mids 123456789 987654321
```

或逗号分隔：

```bash
python main.py --mid 123456789,987654321
```

不请求详情接口，只抓投稿列表：

```bash
python main.py --no-detail
```

重跑失败页：

```bash
python main.py --rerun-failed
```

指定失败页文件重跑：

```bash
python main.py --rerun-failed outputs/failed_pages.jsonl
```

## 输出字段

| 字段 | 说明 |
| --- | --- |
| `mid` | UP 主 ID |
| `author` | 投稿列表返回的作者昵称 |
| `bvid` | 视频 BV 号 |
| `aid` | 视频 AV 号 |
| `title` | 视频标题 |
| `publish_time` | 发布时间 |
| `video_url` | 视频链接 |
| `view_count` | 播放量 |
| `comment_count` | 评论数 |
| `like_count` | 点赞数，来自详情接口 |
| `coin_count` | 投币数，来自详情接口 |
| `favorite_count` | 收藏数，来自详情接口 |
| `share_count` | 分享数，来自详情接口 |
| `danmaku_count` | 弹幕数，来自详情接口 |
| `duration` | 投稿列表中的时长文本 |
| `duration_seconds` | 视频时长秒数 |
| `category_name` | 视频分区 |
| `detail_error` | 单个视频详情请求失败时的错误信息 |

## 失败页记录

当某一页投稿列表请求失败时，脚本会写入：

```text
outputs/failed_pages.jsonl
```

每行是一条 JSON，包含 `mid`、`page_number`、`error` 和 `recorded_at`。后续可用 `--rerun-failed` 只重跑这些页。

## 频率建议

默认配置：

```json
"request_interval_seconds": 10,
"request_interval_jitter_seconds": 5,
"detail_request_interval_seconds": 3,
"detail_request_interval_jitter_seconds": 2
```

也就是投稿列表每页间隔约 10 到 15 秒，视频详情每条间隔约 3 到 5 秒。目标视频很多时，建议增大间隔，或设置 `max_pages` 分批运行。

任何脚本都不能保证账号绝对不会触发平台风控；低频、分批、不要并发运行，是更稳妥的使用方式。
=======
# Bilibili_spider
爬取多个UP主发布的视频标题、播放量和发布时间等信息
>>>>>>> origin/main

