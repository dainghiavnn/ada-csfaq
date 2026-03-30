import streamlit as st
import pandas as pd
import io
import json
import traceback
import bcrypt
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit_authenticator as stauth

# --- IMPORT MODULES RAG ĐÃ TÁCH RỜI ---
from data_ingestion import ingest_all_documents, get_drive_service, get_files_in_folder
from vector_engine import build_vector_database
from rag_generator import generate_rag_response

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="CSADA FAQ System", page_icon="🏢", layout="wide")

# --- 1. KẾT NỐI DRIVE & ỦY QUYỀN ---
@st.cache_resource
def init_drive():
    return get_drive_service()

try:
    drive_service = init_drive()
except Exception as e:
    st.error(f"Lỗi khởi tạo Drive API: {e}")
    st.stop()

@st.cache_data(ttl=600)
def load_users(root_folder_id):
    items = get_files_in_folder(drive_service, root_folder_id)
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get('name') == 'CSADA-UserDetail':
                file_id = item.get('id')
                if file_id:
                    request = drive_service.files().export_media(
                        fileId=file_id,
                        mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    file_stream = io.BytesIO(request.execute())
                    return pd.read_excel(file_stream)
    return pd.DataFrame()

@st.cache_data(ttl=600)
def prepare_credentials(_df_users):
    creds = {"usernames": {}}
    if isinstance(_df_users, pd.DataFrame) and not _df_users.empty:
        active_users = _df_users[_df_users['AGENT_STATUS'].astype(str).str.strip().str.upper() == 'ACTIVE']
        for i, (_, row) in enumerate(active_users.iterrows()):
            email = str(row['MAIL']).strip()
            plain_pass = str(row['Password']).strip()
            
            if plain_pass.startswith("$2b$"): 
                hashed_pass = plain_pass
            else:
                hashed_pass = bcrypt.hashpw(plain_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            creds["usernames"][email] = {
                "email": email,
                "name": str(row['NAME']).strip(),
                "password": hashed_pass, 
                "logged_in": False,
                "failed_login_attempts": 0
            }
            
    # Thêm tài khoản Admin để quản trị Vector DB
    admin_username = "admin"
    admin_plain_pass = "ADA@Vn"
    admin_hashed_pass = bcrypt.hashpw(admin_plain_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    creds["usernames"][admin_username] = {
        "email": admin_username,
        "name": "System Administrator",
        "password": admin_hashed_pass,
        "logged_in": False,
        "failed_login_attempts": 0
    }
    return creds

@st.cache_data(ttl=3600)
def build_ui_filters(root_folder_id):
    """Quét thư mục nhanh để lấy danh sách Client/Region lên Dropdown (Không đọc ruột file)"""
    catalog = {} 
    root_items = get_files_in_folder(drive_service, root_folder_id)
    if not isinstance(root_items, list): return catalog
    
    faq_data_folder = next((item for item in root_items if isinstance(item, dict) and item.get('name') == 'faq_data'), None)
    if not faq_data_folder: return catalog

    lang_folders = get_files_in_folder(drive_service, faq_data_folder.get('id'))
    if isinstance(lang_folders, list):
        for lang in lang_folders:
            if not isinstance(lang, dict): continue
            lang_name = lang.get('name')
            if not lang_name: continue
            catalog[lang_name] = []
            
            brand_folders = get_files_in_folder(drive_service, lang.get('id'))
            if isinstance(brand_folders, list):
                for brand in brand_folders:
                    if not isinstance(brand, dict): continue
                    brand_name = brand.get('name')
                    if brand_name:
                        catalog[lang_name].append(brand_name)
    return catalog

# ==========================================
# MAIN INTERFACE & LOGIN FLOW
# ==========================================
ROOT_FOLDER_ID = "1ZXM5TjT2PPWAtA39ofvBGiBh5owWyuq0"

try:
    with st.spinner("Đang khởi tạo hệ thống bảo mật..."):
        df_users = load_users(ROOT_FOLDER_ID)
        credentials = prepare_credentials(df_users)
        
    authenticator = stauth.Authenticate(
        credentials,
        "cs_faq_cookie",
        "ada_secret_key_2026",
        cookie_expiry_days=30
    )

    st.subheader('CSADA FAQ Portal Login')
    
    authenticator.login(location='main')
    
    authentication_status = st.session_state.get("authentication_status")
    name = st.session_state.get("name")
    username = st.session_state.get("username")

    if authentication_status == False:
        st.error('❌ Sai Email hoặc Mật khẩu.')
    elif authentication_status == None:
        st.info('ℹ️ Vui lòng đăng nhập để truy cập dữ liệu SLA.')
    elif authentication_status:
        # --- GIAO DIỆN CHUNG ---
        col_welcome, col_logout = st.columns([5, 1])
        with col_welcome:
            st.markdown(f"**Welcome {name}**")
        with col_logout:
            authenticator.logout('Đăng xuất', 'main')
            
        st.divider()

        # --- KHU VỰC ĐẶC QUYỀN CỦA ADMIN ---
        if username == "admin":
            with st.expander("🛠️ BẢNG ĐIỀU KHIỂN ADMIN (Quản lý Vector Database)", expanded=True):
                st.warning("Hành động này sẽ ép hệ thống đọc lại toàn bộ file từ Drive và băm nhỏ vào DB. Cần vài phút để hoàn thành.")
                
                # Nút Sync Data cũ
               if st.button("🔄 Khởi chạy Đồng bộ hóa Dữ liệu (Sync Data)", type="primary"):
                    st.toast("Đã nhận lệnh! Bắt đầu kết nối Drive...", icon="🚀") # Hiển thị thông báo nổi ngay lập tức
                    
                    with st.status("Đang xây dựng lại não bộ RAG...", expanded=True) as status:
                        try:
                            st.write("1. Đang quét cây thư mục Google Drive...")
                            raw_docs = ingest_all_documents(ROOT_FOLDER_ID)
                            
                            if not raw_docs:
                                status.update(label="Đồng bộ thất bại: 0 tài liệu được tìm thấy!", state="error", expanded=True)
                                st.error("🚨 NGUYÊN NHÂN LỖI: API chạy thành công nhưng Drive trống rỗng.")
                                st.warning("Cách xử lý:\n1. Kiểm tra lại xem bạn đã cấp quyền Viewer cho email Service Account vào folder chưa?\n2. Đảm bảo bên trong folder gốc có một thư mục con tên chính xác là `faq_data` (chữ thường).")
                            else:
                                st.write(f">> Đã trích xuất thành công {len(raw_docs)} tài liệu.")
                                st.write("2. Đang băm nhỏ (Chunking) và Nhúng (Embedding) vào ChromaDB...")
                                
                                db = build_vector_database(raw_docs)
                                
                                if db:
                                    status.update(label="Hoàn tất đồng bộ!", state="complete", expanded=False)
                                    st.success("Hệ thống RAG đã cập nhật thành công. AI đã sẵn sàng!")
                                else:
                                    status.update(label="Lỗi ở khâu băm dữ liệu", state="error", expanded=True)
                                    st.error("Có tài liệu nhưng hệ thống ChromaDB không thể mã hóa được. Vui lòng kiểm tra Logs.")
                        except Exception as e:
                            status.update(label="Hệ thống sập ngầm trong lúc chạy", state="error", expanded=True)
                            st.error(f"Lỗi kỹ thuật: {e}")
                    pass 

                st.divider()
                
                # [MỚI] NÚT CHẨN ĐOÁN LỖI 404
                st.info("Công cụ gỡ lỗi API: Quét danh sách Model khả dụng cho API Key của ADA")
                if st.button("🔍 Quét danh sách Model Google"):
                    import google.generativeai as genai
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    
                    st.write("**Đây là những Model thực sự tồn tại và khả dụng cho API Key của bạn:**")
                    try:
                        models = genai.list_models()
                        for m in models:
                            if 'generateContent' in m.supported_generation_methods:
                                st.code(m.name.replace("models/", "")) # Cắt bỏ chữ models/ để lấy tên chuẩn
                    except Exception as e:
                        st.error(f"Lỗi khi quét API: {e}")
            st.divider()
            
        # --- KHU VỰC LÀM VIỆC CỦA CHUYÊN VIÊN CS ---
        with st.spinner("Đang tải danh mục Brand..."):
            ui_filters = build_ui_filters(ROOT_FOLDER_ID)
            
        if not ui_filters:
            st.warning("Không tìm thấy cấu trúc thư mục trên Drive.")
        else:
            available_languages = list(ui_filters.keys())
            
            with st.sidebar:
                st.write("### Cấu hình Khách hàng")
                selected_lang = st.selectbox("Thị trường (Region)", available_languages)
                
            st.write("**:speech_balloon: Trợ lý AI Phân tích Luật lệ & FAQ:**")
            chat_container = st.container(height=450, border=True)
            
            available_brands = ui_filters.get(selected_lang, [])
            
            col_client, col_brand = st.columns(2)
            with col_client:
                selected_client = st.selectbox("Thương hiệu (Client)", available_brands)
            with col_brand:
                st.selectbox("Cửa hàng (Store)", ["Tất cả Store"]) 
            
            if 'messages' not in st.session_state:
                st.session_state.messages = []
            else:
                st.session_state.messages = [m for m in st.session_state.messages if isinstance(m, dict)]

            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message.get("role", "unknown")):
                        st.markdown(message.get("content", ""))

            if prompt := st.chat_input("Nhập câu hỏi của khách hàng (VD: Kem vón cục đổi trả thế nào?)..."):
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})

                with chat_container:
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        message_placeholder.markdown(f"Đang lục soát Vector Database cho **{selected_client}**... ⏳")
                        
                        # Gọi thẳng vào RAG Generator, tốc độ truy xuất giờ chỉ tính bằng mili-giây
                        response_text = generate_rag_response(prompt, selected_client, selected_lang)
                        
                        message_placeholder.markdown(response_text)
                        
                st.session_state.messages.append({"role": "assistant", "content": response_text})

except Exception as e:
    st.error(f"Sập hệ thống RAG: {e}")
    with st.expander("Gỡ lỗi kỹ thuật (Traceback)"):
        st.code(traceback.format_exc())
