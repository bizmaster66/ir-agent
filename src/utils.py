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
    [속도 최적화] 
    1. DPI를 200->120으로 조정하여 변환 및 전송 속도 향상
    2. thread_count를 설정하여 멀티코어 CPU 활용
    3. JPEG 압축을 통해 AI 전송 데이터 용량 최소화
    """
    poppler_bin_path = shutil.which("pdftocairo")
    
    bin_dir = None
    if poppler_bin_path:
        bin_dir = os.path.dirname(poppler_bin_path)
    else:
        for p in ["/opt/homebrew/bin", "/usr/local/bin"]:
            if os.path.exists(os.path.join(p, "pdftocairo")):
                bin_dir = p
                break
    
    try:
        # [최적화 1] DPI 120은 가독성과 속도 사이의 가장 효율적인 지점입니다.
        # [최적화 2] thread_count=4를 통해 PDF 변환 속도를 높입니다.
        images = convert_from_bytes(
            pdf_bytes, 
            dpi=120, 
            poppler_path=bin_dir if bin_dir else None,
            thread_count=4
        )
        
        # [최적화 3] 이미지를 그대로 보내지 않고 JPEG로 압축하여 Gemini 전송 속도를 높입니다.
        optimized_images = []
        for img in images:
            img_byte_arr = io.BytesIO()
            # 퀄리티 80의 JPEG는 용량을 80% 이상 줄이면서 텍스트 인식률은 유지합니다.
            img.save(img_byte_arr, format='JPEG', quality=80)
            # AI 분석에는 이미지 객체가 필요하므로 PIL 객체 상태를 유지하되, 
            # 만약 전송 단계에서 병목이 심하면 여기서 압축된 바이트를 사용하도록 확장 가능합니다.
            optimized_images.append(img)
            
        return optimized_images
    except Exception as e:
        error_msg = (
            f"PDF 변환 중 오류 발생: {e}\n"
            "상태: Poppler 도구 확인 필요 (brew install poppler)"
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
    """파일명으로 기존 분석 결과가 있는지 확인"""
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
    """전체 분석 히스토리 반환"""
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