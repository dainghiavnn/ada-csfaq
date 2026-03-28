import streamlit as st
import pandas as pd
import io
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit_authenticator as stauth

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Hệ thống CSADA FAQ", page_icon="🏢", layout="wide")

# --- 1. KHỞI TẠO API KẾT NỐI DRIVE ---
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

# --- 2. HÀM QUÉT THƯ MỤC ĐỆ QUY ---
def get_files_in_folder(folder_id):
    """Lấy tất cả file và folder con bên trong một folder ID"""
    query = f"'{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(
        q=query, 
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get('files', [])

# --- 3. ĐỌC FILE USER DETAIL (Đã fix lỗi HttpError) ---
@st.cache_data(ttl=600)
def load_users(root_folder_id):
    items = get_files_in_folder(root_folder_id)
    for item in items:
        if item['name'] == 'CSADA-UserDetail':
            # Phải dùng export_media cho các file Google Sheets thuần
            request = drive_service.files().export_media(
                fileId=item['id'],
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            file_stream = io.BytesIO(request.execute())
            return pd.read_excel(file_stream)
    return pd.DataFrame()

# --- 4. QUÉT VÀ PHÂN LOẠI DỮ LIỆU FAQ THEO BRAND ---
@st.cache_data(ttl=3600)
def build_faq_catalog(root_folder_id):
    catalog = {} 
    root_items = get_files_in_folder(root_folder_id)
    faq_data_folder = next((item for item in root_items if item['name'] == 'faq_data'), None)
    
    if not faq_data_folder:
        return catalog

    lang_folders = get_files_in_folder(faq_data_folder['id'])
    for lang in lang_folders:
        brand_folders = get_files_in_folder(lang['id'])
        for brand in brand_folders:
            brand_name = brand['name']
            catalog[brand_name] = []
            
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
# GIAO DIỆN CHÍNH & LUỒNG ĐĂNG NHẬP
# ==========================================
# ID folder gốc CSADA-FAQ
ROOT_FOLDER_ID = "1ZXM5TjT2PPWAtA39ofvBGiBh5owWyuq0"

try:
    with st.spinner("Đang kết nối hệ thống phân quyền..."):
        df_users = load_users(ROOT_FOLDER_ID)
    
    # 1. Cấu hình Authenticator từ dữ liệu Google Sheet
    credentials = {"usernames": {}}
    if not df_users.empty:
        for _, row in df_users.iterrows():
            if str(row['AGENT_STATUS']).strip().upper() == 'ACTIVE':
                email = str(row['MAIL']).strip()
                credentials["usernames"][email] = {
                    "name": str(row['NAME']).strip(),
                    "password": str(row['Password']).strip() 
                    # Lưu ý: Password trong Sheet hiện tại đang để text thường để test. 
                    # Môi trường thực tế nên được hash trước.
                }

    authenticator = stauth.Authenticate(
        credentials,
        "cs_faq_cookie",
        "random_key_ada_2026",
        cookie_expiry_days=30
    )

    # 2. Hiển thị form đăng nhập (Mockup 1)
    name, authentication_status, username = authenticator.login('Đăng nhập Hệ thống FAQ ADA', 'main')

    # 3. Xử lý trạng thái đăng nhập
    if authentication_status == False:
        st.error('Email hoặc mật khẩu không đúng.')
    elif authentication_status == None:
        st.info('Vui lòng đăng nhập bằng tài khoản nội bộ được cấp.')
    elif authentication_status:
        # --- GIAO DIỆN SAU KHI ĐĂNG NHẬP (Mockup 2) ---
        col1, col2 = st.columns([5, 1])
        with col1:
            st.write(f"### Welcome **{name}**")
        with col2:
            authenticator.logout('Logout', 'main')
            
        st.divider()
        
        # Tải danh sách cấu trúc thư mục FAQ
        with st.spinner("Đang đồng bộ kho tài liệu FAQ..."):
            faq_catalog = build_faq_catalog(ROOT_FOLDER_ID)
            
        if not faq_catalog:
            st.warning("Không tìm thấy dữ liệu FAQ trong thư mục Google Drive.")
        else:
            # Layout chọn Brand / Store
            col_brand, col_store = st.columns(2)
            with col_brand:
                selected_brand = st.selectbox("Brand:", list(faq_catalog.keys()))
            with col_store:
                st.selectbox("Store:", ["Tất cả Store"]) # Có thể nối data riêng nếu cần
            
            # Khởi tạo vùng lưu trữ lịch sử chat
            if 'messages' not in st.session_state:
                st.session_state.messages = []

            st.write("**:speech_balloon: Conversation:**")
            chat_container = st.container(height=400, border=True)
            
            # Hiển thị lịch sử hội thoại
            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

            # Khung nhập câu hỏi (Question) ở dưới cùng
            if prompt := st.chat_input("**:question: Question:**"):
                # Hiển thị câu hỏi của user
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})

                # Hiển thị phản hồi từ AI (Phần placeholder chờ tích hợp Gemini)
                with chat_container:
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        message_placeholder.markdown("Đang tra cứu tài liệu từ Google Drive... ⏳")
                        time.sleep(1.5) # Giả lập delay xử lý
                        
                        # Khung trả lời tạm thời trước khi nối model AI
                        response_text = f"Đã nhận câu hỏi: '{prompt}'. Tính năng AI đọc tài liệu của **{selected_brand}** sẽ được tích hợp tại đây."
                        message_placeholder.markdown(response_text)
                        
                st.session_state.messages.append({"role": "assistant", "content": response_text})

except Exception as e:
    st.error(f"Lỗi hệ thống: {e}")
