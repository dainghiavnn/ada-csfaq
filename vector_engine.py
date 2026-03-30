import streamlit as st
import os
import time  # <--- Bắt buộc phải có thư viện này để ru ngủ hệ thống
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma

# Đường dẫn lưu trữ Vector DB cục bộ trên máy chủ Streamlit
CHROMA_PERSIST_DIR = "./chroma_db"

def get_embedding_model():
    """Khởi tạo mô hình nhúng (Embedding) của Google để biến chữ thành ma trận số"""
    if "GEMINI_API_KEY" not in st.secrets:
        raise ValueError("Thiếu GEMINI_API_KEY trong cấu hình Secrets.")
    
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001", 
        google_api_key=st.secrets["GEMINI_API_KEY"]
    )
    
def build_vector_database(raw_documents):
    """
    Băm nhỏ văn bản và ép vào CSDL Vector theo từng Lô (Batching) để né lỗi 429
    """
    if not raw_documents:
        print("Cảnh báo: Không có tài liệu nào để Vector hóa.")
        return None

    # 1. TĂNG KÍCH THƯỚC CHUNK ĐỂ GIẢM SỐ LƯỢNG MẢNH VỠ
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,   # Cắt to hơn (tăng từ 1000 lên 3000)
        chunk_overlap=500, # Vay mượn nhiều hơn để giữ ngữ cảnh (tăng từ 200 lên 500)
        separators=["\n\n", "\n", ".", " ", ""]
    )

    chunks = []
    metadatas = []

    for doc in raw_documents:
        text = doc.get("text", "")
        metadata = doc.get("metadata", {})
        
        if text:
            split_texts = text_splitter.split_text(text)
            chunks.extend(split_texts)
            metadatas.extend([metadata] * len(split_texts))

    if not chunks:
        print("Lỗi: Không thể trích xuất đoạn văn bản nào sau khi Chunking.")
        return None

    # 2. KHỞI TẠO DB VÀ BƠM DỮ LIỆU TỪ TỪ (CHIẾN THUẬT DU KÍCH)
    embeddings = get_embedding_model()
    
    # Tạo kết nối với thư mục DB rỗng
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR, 
        embedding_function=embeddings
    )
    
    BATCH_SIZE = 90  # Khóa giới hạn an toàn: Luôn gửi dưới 100 request/phút
    total_chunks = len(chunks)
    
    # Báo cáo lên giao diện Streamlit cho Admin biết đang làm gì
    progress_text = f"Chuẩn bị nạp {total_chunks} đoạn văn bản. Bắt đầu chiến thuật ru ngủ API..."
    my_bar = st.progress(0, text=progress_text)

    for i in range(0, total_chunks, BATCH_SIZE):
        batch_texts = chunks[i:i+BATCH_SIZE]
        batch_metadatas = metadatas[i:i+BATCH_SIZE]
        
        # Đẩy 1 lô 90 mảnh vào Database
        vector_db.add_texts(texts=batch_texts, metadatas=batch_metadatas)
        
        # Tính toán tiến độ
        current_chunk = min(i + BATCH_SIZE, total_chunks)
        progress_ratio = current_chunk / total_chunks
        
        if current_chunk < total_chunks:
            # Nếu chưa xong, báo UI và ngủ đông 60 giây
            my_bar.progress(progress_ratio, text=f"Đã nạp {current_chunk}/{total_chunks} đoạn. Đang ngủ đông 60s để Google hồi Quota...")
            time.sleep(60) 
        else:
            # Nếu đã xong
            my_bar.progress(1.0, text=f"Hoàn tất nạp {total_chunks}/{total_chunks} đoạn thành công!")

    # Ép ChromaDB lưu dữ liệu vật lý xuống ổ cứng tạm của Streamlit
    vector_db.persist()
    print(f"Đã Vector hóa thành công {total_chunks} phân đoạn tài liệu.")
    
    return vector_db

def get_vector_db():
    """Hàm gọi lại DB đã tồn tại để thực hiện tìm kiếm mà không cần build lại"""
    if not os.path.exists(CHROMA_PERSIST_DIR):
        return None
    
    embeddings = get_embedding_model()
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR, 
        embedding_function=embeddings
    )
