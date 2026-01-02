import io
import os
import shutil
import sqlite3
import pandas as pd
from datetime import datetime
from pdf2image import convert_from_bytes

DB_PATH = "data/history.db"

def convert_pdf_to_images(pdf_bytes):
    """PDF를 고해상도 이미지로 변환합니다. 속도를 위해 최적 DPI를 설정합니다."""
    poppler_bin_path = shutil.which("pdftocairo")
    
    if not poppler_bin_path:
        possible_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
        for p in possible_paths:
            if os.path.exists(os.path.join(p, "pdftocairo")):
                poppler_bin_path = p
                break

    try:
        # 유료 사용자의 경우 처리 속도를 위해 DPI 200 설정을 유지하되 
        # 나중에 agent에서 물리적 크기를 리사이징하여 속도를 높입니다.
        if poppler_bin_path:
            actual_path = os.path.dirname(poppler_bin_path) if "/" in poppler_bin_path else poppler_bin_path
            images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=actual_path)
        else:
            images = convert_from_bytes(pdf_bytes, dpi=200)
        return images
    except Exception as e:
        raise Exception(f"PDF 변환 중 오류 발생: {e}")

def init_db():
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

def save_to_db(filename, page_md, total_md):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO ir_history (filename, analysis_date, page_detail, strategic_summary) VALUES (?, ?, ?, ?)",
                (filename, now, page_md, total_md))
    conn.commit()
    conn.close()

def get_all_history():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM ir_history ORDER BY analysis_date DESC", conn)
    conn.close()
    return df

def delete_history(record_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM ir_history WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()