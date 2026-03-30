import streamlit as st
import io
import json
import PyPDF2
import docx
import pandas as pd  # <--- THÊM DÒNG NÀY ĐỂ XỬ LÝ EXCEL
from google.oauth2 import service_account
from googleapiclient.discovery import build

def get_drive_service():
    """Khởi tạo kết nối an toàn với Google Drive API"""
    raw_creds = st.secrets["gcp_service_account"]
    creds_info = {}
    if isinstance(raw_creds, str):
        try: creds_info = json.loads(raw_creds)
        except Exception: pass
    elif hasattr(raw_creds, "to_dict"):
        creds_info = raw_creds.to_dict()
    elif isinstance(raw_creds, dict):
        creds_info = raw_creds

    if not creds_info:
        raise ValueError("Cannot parse Google Service Account credentials.")

    creds_dict = {str(k): str(v) for k, v in creds_info.items()}
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return build('drive', 'v3', credentials=creds)

def get_files_in_folder(drive_service, folder_id):
    """Quét các file/folder con bên trong một folder ID"""
    if not folder_id or not isinstance(folder_id, str): return []
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        return results.get('files', []) if isinstance(results, dict) else []
    except Exception as e:
        print(f"Drive API Error: {e}")
        return []

def read_file_content(drive_service, file_id, mime_type):
    """Giải mã tầng nhị phân và trích xuất văn bản thô"""
    try:
        if mime_type == 'application/vnd.google-apps.document':
            request = drive_service.files().export_media(fileId=file_id, mimeType='text/plain')
            return request.execute().decode('utf-8')
            
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            request = drive_service.files().export_media(fileId=file_id, mimeType='text/csv')
            return request.execute().decode('utf-8')
            
        else:
            request = drive_service.files().get_media(fileId=file_id)
            file_stream = io.BytesIO(request.execute())
            
            if mime_type == 'application/pdf':
                reader = PyPDF2.PdfReader(file_stream)
                text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                return text
                
            elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                doc = docx.Document(file_stream)
                return "\n".join([paragraph.text for paragraph in doc.paragraphs])
            
            # ---> BẮT ĐẦU ĐOẠN MÃ MỚI THÊM VÀO ĐỂ ĐỌC EXCEL (.xlsx) <---
            elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                # Thêm tham số sheet_name=None để ép Pandas đọc TẤT CẢ các sheet
                excel_data = pd.read_excel(file_stream, sheet_name=None)
                all_sheets_text = []
                
                # Duyệt qua từng sheet một và gom chung lại thành một bài văn bản dài
                for sheet_name, df in excel_data.items():
                    # Đánh dấu tên Sheet để AI phân biệt được nội dung
                    all_sheets_text.append(f"--- Dữ liệu từ Sheet: {sheet_name} ---")
                    # Chuyển bảng thành dạng CSV để AI dễ hiểu cấu trúc dòng/cột
                    all_sheets_text.append(df.to_csv(index=False))
                    
                return "\n\n".join(all_sheets_text)
            # ---> KẾT THÚC ĐOẠN MÃ MỚI <---
                
            elif mime_type == 'text/plain':
                return file_stream.read().decode('utf-8')
                
            else:
                return ""
    except Exception as e:
        print(f"Extraction Error on {file_id}: {e}")
        return ""
    except Exception as e:
        print(f"Extraction Error on {file_id}: {e}")
        return ""

def ingest_all_documents(root_folder_id):
    """
    Đường ống chính: Quét toàn bộ Drive và trả về mảng dữ liệu đã chuẩn hóa.
    Output format: [{"text": "...", "metadata": {"region": "...", "client": "...", "source": "..."}}]
    """
    drive_service = get_drive_service()
    documents = []
    
    root_items = get_files_in_folder(drive_service, root_folder_id)
    faq_data_folder = next((item for item in root_items if isinstance(item, dict) and item.get('name') == 'faq_data'), None)
    
    if not faq_data_folder:
        return documents

    lang_folders = get_files_in_folder(drive_service, faq_data_folder.get('id'))
    for lang in lang_folders:
        lang_name = lang.get('name')
        
        brand_folders = get_files_in_folder(drive_service, lang.get('id'))
        for brand in brand_folders:
            brand_name = brand.get('name')
            
            docs = get_files_in_folder(drive_service, brand.get('id'))
            for doc in docs:
                mime_type = doc.get('mimeType')
                if mime_type != 'application/vnd.google-apps.folder':
                    file_name = doc.get('name')
                    file_id = doc.get('id')
                    
                    content = read_file_content(drive_service, file_id, mime_type)
                    if content.strip():
                        # Đóng gói văn bản kèm Metadata để AI không bị lẫn lộn giữa các Client
                        documents.append({
                            "text": content,
                            "metadata": {
                                "region": lang_name,
                                "client": brand_name,
                                "source": file_name
                            }
                        })
    return documents
