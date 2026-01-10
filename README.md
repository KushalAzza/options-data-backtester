# Nifty Options Backtest System

A backtesting system for Nifty index options with a web-based visualization interface.

## Features

- Backtest ATM CE and PE options strategy
- Configurable entry/exit times and strike selection
- Interactive web dashboard with charts and detailed trade logs
- Dark mode interface with monospace font
- Real-time data visualization

## Setup

### 1. Install Dependencies

```bash
# Install Flask (web framework)
python3 -m pip install --user Flask
# OR if you have permission issues:
python3 -m pip install Flask --break-system-packages
```

### 2. Run Backtest

First, run the backtest to generate results:

```bash
python3 run_backtest.py
```

This will create `backtest_results.json` with the backtest results.

### 3. Start Web Application

Start the web server:

```bash
./start_server.sh
```

Or directly:

```bash
python3 app.py
```

The web app will be available at: **http://localhost:3003**

## Configuration

Edit `config.json` to customize the backtest parameters. Here's a detailed guide:

### Configuration Structure

```json
{
  "backtest_period": {
    "start_date": "2025-06-01",
    "end_date": "2025-12-31"
  },
  "trading_times": {
    "entry_time": "09:20:00",
    "exit_time": "15:20:00"
  },
  "strike_selection": {
    "ce_strike_offset": 0,
    "pe_strike_offset": 0,
    "strike_rounding": 50
  },
  "options": {
    "use_next_expiry": false,
    "lot_size": 50,
    "lot_multiple": 10,
    "per_order_charges": 30
  },
  "output": {
    "results_json": "backtest_results.json"
  },
  "data_paths": {
    "options_data": "data",
    "nifty_intraday": "data/nifty_intraday_price.json"
  }
}
```

### Configuration Options

#### `backtest_period`
- **`start_date`** (string, format: `YYYY-MM-DD`): First date to run backtest
  - Example: `"2025-06-01"`
- **`end_date`** (string, format: `YYYY-MM-DD`): Last date to run backtest
  - Example: `"2025-12-31"`
  - Note: Weekends are automatically skipped

#### `trading_times`
- **`entry_time`** (string, format: `HH:MM:SS`): Time to enter trades (SHORT positions)
  - Example: `"09:20:00"` (9:20 AM IST)
- **`exit_time`** (string, format: `HH:MM:SS`): Time to exit trades (buy back positions)
  - Example: `"15:20:00"` (3:20 PM IST)
  - Note: Times are in IST (Indian Standard Time)

#### `strike_selection`
- **`ce_strike_offset`** (integer): Offset for Call (CE) strike selection
  - `0` = ATM (At-The-Money)
  - `1` = ATM+1 (one strike above ATM)
  - `-1` = ATM-1 (one strike below ATM)
  - Example: With ATM at 24000 and `strike_rounding: 50`, offset `1` = 24050
- **`pe_strike_offset`** (integer): Offset for Put (PE) strike selection
  - Same logic as `ce_strike_offset`
- **`strike_rounding`** (integer): Strike price rounding interval
  - `50` = Strikes rounded to nearest 50 (e.g., 24000, 24050, 24100)
  - `100` = Strikes rounded to nearest 100 (e.g., 24000, 24100, 24200)

#### `options`
- **`use_next_expiry`** (boolean): Use next expiry options data
  - `false` = Use current expiry options
  - `true` = Use next expiry options (if available)
- **`lot_size`** (integer): Number of units per lot
  - `50` = Standard Nifty lot size (50 units)
- **`lot_multiple`** (integer): Number of lots to trade
  - `1` = Trade 1 lot
  - `10` = Trade 10 lots (P&L and charges multiplied by 10)
  - Example: With `lot_multiple: 10`, if 1 lot gives ₹100 P&L, total P&L = ₹1,000
- **`per_order_charges`** (float): Brokerage/charges per order in INR
  - `30` = ₹30 per order
  - Total charges = (4 orders per trade day) × (lot_multiple) × (per_order_charges)
  - Example: 1 trade day with 10 lots = 4 × 10 × 30 = ₹1,200 charges

#### `output`
- **`results_json`** (string): Path to save backtest results JSON file
  - Example: `"backtest_results.json"`

#### `data_paths`
- **`options_data`** (string): Directory path containing options data
  - Structure: `data/YYYY/nifty_options_YYYY-MM-DD.json`
  - Example: `"data"` → looks for `data/2025/nifty_options_2025-06-01.json`
- **`nifty_intraday`** (string): Path to Nifty intraday price JSON file
  - Example: `"data/nifty_intraday_price.json"`

### Example Configurations

**ATM Strategy (Current Default):**
```json
{
  "strike_selection": {
    "ce_strike_offset": 0,
    "pe_strike_offset": 0,
    "strike_rounding": 50
  },
  "options": {
    "lot_multiple": 10
  }
}
```
- Trades ATM CE and PE options
- 10 lots per trade

**ATM+1 Strategy:**
```json
{
  "strike_selection": {
    "ce_strike_offset": 1,
    "pe_strike_offset": 1,
    "strike_rounding": 50
  }
}
```
- Trades one strike above ATM for both CE and PE

**Single Lot Trading:**
```json
{
  "options": {
    "lot_multiple": 1
  }
}
```
- Trade only 1 lot (lower risk, lower returns)

## File Structure

```
backtest-trade/
├── app.py                 # Flask web application
├── run_backtest.py        # Backtest script
├── config.json            # Configuration file
├── start_server.sh        # Server startup script
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Web dashboard template
├── data/
│   ├── nifty_intraday_price.json
│   └── 2025/            # Options data by year
└── backtest_results.json # Generated results
```

## Usage

1. **Configure**: Edit `config.json` with your desired parameters
2. **Backtest**: Run `python3 run_backtest.py` to generate results
3. **View**: Start the web app with `./start_server.sh` and open http://localhost:3003

## Web Dashboard Features

- Summary statistics (Total Trades, P&L, Win/Loss ratio)
- Interactive charts (Daily P&L, Cumulative P&L)
- Detailed trade table with separate rows for CE and PE
- Dark mode interface
- Real-time data from JSON file

## Hyperparameter Optimization

The system includes a hyperparameter optimization script that uses Optuna to find optimal configuration parameters for maximum profit with low max loss and drawdown days.

### Setup

First, install the optimization dependencies:

```bash
pip install optuna
```

Or install all requirements:

```bash
pip install -r requirements.txt
```

### Running Optimization

```bash
python3 optimize_hyperparameters.py
```

### Parameters Being Optimized

The optimization script tests the following parameters:

1. **Entry Time** (`trading_times.entry_time`)
   - Hour: 9-11
   - Minute: 0-59 (step of 5 minutes)

2. **Stop Loss & Targets** (`options`)
   - `stop_loss_percentage`: 10-50% (step of 5%)
   - `target_percentage`: 0-30% (step of 5%)
   - `vix_threshold`: 10-25

3. **Re-entry Settings** (`reentry`)
   - `enabled`: True/False
   - `max_reentries`: 1-10 (if enabled)
   - `stop_loss_cooldown_minutes`: 0-60 minutes (step of 5)

4. **EMA Signals** (`ema_signals`)
   - `time_interval`: 1-15 minutes
   - `fast_ema`: 5-20
   - `slow_ema`: 15-50 (ensured to be > fast_ema)

### Optimization Objective

The optimization maximizes a composite score that considers:
- **Net P&L** (maximize)
- **Max Loss** (minimize - penalty applied)
- **Max Drawdown** (minimize - penalty applied)
- **Max Drawdown Days** (minimize - penalty applied)

Formula: `score = net_pnl - (max_loss × 0.5) - (max_drawdown × 0.3) - (max_drawdown_days × 100)`

### Output

After optimization completes:
- **Best configuration** saved to `config_best_optimized.json`
- **Study database** saved to `nifty_options_optimization.db` (can resume optimization)
- **Top 5 trials** displayed with their metrics

### Applying Best Configuration

To use the optimized configuration:

```bash
# Copy the best config to your main config
cp config_best_optimized.json config.json

# Recalculate EMA values if EMA parameters changed
python3 cal_ema_nifty_data.py

# Run backtest with optimized config
python3 run_backtest.py
```

### Notes

- Optimization runs 100 trials by default (adjustable in the script)
- Each trial runs a full backtest, so optimization can take a while
- The script automatically recalculates EMA values when EMA parameters change
- You can interrupt and resume optimization (it saves progress to a database)
- The script does NOT modify your original `config.json` by default (saves to `config_best_optimized.json`)
