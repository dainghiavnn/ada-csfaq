import streamlit as st
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
import io

# --- 1. KHỞI TẠO API KẾT NỐI (Đã dùng TOML Secrets) ---
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

# --- 2. HÀM QUÉT THƯ MỤC ĐỆ QUY (Động cơ cốt lõi) ---
def get_files_in_folder(folder_id):
    """Lấy tất cả file và folder con bên trong một folder ID"""
    query = f"'{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(
        q=query, 
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get('files', [])

# --- 3. ĐỌC FILE USER DETAIL ---
@st.cache_data(ttl=600)
def load_users(root_folder_id):
    items = get_files_in_folder(root_folder_id)
    for item in items:
        if item['name'] == 'CSADA-UserDetail':
            request = drive_service.files().get_media(fileId=item['id'])
            file_stream = io.BytesIO(request.execute())
            return pd.read_excel(file_stream)
    return pd.DataFrame()

# --- 4. QUÉT VÀ PHÂN LOẠI DỮ LIỆU FAQ THEO BRAND ---
@st.cache_data(ttl=3600) # Cache 1 tiếng để tối ưu cho 50 user
def build_faq_catalog(root_folder_id):
    """
    Hàm này sẽ tự động tìm folder 'faq_data', luồn vào 'vi-vn', 
    và gom nhóm các file theo từng 'Brand' (VD: ulv-ahc)
    """
    catalog = {} # Dạng: {'ulv-ahc': [{'name': 'file1.pdf', 'id': '...'}, ...]}
    
    # 1. Tìm folder faq_data
    root_items = get_files_in_folder(root_folder_id)
    faq_data_folder = next((item for item in root_items if item['name'] == 'faq_data'), None)
    
    if not faq_data_folder:
        return catalog

    # 2. Tìm folder ngôn ngữ (VD: vi-vn)
    lang_folders = get_files_in_folder(faq_data_folder['id'])
    for lang in lang_folders:
        # 3. Tìm các folder Brand (VD: ulv-ahc)
        brand_folders = get_files_in_folder(lang['id'])
        for brand in brand_folders:
            brand_name = brand['name']
            catalog[brand_name] = []
            
            # 4. Lấy tất cả file Document bên trong Brand đó
            docs = get_files_in_folder(brand['id'])
            for doc in docs:
                if doc['mimeType'] != 'application/vnd.google-apps.folder':
                    catalog[brand_name].append({
                        'file_name': doc['name'],
                        'file_id': doc['id'],
                        'mime_type': doc['mimeType']
                    })
                    
    return catalog

# ==========================================
# THỰC THI THỬ NGHIỆM TRÊN GIAO DIỆN
# ==========================================
# THAY BẰNG ID CỦA FOLDER "CSADA-FAQ" (Lấy trên thanh địa chỉ trình duyệt)
ROOT_FOLDER_ID = "1ZXM5TjT2PPWAtA39ofvBGiBh5owWyuq0" 

st.title("Hệ thống CSADA FAQ - Testing Khung Dữ liệu")

with st.spinner("Đang đồng bộ dữ liệu với Google Drive..."):
    # Tải danh sách User
    df_users = load_users(ROOT_FOLDER_ID)
    st.write("### 1. Dữ liệu User Detail")
    st.dataframe(df_users)
    
    # Tải cấu trúc FAQ
    faq_catalog = build_faq_catalog(ROOT_FOLDER_ID)
    st.write("### 2. Dữ liệu FAQ phân theo Brand")
    st.json(faq_catalog)

# (Giao diện UI có dropdown chọn Brand sẽ dùng dữ liệu từ faq_catalog này)
if faq_catalog:
    selected_brand = st.selectbox("Chọn Brand để tra cứu:", list(faq_catalog.keys()))
    st.write(f"Bạn đang trực cho Brand: **{selected_brand}**")
    st.write("Các tài liệu AI sẽ dùng để trả lời:", [f['file_name'] for f in faq_catalog[selected_brand]])
