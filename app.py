import streamlit as st
import pandas as pd
import io
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Crypto Tax FIFO Tool",
    page_icon="⚖️",
    layout="wide"
)

# --- SIDEBAR CONTROLS ---
with st.sidebar:
    st.title("⚙️ Tax Parameters")
    
    # 1. Year Selection
    current_year = datetime.now().year
    selected_year = st.selectbox(
        "Select Tax Year",
        options=list(range(current_year, 2010, -1)),
        index=0
    )
    
    # 2. Holding Period Selection
    months_threshold = st.slider(
        "Tax-Free Holding Period (Months)",
        min_value=0,
        max_value=120,
        value=12,
        help="Sales of assets held longer than this period will be marked as non-taxable."
    )
    days_threshold = months_threshold * 30.44 

    st.divider()
    st.info("📊 **Note:** All headers and calculations are now in English.")

# --- CORE LOGIC ---
def calculate_tax_logic(df, target_year, hold_days):
    try:
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values(['time', 'refid'])
        
        inventory = {}
        tax_data = []
        EPSILON = 1e-9 

        # 1. Trade-Mapping
        trades = {}
        for refid, group in df.groupby('refid'):
            eur_rows = group[group['asset'].isin(['ZEUR', 'EUR'])]
            if not eur_rows.empty:
                trades[refid] = {
                    'eur_total': abs(eur_rows['amount'].sum()),
                    'fee_total': group['fee'].sum()
                }

        # 2. Ledger Processing
        for idx, row in df.iterrows():
            asset = row['asset']
            if asset in ['ZEUR', 'EUR', 'KFEE']: continue
            
            asset = asset.replace('ZEUR', '').replace('EUR', '').replace('X', '', 1) if asset.startswith('X') else asset
            raw_amount, fee, date, refid = float(row['amount']), float(row['fee']), row['time'], row['refid']

            # INFLOW (BUY)
            if raw_amount > 0:
                eur_paid = trades.get(refid, {}).get('eur_total', 0)
                inventory.setdefault(asset, []).append({
                    'amount': raw_amount - fee,
                    'pure_price_eur': eur_paid, 
                    'buy_fee': fee, 
                    'date': date
                })
                
            # OUTFLOW (SELL)
            elif raw_amount < 0:
                if asset not in inventory or not inventory[asset]: continue
                
                abs_sell_amount = abs(raw_amount)
                eur_received = trades.get(refid, {}).get('eur_total', 0)
                sell_fee = trades.get(refid, {}).get('fee_total', 0)
                sell_vol_remaining = abs_sell_amount
                
                while sell_vol_remaining > EPSILON and inventory[asset]:
                    first_buy = inventory[asset][0]
                    days_held = (date - first_buy['date']).days
                    amount_to_process = min(sell_vol_remaining, first_buy['amount'])
                    
                    # Process if the SALE happened in the selected year
                    if date.year == target_year:
                        v_preis = (eur_received / abs_sell_amount) * amount_to_process
                        k_preis = (first_buy['pure_price_eur'] / (first_buy['amount'] + 1e-12)) * amount_to_process
                        nk_anschauung = (first_buy['buy_fee'] / (first_buy['amount'] + 1e-12)) * amount_to_process
                        vk_kosten = (sell_fee / abs_sell_amount) * amount_to_process
                        
                        gain_loss = v_preis - (k_preis + nk_anschauung) - vk_kosten
                        is_taxable = days_held <= hold_days

                        tax_data.append({
                            'Asset': asset,
                            'Sell Date': date.strftime('%d.%m.%Y'),
                            'Buy Date': first_buy['date'].strftime('%d.%m.%Y'),
                            'Holding Period (Days)': days_held,
                            'Amount': round(amount_to_process, 8),
                            'Proceeds (EUR)': round(v_preis, 2),
                            'Cost Basis (EUR)': round(k_preis + nk_anschauung, 2),
                            'Selling Fees (EUR)': round(vk_kosten, 2),
                            'Gain/Loss (EUR)': round(gain_loss, 2),
                            'Taxable': "Yes" if is_taxable else "No"
                        })

                    # FIFO update
                    sell_vol_remaining -= amount_to_process
                    first_buy['amount'] -= amount_to_process
                    if first_buy['amount'] < EPSILON:
                        inventory[asset].pop(0)

        return pd.DataFrame(tax_data), None
    except Exception as e:
        return None, str(e)

# --- MAIN UI ---
st.title("⚖️ Crypto Tax Calculator")
st.write(f"Analyzing year **{selected_year}** | Threshold: **{months_threshold} months**")

uploaded_file = st.file_uploader("Upload Kraken Ledger CSV", type=["csv"])

if uploaded_file:
    try:
        df_input = pd.read_csv(uploaded_file)
        
        with st.spinner('Calculating FIFO...'):
            result_df, error = calculate_tax_logic(df_input, selected_year, days_threshold)
        
        if error:
            st.error(f"Error: {error}")
        elif result_df.empty:
            st.warning(f"No sales found in {selected_year}.")
        else:
            # Calculate Summary Metrics
            total_gains = result_df['Gain/Loss (EUR)'].sum()
            taxable_gains = result_df[result_df['Taxable'] == "Yes"]['Gain/Loss (EUR)'].sum()
            
            # Display Summary
            m1, m2 = st.columns(2)
            m1.metric("Total Realized Gain/Loss", f"{total_gains:,.2f} €", help="Gains from all sales in this year.")
            m2.metric("Total Taxable Gain/Loss", f"{taxable_gains:,.2f} €", help=f"Only sales held ≤ {months_threshold} months.")
            
            st.divider()
            
            # Show Table
            st.dataframe(result_df, use_container_width=True)

            # Excel Download
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                result_df.to_excel(writer, index=False, sheet_name='Tax_Report')
            
            st.download_button(
                label="📥 Download English Report (Excel)",
                data=buffer.getvalue(),
                file_name=f"Tax_Report_{selected_year}_EN.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"File Parsing Error: {e}")
