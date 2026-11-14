# 已保存关注分布 Interface · attention-summary/1

计算与无图展示独立于编辑器；输入采用[关注分析契约](ATTENTION_CONTRACT.md)的已保存 `attention/1` 状态。只读取 `opinions[].facets[]`，不用T1顶层投影。真实状态及生成页面继承原材料权限，不能发布到仓库。

```python
from reviewproto.attention_summary import summarize
from reviewproto.attention_summary_view import render_summary

result = summarize(saved_state, {'paper_ids': ['synthetic-paper']})
fragment = render_summary(result)
```

`summarize(state, filters=None)` 是唯一纯计算 Interface：不读写文件、数据库、模型或网络，不改变输入。接受来自同一保存修订的普通字典，返回可JSON序列化的字典；不是未校验输入的导入接口。未知筛选名称抛出 `ValueError`。返回对象与输入的原话/方面独立，可安全交给展示层。

## 分母与筛选

- `record_ids`、`paper_ids`：列表；二者同时给出时取交集，改变分母。材料组优先读用户声明的 `record.paper_id`，旧包回退 `record.locator.paper_id`；未知组可用列表中的 `None` 显式选择。空列表得到N=0。
- `directions`、`statuses`、`functions`：列表；同字段内为“或”，不同字段间为“且”。筛选方面的 `qualifiers.direction`、`status`、`expression.function`；方向列表逐项匹配。未说明的方向显示为“未说明”。
- `boilerplate_candidate`：`True/False/None` 分别选择是、否、未判断。候选只是一项表达属性，不自动删除实质内容。

后四种表达筛选只改变命中，不改变记录分母。无方面的记录仍保留在N中。主题和A所有已知行保留零值，关系类型零命中也保留；N=0时 `ratio=None`，不除零。不同来源即使原话相同，也不推断为同一记录；相同 `record_id` 的副本只进集合一次，观点/方面身份相同的重复投影不增加辅助数。新run不会产生新的独立记录。

## 结果与复算

`denominator`、`hits`、`themes[id]`、`a_items[id][kind]`、`a_parts[id][kind]`、`a_unassigned[kind]`、`directions[value]`、`statuses[value]`、`outside[status]` 和 `relations[type]` 的数均含 `count/denominator/record_ids/ratio`。记录ID排序；`ratio`是0至1的比值。取 `record_ids` 长度即可独立复算记录数。

`themes` 包含显式成员及全部父主题的记录并集；保留主题定义、边界和父组于 `theme_definitions`。A部分按条目的显式 `part_id` 取并集，不相加子项。旧参照无分组时 `a_parts={}`，不猜测分组。

A的五列为 `explicit/partial/related/undetermined/needs_review`。`working` 和 `confirmed` 关联可按原kind计入；待核关联、待核方面、失效版本、材料失效、非法kind及未知非空条目ID仅进待核列。`withdrawn/superseded` 观点、方面、关联不计当前。合法 `a_item_id=None,kind=undetermined` 只进全局 `a_unassigned.undetermined`，不分摊给A条目。当前清单外由 `outside` 独立按状态分列，不由A链接是否为空推断。

`content` 与 `disposition` 各含 `opinions/facets/records`；前二者为辅助数，含 `count/ids/record_ids/denominator/unit`。辅助数不称为记录覆盖率。处置方面不进入主题、A及内容方向排名。关系另列 `relations` 和完整 `relation_details`，只有所有实际端点都在当前命中方面中时保留；关系记录集合取端点记录并集，不当额外主题或独立记录数。

`details[record_id]` 保存完整原记录（分区、原分、定位）及当前命中方面、观点解释/状态。`revision/analysis_id/rules_version/summary_rules_version/a_version/material_status/a_material_status/b_material_status/filters` 与数字一起返回；`saved=True` 表示调用约定为已保存状态，并不检测调用者私改的字典。草稿应独立展示，不能传入并宣称已保存。

## T5嵌入点与即时筛选

`render_summary(result)` 返回带局部样式、无脚本、已转义的HTML `<section>`。可嵌入主页面已保存区；主题/A各列链接到同片段记录明细，键盘可展开原话与解释。同一页面只嵌入一次，避免重复锚点。主页面与即时筛选通过下述T5嵌入点使用本Interface。

`contributions` 是逐方面贡献索引，每项带 `record_id/opinion_id/facet_id/kind/status/directions/expression/theme_ids/a_items/a_parts/a_unassigned/outside`。`theme_ids` 已展开父组，A条目/部分以 `{id,kind}` 给出Python已经判定的有效列；浏览器不得重新解释A版本/状态或从文字猜类型。列表可有同列重复贡献，汇总时必须取记录集合。

T5在离线页面使用无表达筛选的结果作为完整贡献索引：先按记录/材料选出分母记录，随后按表达属性筛选贡献，再对指定行的贡献取 `record_id` 并集。关系使用 `relation_details.endpoints[].facet_id` 检查全部端点是否保留。辅助观点/方面按各自ID去重。原始 `details` 足够展示原话/原分及命中依据。已筛选结果的贡献索引仅包含该次命中，不能据此撤销筛选恢复原数据。

数字只说明本批表达，不表示教师群体重要性、论文质量、A权重或专业结论正确。未知教师/轮次不妨碍记录统计；主题宽窄、重叠和工作状态需随展示保留。

## 验证

`python -m unittest discover -s tests -p test_attention_summary.py -v` 使用独立四记录手算集合，覆盖并集、副本、多方面、失效引用、表达筛选、空N、处置/关系分列、贡献索引、转义及1440/420宽度键盘回查。`ATTENTION_SUMMARY_EVIDENCE_DIR` 可指定合成浏览器截图的本地输出目录。全套使用 `scripts/check.ps1 -Python python`，并设置真实Chrome的 `REVIEW_BROWSER_BINARY`。

T5已将本Interface接入主关注页。`attention_views.js`从无筛选`summarize()`结果读取完整贡献索引，统一筛选后供无图数字/明细、矩阵与局部关系图使用；不重判A有效性。无脚本时保留`render_summary()`无图结果。交互及保存语义见[视图操作](ATTENTION_CONTRACT.md#t5-保存结果视图)。浏览器回归：`python -m unittest discover -s tests -p test_attention_views.py -v`。

复用工具在保存结果区加入“当前关注概览”，显示实际修订、动态A结构、规模和可回查记录集合；无A/未整理/来源失效各有明确空态或提示。概览与下方各主题、A条目/部分、关系及可选图共用当前集合及分母，不生成无依据的解释性发现；下载草稿不改变保存概览。复用浏览器回归见`test_attention_overview.py`，普通输入跨批验收见[复用施工计划](plans/b-attention-reuse-construction.md)。
