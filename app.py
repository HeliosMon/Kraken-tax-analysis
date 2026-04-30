import streamlit as st
import pandas as pd
import io
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Custom Crypto Tax Tool",
    page_icon="⚖️",
    layout="wide"
)

# --- SIDEBAR CONTROLS ---
with st.sidebar:
    st.title("⚙️ Tax Parameters")
    
    # 1. Year Selection
    current_year = datetime.now().year
    selected_year = st.selectbox(
        "Which tax year do you want to calculate?",
        options=list(range(current_year, 2010, -1)),
        index=0
    )
    
    # 2. Holding Period Selection
    months_threshold = st.slider(
        "Holding period for tax-free gains (Months)",
        min_value=0,
        max_value=120, # Up to 10 years (relevant for some staking laws)
        value=12,
        help="In Germany, this is usually 12 months."
    )
    # Convert months to days for the logic
    days_threshold = months_threshold * 30.44 

    st.divider()
    st.info("""
    **Privacy:** Data is processed in your browser session and wiped when the tab is closed.
    """)

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
                    
                    # FILTER: Only process if the SELL happened in the selected year 
                    # AND if it was held LESS than the threshold
                    if date.year == target_year:
                        if days_held <= hold_days:
                            v_preis = (eur_received / abs_sell_amount) * amount_to_process
                            k_preis = (first_buy['pure_price_eur'] / (first_buy['amount'] + (0 if first_buy['amount'] > 0 else 1e-12))) * amount_to_process
                            nk_anschauung = (first_buy['buy_fee'] / (first_buy['amount'] + (0 if first_buy['amount'] > 0 else 1e-12))) * amount_to_process
                            vk_kosten = (sell_fee / abs_sell_amount) * amount_to_process

                            tax_data.append({
                                'Asset': asset,
                                'Verkaufsdatum': date.strftime('%d.%m.%Y'),
                                'Anschaffungsdatum': first_buy['date'].strftime('%d.%m.%Y'),
                                'Haltedauer (Tage)': days_held,
                                'Menge': round(amount_to_process, 8),
                                'Erlös (EUR)': round(v_preis, 2),
                                'Anschaffungskosten (EUR)': round(k_preis + nk_anschauung, 2),
                                'Gewinn/Verlust': round(v_preis - (k_preis + nk_anschauung) - vk_kosten, 2)
                            })

                    # FIFO update (happens regardless of year to keep inventory correct)
                    sell_vol_remaining -= amount_to_process
                    first_buy['amount'] -= amount_to_process
                    if first_buy['amount'] < EPSILON:
                        inventory[asset].pop(0)

        return pd.DataFrame(tax_data), None
    except Exception as e:
        return None, str(e)

# --- MAIN UI ---
st.title("⚖️ Crypto Tax Calculator")
st.write(f"Calculating gains for **{selected_year}** with a **{months_threshold} month** tax-free threshold.")

uploaded_file = st.file_uploader("Upload your kraken_ledger.csv", type=["csv"])

if uploaded_file:
    try:
        df_input = pd.read_csv(uploaded_file)
        
        with st.spinner('Running FIFO Analysis...'):
            result_df, error = calculate_tax_logic(df_input, selected_year, days_threshold)
        
        if error:
            st.error(f"Calculation Error: {error}")
        elif result_df.empty:
            st.warning(f"No taxable sales found for the year {selected_year}. Either you didn't sell anything, or everything was held longer than {months_threshold} months.")
        else:
            total_profit = result_df['Gewinn/Verlust'].sum()
            
            st.metric(label=f"Total Taxable Profit for {selected_year}", value=f"{total_profit:,.2f} €")
            
            st.dataframe(result_df, use_container_width=True)

            # Excel Export
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                result_df.to_excel(writer, index=False, sheet_name=f'Tax_{selected_year}')
            
            st.download_button(
                label=f"📥 Download {selected_year} Report",
                data=buffer.getvalue(),
                file_name=f"Tax_Report_{selected_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"File Error: {e}")
