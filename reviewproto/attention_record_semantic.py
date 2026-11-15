"""Pure record-level adaptation; request audit and storage stay in candidates."""
import copy
from .core import require, ReviewError
from . import attention_semantic as semantic

PROTOCOL='attention-record-semantic/1'
B_PROMPT=semantic.EXTRACTION_PROMPT.replace('不分类表达功能','同时分类每个方面的表达功能')+'''
每个方面同时返回state和boilerplate，不另发分类请求。state使用下表括号内的存储值，依据所选evidence组在完整记录中的作用判断，不能借用邻近方面的作用。
完整类别定义：
'''+ '\n'.join(label+'（state='+stored+'）：'+meaning for label,stored,meaning in semantic.FUNCTION_LABELS)+'''
boilerplate仅标礼貌或通用总体判断候选，具体技术判断、归属与限制不因常见句式成为套话。
可用ranges[{focus,evidence}]指定本方面需要分别对照A的语义范围；必须完整覆盖原evidence选择，不得扩展。未指定时整组证据共同构成一个范围。'''
A_PROMPT='''一次比较本条记录内全部已冻结B方面的各范围与完整reference内的每个A条目。
返回facets对象，严格使用输入facet.id，每个方面返回comparisons对象，使用每个reference.id，值为{a_text,comparisons}。
内层comparisons严格使用本方面每个scope.id，值为{b_text,kind,reason}。a_text逐字回传对应A.text，b_text逐字回传该方面scope.text。
全部方面×全部A×全部指定范围都必须有一行，不得遗漏、截短、增加或改写B。不在输出中直接判断清单外。
context只帮助理解指代、限定和条件；不得将其他方面或语境搬入当前scope。reference是本批完整关注参照，不是评分标准。
'''+semantic.SCOPED_A_PROMPT.replace('与唯一A原文','与当前行对应的A原文')+'\n完整关系定义：\n'+semantic.definition_table(semantic.A_RELATIONS)
A_SCHEMA=semantic.obj({'facets':{'type':'object','additionalProperties':semantic.obj({
    'comparisons':{'type':'object','additionalProperties':semantic.SCOPED_A_SCHEMA}})}})


def freeze_b(record,response):
    """Bind labels and complete source ranges before canonical conversion."""
    scopes={};bindings={};rejected=[]
    for op in response.get('opinions',[]):
        valid=[]
        for raw in op.get('facets',[]):
            try:
                require('facet-'+raw['ref'] not in scopes,'E_ATTENTION_DUPLICATE')
                selected=[semantic.quote(record,ev,True) for ev in raw['evidence']]
                binding=semantic.bind_focus(raw['focus'],selected)
                for group in raw.get('ranges',[]):
                    bound=semantic.bind_focus(group['focus'],[semantic.quote(record,ev,True) for ev in group['evidence']])
                    binding.setdefault('ranges',[]).append(bound)
                groups=semantic.semantic_ranges(record,raw)
                raw.pop('ranges',None)
                scopes['facet-'+raw['ref']]=groups
                bindings['facet-'+raw['ref']]=binding
                valid.append(raw)
            except (ReviewError,KeyError,TypeError) as exc:
                rejected.append({'stage':'b_analysis','code':str(exc) if isinstance(exc,ReviewError) else 'E_ATTENTION_RESPONSE'})
        op['facets']=valid
    return scopes,bindings,rejected


def a_request(record,selected,reference,source_scopes):
    """Every current A item and every accepted B scope, without shortlisting."""
    facets={};items={'a'+str(i+1):item for i,item in enumerate(reference['items'])}
    payload={'context':{'sections':[{'id':'s'+str(i+1),'text':section['text']}
        for i,section in enumerate(record['sections'])]},
        'reference':[{'id':alias,'text':item['text']} for alias,item in items.items()], 'facets':[]}
    schemas={}
    for op in selected:
        for facet in op['facets']:
            alias='f'+str(len(facets)+1)
            groups={'b'+str(i+1):group for i,group in enumerate(source_scopes[facet['facet_id']])}
            scopes={key:group['text'] for key,group in groups.items()}
            facets[alias]=(facet,groups)
            payload['facets'].append({'id':alias,'focus':facet['qualifiers']['object'],
                'context':[e['quote'] for e in facet['evidence']],
                'scopes':[{'id':key,'text':group['text'],'focus':group['focus'],
                           'quotes':[e['quote'] for e in group['evidence']]} for key,group in groups.items()]})
            schemas[alias]=semantic.obj({'comparisons':semantic.obj({key:semantic.scoped_a_schema(item,scopes)
                for key,item in items.items()})})
    return payload,semantic.obj({'facets':semantic.obj(schemas)}),facets,items


def convert_a(response,facets,items,version):
    """Reject an incomplete record matrix; failure never means unrelated."""
    require(isinstance(response,dict) and set(response)=={'facets'},'E_ATTENTION_A_REWRITE')
    rows=response['facets']
    require(isinstance(rows,dict) and set(rows)==set(facets),'E_ATTENTION_A')
    mappings=[]
    for alias,(facet,groups) in facets.items():
        block=rows[alias]
        require(isinstance(block,dict) and set(block)=={'comparisons'},'E_ATTENTION_A_REWRITE')
        comparisons=block['comparisons']
        require(isinstance(comparisons,dict) and set(comparisons)==set(items),'E_ATTENTION_A')
        scopes={key:group['text'] for key,group in groups.items()}
        decisions={key:semantic.scoped_decisions(comparisons[key],item,scopes) for key,item in items.items()}
        links=[];outside=[]
        for key,item in items.items():
            for scope,pos in decisions[key].items():
                if pos['kind']=='unrelated': continue
                links.append({'a_item_id':item['id'],'version':version,'kind':pos['kind'],
                    'scope':groups[scope]['focus']+'：'+scopes[scope],'reason':pos['reason'],
                    'evidence':copy.deepcopy(facet['evidence']),'status':'needs_review'})
        if items:
            for scope,literal in scopes.items():
                if all(row[scope]['kind']=='unrelated' for row in decisions.values()):
                    outside.append({'scope':groups[scope]['focus']+'：'+literal,
                        'reason':'仅相对完整本版A，逐项对象比较均无交集：'+'；'.join(row[scope]['reason'] for row in decisions.values()),
                        'evidence':copy.deepcopy(facet['evidence']),'status':'needs_review'})
        mappings.append({'facet_id':facet['facet_id'],'a_links':links,'outside':outside})
    return {'mappings':mappings}
