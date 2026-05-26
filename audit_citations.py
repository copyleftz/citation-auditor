#!/usr/bin/env python3
"""
Citation Auditor — 论文引文真实性审核核心脚本
支持：DOI核查、URL核查、期刊信息核查、标题关键词核查
输出：Markdown格式审核报告
"""

import re
import json
import sys
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

# ─── 颜色输出 ───────────────────────────────────────────────
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BOLD = '\033[1m'
RESET = '\033[0m'

def log_info(msg):  print(f"{BOLD}[INFO]{RESET} {msg}")
def log_ok(msg):    print(f"{GREEN}[OK]{RESET} {msg}")
def log_warn(msg):  print(f"{YELLOW}[WARN]{RESET} {msg}")
def log_fail(msg):  print(f"{RED}[FAIL]{RESET} {msg}")

# ─── 解析引文 ────────────────────────────────────────────────
GBTH_PATTERN = re.compile(
    r'\[(\d+)\]\s+(.+?)\.\s+"([^"]+)".*?\[([^\]]+)\]'  # [N] Author. "Title"[J]. Journal, YYYY.
)
EN_PATTERN = re.compile(
    r'\[(\d+)\]\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),?\s+et al\.?,?\s+(.+?)\.\s+"([^"]+)"\s*\[([A-Z])\]?\.\s*([^(]+?)(?:,|\()\s*(\d{4})'
)

def parse_citation(line: str) -> dict:
    """从单行引文中提取结构化字段"""
    result = {"raw": line.strip(), "status": "pending", "risks": [], "details": {}}
    if not line.strip() or line.startswith("#"):
        return result

    # 提取编号
    num_m = re.search(r'\[(\d+)\]', line)
    result["number"] = int(num_m.group(1)) if num_m else None

    # DOI 提取
    doi_m = re.search(r'(10\.\d{4,}/[^\s\]]+)', line)
    result["doi"] = doi_m.group(1) if doi_m else None

    # 年份
    year_m = re.search(r'[(（](\d{4})[)）]', line)
    result["year"] = year_m.group(1) if year_m else None

    # URL 提取
    url_m = re.search(r'https?://[^\s\]]+', line)
    result["url"] = url_m.group(0) if url_m else None

    # 标题
    title_m = re.search(r'"([^"]+)"', line)
    if not title_m:
        title_m = re.search(r'《([^》]+)》', line)
    result["title"] = title_m.group(1) if title_m else None

    # 期刊名（中文）
    journal_cn = re.search(r'《([^》]+)》', line)
    result["journal_cn"] = journal_cn.group(1) if journal_cn else None

    # 英文期刊
    journal_en = re.search(r'\(([A-Z][a-zA-Z\s&:]+)\)\s*,?\s*\d{4}', line)
    if not journal_en:
        journal_en = re.search(r'\[J\]\.\s*([A-Z][A-Za-z\s&]+),', line)
    result["journal_en"] = journal_en.group(1).strip() if journal_en else None

    return result


# ─── DOI 核查 ────────────────────────────────────────────────
def verify_doi(doi: str, timeout: int = 8) -> dict:
    """通过 doi.org API 验证 DOI"""
    if not doi:
        return {"ok": False, "reason": "无DOI"}

    url = f"https://doi.org/{doi}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "CitationAuditor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            # doi.org 重定向到出版商页面即说明 DOI 有效
            result = {"ok": True, "url": final_url}
            # 尝试解析响应中的 JSON 元数据
            try:
                meta = json.loads(resp.read().decode())
                result["title"] = meta.get("title", "")
                result["publisher"] = meta.get("publisher", "")
            except Exception:
                pass
            return result
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:60]}


# ─── URL 核查 ────────────────────────────────────────────────
def verify_url(url: str, timeout: int = 8) -> dict:
    """HTTP HEAD 请求验证 URL"""
    if not url:
        return {"ok": False, "reason": "无URL"}

    try:
        req = urllib.request.Request(url, method="HEAD",
            headers={"User-Agent": "CitationAuditor/1.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            return {"ok": 200 <= status < 400, "status": status,
                    "final_url": resp.geturl()}
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": f"HTTP {e.code}", "status": e.code}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:60]}


# ─── PubMed 标题核查 ─────────────────────────────────────────
def search_pubmed(query: str, timeout: int = 10) -> dict:
    """用 PubMed E-utilities 搜索标题"""
    if not query or len(query) < 5:
        return {"ok": False, "reason": "标题太短"}

    try:
        # ESearch
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        search_url = f"{base}esearch.fcgi?db=pubmed&term={urllib.parse.quote(query)}&retmax=3&retmode=json"
        req = urllib.request.Request(search_url, headers={"User-Agent": "CitationAuditor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            ids = data.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return {"ok": False, "reason": "PubMed 未找到"}

            # ESummary 获取期刊/年份
            id_list = "+".join(ids[:3])
            summary_url = f"{base}esummary.fcgi?db=pubmed&id={id_list}&retmode=json"
            sum_req = urllib.request.Request(summary_url, headers={"User-Agent": "CitationAuditor/1.0"})
            with urllib.request.urlopen(sum_req, timeout=timeout) as sum_resp:
                sum_data = json.loads(sum_resp.read().decode())
                results = []
                for uid, info in sum_data.get("result", {}).items():
                    if uid == "uids":
                        continue
                    results.append({
                        "pmid": uid,
                        "title": info.get("title", ""),
                        "source": info.get("source", ""),
                        "pubdate": info.get("pubdate", "")[:4],
                        "authors": [a.get("name","") for a in info.get("authors", [])][:3]
                    })
                return {"ok": True, "matches": results}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:60]}


# ─── 中文期刊核查 ─────────────────────────────────────────────
def verify_chinese_journal(journal_name: str, year: str = None, timeout: int = 8) -> dict:
    """通过万方 API 验证中文期刊（需网络）"""
    if not journal_name:
        return {"ok": False, "reason": "无期刊名"}

    try:
        url = f"https://www.wanfangdata.com.cn/search/search.do?searchWord={urllib.parse.quote(journal_name)}&searchType=periodical&娘娘=20"
        req = urllib.request.Request(url, headers={"User-Agent": "CitationAuditor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            if journal_name[:4] in content or "ISSN" in content:
                return {"ok": True, "found_in": "wanfang"}
            return {"ok": True, "found_in": "wanfang", "note": "期刊存在，建议人工核对年份"}
    except Exception as e:
        return {"ok": False, "reason": f"万方查询失败: {str(e)[:40]}"}


# ─── 风险评估 ───────────────────────────────────────────────
def assess_risk(citation: dict, doi_result: dict = None, url_result: dict = None,
                pubmed_result: dict = None, cn_journal_result: dict = None) -> str:
    """综合评估风险等级：pass / risk / fail"""
    reasons = []

    if doi_result and not doi_result.get("ok"):
        reasons.append(f"DOI无效: {doi_result.get('reason','')}")
    if url_result and not url_result.get("ok"):
        reasons.append(f"URL无效: {url_result.get('reason','')}")
    if pubmed_result and not pubmed_result.get("ok"):
            reasons.append(f"PubMed未找到匹配: {pubmed_result.get('reason','')}")

    if not doi_result and not url_result:
        reasons.append("无DOI/URL，完全依赖人工验证")

    citation["risks"] = reasons
    if not reasons:
        return "pass"
    elif any("未找到" in r or "无效" in r for r in reasons):
        return "risk"
    else:
        return "risk"


# ─── 生成 Markdown 报告 ───────────────────────────────────────
def generate_report(citations: list, output_path: str = None):
    """生成 Markdown 格式审核报告"""
    total = len(citations)
    passed = [c for c in citations if c.get("status") == "pass"]
    risk_c = [c for c in citations if c.get("status") == "risk"]
    failed = [c for c in citations if c.get("status") == "fail"]

    lines = [
        "# 📋 论文引文真实性审核报告",
        "",
        f"**审核日期**：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**参考文献总数**：{total} 条  ",
        f"**核查完成**：{len(citations)} 条 | "
        f"**✅ 通过**：{len(passed)} 条 | "
        f"**⚠ 风险**：{len(risk_c)} 条 | "
        f"**❌ 失败**：{len(failed)} 条",
        "",
        "---",
        "",
    ]

    # 通过的引文
    if passed:
        lines += ["## ✅ 通过的引文\n",
                  "| # | 作者 | 标题（缩略） | 年份 | DOI/URL | 状态 |",
                  "|---|------|-------------|------|---------|------|"]
        for c in passed:
            num = c.get("number", "")
            title = (c.get("title") or "")[:40]
            year = c.get("year", "")
            doi = f"`{c.get('doi','')}`" if c.get("doi") else ""
            lines.append(f"| {num} | — | {title} | {year} | {doi} | ✓ 通过 |")

    # 风险引文
    if risk_c:
        lines += ["\n## ⚠ 风险引文 — 需要人工核实\n",
                  "| # | 标题 | 风险原因 | 建议操作 |",
                  "|---|------|---------|---------|"]
        for c in risk_c:
            num = c.get("number", "")
            title = (c.get("title") or c.get("raw",""))[:40]
            reasons = "；".join(c.get("risks", []))
            lines.append(f"| {num} | {title} | {reasons} | 手动搜索验证 |")

    # 失败引文
    if failed:
        lines += ["\n## ❌ 无法验证\n",
                  "| # | 引文内容 | 失败原因 |",
                  "|---|---------|---------|"]
        for c in failed:
            num = c.get("number", "")
            raw = c.get("raw", "")[:60]
            reasons = "；".join(c.get("risks", ["未知原因"]))
            lines.append(f"| {num} | {raw} | {reasons} |")

    # 统计摘要
    doi_ok = sum(1 for c in citations if c.get("doi") and c.get("_doi_ok"))
    doi_total = sum(1 for c in citations if c.get("doi"))
    url_ok = sum(1 for c in citations if c.get("url") and c.get("_url_ok"))
    url_total = sum(1 for c in citations if c.get("url"))

    lines += [
        "",
        "---",
        "",
        "## 统计摘要",
        "",
        f"- **DOI 有效率**：{f'{doi_ok}/{doi_total}' if doi_total else 'N/A'} "
          f"({'✅ 100%' if doi_total and doi_ok == doi_total else (f'⚠️ {doi_ok*100//doi_total}%' if doi_total else '—')})",
        f"- **URL 可访问率**：{f'{url_ok}/{url_total}' if url_total else 'N/A'} "
          f"({'✅ 100%' if url_total and url_ok == url_total else (f'⚠️ {url_ok*100//url_total}%' if url_total else '—')})",
        "",
        "---",
        "",
        "## 审核建议",
        "",
        "1. 对 ⚠ 风险引文进行人工核查后再投稿",
        "2. ❌ 无法验证的引文建议替换为可验证的同类文献",
        "3. 建议外文引用比例 ≥60%",
        "",
        "*本报告由 Citation Auditor 自动生成 — 仅供参考，建议配合人工审核*",
    ]

    report = "\n".join(lines)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        log_ok(f"报告已保存: {output_path}")
    return report


# ─── 主审核流程 ───────────────────────────────────────────────
def audit_citations(input_text: str = None, input_file: str = None,
                    output_file: str = None, delay: float = 1.0) -> str:
    """
    审核入口函数
    """
    # 读取输入
    if input_file:
        with open(input_file, encoding="utf-8") as f:
            text = f.read()
    elif input_text:
        text = input_text
    else:
        text = sys.stdin.read()

    # 逐行解析
    lines = [l for l in text.strip().split("\n") if l.strip()]
    citations = []
    for line in lines:
        parsed = parse_citation(line)
        if parsed.get("number"):
            citations.append(parsed)

    if not citations:
        log_warn("未检测到带编号的引文，尝试按行处理...")
        for i, line in enumerate(lines, 1):
            c = {"number": i, "raw": line.strip(), "status": "pending", "risks": [], "details": {}}
            citations.append(c)

    log_info(f"共解析 {len(citations)} 条引文，开始核查...")

    # 逐条核查（带延迟避免限流）
    for i, c in enumerate(citations):
        num = c.get("number", i+1)
        print(f"  [{i+1}/{len(citations)}] 核查引文 #{num}...", end=" ", flush=True)

        doi_r, url_r, pm_r = None, None, None

        # DOI核查
        if c.get("doi"):
            doi_r = verify_doi(c["doi"])
            c["_doi_ok"] = doi_r["ok"]
            if doi_r["ok"]:
                c["details"]["doi_url"] = doi_r.get("url", "")

        # URL核查
        if c.get("url"):
            url_r = verify_url(c["url"])
            c["_url_ok"] = url_r["ok"]

        # PubMed标题核查
        if c.get("title") and len(c.get("title", "")) > 10:
            pm_r = search_pubmed(c["title"])
            if pm_r.get("ok") and pm_r.get("matches"):
                c["details"]["pubmed"] = pm_r["matches"][0]

        # 风险评估
        status = assess_risk(c, doi_r, url_r, pm_r)
        c["status"] = status

        # 日志输出
        if status == "pass":
            print(f"{GREEN}✓ 通过{RESET}")
        elif status == "risk":
            reasons = "; ".join(c.get("risks", [])[:1])
            print(f"{YELLOW}⚠ 风险{RESET} — {reasons[:50]}")
        else:
            print(f"{RED}❌ 失败{RESET}")

        time.sleep(delay)

    # 生成报告
    print()
    report = generate_report(citations, output_file)

    # 打印摘要
    passed = sum(1 for c in citations if c["status"] == "pass")
    risk_c = sum(1 for c in citations if c["status"] == "risk")
    failed = sum(1 for c in citations if c["status"] == "fail")
    print(f"\n{BOLD}审核完成：✅ {passed} | ⚠ {risk_c} | ❌ {failed}{RESET}")

    return report


# ─── CLI 入口 ────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, urllib.parse

    p = argparse.ArgumentParser(description="Citation Auditor — 引文真实性审核")
    p.add_argument("input", nargs="?", help="引文文件路径（.txt/.md）")
    p.add_argument("-o", "--output", help="输出报告路径（.md）")
    p.add_argument("--delay", type=float, default=1.0, help="请求间隔（秒，默认1.0）")
    args = p.parse_args()

    output = args.output or f"citation_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

    if args.input:
        report = audit_citations(input_file=args.input, output_file=output, delay=args.delay)
    else:
        print("请粘贴参考文献（Ctrl+D 结束输入）：")
        text = sys.stdin.read()
        report = audit_citations(input_text=text, output_file=output, delay=args.delay)

    print(f"\n报告已保存: {output}")
