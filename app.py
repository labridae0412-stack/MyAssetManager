import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import traceback  # ★追加: エラー詳細表示用

# --- ページ設定 ---
st.set_page_config(page_title="AI家計簿", layout="wide")
st.title("💰 AI資産管理マネージャー")

# ==========================================
# 🔐 セキュリティ対策: パスワード認証機能
# ==========================================
if "APP_PASSWORD" in st.secrets:
    password = st.sidebar.text_input("パスワードを入力してください", type="password")
    if password != st.secrets["APP_PASSWORD"]:
        st.warning("正しいパスワードを入力するまで機能は制限されます。")
        st.stop()
else:
    st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
    st.stop()

# --- サイドバー：設定 ---
st.sidebar.header("機能メニュー")
menu = st.sidebar.radio("選択してください", ["レシート登録", "データ確認"])

# --- Session State初期化 (フォーム入力値保持用) ---
if 'input_date' not in st.session_state:
    st.session_state['input_date'] = date.today()
if 'input_store' not in st.session_state:
    st.session_state['input_store'] = ""
if 'input_amount' not in st.session_state:
    st.session_state['input_amount'] = 0
if 'input_category' not in st.session_state:
    st.session_state['input_category'] = "食費"
if 'raw_response' not in st.session_state:
    st.session_state['raw_response'] = ""

# --- 関数: OpenAIで画像を解析 ---
def analyze_receipt(image_bytes):
    # 画像をbase64エンコード
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    # プロンプトを極限まで短縮してコスト削減
    system_prompt = "レシート画像からdate(YYYY-MM-DD),store,amount(数値),category(食費/日用品/交通費/その他)をJSONで抽出せよ。"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        
        if not content:
            return None, "APIからの応答が空でした。"

        data = json.loads(content)
        return data, content

    except Exception as e:
        return None, f"解析エラー: {str(e)}"

# --- 関数: Google Sheetsへ保存 ---
def save_to_google_sheets(data):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        
        row = [str(data['date']), data['store'], data['category'], data['amount'], str(datetime.now())]
        sheet.append_row(row)
        return True
    except KeyError:
        st.error("Secretsに 'SPREADSHEET_ID' が設定されていません。")
        return False
    except Exception as e:
        # ★修正: エラーの詳細ログ(Traceback)を画面に出力する
        st.error(f"スプレッドシートへの保存に失敗しました: {e}")
        st.text("▼ エラー詳細ログ")
        st.text(traceback.format_exc()) 
        return False

# --- メイン画面：レシート登録 ---
if menu == "レシート登録":
    st.subheader("📸 レシート撮影・登録")
    
    uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロード画像", width=300)
        
        if st.button("🤖 AI解析開始 (自動入力)"):
            with st.spinner("AIが読み取っています..."):
                bytes_data = uploaded_file.getvalue()
                result_json, raw_text = analyze_receipt(bytes_data)
                
                st.session_state['raw_response'] = raw_text

                if result_json:
                    st.success("読み取り成功！下部のフォームを確認・修正してください。")
                    try:
                        if result_json.get("date"):
                            st.session_state['input_date'] = datetime.strptime(result_json["date"], "%Y-%m-%d").date()
                        st.session_state['input_store'] = result_json.get("store", "")
                        st.session_state['input_amount'] = int(result_json.get("amount", 0))
                        
                        cat = result_json.get("category", "その他")
                        if cat in ["食費", "日用品", "交通費", "その他"]:
                            st.session_state['input_category'] = cat
                        else:
                            st.session_state['input_category'] = "その他"
                    except Exception as e:
                        st.warning(f"一部データの変換に失敗しましたが、続けられます: {e}")
                else:
                    st.error("AI解析に失敗しました。手動で入力してください。")

    with st.expander("▼ 解析結果（デバッグ用・AIの思考）を確認する"):
        st.text_area("OpenAI Output", value=st.session_state['raw_response'], height=150)

    st.markdown("---")
    st.write("### ✏️ 登録フォーム (手動修正可能)")

    with st.form("entry_form"):
        col1, col2 = st.columns(2)
        
        input_date = col1.date_input("日付", value=st.session_state['input_date'])
        input_store = col2.text_input("店名", value=st.session_state['input_store'])
        input_amount = col1.number_input("金額", min_value=0, value=st.session_state['input_amount'])
        input_category = col2.selectbox("カテゴリ", ["食費", "日用品", "交通費", "その他"], 
                                      index=["食費", "日用品", "交通費", "その他"].index(st.session_state['input_category']))
        
        submitted = st.form_submit_button("✅ この内容で登録する")
        
        if submitted:
            final_data = {
                "date": input_date,
                "store": input_store,
                "amount": input_amount,
                "category": input_category
            }
            if save_to_google_sheets(final_data):
                st.balloons()
                st.success("スプレッドシートに保存しました！")

elif menu == "データ確認":
    st.subheader("📊 最新の支出データ")
    
    def load_data():
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet_id = st.secrets["SPREADSHEET_ID"]
            sheet = client.open_by_key(spreadsheet_id).sheet1
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        except Exception as e:
            st.error(f"データの読み込みに失敗しました: {e}")
            st.text(traceback.format_exc()) # こちらにも詳細ログを追加
            return None

    if st.button("データを更新"):
        st.cache_data.clear()

    df = load_data()

    if df is not None and not df.empty:
        st.write("### 📝 登録明細")
        st.dataframe(df)

        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), errors='coerce')
            
        if 'category' in df.columns and 'amount' in df.columns:
            st.write("### 🥧 カテゴリ別支出")
            category_sum = df.groupby('category')['amount'].sum().reset_index()
            st.bar_chart(category_sum.set_index('category'))
            
            total_spend = df['amount'].sum()
            st.metric(label="総支出額", value=f"¥{total_spend:,.0f}")
    else:
        st.info("データがまだありません。")
