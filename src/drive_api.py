import os
import io
import streamlit as st
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """구글 드라이브 서비스 객체 생성 (매번 새로 호출하여 세션 유지)"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return None
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_drive_files(folder_id):
    """특정 폴더의 PDF 목록 가져오기"""
    service = get_drive_service()
    if not service: return []
    try:
        with st.expander("🔍 연결 상세 정보"):
            creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
            st.write(f"봇 계정: {creds.service_account_email}")
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
    """결과물 저장용 폴더 생성 (서비스 객체 내부 생성)"""
    service = get_drive_service()
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
    """결과 마크다운 업로드 (Broken Pipe 방지를 위해 서비스 객체 매번 생성)"""
    try:
        service = get_drive_service()
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
    except Exception as e:
        st.error(f"드라이브 업로드 중 오류 발생: {e}")

def download_drive_file(file_id):
    """파일 다운로드"""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()