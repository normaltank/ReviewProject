"""Public generation boundary regression: don't overwrite duplicate model fields."""
import json
import unittest
import test_attention_api_format_repair as fixture
from reviewproto.core import digest
from reviewproto.local_io import encoded

def duplicate(value):
    op=value['opinions'][0]
    return ('{"opinions":[{"summary":'+json.dumps(op['summary'],ensure_ascii=False)+
            ',"facets":'+json.dumps(op['facets'],ensure_ascii=False)+
            ',"facets":[]}],"relations":[],"unprocessed":[]}')

class DuplicateContent(unittest.TestCase):
    def test_duplicate_field_gets_one_repair_instead_of_empty_overwrite(self):
        bad=duplicate(fixture.B)
        run,sent=fixture.FormatRepair().execute([
            fixture.reply(bad),fixture.reply(fixture.B),fixture.reply({'function':'实质评价'})])
        self.assertEqual(len(sent),3,'duplicate output must reach the existing one-repair boundary')
        self.assertEqual(len(run['patch']['edits']),1)
        self.assertEqual(run['status'],'partial')
        self.assertEqual(run['format_repair_count'],1)
        first=run['calls'][0]
        self.assertEqual(first['status'],'failed')
        self.assertEqual(first['error'],'E_ATTENTION_JSON_FORMAT')
        self.assertEqual(first['format_diagnostic']['kind'],'duplicate_key')
        self.assertEqual(first['format_diagnostic']['field'],'facets')
        self.assertEqual(sent[1]['messages'][2]['content'],bad)
        self.assertEqual(sent[0]['messages'][:2],sent[1]['messages'][:2])
        self.assertEqual(sent[0]['max_tokens'],sent[1]['max_tokens'])
        self.assertEqual(run['calls'][1]['purpose'],'format_repair')
        repair=run['calls'][1]
        self.assertEqual(repair['parent_call_id'],first['call_id'])
        for call,expected in zip(run['calls'][:2],[bad,json.dumps(fixture.B,ensure_ascii=False)]):
            self.assertEqual(call['parsed_response']['choices'][0]['message']['content'],expected)
            self.assertEqual(call['usage'],fixture.USAGE)
            self.assertEqual(call['response_hash'],digest(encoded(call['response'])))
        self.assertEqual(run['unprocessed'],[])

    def test_escaped_same_field_is_also_duplicate(self):
        bad=duplicate(fixture.B).replace('"facets":[]','"fac\\u0065ts":[]')
        run,sent=fixture.FormatRepair().execute([
            fixture.reply(bad),fixture.reply(fixture.B),fixture.reply({'function':'实质评价'})])
        self.assertEqual(len(sent),3)
        self.assertEqual(run['calls'][0]['format_diagnostic']['field'],'facets')
        self.assertEqual(len(run['patch']['edits']),1)

    def test_second_duplicate_stops_and_retains_unprocessed_record(self):
        bad=duplicate(fixture.B)
        run,sent=fixture.FormatRepair().execute([fixture.reply(bad),fixture.reply(bad)])
        self.assertEqual(len(sent),2)
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['patch']['edits'],[])
        self.assertTrue(run['unprocessed'])
        self.assertEqual(run['format_repair_count'],1)
        record=run['snapshot']['records'][0]
        self.assertEqual([(item['record_id'],item['section_id']) for item in run['unprocessed']],
            [(record['record_id'],section['section_id']) for section in record['sections']])

    def test_unknown_usage_does_not_add_repair(self):
        run,sent=fixture.FormatRepair().execute([fixture.reply(duplicate(fixture.B),usage=None)])
        self.assertEqual(len(sent),1)
        self.assertEqual(run['format_repair_count'],0)
        self.assertEqual(run['status'],'failed')
        self.assertTrue(run['unprocessed'])
        self.assertIsNone(run['calls'][0]['usage'])
        record=run['snapshot']['records'][0]
        self.assertEqual([(item['record_id'],item['section_id']) for item in run['unprocessed']],
            [(record['record_id'],section['section_id']) for section in record['sections']])

if __name__=='__main__':unittest.main(verbosity=2)
