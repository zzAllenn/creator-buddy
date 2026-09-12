# 小红书热门笔记输入输出

统一入口 `scripts/fetch_xhs_hot_articles.py`，Python 3.9+ 标准库，无第三方依赖。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--provider` | `auto` | 已配置 RNOTE_API_KEY 时选 RNote，否则红狐；可显式 rnote/redfox |
| `--keyword` | 必填 | RNote 非空单词组；红狐还支持空词全站榜/逗号多词 |
| `--max-items` | 10 | JSON/HTML 最多输出条数 |
| `--output-format` | json | json/html；stdout 始终为 JSON |
| `--output-file` | 无 | 显式传入时额外写 HTML；无此参数且 format=json 时不写文件 |
| `--page-num` | 1 | 当前页，RNote 续页必须携带两个会话参数 |
| `--pages` | 1 | RNote 连续获取页数 |
| `--sort-type` | popularity_descending | RNote 排序，取值见 data_sources.md |
| `--time-filter` | 一周内 | RNote 仅支持不限/一天内/一周内/半年内 |
| `--note-type` | 不限 | RNote 中文类型枚举 |
| `--search-id / --search-session-id` | 空 | RNote 续页时原样传回 |
| `--with-related` | false | RNote 额外查询推荐词 |
| `--start-date / --end-date` | 无 | 仅红狐，yyyy-MM-dd |
| `--page-size` | 50（红狐） | 仅红狐，1~50 |
| `--max-retries` | 3 | 仅红狐；RNote 不自动重试 |
| `--debug` | false | stderr 调试信息；RNote 不输出凭证/会话/响应正文 |

## 统一 JSON

- `source`：rnote / redfox，旧红狐文件没有该字段时分析器按 redfox 处理。
- `keyword`、`total`、`pageNum`、`pageSize`、`isFullSite`：查询回显；total 为取得的样本数，items 受 max-items 截断。RNote pageSize 为 null，不代表 0 条。
- `items[]`：主笔记；`latestHotArticles[]`：红狐推荐笔记；`relatedSearches[]`：供应商返回的拓词。
- RNote 附加 `timeFilter`、`sortType`、`noteType`、`pagesFetched`、`nextPage`、`searchId`、`searchSessionId`、`warnings`、`dataNotice`。只有 nextPage 有效且两个会话值齐全时才能续页。

| items 字段 | 说明 |
|---|---|
| noteId / title / desc | 笔记 ID、标题、摘要 |
| noteLink | 原始完整笔记 URL；未提供时空串，不能自行通过 ID 拼接 |
| authorId / authorNickname / authorLink | 作者及主页 |
| authorFans | 粉丝数，缺失为 null；红狐保留原模糊展示 |
| createTime | 原始发布时间，未返回时缺失，不从 ID 推断 |
| likedCount / collectedCount / commentsCount / sharedCount | 赞/藏/评/分享；RNote 保留数值或近似字符串，缺失为 null |
| interactiveCount | 上游总互动数；RNote 仅在四项均为精确数值时可求和，缺字段不当零 |
| totalScore / relevanceScore / popularityScore / recencyScore | 仅红狐关键词搜索提供，RNote 不输出伪造评分 |

## 对比分析

`compare_sets.py` 同时接受 RNote/红狐 `items[]` 和怪壳 `results[]`，按 source 区分路线。缺失互动值不参与中位数和最高值；缺失赞藏评时不输出不完整的比值。粉丝样本不足时，小号占比只以已知粉丝样本为分母。

不同供应商样本口径不同，不能直接比较绝对互动量；近似字符串参与离线统计时只得到近似结果。RNote 搜索不代表全站排名，也不保证所有结果达到 1000+ 互动。

## 接口依据

[RNote OpenAPI](https://rnote.dev/openapi.json) 与 [文档](https://rnote.dev/docs)，核对日期 2026-09-12。卡片完整字段没有公开响应 schema，适配已覆盖常见嵌套/扁平形态，仍需配置 Key 后用真实返回确认。
