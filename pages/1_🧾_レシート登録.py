import streamlit as st
# utils.py から関数を読み込む (同じ階層にあるとみなしてimport可能)
import utils 

st.set_page_config(page_title="レシート登録", layout="wide")
st.title("📸 レシート撮影・登録")

# --- 認証ロジック（必要なら入れる） ---
# if "authenticated" not in st.session_state: ... (省略)

st.info("レシートを撮影またはアップロードして、家計簿に登録します。")

uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="アップロードされたレシート", width=300)
    
    if st.button("AI解析開始"):
        with st.spinner("AIがレシートを読んでいます..."):
            try:
                bytes_data = uploaded_file.getvalue()
                # utilsにある関数を呼び出す
                result = utils.analyze_receipt(bytes_data) 
                st.session_state['result'] = result
                st.success("解析完了！")
            except Exception as e:
                st.error(f"解析エラー: {e}")

    # 解析結果がある場合のみフォームを表示
    if 'result' in st.session_state:
        result = st.session_state['result']
        
        with st.form("edit_form"):
            col1, col2 = st.columns(2)
            date = col1.text_input("日付", value=result.get("date"))
            store = col2.text_input("店名", value=result.get("store"))
            amount = col1.number_input("金額", value=int(result.get("amount", 0)))
            
            category = col2.selectbox("カテゴリ", ["食費", "日用品", "交通費", "その他"], 
                                      index=["食費", "日用品", "交通費", "その他"].index(result.get("category", "その他")))
            
            # Phase 2対応：入力項目の追加
            payment_method = col1.selectbox("決済方法", ["現金", "M用銀行", "Y用銀行", "M用クレカ", "Y用クレカ", "PayPay"])
            user = col2.selectbox("対象", ["共通", "まさ", "ゆう", "はると"])

            submitted = st.form_submit_button("この内容で登録")
            
            if submitted:
                final_data = {
                    "date": date, "store": store, "amount": amount, 
                    "category": category, "payment_method": payment_method, "user": user
                }
                
                if utils.save_to_google_sheets(final_data):
                    st.balloons()
                    st.success("スプレッドシートに保存しました！")
                    # 入力クリアなどの処理はお好みで