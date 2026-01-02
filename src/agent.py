from google import genai
from google.genai import types
import io
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

# Gemini 3 Flash 모델 적용
MODEL_NAME = "gemini-2.5-pro" 

# [질문자님 프롬프트 원안 100% 유지]
PROMPT_PAGE = """
당신은 IR 자료를 정밀 분석하여 '평가 에이전트'가 판단을 내릴 수 있도록 원천 데이터를 복원하는 데이터 엔지니어이자 전문 분석가입니다. 

[수행 지침]
1. 정보 손실 제로: 페이지 내의 모든 타이틀, 핵심 지표, 그래프의 좌표값, 시각적 도표의 구성 요소, 하단 주석의 상세 내용까지 단 하나도 누락하지 말고 '상세한 문장'으로 기술하십시오.
2. 논리적 인과관계 복원: "A 그래프가 상승하고 있다"가 아니라, "A 지표가 X 시점부터 Y 시점까지 Z% 상승한 것은 기업의 B 전략이 시장에서 C라는 결과로 이어졌음을 입증하는 데이터임"과 같이 인과관계를 구체적으로 서술하십시오.
3. 시각 요소의 텍스트화: 복잡한 비즈니스 모델 도표나 프로세스 맵을 평가 에이전트가 이해할 수 있도록, 구성 요소 간의 연결 고리와 작동 원리를 논리적 순서에 따라 장황할 정도로 상세히 설명하십시오.
4. 요약 절대 금지: 평가 에이전트는 당신의 설명문만 보고 기업의 가치를 판단해야 합니다. 설명이 비면 평가가 왜곡됩니다. 페이지당 최소 1,000자 이상의 고밀도 텍스트 생성을 목표로 하십시오.

[출력 형식]
## [Page {page_num}] Raw Data 정밀 분석 보고
- **데이터 식별 정보:** (페이지 타이틀 및 계층 구조)
- **객관적 데이터 복원:** (수치, 통계, 텍스트의 정밀한 서술)
- **전략 및 논리적 근거:** (데이터가 시사하는 전략적 의미와 인과관계의 상세 기술)
"""

PROMPT_TOTAL = """
당신은 수석 IR 평가 전략가입니다. 개별 페이지에서 추출된 고밀도 데이터를 바탕으로, 향후 '평가 에이전트'가 심층 진단을 내릴 수 있도록 7대 핵심 기준에 맞춰 정보를 완벽하게 재구성하십시오.

[통합 분석 지침]
1. 7대 기준별 입체 서술: 각 기준(problem_definition 등)에 대해 개별 페이지에 흩어진 파편화된 정보를 모아 하나의 거대한 '전략 기술서'로 만드십시오. 
2. 평가를 위한 근거 강화: 평가 에이전트가 "시장 규모가 타당한가?", "경쟁 우위가 확실한가?"를 검증할 수 있도록, 자료 내의 모든 증거(Evidence)를 해당 항목 아래에 논리적으로 배치하십시오.
3. 구체성의 극대화: 단순한 문장이 아닌, 각 항목당 백서(Whitepaper) 수준의 디테일을 확보하십시오. 정보가 부족한 부분은 "자료상 미기재됨"을 명시하여 평가 에이전트가 오판하지 않게 하십시오.
4. 전문 용어의 보존: 원문에 사용된 산업 전문 용어와 고유 지표를 정확하게 유지하여 데이터의 전문성을 보존하십시오.

[출력 형식]
# [종합] IR 전략 체계 및 원천 데이터 통합 보고서
---
(7대 기준별로 자료의 모든 근거와 수치를 포함한 방대한 분량의 설명문 작성)
"""

def run_ir_agent(api_key, images):
    client = genai.Client(api_key=api_key)
    
    def analyze_single_page(args):
        i, img = args
        
        # [속도 개선 핵심 1] 이미지 물리적 리사이징 (전송 용량 최적화)
        # 가로 1600px은 Gemini 3가 표를 읽기에 매우 넉넉하면서 용량은 가벼운 크기입니다.
        base_width = 1600
        w_percent = (base_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
        
        img_byte = io.BytesIO()
        # 품질 85로 압축하여 업로드 속도 극대화
        img.save(img_byte, format='JPEG', quality=85, optimize=True)
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                PROMPT_PAGE.format(page_num=i+1),
                types.Part.from_bytes(data=img_byte.getvalue(), mime_type='image/jpeg')
            ]
        )
        return i, response.text

    # [속도 개선 핵심 2] 유료 사용자를 위한 고성능 병렬 스레드 (max_workers=15)
    # 한 페이지씩 기다리지 않고 15개 페이지를 동시에 전송합니다.
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(analyze_single_page, enumerate(images)))
    
    results.sort(key=lambda x: x[0])
    page_results = [r[1] for r in results]
    combined_context = "\n\n".join(page_results)
    
    # 최종 통합 리포트 생성
    final_response = client.models.generate_content(
        model=MODEL_NAME,
        contents=PROMPT_TOTAL + f"\n\n[페이지별 고밀도 원천 데이터]\n{combined_context}"
    )
    
    return combined_context, final_response.text