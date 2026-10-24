from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/mcp'))
from search_policy import query,public_url

class SearchPrivacyTests(unittest.TestCase):
    def test_public_topic(self):
        self.assertEqual(query('CO2 储能 原理'),'CO2 储能 原理')
    def test_private_queries_rejected(self):
        for value in ('我的邮箱 a@b.example','token=abc','QQ号 12345678','password hello','https://site.example/path','x'*101):
            with self.assertRaises(ValueError): query(value)
    def test_result_link_does_not_authorize_private_navigation(self):
        for value in ('http://example.com','https://127.0.0.1/','https://169.254.169.254/','https://localhost/','https://host.internal','https://user:password@example.com'):
            self.assertFalse(public_url(value),value)
        self.assertTrue(public_url('https://docs.python.org/3/'))

if __name__=='__main__':unittest.main()
