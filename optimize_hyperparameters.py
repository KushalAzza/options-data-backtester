#!/usr/bin/env python3
"""
Hyperparameter Optimization Script for Nifty Options Backtest
Uses Optuna to find optimal configuration parameters
"""

import json
import os
import optuna  # type: ignore
from optuna.visualization import plot_optimization_history, plot_param_importances  # type: ignore
import copy
import subprocess
import threading
import shutil
from run_intraday_backtest import run_backtest, load_config, calculate_drawdown_metrics, load_nifty_intraday
from datetime import datetime, timedelta


def load_base_config(config_path: str = "config_optimization.json") -> dict:
    """Load base configuration from JSON file for optimization"""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_optimization_params(params_path: str = "optimization_params.json") -> dict:
    """Load optimization parameters (ranges, trials, etc.) from JSON file"""
    if not os.path.exists(params_path):
        # Return default values if file doesn't exist
        return {
            "optimization_settings": {
                "n_trials": 200,
                "n_jobs": 7,
                "study_name": "nifty_options_optimization",
                "sampler_seed": 42
            },
            "parameter_ranges": {
                "entry_time": {
                    "entry_hour": {"min": 9, "max": 12},
                    "entry_minute": {
                        "values": [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55],
                        "excluded_for_hour_9": [0, 5, 10, 15]
                    }
                },
                "stop_loss_percentage": {"min": 0, "max": 50, "step": 2},
                "target_percentage": {"min": 0, "max": 100, "step": 2},
                "vix_threshold": {"min": 12, "max": 26, "step": 2},
                "use_next_expiry": {"values": [True, False]},
                "reentry": {
                    "enabled": {"values": [True, False]},
                    "max_reentries": {"min": 1, "max": 5, "step": 1},
                    "stop_loss_cooldown_minutes": {"min": 0, "max": 120, "step": 5}
                },
                "ema_signals": {
                    "fast_ema": {"min": 2, "max": 24, "step": 2},
                    "slow_ema": {"min": 12, "max": 60, "step": 2},
                    "round_to_ema_interval": {"values": [True, False]},
                    "time_interval": 5
                }
            }
        }
    
    with open(params_path, 'r') as f:
        return json.load(f)


def save_config(config: dict, config_path: str = "config.json"):
    """Save configuration to JSON file"""
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


def format_time(hour: int, minute: int) -> str:
    """Format hour and minute as HH:MM:SS"""
    return f"{hour:02d}:{minute:02d}:00"


def create_temp_nifty_data_for_backtest(config: dict, trial_id: int = None, use_cache: bool = True) -> str:
    """Create a temporary nifty data file with only the backtest date range + buffer for EMA calculation"""
    # Parse backtest period
    start_date = datetime.strptime(config['backtest_period']['start_date'], "%Y-%m-%d")
    end_date = datetime.strptime(config['backtest_period']['end_date'], "%Y-%m-%d")
    
    # Create a cache key based on date range (not EMA params, as those change)
    date_range_key = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    
    # Check if we already have a cached file for this date range (without EMA)
    if use_cache and trial_id is None:
        cache_file = f"data/nifty_intraday_temp_{date_range_key}_base.json"
        if os.path.exists(cache_file):
            return cache_file
    
    # Load full nifty data
    nifty_file = config['data_paths']['nifty_intraday']
    full_nifty_data = load_nifty_intraday(nifty_file)
    
    # Get EMA parameters to determine how much historical data we need
    ema_config = config.get('ema_signals', {})
    if not ema_config.get('enabled', False):
        # If EMA not enabled, we still need some buffer for consistency
        buffer_days = 10
    else:
        # Need enough historical data for slow_ema calculation (use max of fast/slow)
        fast_ema = ema_config.get('fast_ema', 9)
        slow_ema = ema_config.get('slow_ema', 21)
        max_ema_period = max(fast_ema, slow_ema)
        # Add buffer: need at least max_ema_period days of data before start_date
        # Plus some extra for safety (weekends, etc.)
        buffer_days = max_ema_period + 20
    
    # Calculate date range: start from buffer_days before start_date to end_date
    historical_start = start_date - timedelta(days=buffer_days)
    
    # Extract only the dates we need
    temp_nifty_data = {}
    all_dates = sorted(full_nifty_data.keys())
    
    for date_str in all_dates:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            # Include dates from historical_start to end_date
            if historical_start.date() <= date_obj.date() <= end_date.date():
                temp_nifty_data[date_str] = full_nifty_data[date_str]
        except:
            continue
    
    # Save to temporary file with proper error handling (include trial_id for uniqueness)
    if trial_id is not None:
        temp_nifty_file = f"data/nifty_intraday_temp_{date_range_key}_{trial_id}.json"
    else:
        temp_nifty_file = f"data/nifty_intraday_temp_{date_range_key}_base.json"
    
    # Use a temporary file first, then rename to ensure atomic write
    temp_file_write = temp_nifty_file + ".tmp"
    try:
        with open(temp_file_write, 'w') as f:
            json.dump(temp_nifty_data, f, indent=2)
        
        # Verify the file was written correctly by trying to read it back
        with open(temp_file_write, 'r') as f:
            json.load(f)  # This will raise an error if JSON is invalid
        
        # If successful, rename to final file
        if os.path.exists(temp_nifty_file):
            os.remove(temp_nifty_file)
        os.rename(temp_file_write, temp_nifty_file)
        
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_file_write):
            os.remove(temp_file_write)
        raise Exception(f"Failed to create temporary nifty data file: {e}")
    
    return temp_nifty_file


def run_backtest_with_config(config: dict, recalculate_ema: bool = True, trial_id: int = None) -> dict:
    """Run backtest with given configuration and return summary metrics"""
    # Use trial_id to make temporary files unique for parallel processing
    if trial_id is None:
        trial_id = threading.get_ident()  # Use thread ID as fallback
    
    # Save config temporarily with unique name
    temp_config_path = f"config_temp_optimization_{trial_id}.json"
    temp_nifty_file = None
    original_nifty_path = None
    original_results_json = None
    
    try:
        # Create temporary nifty data file with only backtest date range
        temp_nifty_file = create_temp_nifty_data_for_backtest(config, trial_id=trial_id)
        original_nifty_path = config['data_paths']['nifty_intraday']
        config['data_paths']['nifty_intraday'] = temp_nifty_file
        
        # Use unique results file for each trial to avoid conflicts
        original_results_json = config['output'].get('results_json', 'backtest_results.json')
        config['output']['results_json'] = f"backtest_results_optimization_{trial_id}.json"
        
        # Save updated config
        save_config(config, temp_config_path)
        
        # If EMA parameters changed, recalculate EMA values on the temporary file
        if recalculate_ema and config.get('ema_signals', {}).get('enabled', False):
            # Check if EMA already calculated for these parameters (global cache)
            ema_config = config.get('ema_signals', {})
            ema_cache_key = (
                ema_config.get('time_interval', 5),
                ema_config.get('fast_ema', 9),
                ema_config.get('slow_ema', 21)
            )
            
            # Check global cache for this EMA combination
            cached_ema_file = None
            with _ema_cache_lock:
                if ema_cache_key in _ema_cache:
                    cached_ema_file = _ema_cache[ema_cache_key]
                    if os.path.exists(cached_ema_file):
                        # Copy cached file to trial-specific file
                        shutil.copy2(cached_ema_file, temp_nifty_file)
                        cached_ema_file = temp_nifty_file
            
            if cached_ema_file is None:
                # Need to calculate EMA - save optimization config temporarily for EMA calculation
                temp_config_for_ema = f"config_temp_for_ema_{trial_id}.json"
                save_config(config, temp_config_for_ema)
                try:
                    # Run EMA calculation script with optimization config file
                    # This will calculate EMA only on the temporary file (backtest date range)
                    result = subprocess.run(
                        ['python3', 'utils/cal_ema_nifty_data.py', temp_config_for_ema],
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 minute timeout
                    )
                    if result.returncode != 0:
                        print(f"Warning: EMA calculation failed: {result.stderr}")
                        raise Exception(f"EMA calculation failed: {result.stderr}")
                    
                    # Verify the file is still valid JSON after EMA calculation
                    try:
                        with open(temp_nifty_file, 'r') as f:
                            json.load(f)
                    except json.JSONDecodeError as e:
                        raise Exception(f"Temporary nifty file corrupted after EMA calculation: {e}")
                    
                    # Cache this EMA calculation (create a base cache file)
                    cache_base_file = f"data/nifty_intraday_temp_ema_{ema_cache_key[0]}_{ema_cache_key[1]}_{ema_cache_key[2]}.json"
                    if not os.path.exists(cache_base_file):
                        shutil.copy2(temp_nifty_file, cache_base_file)
                        with _ema_cache_lock:
                            _ema_cache[ema_cache_key] = cache_base_file
                finally:
                    # Clean up temporary config file
                    if os.path.exists(temp_config_for_ema):
                        os.remove(temp_config_for_ema)
        
        # Run backtest (will use the temporary nifty file)
        # Note: run_backtest() only returns results list, it doesn't save files or to DB
        # We calculate metrics from results directly, no file conflicts
        results = run_backtest(config)
        
        if not results:
            return {
                'net_pnl': -999999,
                'max_loss': 999999,
                'max_drawdown': 999999,
                'max_drawdown_days': 9999,
                'total_trades': 0,
                'total_pnl': 0,
                'total_charges': 0
            }
        
        # Calculate metrics
        actual_trades = [r for r in results if r.get('entry_reason') not in ['VIX_THRESHOLD_EXCEEDED', 'EMA_NEUTRAL']]
        
        if not actual_trades:
            return {
                'net_pnl': -999999,
                'max_loss': 999999,
                'max_drawdown': 999999,
                'max_drawdown_days': 9999,
                'total_trades': 0,
                'total_pnl': 0,
                'total_charges': 0
            }
        
        # Calculate total orders and charges
        total_orders = 0
        for r in actual_trades:
            if r.get('ce_strike') is not None:
                total_orders += 2
            if r.get('pe_strike') is not None:
                total_orders += 2
        
        per_order_charges = config['options'].get('per_order_charges', 100)
        total_charges = total_orders * per_order_charges
        
        # Calculate net P&L
        total_pnl = sum(r['total_pnl'] for r in actual_trades)
        net_pnl = total_pnl - total_charges
        
        # Calculate max loss
        max_loss = min([r['total_pnl'] for r in actual_trades]) if actual_trades else 0
        
        # Calculate drawdown metrics
        max_drawdown, max_drawdown_days = calculate_drawdown_metrics(results)
        
        return {
            'net_pnl': net_pnl,
            'max_loss': max_loss,
            'max_drawdown': max_drawdown,
            'max_drawdown_days': max_drawdown_days,
            'total_trades': len(actual_trades),
            'total_pnl': total_pnl,
            'total_charges': total_charges
        }
    finally:
        # Restore original nifty path in config (for reference, though we're done with it)
        if original_nifty_path:
            config['data_paths']['nifty_intraday'] = original_nifty_path
        
        # Restore original results JSON path
        if original_results_json:
            config['output']['results_json'] = original_results_json
        
        # Clean up temp config if exists
        if os.path.exists(temp_config_path):
            try:
                os.remove(temp_config_path)
            except:
                pass  # Ignore errors during cleanup
        
        # Clean up temporary nifty data file
        if temp_nifty_file and os.path.exists(temp_nifty_file):
            try:
                os.remove(temp_nifty_file)
            except:
                pass  # Ignore errors during cleanup
        
        # Clean up temporary results file (optimization doesn't need it)
        # Get the temp results file path before restoring original
        temp_results_file = None
        if 'output' in config and 'results_json' in config['output']:
            temp_results_file = config['output']['results_json']
        
        # Restore original results JSON path (if not already restored above)
        if original_results_json and config.get('output', {}).get('results_json') != original_results_json:
            config['output']['results_json'] = original_results_json
        
        # Clean up temp results file if it was created
        if temp_results_file and temp_results_file.startswith('backtest_results_optimization_'):
            try:
                if os.path.exists(temp_results_file):
                    os.remove(temp_results_file)
            except:
                pass  # Ignore errors during cleanup


# Global EMA cache (shared across all workers) - key: (time_interval, fast_ema, slow_ema), value: file_path
_ema_cache = {}
_ema_cache_lock = threading.Lock()

# Thread-local storage for EMA parameters cache (for parallel processing)
_local = threading.local()

def objective(trial: optuna.Trial, opt_params: dict) -> float:
    """Objective function for Optuna optimization"""
    # Use thread-local storage for EMA cache to support parallel processing
    if not hasattr(_local, 'last_ema_params'):
        _local.last_ema_params = None
    
    # Load base config from optimization config file
    base_config = load_base_config("config_optimization.json")
    config = copy.deepcopy(base_config)
    
    param_ranges = opt_params['parameter_ranges']
    
    # Parameter 1: entry_time
    entry_hour_range = param_ranges['entry_time']['entry_hour']
    entry_hour = trial.suggest_int('entry_hour', entry_hour_range['min'], entry_hour_range['max'])
    
    # Use categorical for entry_minute
    entry_minute_values = param_ranges['entry_time']['entry_minute']['values']
    entry_minute = trial.suggest_categorical('entry_minute', entry_minute_values)
    
    # Exclude invalid combinations if specified
    excluded_minutes = param_ranges['entry_time']['entry_minute'].get('excluded_for_hour_9', [])
    if entry_hour == 9 and entry_minute in excluded_minutes:
        raise optuna.TrialPruned(f"Invalid entry time: 9:{entry_minute:02d} is excluded")
    
    config['trading_times']['entry_time'] = format_time(entry_hour, entry_minute)
    
    # Parameter 2: stop_loss_percentage, target_percentage, vix_threshold, use_next_expiry
    sl_range = param_ranges['stop_loss_percentage']
    config['options']['stop_loss_percentage'] = trial.suggest_float('stop_loss_percentage', sl_range['min'], sl_range['max'], step=sl_range['step'])
    
    target_range = param_ranges['target_percentage']
    config['options']['target_percentage'] = trial.suggest_float('target_percentage', target_range['min'], target_range['max'], step=target_range['step'])
    
    vix_range = param_ranges['vix_threshold']
    config['options']['vix_threshold'] = trial.suggest_int('vix_threshold', vix_range['min'], vix_range['max'], step=vix_range['step'])
    
    config['options']['use_next_expiry'] = trial.suggest_categorical('use_next_expiry', param_ranges['use_next_expiry']['values'])
    
    # Parameter 3: reentry enabled and max_reentries
    reentry_enabled = trial.suggest_categorical('reentry_enabled', param_ranges['reentry']['enabled']['values'])
    config['reentry']['enabled'] = reentry_enabled
    if reentry_enabled:
        max_reentries_range = param_ranges['reentry']['max_reentries']
        config['reentry']['max_reentries'] = trial.suggest_int('max_reentries', max_reentries_range['min'], max_reentries_range['max'], step=max_reentries_range['step'])
    else:
        config['reentry']['max_reentries'] = 0
    
    # Parameter 4: stop_loss_cooldown_minutes
    cooldown_range = param_ranges['reentry']['stop_loss_cooldown_minutes']
    config['reentry']['stop_loss_cooldown_minutes'] = trial.suggest_int('stop_loss_cooldown_minutes', cooldown_range['min'], cooldown_range['max'], step=cooldown_range['step'])
    
    # Parameter 5: EMA signals
    config['ema_signals']['time_interval'] = param_ranges['ema_signals']['time_interval']  # Fixed, not optimized
    
    fast_ema_range = param_ranges['ema_signals']['fast_ema']
    config['ema_signals']['fast_ema'] = trial.suggest_int('ema_fast', fast_ema_range['min'], fast_ema_range['max'], step=fast_ema_range['step'])
    
    slow_ema_range = param_ranges['ema_signals']['slow_ema']
    config['ema_signals']['slow_ema'] = trial.suggest_int('ema_slow', slow_ema_range['min'], slow_ema_range['max'], step=slow_ema_range['step'])
    
    config['ema_signals']['round_to_ema_interval'] = trial.suggest_categorical('round_to_ema_interval', param_ranges['ema_signals']['round_to_ema_interval']['values'])
    
    # Ensure slow_ema > fast_ema
    if config['ema_signals']['slow_ema'] <= config['ema_signals']['fast_ema']:
        config['ema_signals']['slow_ema'] = config['ema_signals']['fast_ema'] + 2
    
    # Check if EMA parameters changed (using thread-local cache)
    current_ema_params = (
        config['ema_signals']['time_interval'],
        config['ema_signals']['fast_ema'],
        config['ema_signals']['slow_ema']
    )
    recalculate_ema = (_local.last_ema_params is None or _local.last_ema_params != current_ema_params)
    if recalculate_ema:
        _local.last_ema_params = current_ema_params
    
    # Run backtest with this configuration (pass trial number for unique temp files)
    # Note: opt_params is passed via closure from main()
    metrics = run_backtest_with_config(config, recalculate_ema=recalculate_ema, trial_id=trial.number)
    
    # Focus only on maximizing total P&L (net P&L)
    net_pnl = metrics['net_pnl']
    score = net_pnl
    
    # Store metrics for later analysis (still calculate for reporting, but not used in score)
    max_drawdown = metrics.get('max_drawdown', 0)
    max_drawdown_days = metrics.get('max_drawdown_days', 0)
    
    trial.set_user_attr('net_pnl', net_pnl)
    trial.set_user_attr('max_loss', metrics.get('max_loss', 0))
    trial.set_user_attr('max_drawdown', max_drawdown)
    trial.set_user_attr('max_drawdown_days', max_drawdown_days)
    trial.set_user_attr('total_trades', metrics.get('total_trades', 0))
    trial.set_user_attr('total_pnl', metrics.get('total_pnl', 0))
    trial.set_user_attr('total_charges', metrics.get('total_charges', 0))
    
    return score


def main():
    """Main optimization function"""
    import sys
    
    # Load optimization parameters (allow override via command line)
    params_file = sys.argv[1] if len(sys.argv) > 1 else "optimization_params.json"
    opt_params = load_optimization_params(params_file)
    
    print("=" * 80)
    print("Nifty Options Backtest - Hyperparameter Optimization")
    print("=" * 80)
    print(f"\nUsing optimization parameters from: {params_file}")
    
    # Load config to show backtest period
    base_config = load_base_config("config_optimization.json")
    backtest_period = base_config.get('backtest_period', {})
    start_date = backtest_period.get('start_date', 'N/A')
    end_date = backtest_period.get('end_date', 'N/A')
    
    print(f"\nBacktest Period: {start_date} to {end_date}")
    print("\nOptimizing for:")
    print("  - Maximum profit (net P&L)")
    
    # Display parameter ranges from config
    param_ranges = opt_params['parameter_ranges']
    print("\nParameters being optimized:")
    print(f"  1. entry_time (trading_times.entry_time)")
    print(f"     - entry_hour: {param_ranges['entry_time']['entry_hour']['min']}-{param_ranges['entry_time']['entry_hour']['max']}")
    print(f"     - entry_minute: {param_ranges['entry_time']['entry_minute']['values']}")
    excluded = param_ranges['entry_time']['entry_minute'].get('excluded_for_hour_9', [])
    if excluded:
        print(f"     - Note: For hour 9, minutes {excluded} are excluded")
    
    sl_range = param_ranges['stop_loss_percentage']
    print(f"  2. stop_loss_percentage ({sl_range['min']}-{sl_range['max']}%, step: {sl_range['step']}%)")
    
    target_range = param_ranges['target_percentage']
    print(f"  3. target_percentage ({target_range['min']}-{target_range['max']}%, step: {target_range['step']}%)")
    
    vix_range = param_ranges['vix_threshold']
    print(f"  4. vix_threshold ({vix_range['min']}-{vix_range['max']}, step: {vix_range['step']})")
    
    print(f"  5. use_next_expiry ({param_ranges['use_next_expiry']['values']})")
    print(f"  6. reentry.enabled ({param_ranges['reentry']['enabled']['values']})")
    
    max_reentries_range = param_ranges['reentry']['max_reentries']
    print(f"  7. reentry.max_reentries ({max_reentries_range['min']}-{max_reentries_range['max']}, step: {max_reentries_range['step']})")
    
    cooldown_range = param_ranges['reentry']['stop_loss_cooldown_minutes']
    print(f"  8. reentry.stop_loss_cooldown_minutes ({cooldown_range['min']}-{cooldown_range['max']} minutes, step: {cooldown_range['step']})")
    
    fast_ema_range = param_ranges['ema_signals']['fast_ema']
    print(f"  9. ema_signals.fast_ema ({fast_ema_range['min']}-{fast_ema_range['max']}, step: {fast_ema_range['step']})")
    
    slow_ema_range = param_ranges['ema_signals']['slow_ema']
    print(f"  10. ema_signals.slow_ema ({slow_ema_range['min']}-{slow_ema_range['max']}, step: {slow_ema_range['step']})")
    
    print(f"  11. ema_signals.round_to_ema_interval ({param_ranges['ema_signals']['round_to_ema_interval']['values']})")
    print(f"     Note: ema_signals.time_interval is fixed at {param_ranges['ema_signals']['time_interval']} minutes")
    print("\n" + "=" * 80)
    
    # Get optimization settings
    opt_settings = opt_params['optimization_settings']
    study_name = opt_settings['study_name']
    storage = f"sqlite:///{study_name}.db"
    n_trials = opt_settings['n_trials']
    n_jobs = opt_settings['n_jobs']
    sampler_seed = opt_settings.get('sampler_seed', 42)
    
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction='maximize',
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=sampler_seed)
    )
    
    print(f"\nStarting optimization with {n_trials} trials...")
    if n_jobs == -1:
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()
        print(f"Using {cpu_count} parallel workers (all available CPUs)")
    elif n_jobs > 1:
        print(f"Using {n_jobs} parallel workers")
    else:
        print("Running sequentially (single worker)")
    print("This may take a while. Each trial runs a full backtest.\n")
    
    # Create a wrapper function that includes opt_params
    def objective_with_params(trial):
        return objective(trial, opt_params)
    
    try:
        study.optimize(objective_with_params, n_trials=n_trials, n_jobs=n_jobs, show_progress_bar=True)
    except KeyboardInterrupt:
        print("\n\nOptimization interrupted by user.")
    
    print("\n" + "=" * 80)
    print("Optimization Complete!")
    print("=" * 80)
    
    # Get best trial
    best_trial = study.best_trial
    print(f"\nBest Trial (Trial #{best_trial.number}):")
    print(f"  Score: {best_trial.value:.2f}")
    print(f"  Net P&L: ₹{best_trial.user_attrs['net_pnl']:.2f}")
    print(f"  Max Loss: ₹{best_trial.user_attrs['max_loss']:.2f}")
    print(f"  Max Drawdown: ₹{best_trial.user_attrs['max_drawdown']:.2f}")
    print(f"  Max Drawdown Days: {best_trial.user_attrs['max_drawdown_days']}")
    print(f"  Total Trades: {best_trial.user_attrs['total_trades']}")
    print(f"  Total P&L: ₹{best_trial.user_attrs['total_pnl']:.2f}")
    print(f"  Total Charges: ₹{best_trial.user_attrs['total_charges']:.2f}")
    
    print("\nBest Parameters:")
    for key, value in best_trial.params.items():
        print(f"  {key}: {value}")
    
    # Reconstruct best config from optimization config
    base_config = load_base_config("config_optimization.json")
    best_config = copy.deepcopy(base_config)
    
    # Apply best parameters
    entry_hour = best_trial.params['entry_hour']
    entry_minute = best_trial.params['entry_minute']
    best_config['trading_times']['entry_time'] = format_time(entry_hour, entry_minute)
    
    best_config['options']['stop_loss_percentage'] = best_trial.params['stop_loss_percentage']
    best_config['options']['target_percentage'] = best_trial.params['target_percentage']
    best_config['options']['vix_threshold'] = best_trial.params['vix_threshold']
    best_config['options']['use_next_expiry'] = best_trial.params['use_next_expiry']
    
    best_config['reentry']['enabled'] = best_trial.params['reentry_enabled']
    if best_config['reentry']['enabled']:
        best_config['reentry']['max_reentries'] = best_trial.params['max_reentries']
    else:
        best_config['reentry']['max_reentries'] = 0
    
    best_config['reentry']['stop_loss_cooldown_minutes'] = best_trial.params['stop_loss_cooldown_minutes']
    
    best_config['ema_signals']['time_interval'] = 5  # Fixed at 5 minutes
    best_config['ema_signals']['fast_ema'] = best_trial.params['ema_fast']
    best_config['ema_signals']['slow_ema'] = best_trial.params['ema_slow']
    best_config['ema_signals']['round_to_ema_interval'] = best_trial.params['round_to_ema_interval']
    
    # Save best config
    best_config_path = "config_best_optimized.json"
    save_config(best_config, best_config_path)
    print(f"\nBest configuration saved to: {best_config_path}")
    
    # Optionally update main config (commented out for safety)
    # print("\nUpdating main config.json with best parameters...")
    # save_config(best_config, "config.json")
    # print("Main config.json updated!")
    
    # Print top 5 trials
    print("\n" + "=" * 80)
    print("Top 5 Trials:")
    print("=" * 80)
    # Filter out failed trials (those with None value) and sort by value
    successful_trials = [t for t in study.trials if t.value is not None]
    trials = sorted(successful_trials, key=lambda t: t.value, reverse=True)[:5]
    for i, trial in enumerate(trials, 1):
        print(f"\n{i}. Trial #{trial.number} (Score: {trial.value:.2f})")
        print(f"   Net P&L: ₹{trial.user_attrs['net_pnl']:.2f}")
        print(f"   Max Loss: ₹{trial.user_attrs['max_loss']:.2f}")
        print(f"   Max Drawdown: ₹{trial.user_attrs['max_drawdown']:.2f}")
        print(f"   Max Drawdown Days: {trial.user_attrs['max_drawdown_days']}")
        print(f"   Key Params: entry_time={format_time(trial.params['entry_hour'], trial.params['entry_minute'])}, "
              f"stop_loss={trial.params['stop_loss_percentage']}%, "
              f"vix_threshold={trial.params['vix_threshold']}, "
              f"use_next_expiry={trial.params['use_next_expiry']}, "
              f"reentry_enabled={trial.params['reentry_enabled']}")
    
    print("\n" + "=" * 80)
    print("Optimization Summary:")
    print("=" * 80)
    print(f"Total Trials: {len(study.trials)}")
    print(f"Best Score: {study.best_value:.2f}")
    print(f"Study database: {storage}")
    print("\nTo continue optimization, run this script again (it will resume from the database).")
    print("To apply the best config, copy config_best_optimized.json to config.json")
    print("\nNote: This optimization uses config_optimization.json as the base config.")
    print("      Your main config.json remains unchanged during optimization.")


if __name__ == "__main__":
    main()
