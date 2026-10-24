"""Markdown AST to QQ text. No browser, network, file access or generated images."""
import re,secrets

STYLE='''[P1-QQ-PLAIN:v1]
QQ输出使用普通聊天文本，不使用Markdown粗体、斜体、标题井号、引用尖括号、反引号、删除线、表格竖线或链接包装语法。日常自然说话；确需比较或步骤时用短行及1、2、编号。网址直接写出。代码仅在确实需要时保持内容与缩进。不要输出括号舞台动作、人格分析、内心独白或情绪标签。'''

def parser():
    from markdown_it import MarkdownIt
    return MarkdownIt('commonmark',{'html':False,'linkify':False}).enable('table').enable('strikethrough')

def inline(tokens):
    out=[];links=[]
    for t in tokens or []:
        if t.type in ('text','code_inline'):out.append(t.content)
        elif t.type in ('softbreak','hardbreak'):out.append('\n')
        elif t.type=='link_open':links.append((len(out),t.attrGet('href') or ''))
        elif t.type=='link_close' and links:
            start,href=links.pop();label=''.join(out[start:])
            if href and label!=href:out.append('（'+href+'）')
        elif t.type=='image':
            label=inline(t.children);href=t.attrGet('src') or ''
            out.append((label+'：' if label else '图片链接：')+href)
        elif t.type in ('html_inline','html_block'):out.append(t.content)
    return ''.join(out)

def render(text):
    if not isinstance(text,str) or not text:return text,False
    # Reasoning should already be separate; strip an accidental leading block.
    text=re.sub(r'^\s*<(?:think|analysis)>[\s\S]*?</(?:think|analysis)>\s*','',text,flags=re.I)
    protected={};nonce=secrets.token_hex(6)
    def keep(value):
        key='\ue100'+nonce+str(len(protected))+'\ue101';protected[key]=value;return key
    # Bare arithmetic is literal, even where Markdown could parse a*b*c as emphasis.
    urls=[m.span() for m in re.finditer(r'https?://[^\s<>]+',text)]
    def math_literal(m):
        if any(m.start()<b and m.end()>a for a,b in urls):return m.group()
        return keep(m.group())
    text=re.sub(r'(?<![\w])(?:[A-Za-z0-9_.]+(?:[ \t]*[*/+=-][ \t]*[A-Za-z0-9_.]+)+)(?![\w])',math_literal,text)
    ts=parser().parse(text);out=[];lists=[];structured=False;i=0
    def newline():
        if out and not out[-1].endswith('\n'):out.append('\n')
    while i<len(ts):
        t=ts[i]
        if t.type=='table_open':
            structured=True;headers=[];rows=[];cells=[];header=False;i+=1
            while i<len(ts) and ts[i].type!='table_close':
                q=ts[i]
                if q.type=='thead_open':header=True
                elif q.type=='thead_close':header=False
                elif q.type=='tr_open':cells=[]
                elif q.type=='inline':cells.append(inline(q.children))
                elif q.type=='tr_close':
                    if header:headers=cells[:]
                    else:rows.append(cells[:])
                i+=1
            newline()
            for row in rows:
                if headers and len(headers)==len(row):out.append('；'.join(h+'：'+v for h,v in zip(headers,row))+'\n')
                else:out.append('；'.join(row)+'\n')
        elif t.type in ('fence','code_block'):
            structured=True;newline();out.append(keep(t.content.rstrip('\n')));out.append('\n')
        elif t.type=='inline':out.append(inline(t.children))
        elif t.type in ('paragraph_open','heading_open','blockquote_open'):
            if not (t.type=='paragraph_open' and i and ts[i-1].type=='list_item_open'):newline()
        elif t.type=='paragraph_close':
            newline()
            if not lists:out.append('\n')
        elif t.type in ('heading_close','blockquote_close'):newline()
        elif t.type in ('bullet_list_open','ordered_list_open'):
            structured=True;lists.append([t.type,int(t.attrGet('start') or 1)]);newline()
        elif t.type in ('bullet_list_close','ordered_list_close'):
            if lists:lists.pop()
            newline()
        elif t.type=='list_item_open':
            newline()
            if lists and lists[-1][0]=='ordered_list_open':out.append(str(lists[-1][1])+'、');lists[-1][1]+=1
        elif t.type=='list_item_close':newline()
        elif t.type=='hr':newline()
        elif t.type in ('html_block',):out.append(t.content)
        i+=1
    result=re.sub(r'\n{3,}','\n\n',''.join(out)).strip()
    for key,value in reversed(list(protected.items())):result=result.replace(key,value)
    return result,structured
