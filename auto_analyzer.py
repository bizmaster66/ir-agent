import os
import io
import time
import json
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account
from src.agent import run_ir_agent  # 기존에 만든 분석 로직 재사용
from src.utils import convert_pdf_to_images
from dotenv import load_dotenv

load_dotenv()

# --- [설정 세팅] ---
API_KEY = os.getenv("GEMINI_API_KEY")
SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

# 구글 드라이브 폴더 ID (구글 드라이브 접속 시 주소창 뒷부분의 긴 문자열)
# 예: https://drive.google.com/drive/u/0/folders/1ABCDEFG... 에서 1ABCDEFG... 부분
WATCH_FOLDER_ID = '0AAPErCGTYkVPUk9PVA' 

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def download_file(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return fh.getvalue()

def upload_markdown(service, filename, content, parent_id):
    file_metadata = {
        'name': f"[분석완료] {filename.replace('.pdf', '')}.md",
        'parents': [parent_id]
    }
    media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), 
                              mimetype='text/markdown')
    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def process_files():
    service = get_drive_service()
    
    # 1. 감시 폴더에서 PDF 파일만 조회 (이미 분석된 파일 중복 방지를 위해 이름 필터링 활용 가능)
    query = f"'{WATCH_FOLDER_ID}' in parents and mimeType='application/pdf' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])

    if not items:
        return

    print(f"[{datetime.now()}] 총 {len(items)}개의 분석 대기 파일을 발견했습니다.")

    for item in items:
        file_name = item['name']
        file_id = item['id']
        
        # 파일명이 '[분석중]'으로 시작하면 건너뜀 (이미 처리 중인 파일)
        if file_name.startswith("[분석중]"):
            continue

        print(f"🚀 분석 시작: {file_name}")
        
        try:
            # 상태 표시를 위해 이름 일시 변경
            service.files().update(fileId=file_id, body={'name': f"[분석중] {file_name}"}).execute()
            
            # 파일 다운로드
            pdf_bytes = download_file(service, file_id)
            
            # 이미지 변환
            images = convert_pdf_to_images(pdf_bytes)
            
            # Gemini 3 고밀도 분석 엔진 실행 (기존 src.agent 활용)
            page_md, total_md = run_ir_agent(API_KEY, images)
            
            # 최종 마크다운 구성
            full_markdown = f"# IR 분석 리포트: {file_name}\n\n"
            full_markdown += f"## 🎯 전략 통합 보고서\n\n{total_md}\n\n"
            full_markdown += f"## 📄 페이지별 상세 데이터\n\n{page_md}"
            
            # 구글 드라이브에 업로드
            upload_markdown(service, file_name, full_markdown, WATCH_FOLDER_ID)
            
            # 분석 완료 후 원본 파일 이름 변경 혹은 삭제 (여기서는 이름 변경)
            service.files().update(fileId=file_id, body={'name': f"[완료] {file_name}"}).execute()
            print(f"✅ 분석 완료 및 마크다운 생성: {file_name}")
            
        except Exception as e:
            print(f"❌ {file_name} 처리 중 오류 발생: {e}")
            service.files().update(fileId=file_id, body={'name': f"[오류] {file_name}"}).execute()

if __name__ == '__main__':
    print("🤖 IR-Auto-script 실시간 감시 모드 가동 중...")
    while True:
        try:
            process_files()
        except Exception as e:
            print(f"⚠️ 시스템 오류: {e}")
        
        # 30초마다 폴더 체크
        time.sleep(30)