import streamlit as st
import os
import time
import pandas as pd
from dotenv import load_dotenv
from src.utils import convert_pdf_to_images, init_db, save_to_db, get_all_history, delete_history, check_cache
from src.agent import run_ir_agent
from src.drive_api import get_drive_files, download_drive_file, create_result_folder, upload_to_drive

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
init_db()

st.set_page_config(page_title="IR Data Agent", page_icon="📈", layout="wide")

st.title("📊 고밀도 IR 분석 플랫폼")

tab1, tab2 = st.tabs(["📤 직접 업로드 및 히스토리", "☁️ 구글 드라이브 일괄 분석"])

# --- Tab 1: 직접 업로드 및 검색 가능한 히스토리 ---
with tab1:
    st.subheader("파일 업로드")
    uploaded_file = st.file_uploader("PDF 파일을 선택하세요", type="pdf", key="manual_upload")
    
    if uploaded_file:
        if st.button("🚀 즉시 분석", key="run_manual"):
            with st.status("분석 진행 중...") as s:
                pdf_content = uploaded_file.read()
                images = convert_pdf_to_images(pdf_content)
                page_md, total_md = run_ir_agent(API_KEY, images)
                save_to_db(uploaded_file.name, page_md, total_md)
                st.success(f"'{uploaded_file.name}' 분석 완료!")
                st.rerun()

    st.divider()
    st.subheader("📜 분석 히스토리")
    history_df = get_all_history()
    
    if not history_df.empty:
        search_query = st.text_input("🔍 파일명 검색", placeholder="찾으시는 파일명을 입력하세요...")
        filtered_df = history_df[history_df['filename'].str.contains(search_query, case=False)] if search_query else history_df

        if not filtered_df.empty:
            h_col1, h_col2, h_col3, h_col4 = st.columns([3, 2, 1, 1])
            h_col1.write("**파일명**")
            h_col2.write("**분석 일시**")
            h_col3.write("**보기**")
            h_col4.write("**삭제**")
            
            for _, row in filtered_df.iterrows():
                c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                c1.write(row['filename'])
                c2.write(row['analysis_date'])
                if c3.button("👁️", key=f"view_{row['id']}"):
                    st.session_state.current_view = {
                        "filename": row['filename'],
                        "page_detail": row['page_detail'],
                        "strategic_summary": row['strategic_summary']
                    }
                if c4.button("🗑️", key=f"del_{row['id']}"):
                    delete_history(row['id'])
                    st.rerun()
        else:
            st.info("검색 결과가 없습니다.")
    else:
        st.info("아직 분석된 파일이 없습니다.")

# --- Tab 2: 구글 드라이브 일괄 분석 ---
with tab2:
    folder_id = st.text_input("📁 구글 드라이브 폴더 ID 입력", key="drive_id")
    
    if folder_id:
        files = get_drive_files(folder_id)
        if files:
            unprocessed_files = [f for f in files if not check_cache(f['name'])]
            st.success(f"✅ 연결 성공! (총 {len(files)}개 파일 / 미분석 {len(unprocessed_files)}개)")
            
            if unprocessed_files:
                if st.button(f"🔥 미분석 {len(unprocessed_files)}건 일괄 분석 시작"):
                    # 결과 폴더 ID 확인/생성
                    res_folder_id = create_result_folder(folder_id)
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for idx, f in enumerate(unprocessed_files):
                        percent = (idx + 1) / len(unprocessed_files)
                        progress_bar.progress(percent)
                        status_text.info(f"🔄 ({idx+1}/{len(unprocessed_files)}) {f['name']} 분석 중...")
                        
                        # 분석 실행
                        pdf_bytes = download_drive_file(f['id'])
                        images = convert_pdf_to_images(pdf_bytes)
                        p_md, t_md = run_ir_agent(API_KEY, images)
                        
                        # 로컬 DB 저장
                        save_to_db(f['name'], p_md, t_md)
                        
                        # 구글 드라이브 업로드 (안정화된 함수 호출)
                        full_report = f"# {f['name']} 분석 보고서\n\n{t_md}\n\n{p_md}"
                        upload_to_drive(res_folder_id, f['name'], full_report)
                        
                    status_text.success("🎉 모든 파일의 일괄 분석 및 업로드가 완료되었습니다!")
                    time.sleep(2)
                    st.rerun()
            else:
                st.info("모든 파일이 이미 분석되었습니다.")

# --- 결과 출력 섹션 ---
if "current_view" in st.session_state:
    v = st.session_state.current_view
    st.divider()
    col_title, col_close = st.columns([9, 1])
    col_title.header(f"🔍 분석 결과: {v['filename']}")
    if col_close.button("닫기 ✖️"):
        del st.session_state.current_view
        st.rerun()
    
    t1, t2 = st.tabs(["🎯 전략 통합 리포트", "📄 페이지별 데이터"])
    with t1: st.markdown(v['strategic_summary'])
    with t2: st.markdown(v['page_detail'])