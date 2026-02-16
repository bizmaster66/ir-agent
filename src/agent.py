from google import genai
from google.genai import types
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageFilter, ImageStat

PROMPT_PAGE = """
당신은 IR 자료를 정밀 분석하여 '평가 에이전트'가 판단을 내릴 수 있도록 원천 데이터를 복원하는 데이터 엔지니어이자 전문 분석가입니다.

[핵심 원칙: 편향/환각 방지]
- IR 페이지(이미지)에 **명시된 내용만** 서술하십시오. IR에 없는 내용은 생성/추정/보완하지 마십시오.
- **투자 매력도/추천/종합 판단**은 절대 금지입니다.
- “리스크가 낮다/높다”, “우수하다/A급”, “성공 가능성”, “확장 가능”, “기대된다/가능하다” 등 **평가·가능성·전망 표현**은 절대 금지입니다.
- **창업자의 의도/전략적 판단**을 추정하지 마십시오.
- 고유명사는 **페이지에 실제로 등장한 회사명/제품명/서비스명 표기 그대로만** 사용하십시오. (변형/약칭/유사명 혼입 금지)

[수행 지침]
1. 정보 손실 제로(팩트 복원): 페이지 내의 모든 타이틀, 본문 텍스트, 표의 항목/값, 그래프에서 읽히는 수치(축/범례/데이터 포인트), 도표의 구성 요소, 하단 주석의 상세 내용까지 **단 하나도 누락하지 말고** 문장으로 기술하십시오.
2. 시각 요소의 텍스트화(구조 설명): 복잡한 비즈니스 모델 도표나 프로세스 맵/플로우차트는, 구성 요소(노드)와 연결(화살표/흐름/입출력)을 **관찰 가능한 형태 그대로** 논리적 순서에 따라 상세히 설명하십시오.
   - 금지: “이 구조는 ~를 가능하게 한다/유도한다/증명한다” 같은 효과·인과·가치 판단
3. 수치/지표의 서술 규칙:
   - 표/그래프에서 직접 읽히는 경우에만 수치를 적으십시오.
   - 비교/증감/추세는 **그래프 축과 데이터 포인트에서 직접 확인되는 범위**에서만 서술하십시오.
   - “~때문에”, “~로 인해”, “~을 입증” 같은 인과 단정 표현 금지
4. 전달 의도/맥락(약한 추론): 페이지의 텍스트/시각 요소에서 직접 확인 가능한 근거만 사용해, 작성자가 강조하려는 메시지를 2~4문장으로 정리하십시오.
   - 반드시 관찰된 근거를 먼저 제시하고, 해석은 단정 없이 제한적으로 작성하십시오.
   - 강한 전망/평가/투자판단 문구는 금지입니다.

[출력 형식]
## [Page {page_num}] Raw Data 정밀 분석 보고
- **데이터 식별 정보:** (페이지 타이틀 및 계층 구조)
- **객관적 데이터 복원:** (수치, 통계, 텍스트, 표/그래프/도표의 관찰 가능한 내용에 대한 정밀한 서술)
- **구조적 설명(도표/흐름):** (구성 요소 간 연결 관계와 작동 순서를 '관찰 가능한 형태'로 상세 기술)
- **전달 의도/맥락(약한 추론):** (관찰 근거 1~2개 + 해석 2~4문장)
"""


def _estimate_visual_complexity(img):
    """Return a lightweight complexity score for routing dense pages to pro."""
    thumb = img.convert("L")
    thumb.thumbnail((320, 320))
    edge = thumb.filter(ImageFilter.FIND_EDGES)

    edge_mean = ImageStat.Stat(edge).mean[0]
    contrast = ImageStat.Stat(thumb).stddev[0]
    return (edge_mean * 0.7) + (contrast * 0.3)


def _build_page_plan(images, base_model):
    enable_routing = os.getenv("IR_ENABLE_MODEL_ROUTING", "1") == "1"
    pro_model = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro")
    complexity_threshold = float(os.getenv("IR_PRO_COMPLEXITY_THRESHOLD", "36"))
    pro_ratio = float(os.getenv("IR_PRO_PAGE_RATIO", "0.25"))

    complexities = [_estimate_visual_complexity(img) for img in images]
    plan = [base_model] * len(images)

    if not enable_routing or not base_model.endswith("flash"):
        return plan, complexities

    candidates = [
        (idx, score) for idx, score in enumerate(complexities)
        if score >= complexity_threshold
    ]
    candidates.sort(key=lambda x: x[1], reverse=True)

    max_pro_pages = max(1, int(len(images) * pro_ratio)) if images else 0
    for idx, _ in candidates[:max_pro_pages]:
        plan[idx] = pro_model

    return plan, complexities


def run_ir_agent(api_key, images, return_metrics=False):
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    base_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    image_width = int(os.getenv("IR_IMAGE_WIDTH", "1400"))
    max_workers = int(os.getenv("IR_MAX_WORKERS", "8"))
    batch_size = max(1, int(os.getenv("IR_BATCH_SIZE", "6")))

    client = genai.Client(api_key=api_key)
    page_plan, complexities = _build_page_plan(images, base_model)

    started_at = time.perf_counter()
    results = []
    preprocess_ms_total = 0.0
    api_ms_total = 0.0

    def analyze_single_page(args):
        i, img = args

        prep_start = time.perf_counter()
        w_percent = (image_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((image_width, h_size), Image.Resampling.LANCZOS)

        img_byte = io.BytesIO()
        img.save(img_byte, format="JPEG", quality=80, optimize=True)
        prep_ms = (time.perf_counter() - prep_start) * 1000

        model_for_page = page_plan[i]
        api_start = time.perf_counter()
        response = client.models.generate_content(
            model=model_for_page,
            contents=[
                PROMPT_PAGE.format(page_num=i + 1),
                types.Part.from_bytes(data=img_byte.getvalue(), mime_type="image/jpeg"),
            ],
        )
        api_ms = (time.perf_counter() - api_start) * 1000

        return {
            "idx": i,
            "text": response.text,
            "model": model_for_page,
            "prep_ms": prep_ms,
            "api_ms": api_ms,
        }

    indexed = list(enumerate(images))
    for start in range(0, len(indexed), batch_size):
        batch = indexed[start:start + batch_size]
        batch_workers = min(max_workers, len(batch))
        with ThreadPoolExecutor(max_workers=batch_workers) as executor:
            batch_results = list(executor.map(analyze_single_page, batch))
        results.extend(batch_results)

    results.sort(key=lambda x: x["idx"])
    for r in results:
        preprocess_ms_total += r["prep_ms"]
        api_ms_total += r["api_ms"]

    page_results = [r["text"] for r in results]
    combined_context = "\n\n".join(page_results)
    total_wall_ms = (time.perf_counter() - started_at) * 1000

    model_counts = {}
    for r in results:
        model_counts[r["model"]] = model_counts.get(r["model"], 0) + 1

    metrics = {
        "pages": len(images),
        "batch_size": batch_size,
        "batches": (len(images) + batch_size - 1) // batch_size if batch_size else 0,
        "max_workers": max_workers,
        "preprocess_ms_total": round(preprocess_ms_total, 1),
        "api_ms_total": round(api_ms_total, 1),
        "wall_ms_total": round(total_wall_ms, 1),
        "model_counts": model_counts,
        "complexity_avg": round(sum(complexities) / len(complexities), 2) if complexities else 0,
    }

    if return_metrics:
        return combined_context, "", metrics
    return combined_context, ""
