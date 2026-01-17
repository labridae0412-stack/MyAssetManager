import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="CSV一括登録", layout="wide")
utils.check_password()

# ==========================================
# 🔒 セキュリティロック機能
# ==========================================
env = st.secrets.get("ENVIRONMENT", "cloud")

if env != "local":
    st.error("⛔ セキュリティ制限")
    st.warning("""
    **この機能はセキュリティのため、Web版（クラウド）では無効化されています。**
    
    銀行データの登録を行う場合は、自宅PCのローカル環境でアプリを起動してください。
    (VSCode Terminal: `streamlit run Home.py`)
    """)
    st.stop()

# ==========================================
# 画面描画
# ==========================================
st.title("📥 金融機関データ取込")
st.markdown("各金融機関のCSVを取り込み、それぞれのデータベースへ振り分けます。")

# 1. 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member = col2.selectbox("👤 誰のデータですか？", utils.MEMBERS, index=0)

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]

st.info(f"保存先DB: **{target_sheet}** / 読み込み設定: {config['encoding']}")

# 2. ファイルアップロード
uploaded_file = st.file_uploader(f"{institution_name} のCSVをアップロード", type=["csv"])

if uploaded_file:
    try:
        # 設定された文字コードで読み込み
        df = pd.read_csv(uploaded_file, encoding=config["encoding"])
        
        # -----------------------------------------------------
        # A. 2列構成 (支出列 / 収入列) の場合: 例 M銀行
        # -----------------------------------------------------
        if "expense_col" in config and "income_col" in config:
            # 必要な列のチェック
            required_cols = [config["date_col"], config["store_col"], config["expense_col"], config["income_col"]]
            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
                st.write(df.columns.tolist())
            else:
                import_df = pd.DataFrame()
                import_df['date'] = pd.to_datetime(df[config["date_col"]], errors='coerce').dt.date
                import_df['store'] = df[config["store_col"]].fillna("")
                
                # 支出金額の処理 (カンマ除去 -> 数値化 -> 0埋め)
                exp_series = df[config["expense_col"]].astype(str).str.replace(',', '').str.replace('円', '')
                exp_vals = pd.to_numeric(exp_series, errors='coerce').fillna(0).astype(int)
                
                # 収入金額の処理
                inc_series = df[config["income_col"]].astype(str).str.replace(',', '').str.replace('円', '')
                inc_vals = pd.to_numeric(inc_series, errors='coerce').fillna(0).astype(int)
                
                # 金額の統合ロジック:
                # 支出があればそれを採用、なければ収入を採用(収入しかない行を想定)
                # 今回は家計簿なので、支出はそのままプラスの値、収入もプラスの値として扱う
                # (収入か支出かはカテゴリで区別する運用を想定)
                import_df['amount'] = exp_vals + inc_vals
                
                # 収入行（支出が0で収入がある行）に「収入」フラグ的な情報を入れたい場合
                # ここでは簡易的に「未分類」とするが、収入金額がある行はカテゴリを「その他」や「給与」に初期設定する手もある
                import_df['category'] = "未分類"
                
                # 両方0円の行は除外したい場合
                import_df = import_df[import_df['amount'] > 0]

        # -----------------------------------------------------
        # B. 1列構成 (入出金が1列 or 支出のみ) の場合: 従来通り
        # -----------------------------------------------------
        else:
            required_cols = [config["date_col"], config["store_col"], config["amount_col"]]
            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
                st.write(df.columns.tolist())
            else:
                import_df = pd.DataFrame()
                import_df['date'] = pd.to_datetime(df[config["date_col"]], errors='coerce').dt.date
                import_df['store'] = df[config["store_col"]].fillna("")
                
                amount_series = df[config["amount_col"]].astype(str).str.replace(',', '').str.replace('円', '')
                import_df['amount'] = pd.to_numeric(amount_series, errors='coerce').fillna(0).astype(int).abs()
                import_df['category'] = "未分類"

        # 共通処理 (DataFrameが作成されていれば表示)
        if 'import_df' in locals():
            # 共通付加情報
            import_df['member'] = selected_member
            import_df = import_df.dropna(subset=['date'])
            
            st.write("### プレビュー (確認)")
            
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