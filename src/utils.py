import io
import os
import shutil
import sqlite3
import pandas as pd
from datetime import datetime
from pdf2image import convert_from_bytes

DB_PATH = "data/history.db"

def convert_pdf_to_images(pdf_bytes):
    """
    PDF 바이너리를 이미지 리스트로 변환합니다.
    로컬(Mac/Win) 및 클라우드(Linux) 환경의 Poppler 경로 차이를 자동으로 해결합니다.
    """
    # 1. 시스템 PATH에서 pdftocairo(Poppler 핵심파일) 위치 검색
    poppler_bin_path = shutil.which("pdftocairo")
    
    bin_dir = None
    if poppler_bin_path:
        # 시스템이 이미 경로를 알고 있는 경우
        bin_dir = os.path.dirname(poppler_bin_path)
    else:
        # 2. 로컬 Mac 환경에서 흔히 설치되는 경로 강제 탐색 (Homebrew 경로)
        possible_mac_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
        for p in possible_mac_paths:
            if os.path.exists(os.path.join(p, "pdftocairo")):
                bin_dir = p
                break
    
    try:
        if bin_dir:
            # 탐색된 경로를 사용하여 변환
            images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=bin_dir)
        else:
            # 경로를 못 찾은 경우 시스템 기본값에 의존 (Streamlit Cloud 등)
            images = convert_from_bytes(pdf_bytes, dpi=200)
        return images
    except Exception as e:
        error_msg = (
            f"PDF 변환 중 오류 발생: {e}\n"
            "상태: Poppler(pdftocairo)를 찾을 수 없습니다.\n"
            "해결방법: 터미널에서 'brew install poppler'를 실행했는지 확인해 주세요."
        )
        raise Exception(error_msg)

def init_db():
    """DB 초기화: 데이터 폴더 및 히스토리 테이블 생성"""
    if not os.path.exists('data'):
        os.makedirs('data')
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ir_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            analysis_date TEXT,
            page_detail TEXT,
            strategic_summary TEXT
        )
    """)
    conn.commit()
    conn.close()

def check_cache(filename):
    """파일명으로 기존 분석 결과가 있는지 확인 (중복 분석 방지)"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT page_detail, strategic_summary FROM ir_history WHERE filename = ?", (filename,))
    result = cur.fetchone()
    conn.close()
    return result

def save_to_db(filename, page_md, total_md):
    """분석 완료된 데이터를 DB에 저장"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO ir_history (filename, analysis_date, page_detail, strategic_summary) 
        VALUES (?, ?, ?, ?)
    """, (filename, now, page_md, total_md))
    conn.commit()
    conn.close()

def get_all_history():
    """전체 분석 히스토리를 데이터프레임으로 반환"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM ir_history ORDER BY analysis_date DESC", conn)
    conn.close()
    return df

def delete_history(record_id):
    """특정 히스토리 기록 삭제"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM ir_history WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()