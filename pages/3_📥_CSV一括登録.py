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

# --- サイドバー：マスタ管理機能 ---
with st.sidebar:
    st.header("⚙️ マスタ管理")
    st.info("過去の登録データから、店名とカテゴリの組み合わせを学習させることができます。")
    if st.button("🔄 過去データからマスタを初期作成"):
        with st.spinner("データベースを解析中..."):
            count = utils.create_master_from_history()
            if count > 0:
                st.success(f"完了: {count} 件のキーワードをマスタに登録しました！")
            else:
                st.warning("新規に追加できるデータが見つかりませんでした。")

st.markdown("各金融機関のCSVを取り込み、**収支区分(Cat1)** と **費目(Cat2)** に分けて登録します。")
st.info("⚠️ スプレッドシートの **I列** に「残高」列が追加されていることを確認してください。")

# 1. 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member = col2.selectbox("👤 誰のデータですか？", utils.MEMBERS, index=0)

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]

# ★ここでマスタを読み込んでおく
master_dict = utils.load_category_master()

st.info(f"保存先DB: **{target_sheet}** / 読み込み設定: {config['encoding']}")

# 2. ファイルアップロード
uploaded_file = st.file_uploader(f"{institution_name} のCSVをアップロード", type=["csv"])

if uploaded_file:
    try:
        # 設定された文字コードで読み込み
        df = pd.read_csv(uploaded_file, encoding=config["encoding"])
        
        # データ整形用のリスト
        processed_rows = []

        # -----------------------------------------------------
        # A. 2列構成 (支出列 / 収入列) の場合: M銀行など
        # -----------------------------------------------------
        if "expense_col" in config and "income_col" in config:
            required_cols = [config["date_col"], config["store_col"], config["expense_col"], config["income_col"]]
            if "balance_col" in config:
                required_cols.append(config["balance_col"])

            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
            else:
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    if pd.isna(date_val): continue

                    # 残高取得
                    balance_val = None
                    if "balance_col" in config:
                        bal_str = str(row[config["balance_col"]]).replace(',', '').replace('円', '')
                        try:
                            balance_val = int(float(bal_str)) if bal_str and bal_str != 'nan' else None
                        except:
                            balance_val = None

                    # ★カテゴリ自動推論
                    suggested_cat = utils.suggest_category(store_val, master_dict)

                    # 1. 支出列チェック
                    exp_str = str(row[config["expense_col"]]).replace(',', '').replace('円', '')
                    try:
                        exp_amount = int(float(exp_str)) if exp_str and exp_str != 'nan' else 0
                    except:
                        exp_amount = 0
                    
                    if exp_amount > 0:
                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "支出",
                            "category_2": suggested_cat, # 推論結果を使用
                            "amount": abs(exp_amount),
                            "member": selected_member,
                            "institution": institution_name,
                            "balance": balance_val
                        })

                    # 2. 収入列チェック
                    inc_str = str(row[config["income_col"]]).replace(',', '').replace('円', '')
                    try:
                        inc_amount = int(float(inc_str)) if inc_str and inc_str != 'nan' else 0
                    except:
                        inc_amount = 0
                    
                    if inc_amount > 0:
                        # 収入の場合、推論が「未分類」なら「その他」をデフォルトにする
                        final_cat = suggested_cat if suggested_cat != "未分類" else "その他"
                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "収入",
                            "category_2": final_cat,
                            "amount": abs(inc_amount),
                            "member": selected_member,
                            "institution": institution_name,
                            "balance": balance_val
                        })

        # -----------------------------------------------------
        # B. 1列構成 (入出金が1列 or 支出のみ) の場合
        # -----------------------------------------------------
        else:
            required_cols = [config["date_col"], config["store_col"], config["amount_col"]]
            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
            else:
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    if pd.isna(date_val): continue

                    amount_str = str(row[config["amount_col"]]).replace(',', '').replace('円', '')
                    try:
                        amount_raw = int(float(amount_str)) if amount_str and amount_str != 'nan' else 0
                    except:
                        amount_raw = 0
                    
                    # 残高取得
                    balance_val = None
                    if "balance_col" in config and config["balance_col"] in df.columns:
                        bal_str = str(row[config["balance_col"]]).replace(',', '').replace('円', '')
                        try:
                            balance_val = int(float(bal_str)) if bal_str and bal_str != 'nan' else None
                        except:
                            balance_val = None

                    if amount_raw != 0:
                        # ★カテゴリ自動推論
                        suggested_cat = utils.suggest_category(store_val, master_dict)
                        
                        # 収支区分判定
                        cat1 = "支出" if amount_raw < 0 else "収入" # 多くの場合マイナスが支出だが、CSVによるので注意
                        # (※M銀行などは正の値で列が分かれているが、1列の場合は符号で判断するのが通例。
                        #  ただしRカードなどは請求額が正の値で来ることもあるため、必要に応じてロジック調整)
                        # ここではシンプルに絶対値を使用し、正負は文脈依存とします（一旦デフォルト支出）
                        
                        # CSVの仕様に合わせて微調整が必要な場合がありますが、基本は絶対値で処理
                        final_amount = abs(amount_raw)

                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "支出", # デフォルト（必要に応じて変更）
                            "category_2": suggested_cat,
                            "amount": final_amount,
                            "member": selected_member,
                            "institution": institution_name,
                            "balance": balance_val
                        })

        # --- 結果の表示と保存 ---
        if processed_rows:
            import_df = pd.DataFrame(processed_rows)
            
            st.write("### プレビュー (確認・編集)")
            st.info("💡 店名からカテゴリを推論しました。「未分類」の箇所は手動で修正してください。後でマスタに登録できます。")
            
            edited_df = st.data_editor(
                import_df,
                num_rows="dynamic",
                column_config={
                    "date": st.column_config.DateColumn("日付"),
                    "category_1": st.column_config.SelectboxColumn("収支区分", options=["支出", "収入"]),
                    "category_2": st.column_config.SelectboxColumn("費目(Cat2)", options=utils.CATEGORIES + ["その他"]),
                    "amount": st.column_config.NumberColumn("金額"),
                    "institution": st.column_config.TextColumn("金融機関", disabled=True),
                    "balance": st.column_config.NumberColumn("残高")
                },
                hide_index=True,
                key="editor"
            )
            
            if st.button(f"✅ {target_sheet} に登録実行"):
                success, added_count, skipped_count = utils.save_bulk_to_google_sheets(edited_df, target_sheet, institution_name)
                
                if success:
                    st.balloons()
                    msg = f"登録完了！\n- **{added_count}** 件を新規登録しました。\n"
                    if skipped_count > 0:
                        msg += f"- **{skipped_count}** 件は重複のためスキップされました。"
                    
                    if added_count > 0:
                        st.success(msg)
                    else:
                        st.warning(msg)

                    # ------------------------------------------
                    # ★ マスタ学習ロジック (登録成功時のみ表示)
                    # ------------------------------------------
                    new_mappings = {}
                    # 編集後のデータフレームを走査
                    for index, row in edited_df.iterrows():
                        store_name = row['store']
                        category = row['category_2']

                        # 条件: 
                        # 1. マスタにまだ登録されていない店名である
                        # 2. カテゴリが「未分類」「その他」ではない (有効なカテゴリが設定されている)
                        # 3. 店名が空でない
                        if store_name and (store_name not in master_dict) and (category not in ["未分類", "その他"]):
                            new_mappings[store_name] = category

                    if new_mappings:
                        st.divider()
                        st.subheader("🧠 マスタ学習の提案")
                        st.write("今回設定された以下の組み合わせを、カテゴリマスタに登録しますか？")
                        st.write("次回から自動で入力されるようになります。")
                        
                        # 確認用表示
                        st.json(new_mappings, expanded=False)
                        
                        if st.button("💾 これらをマスタに保存する"):
                            count = utils.update_category_master(new_mappings)
                            st.toast(f"{count} 件の新しいルールを学習しました！", icon="🎓")
                            # マスタ辞書を更新して再読み込みを防ぐ（簡易的）
                            master_dict.update(new_mappings)

                else:
                    st.error(f"登録失敗: {added_count}")
        else:
            st.warning("読み込めるデータがありませんでした。")

    except Exception as e:
        st.error(f"読み込みエラー: {e}")