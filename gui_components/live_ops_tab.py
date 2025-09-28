#live_ops_tab.py

import customtkinter as ctk
from typing import Any, Dict, Optional
import time

from bot_engine import ArbitrageBot

class LiveOpsTab(ctk.CTkFrame):
    """
    The "Live Operations" tab.
    Contains the live market scan, recent opportunity history, and the main log output.
    """
    def __init__(self, master, config: Dict[str, Any], app: Optional[ArbitrageBot]):
        super().__init__(master, fg_color="transparent")
        self.config = config
        self.app = app
        self.market_data_labels: Dict[str, Dict[str, ctk.CTkLabel]] = {}
        
        # --- NEW: Store the last price to detect changes ---
        self.last_prices: Dict[str, Any] = {}
        self.default_text_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        self.price_up_color = "#33FF99"   # A brighter green
        self.price_down_color = "#FF6666" # A softer red

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.build_market_scan_panel()
        self.build_opportunity_history_panel()
        
        self.log_textbox = ctk.CTkTextbox(self, state="disabled", font=("Courier New", 12))
        self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.setup_log_colors()
        self.pack(expand=True, fill="both")

    def build_market_scan_panel(self):
        """Creates the live market data grid."""
        scan_outer_frame = ctk.CTkFrame(self)
        scan_outer_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        scan_outer_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(scan_outer_frame, text="Live Market Scan", font=ctk.CTkFont(weight="bold")).pack()
        
        scan_frame = ctk.CTkScrollableFrame(scan_outer_frame, height=200)
        scan_frame.pack(fill="x", expand=True, padx=5, pady=5)
        
        if not self.bot: return

        clients = self.bot.exchange_manager.get_all_clients()
        headers = ["Symbol"] + [f"{name.capitalize()} {val}" for name in clients for val in ["Bid", "Ask"]] + ["Spread %"]
        scan_frame.grid_columnconfigure(list(range(len(headers))), weight=1)
        
        for i, header in enumerate(headers):
            ctk.CTkLabel(scan_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5)
        
        for i, symbol in enumerate(self.config['trading_parameters']['symbols_to_scan']):
            row_index = i + 1
            self.market_data_labels[symbol] = {}
            self.last_prices[symbol] = {} # Initialize storage for this symbol
            
            symbol_label = ctk.CTkLabel(scan_frame, text=symbol, fg_color="transparent")
            symbol_label.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
            self.market_data_labels[symbol]['symbol'] = symbol_label
            
            col_idx = 1
            for ex_name in clients:
                for val in ["bid", "ask"]:
                    label_key = f"{ex_name}_{val}"
                    label = ctk.CTkLabel(scan_frame, text="-", fg_color="transparent")
                    label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
                    self.market_data_labels[symbol][label_key] = label
                    self.last_prices[symbol][label_key] = None # Initialize last price
                    col_idx += 1

            spread_label = ctk.CTkLabel(scan_frame, text="-", fg_color="transparent")
            spread_label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
            self.market_data_labels[symbol]['spread'] = spread_label

    def build_opportunity_history_panel(self):
        """Creates the textbox for recent profitable opportunities."""
        opp_history_frame = ctk.CTkFrame(self)
        opp_history_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(opp_history_frame, text="Recent Profitable Opportunities", font=ctk.CTkFont(weight="bold")).pack(pady=(5,5))
        self.opp_history_textbox = ctk.CTkTextbox(opp_history_frame, state="disabled", height=120, font=("Calibri", 12))
        self.opp_history_textbox.pack(fill="x", expand=True, padx=5, pady=5)
        self.opp_history_textbox.tag_config("profit", foreground="cyan")

    def setup_log_colors(self):
        """Configures color tags for the main log textbox."""
        self.log_textbox.tag_config("INFO", foreground="white")
        self.log_textbox.tag_config("WARNING", foreground="yellow")
        self.log_textbox.tag_config("ERROR", foreground="red")
        self.log_textbox.tag_config("CRITICAL", foreground="#ff4d4d")
        self.log_textbox.tag_config("TRADE", foreground="cyan")
        self.log_textbox.tag_config("SUCCESS", foreground="green")

    def add_log_message(self, level: str, message: str):
        """Adds a new line to the log textbox with appropriate color."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", f"{message}\n", level)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")

    def add_opportunity_to_history(self, data: Dict[str, Any]):
        """Adds a new line to the opportunity history textbox."""
        symbol = data.get('symbol', 'N/A')
        spread = data.get('spread_pct', 0.0)
        timestamp = time.strftime('%H:%M:%S')
        log_line = f"[{timestamp}] {symbol:<10} | Spread: {spread:.3f}%\n"
        self.opp_history_textbox.configure(state="normal")
        self.opp_history_textbox.insert("1.0", log_line, "profit")
        self.opp_history_textbox.configure(state="disabled")

    def update_market_data_display(self, data: Dict[str, Any]):
        """Updates a single row in the market scan grid with new data, including price change indicators."""
        if not self.bot: return
        try:
            symbol = data.get('symbol')
            if symbol in self.market_data_labels:
                labels = self.market_data_labels[symbol]
                last_symbol_prices = self.last_prices.get(symbol, {})
                clients = self.bot.exchange_manager.get_all_clients()
                
                # --- UPDATE BID/ASK PRICES WITH INDICATORS ---
                for ex_name in clients:
                    for price_type in ["bid", "ask"]:
                        label_key = f"{ex_name}_{price_type}"
                        label_widget = labels.get(label_key)
                        new_price = data.get(label_key)

                        if label_widget and new_price is not None:
                            old_price = last_symbol_prices.get(label_key)
                            
                            text_color = self.default_text_color
                            indicator = ""
                            
                            if old_price is not None:
                                if new_price > old_price:
                                    text_color = self.price_up_color
                                    indicator = " ▲"
                                elif new_price < old_price:
                                    text_color = self.price_down_color
                                    indicator = " ▼"
                            
                            label_widget.configure(text=f"{new_price:.4f}{indicator}", text_color=text_color)
                            self.last_prices[symbol][label_key] = new_price # Update stored price
                        elif label_widget:
                            label_widget.configure(text="-", text_color=self.default_text_color)


                # --- UPDATE SPREAD ---
                spread_pct = data.get('spread_pct')
                is_profitable = data.get('is_profitable', False)
                spread_label = labels['spread']
                
                if spread_pct is not None:
                    spread_color = "green" if spread_pct > 0 else "red"
                    spread_label.configure(text=f"{spread_pct:.3f}%", text_color=spread_color)
                else:
                    spread_label.configure(text="-", text_color=self.default_text_color)

                # --- UPDATE ROW HIGHLIGHT ---
                highlight_color = "#1E4D2B" if is_profitable else "transparent" 
                for label_widget in labels.values():
                   label_widget.configure(fg_color=highlight_color)

        except Exception as e:
            # Using master's logger to log the error. The widget hierarchy is master.master.master
            # LiveOpsTab -> CTkFrame(tab) -> CTkTabview -> CTkFrame(right_frame) -> App
            # This is a bit fragile; a more robust solution might involve passing the logger down.
            try:
                self.master.master.master.master.logger.warning(f"Failed to update GUI market data. Error: {e}", exc_info=False)
            except AttributeError: # Fallback if widget hierarchy changes
                print(f"GUI ERROR: Failed to log market data update error: {e}")

