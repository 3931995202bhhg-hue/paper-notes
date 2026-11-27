# {{paper_card.title}}

**Authors:** {{paper_card.authors | join(", ")}}
**Pages:** {{paper.pages}}
**Type:** {{paper_card.paper_type}}
**Case:** {{case_id}}

## 一页摘要

{{paper_card.summary}} [p.{{paper_card.summary_page}}]

## 论文卡片

| 字段 | 内容 |
| --- | --- |
| 研究问题 | {{paper_card.research_question}} |
| 数据 | {{paper_card.data | join("; ")}} |
| 方法 | {{paper_card.methods | join("; ")}} |
| 主要发现 | {{paper_card.findings | join("; ")}} |
| 局限（{{paper_card.limitations_kind}}） | {{paper_card.limitations | join("; ")}} |

## 章节笔记

{{#each sections}}
### {{id}} · {{title}}

*p.{{page_start}}–{{page_end}} · {{n_paragraphs}} 段 · 状态 {{status}}*

- **本节目的:** {{objective}} [p.{{objective_page}}]
- **方法:** {{methods | join(" ")}}
- **结果:** {{results | join(" ")}}
- **结论:** {{conclusion}}
- **承接:** 上一节以「{{continuity.previous_tail}}」收束，本节以「{{continuity.opens_with}}」展开。
{{#each key_points}}
- **要点:** {{this}}
{{/each}}

{{/each}}

## 知识点

| 编号 | 术语 | 类型 | 说明 | 页码 |
| --- | --- | --- | --- | --- |
{{#each knowledge_points}}
| {{id}} | {{term}} | {{kind}} | {{statement}} | p.{{page}} |
{{/each}}

## 不确定与未报告

{{#each uncertainty}}
- **{{kind}}**: {{detail}}
{{/each}}

## 核验

- 锚点总数 {{verification.anchors_total}}，通过 {{verification.anchors_verified}}，
  失败 {{verification.anchors_failed}}，覆盖率 {{verification.coverage}}
- 核验方式: {{verification.method}}
