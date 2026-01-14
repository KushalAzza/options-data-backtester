#!/usr/bin/env python3
"""
Script to add base_ema (20-period EMA) values to india_vix_intraday_price.json
EMA is calculated using 25-minute interval open prices, then applied to all minute entries.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os


def load_vix_data(file_path: str) -> Dict:
    """Load VIX intraday data"""
    print(f"Loading VIX data from {file_path}...")
    with open(file_path, 'r') as f:
        return json.load(f)


def save_vix_data(file_path: str, data: Dict):
    """Save VIX intraday data"""
    print(f"Saving VIX data to {file_path}...")
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)


def calculate_ema_series(opens: List[float], period: int) -> List[Optional[float]]:
    """
    Calculate EMA for a series of open prices.
    Returns list of EMA values (None for first period-1 values).
    """
    if len(opens) < period:
        return [None] * len(opens)
    
    ema_values = []
    multiplier = 2.0 / (period + 1)
    
    # First EMA value is SMA of first 'period' values
    sma = sum(opens[:period]) / period
    
    # Pad with None for first period-1 values
    ema_values = [None] * (period - 1)
    ema_values.append(sma)
    
    # Calculate EMA for remaining values
    for i in range(period, len(opens)):
        ema = (opens[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)
    
    return ema_values


def round_time_to_25min_interval(time_str: str) -> str:
    """
    Round time to the start of the 25-minute interval.
    Example: 09:17:00 -> 09:00:00, 09:45:00 -> 09:25:00
    """
    try:
        time_obj = datetime.strptime(time_str, "%H:%M:%S").time()
        total_minutes = time_obj.hour * 60 + time_obj.minute
        rounded_minutes = (total_minutes // 25) * 25
        rounded_hour = rounded_minutes // 60
        rounded_min = rounded_minutes % 60
        return f"{rounded_hour:02d}:{rounded_min:02d}:00"
    except:
        return time_str


def aggregate_to_25min_intervals(entries: List[Dict], date: str) -> Dict[str, float]:
    """
    Aggregate minute entries into 25-minute intervals.
    Returns a dictionary mapping interval start time (HH:MM:00) to the open price of that interval.
    """
    interval_opens = {}
    
    for entry in entries:
        time_str = entry.get('time', '')
        if not time_str:
            continue
        
        # Round to 25-minute interval
        interval_key = round_time_to_25min_interval(time_str)
        
        # Use the first open price in each interval (fallback to close if open not available)
        if interval_key not in interval_opens:
            open_price = entry.get('open', entry.get('close'))
            if open_price is not None:
                interval_opens[interval_key] = open_price
    
    return interval_opens


def add_base_ema_to_vix_data(vix_data: Dict, period: int = 20, interval_minutes: int = 25) -> Dict:
    """
    Add base_ema (20-period EMA) to each entry in vix_data.
    EMA is calculated using 25-minute interval open prices, then applied to all minute entries.
    
    Args:
        vix_data: Dictionary with dates as keys and lists of minute entries as values
        period: Number of 25-minute intervals for EMA calculation (default: 20)
        interval_minutes: Interval size in minutes (default: 25)
    """
    # Get sorted dates
    dates = sorted(vix_data.keys())
    
    if not dates:
        return vix_data
    
    print(f"Processing {len(dates)} dates...")
    print(f"EMA period: {period} intervals ({period * interval_minutes} minutes)")
    print(f"Interval size: {interval_minutes} minutes")
    
    # Build a chronological list of all 25-minute intervals across all dates
    all_interval_opens = []
    interval_to_index = {}  # Maps (date, interval_time) to index in all_interval_opens
    index_to_interval = {}  # Maps index to (date, interval_time) for reverse lookup
    
    interval_index = 0
    for date in dates:
        entries = vix_data[date]
        if not entries:
            continue
        
        # Aggregate entries into 25-minute intervals for this date
        interval_opens = aggregate_to_25min_intervals(entries, date)
        
        # Sort intervals by time for this date
        sorted_intervals = sorted(interval_opens.items())
        
        for interval_time, open_price in sorted_intervals:
            all_interval_opens.append(open_price)
            interval_to_index[(date, interval_time)] = interval_index
            index_to_interval[interval_index] = (date, interval_time)
            interval_index += 1
    
    print(f"Total 25-minute intervals: {len(all_interval_opens)}")
    
    # Filter out None values for EMA calculation, but keep track of indices
    valid_interval_opens = []
    valid_indices = []
    for i, open_price in enumerate(all_interval_opens):
        if open_price is not None:
            valid_interval_opens.append(open_price)
            valid_indices.append(i)
    
    if len(valid_interval_opens) < period:
        print(f"Warning: Only {len(valid_interval_opens)} valid interval opens, need {period} for EMA calculation")
        # Still process, but EMA will be None for most intervals
    
    # Calculate EMA for valid interval opens
    ema_values = calculate_ema_series(valid_interval_opens, period)
    
    # Map EMA values back to intervals
    interval_to_ema = {}
    for idx, original_idx in enumerate(valid_indices):
        if idx < len(ema_values) and ema_values[idx] is not None:
            date, interval_time = index_to_interval[original_idx]
            interval_to_ema[(date, interval_time)] = ema_values[idx]
    
    # Add base_ema to all minute entries based on their 25-minute interval
    processed_dates = 0
    for date in dates:
        entries = vix_data[date]
        
        for entry in entries:
            time_str = entry.get('time', '')
            if not time_str:
                entry['base_ema'] = None
                continue
            
            # Round to 25-minute interval
            interval_key = round_time_to_25min_interval(time_str)
            
            # Get EMA value for this interval
            ema_value = interval_to_ema.get((date, interval_key))
            entry['base_ema'] = round(ema_value, 2) if ema_value is not None else None
        
        processed_dates += 1
        if processed_dates % 100 == 0:
            print(f"  Processed {processed_dates}/{len(dates)} dates...")
    
    print(f"  Processed {processed_dates}/{len(dates)} dates... Done!")
    return vix_data


def main():
    print("=" * 60)
    print("Add Base EMA (20-period, 25-min intervals) to India VIX Intraday Price Data")
    print("=" * 60)
    
    vix_file = "data/india_vix_intraday_price.json"
    ema_period = 20  # 20 periods
    interval_minutes = 25  # 25-minute intervals
    
    if not os.path.exists(vix_file):
        print(f"Error: VIX data file not found: {vix_file}")
        return
    
    print(f"\nConfiguration:")
    print(f"  VIX data file: {vix_file}")
    print(f"  EMA period: {ema_period} periods ({ema_period * interval_minutes} minutes)")
    print(f"  Interval size: {interval_minutes} minutes")
    print()
    
    # Load data
    vix_data = load_vix_data(vix_file)
    dates = sorted(vix_data.keys())
    print(f"  Loaded {len(dates)} dates")
    if dates:
        print(f"  Date range: {dates[0]} to {dates[-1]}")
    
    # Add EMA values
    print(f"\nCalculating and adding base_ema values ({ema_period}-period EMA on {interval_minutes}-minute intervals)...")
    vix_data = add_base_ema_to_vix_data(vix_data, ema_period, interval_minutes)
    
    # Save data
    print("\nSaving updated VIX data...")
    save_vix_data(vix_file, vix_data)
    print(f"  Saved to {vix_file}")
    
    # Verify
    print("\nVerification:")
    if dates:
        # Check first date with EMA values
        for i, date in enumerate(dates):
            entries = vix_data[date]
            has_ema = any(e.get('base_ema') is not None for e in entries)
            if has_ema:
                print(f"  First date with EMA: {date}")
                # Find first entry with EMA
                for entry in entries:
                    if entry.get('base_ema') is not None:
                        print(f"  First entry with EMA: {entry['time']}")
                        print(f"    open: {entry.get('open', entry.get('close', 'N/A'))}")
                        print(f"    base_ema: {entry['base_ema']}")
                        break
                break
        
        # Check last date
        last_date = dates[-1]
        last_entries = vix_data[last_date]
        if last_entries:
            last_entry = last_entries[-1]
            print(f"  Last entry: {last_entry['time']}")
            print(f"    open: {last_entry.get('open', last_entry.get('close', 'N/A'))}")
            print(f"    base_ema: {last_entry.get('base_ema')}")
        
        # Show a sample of dates with EMA values
        print(f"\n  Sample dates with EMA values:")
        sample_count = 0
        for date in dates:
            entries = vix_data[date]
            if entries and entries[0].get('base_ema') is not None:
                first_open = entries[0].get('open', entries[0].get('close', 'N/A'))
                print(f"    {date}: EMA = {entries[0]['base_ema']}, Open = {first_open}")
                sample_count += 1
                if sample_count >= 5:
                    break
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
