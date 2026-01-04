import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import traceback

# --- ページ設定 ---
st.set_page_config(page_title="AI家計簿", layout="wide")
st.title("💰 AI資産管理マネージャー")

# ==========================================
# 🔐 セキュリティ対策
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

# --- Session State初期化 ---
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

# --- 関数: OpenAI解析 ---
def analyze_receipt(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    system_prompt = "レシート画像からdate(YYYY-MM-DD),store,amount(数値),category(食費/日用品/交通費/娯楽/その他)をJSONで抽出せよ。"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if not content: return None, "空の応答"
        return json.loads(content), content
    except Exception as e:
        return None, str(e)

# --- 関数: Google Sheets保存 ---
def save_to_google_sheets(data):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        
        # 保存する列の順番: [日付, 店名, カテゴリ, 金額, 登録日時]
        row = [str(data['date']), data['store'], data['category'], data['amount'], str(datetime.now())]
        sheet.append_row(row)
        return True
    except KeyError:
        st.error("Secrets設定エラー: SPREADSHEET_ID")
        return False
    except Exception as e:
        st.error(f"保存エラー: {e}")
        st.text(traceback.format_exc())
        return False

# ==========================================
# 1. レシート登録画面
# ==========================================
if menu == "レシート登録":
    st.subheader("📸 レシート撮影・登録")
    
    uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])
    
    # 画像解析処理
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロード画像", width=300)
        
        if st.button("🤖 AI解析開始 (自動入力)"):
            with st.spinner("AIが読み取っています..."):
                bytes_data = uploaded_file.getvalue()
                result_json, raw_text = analyze_receipt(bytes_data)
                st.session_state['raw_response'] = raw_text

                if result_json:
                    st.success("読み取り成功！")
                    try:
                        if result_json.get("date"):
                            st.session_state['input_date'] = datetime.strptime(result_json["date"], "%Y-%m-%d").date()
                        st.session_state['input_store'] = result_json.get("store", "")
                        st.session_state['input_amount'] = int(result_json.get("amount", 0))
                        st.session_state['input_category'] = result_json.get("category", "その他")
                    except:
                        pass
                else:
                    st.error("解析失敗。手入力してください。")

    st.markdown("---")
    st.write("### ✏️ 登録フォーム")

    with st.form("entry_form"):
        col1, col2 = st.columns(2)
        
        input_date = col1.date_input("日付", value=st.session_state['input_date'])
        input_store = col2.text_input("店名", value=st.session_state['input_store'])
        input_amount = col1.number_input("金額", min_value=0, value=st.session_state['input_amount'])
        
        # --- ★変更点1: カテゴリ手動追加機能 ---
        # 既存リスト + 新規追加オプション
        base_categories = ["食費", "日用品", "交通費", "娯楽", "教育費", "投資", "その他"]
        
        # SessionStateのカテゴリがリストになければ「その他」にする（エラー回避）
        current_cat = st.session_state['input_category']
        if current_cat not in base_categories:
            # もしAIが未知のカテゴリを出したら「その他」扱いにするか、リストに追加して表示するか
            # ここではシンプルにリストに一時的に追加して表示
            if current_cat: 
                base_categories.append(current_cat)
            else:
                current_cat = "その他"

        # 選択肢の末尾に「➕ 手入力 (新規作成)」を追加
        select_options = base_categories + ["➕ 手入力 (新規作成)"]
        
        # インデックスの決定
        try:
            default_index = select_options.index(current_cat)
        except ValueError:
            default_index = select_options.index("その他")

        selected_option = col2.selectbox("カテゴリ選択", select_options, index=default_index)
        
        # 「手入力」が選ばれたらテキストボックスを表示
        final_category = selected_option
        if selected_option == "➕ 手入力 (新規作成)":
            final_category = col2.text_input("新しいカテゴリ名を入力してください", value="")
        
        submitted = st.form_submit_button("✅ 登録する")
        
        if submitted:
            if final_category == "" or final_category == "➕ 手入力 (新規作成)":
                st.error("カテゴリ名を入力してください")
            else:
                final_data = {
                    "date": input_date,
                    "store": input_store,
                    "amount": input_amount,
                    "category": final_category
                }
                if save_to_google_sheets(final_data):
                    st.balloons()
                    st.success(f"登録完了: {final_category} / ¥{input_amount}")

# ==========================================
# 2. データ確認画面 (修正版)
# ==========================================
elif menu == "データ確認":
    st.subheader("📊 最新の支出データ")
    
    if st.button("データを更新"):
        st.cache_data.clear()

    # データ読み込み関数
    def load_data():
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet_id = st.secrets["SPREADSHEET_ID"]
            sheet = client.open_by_key(spreadsheet_id).sheet1
            
            # get_all_values で「文字列のリスト」として取得（ヘッダー問題を回避するため）
            data = sheet.get_all_values()
            
            # データが1行（ヘッダーのみ）以下の場合は空とみなす
            if len(data) <= 1:
                return pd.DataFrame()

            # DataFrame化（1行目をヘッダーとして扱うのではなく、強制的に列名を割り当てる）
            # ★変更点2: 列ズレ対策のため、列名を強制指定
            df = pd.DataFrame(data[1:]) # 1行目はスキップ（またはデータとして扱う）
            
            # スプレッドシートの列数が足りない場合の対策
            expected_cols = ["date", "store", "category", "amount", "timestamp"]
            current_cols = df.shape[1]
            
            if current_cols >= 5:
                df = df.iloc[:, :5] # 最初の5列だけ使う
                df.columns = expected_cols
            else:
                st.error(f"データの列数が足りません（現在{current_cols}列）。A〜E列までデータが入っているか確認してください。")
                return pd.DataFrame()

            return df
        except Exception as e:
            st.error(f"読み込みエラー: {e}")
            return None

    df = load_data()

    if df is not None and not df.empty:
        # --- データ前処理 (金額の数値化) ---
        # カンマや円マークを除去し、数値に変換できないものは 0 にする
        df['amount'] = pd.to_numeric(
            df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), 
            errors='coerce'
        ).fillna(0).astype(int)

        # 1. サマリー表示
        total_spend = df['amount'].sum()
        
        col1, col2 = st.columns(2)
        col1.metric("💰 総支出額", f"¥{total_spend:,}")
        col2.metric("🧾 登録件数", f"{len(df)} 件")

        # 2. カテゴリ別グラフ
        st.write("### 🥧 カテゴリ別構成")
        if total_spend > 0:
            category_sum = df.groupby('category')['amount'].sum().reset_index().sort_values('amount', ascending=False)
            st.bar_chart(category_sum.set_index('category'))
        else:
            st.info("金額データが集計できませんでした。数値が正しく登録されているか確認してください。")

        # 3. 明細表
        st.write("### 📝 最近の明細")
        st.dataframe(df.sort_values('date', ascending=False))
        
    else:
        st.info("データがまだありません。レシートを登録してください。")
