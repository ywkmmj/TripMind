from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import sys
from typing import Any
from dataclasses import dataclass, asdict
from enum import Enum


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools.rag_tool import build_destination_query
from app.rag.retriever import retrieve_travel_guide_chunks


DEFAULT_CASES_PATH = BACKEND_DIR / "eval" / "rag_eval_cases.json"

ALL_DESTINATIONS = ["大理", "成都", "西安", "厦门", "三亚"]


class EvaluationStatus(Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass
class MetricsResult:
    """单个评估案例的详细指标"""
    case_id: str
    status: EvaluationStatus
    
    # 传统指标
    top1_title_hit: bool
    topk_title_hit: bool
    reciprocal_rank: float
    mrr: float
    
    # 内容质量指标
    required_keyword_hits: int
    required_keyword_total: int
    required_coverage: float
    
    # 噪声和污染指标
    noise_count: int
    noise_rate: float
    pollution_count: int
    pollution_rate: float
    
    # 用户偏好匹配
    preference_match_count: int
    preference_total: int
    preference_match_rate: float
    
    # 禁用内容检测
    forbidden_place_hits: int
    
    # 性能指标
    latency_ms: float
    
    # 详细信息
    query: str
    top1_title: str
    titles: list[str]


@dataclass
class AggregatedMetrics:
    """聚合后的评估指标"""
    total_cases: int
    
    # 传统指标统计
    top1_hit_rate: float
    topk_hit_rate: float
    avg_mrr: float
    
    # 内容质量统计
    avg_required_coverage: float
    total_required_hits: int
    total_required_keywords: int
    
    # 噪声和污染统计
    avg_noise_rate: float
    total_noise: int
    avg_pollution_rate: float
    total_pollution: int
    
    # 用户偏好匹配统计
    avg_preference_match_rate: float
    total_preference_hits: int
    total_preference_keywords: int
    
    # 禁用内容统计
    total_forbidden_hits: int
    
    # 性能统计
    avg_latency_ms: float
    
    # 总体评估
    overall_status: EvaluationStatus


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("RAG eval cases file must contain a JSON list.")
    return data


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _evaluate_case(case: dict[str, Any]) -> MetricsResult:
    top_k = int(case.get("top_k", 5))
    destination = str(case["destination"])
    query = build_destination_query(
        destination=destination,
        preferences=list(case.get("preferences", [])),
        pace=case.get("pace"),
        special_notes=case.get("special_notes"),
    )

    start_time = time.perf_counter()
    chunks = retrieve_travel_guide_chunks(query=query, top_k=top_k, destination=destination)
    latency_ms = round((time.perf_counter() - start_time) * 1000, 1)

    expected_title_keywords = list(case.get("expected_title_keywords", []))
    required_content_keywords = list(case.get("required_content_keywords", []))
    noise_title_keywords = list(case.get("noise_title_keywords", []))
    
    # 新增指标所需的配置
    forbidden_place_keywords = list(case.get("forbidden_place_keywords", []))
    preference_match_keywords = list(case.get("preference_match_keywords", []))

    titles = [str(chunk.get("title", "")) for chunk in chunks]
    combined_text = "\n".join(
        f"{chunk.get('title', '')}\n{chunk.get('text', '')}" for chunk in chunks
    )

    top1_title = titles[0] if titles else ""
    top1_title_hit = _contains_any(top1_title, expected_title_keywords)
    topk_title_hit = any(_contains_any(title, expected_title_keywords) for title in titles)
    required_keyword_hits = _count_keyword_hits(combined_text, required_content_keywords)
    noise_count = sum(
        1 for title in titles if _contains_any(title, noise_title_keywords)
    )

    # MRR: 第一个命中期望关键词的结果排名的倒数
    reciprocal_rank = 0.0
    for rank, title in enumerate(titles, start=1):
        if _contains_any(title, expected_title_keywords):
            reciprocal_rank = 1.0 / rank
            break

    # 跨目的地污染：片段来源包含非当前目的地的城市名
    other_destinations = [d for d in ALL_DESTINATIONS if d not in destination]
    pollution_count = 0
    for chunk in chunks:
        source = str(chunk.get("source", ""))
        title = str(chunk.get("title", ""))
        chunk_text = f"{source} {title}"
        if any(other in chunk_text for other in other_destinations):
            pollution_count += 1
    
    # 用户偏好匹配度
    preference_match_count = _count_keyword_hits(combined_text, preference_match_keywords)
    
    # 禁用内容检测（已关闭景点等）
    forbidden_place_hits = _count_keyword_hits(combined_text, forbidden_place_keywords)
    
    # 计算各种比率
    required_coverage = required_keyword_hits / len(required_content_keywords) if required_content_keywords else 0.0
    noise_rate = noise_count / top_k if top_k > 0 else 0.0
    pollution_rate = pollution_count / top_k if top_k > 0 else 0.0
    preference_match_rate = preference_match_count / len(preference_match_keywords) if preference_match_keywords else 0.0
    
    # 确定案例状态
    status = EvaluationStatus.PASSED
    if noise_rate > 0.3 or pollution_rate > 0.2 or required_coverage < 0.5:
        status = EvaluationStatus.WARNING
    if required_coverage < 0.2 or forbidden_place_hits > 0:
        status = EvaluationStatus.FAILED

    return MetricsResult(
        case_id=case.get("id", "<unknown>"),
        status=status,
        
        # 传统指标
        top1_title_hit=top1_title_hit,
        topk_title_hit=topk_title_hit,
        reciprocal_rank=reciprocal_rank,
        mrr=reciprocal_rank,
        
        # 内容质量
        required_keyword_hits=required_keyword_hits,
        required_keyword_total=len(required_content_keywords),
        required_coverage=required_coverage,
        
        # 噪声和污染
        noise_count=noise_count,
        noise_rate=noise_rate,
        pollution_count=pollution_count,
        pollution_rate=pollution_rate,
        
        # 用户偏好
        preference_match_count=preference_match_count,
        preference_total=len(preference_match_keywords),
        preference_match_rate=preference_match_rate,
        
        # 禁用内容
        forbidden_place_hits=forbidden_place_hits,
        
        # 性能
        latency_ms=latency_ms,
        
        # 详细信息
        query=query,
        top1_title=top1_title,
        titles=titles,
    )


def _aggregate_results(results: list[MetricsResult]) -> AggregatedMetrics:
    total = len(results)
    if total == 0:
        return AggregatedMetrics(
            total_cases=0,
            top1_hit_rate=0.0,
            topk_hit_rate=0.0,
            avg_mrr=0.0,
            avg_required_coverage=0.0,
            total_required_hits=0,
            total_required_keywords=0,
            avg_noise_rate=0.0,
            total_noise=0,
            avg_pollution_rate=0.0,
            total_pollution=0,
            avg_preference_match_rate=0.0,
            total_preference_hits=0,
            total_preference_keywords=0,
            total_forbidden_hits=0,
            avg_latency_ms=0.0,
            overall_status=EvaluationStatus.PASSED,
        )
    
    top1_hits = sum(1 for r in results if r.top1_title_hit)
    topk_hits = sum(1 for r in results if r.topk_title_hit)
    total_noise = sum(r.noise_count for r in results)
    total_required_hits = sum(r.required_keyword_hits for r in results)
    total_required_keywords = sum(r.required_keyword_total for r in results)
    total_pollution = sum(r.pollution_count for r in results)
    total_preference_hits = sum(r.preference_match_count for r in results)
    total_preference_keywords = sum(r.preference_total for r in results)
    total_forbidden_hits = sum(r.forbidden_place_hits for r in results)
    
    # 计算平均值
    avg_mrr = sum(r.reciprocal_rank for r in results) / total
    avg_required_coverage = sum(r.required_coverage for r in results) / total
    avg_noise_rate = sum(r.noise_rate for r in results) / total
    avg_pollution_rate = sum(r.pollution_rate for r in results) / total
    avg_preference_match_rate = sum(r.preference_match_rate for r in results) / total
    avg_latency_ms = sum(r.latency_ms for r in results) / total
    
    # 确定总体状态
    overall_status = EvaluationStatus.PASSED
    if avg_noise_rate > 0.2 or avg_pollution_rate > 0.1 or avg_required_coverage < 0.7:
        overall_status = EvaluationStatus.WARNING
    if avg_required_coverage < 0.4 or total_forbidden_hits > 0:
        overall_status = EvaluationStatus.FAILED
    
    return AggregatedMetrics(
        total_cases=total,
        top1_hit_rate=top1_hits / total,
        topk_hit_rate=topk_hits / total,
        avg_mrr=avg_mrr,
        avg_required_coverage=avg_required_coverage,
        total_required_hits=total_required_hits,
        total_required_keywords=total_required_keywords,
        avg_noise_rate=avg_noise_rate,
        total_noise=total_noise,
        avg_pollution_rate=avg_pollution_rate,
        total_pollution=total_pollution,
        avg_preference_match_rate=avg_preference_match_rate,
        total_preference_hits=total_preference_hits,
        total_preference_keywords=total_preference_keywords,
        total_forbidden_hits=total_forbidden_hits,
        avg_latency_ms=avg_latency_ms,
        overall_status=overall_status,
    )


def _print_case_result(result: MetricsResult) -> None:
    status_emoji = {
        EvaluationStatus.PASSED: "✅",
        EvaluationStatus.WARNING: "⚠️",
        EvaluationStatus.FAILED: "❌",
    }
    emoji = status_emoji.get(result.status, "?")
    print(f"\n{emoji} Case: {result.case_id} [{result.status.value.upper()}]")
    print(f"  Destination: {result.case_id.split('_')[0]}")
    print(f"  Query: {result.query}")
    print(f"  Top1 Title: {result.top1_title}")
    print(f"  Top1 Hit: {'✅' if result.top1_title_hit else '❌'} | TopK Hit: {'✅' if result.topk_title_hit else '❌'}")
    print(f"  MRR: {result.mrr:.3f}")
    print(f"  Required Coverage: {result.required_keyword_hits}/{result.required_keyword_total} ({result.required_coverage*100:.1f}%)")
    print(f"  Preference Match: {result.preference_match_count}/{result.preference_total} ({result.preference_match_rate*100:.1f}%)")
    print(f"  Noise: {result.noise_count} ({result.noise_rate*100:.1f}%) | Pollution: {result.pollution_count} ({result.pollution_rate*100:.1f}%)")
    if result.forbidden_place_hits > 0:
        print(f"  ⚠️ FORBIDDEN HITS: {result.forbidden_place_hits}")
    print(f"  Latency: {result.latency_ms}ms")
    print(f"  Titles:")
    for index, title in enumerate(result.titles, start=1):
        print(f"    {index}. {title}")


def _print_summary_report(aggregated: AggregatedMetrics) -> None:
    status_emoji = {
        EvaluationStatus.PASSED: "✅",
        EvaluationStatus.WARNING: "⚠️",
        EvaluationStatus.FAILED: "❌",
    }
    overall_emoji = status_emoji.get(aggregated.overall_status, "?")
    
    print("\n" + "="*80)
    print(f"RAG EVALUATION SUMMARY {overall_emoji} [{aggregated.overall_status.value.upper()}]")
    print("="*80)
    print(f"Total Cases: {aggregated.total_cases}")
    print()
    
    print("📊 TRADITIONAL METRICS:")
    print(f"  Top1 Hit Rate:  {aggregated.top1_hit_rate*100:5.1f}%")
    print(f"  TopK Hit Rate:  {aggregated.topk_hit_rate*100:5.1f}%")
    print(f"  Average MRR:    {aggregated.avg_mrr:10.3f}")
    print()
    
    print("🎯 CONTENT QUALITY METRICS:")
    print(f"  Required Coverage: {aggregated.avg_required_coverage*100:5.1f}% ({aggregated.total_required_hits}/{aggregated.total_required_keywords})")
    print(f"  Preference Match:  {aggregated.avg_preference_match_rate*100:5.1f}% ({aggregated.total_preference_hits}/{aggregated.total_preference_keywords})")
    print()
    
    print("🔍 QUALITY CONTROL METRICS:")
    print(f"  Noise Rate: {aggregated.avg_noise_rate*100:.1f}% (Total: {aggregated.total_noise})")
    print(f"  Pollution Rate: {aggregated.avg_pollution_rate*100:.1f}% (Total: {aggregated.total_pollution})")
    if aggregated.total_forbidden_hits > 0:
        print(f"  ⚠️ FORBIDDEN PLACE HITS: {aggregated.total_forbidden_hits}")
    print()
    
    print("⚡ PERFORMANCE:")
    print(f"  Average Latency: {aggregated.avg_latency_ms:.1f}ms")
    print()
    
    print("💡 INTERPRETATION:")
    if aggregated.overall_status == EvaluationStatus.PASSED:
        print("  RAG system is working well!")
    elif aggregated.overall_status == EvaluationStatus.WARNING:
        print("  Some areas need improvement (noise/pollution/coverage).")
    else:
        print("  Critical issues detected! Please check the forbidden hits or coverage.")
    print("="*80)


def _dataclass_to_dict(obj) -> dict:
    """把数据类对象转换成字典，专门处理枚举类型"""
    from dataclasses import asdict
    result = asdict(obj)
    # 处理枚举类型，提取 value
    for key, value in result.items():
        if isinstance(value, Enum):
            result[key] = value.value
    return result

def _save_json_report(results: list[MetricsResult], aggregated: AggregatedMetrics, output_path: Path) -> None:
    """保存详细的 JSON 评估报告"""
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": _dataclass_to_dict(aggregated),
        "cases": [_dataclass_to_dict(r) for r in results],
    }
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 JSON report saved to: {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG retrieval quality with a small scenario case set."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to the RAG eval cases JSON file.",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=None,
        help="Path to save JSON report (optional)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = _load_cases(args.cases)
    
    print("="*80)
    print("Running RAG Evaluation...")
    print(f"Cases: {len(cases)}")
    print("="*80)
    
    results = [_evaluate_case(case) for case in cases]
    
    for result in results:
        _print_case_result(result)
    
    aggregated = _aggregate_results(results)
    _print_summary_report(aggregated)
    
    if args.json_report:
        _save_json_report(results, aggregated, args.json_report)
    
    # 返回失败的状态码（如果总体失败）
    if aggregated.overall_status == EvaluationStatus.FAILED:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
