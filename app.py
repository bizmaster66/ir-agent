import streamlit as st
import os
import time
import pandas as pd
from dotenv import load_dotenv
from src.utils import convert_pdf_to_images, init_db, save_to_db, get_all_history, delete_history, check_cache
from src.agent import run_ir_agent
from src.drive_api import get_drive_files, download_drive_file, create_result_folder, upload_to_drive

# 환경변수 로드
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY") or (st.secrets["GEMINI_API_KEY"] if "GEMINI_API_KEY" in st.secrets else None)
init_db()

st.set_page_config(page_title="IR Data Agent", page_icon="📈", layout="wide")

st.title("📊 고밀도 IR 분석 플랫폼")

with st.sidebar:
    st.subheader("⚙️ 분석 설정")
    default_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    model = st.selectbox("Gemini 모델", ["gemini-2.5-flash", "gemini-2.5-pro"], index=0 if default_model == "gemini-2.5-flash" else 1)
    max_workers = st.number_input("IR_MAX_WORKERS (병렬 처리 수)", min_value=1, max_value=20, value=int(os.getenv("IR_MAX_WORKERS", "8")))
    batch_size = st.number_input("IR_BATCH_SIZE (배치 페이지 수)", min_value=1, max_value=12, value=int(os.getenv("IR_BATCH_SIZE", "6")))
    image_width = st.slider("IR_IMAGE_WIDTH (이미지 너비)", min_value=1000, max_value=2000, value=int(os.getenv("IR_IMAGE_WIDTH", "1400")), step=50)
    enable_routing = st.toggle("복잡 페이지 자동 PRO 라우팅", value=os.getenv("IR_ENABLE_MODEL_ROUTING", "1") == "1")
    pro_ratio = st.slider("IR_PRO_PAGE_RATIO (PRO 비율)", min_value=0.05, max_value=0.50, value=float(os.getenv("IR_PRO_PAGE_RATIO", "0.25")), step=0.05)
    st.caption("값이 높을수록 품질은 좋아지지만 속도는 느려집니다.")

os.environ["GEMINI_MODEL"] = model
os.environ["IR_MAX_WORKERS"] = str(max_workers)
os.environ["IR_BATCH_SIZE"] = str(batch_size)
os.environ["IR_IMAGE_WIDTH"] = str(image_width)
os.environ["IR_ENABLE_MODEL_ROUTING"] = "1" if enable_routing else "0"
os.environ["IR_PRO_PAGE_RATIO"] = str(pro_ratio)

tab1, tab2 = st.tabs(["📤 직접 업로드 및 히스토리", "☁️ 구글 드라이브 일괄 분석"])

# --- Tab 1: 직접 업로드 및 검색 가능한 히스토리 ---
with tab1:
    st.subheader("파일 업로드")
    uploaded_file = st.file_uploader("PDF 파일을 선택하세요", type="pdf", key="manual_upload")
    
    if uploaded_file:
        if st.button("🚀 즉시 분석", key="run_manual"):
            # 타이머 및 상태 표시용 컨테이너
            status_container = st.empty()
            start_time = time.time()
            perf = {}
            
            with st.status("분석 진행 중...") as s:
                # 1단계: 파일 로드
                t0 = time.perf_counter()
                pdf_content = uploaded_file.read()
                perf["upload_read_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                elapsed = int(time.time() - start_time)
                status_container.info(f"⏱️ 경과 시간: {elapsed}초 | PDF 파일을 읽고 있습니다...")
                
                # 2단계: 이미지 변환 (최적화된 utils 활용)
                t0 = time.perf_counter()
                images = convert_pdf_to_images(pdf_content)
                perf["pdf_to_image_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                elapsed = int(time.time() - start_time)
                status_container.info(f"⏱️ 경과 시간: {elapsed}초 | 이미지 변환 완료! Gemini AI 분석을 시작합니다...")
                
                # 3단계: AI 분석
                page_md, _, agent_metrics = run_ir_agent(API_KEY, images, return_metrics=True)
                perf["agent_wall_ms"] = agent_metrics["wall_ms_total"]
                t0 = time.perf_counter()
                save_to_db(uploaded_file.name, page_md, "")
                perf["db_save_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                perf["total_ms"] = round((time.time() - start_time) * 1000, 1)
                
                # 완료 리포트
                end_time = time.time()
                final_duration = int(end_time - start_time)
                status_container.success(f"✅ 분석 완료! (총 소요 시간: {final_duration}초)")
                st.session_state.last_manual_metrics = {"pipeline": perf, "agent": agent_metrics}
                st.balloons()
                time.sleep(2)
                st.rerun()

    st.divider()
    st.subheader("📜 분석 히스토리")
    history_df = get_all_history()
    
    if not history_df.empty:
        search_query = st.text_input("🔍 파일명 검색", placeholder="찾으시는 파일명을 입력하세요...")
        filtered_df = history_df[history_df['filename'].str.contains(search_query, case=False)] if search_query else history_df

        if not filtered_df.empty:
            h_col1, h_col2, h_col3, h_col4, h_col5 = st.columns([3, 2, 1, 1, 1])
            h_col1.write("**파일명**")
            h_col2.write("**분석 일시**")
            h_col3.write("**보기**")
            h_col4.write("**다운로드**")
            h_col5.write("**삭제**")
            
            for _, row in filtered_df.iterrows():
                c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
                c1.write(row['filename'])
                c2.write(row['analysis_date'])
                if c3.button("👁️", key=f"view_{row['id']}"):
                    st.session_state.current_view = {
                        "filename": row['filename'],
                        "page_detail": row['page_detail'],
                        "strategic_summary": row['strategic_summary']
                    }
                report_content = f"# {row['filename']} 분석 보고서\n\n{row['page_detail']}"
                c4.download_button(
                    "⬇️",
                    data=report_content,
                    file_name=f"{row['filename'].replace('.pdf', '')}_분석보고서.md",
                    mime="text/markdown",
                    key=f"download_{row['id']}"
                )
                if c5.button("🗑️", key=f"del_{row['id']}"):
                    delete_history(row['id'])
                    st.rerun()
        else:
            st.info("검색 결과가 없습니다.")
    else:
        st.info("아직 분석된 파일이 없습니다.")

# --- Tab 2: 구글 드라이브 일괄 분석 ---
with tab2:
    folder_id = st.text_input("📁 구글 드라이브 폴더 ID 입력", key="drive_id", placeholder="폴더 ID를 입력하세요")
    
    if folder_id:
        files = get_drive_files(folder_id)
        if files:
            unprocessed_files = [f for f in files if not check_cache(f['name'])]
            st.success(f"✅ 연결 성공! (총 {len(files)}개 파일 / 미분석 {len(unprocessed_files)}개)")
            
            if unprocessed_files:
                if st.button(f"🔥 미분석 {len(unprocessed_files)}건 일괄 분석 시작"):
                    res_folder_id = create_result_folder(folder_id)
                    
                    overall_start_time = time.time()
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    timer_text = st.empty() # 전체 타이머 표시용
                    
                    for idx, f in enumerate(unprocessed_files):
                        file_start_time = time.time()
                        percent = (idx + 1) / len(unprocessed_files)
                        progress_bar.progress(percent)
                        
                        status_text.info(f"🔄 ({idx+1}/{len(unprocessed_files)}) '{f['name']}' 분석 중...")
                        
                        try:
                            # 1단계: 다운로드
                            t0 = time.perf_counter()
                            pdf_bytes = download_drive_file(f['id'])
                            dl_ms = round((time.perf_counter() - t0) * 1000, 1)
                            
                            # 2단계: 이미지 변환
                            t0 = time.perf_counter()
                            images = convert_pdf_to_images(pdf_bytes)
                            conv_ms = round((time.perf_counter() - t0) * 1000, 1)
                            
                            # 3단계: AI 분석
                            p_md, _, agent_metrics = run_ir_agent(API_KEY, images, return_metrics=True)
                            t0 = time.perf_counter()
                            save_to_db(f['name'], p_md, "")
                            db_ms = round((time.perf_counter() - t0) * 1000, 1)
                            
                            # 4단계: 결과 업로드
                            full_report = f"# {f['name']} 분석 보고서\n\n{p_md}"
                            t0 = time.perf_counter()
                            upload_to_drive(res_folder_id, f['name'], full_report)
                            up_ms = round((time.perf_counter() - t0) * 1000, 1)
                            
                            # 개별 파일 시간 및 누적 시간 표시
                            file_dur = int(time.time() - file_start_time)
                            total_dur = int(time.time() - overall_start_time)
                            timer_text.markdown(
                                f"**⏱️ 최근 파일:** {file_dur}초 | **누적:** {total_dur}초  \n"
                                f"`download={dl_ms}ms / convert={conv_ms}ms / agent={agent_metrics['wall_ms_total']}ms / db={db_ms}ms / upload={up_ms}ms`"
                            )
                            
                        except Exception as e:
                            st.error(f"파일 {f['name']} 처리 중 오류 발생: {e}")
                        
                    status_text.success(f"🎉 모든 파일 분석 완료! (총 소요 시간: {int(time.time() - overall_start_time)}초)")
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
    with t1:
        if v.get('strategic_summary'):
            st.markdown(v['strategic_summary'])
        else:
            st.info("통합 리포트는 현재 비활성화되어 있습니다.")
    with t2:
        st.markdown(v['page_detail'])

if "last_manual_metrics" in st.session_state:
    st.divider()
    st.subheader("📈 최근 실행 메트릭")
    st.json(st.session_state.last_manual_metrics)
