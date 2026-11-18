"""Explicit, entirely invented saved example; never calls a model or reads keys."""
from contextlib import closing
from .attention import AttentionWorkspace
from .attention_input import AttentionInput, build_prepared


def create_sample(destination):
    draft=AttentionInput()
    for anchor,text,scores in [
        ('合成示例甲','若图表保留，请补充图例。',[{'label':'自由原分示例','raw_value':' B+ '}]),
        ('合成示例乙','论述清楚。建议说明样本的范围。',[])]:
        draft.add_transcription(anchor,text,'author_visible',scores,
            '为试用虚构的材料，不是真实评语','纯合成示例（非真实材料）')
    draft.set_a({'version':'合成示例A-v1（非金标）','parts':[
        {'id':'illustration','label':'图表说明'},{'id':'scope','label':'材料范围'},
        {'id':'robustness','label':'稳健性检验'},{'id':'ethics','label':'研究伦理'},
        {'id':'limitations','label':'研究局限'}], 'items':[
        {'id':'legend','part_id':'illustration','text':'说明图表中符号的含义。','locator':'合成A第一条'},
        {'id':'sample','part_id':'scope','text':'说明样本及适用范围。','locator':'合成A第二条'},
        {'id':'sensitivity','part_id':'robustness','text':'说明更换分析设定后结论是否变化。','locator':'合成A第三条'},
        {'id':'participants','part_id':'ethics','text':'如涉及研究参与者，说明知情同意与隐私保护。','locator':'合成A第四条'}]})
    state=build_prepared(draft,destination)
    themes=[{'theme_id':key,'label':label,'definition':definition,'parent_ids':[],'status':'working'}
        for key,label,definition in [('figure','图表可读性','图例与符号说明'),
            ('range','样本范围','材料及样本覆盖的边界'),('writing','表达组织','行文清楚程度')]]
    a_reasons={
        'legend':'A关注图表符号说明，补充图例是同一范围内的建议。',
        'sample':'A关注样本及适用范围，此建议同样涉及样本覆盖边界。'}
    opinions=[]
    for index,(record_index,quote,reading,theme,a_id) in enumerate([
        (0,'若图表保留，请补充图例。','保留图表时补充图例','figure','legend'),
        (1,'论述清楚。','对论述清楚的肯定','writing',None),
        (1,'建议说明样本的范围。','补充样本覆盖的范围','range','sample')]):
        record=state['records'][record_index];section=record['sections'][0]
        start=section['text'].index(quote)
        evidence=[{'source_id':record['source_id'],'section_id':section['section_id'],
            'start':start,'end':start+len(quote),'quote':quote}]
        facet={'facet_id':'sample-facet-'+str(index),'interpretation':reading,
            'status':'working','evidence':evidence,
            'themes':[{'theme_id':theme,'reason':'原话直接涉及此主题，属于合成示范读法',
                'evidence':evidence,'status':'working'}],
            'qualifiers':{'conditions':'若图表保留' if record_index==0 else ''},
            'expression':{'function':'肯定' if theme=='writing' else '建议','boilerplate_candidate':False}}
        if a_id:
            facet['a_links']=[{'a_item_id':a_id,'version':state['a_reference']['version'],
                'kind':'explicit','scope':reading,'reason':a_reasons[a_id],
                'evidence':evidence,'status':'working'}]
        else:
            facet['outside']=[{'scope':'论述清楚程度','reason':'本版合成A未明示论述是否清楚。',
                'evidence':evidence,'status':'working'}]
        opinions.append({'opinion_id':'sample-opinion-'+str(index),'record_id':record['record_id'],
            'interpretation':reading,'status':'working','facets':[facet]})
    with closing(AttentionWorkspace(destination)) as ws:
        return ws.apply({'schema':'attention-patch/2','analysis_id':state['analysis_id'],
            'base_revision':state['revision'],'actor':'合成示例编写者',
            'reason':'人工编写的功能示范，非模型结果、非专业金标；所有材料均为虚构。',
            'edits':opinions,'themes':themes})
