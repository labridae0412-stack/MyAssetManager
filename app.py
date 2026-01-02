import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- ページ設定 ---
st.set_page_config(page_title="AI家計簿", layout="wide")
st.title("💰 AI資産管理マネージャー")

# ==========================================
# 🔐 セキュリティ対策: パスワード認証機能
# ==========================================
# Secretsに "APP_PASSWORD" が設定されているか確認し、認証を行う
if "APP_PASSWORD" in st.secrets:
    password = st.sidebar.text_input("パスワードを入力してください", type="password")
    if password != st.secrets["APP_PASSWORD"]:
        st.warning("正しいパスワードを入力するまで機能は制限されます。")
        st.stop()  # ここで処理を止める（これより下のコードは実行されない）
else:
    st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
    st.stop()

# --- サイドバー：設定 ---
st.sidebar.header("機能メニュー")
menu = st.sidebar.radio("選択してください", ["レシート登録", "データ確認"])

# --- 関数: OpenAIで画像を解析 ---
def analyze_receipt(image_bytes):
    # 画像をbase64エンコード
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "このレシート画像を解析し、以下の情報をJSON形式で抽出してください。\nキー名: date (YYYY-MM-DD), store (店名), amount (合計金額・数値のみ), category (食費, 日用品, 交通費, その他 のいずれか)\n余計な解説は不要で、JSONデータのみを返してください。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ],
            }
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 関数: Google Sheetsへ保存 ---
def save_to_google_sheets(data):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        # シート名も直書きせず、エラーハンドリングする
        sheet_name = "Kakeibo_DB" 
        sheet = client.open(sheet_name).sheet1
        
        # 行を追加: [日付, 店名, カテゴリ, 金額, 登録日時]
        row = [data['date'], data['store'], data['category'], data['amount'], str(datetime.now())]
        sheet.append_row(row)
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"エラー: スプレッドシート '{sheet_name}' が見つかりません。名前を確認してください。")
        return False
    except Exception as e:
        st.error(f"スプレッドシートへの保存に失敗しました: {e}")
        return False

# --- メイン画面：レシート登録 ---
if menu == "レシート登録":
    st.subheader("📸 レシート撮影・解析")
    
    uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロードされたレシート", width=300)
        
        if st.button("AI解析開始"):
            with st.spinner("AIがレシートを読んでいます..."):
                try:
                    bytes_data = uploaded_file.getvalue()
                    result = analyze_receipt(bytes_data)
                    
                    st.success("解析完了！内容を確認してください。")
                    
                    with st.form("edit_form"):
                        col1, col2 = st.columns(2)
                        date = col1.text_input("日付", value=result.get("date"))
                        store = col2.text_input("店名", value=result.get("store"))
                        amount = col1.number_input("金額", value=int(result.get("amount", 0)))
                        category = col2.selectbox("カテゴリ", ["食費", "日用品", "交通費", "その他"], index=["食費", "日用品", "交通費", "その他"].index(result.get("category", "その他")))
                        
                        submitted = st.form_submit_button("この内容で登録")
                        
                        if submitted:
                            final_data = {"date": date, "store": store, "amount": amount, "category": category}
                            if save_to_google_sheets(final_data):
                                st.balloons()
                                st.success("スプレッドシートに保存しました！")
                            
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

elif menu == "データ確認":
    st.subheader("📊 最新の支出データ")
    st.info("※ここにスプレッドシートのデータを読み込んでグラフ表示します（今回は枠組みのみ）")
