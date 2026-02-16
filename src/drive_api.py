import os
import io
import streamlit as st
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """
    구글 드라이브 서비스 객체 생성.
    로컬의 json 파일 혹은 Streamlit Cloud의 Secrets 설정을 자동으로 탐색하며,
    키 형식 오류를 방지하기 위해 문자열을 자동 정제합니다.
    """
    creds = None
    
    # 1. 로컬 환경: service_account.json 파일이 있는 경우
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    
    # 2. 클라우드 배포 환경: Streamlit Secrets에 설정이 있는 경우
    elif "gcp_service_account" in st.secrets:
        creds_info = dict(st.secrets["gcp_service_account"])
        
        if "private_key" in creds_info:
            # 중요: TOML과 JSON 간의 이스케이프 문자(\n) 충돌을 방지하기 위한 정제 로직
            key = creds_info["private_key"]
            # 리터럴 \n 문자를 실제 줄바꿈 문자로 변경
            key = key.replace("\\n", "\n")
            # 앞뒤 불필요한 공백 제거
            creds_info["private_key"] = key.strip()
            
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=SCOPES)
            
    if not creds:
        st.error("❌ 구글 서비스 계정 인증 정보가 없습니다. (json 파일 또는 Secrets 확인 필요)")
        return None
        
    return build('drive', 'v3', credentials=creds)

def get_drive_files(folder_id):
    """특정 폴더의 PDF 목록 가져오기"""
    service = get_drive_service()
    if not service: return []
    try:
        with st.expander("🔍 연결 상세 정보"):
            # 인증된 계정 이메일 노출 (진단용)
            email = ""
            if os.path.exists(SERVICE_ACCOUNT_FILE):
                temp_creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
                email = temp_creds.service_account_email
            elif "gcp_service_account" in st.secrets:
                email = st.secrets["gcp_service_account"]["client_email"]
            
            st.write(f"봇 계정: {email}")
            folder = service.files().get(fileId=folder_id, fields="name", supportsAllDrives=True).execute()
            st.write(f"연결된 폴더: {folder['name']}")

        query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        results = service.files().list(
            q=query, 
            fields="files(id, name)", 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        return results.get('files', [])
    except Exception as e:
        st.error(f"드라이브 연결 오류: {e}")
        return []

def create_result_folder(parent_id):
    """결과물 저장용 폴더 생성"""
    service = get_drive_service()
    if not service: return None
    
    query = f"name = '[Analysis_Results]' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    folders = results.get('files', [])
    
    if folders:
        return folders[0]['id']
    
    file_metadata = {
        'name': '[Analysis_Results]',
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
    return folder.get('id')

def upload_to_drive(folder_id, filename, content):
    """결과 마크다운 업로드 (안정적인 세션 유지를 위해 내부에서 서비스 생성)"""
    try:
        service = get_drive_service()
        if not service:
            return False
        
        file_metadata = {
            'name': f"{filename.replace('.pdf', '')}_분석보고서.md",
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode('utf-8')), 
            mimetype='text/markdown',
            resumable=True
        )
        service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id', 
            supportsAllDrives=True
        ).execute()
        return True
    except Exception as e:
        st.error(f"드라이브 업로드 중 오류 발생: {e}")
        return False

def download_drive_file(file_id):
    """파일 다운로드"""
    service = get_drive_service()
    if not service: return None
    
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()
