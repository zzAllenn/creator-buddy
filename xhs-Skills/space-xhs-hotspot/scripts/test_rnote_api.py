"""离线契约测试；包含按真实响应字段构造的匿名 fixture。"""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import compare_sets
import fetch_xhs_hot_articles as cli
import rnote_api


def note(note_id='a', **stats):
    return {'id': note_id, 'model_type': 'note', 'note_card': {
        'display_title': '通勤穿搭', 'user': {'nickname': '作者'},
        'interact_info': stats}}


def page(items, next_page=None):
    return ({'search_id': 'search', 'search_session_id': 'session', 'next_page': next_page},
            {'items': items})


class RNoteTests(unittest.TestCase):
    def test_live_note_shape(self):
        raw = {'model_type': 'note', 'note': {
            'id': '6aa12e500000000028031607', 'title': '测试笔记', 'desc': '测试摘要',
            'xsec_token': 'fixture+/token=',
            'user': {'userid': 'fixture-author', 'nickname': '测试作者'},
            'timestamp': 1788948048,
            'images_list': [{'url': '', 'url_size_large': 'https://example.com/cover.jpg'}],
            'liked_count': 8222, 'collected_count': 3931,
            'comments_count': 70, 'shared_count': 354,
        }}
        result = rnote_api.normalize_item(raw)
        self.assertEqual(result['id'], '6aa12e500000000028031607')
        self.assertEqual(result['authorId'], 'fixture-author')
        self.assertEqual(result['interactiveCount'], 12577)
        self.assertEqual(result['createTime'], '2026-09-09T10:00:48+00:00')
        self.assertEqual(result['cover'], 'https://example.com/cover.jpg')
        self.assertIsNone(result['authorFans'])
        self.assertEqual(
            result['shareInfoLink'],
            'https://www.xiaohongshu.com/explore/6aa12e500000000028031607'
            '?xsec_token=fixture%2B%2Ftoken%3D&xsec_source=pc_search')

    def test_note_url_requires_valid_id_and_token(self):
        self.assertEqual(rnote_api.build_note_url('invalid', 'token'), '')
        self.assertEqual(rnote_api.build_note_url('6aa12e500000000028031607', ''), '')

    def test_invalid_timestamp_is_missing(self):
        self.assertIsNone(rnote_api.publish_time({'timestamp': 1e100}))
        self.assertIsNone(rnote_api.publish_time({'timestamp': True}))

    def test_request_contract_and_auth(self):
        payload = {'success': True, 'data': {'data': {'items': []}}}
        with patch.dict(os.environ, {'RNOTE_API_KEY': 'test-only-key'}), patch(
                'urllib.request.urlopen', return_value=io.StringIO(json.dumps(payload))) as call:
            rnote_api.request('search/notes', {'keyword': '通勤穿搭', 'time_filter': '一周内'})
        req = call.call_args.args[0]
        self.assertEqual(req.get_header('X-api-key'), 'test-only-key')
        self.assertEqual(req.get_header('User-agent'), 'creator-buddy/1.0 (RNote API client)')
        self.assertEqual(req.get_method(), 'GET')
        self.assertIn('/api/v2/crawler/search/notes?', req.full_url)
        self.assertNotIn('test-only-key', req.full_url)

    def test_http_error_does_not_retry_or_echo_body(self):
        error = urllib.error.HTTPError('https://rnote.dev', 401, 'unauthorized', {},
                                       io.BytesIO(b'test-only-secret'))
        with patch.dict(os.environ, {'RNOTE_API_KEY': 'test-only-key'}), patch(
                'urllib.request.urlopen', side_effect=error) as call:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as caught:
                rnote_api.request('search/notes', {'keyword': 'test'})
        call.assert_called_once()
        self.assertNotIn('test-only-secret', str(caught.exception))

    def test_business_error_and_invalid_schema(self):
        for body in ({'success': False}, {'success': True, 'data': {}}):
            with patch.dict(os.environ, {'RNOTE_API_KEY': 'test-only-key'}), patch(
                    'urllib.request.urlopen', return_value=io.StringIO(json.dumps(body))):
                with self.assertRaises(RuntimeError):
                    rnote_api.request('search/notes', {'keyword': 'test'})

    def test_missing_fields_and_scores_are_not_zero(self):
        with patch.object(rnote_api, 'request', return_value=page([note(liked_count='5000+')])):
            result = cli.format_as_json(rnote_api.fetch_rnote_notes('通勤'))
        item = result['items'][0]
        self.assertEqual(item['likedCount'], '5000+')
        self.assertIsNone(item['interactiveCount'])
        self.assertIsNone(item['authorFans'])
        self.assertEqual(item['noteLink'], '')
        self.assertNotIn('totalScore', item)
        self.assertEqual(result['source'], 'rnote')

    def test_zero_and_complete_counts_and_original_link(self):
        raw = note(liked_count='0', collected_count='20', comment_count='3', share_count='1')
        raw['note_url'] = 'https://www.xiaohongshu.com/explore/a?xsec_token=synthetic&x=1'
        result = rnote_api.normalize_item(raw)
        self.assertEqual(result['interactiveCount'], 24)
        self.assertEqual(result['likedCount'], 0)
        self.assertEqual(result['shareInfoLink'], raw['note_url'])

    def test_pagination_carries_sessions_and_deduplicates(self):
        with patch.object(rnote_api, 'request', side_effect=[
                page([note('a'), {'model_type': 'recommend', 'id': 'x'}], 2),
                page([note('a'), note('b')])]) as call:
            result = rnote_api.fetch_rnote_notes('通勤', pages=3)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['pagesFetched'], 2)
        params = call.call_args_list[1].args[1]
        self.assertEqual(params['page'], 2)
        self.assertEqual(params['search_id'], 'search')
        self.assertEqual(params['search_session_id'], 'session')

    def test_pagination_requires_both_sessions(self):
        with patch.object(rnote_api, 'request') as call:
            with self.assertRaises(ValueError):
                rnote_api.fetch_rnote_notes('通勤', page_num=2, search_id='search')
        call.assert_not_called()

    def test_missing_session_stops_automatic_pagination(self):
        with patch.object(rnote_api, 'request', return_value=(
                {'next_page': 2}, {'items': [note()]})) as call:
            result = rnote_api.fetch_rnote_notes('通勤', pages=2)
        call.assert_called_once()
        self.assertTrue(any('缺少搜索会话' in w for w in result['warnings']))

    def test_unknown_nonempty_response_is_not_zero_sample(self):
        with patch.object(rnote_api, 'request', return_value=page([{'unexpected': 'shape'}])):
            with self.assertRaisesRegex(RuntimeError, '无可识别笔记'):
                rnote_api.fetch_rnote_notes('通勤')

    def test_recommend_failure_preserves_notes(self):
        with patch.object(rnote_api, 'request', side_effect=[page([note()]), RuntimeError('fail')]):
            result = rnote_api.fetch_rnote_notes('通勤', with_related=True)
        self.assertEqual(result['total'], 1)
        self.assertTrue(any('拓词请求失败' in w for w in result['warnings']))

    def test_auto_selection_and_redfox_compatibility(self):
        with patch.dict(os.environ, {'RNOTE_API_KEY': 'test-only-key'}), patch.object(
                cli, 'fetch_rnote_notes', return_value={'source': 'rnote'}) as fetch:
            self.assertEqual(cli.fetch_xhs_hot_notes('test')['source'], 'rnote')
            fetch.assert_called_once()
        with patch.object(cli, 'fetch_redfox_notes', return_value={'articles': []}) as fetch:
            self.assertEqual(cli.fetch_xhs_hot_notes('test', provider='redfox')['source'], 'redfox')
            self.assertEqual(fetch.call_args.args[-1], 50)

    def test_unsupported_filters_fail_before_network(self):
        with patch.object(cli, 'fetch_rnote_notes') as fetch:
            for args in ({'start_date': '2026-09-01'}, {'end_date': '2026-09-10'}, {'page_size': 20}):
                with self.assertRaises(ValueError):
                    cli.fetch_xhs_hot_notes('test', provider='rnote', **args)
            fetch.assert_not_called()

    def test_comparison_ignores_missing_metrics(self):
        with patch.object(rnote_api, 'request', return_value=page([note(liked_count=12)])):
            data = rnote_api.fetch_rnote_notes('通勤')
        normalized, route = compare_sets.normalize(cli.format_as_json(data))
        summary = compare_sets.summarize('通勤', normalized, route, 20)
        self.assertEqual(route, 'rnote')
        self.assertIsNone(summary['interactive_median'])
        self.assertIsNone(summary['collect_like_ratio'])
        self.assertFalse(summary['fans_known'])
        self.assertNotIn('0 | 0', compare_sets.render([summary], 'sector'))

    def test_redfox_scores_stay_and_rnote_html_has_no_scores(self):
        data = {'keyword': '通勤', 'articles': [{'id': 'a', 'title': 'test', 'likedCount': 12,
                'totalScore': 10}], 'source': 'redfox'}
        self.assertEqual(cli.format_as_json(data)['items'][0]['totalScore'], 10)
        data['source'] = 'rnote'
        html = cli.format_as_html(data)
        self.assertNotIn('相关性 0', html)
        self.assertIn('RNote 搜索样本', html)
        self.assertNotIn('explore/a', html)


if __name__ == '__main__':
    unittest.main()
