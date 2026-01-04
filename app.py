import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone
import traceback

# --- ページ設定 ---
st.set_page_config(page_title="AI家計簿", layout="wide")

# ==========================================
# ① パスワード入力画面 (CSSで拡大)
# ==========================================
st.markdown("""
<style>
    div[data-testid="stTextInput"] input {
        font-size: 20px;
        padding: 15px;
    }
    div[data-testid="stButton"] button {
        height: 3em;
        font-size: 18px;
    }
</style>
""", unsafe_allow_html=True)

if "APP_PASSWORD" in st.secrets:
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if not st.session_state['authenticated']:
        st.title("🔐 ログイン")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("ログイン"):
            if password == st.secrets["APP_PASSWORD"]:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.stop()
else:
    st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
    st.stop()

st.title("💰 AI資産管理マネージャー")

# --- サイドバー ---
st.sidebar.header("機能メニュー")
menu = st.sidebar.radio("選択してください", ["レシート登録", "データ確認"])

# --- Session State初期化 ---
if 'input_date' not in st.session_state: st.session_state['input_date'] = date.today()
if 'input_store' not in st.session_state: st.session_state['input_store'] = ""
if 'input_amount' not in st.session_state: st.session_state['input_amount'] = 0
if 'input_category' not in st.session_state: st.session_state['input_category'] = "食費"
if 'input_member' not in st.session_state: st.session_state['input_member'] = ""
# 分割モード用データ保持
if 'split_data' not in st.session_state: st.session_state['split_data'] = None

# --- 定数定義 ---
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル"]

# 日本時間 (JST) 定義
JST = timezone(timedelta(hours=9), 'JST')

# --- 関数: OpenAI解析 ---
def analyze_receipt(image_bytes, mode="total"):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    categories_str = "/".join(CATEGORIES)

    # モードによってプロンプトを切り替え
    if mode == "split":
        # 明細分割モード
        system_prompt = f"""
        レシート画像を解析し、JSONで出力せよ。
        1. date(YYYY-MM-DD)とstore(店名)を抽出。
        2. 購入品目を全てリスト化し、key名を'items'とする。
        3. itemsの中身は {{"name": "商品名", "amount": 金額(数値)}} の形式にする。
        4. 割引等は無視し、個別の商品と金額を抽出すること。
        """
    else:
        # 合計一括モード
        system_prompt = f"レシート画像からdate(YYYY-MM-DD),store,amount(合計金額・数値),category({categories_str})をJSONで抽出せよ。"

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
        
        # ★変更: タイムスタンプを日本時間で取得
        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

        # [日付, 店名, カテゴリ, 金額, 対象者, タイムスタンプ]
        row = [
            str(data['date']), 
            data['store'], 
            data['category'], 
            data['amount'], 
            data['member'], 
            now_jst
        ]
        sheet.append_row(row)
        return True
    except KeyError:
        st.error("Secrets設定エラー: SPREADSHEET_ID")
        return False
    except Exception as e:
        st.error(f"保存エラー: {e}")
        st.text(traceback.format_exc())
        return False

# --- 関数: 会計月の計算 (25日締め) ---
def get_fiscal_month(date_obj):
    if date_obj.day >= 25:
        next_month = (date_obj.replace(day=1) + pd.DateOffset(months=1))
        return next_month.strftime('%Y-%m')
    else:
        return date_obj.strftime('%Y-%m')

# ==========================================
# 1. レシート登録画面
# ==========================================
if menu == "レシート登録":
    st.subheader("📸 レシート撮影・登録")
    
    # ★変更: モード選択ラジオボタン
    reg_mode = st.radio("登録モードを選択", ["1. 合計で登録 (一括)", "2. 明細ごとに登録 (分割)"])
    
    uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])
    
    # -------------------------------------
    # モード2: 明細分割 (Split)
    # -------------------------------------
    if reg_mode == "2. 明細ごとに登録 (分割)":
        if uploaded_file is not None:
            st.image(uploaded_file, caption="アップロード画像", width=300)
            
            if st.button("🤖 AI解析 (明細読み取り)"):
                with st.spinner("商品ごとの明細を読み取っています..."):
                    bytes_data = uploaded_file.getvalue()
                    # 分割モードでAI呼び出し
                    result_json, raw_text = analyze_receipt(bytes_data, mode="split")
                    
                    if result_json and "items" in result_json:
                        st.success(f"{len(result_json['items'])} 件の明細を検出しました。")
                        
                        # データフレームを作成してSessionに保存
                        items = result_json['items']
                        date_val = result_json.get("date", str(date.today()))
                        store_val = result_json.get("store", "")
                        
                        # 編集用初期データ作成
                        init_data = []
                        for item in items:
                            init_data.append({
                                "利用日": date_val,
                                "店名": store_val,
                                "商品名(メモ)": item.get("name", ""),
                                "金額": item.get("amount", 0),
                                "カテゴリ": "食費", # デフォルト
                                "対象者": "" # デフォルト
                            })
                        st.session_state['split_data'] = pd.DataFrame(init_data)
                    else:
                        st.error("明細の読み取りに失敗しました。合計モードを試すか手入力してください。")
            
            # 解析結果がある場合、編集テーブルを表示
            if st.session_state['split_data'] is not None:
                st.write("### 📝 明細の編集・登録")
                st.info("以下の表で「カテゴリ」や「対象者」を変更できます。不要な行は削除できます。")
                
                # data_editorで編集可能にする
                edited_df = st.data_editor(
                    st.session_state['split_data'],
                    num_rows="dynamic", # 行の追加削除許可
                    column_config={
                        "利用日": st.column_config.DateColumn("日付"),
                        "カテゴリ": st.column_config.SelectboxColumn(
                            "カテゴリ",
                            options=CATEGORIES + ["その他"],
                            required=True
                        ),
                        "対象者": st.column_config.SelectboxColumn(
                            "対象者",
                            options=[""] + MEMBERS,
                            required=False
                        ),
                        "金額": st.column_config.NumberColumn("金額", format="%d円")
                    },
                    hide_index=True
                )
                
                if st.button("✅ 全て登録する"):
                    success_count = 0
                    for index, row in edited_df.iterrows():
                        # 保存用データ形式に変換
                        save_data = {
                            "date": row["利用日"],
                            "store": row["店名"] + " (" + row["商品名(メモ)"] + ")", # 店名に商品名を付記
                            "category": row["カテゴリ"],
                            "amount": row["金額"],
                            "member": row["対象者"] if row["対象者"] else ""
                        }
                        if save_to_google_sheets(save_data):
                            success_count += 1
                    
                    if success_count > 0:
                        st.balloons()
                        st.success(f"{success_count} 件のデータを登録しました！")
                        st.session_state['split_data'] = None # クリア

    # -------------------------------------
    # モード1: 合計一括 (Total) - 既存ロジック
    # -------------------------------------
    else:
        if uploaded_file is not None:
            st.image(uploaded_file, caption="アップロード画像", width=300)
            
            if st.button("🤖 AI解析開始"):
                with st.spinner("合計金額を読み取っています..."):
                    bytes_data = uploaded_file.getvalue()
                    result_json, raw_text = analyze_receipt(bytes_data, mode="total")

                    if result_json:
                        st.success("読み取り成功！")
                        try:
                            if result_json.get("date"):
                                st.session_state['input_date'] = datetime.strptime(result_json["date"], "%Y-%m-%d").date()
                            st.session_state['input_store'] = result_json.get("store", "")
                            st.session_state['input_amount'] = int(result_json.get("amount", 0))
                            
                            ai_cat = result_json.get("category", "その他")
                            matched = "その他"
                            for cat in CATEGORIES:
                                if cat in ai_cat:
                                    matched = cat
                                    break
                            st.session_state['input_category'] = matched
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
            
            select_options = CATEGORIES + ["➕ 手入力 (新規作成)"]
            try:
                default_idx = select_options.index(st.session_state['input_category'])
            except:
                default_idx = select_options.index("その他")
            selected_cat = col2.selectbox("カテゴリ", select_options, index=default_idx)
            
            if selected_cat == "➕ 手入力 (新規作成)":
                final_category = col2.text_input("カテゴリ名を入力", value="")
            else:
                final_category = selected_cat

            member_options = [""] + MEMBERS
            current_mem = st.session_state['input_member']
            mem_idx = member_options.index(current_mem) if current_mem in member_options else 0
            input_member = col1.selectbox("対象者 (任意)", member_options, index=mem_idx)

            submitted = st.form_submit_button("✅ 登録する")
            
            if submitted:
                if not final_category:
                    st.error("カテゴリ名は必須です")
                else:
                    final_data = {
                        "date": input_date,
                        "store": input_store,
                        "amount": input_amount,
                        "category": final_category,
                        "member": input_member 
                    }
                    if save_to_google_sheets(final_data):
                        st.balloons()
                        msg_cat = final_category
                        if input_member:
                            msg_cat += f"({input_member})"
                        st.success(f"登録完了: {msg_cat} / ¥{input_amount}")

# ==========================================
# 2. データ確認画面
# ==========================================
elif menu == "データ確認":
    st.subheader("📊 月別支出集計 (25日締め)")
    
    if st.button("データを更新"):
        st.cache_data.clear()

    def load_data():
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet_id = st.secrets["SPREADSHEET_ID"]
            sheet = client.open_by_key(spreadsheet_id).sheet1
            data = sheet.get_all_values()
            
            if len(data) <= 1: return pd.DataFrame()

            df = pd.DataFrame(data[1:]) 
            
            if df.shape[1] == 5:
                df.columns = ["date", "store", "category", "amount", "timestamp"]
                df["member"] = ""
            elif df.shape[1] >= 6:
                df = df.iloc[:, :6]
                df.columns = ["date", "store", "category", "amount", "member", "timestamp"]
            else:
                return pd.DataFrame()
            return df
        except Exception as e:
            st.error(f"読み込みエラー: {e}")
            return None

    df = load_data()

    if df is not None and not df.empty:
        # --- 前処理 ---
        df['amount'] = pd.to_numeric(
            df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), 
            errors='coerce'
        ).fillna(0).astype(int)

        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])
        df['fiscal_month'] = df['date'].apply(get_fiscal_month)
        
        if 'member' in df.columns:
            df['member'] = df['member'].fillna("").astype(str)
        else:
            df['member'] = ""

        # 表示用カテゴリ
        def make_display_category(row):
            cat = row['category']
            mem = row['member']
            if mem and mem.strip() != "":
                return f"{cat}({mem})"
            else:
                return cat

        df['display_category'] = df.apply(make_display_category, axis=1)

        # --- 表示 ---
        month_list = sorted(df['fiscal_month'].unique(), reverse=True)
        selected_month = st.selectbox("対象年月を選択", month_list)
        month_df = df[df['fiscal_month'] == selected_month]

        # サマリー
        total_spend = month_df['amount'].sum()
        st.divider()
        col1, col2 = st.columns(2)
        col1.metric(f"{selected_month}月度の総支出", f"¥{total_spend:,}")
        col2.metric("データ件数", f"{len(month_df)} 件")
        
        # グラフ
        st.write("### 🥧 カテゴリ別支出")
        cat_sum = month_df.groupby('display_category')['amount'].sum().reset_index().sort_values('amount', ascending=False)
        st.bar_chart(cat_sum.set_index('display_category'))

        # 明細表 (カラム名変更対応)
        st.write("### 📝 詳細データ")
        
        # 表示用にDataFrameをコピー・整理
        view_df = month_df.copy()
        
        # 指定されたカラム名への変更
        # date⇒日付, store⇒購入箇所, category⇒カテゴリ-, timestamp⇒入力日, member⇒対象者, fisical_month⇒対象年月
        view_df = view_df.rename(columns={
            'date': '日付',
            'store': '購入箇所',
            'display_category': 'カテゴリー', # category列ではなく結合後のdisplay_categoryを表示
            'amount': '金額',
            'timestamp': '入力日',
            'member': '対象者',
            'fiscal_month': '対象年月'
        })
        
        # 表示したい列の順序
        display_cols = ['日付', 'カテゴリー', '購入箇所', '金額', '対象者', '入力日']
        
        view_df = view_df.sort_values('日付', ascending=False)
        st.dataframe(view_df[display_cols])
        
    else:
        st.info("データがありません。")
