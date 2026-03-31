import streamlit as st
import time  # Vẫn giữ lại để ru ngủ API của Google
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

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
    Băm nhỏ văn bản và ép thẳng lên đám mây Pinecone theo từng Lô (Batching) để né lỗi 429
    """
    if not raw_documents:
        print("Cảnh báo: Không có tài liệu nào để Vector hóa.")
        return None

    # 1. TĂNG KÍCH THƯỚC CHUNK ĐỂ GIẢM SỐ LƯỢNG MẢNH VỠ
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,   
        chunk_overlap=500, 
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

    # 2. KHỞI TẠO KẾT NỐI VỚI ĐÁM MÂY PINECONE
    pc = Pinecone(api_key=st.secrets["PINECONE_API_KEY"])
    index_name = st.secrets["PINECONE_INDEX_NAME"]
    index = pc.Index(index_name)
    
    embeddings = get_embedding_model()
    
    # Kết nối thẳng với Pinecone Vector Store thay vì dùng Chroma cục bộ
    vector_db = PineconeVectorStore(index=index, embedding=embeddings)
    
    # 3. CHIẾN THUẬT DU KÍCH: BƠM TỪ TỪ LÊN MÂY
    BATCH_SIZE = 90  # Khóa giới hạn an toàn: Luôn gửi dưới 100 request/phút
    total_chunks = len(chunks)
    
    # Báo cáo lên giao diện Streamlit cho Admin biết đang làm gì
    progress_text = f"Chuẩn bị nạp {total_chunks} đoạn văn bản lên Pinecone Cloud..."
    my_bar = st.progress(0, text=progress_text)

    for i in range(0, total_chunks, BATCH_SIZE):
        batch_texts = chunks[i:i+BATCH_SIZE]
        batch_metadatas = metadatas[i:i+BATCH_SIZE]
        
        # Đẩy 1 lô 90 mảnh lên Cloud
        vector_db.add_texts(texts=batch_texts, metadatas=batch_metadatas)
        
        # Tính toán tiến độ
        current_chunk = min(i + BATCH_SIZE, total_chunks)
        progress_ratio = current_chunk / total_chunks
        
        if current_chunk < total_chunks:
            # Nếu chưa xong, báo UI và ngủ đông 60 giây
            my_bar.progress(progress_ratio, text=f"Đã bắn {current_chunk}/{total_chunks} đoạn lên Cloud. Đang ngủ đông 60s để Google hồi Quota...")
            time.sleep(60) 
        else:
            # Nếu đã xong
            my_bar.progress(1.0, text=f"Hoàn tất nạp {total_chunks}/{total_chunks} đoạn thành công lên Pinecone!")

    # KHÔNG CÒN LỆNH .persist() NỮA VÌ DỮ LIỆU ĐÃ NẰM TRÊN MÂY RỒI
    print(f"Đã Vector hóa thành công {total_chunks} phân đoạn tài liệu lên Đám mây.")
    
    return vector_db

def get_vector_db():
    """Hàm gọi lại DB từ Pinecone Cloud để Truy xuất siêu tốc"""
    if "PINECONE_API_KEY" not in st.secrets or "PINECONE_INDEX_NAME" not in st.secrets:
        return None
        
    index_name = st.secrets["PINECONE_INDEX_NAME"]
    embeddings = get_embedding_model()
    
    # Móc thẳng lên đám mây, ứng dụng Streamlit giờ cực kỳ nhẹ nhàng
    return PineconeVectorStore(index_name=index_name, embedding=embeddings)
