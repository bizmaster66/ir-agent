import streamlit as st
import os
import pandas as pd
from dotenv import load_dotenv
from src.utils import convert_pdf_to_images, init_db, save_to_db, get_all_history, delete_history
from src import run_ir_agent

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# 데이터베이스 초기화
init_db()

st.set_page_config(page_title="IR Evaluation Data Agent", page_icon="📈", layout="wide")

# 사이드바 히스토리
with st.sidebar:
    st.header("🗄️ 분석 아카이브")
    history_df = get_all_history()
    
    if history_df.empty:
        st.write("저장된 기록이 없습니다.")
    else:
        csv = history_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 전체 내역 CSV 받기", csv, "ir_history.csv", "text/csv")
        st.divider()

        history_df['date_only'] = history_df['analysis_date'].str[:10]
        for date in history_df['date_only'].unique():
            with st.expander(f"📅 {date}", expanded=False):
                daily_df = history_df[history_df['date_only'] == date]
                for _, row in daily_df.iterrows():
                    col_file, col_del = st.columns([4, 1])
                    with col_file:
                        if st.button(f"📄 {row['filename'][:15]}", key=f"v_{row['id']}"):
                            st.session_state.current_view = row.to_dict()
                    with col_del:
                        if st.button("🗑️", key=f"d_{row['id']}"):
                            delete_history(row['id'])
                            st.rerun()

st.title("📊 Gemini 3 고밀도 IR 분석 에이전트")
st.info("이 에이전트는 평가 에이전트용 '고밀도 원천 데이터'를 생성하기 위해 최적화되었습니다.")

uploaded_file = st.file_uploader("분석할 IR PDF를 업로드하세요", type="pdf")

if uploaded_file and API_KEY:
    if st.button("🚀 고속 심층 분석 시작"):
        try:
            with st.status("Gemini 3 엔진 가동 중 (15개 스레드 병렬 처리)...", expanded=True) as status:
                st.write("📸 이미지 변환 및 최적화 중...")
                # 파일 읽기 후 포인터 초기화
                file_content = uploaded_file.read()
                images = convert_pdf_to_images(file_content)
                
                st.write(f"🧠 {len(images)}개 페이지 동시 분석 중 (유료 티어 고속 모드)...")
                page_md, total_md = run_ir_agent(API_KEY, images)
                
                save_to_db(uploaded_file.name, page_md, total_md)
                status.update(label="✅ 분석 완료!", state="complete", expanded=False)
                
                # 즉시 보기 위해 세션 업데이트
                st.session_state.current_view = {
                    "filename": uploaded_file.name,
                    "page_detail": page_md,
                    "strategic_summary": total_md
                }
                st.rerun()
        except Exception as e:
            st.error(f"오류 발생: {e}")

# 결과 표시 및 마크다운 다운로드 섹션
if "current_view" in st.session_state:
    view = st.session_state.current_view
    st.divider()
    
    col_title, col_down = st.columns([3, 1])
    with col_title:
        st.header(f"📂 분석 결과: {view['filename']}")
    
    with col_down:
        # 다운로드할 마크다운 합치기
        full_markdown = f"# IR 분석 리포트: {view['filename']}\n\n"
        full_markdown += f"## 1. 7대 기준 전략 통합 보고서\n\n{view['strategic_summary']}\n\n"
        full_markdown += f"## 2. 페이지별 고밀도 원천 데이터\n\n{view['page_detail']}"
        
        st.download_button(
            label="📥 마크다운(.md) 다운로드",
            data=full_markdown,
            file_name=f"IR_Analysis_{view['filename']}.md",
            mime="text/markdown"
        )
    
    t1, t2 = st.tabs(["📄 고밀도 원천 데이터 (평가용)", "🎯 7대 기준 전략 통합 보고서"])
    with t1:
        st.markdown(view['page_detail'])
    with t2:
        st.markdown(view['strategic_summary'])