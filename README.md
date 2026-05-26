# Citation Auditor

> Paper Citation Authenticity Auditor — Automatically verify DOI, URL, journal info, and author existence of paper references, generate structured audit reports.

**Author:** OpenClaw Community  
**License:** MIT

## Features

- **DOI Verification** — Verify DOI format and resolvability via doi.org API
- **URL Verification** — HTTP HEAD checks for web links (journal pages, PDF links)
- **PubMed Title Search** — Confirm title/year/journal match via E-utilities
- **Chinese Journal Verification** — Query WanFang / CNKI for Chinese journals
- **Risk Assessment** — Three-tier rating: Pass / Risk / Fail
- **Markdown Report** — Print-ready audit report with statistics

## Quick Start

```bash
# Install skill
install https://github.com/copyleftz/citation-auditor

# Audit from file
citation-audit references.txt -o audit_report.md

# Audit from stdin (paste citations)
citation-audit -o audit_report.md

# With rate-limiting delay
citation-audit references.txt --delay 1.5
```

## Input Format

```
[1] Chen X, Wang Y. Clinical decision support systems in oncology[J]. J Clin Med, 2021, 10(5): 1023.
[2] 王明, 李强. 医院数据治理研究[J]. 中华医学图书情报杂志, 2020, 29(3): 45-52.
[3] https://doi.org/10.1016/j.jbi.2021.103892
```

## Report Output

```
📋 Paper Citation Authenticity Audit Report

审核日期：2026-05-26
参考文献总数：20 条
✅ 通过：16 条 | ⚠ 风险：3 条 | ❌ 失败：1 条

## ✅ Passed
| # | Title | DOI | Status |
|---|-------|-----|--------|
| 1 | Clinical decision support... | 10.1016/j.jbi... | ✓ |

## ⚠ Risk
| # | Issue | Recommendation |
|---|-------|----------------|

## Statistics
- DOI Pass Rate: 85%
- URL Avail Rate: 72%
```

## Architecture

```
Input Text/File
    ↓
[Parser] → extract DOI, URL, title, journal, year
    ↓
┌───────────────────────────────────────┐
│  Parallel Verification               │
│  ├── DOI → doi.org API              │
│  ├── URL → HTTP HEAD                │
│  ├── Title → PubMed E-utilities     │
│  └── Journal → WanFang / ISSN       │
└───────────────────────────────────────┘
    ↓
[Risk Assessor] → pass / risk / fail
    ↓
[Markdown Report Generator]
```

## API References

- doi.org API: https://doi.org/{doi}
- PubMed E-utilities: https://eutils.ncbi.nlm.nih.gov
- CrossRef: https://api.crossref.org
- WanFang: https://www.wanfangdata.com.cn
