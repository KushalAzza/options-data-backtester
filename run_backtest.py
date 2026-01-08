#!/usr/bin/env python3
"""
Nifty Options Backtest Script
Backtests ATM CE and PE options strategy for specified period
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math


def load_config(config_path: str = "config.json") -> Dict:
    """Load configuration from JSON file"""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_nifty_intraday(nifty_file: str) -> Dict:
    """Load Nifty intraday price data"""
    print(f"Loading Nifty intraday data from {nifty_file}...")
    with open(nifty_file, 'r') as f:
        return json.load(f)


def load_vix_intraday(vix_file: str) -> Dict:
    """Load India VIX intraday price data"""
    print(f"Loading India VIX intraday data from {vix_file}...")
    with open(vix_file, 'r') as f:
        return json.load(f)


def load_options_data(options_file: str) -> Optional[Dict]:
    """Load options data for a specific date"""
    if not os.path.exists(options_file):
        return None
    try:
        with open(options_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {options_file}: {e}")
        return None


def round_to_strike(price: float, strike_rounding: int = 50) -> int:
    """Round price to nearest strike"""
    return int(round(price / strike_rounding) * strike_rounding)


def get_price_at_time(data: List[Dict], target_time: str) -> Optional[float]:
    """Get close price at specific time from minute-level data"""
    for entry in data:
        if entry.get('datetime', entry.get('time', '')).startswith(target_time[:10] + ' ' + target_time[11:]):
            return entry.get('close')
    return None


def get_nifty_price_at_time(nifty_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get Nifty close price at specific date and time"""
    date_key = date
    if date_key not in nifty_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in nifty_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('close')
    return None


def get_vix_price_at_time(vix_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get India VIX close price at specific date and time"""
    date_key = date
    if date_key not in vix_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in vix_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('close')
    return None


def find_atm_strike(spot_price: float, strike_rounding: int = 50) -> int:
    """Find ATM strike price"""
    return round_to_strike(spot_price, strike_rounding)


def get_option_price(options_data: Dict, option_type: str, strike: int, time_str: str) -> Optional[float]:
    """Get option price at specific time"""
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None
    
    strike_data = option_section[strike_key]
    target_datetime = f"{options_data['date']} {time_str}"
    
    for entry in strike_data:
        if entry.get('datetime') == target_datetime:
            return entry.get('close')
    
    return None


def get_option_price_closest(options_data: Dict, option_type: str, strike: int, time_str: str) -> Optional[float]:
    """Get option price closest to target time (within 5 minutes)"""
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None
    
    strike_data = option_section[strike_key]
    target_datetime = datetime.strptime(f"{options_data['date']} {time_str}", "%Y-%m-%d %H:%M:%S")
    
    closest_price = None
    min_diff = timedelta(hours=24)
    
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            entry_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            diff = abs(entry_datetime - target_datetime)
            
            if diff <= timedelta(minutes=5) and diff < min_diff:
                min_diff = diff
                closest_price = entry.get('close')
        except:
            continue
    
    return closest_price


def check_stop_loss(options_data: Dict, option_type: str, strike: int, entry_time: str, 
                    exit_time: str, entry_price: float, stop_loss_percentage: float) -> Tuple[Optional[float], Optional[str]]:
    """
    Check if stop loss is hit between entry and exit times.
    For SHORT positions: stop loss triggers when price increases by stop_loss_percentage.
    Returns: (stop_loss_exit_price, stop_loss_exit_time) or (None, None) if not hit
    """
    if stop_loss_percentage <= 0 or entry_price is None:
        return None, None
    
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None, None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None, None
    
    strike_data = option_section[strike_key]
    entry_datetime = datetime.strptime(f"{options_data['date']} {entry_time}", "%Y-%m-%d %H:%M:%S")
    exit_datetime = datetime.strptime(f"{options_data['date']} {exit_time}", "%Y-%m-%d %H:%M:%S")
    
    # Calculate stop loss price (for SHORT: price goes UP by stop_loss_percentage)
    stop_loss_price = entry_price * (1 + stop_loss_percentage / 100)
    
    # Check prices between entry and exit times
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            price = entry.get('close')
            
            # Only check times between entry and exit
            if entry_datetime <= price_datetime <= exit_datetime:
                # For SHORT: stop loss triggers when price >= stop_loss_price
                if price is not None and price >= stop_loss_price:
                    return price, entry_datetime_str.split(' ')[1]  # Return time part only
        except:
            continue
    
    return None, None


def run_backtest(config: Dict) -> List[Dict]:
    """Run backtest for specified period"""
    results = []
    
    # Load data
    nifty_data = load_nifty_intraday(config['data_paths']['nifty_intraday'])
    
    # Load VIX data if path is configured
    vix_data = None
    vix_threshold = config['options'].get('vix_threshold', None)
    if vix_threshold is not None and 'vix_intraday' in config['data_paths']:
        vix_data = load_vix_intraday(config['data_paths']['vix_intraday'])
    
    # Parse dates
    start_date = datetime.strptime(config['backtest_period']['start_date'], "%Y-%m-%d")
    end_date = datetime.strptime(config['backtest_period']['end_date'], "%Y-%m-%d")
    
    entry_time = config['trading_times']['entry_time']
    exit_time = config['trading_times']['exit_time']
    
    strike_rounding = config['strike_selection']['strike_rounding']
    ce_offset = config['strike_selection']['ce_strike_offset']
    pe_offset = config['strike_selection']['pe_strike_offset']
    lot_size = config['options']['lot_size']
    lot_multiple = config['options'].get('lot_multiple', 1)
    use_next_expiry = config['options']['use_next_expiry']
    stop_loss_percentage = config['options'].get('stop_loss_percentage', 0)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        print(f"Processing {date_str}...")
        
        # Determine options file
        year = current_date.year
        options_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}.json"
        if use_next_expiry and os.path.exists(f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}_next_expiry.json"):
            options_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}_next_expiry.json"
        
        options_data = load_options_data(options_file)
        if not options_data:
            print(f"  No options data found for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Get Nifty prices
        nifty_entry_price = get_nifty_price_at_time(nifty_data, date_str, entry_time)
        nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, exit_time)
        
        if not nifty_entry_price or not nifty_exit_price:
            print(f"  Missing Nifty price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Check VIX threshold if configured
        entry_reason = "NORMAL"
        if vix_data is not None and vix_threshold is not None:
            vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time)
            if vix_entry_price is not None and vix_entry_price > vix_threshold:
                print(f"  VIX threshold exceeded: {vix_entry_price} > {vix_threshold}, skipping trade")
                entry_reason = "VIX_THRESHOLD_EXCEEDED"
                # Store skipped trade result
                result = {
                    "date": date_str,
                    "entry_time": f"{date_str} {entry_time}",
                    "exit_time": f"{date_str} {entry_time}",
                    "entry_reason": entry_reason,
                    "vix_at_entry": round(vix_entry_price, 2),
                    "vix_at_exit": round(vix_entry_price, 2),  # Same as entry since no trade occurred
                    "nifty_entry_price": round(nifty_entry_price, 2),
                    "nifty_exit_price": round(nifty_entry_price, 2),
                    "ce_strike": None,
                    "ce_entry_price": None,
                    "ce_exit_price": None,
                    "ce_exit_time": None,
                    "ce_exit_reason": None,
                    "ce_stopped": False,
                    "ce_pnl": 0.0,
                    "pe_strike": None,
                    "pe_entry_price": None,
                    "pe_exit_price": None,
                    "pe_exit_time": None,
                    "pe_exit_reason": None,
                    "pe_stopped": False,
                    "pe_pnl": 0.0,
                    "total_pnl": 0.0
                }
                results.append(result)
                current_date += timedelta(days=1)
                continue
        
        # Calculate strikes
        atm_strike = find_atm_strike(nifty_entry_price, strike_rounding)
        ce_strike = atm_strike + (ce_offset * strike_rounding)
        pe_strike = atm_strike + (pe_offset * strike_rounding)
        
        # Get option entry prices
        ce_entry_price = get_option_price_closest(options_data, 'CE', ce_strike, entry_time)
        pe_entry_price = get_option_price_closest(options_data, 'PE', pe_strike, entry_time)
        
        if ce_entry_price is None or pe_entry_price is None:
            print(f"  Missing option entry price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Check for stop loss - each leg runs independently
        # CE leg: Check stop loss between entry_time and scheduled exit_time
        ce_stop_loss_price, ce_stop_loss_time = check_stop_loss(
            options_data, 'CE', ce_strike, entry_time, exit_time, 
            ce_entry_price, stop_loss_percentage
        )
        
        # Determine CE exit price and time
        if ce_stop_loss_price is not None:
            ce_exit_price = ce_stop_loss_price
            ce_exit_time = ce_stop_loss_time
            ce_stopped = True
            ce_exit_reason = "STOP_LOSS"
        else:
            # CE did not hit stop loss, use scheduled exit
            ce_exit_price = get_option_price_closest(options_data, 'CE', ce_strike, exit_time)
            ce_exit_time = exit_time
            ce_stopped = False
            ce_exit_reason = "SCHEDULED_EXIT"
        
        # PE leg: Check stop loss between entry_time and scheduled exit_time
        # PE continues regardless of CE's stop loss status
        pe_stop_loss_price, pe_stop_loss_time = check_stop_loss(
            options_data, 'PE', pe_strike, entry_time, exit_time,
            pe_entry_price, stop_loss_percentage
        )
        
        # Determine PE exit price and time
        if pe_stop_loss_price is not None:
            pe_exit_price = pe_stop_loss_price
            pe_exit_time = pe_stop_loss_time
            pe_stopped = True
            pe_exit_reason = "STOP_LOSS"
        else:
            # PE did not hit stop loss, use scheduled exit
            pe_exit_price = get_option_price_closest(options_data, 'PE', pe_strike, exit_time)
            pe_exit_time = exit_time
            pe_stopped = False
            pe_exit_reason = "SCHEDULED_EXIT"
        
        if ce_exit_price is None or pe_exit_price is None:
            print(f"  Missing option exit price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Calculate P&L (SHORT positions: sell at entry, buy back at exit)
        # Apply lot_multiple to scale the position size
        ce_pnl = (ce_entry_price - ce_exit_price) * lot_size * lot_multiple
        pe_pnl = (pe_entry_price - pe_exit_price) * lot_size * lot_multiple
        total_pnl = ce_pnl + pe_pnl
        
        # Determine overall exit time (earliest of CE/PE exit times for display purposes)
        # Note: Each leg exits independently, but we track the earliest for overall exit time
        exit_times = [ce_exit_time, pe_exit_time]
        overall_exit_time = min(exit_times)
        
        # Get Nifty price at overall exit time (earliest exit)
        nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, overall_exit_time)
        if nifty_exit_price is None:
            # Fallback to scheduled exit time price if not available
            nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, exit_time)
        
        # Get VIX at entry and exit for record keeping
        vix_at_entry = None
        vix_at_exit = None
        if vix_data is not None:
            vix_at_entry = get_vix_price_at_time(vix_data, date_str, entry_time)
            vix_at_exit = get_vix_price_at_time(vix_data, date_str, overall_exit_time)
        
        # Store result
        result = {
            "date": date_str,
            "entry_time": f"{date_str} {entry_time}",
            "exit_time": f"{date_str} {overall_exit_time}",
            "entry_reason": entry_reason,
            "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
            "vix_at_exit": round(vix_at_exit, 2) if vix_at_exit is not None else None,
            "nifty_entry_price": round(nifty_entry_price, 2),
            "nifty_exit_price": round(nifty_exit_price, 2) if nifty_exit_price else round(get_nifty_price_at_time(nifty_data, date_str, exit_time) or 0, 2),
            "ce_strike": ce_strike,
            "ce_entry_price": round(ce_entry_price, 2),
            "ce_exit_price": round(ce_exit_price, 2),
            "ce_exit_time": f"{date_str} {ce_exit_time}",
            "ce_exit_reason": ce_exit_reason,
            "ce_stopped": ce_stopped,
            "ce_pnl": round(ce_pnl, 2),
            "pe_strike": pe_strike,
            "pe_entry_price": round(pe_entry_price, 2),
            "pe_exit_price": round(pe_exit_price, 2),
            "pe_exit_time": f"{date_str} {pe_exit_time}",
            "pe_exit_reason": pe_exit_reason,
            "pe_stopped": pe_stopped,
            "pe_pnl": round(pe_pnl, 2),
            "total_pnl": round(total_pnl, 2)
        }
        
        results.append(result)
        print(f"  CE Strike: {ce_strike}, Entry: {ce_entry_price}, Exit: {ce_exit_price} at {ce_exit_time} ({ce_exit_reason}), P&L: {ce_pnl}")
        print(f"  PE Strike: {pe_strike}, Entry: {pe_entry_price}, Exit: {pe_exit_price} at {pe_exit_time} ({pe_exit_reason}), P&L: {pe_pnl}")
        print(f"  Total P&L: {total_pnl}")
        if ce_exit_reason == "STOP_LOSS" and pe_exit_reason == "STOP_LOSS":
            print(f"    → Both legs hit stop loss")
        elif ce_exit_reason == "STOP_LOSS":
            print(f"    → CE hit stop loss at {ce_exit_time}, PE continued until {pe_exit_time}")
        elif pe_exit_reason == "STOP_LOSS":
            print(f"    → PE hit stop loss at {pe_exit_time}, CE continued until {ce_exit_time}")
        
        current_date += timedelta(days=1)
    
    return results


def calculate_drawdown_metrics(results: List[Dict]) -> tuple:
    """Calculate max drawdown and max drawdown days from results"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED) for drawdown calculation
    actual_trades = [r for r in results if r.get('entry_reason') != 'VIX_THRESHOLD_EXCEEDED']
    
    if not actual_trades:
        return 0.0, 0
    
    # Calculate cumulative P&L for each trade day
    cumulative_pnl = []
    cumsum = 0
    for r in actual_trades:
        cumsum += r['ce_pnl'] + r['pe_pnl']
        cumulative_pnl.append(cumsum)
    
    if not cumulative_pnl:
        return 0.0, 0
    
    # Calculate max drawdown
    max_drawdown = 0.0
    peak = cumulative_pnl[0]
    max_drawdown_days = 0
    current_drawdown_days = 0
    
    for i, cum_pnl in enumerate(cumulative_pnl):
        # Update peak
        if cum_pnl > peak:
            peak = cum_pnl
            current_drawdown_days = 0
        else:
            # Calculate drawdown from peak
            drawdown = peak - cum_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            # Count drawdown days (days below peak)
            if cum_pnl < peak:
                current_drawdown_days += 1
                if current_drawdown_days > max_drawdown_days:
                    max_drawdown_days = current_drawdown_days
    
    return round(max_drawdown, 2), max_drawdown_days


def save_results(results: List[Dict], output_file: str, per_order_charges: float = 30.0, lot_multiple: int = 1):
    """Save backtest results to JSON file"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED) for trade statistics
    actual_trades = [r for r in results if r.get('entry_reason') != 'VIX_THRESHOLD_EXCEEDED']
    
    max_drawdown, max_drawdown_days = calculate_drawdown_metrics(results)
    
    # Calculate total charges: Each actual trade day has 4 orders (CE entry, CE exit, PE entry, PE exit)
    # Note: lot_multiple affects position size (P&L) but not number of orders
    # Each order can be for multiple lots, so it's still 1 order per leg per action
    total_orders = len(actual_trades) * 4
    total_charges = total_orders * per_order_charges
    
    # Calculate net P&L after charges (only for actual trades)
    total_pnl = round(sum(r['total_pnl'] for r in actual_trades), 2)
    net_pnl = round(total_pnl - total_charges, 2)
    
    # Total trading days includes all days (skipped + actual trades)
    total_trading_days = len(results)
    
    summary = {
        "total_trading_days": total_trading_days,
        "total_trades": len(actual_trades),
        "total_pnl": total_pnl,
        "total_orders": total_orders,
        "per_order_charges": per_order_charges,
        "total_charges": round(total_charges, 2),
        "net_pnl": net_pnl,
        "winning_trades": len([r for r in actual_trades if r['total_pnl'] > 0]),
        "losing_trades": len([r for r in actual_trades if r['total_pnl'] < 0]),
        "average_pnl": round(sum(r['total_pnl'] for r in actual_trades) / len(actual_trades) if actual_trades else 0, 2),
        "max_profit": round(max([r['total_pnl'] for r in actual_trades]) if actual_trades else 0, 2),
        "max_loss": round(min([r['total_pnl'] for r in actual_trades]) if actual_trades else 0, 2),
        "max_drawdown": max_drawdown,
        "max_drawdown_days": max_drawdown_days,
        "results": results
    }
    
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nResults saved to {output_file}")
    print(f"Total Trading Days: {summary['total_trading_days']}")
    print(f"Total Trades: {summary['total_trades']}")
    print(f"Total Orders: {summary['total_orders']}")
    print(f"Per Order Charges: ₹{summary['per_order_charges']}")
    print(f"Total Charges: ₹{summary['total_charges']}")
    print(f"Total P&L: ₹{summary['total_pnl']}")
    print(f"Net P&L (after charges): ₹{summary['net_pnl']}")
    print(f"Winning Trades: {summary['winning_trades']}")
    print(f"Losing Trades: {summary['losing_trades']}")
    print(f"Average P&L: ₹{summary['average_pnl']}")
    print(f"Max Drawdown: ₹{summary['max_drawdown']}")
    print(f"Max Drawdown Days: {summary['max_drawdown_days']}")


def main():
    """Main function"""
    print("=" * 60)
    print("Nifty Options Backtest")
    print("=" * 60)
    
    # Load configuration
    config = load_config()
    
    # Run backtest
    results = run_backtest(config)
    
    if not results:
        print("No results generated. Please check your data files.")
        return
    
    # Save results
    output_json = config['output']['results_json']
    per_order_charges = config['options'].get('per_order_charges', 30.0)
    lot_multiple = config['options'].get('lot_multiple', 1)
    save_results(results, output_json, per_order_charges, lot_multiple)
    
    print("\nBacktest completed successfully!")
    print(f"View results in web app: python3 app.py")


if __name__ == "__main__":
    main()

