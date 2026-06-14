import streamlit as st
st.set_page_config(page_title='Pro Stock Decision Engine', layout='wide')
import pandas as pd, numpy as np
import plotly.graph_objects as go
from datetime import datetime

from data_loader import parse_tickers, get_ohlcv, get_info, get_options_chain, get_news, DEFAULT_UNIVERSES
from fundamentals import fundamental_score, fundamental_table
from technicals import technical_score, add_indicators, trade_levels
from liquidity import liquidity_score
from options_engine import options_score
from game_theory import game_theory_score
from catalyst_engine import catalyst_score
from expectation_engine import expectation_score
from skew_engine import skew_score
from cml_sml_engine import cml_sml_score
from black_litterman_engine import black_litterman_allocation
from scoring import combine_scores, classify, build_thesis, result_row
from backtester import backtest
from utils import save_scanner_rows, save_trade_journal, read_table

st.title('🧠 Professional Stock Decision-Support Engine')
st.caption('Multi-angle trading desk scanner: fundamentals + technicals + liquidity + options positioning + participant behavior + catalysts.')

with st.sidebar:
    st.header('Universe')
    universe = st.selectbox('Predefined universe', ['None','Mega-cap Tech','Liquid Momentum','Sector ETFs','S&P 500','Nasdaq 100'])
    manual = st.text_area('Manual tickers', 'AAPL, MSFT, NVDA, AMD, TSLA')
    csv_file = st.file_uploader('Upload CSV watchlist', type=['csv'])
    period = st.selectbox('History period', ['6mo','1y','2y','5y'], index=1)
    interval = st.selectbox('Interval', ['1d','1h','30m','15m'], index=0)
    account_size = st.number_input('Account size', min_value=1000, value=100000, step=5000)
    risk_pct = st.number_input('Risk per trade %', min_value=0.05, max_value=5.0, value=0.50, step=0.05)/100
    st.header('Score weights')
    weights = {
        'fundamental': st.slider('Fundamental',0.0,1.0,0.20,0.05),
        'technical': st.slider('Technical',0.0,1.0,0.25,0.05),
        'liquidity': st.slider('Liquidity',0.0,1.0,0.15,0.05),
        'options': st.slider('Options/Volatility',0.0,1.0,0.15,0.05),
        'game': st.slider('Game Theory',0.0,1.0,0.15,0.05),
        'catalyst': st.slider('Catalyst',0.0,1.0,0.10,0.05),
        'expectation': st.slider('Expectation Investing',0.0,1.0,0.10,0.05),
        'skew': st.slider('Options Skew',0.0,1.0,0.10,0.05),
        'cml_sml': st.slider('CML/SML Macro Pricing',0.0,1.0,0.10,0.05),
    }
    st.header('Macro / Portfolio Model')
    risk_free_rate = st.number_input('Risk-free rate %', min_value=0.0, max_value=15.0, value=4.50, step=0.25) / 100
    expected_market_return = st.number_input('Expected market return %', min_value=0.0, max_value=30.0, value=11.50, step=0.25) / 100
    bl_risk_aversion = st.number_input('BL risk aversion', min_value=0.5, max_value=10.0, value=2.5, step=0.25)
    bl_tau = st.number_input('BL tau', min_value=0.005, max_value=0.25, value=0.05, step=0.005)
    bl_max_weight = st.number_input('BL max single-name weight %', min_value=5.0, max_value=100.0, value=35.0, step=5.0) / 100
    run = st.button('Run scan', type='primary')

def analyze_ticker(ticker):
    df=get_ohlcv(ticker, period, interval)
    if df.empty or len(df)<40: return None
    info=get_info(ticker)
    spy=get_ohlcv('SPY', period, interval)
    f_score,f_meta=fundamental_score(info)
    t_score,t_meta,x=technical_score(df, spy)
    l_score,l_meta=liquidity_score(df, info)
    exp,calls,puts=get_options_chain(ticker)
    o_score,o_meta=options_score(calls, puts, float(df.Close.iloc[-1]))
    news=get_news(ticker)
    c_score,c_meta=catalyst_score(news)
    exp_score,exp_meta=expectation_score(info, df, f_meta, c_meta)
    # Directional bias for skew: use technical setup/final stock context as a proxy.
    setup_txt=str(t_meta.get('setup_type','')).lower()
    skew_bias='short' if any(x in setup_txt for x in ['short','rejection','distribution','downtrend','resistance']) else 'long'
    sk_score,sk_meta=skew_score(calls, puts, float(df.Close.iloc[-1]), skew_bias)
    g_score,g_meta=game_theory_score(t_meta, l_meta, o_meta, info)
    cml_score,cml_meta=cml_sml_score(info, df, spy, risk_free_rate, expected_market_return)
    scores={'fundamental':f_score,'technical':t_score,'liquidity':l_score,'options':o_score,'game':g_score,'catalyst':c_score,'expectation':exp_score,'skew':sk_score,'cml_sml':cml_score}
    final=combine_scores(scores, weights)
    decision=classify(final, t_meta.get('setup_type'))
    levels=trade_levels(x, account_size, risk_pct)
    thesis=build_thesis(ticker, decision, t_meta.get('setup_type'), f_meta, t_meta, l_meta, o_meta, g_meta, c_meta, exp_meta, sk_meta, cml_meta)
    row=result_row(ticker, final, decision, t_meta.get('setup_type'), levels, thesis)
    row.update({k+'_score':round(v,1) for k,v in scores.items()})
    return {'row':row,'df':df,'x':x,'info':info,'fund':f_meta,'tech':t_meta,'liq':l_meta,'opt':o_meta,'cat':c_meta,'game':g_meta,'expectation':exp_meta,'skew':sk_meta,'cml_sml':cml_meta,'calls':calls,'puts':puts,'expiry':exp,'news':news}

@st.cache_data(ttl=900, show_spinner=True)
def cached_scan(tickers, period, interval, account_size, risk_pct, weights_tuple):
    # weights_tuple only invalidates cache; live weights read above in this session.
    out=[]
    for t in tickers[:200]:
        try:
            r=analyze_ticker(t)
            if r: out.append((t,r))
        except Exception as e:
            st.warning(f'{t}: {e}')
    return out

watch = parse_tickers(manual, csv_file, universe)
tab1,tab2,tab3,tab4,tab5,tab6,tab7 = st.tabs(['Market Overview','Stock Scanner','Deep Dive','Options Positioning','Backtest','Trade Journal','Portfolio Risk Model'])

with tab1:
    st.subheader('Market regime')
    cols=st.columns(4)
    for i,sym in enumerate(['SPY','QQQ','IWM','^VIX']):
        d=get_ohlcv(sym,'6mo','1d')
        if not d.empty:
            ret20=d.Close.iloc[-1]/d.Close.iloc[-21]-1 if len(d)>21 else np.nan
            cols[i].metric(sym, f'{d.Close.iloc[-1]:.2f}', f'{ret20:.1%}')
    sectors=['XLK','XLF','XLE','XLV','XLY','XLI','XLC','XLP','XLU','XLB','SMH']
    srows=[]
    for s in sectors:
        d=get_ohlcv(s,'6mo','1d')
        if len(d)>21: srows.append({'ETF':s,'20d momentum':d.Close.iloc[-1]/d.Close.iloc[-21]-1,'price':d.Close.iloc[-1]})
    sdf=pd.DataFrame(srows).sort_values('20d momentum', ascending=False) if srows else pd.DataFrame()
    st.dataframe(sdf, use_container_width=True)
    if not sdf.empty: st.bar_chart(sdf.set_index('ETF')['20d momentum'])

results=[]
if run:
    with st.spinner('Scanning universe...'):
        results = cached_scan(tuple(watch), period, interval, account_size, risk_pct, tuple(weights.items()))
        st.session_state['scan_results']=results
else:
    results = st.session_state.get('scan_results', [])

with tab2:
    st.subheader('Ranked scanner')
    if results:
        rows=[r['row'] for _,r in results]
        dfres=pd.DataFrame(rows).sort_values('final_score', ascending=False)
        st.dataframe(dfres, use_container_width=True)
        save_scanner_rows(rows)
        st.download_button('Export scanner CSV', dfres.to_csv(index=False), file_name='scanner_results.csv')
    else:
        st.info('Choose a universe and click Run scan.')

with tab3:
    st.subheader('Ticker deep dive')
    choices=[t for t,_ in results] or watch
    sel=st.selectbox('Select ticker', choices)
    rdict=dict(results).get(sel) if results else analyze_ticker(sel)
    if rdict:
        row=rdict['row']; st.markdown(f"### {sel}: {row['decision']} | Score {row['final_score']}")
        st.write(row['thesis'])
        c1,c2,c3,c4,c5=st.columns(5)
        c1.metric('Entry', row['entry']); c2.metric('Stop', row['stop']); c3.metric('Target 1', row['target1']); c4.metric('R/R', row['rr']); c5.metric('Shares', row['position_size'])
        x=rdict['x']; fig=go.Figure()
        fig.add_trace(go.Candlestick(x=x.index, open=x.Open, high=x.High, low=x.Low, close=x.Close, name='Price'))
        for e in ['EMA8','EMA21','EMA50','EMA200']:
            if e in x: fig.add_trace(go.Scatter(x=x.index,y=x[e],name=e))
        fig.update_layout(height=550, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        colA,colB=st.columns(2)
        with colA:
            st.markdown('#### Scores')
            st.json({k:row.get(k+'_score') for k in ['fundamental','technical','liquidity','options','game','catalyst','expectation','skew','cml_sml']})
            st.markdown('#### Fundamental table')
            st.dataframe(fundamental_table(rdict['info']), use_container_width=True)
        with colB:
            st.markdown('#### Desk reads')
            st.write('Technical:', rdict['tech'])
            st.write('Liquidity:', rdict['liq'])
            st.write('Options:', rdict['opt'])
            st.write('Game theory:', rdict['game'])
            st.write('Catalyst:', rdict['cat'])
            st.write('Expectation Investing:', rdict.get('expectation',{}))
            st.write('Options Skew:', rdict.get('skew',{}))
            st.write('CML/SML Macro Pricing:', rdict.get('cml_sml',{}))
        if st.button('Save this trade to journal'):
            save_trade_journal({'ticker':sel,'decision':row['decision'],'entry':row['entry'],'stop':row['stop'],'target1':row['target1'],'target2':row['target2'],'size':row['position_size'],'thesis':row['thesis'],'outcome':'open','lessons':''})
            st.success('Saved to journal')

with tab4:
    st.subheader('Options positioning')
    sel2=st.selectbox('Options ticker', watch, key='opt_sel')
    exp,calls,puts=get_options_chain(sel2)
    spotdf=get_ohlcv(sel2,'3mo','1d')
    if exp and not spotdf.empty:
        spot=float(spotdf.Close.iloc[-1]); score,meta=options_score(calls,puts,spot)
        st.markdown(f'Expiry: **{exp}** | Options score: **{score:.0f}** | {meta.get("options_read")}')
        col1,col2=st.columns(2)
        with col1: st.bar_chart(calls.groupby('strike')[['openInterest','volume']].sum())
        with col2: st.bar_chart(puts.groupby('strike')[['openInterest','volume']].sum())
        sk, skmeta = skew_score(calls, puts, spot, 'long')
        st.markdown(f'#### Skew expression score: **{sk:.0f}**')
        st.write(skmeta.get('suggested_options_expression'))
        st.json({**meta, **{'skew': skmeta}})
    else: st.info('No option chain available from the free provider.')

with tab5:
    st.subheader('Signal backtest')
    bt_ticker=st.text_input('Backtest ticker', value=watch[0] if watch else 'AAPL')
    strat=st.selectbox('Strategy', ['Breakout','Pullback','Squeeze','Failed breakdown','High RVOL momentum'])
    hold=st.slider('Holding days',2,30,10)
    btdf=get_ohlcv(bt_ticker,'5y','1d')
    trades,metrics=backtest(btdf,strat,hold)
    st.json(metrics)
    if not trades.empty:
        st.line_chart((1+trades['return']).cumprod())
        st.dataframe(trades.tail(50), use_container_width=True)

with tab6:
    st.subheader('Trade journal')
    st.dataframe(read_table('trade_journal'), use_container_width=True)


with tab7:
    st.subheader('CML/SML + Black-Litterman Portfolio Risk Model')
    if results:
        result_dict = dict(results)
        alloc_df, bl_meta = black_litterman_allocation(
            result_dict,
            risk_free_rate=risk_free_rate,
            risk_aversion=bl_risk_aversion,
            tau=bl_tau,
            long_only=True,
            max_weight=bl_max_weight,
        )
        st.write(bl_meta.get('summary'))
        if not alloc_df.empty:
            pretty = alloc_df.copy()
            pct_cols = ['prior_weight','posterior_weight','weight_change','implied_prior_return','posterior_expected_return','view_return','view_confidence']
            for c in pct_cols:
                if c in pretty:
                    pretty[c] = pretty[c].map(lambda x: f'{x:.2%}' if pd.notna(x) else '')
            st.dataframe(pretty, use_container_width=True)
            chart_df = alloc_df.set_index('ticker')[['prior_weight','posterior_weight']]
            st.bar_chart(chart_df)
            st.download_button('Export BL allocation CSV', alloc_df.to_csv(index=False), file_name='black_litterman_allocation.csv')
        else:
            st.info(bl_meta.get('summary'))
    else:
        st.info('Run the scanner first. The Bayesian allocation engine needs scanner results and price histories.')
