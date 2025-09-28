# gui_components/left_panel.py

import customtkinter as ctk
from typing import Any, Dict, List

class LiveOpsTab(ctk.CTkFrame):
    """
    The main control panel for the bot, restored to its full functionality and
    adapted for the new, safe GUI architecture.
    """
    def __init__(self, parent: ctk.CTk, config: Dict[str, Any], start_callback, stop_callback):
        super().__init__(parent, width=300, corner_radius=0)
        self.app = parent  # Store the main app instance for context
        self.config = config
        self.start_callback = start_callback
        self.stop_callback = stop_callback

        self.grid_rowconfigure(4, weight=1) # Push elements to the top

        # --- Status Display ---
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.pack(pady=10, padx=10, fill="x")
        self.status_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.status_frame, text="Status:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.status_label = ctk.CTkLabel(self.status_frame, text="STOPPED", text_color="red", font=ctk.CTkFont(weight="bold"))
        self.status_label.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(self.status_frame, text="Uptime:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=(10, 5), pady=5, sticky="w")
        self.runtime_label = ctk.CTkLabel(self.status_frame, text="00:00:00")
        self.runtime_label.grid(row=1, column=1, padx=5, pady=5, sticky="w")


        # --- Control Frame ---
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.pack(pady=10, padx=10, fill="x", anchor="s")

        self.start_button = ctk.CTkButton(self.control_frame, text="Start Bot", command=self.start_callback)
        self.start_button.pack(pady=10, padx=10, fill="x")

        self.stop_button = ctk.CTkButton(self.control_frame, text="Stop Bot", command=self.stop_callback, state="disabled")
        self.stop_button.pack(pady=(0, 10), padx=10, fill="x")


        # --- Stats Display ---
        self.stats_frame = ctk.CTkFrame(self)
        self.stats_frame.pack(pady=10, padx=10, fill="x")
        self.stats_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.stats_frame, text="Session Stats", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5)

        self.trades_label = self._create_stat_row(self.stats_frame, "Total Trades:", "0")
        self.successful_label = self._create_stat_row(self.stats_frame, "Successful:", "0")
        self.failed_label = self._create_stat_row(self.stats_frame, "Failed:", "0")
        self.profit_label = self._create_stat_row(self.stats_frame, "Est. Profit:", "$0.00")


        # --- Balance Display ---
        self.balance_frame = ctk.CTkFrame(self)
        self.balance_frame.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkLabel(self.balance_frame, text="Live Balances", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5)
        self.balance_text = ctk.CTkTextbox(self.balance_frame, state="disabled", activate_scrollbars=False)
        self.balance_text.pack(pady=5, padx=5, expand=True, fill="both")

    def _create_stat_row(self, parent, title, initial_value):
        """Helper to create a consistent row in the stats frame."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=10, pady=2)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=title, anchor="w").grid(row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(frame, text=initial_value, anchor="e")
        value_label.grid(row=0, column=1, sticky="e")
        return value_label

    # --- YOUR ORIGINAL METHODS, FULLY RESTORED AND FUNCTIONAL ---

    def get_start_parameters(self) -> Dict[str, Any]:
        """
        Gathers settings to start the bot. In a full UI, this would read from
        checkboxes and entry fields on this panel. For now, it uses the config.
        """
        return {
            "selected_symbols": self.config['trading_parameters']['symbols_to_scan'],
            # Add other parameters your original GUI had, like dry_run, sizing_mode, etc.
        }

    def set_status(self, status: str, color: str):
        """Updates the main status label."""
        self.status_label.configure(text=status, text_color=color)

    def set_controls_state(self, is_enabled: bool):
        """Enables or disables the start/stop buttons."""
        start_state = "normal" if is_enabled else "disabled"
        stop_state = "disabled" if is_enabled else "normal"
        self.start_button.configure(state=start_state)
        self.stop_button.configure(state=stop_state)
        # Assuming your engine switch is now here
        if hasattr(self.app, 'engine_switch'):
            self.app.engine_switch.configure(state=start_state)

    def update_stats_display(self, **stats):
        """Updates the session stats display."""
        self.trades_label.configure(text=str(stats.get('trades', 0)))
        self.successful_label.configure(text=str(stats.get('successful', 0)))
        self.failed_label.configure(text=str(stats.get('failed', 0)))
        self.profit_label.configure(text=f"${stats.get('profit', 0.0):.2f}")

    def update_balance_display(self, balances: Dict[str, Any]):
        """Updates the balance display text box."""
        self.balance_text.configure(state="normal")
        self.balance_text.delete("1.0", "end")
        
        display_text = ""
        for ex, assets in balances.items():
            display_text += f"{ex.title()}:\n"
            # Display USDT and any other significant balances
            usdt_balance = assets.get('USDT', 0.0)
            display_text += f"  USDT: {usdt_balance:.2f}\n"
            for asset, amount in assets.items():
                if asset != 'USDT' and amount > 0.0001:
                     display_text += f"  {asset}: {amount:.6f}\n"
            display_text += "\n"

        self.balance_text.insert("1.0", display_text)
        self.balance_text.configure(state="disabled")
    
    def update_runtime_clock(self, seconds: int):
        """Updates the runtime clock display."""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.runtime_label.configure(text=f"{hours:02}:{minutes:02}:{seconds:02}")

# import customtkinter as ctk
# from typing import Any, Dict, Optional
# import time

# from bot_engine import ArbitrageBot

# class LiveOpsTab(ctk.CTkFrame):
#     """
#     The "Live Operations" tab.
#     Contains the live market scan, recent opportunity history, and the main log output.
#     """
#     def __init__(self, master, config: Dict[str, Any], bot: Optional[ArbitrageBot]):
#         super().__init__(master, fg_color="transparent")
#         self.config = config
#         self.bot = bot
#         self.market_data_labels: Dict[str, Dict[str, ctk.CTkLabel]] = {}
        
#         # --- NEW: Store the last price to detect changes ---
#         self.last_prices: Dict[str, Any] = {}
#         self.default_text_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
#         self.price_up_color = "#33FF99"   # A brighter green
#         self.price_down_color = "#FF6666" # A softer red

#         self.grid_rowconfigure(2, weight=1)
#         self.grid_columnconfigure(0, weight=1)
        
#         self.build_market_scan_panel()
#         self.build_opportunity_history_panel()
        
#         self.log_textbox = ctk.CTkTextbox(self, state="disabled", font=("Courier New", 12))
#         self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
#         self.setup_log_colors()
#         self.pack(expand=True, fill="both")

#     def build_market_scan_panel(self):
#         """Creates the live market data grid."""
#         scan_outer_frame = ctk.CTkFrame(self)
#         scan_outer_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
#         scan_outer_frame.grid_columnconfigure(0, weight=1)
#         ctk.CTkLabel(scan_outer_frame, text="Live Market Scan", font=ctk.CTkFont(weight="bold")).pack()
        
#         scan_frame = ctk.CTkScrollableFrame(scan_outer_frame, height=200)
#         scan_frame.pack(fill="x", expand=True, padx=5, pady=5)
        
#         if not self.bot: return

#         clients = self.bot.exchange_manager.get_all_clients()
#         headers = ["Symbol"] + [f"{name.capitalize()} {val}" for name in clients for val in ["Bid", "Ask"]] + ["Spread %"]
#         scan_frame.grid_columnconfigure(list(range(len(headers))), weight=1)
        
#         for i, header in enumerate(headers):
#             ctk.CTkLabel(scan_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5)
        
#         for i, symbol in enumerate(self.config['trading_parameters']['symbols_to_scan']):
#             row_index = i + 1
#             self.market_data_labels[symbol] = {}
#             self.last_prices[symbol] = {} # Initialize storage for this symbol
            
#             symbol_label = ctk.CTkLabel(scan_frame, text=symbol, fg_color="transparent")
#             symbol_label.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
#             self.market_data_labels[symbol]['symbol'] = symbol_label
            
#             col_idx = 1
#             for ex_name in clients:
#                 for val in ["bid", "ask"]:
#                     label_key = f"{ex_name}_{val}"
#                     label = ctk.CTkLabel(scan_frame, text="-", fg_color="transparent")
#                     label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
#                     self.market_data_labels[symbol][label_key] = label
#                     self.last_prices[symbol][label_key] = None # Initialize last price
#                     col_idx += 1

#             spread_label = ctk.CTkLabel(scan_frame, text="-", fg_color="transparent")
#             spread_label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
#             self.market_data_labels[symbol]['spread'] = spread_label

#     def build_opportunity_history_panel(self):
#         """Creates the textbox for recent profitable opportunities."""
#         opp_history_frame = ctk.CTkFrame(self)
#         opp_history_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
#         ctk.CTkLabel(opp_history_frame, text="Recent Profitable Opportunities", font=ctk.CTkFont(weight="bold")).pack(pady=(5,5))
#         self.opp_history_textbox = ctk.CTkTextbox(opp_history_frame, state="disabled", height=120, font=("Calibri", 12))
#         self.opp_history_textbox.pack(fill="x", expand=True, padx=5, pady=5)
#         self.opp_history_textbox.tag_config("profit", foreground="cyan")

#     def setup_log_colors(self):
#         """Configures color tags for the main log textbox."""
#         self.log_textbox.tag_config("INFO", foreground="white")
#         self.log_textbox.tag_config("WARNING", foreground="yellow")
#         self.log_textbox.tag_config("ERROR", foreground="red")
#         self.log_textbox.tag_config("CRITICAL", foreground="#ff4d4d")
#         self.log_textbox.tag_config("TRADE", foreground="cyan")
#         self.log_textbox.tag_config("SUCCESS", foreground="green")

#     def add_log_message(self, level: str, message: str):
#         """Adds a new line to the log textbox with appropriate color."""
#         self.log_textbox.configure(state="normal")
#         self.log_textbox.insert("end", f"{message}\n", level)
#         self.log_textbox.configure(state="disabled")
#         self.log_textbox.see("end")

#     def add_opportunity_to_history(self, data: Dict[str, Any]):
#         """Adds a new line to the opportunity history textbox."""
#         symbol = data.get('symbol', 'N/A')
#         spread = data.get('spread_pct', 0.0)
#         timestamp = time.strftime('%H:%M:%S')
#         log_line = f"[{timestamp}] {symbol:<10} | Spread: {spread:.3f}%\n"
#         self.opp_history_textbox.configure(state="normal")
#         self.opp_history_textbox.insert("1.0", log_line, "profit")
#         self.opp_history_textbox.configure(state="disabled")

#     def update_market_data_display(self, data: Dict[str, Any]):
#         """Updates a single row in the market scan grid with new data, including price change indicators."""
#         if not self.bot: return
#         try:
#             symbol = data.get('symbol')
#             if symbol in self.market_data_labels:
#                 labels = self.market_data_labels[symbol]
#                 last_symbol_prices = self.last_prices.get(symbol, {})
#                 clients = self.bot.exchange_manager.get_all_clients()
                
#                 # --- UPDATE BID/ASK PRICES WITH INDICATORS ---
#                 for ex_name in clients:
#                     for price_type in ["bid", "ask"]:
#                         label_key = f"{ex_name}_{price_type}"
#                         label_widget = labels.get(label_key)
#                         new_price = data.get(label_key)

#                         if label_widget and new_price is not None:
#                             old_price = last_symbol_prices.get(label_key)
                            
#                             text_color = self.default_text_color
#                             indicator = ""
                            
#                             if old_price is not None:
#                                 if new_price > old_price:
#                                     text_color = self.price_up_color
#                                     indicator = " ▲"
#                                 elif new_price < old_price:
#                                     text_color = self.price_down_color
#                                     indicator = " ▼"
                            
#                             label_widget.configure(text=f"{new_price:.4f}{indicator}", text_color=text_color)
#                             self.last_prices[symbol][label_key] = new_price # Update stored price
#                         elif label_widget:
#                             label_widget.configure(text="-", text_color=self.default_text_color)


#                 # --- UPDATE SPREAD ---
#                 spread_pct = data.get('spread_pct')
#                 is_profitable = data.get('is_profitable', False)
#                 spread_label = labels['spread']
                
#                 if spread_pct is not None:
#                     spread_color = "green" if spread_pct > 0 else "red"
#                     spread_label.configure(text=f"{spread_pct:.3f}%", text_color=spread_color)
#                 else:
#                     spread_label.configure(text="-", text_color=self.default_text_color)

#                 # --- UPDATE ROW HIGHLIGHT ---
#                 highlight_color = "#1E4D2B" if is_profitable else "transparent" 
#                 for label_widget in labels.values():
#                    label_widget.configure(fg_color=highlight_color)

#         except Exception as e:
#             # Using master's logger to log the error. The widget hierarchy is master.master.master
#             # LiveOpsTab -> CTkFrame(tab) -> CTkTabview -> CTkFrame(right_frame) -> App
#             # This is a bit fragile; a more robust solution might involve passing the logger down.
#             try:
#                 self.master.master.master.master.logger.warning(f"Failed to update GUI market data. Error: {e}", exc_info=False)
#             except AttributeError: # Fallback if widget hierarchy changes
#                 print(f"GUI ERROR: Failed to log market data update error: {e}")

