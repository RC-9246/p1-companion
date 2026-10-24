import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_p1_qq_style.plain import render
class QQPlainTests(unittest.TestCase):
 def test_markup_and_links(self):
  actual=render('# 标题\n\n**认真**，*温和*，~~旧的~~ [官网](https://example.com/a_b?q=x*y)\n\n> 引用')[0]
  self.assertEqual(actual,'标题\n认真，温和，旧的 官网（https://example.com/a_b?q=x*y）\n\n引用')
 def test_code_literals_and_arithmetic(self):
  body='def f(x):\n    return x * 2  # 说明\n\n# 原样'
  text,structured=render('```python\n'+body+'\n```')
  self.assertEqual(text,body);self.assertTrue(structured)
  for t in ('a*b*c','2 * 3 = 6','file_name.py','https://example.com/a_b?q=x*y','1+2=3'):
   self.assertEqual(render(t)[0],t)
 def test_lists_and_tables(self):
  text,structured=render('1. 第一\n2. 第二\n\n| 名称 | 值 |\n|---|---|\n| a | 2 |')
  self.assertEqual(text,'1、第一\n2、第二\n名称：a；值：2');self.assertTrue(structured)
 def test_image_becomes_reference_not_native_payload(self):
  self.assertEqual(render('![伙伴](https://example.com/a.jpg)')[0],'伙伴：https://example.com/a.jpg')
 def test_accidental_reasoning_removed(self):
  self.assertEqual(render('<think>内部推理</think>**嗯**')[0],'嗯')
 def test_plain_chinese_unchanged(self):
  for text in ('嗯，回来啦','真的吗？','你这么说，我也挺高兴','a_b_c，20%','嗯……'):
   self.assertEqual(render(text)[0],text)
