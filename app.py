import streamlit as st
import easyocr
import pandas as pd
import cv2
import numpy as np
import re
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONEKSI KE GOOGLE SHEETS (Sama kayak kemarin) ---
def connect_gsheet():
    # Mengambil password dari "Secrets" Streamlit 
    # (Pastikan kamu sudah setting secrets di Streamlit Cloud atau file .streamlit/secrets.toml di local)
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"]) 
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Cashflow_Cahyo_DB").sheet1 
        return sheet
    except Exception as e:
        return None

# --- 2. OTAK OCR (Sama kayak kemarin) ---
@st.cache_resource
def load_model():
    return easyocr.Reader(['id', 'en'], gpu=False)

def process_image(image_file):
    reader = load_model()
    file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, 1)
    result = reader.readtext(img, detail=0)
    
    data = {
        "store": "Toko Unknown",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": 0,
        "items": []
    }
    
    # Logika Parsing
    if len(result) > 0: data["store"] = result[0]
    
    potential_items = []
    max_price = 0
    for text in result:
        clean = text.lower().replace('rp', '').replace('.', '').replace(',', '')
        match = re.search(r'\d+$', clean)
        if match:
            try:
                price = int(match.group())
                if 100 < price < 10000000:
                    name = text.replace(match.group(), "").strip()
                    name = re.sub(r'\d', '', name).replace('.', '').strip()
                    if len(name) > 2:
                        potential_items.append({"item": name, "price": price})
                        if price > max_price: max_price = price
            except: pass
            
    data["total"] = max_price
    data["items"] = [x for x in potential_items if x['price'] != max_price]
    return data

# --- 3. FUNGSI UPLOAD KE GSHEET (Biar rapi dipisah) ---
def upload_to_sheet(sheet_obj, date_obj, store_name, items_df, grand_total):
    rows_to_add = []
    str_date = date_obj.strftime("%Y-%m-%d")
    
    for _, row in items_df.iterrows():
        # Pastikan data valid
        item_name = str(row['item']).strip()
        item_price = int(row['price']) if row['price'] else 0
        
        if item_name and item_price > 0:
            rows_to_add.append([
                str_date, 
                store_name, 
                item_name, 
                item_price, 
                int(grand_total)
            ])
    
    if rows_to_add:
        sheet_obj.append_rows(rows_to_add)
        return True
    return False

# --- 4. UI UTAMA ---
st.set_page_config(page_title="Cahyo App", page_icon="💰")
st.title("💰 Cahyo Cashflow AI")

# Cek Koneksi
sheet = connect_gsheet()
if not sheet:
    st.error("⚠️ Gagal konek ke Google Sheets. Cek Secrets/JSON Key kamu!")
    st.stop()

# SIDEBAR MENU
menu = st.sidebar.selectbox("Pilih Menu", ["📸 Scan Struk", "📝 Input Manual", "📊 Lihat Laporan"])

# === MENU 1: SCAN STRUK ===
if menu == "📸 Scan Struk":
    st.header("Scan Struk Otomatis")
    uploaded_file = st.file_uploader("Upload Foto Struk", type=["jpg", "png", "jpeg"])
    
    if uploaded_file and st.button("🔍 Scan Sekarang"):
        with st.spinner("AI sedang membaca..."):
            res = process_image(uploaded_file)
        
        # Form Koreksi
        col1, col2 = st.columns(2)
        new_store = col1.text_input("Nama Toko", res["store"])
        new_date = col2.date_input("Tanggal", datetime.strptime(res["date"], "%Y-%m-%d"))
        
        st.write("Daftar Belanja (Edit jika salah):")
        df_items = pd.DataFrame(res["items"])
        if df_items.empty: df_items = pd.DataFrame([{"item": "Barang 1", "price": 0}])
        
        # Tabel Editor
        edited_df = st.data_editor(
            df_items, 
            num_rows="dynamic",
            column_config={
                "item": st.column_config.TextColumn("Nama Barang"),
                "price": st.column_config.NumberColumn("Harga", format="Rp %d")
            }
        )
        
        grand_total = edited_df["price"].sum()
        st.metric("Total Belanja", f"Rp {grand_total:,.0f}")
        
        if st.button("🚀 Upload Hasil Scan"):
            success = upload_to_sheet(sheet, new_date, new_store, edited_df, grand_total)
            if success:
                st.balloons()
                st.success("✅ Data Scan tersimpan!")

# === MENU 2: INPUT MANUAL (FITUR BARU) ===
elif menu == "📝 Input Manual":
    st.header("Input Manual Tanpa Scan")
    
    col1, col2 = st.columns(2)
    manual_store = col1.text_input("Nama Toko / Warung", placeholder="Misal: Warteg Bahari")
    manual_date = col2.date_input("Tanggal Transaksi", datetime.now())
    
    st.write("### Daftar Item")
    st.caption("Klik baris kosong di bawah untuk tambah barang.")
    
    # Template Tabel Kosong
    empty_data = pd.DataFrame(columns=["item", "price"])
    # Kita kasih 1 baris kosong biar user langsung ngerti
    initial_data = pd.DataFrame([{"item": "", "price": 0}])
    
    manual_df = st.data_editor(
        initial_data,
        num_rows="dynamic", # Bisa tambah baris sepuasnya
        column_config={
            "item": st.column_config.TextColumn("Nama Barang", required=True),
            "price": st.column_config.NumberColumn("Harga (Rp)", required=True, min_value=0, format="Rp %d")
        },
        use_container_width=True
    )
    
    # Hitung Total Live
    total_manual = manual_df["price"].sum()
    st.write(f"**Total: Rp {total_manual:,.0f}**")
    
    if st.button("💾 Simpan Data Manual"):
        if not manual_store:
            st.warning("⚠️ Isi nama tokonya dulu, Bi!")
        elif total_manual == 0:
            st.warning("⚠️ Belum ada barang yang diinput.")
        else:
            with st.spinner("Menyimpan ke Cloud..."):
                success = upload_to_sheet(sheet, manual_date, manual_store, manual_df, total_manual)
                if success:
                    st.toast("Data berhasil disimpan!", icon="✅")
                    st.success(f"Berhasil! Rp {total_manual:,.0f} masuk pembukuan.")
                    # Opsional: Clear form (perlu trik session state, tapi gini aja cukup)

# === MENU 3: LAPORAN ===
elif menu == "📊 Lihat Laporan":
    st.header("Laporan Keuangan Live")
    
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        if not df.empty:
            # Info Cards
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Pengeluaran", f"Rp {df['Harga'].sum():,.0f}")
            col1.metric("Total Transaksi", len(df))
            col3.metric("Toko Terfavorit", df['Toko'].mode()[0])
            
            st.divider()
            
            # Chart
            tab1, tab2 = st.tabs(["📈 Grafik Toko", "📋 Data Lengkap"])
            
            with tab1:
                st.write("Pengeluaran per Toko")
                st.bar_chart(df.groupby("Toko")["Harga"].sum())
                
            with tab2:
                st.dataframe(df, use_container_width=True)
        else:
            st.info("Data masih kosong. Mulai input dong!")
            
    except Exception as e:
        st.error(f"Error ambil data: {e}")