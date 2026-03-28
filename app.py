import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import time

# --- CẤU HÌNH TRANG (UX) ---
st.set_page_config(page_title="Hệ thống FAQ Nôi bộ", page_icon="🏢", layout="wide")

# --- 1. XỬ LÝ ĐĂNG NHẬP (Mô phỏng image_0.png) ---

# Mô phỏng dữ liệu user (Trong thực tế, nên lưu password đã hash trong DB hoặc Sheets)
# Password '123' đã được hash (admin: 123, user1: 123)
hashed_passwords = stauth.Hasher(['123', '123']).generate()

config = {
    'credentials': {
        'usernames': {
            'admin': {
                'email': 'admin@company.com',
                'name': 'Nguyễn Văn A (Admin)',
                'password': hashed_passwords[0]
            },
            'user1': {
                'email': 'user1@company.com',
                'name': 'Trần Thị B',
                'password': hashed_passwords[1]
            }
        }
    },
    'cookie': {
        'expiry_days': 30,
        'key': 'faq_signature_key', # Chuỗi ngẫu nhiên bất kỳ
        'name': 'faq_cookie'
    },
    'preauthorized': {
        'emails': ['admin@company.com']
    }
}

# Khởi tạo bộ xác thực
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config['preauthorized']
)

# Hiển thị form đăng nhập (Streamlit tự xử lý giao diện giống image_0.png)
name, authentication_status, username = authenticator.login('Đăng nhập Hệ thống FAQ', 'main')

# --- 2. ĐIỀU HƯỚNG GIAO DIỆN DỰA TRÊN TRẠNG THÁI ---

if authentication_status == False:
    st.error('Username/Password không chính xác')

elif authentication_status == None:
    st.warning('Vui lòng nhập Username và Password')
    # Tùy chỉnh thêm CSS để form login nhìn giống hệt image_0.png nếu cần

elif authentication_status:
    # --- 3. GIAO DIỆN CHAT CHÍNH (Mô phỏng image_1.png) ---
    
    # Header: Welcome & Logout (Giống image_1.png)
    col_header1, col_header2 = st.columns([5, 1])
    with col_header1:
        st.markdown(f"### Welcome **{name}**")
    with col_header2:
        # Nút logout tự động xóa cookie và reset session
        authenticator.logout('Logout', 'main')

    st.divider()

    # Layout chính: Conversation & Question (Giống image_1.png)
    # Khởi tạo session state để lưu lịch sử chat
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    # Vùng hiển thị Conversation (Container có thanh cuộn)
    st.write("**:speech_balloon: Conversation:**")
    chat_placeholder = st.container(height=400, border=True)
    
    # Hiển thị các tin nhắn cũ
    with chat_placeholder:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Vùng nhập Question (Giống image_1.png ở dưới cùng)
    # Dùng st.chat_input thay vì st.text_input để có UX giống ChatGPT
    if prompt := st.chat_input("**:question: Question:**"):
        
        # 1. Hiển thị câu hỏi của user
        with chat_placeholder:
            with st.chat_message("user"):
                st.markdown(prompt)
        
        # Lưu vào lịch sử
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 2. Xử lý AI (Phần này sẽ kết nối với Gemini/FAISS sau)
        with chat_placeholder:
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                
                # Giả lập AI đang suy nghĩ (UX)
                with st.spinner("Đang tra cứu FAQ..."):
                    # MÔ PHỎNG LỜI GIẢI TỪ AI DỰA TRÊN TỪ KHÓA
                    if "nghỉ phép" in prompt.lower():
                        simulated_response = "Theo quy định tại file PDF 'Chinh_sach_nhan_su.pdf', nhân viên có 12 ngày nghỉ phép năm..."
                    elif "thanh toán" in prompt.lower():
                        simulated_response = "Quy trình thanh toán được hướng dẫn trong file Word 'Quy_trinh_tai_chinh.docx', bước 1 là lập đề nghị..."
                    else:
                        simulated_response = "Hiện tại tôi chưa tìm thấy thông tin này trong bộ FAQ. Bạn có thể thử đặt câu hỏi khác cụ thể hơn."
                    
                    time.sleep(1) # Giả lập độ trễ API

                # Hiệu ứng gõ chữ (Streaming UX)
                for chunk in simulated_response.split():
                    full_response += chunk + " "
                    time.sleep(0.05)
                    message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
        
        # Lưu câu trả lời của AI vào lịch sử
        st.session_state.messages.append({"role": "assistant", "content": full_response})
