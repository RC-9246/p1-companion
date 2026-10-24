"""Restricted data/math experiments. Additional OS/container limits remain mandatory."""
import ast,json,sys
ALLOWED={'math','statistics','json','csv','re','collections','datetime','itertools'}
BLOCKED={'open','exec','eval','compile','input','globals','locals','vars','getattr','setattr','delattr','help','breakpoint','memoryview','__import__'}
def check(code):
 if not isinstance(code,str) or not 1<=len(code)<=12000:raise ValueError('code_limit')
 tree=ast.parse(code)
 for n in ast.walk(tree):
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   names=[a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [n.module or '']
   if any(x not in ALLOWED for x in names) or getattr(n,'level',0):raise ValueError('import_not_allowed')
  if isinstance(n,ast.Name) and (n.id in BLOCKED or n.id.startswith('_')):raise ValueError('name_not_allowed')
  if isinstance(n,ast.Attribute) and (n.attr.startswith('_') or n.attr in ('system','popen','read','write','load','dump')):raise ValueError('attribute_not_allowed')
 return tree
if __name__=='__main__':
 code=sys.stdin.read(12001);check(code);exec(compile(code,'<experiment>','exec'),{'__builtins__':__builtins__})
