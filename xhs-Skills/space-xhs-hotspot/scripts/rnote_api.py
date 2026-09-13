"""RNote 搜索适配。缺失数据保留 None，不伪造评分或无 token 链接。"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


SORT_TYPES = ('general', 'time_descending', 'popularity_descending',
              'comment_descending', 'collect_descending')
TIME_FILTERS = ('不限', '一天内', '一周内', '半年内')
NOTE_TYPES = ('不限', '视频笔记', '普通笔记', '直播笔记')


def request(path, params, debug=False):
    key = os.environ.get('RNOTE_API_KEY', '').strip()
    if not key:
        raise ValueError('未找到 RNOTE_API_KEY 环境变量，请在本地配置后重试。')
    url = 'https://rnote.dev/api/v2/crawler/' + path
    req = urllib.request.Request(
        url + '?' + urllib.parse.urlencode(params),
        headers={'X-API-Key': key, 'Accept': 'application/json',
                 'User-Agent': 'creator-buddy/1.0 (RNote API client)'})
    if debug:
        print(f'RNote GET {path}（不输出凭证、会话或原始响应）', file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        # 按次计费接口不自动重试；不把服务端回显的凭证/原始内容打进日志。
        raise RuntimeError(f'RNote HTTP {exc.code}；未自动重试，请检查认证、余额或服务状态。') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('RNote 网络请求失败；未自动重试。') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('RNote 响应不是有效 JSON。') from None
    if not isinstance(body, dict) or body.get('success') is not True:
        raise RuntimeError('RNote 业务请求失败（success 非 true）；未自动重试。')
    envelope = body.get('data')
    if not isinstance(envelope, dict) or not isinstance(envelope.get('data'), dict):
        raise RuntimeError('RNote 响应结构变化：缺少 data.data 对象。')
    inner = envelope['data']
    if inner.get('success') is False or envelope.get('success') is False:
        raise RuntimeError('RNote 上游业务失败；未自动重试。')
    return envelope, inner


def first(obj, *names):
    return next((obj[n] for n in names if obj.get(n) is not None), None)


def count(value):
    """完整数值转为 int，1.2万/5000+ 等近似数值保留原值。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip().replace(',', '')
    return int(text) if text.isdigit() else (str(value) if text else None)


def publish_time(card):
    explicit = first(card, 'publish_time', 'time', 'create_time')
    if explicit is not None:
        return explicit
    timestamp = card.get('timestamp')
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def build_note_url(note_id, xsec_token):
    """把 RNote 搜索卡片中的 ID 和访问令牌转换为可打开的小红书链接。"""
    note_id = str(note_id or '').strip()
    xsec_token = str(xsec_token or '').strip()
    if not re.fullmatch(r'[0-9a-f]{24}', note_id) or not xsec_token:
        return ''
    query = urllib.parse.urlencode({
        'xsec_token': xsec_token,
        'xsec_source': 'pc_search',
    })
    return f'https://www.xiaohongshu.com/explore/{note_id}?{query}'


def normalize_item(item):
    if not isinstance(item, dict):
        return None
    model = first(item, 'model_type', 'modelType')
    if model and model not in ('note', 'normal', 'video'):
        return None
    card = first(item, 'note', 'note_card', 'noteCard') or item
    if not isinstance(card, dict):
        return None
    note_id = first(item, 'id', 'note_id') or first(card, 'note_id', 'id')
    title = first(card, 'display_title', 'title', 'desc')
    if not note_id or title is None:
        return None
    user = card.get('user') or {}
    stats = first(card, 'interact_info', 'interactInfo') or card
    if not isinstance(user, dict) or not isinstance(stats, dict):
        raise RuntimeError('RNote 笔记卡片结构变化：user/interact_info 非对象。')
    counters = {
        'likedCount': count(first(stats, 'liked_count', 'likedCount')),
        'collectedCount': count(first(stats, 'collected_count', 'collectedCount')),
        'commentsCount': count(first(stats, 'comment_count', 'comments_count', 'commentsCount')),
        'sharedCount': count(first(stats, 'share_count', 'shared_count', 'sharedCount')),
    }
    # 分享数不是所有搜索卡片都提供；缺少任一项时不把部分和冒充互动总数。
    total = count(first(stats, 'interact_count', 'interactiveCount'))
    if total is None and all(isinstance(v, int) for v in counters.values()):
        total = sum(counters.values())
    cover = card.get('cover') or {}
    cover_url = first(cover, 'url_default', 'url', 'url_pre') if isinstance(cover, dict) else cover
    images = card.get('images_list') or []
    if not cover_url and isinstance(images, list) and images and isinstance(images[0], dict):
        cover_url = images[0].get('url_size_large') or images[0].get('url')
    link = first(item, 'note_url', 'noteLink', 'share_url', 'url')
    link = link or first(card, 'note_url', 'noteLink', 'share_url', 'url')
    if not link:
        xsec_token = first(item, 'xsec_token', 'xsecToken')
        xsec_token = xsec_token or first(card, 'xsec_token', 'xsecToken')
        link = build_note_url(note_id, xsec_token)
    return {
        'id': str(note_id), 'title': str(title), 'desc': card.get('desc') or '',
        'authorId': first(user, 'user_id', 'userId', 'userid', 'id') or '',
        'authorNickname': first(user, 'nickname', 'nick_name') or '',
        'authorFans': count(first(user, 'fans', 'fans_count', 'fansCount')),
        'createTime': publish_time(card),
        'shareInfoLink': link or '', 'cover': cover_url or '',
        'interactiveCount': total, **counters,
    }


def fetch_rnote_notes(keyword, *, page_num=1, pages=1, sort_type='popularity_descending',
                      time_filter='一周内', note_type='不限', search_id='',
                      search_session_id='', with_related=False, debug=False):
    if not keyword.strip():
        raise ValueError('RNote 笔记搜索需要非空关键词；全站热门请显式选择 --provider redfox。')
    if page_num < 1 or pages < 1:
        raise ValueError('page-num 和 pages 必须大于 0。')
    if page_num > 1 and not (search_id and search_session_id):
        raise ValueError('RNote 翻页必须同时传 --search-id 和 --search-session-id。')
    if sort_type not in SORT_TYPES or time_filter not in TIME_FILTERS or note_type not in NOTE_TYPES:
        raise ValueError('RNote 排序、类型或时间筛选参数无效。')
    items, seen, warnings = [], set(), []
    current_page, next_page, pages_fetched = page_num, None, 0
    for index in range(pages):
        params = dict(keyword=keyword, page=current_page, sort_type=sort_type,
                      time_filter=time_filter, note_type=note_type)
        if search_id and search_session_id:
            params.update(search_id=search_id, search_session_id=search_session_id)
        envelope, inner = request('search/notes', params, debug)
        raw = inner.get('items')
        if not isinstance(raw, list):
            raise RuntimeError('RNote 响应结构变化：data.data.items 不是数组。')
        notes = [n for item in raw if (n := normalize_item(item)) is not None]
        if raw and not notes:
            raise RuntimeError('RNote 本页无可识别笔记卡片，不能据此判断赛道无数据。')
        for note in notes:
            if note['id'] not in seen:
                seen.add(note['id'])
                items.append(note)
        pages_fetched += 1
        search_id = envelope.get('search_id') or search_id
        search_session_id = envelope.get('search_session_id') or search_session_id
        next_page = envelope.get('next_page')
        if not next_page:
            break
        if not isinstance(next_page, int) or next_page <= current_page:
            warnings.append('next_page 无效，已停止翻页。')
            break
        if index + 1 < pages and not (search_id and search_session_id):
            warnings.append('缺少搜索会话参数，已停止翻页。')
            break
        current_page = next_page
    related = []
    if with_related:
        try:
            _, inner = request('search/recommend', {'keyword': keyword}, debug)
            if not isinstance(inner.get('items'), list):
                raise RuntimeError('推荐词响应缺少 items 数组。')
            related = inner['items']
        except RuntimeError as exc:
            warnings.append(f'拓词请求失败，保留笔记结果：{exc}')
    if any(not n['shareInfoLink'] for n in items):
        warnings.append('部分卡片缺少有效的 note ID 或 xsec_token，无法生成笔记链接。')
    if any(n['interactiveCount'] is None for n in items):
        warnings.append('部分互动字段缺失，总互动数不可计算；按请求排序解读样本。')
    return {
        'source': 'rnote', 'keyword': keyword, 'articles': items, 'total': len(items),
        'pageNum': page_num, 'pageSize': None, 'pagesFetched': pages_fetched,
        'nextPage': next_page, 'searchId': search_id, 'searchSessionId': search_session_id,
        'sortType': sort_type, 'timeFilter': time_filter, 'noteType': note_type,
        'relatedSearches': related, 'latestHotArticles': [], 'warnings': warnings,
        'dataNotice': 'RNote 搜索样本；无 1000+ 收录门槛、T+1 或固定 30 天库口径；缺失字段为 null。',
    }
