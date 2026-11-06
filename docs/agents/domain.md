# Domain docs

本项目采用 single-context：根目录一个 `GLOSSARY.md`，决策记录位于 `docs/adr/`。

## 探索前读取

- 读取根目录 `GLOSSARY.md`，使用项目已明确的领域术语。
- 从 `docs/adr/` 读取与当前问题有关的 ADR。
- 上述文件尚未存在时直接继续；不把缺失作为阻碍，也不为凑齐结构而预先创建空文档。通过 `/domain-modeling` 或 `/grill-with-docs` 明确术语、形成决策后，再按需建立。

## 术语与决策的使用

工作项标题、规格、设计建议和测试名称使用术语表定义的词汇。发现缺少关键概念时，先区分项目尚未定义与自行发明术语，再在适用的领域建模工作中解决。

建议与已有 ADR 冲突时，明确指出冲突的 ADR 及重新讨论的理由，保留原决策的可追溯性。

## 预期位置

```text
ReviewProject/
  GLOSSARY.md             # 术语明确后按需建立
  docs/
    adr/                  # 决策形成后按需建立
    agents/               # 工程技能配置
```
