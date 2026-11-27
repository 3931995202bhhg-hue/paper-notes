# BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding

**Authors:** Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova  
**Pages:** 16  
**Type:** empirical  
**Case:** example-bert

## 一页摘要

We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers. Unlike recent language representation models (Peters et al., 2018a; Radford et al., 2018), BERT is designed to pretrain deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers. As a result, the pre-trained BERT model can be ﬁnetuned with just one additional output layer to create state-of-the-art models for a wide range of tasks, such as question answering and language inference, without substantial taskspeciﬁc architecture modiﬁcations. [p.1, p.1, p.1, p.1, p.1, p.9]

## 论文卡片

| 字段 | 内容 |
| --- | --- |
| 研究问题 | 能否用统一的双向 Transformer 预训练目标，替代任务特定的架构改造，并在多类 NLP 任务上同时取得最好结果？ |
| 方法 | As a result, the pre-trained BERT model can be ﬁnetuned with just one additional output layer to create state-of-the-art models for a wide range of tasks, such as question answering and language inference, without substantial taskspeciﬁc architecture modiﬁcations.; The feature-based approach, such as ELMo (Peters et al., 2018a), uses task-speciﬁc architectures that include the pre-trained representations as additional features.; The two approaches share the same objective function during pre-training, where they use unidirectional language models to learn general language representations. |
| 主要发现 | As a result, the pre-trained BERT model can be ﬁnetuned with just one additional output layer to create state-of-the-art models for a wide range of tasks, such as question answering and language inference, without substantial taskspeciﬁc architecture modiﬁcations.; It obtains new state-of-the-art results on eleven natural language processing tasks, including pushing the GLUE score to 80.5% (7.7% point absolute improvement), MultiNLI accuracy to 86.7% (4.6% absolute improvement), SQuAD v1.1 question answering Test F1 to 93.2 (1.5 point absolute improvement) and SQuAD v2.0 Test F1 to 83.1 (5.1 point absolute improvement). |
| 局限 | 论文自身未设局限章节；从方法条件看，结论依赖大规模无标注语料与充足算力，小数据场景未报告。 |

## 章节地图

| 节 | 标题 | 层级 | 页码 | 段数 | 状态 |
| --- | --- | --- | --- | --- | --- |
| S01 | Abstract | L1 | p.1–1 | 3 | ok |
| S02 | Introduction | L1 | p.1–2 | 18 | ok |
| S03 | Related Work | L1 | p.2–2 | 2 | thin |

## 章节笔记

### S01 · Abstract
*p.1–1 · 3 段 · 状态 ok*

- **本节目的:** We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers. [p.1]
- **方法:** As a result, the pre-trained BERT model can be ﬁnetuned with just one additional output layer to create state-of-the-art models for a wide range of tasks, such as question answering and language inference, without substantial taskspeciﬁc architecture modiﬁcations.
- **结果:** It obtains new state-of-the-art results on eleven natural language processing tasks, including pushing the GLUE score to 80.5% (7.7% point absolute improvement), MultiNLI accuracy to 86.7% (4.6% absolute improvement), SQuAD v1.1 question answering Test F1 to 93.2 (1.5 point absolute improvement) and SQuAD v2.0 Test F1 to 83.1 (5.1 point absolute improvement). Unlike recent language representation models (Peters et al., 2018a; Radford et al., 2018), BERT is designed to pretrain deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.
- **结论:** BERT is conceptually simple and empirically powerful.
- **要点:** Unlike recent language representation models (Peters et al., 2018a; Radford et al., 2018), BERT is designed to pretrain deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.

### S02 · Introduction
*p.1–2 · 18 段 · 状态 ok*

- **本节目的:** Language model pre-training has been shown to be effective for improving many natural language processing tasks (Dai and Le, 2015; Peters et al., 2018a; Radford et al., 2018; Howard and Ruder, 2018). [p.1]
- **方法:** The feature-based approach, such as ELMo (Peters et al., 2018a), uses task-speciﬁc architectures that include the pre-trained representations as additional features. The two approaches share the same objective function during pre-training, where they use unidirectional language models to learn general language representations.
- **结果:** Williams et al., 2018) and paraphrasing (Dolan and Brockett, 2005), which aim to predict the relationships between sentences by analyzing them holistically, as well as token-level tasks such as named entity recognition and question answering, where models are required to produce ﬁne-grained output at the token level (Tjong Kim Sang and De Meulder, 2003; Rajpurkar et al., 2016). BERT is the ﬁrst ﬁnetuning based representation model that achieves state-of-the-art performance on a large suite of sentence-level and token-level tasks, outperforming many task-speciﬁc architectures.
- **结论:** • BERT advances the state of the art for eleven
- **承接:** 上一节以「BERT is conceptually simple and empirically powerful.」收束，本节以「Language model pre-training has been shown to be effective …」展开。
- **要点:** BERT is the ﬁrst ﬁnetuning based representation model that achieves state-of-the-art performance on a large suite of sentence-level and token-level tasks, outperforming many task-speciﬁc architectures.
- **要点:** The feature-based approach, such as ELMo (Peters et al., 2018a), uses task-speciﬁc architectures that include the pre-trained representations as additional features.

### S03 · Related Work
*p.2–2 · 2 段 · 状态 thin*

- **本节目的:** There is a long history of pre-training general language representations, and we brieﬂy review the most widely-used approaches in this section. [p.2]
- **承接:** 上一节以「• BERT advances the state of the art for eleven」收束，本节以「There is a long history of pre-training general language re…」展开。

## 知识点

| 编号 | 术语 | 类型 | 说明 | 页码 |
| --- | --- | --- | --- | --- |
| K001 | A “sequence” | concept | A “sequence” — the input token sequence to BERT, which may be a single sentence or two sentence | p.4 |
| K002 | NSP | abbreviation | NSP = Next Sentence Prediction | p.4 |
| K003 | QA | abbreviation | QA = downstream tasks such as Question | p.4 |
| K004 | NLI | abbreviation | NLI = Natural Language Inference | p.4 |
| K005 | GLUE | abbreviation | GLUE = General Language Understanding Evaluation | p.5 |
| K006 | SWAG | abbreviation | SWAG = Situations With Adversarial Generations | p.7 |

## 不确定与未报告

- **example**: 示例仅保留前 3 节，用于展示结构，不是完整结果

## 锚点索引（可回链）

| 锚点 | 页 | 节 | 引文（逐字） |
| --- | --- | --- | --- |
| A0001 | p.1 | S01 | We introduce a new language representation model called BERT, which s… |
| A0002 | p.1 | S01 | As a result, the pre-trained BERT model can be ﬁnetuned with just one… |
| A0003 | p.1 | S01 | It obtains new state-of-the-art results on eleven natural language pr… |
| A0004 | p.1 | S01 | Unlike recent language representation models (Peters et al., 2018a; R… |
| A0005 | p.1 | S01 | BERT is conceptually simple and empirically powerful. |
| A0006 | p.1 | S02 | Language model pre-training has been shown to be effective for improv… |
| A0007 | p.1 | S02 | The feature-based approach, such as ELMo (Peters et al., 2018a), uses… |
| A0008 | p.1 | S02 | The two approaches share the same objective function during pre-train… |
| A0009 | p.1 | S02 | Williams et al., 2018) and paraphrasing (Dolan and Brockett, 2005), w… |
| A0010 | p.2 | S02 | BERT is the ﬁrst ﬁnetuning based representation model that achieves s… |
| A0011 | p.2 | S02 | • BERT advances the state of the art for eleven |
| A0012 | p.2 | S03 | There is a long history of pre-training general language representati… |
| A0076 | p.9 | S18 | All of the BERT results presented so far have used the ﬁne-tuning app… |

## 核验

- 锚点总数 13，通过 13，失败 0，覆盖率 1.0
- 核验方式: bbox_clip+page_text+native_search
