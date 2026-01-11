import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="CSV一括登録", layout="wide")
utils.check_password()

# ==========================================
# 🔒 セキュリティロック機能 (新規追加)
# ==========================================
# secretsに "ENVIRONMENT = 'local'" がある場合のみ通す
env = st.secrets.get("ENVIRONMENT", "cloud")

if env != "local":
    st.error("⛔ セキュリティ制限")
    st.warning("""
    **この機能はセキュリティのため、Web版（クラウド）では無効化されています。**
    
    銀行データの登録を行う場合は、自宅PCのローカル環境でアプリを起動してください。
    (VSCode Terminal: `streamlit run Home.py`)
    """)
    st.stop() # ここで処理を強制終了し、以下の画面を表示させない
# ==========================================

st.title("📥 金融機関データ取込")
st.title("📥 金融機関データ取込")
st.markdown("各金融機関のCSVを取り込み、それぞれのデータベースへ振り分けます。")

# 1. 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member = col2.selectbox("👤 誰のデータですか？", utils.MEMBERS, index=0) # マサをデフォルト

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]

st.info(f"保存先DB: **{target_sheet}** / 読み込み設定: {config['encoding']}")

# 2. ファイルアップロード
uploaded_file = st.file_uploader(f"{institution_name} のCSVをアップロード", type=["csv"])

if uploaded_file:
    try:
        # 設定された文字コードで読み込み
        df = pd.read_csv(uploaded_file, encoding=config["encoding"])
        
        # 必要な列が存在するかチェック
        required_cols = [config["date_col"], config["store_col"], config["amount_col"]]
        missing_cols = [c for c in required_cols if c not in df.columns]
        
        if missing_cols:
            st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
            st.warning("utils.py の INSTITUTION_CONFIG の列名設定が、実際のCSVと合っているか確認してください。")
            st.write("▼ 読み込んだCSVの列名一覧:")
            st.write(df.columns.tolist())
        else:
            # データの抽出と整形
            import_df = pd.DataFrame()
            import_df['date'] = pd.to_datetime(df[config["date_col"]], errors='coerce').dt.date
            import_df['store'] = df[config["store_col"]].fillna("")
            
            # 金額処理
            # 文字列置換してから数値化
            amount_series = df[config["amount_col"]].astype(str).str.replace(',', '').str.replace('円', '')
            import_df['amount'] = pd.to_numeric(amount_series, errors='coerce').fillna(0).astype(int)
            
            # マイナス値の扱い（支出なら正の値に変換するなど）
            # ここでは「絶対値」に変換して保存します（出金も入金も大きさとして扱う）
            # ※必要であれば銀行ごとにロジックを変えられます
            import_df['amount'] = import_df['amount'].abs()
            
            # 付加情報
            import_df['category'] = "未分類" # 一旦未分類にする
            import_df['member'] = selected_member
            
            # 有効な行のみ抽出
            import_df = import_df.dropna(subset=['date'])
            
            st.write("### プレビュー (確認)")
            
            # 編集可能なテーブルで表示（ここでカテゴリ修正可能）
            edited_df = st.data_editor(
                import_df,
                num_rows="dynamic",
                column_config={
                    "date": st.column_config.DateColumn("日付"),
                    "category": st.column_config.SelectboxColumn("カテゴリ", options=utils.CATEGORIES + ["その他"]),
                    "amount": st.column_config.NumberColumn("金額")
                },
                hide_index=True,
                key="editor"
            )
            
            if st.button(f"✅ {target_sheet} に登録実行"):
                success, msg = utils.save_bulk_to_google_sheets(edited_df, target_sheet)
                if success:
                    st.balloons()
                    st.success(f"{msg} 件のデータを {target_sheet} に登録しました！")
                else:
                    st.error(f"登録失敗: {msg}")

    except Exception as e:
        st.error(f"読み込みエラー: {e}")