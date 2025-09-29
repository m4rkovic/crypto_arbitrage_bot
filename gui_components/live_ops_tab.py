# live_ops_tab.py

import customtkinter as ctk
from tkinter import ttk  # <-- ADDED for Treeview
from typing import Any, Dict, Optional
import time

class LiveOpsTab(ctk.CTkFrame):
    """
    The "Live Operations" tab.
    Contains the live market scan, recent opportunity history, and the main log output.
    """
    def __init__(self, master, **kwargs):
            super().__init__(master, **kwargs)

            self.configure(corner_radius=0, fg_color="transparent")
            self.grid_columnconfigure(0, weight=1)
            self.grid_rowconfigure(0, weight=1)

            # === Treeview for Market Data ===
            style = ttk.Style()
            style.theme_use("default")
            
            # Configure Treeview colors for dark mode
            style.configure("Treeview",
                            background="#2a2d2e",
                            foreground="white",
                            rowheight=25,
                            fieldbackground="#343638",
                            bordercolor="#343638",
                            borderwidth=0)
            style.map('Treeview', background=[('selected', '#22559b')])
            style.configure("Treeview.Heading",
                            background="#565b5e",
                            foreground="white",
                            relief="flat")
            style.map("Treeview.Heading",
                    background=[('active', '#3484F0')])

            columns = ("symbol", "exchange1", "price1", "exchange2", "price2", "spread")
            self.market_table = ttk.Treeview(self, columns=columns, show="headings")
            
            # Define headings
            self.market_table.heading("symbol", text="Symbol")
            self.market_table.heading("exchange1", text="Buy Exchange")
            self.market_table.heading("price1", text="Buy Price")
            self.market_table.heading("exchange2", text="Sell Exchange")
            self.market_table.heading("price2", text="Sell Price")
            self.market_table.heading("spread", text="Spread (%)")

            # Configure column widths
            for col in columns:
                self.market_table.column(col, anchor="center", width=120)

            self.market_table.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
            
            # Configure tags for coloring rows
            self.market_table.tag_configure('positive_spread', background='#1f4021')
            self.market_table.tag_configure('negative_spread', background='#402121')
            
    def build_market_scan_panel(self):
        """Creates the live market data panel using a ttk.Treeview."""
        market_data_frame = ctk.CTkFrame(self)
        market_data_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        market_data_frame.grid_columnconfigure(0, weight=1)
        market_data_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(market_data_frame, text="Live Market Data", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, pady=5)
        
        # --- Treeview Setup ---
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0, rowheight=25)
        style.map('Treeview', background=[('selected', '#1f6aa5')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", font=('Arial', 10, 'bold'), padding=5)

        self.market_data_table = ttk.Treeview(
            market_data_frame,
            columns=("Symbol", "Bid", "Ask", "Spread"),
            show="headings"
        )
        
        self.market_data_table.heading("Symbol", text="Symbol")
        self.market_data_table.heading("Bid", text="Best Bid")
        self.market_data_table.heading("Ask", text="Best Ask")
        self.market_data_table.heading("Spread", text="Spread (%)")

        self.market_data_table.column("Symbol", width=120, anchor="w")
        self.market_data_table.column("Bid", width=120, anchor="e")
        self.market_data_table.column("Ask", width=120, anchor="e")
        self.market_data_table.column("Spread", width=100, anchor="e")

        self.market_data_table.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        
        # Configure tags for highlighting
        self.market_data_table.tag_configure('profitable', background='#1E4D2B')
        self.market_data_table.tag_configure('normal', background='#2b2b2b')

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
        """Updates the Treeview with a new snapshot of all market data."""
        # Clear existing data from the table
        for i in self.market_data_table.get_children():
            self.market_data_table.delete(i)
            
        # Insert new data, sorted by symbol
        for symbol, prices in sorted(data.items()):
            best_bid = prices.get('best_bid', 0.0)
            best_ask = prices.get('best_ask', 0.0)
            is_profitable = prices.get('is_profitable', False)
            
            if best_bid and best_ask and best_ask > 0:
                spread = ((best_ask - best_bid) / best_ask) * 100
                spread_str = f"{spread:.4f}%"
            else:
                spread_str = "N/A"

            row_tag = 'profitable' if is_profitable else 'normal'

            self.market_data_table.insert(
                "", 
                "end", 
                values=(symbol, f"{best_bid:.8f}", f"{best_ask:.8f}", spread_str),
                tags=(row_tag,)
            )