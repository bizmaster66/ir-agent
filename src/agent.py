from google import genai
from google.genai import types
import io
import os
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

# Gemini 2.5 Flash 기본값 (필요 시 환경변수로 변경 가능)
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ✅ PROMPT_PAGE만 편향 방지 버전으로 교체 (코드 구조/로직은 그대로)
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
4. 명시적 추론(제한적 허용): 오직 팩트에 직접 근거하여, 심사역이 이해를 돕기 위한 최소 수준의 해석이 필요할 때만 아래 형식으로 1~2개 이내로 작성하십시오.
   - 반드시 라벨링 + 3단 구조를 사용하십시오.
   - 가능성/전망/평가/판단 표현은 금지입니다.

[명시적 추론 형식(강제)]
[추론]
- 팩트: (IR에 제시된 사실 요약)
- 해석: (팩트로부터 가능한 해석. 단, 단정/전망/평가 금지)
- 한계: (이 해석이 가지는 명확한 한계 또는 부족한 정보)

5. 요약 절대 금지: 평가 에이전트는 당신의 설명문만 보고 기업의 내용을 파악해야 합니다. 설명이 비면 판단이 왜곡됩니다. **불필요한 반복을 줄이고 핵심 정보를 빠짐없이 기술**하십시오. (길이 가이드: 페이지당 약 500~900자, 표/그래프가 복잡하면 더 길어도 됨)

[출력 형식]
## [Page {page_num}] Raw Data 정밀 분석 보고
- **데이터 식별 정보:** (페이지 타이틀 및 계층 구조)
- **객관적 데이터 복원:** (수치, 통계, 텍스트, 표/그래프/도표의 관찰 가능한 내용에 대한 정밀한 서술)
- **구조적 설명(도표/흐름):** (구성 요소 간 연결 관계와 작동 순서를 '관찰 가능한 형태'로 상세 기술)
- **명시적 추론(있는 경우에만):** (위 [추론] 형식 준수, 1~2개 이내)
"""

def run_ir_agent(api_key, images):
    client = genai.Client(api_key=api_key)
    
    def analyze_single_page(args):
        i, img = args
        
        # [속도 개선 핵심 1] 이미지 물리적 리사이징 (전송 용량 최적화)
        # 가로 1600px은 Gemini 3가 표를 읽기에 매우 넉넉하면서 용량은 가벼운 크기입니다.
        base_width = int(os.getenv("IR_IMAGE_WIDTH", "1400"))
        w_percent = (base_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
        
        img_byte = io.BytesIO()
        # 품질 80으로 압축하여 업로드 속도와 가독성 균형 유지
        img.save(img_byte, format='JPEG', quality=80, optimize=True)
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                PROMPT_PAGE.format(page_num=i+1),
                types.Part.from_bytes(data=img_byte.getvalue(), mime_type='image/jpeg')
            ]
        )
        return i, response.text

    # [속도 개선 핵심 2] 병렬 처리 (환경에 맞춰 조정 가능)
    max_workers = int(os.getenv("IR_MAX_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(analyze_single_page, enumerate(images)))
    
    results.sort(key=lambda x: x[0])
    page_results = [r[1] for r in results]
    combined_context = "\n\n".join(page_results)
    return combined_context, ""
