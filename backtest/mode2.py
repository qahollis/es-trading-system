# mode2.py
# ES Futures Volume Profile — Execution Simulation
#
# Simulates realistic trading session outcomes using rules:
# Rule 1: One trade at a time — no new entry while trade is open
# Rule 2: Stop trading after 2 losses in a session
#
# Mode 2A: Previous Day levels only (bearish approach, long)
# Mode 2B: All session types (bearish approach, long)
#
# Compares both modes to find optimal strategy for live trading

import os
import sys
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Add pipeline to path for imports
sys.path.insert(0, 'pipeline')

load_dotenv()
EASTERN = ZoneInfo("America/New_York")

DB_URL = f"postgresql://postgres:{os.getenv('PG_PASSWORD')}@localhost:5432/es_trading"
engine = create_engine(DB_URL)

# ── Parameters ─────────────────────────────────────────────────────────────
TICK_SIZE     = 0.25
STOP_TICKS    = 16
TARGET_TICKS  = 60
STOP_POINTS   = STOP_TICKS  * TICK_SIZE   # 4.00 points
TARGET_POINTS = TARGET_TICKS * TICK_SIZE  # 15.00 points
COOLDOWN_BARS = 10
MAX_LOSSES    = 2  # daily loss limit

ENTRY_WINDOW_START = 18.5  # 6:30pm Eastern
ENTRY_WINDOW_END   = 22.0  # 10:00pm Eastern

# ── Data Retrieval ──────────────────────────────────────────────────────────

def get_trading_dates():
    query = """
        SELECT DISTINCT v.trade_date
        FROM volume_profile_levels v
        INNER JOIN es_trades t ON t.trade_date = v.trade_date
        WHERE v.trade_date >= '2024-01-02'
        ORDER BY v.trade_date ASC
    """
    df = pd.read_sql(query, engine)
    return df['trade_date'].tolist()

def get_levels_for_date(trade_date):
    query = f"""
        SELECT session_type, vah, poc, val
        FROM volume_profile_levels
        WHERE trade_date = '{trade_date}'
    """
    df = pd.read_sql(query, engine)
    if df.empty:
        return {}
    levels = {}
    for _, row in df.iterrows():
        levels[row['session_type']] = {
            'vah': float(row['vah']),
            'poc': float(row['poc']),
            'val': float(row['val'])
        }
    return levels

def get_bars_for_date(trade_date):
    query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM es_trades
        WHERE trade_date = '{trade_date}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine)
    if df.empty:
        return None
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp'] = df['timestamp'].dt.tz_convert(EASTERN)
    df = df.reset_index(drop=True)
    return df

def get_session_end(trade_date_str):
    trade_date_dt = pd.Timestamp(trade_date_str)
    return pd.Timestamp(
        str(trade_date_dt.date() + pd.Timedelta(days=1)) + ' 09:30:00'
    ).tz_localize(EASTERN)

# ── Helper Functions ────────────────────────────────────────────────────────

def bar_touched_level(bar_high, bar_low, level_price):
    """Returns True if level falls within bar high-low range."""
    return bar_low <= level_price <= bar_high

def is_in_trading_window(timestamp):
    hour_decimal = timestamp.hour + timestamp.minute / 60
    return ENTRY_WINDOW_START <= hour_decimal <= ENTRY_WINDOW_END

def get_approach_direction(bars, touch_idx, lookback=3):
    if touch_idx < lookback:
        return 'neutral'
    start_price = float(bars.iloc[touch_idx - lookback]['close'])
    end_price   = float(bars.iloc[touch_idx]['close'])
    diff        = end_price - start_price
    if diff > TICK_SIZE:
        return 'bullish'
    elif diff < -TICK_SIZE:
        return 'bearish'
    else:
        return 'neutral'

def get_confluence_count(levels, touched_session, touched_type, level_price):
    """Counts other levels within 4 ticks of touched level."""
    tolerance = 4 * TICK_SIZE
    count = 0
    for session_type, session_levels in levels.items():
        for level_type, lp in session_levels.items():
            if session_type == touched_session and level_type == touched_type:
                continue
            if abs(level_price - lp) <= tolerance:
                count += 1
    return count

def simulate_trade(bars, entry_idx, session_end, entry_price):
    """
    Simulates a LONG trade from entry_idx.
    Returns outcome, ticks, mae, bars_held.
    Always long — Mode 2 only trades long entries.
    """
    mae_ticks = 0

    for i in range(entry_idx + 1, len(bars)):
        bar       = bars.iloc[i]
        bars_held = i - entry_idx
        bar_time  = bar['timestamp']
        bar_high  = float(bar['high'])
        bar_low   = float(bar['low'])

        if bar_time >= session_end:
            return {
                'outcome':  'timeout',
                'ticks':     0,
                'mae':       round(mae_ticks, 1),
                'bars_held': bars_held
            }

        adverse   = max(0, (entry_price - bar_low)  / TICK_SIZE)
        favorable = max(0, (bar_high - entry_price) / TICK_SIZE)

        mae_ticks = max(mae_ticks, adverse)

        if adverse >= STOP_TICKS:
            return {
                'outcome':  'loss',
                'ticks':    -STOP_TICKS,
                'mae':       float(STOP_TICKS),
                'bars_held': bars_held
            }

        if favorable >= TARGET_TICKS:
            return {
                'outcome':  'win',
                'ticks':     TARGET_TICKS,
                'mae':       round(mae_ticks, 1),
                'bars_held': bars_held
            }

    return {
        'outcome':  'timeout',
        'ticks':     0,
        'mae':       round(mae_ticks, 1),
        'bars_held': len(bars) - entry_idx
    }

# ── Signal Scanner ──────────────────────────────────────────────────────────

def scan_session_signals(bars, levels, trade_date_str, session_filter):
    """
    Scans a session for all valid entry signals.
    Returns list of signals sorted by timestamp (chronological).

    session_filter: 'previous_day' for Mode 2A
                    'all' for Mode 2B

    Only returns bearish approach long entries.
    """
    signals = []
    touch_counts = {}
    session_end = get_session_end(trade_date_str)

    for bar_idx in range(len(bars)):
        bar       = bars.iloc[bar_idx]
        timestamp = bar['timestamp']

        if not is_in_trading_window(timestamp):
            continue

        bar_high = float(bar['high'])
        bar_low  = float(bar['low'])

        for session_type, session_levels in levels.items():

            # Mode 2A: previous_day only
            if session_filter == 'previous_day' and session_type != 'previous_day':
                continue

            for level_type, level_price in session_levels.items():

                # Mode 2B: exclude previous_week POC and VAL
                # Previous week VAH included (83.6% win rate)
                # Previous week POC excluded (59.7% win rate)
                # Previous week VAL excluded (78.6% -- borderline)
                if session_filter == 'all' and session_type == 'previous_week' and level_type in ['poc', 'val']:
                    continue

                # Only VAH, POC, VAL
                if level_type not in ['vah', 'poc', 'val']:
                    continue

                # Bar must touch the level
                if not bar_touched_level(bar_high, bar_low, level_price):
                    continue

                # Approach must be bearish
                approach = get_approach_direction(bars, bar_idx)
                if approach not in ['bearish', 'neutral']:
                    continue

                # Cooldown check
                key = (session_type, level_type)
                last_idx = touch_counts.get(key, -999)
                if bar_idx - last_idx < COOLDOWN_BARS:
                    continue

                touch_counts[key] = bar_idx

                confluence = get_confluence_count(
                    levels, session_type, level_type, level_price
                )

                signals.append({
                    'bar_idx':         bar_idx,
                    'timestamp':       timestamp,
                    'session_type':    session_type,
                    'level_type':      level_type,
                    'level_price':     level_price,
                    'confluence_count': confluence,
                    'session_end':     session_end
                })

    return signals

# ── Mode 2 Session Simulator ────────────────────────────────────────────────

def simulate_session(signals, bars, max_losses=MAX_LOSSES):
    """
    Simulates a trading session with real execution rules:
    Rule 1: One trade at a time
    Rule 2: Stop after max_losses losses

    Takes signals in chronological order.
    Returns list of trades taken and session summary.
    """
    trades_taken  = []
    losses_today  = 0
    in_trade      = False
    trade_end_idx = -1

    for signal in signals:
        bar_idx     = signal['bar_idx']
        session_end = signal['session_end']
        level_price = signal['level_price']

        # Rule 2: stop if daily loss limit hit
        if losses_today >= max_losses:
            break

        # Rule 1: skip if trade still open
        if in_trade and bar_idx <= trade_end_idx:
            continue

        # Trade is now closed or never opened
        in_trade = False

        # Enter trade at level price
        result = simulate_trade(bars, bar_idx, session_end, level_price)

        trade_record = {
            'timestamp':        signal['timestamp'],
            'session_type':     signal['session_type'],
            'level_type':       signal['level_type'],
            'level_price':      level_price,
            'confluence_count': signal['confluence_count'],
            'outcome':          result['outcome'],
            'ticks':            result['ticks'],
            'mae':              result['mae'],
            'bars_held':        result['bars_held']
        }
        trades_taken.append(trade_record)

        # Update state
        if result['outcome'] == 'loss':
            losses_today += 1
        elif result['outcome'] == 'win':
            pass

        # Mark trade as open until it closes
        in_trade      = True
        trade_end_idx = bar_idx + result['bars_held']

    return trades_taken

# ── Main Mode 2 Runner ──────────────────────────────────────────────────────

def run_mode2(mode='2A'):
    """
    Runs Mode 2 simulation.
    mode: '2A' = previous_day only
          '2B' = all session types
    """
    session_filter = 'previous_day' if mode == '2A' else 'all'
    label = 'MODE 2A (Previous Day Only)' if mode == '2A' else 'MODE 2B (All Sessions)'

    print("="*60)
    print(f"{label}")
    print(f"Filter: bearish approach, long only")
    print(f"Rules: one trade at a time, {MAX_LOSSES}-loss daily stop")
    print(f"Stop: {STOP_TICKS}t | Target: {TARGET_TICKS}t")
    print("="*60)

    dates = get_trading_dates()
    print(f"\nProcessing {len(dates)} trading days...\n")

    all_trades      = []
    session_results = []

    for date_idx, trade_date in enumerate(dates):
        trade_date_str = (trade_date.isoformat()
                          if hasattr(trade_date, 'isoformat')
                          else str(trade_date))

        levels = get_levels_for_date(trade_date_str)
        bars   = get_bars_for_date(trade_date_str)

        if not levels or bars is None or bars.empty:
            continue

        # Scan for signals
        signals = scan_session_signals(
            bars, levels, trade_date_str, session_filter
        )

        if not signals:
            continue

        # Simulate session with rules
        trades = simulate_session(signals, bars)

        if not trades:
            continue

        # Record session summary
        wins     = sum(1 for t in trades if t['outcome'] == 'win')
        losses   = sum(1 for t in trades if t['outcome'] == 'loss')
        timeouts = sum(1 for t in trades if t['outcome'] == 'timeout')
        net_ticks = sum(t['ticks'] for t in trades)
        signals_available = len(signals)
        signals_taken     = len(trades)
        signals_skipped   = signals_available - signals_taken

        session_results.append({
            'trade_date':         trade_date_str,
            'signals_available':  signals_available,
            'signals_taken':      signals_taken,
            'signals_skipped':    signals_skipped,
            'wins':               wins,
            'losses':             losses,
            'timeouts':           timeouts,
            'net_ticks':          net_ticks,
            'session_profitable': net_ticks > 0
        })

        # Add trade_date to each trade record
        for t in trades:
            t['trade_date'] = trade_date_str
            all_trades.append(t)

        if (date_idx + 1) % 50 == 0:
            print(f"Processed {date_idx+1}/{len(dates)} days — "
                  f"{len(all_trades)} trades taken so far")

    return pd.DataFrame(all_trades), pd.DataFrame(session_results)

# ── Analysis ────────────────────────────────────────────────────────────────

def analyze_mode2(trades_df, sessions_df, label):
    """Prints full analysis of Mode 2 results."""

    print(f"\n{'='*60}")
    print(f"{label} — RESULTS")
    print(f"{'='*60}")

    if trades_df is None or trades_df.empty:
        print("No trades recorded.")
        return

    completed = trades_df[trades_df['outcome'] != 'timeout']

    # Trade level stats
    total   = len(completed)
    wins    = (completed['outcome'] == 'win').sum()
    losses  = (completed['outcome'] == 'loss').sum()
    wr      = wins / total * 100 if total > 0 else 0

    print(f"\nTRADE LEVEL STATS:")
    print(f"  Total trades taken:  {len(trades_df)}")
    print(f"  Completed trades:    {total}")
    print(f"  Wins:                {wins}")
    print(f"  Losses:              {losses}")
    print(f"  Win rate:            {wr:.1f}%")
    print(f"  Avg MAE on wins:     {completed[completed['outcome']=='win']['mae'].mean():.1f} ticks")

    # Expectancy
    exp_ticks = (wr/100 * TARGET_TICKS) - ((1-wr/100) * STOP_TICKS)
    print(f"  Expectancy:          {exp_ticks:+.1f} ticks = ${exp_ticks*12.50:+.2f}/trade")

    # Session level stats
    print(f"\nSESSION LEVEL STATS:")
    total_sessions    = len(sessions_df)
    profitable        = sessions_df['session_profitable'].sum()
    session_wr        = profitable / total_sessions * 100 if total_sessions > 0 else 0
    avg_trades        = sessions_df['signals_taken'].mean()
    avg_skipped       = sessions_df['signals_skipped'].mean()
    avg_net           = sessions_df['net_ticks'].mean()
    stopped_early     = (sessions_df['losses'] >= MAX_LOSSES).sum()

    print(f"  Sessions with trades:    {total_sessions}")
    print(f"  Profitable sessions:     {profitable} ({session_wr:.1f}%)")
    print(f"  Avg trades per session:  {avg_trades:.1f}")
    print(f"  Avg signals skipped:     {avg_skipped:.1f}")
    print(f"  Sessions stopped early:  {stopped_early} ({stopped_early/total_sessions*100:.1f}%)")
    print(f"  Avg net ticks/session:   {avg_net:+.1f}")
    print(f"  Avg net $/session:       ${avg_net*12.50:+.2f}")

    # Monthly estimates
    months = 708 / 21
    print(f"\nMONTHLY ESTIMATES:")
    print(f"  Sessions per month:      {total_sessions/months:.1f}")
    print(f"  Trades per month:        {len(trades_df)/months:.1f}")
    print(f"  Expected net ticks/mo:   {sessions_df['net_ticks'].sum()/months:+.1f}")
    print(f"  Expected net $/mo:       ${sessions_df['net_ticks'].sum()/months*12.50:+.2f}")

    # Confluence breakdown
    print(f"\nCONFLUENCE BREAKDOWN:")
    for conf in sorted(completed['confluence_count'].unique()):
        subset = completed[completed['confluence_count'] == conf]
        if len(subset) < 10:
            continue
        w = (subset['outcome'] == 'win').sum()
        wr_c = w / len(subset) * 100
        print(f"  {conf} confluence(s): {len(subset)} trades, {wr_c:.1f}% win rate")

    # Level type breakdown
    print(f"\nLEVEL TYPE BREAKDOWN:")
    for lt in ['vah', 'poc', 'val']:
        subset = completed[completed['level_type'] == lt]
        if len(subset) < 10:
            continue
        w = (subset['outcome'] == 'win').sum()
        wr_l = w / len(subset) * 100
        exp_l = (wr_l/100*60) - ((1-wr_l/100)*16)
        print(f"  {lt.upper()}: {len(subset)} trades, {wr_l:.1f}% win rate, "
              f"{exp_l:+.1f}t expectancy")

# ── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Run Mode 2A
    trades_2a, sessions_2a = run_mode2(mode='2A')
    analyze_mode2(trades_2a, sessions_2a, "MODE 2A — PREVIOUS DAY ONLY")

    if trades_2a is not None and not trades_2a.empty:
        trades_2a.to_csv('backtest/mode2a_trades.csv', index=False)
        sessions_2a.to_csv('backtest/mode2a_sessions.csv', index=False)
        print("\nMode 2A saved to backtest/mode2a_trades.csv")

    # Run Mode 2B
    trades_2b, sessions_2b = run_mode2(mode='2B')
    analyze_mode2(trades_2b, sessions_2b, "MODE 2B — ALL SESSIONS")

    if trades_2b is not None and not trades_2b.empty:
        trades_2b.to_csv('backtest/mode2b_trades.csv', index=False)
        sessions_2b.to_csv('backtest/mode2b_sessions.csv', index=False)
        print("\nMode 2B saved to backtest/mode2b_trades.csv")

    # Side by side comparison
    if (trades_2a is not None and not trades_2a.empty and
            trades_2b is not None and not trades_2b.empty):

        comp_2a = trades_2a[trades_2a['outcome'] != 'timeout']
        comp_2b = trades_2b[trades_2b['outcome'] != 'timeout']

        wr_2a = (comp_2a['outcome'] == 'win').sum() / len(comp_2a) * 100
        wr_2b = (comp_2b['outcome'] == 'win').sum() / len(comp_2b) * 100

        exp_2a = (wr_2a/100*60) - ((1-wr_2a/100)*16)
        exp_2b = (wr_2b/100*60) - ((1-wr_2b/100)*16)

        months = 708 / 21

        print(f"\n{'='*60}")
        print("SIDE BY SIDE COMPARISON")
        print(f"{'='*60}")
        print(f"{'Metric':<35} {'Mode 2A':>10} {'Mode 2B':>10}")
        print("-"*55)
        print(f"{'Win rate':<35} {wr_2a:>9.1f}% {wr_2b:>9.1f}%")
        print(f"{'Expectancy (ticks/trade)':<35} {exp_2a:>+9.1f}t {exp_2b:>+9.1f}t")
        print(f"{'Expectancy ($/trade)':<35} ${exp_2a*12.50:>+8.2f} ${exp_2b*12.50:>+8.2f}")
        print(f"{'Trades per month':<35} {len(trades_2a)/months:>10.1f} {len(trades_2b)/months:>10.1f}")
        print(f"{'Sessions per month':<35} {len(sessions_2a)/months:>10.1f} {len(sessions_2b)/months:>10.1f}")
        print(f"{'Profitable sessions %':<35} "
              f"{sessions_2a['session_profitable'].mean()*100:>9.1f}% "
              f"{sessions_2b['session_profitable'].mean()*100:>9.1f}%")
        print(f"{'Expected net $/month':<35} "
              f"${sessions_2a['net_ticks'].sum()/months*12.50:>+8.2f} "
              f"${sessions_2b['net_ticks'].sum()/months*12.50:>+8.2f}")
        print()
        print(f"Win rate difference (2A vs 2B): {wr_2a - wr_2b:+.1f}%")
        if wr_2a - wr_2b >= 5:
            print("Mode 2A adds meaningful edge — restriction is worth it")
        elif wr_2a - wr_2b >= 2:
            print("Mode 2A adds modest edge — weigh against lower frequency")
        else:
            print("Modes perform similarly — Mode 2B preferred for frequency")