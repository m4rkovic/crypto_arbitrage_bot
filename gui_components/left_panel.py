#lef_panel.py 

import customtkinter as ctk
from typing import Any, Dict, Callable


class LeftPanel(ctk.CTkFrame):
    """
    The entire left-side panel of the GUI.
    Handles all user controls: start/stop, sizing, symbol selection,
    and displays for session stats and wallet balances.
    """

    def __init__(self, master, config: Dict[str, Any], start_callback: Callable, stop_callback: Callable):
        super().__init__(master, width=350, corner_radius=0)
        self.config = config
        self.start_callback = start_callback
        self.stop_callback = stop_callback

        self.grid_propagate(False)
        self.grid_rowconfigure(4, weight=1)

        self.symbol_checkboxes: Dict[str, ctk.CTkCheckBox] = {}
        self.create_widgets()

        self.pack(expand=True, fill="both")

    # ----------------------------------------------------------------------
    # UI CREATION
    # ----------------------------------------------------------------------
    def create_widgets(self):
        """Builds all widgets within the left panel."""
        ctk.CTkLabel(
            self, text="Arbitrage Bot", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Control Frame ---
        control_frame = ctk.CTkFrame(self)
        control_frame.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.start_button = ctk.CTkButton(control_frame, text="Start Bot", command=self.start_callback)
        self.start_button.pack(side="left", expand=True, padx=5, pady=5)
        self.stop_button = ctk.CTkButton(control_frame, text="Stop Bot", command=self.stop_callback, state="disabled")
        self.stop_button.pack(side="left", expand=True, padx=5, pady=5)

        # --- Sizing Frame ---
        sizing_frame = ctk.CTkFrame(self)
        sizing_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        sizing_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sizing_frame, text="Sizing Mode", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=2, pady=(5, 0))
        self.sizing_mode_var = ctk.StringVar(
            value=self.config["trading_parameters"].get("sizing_mode", "fixed")
        )

        self.fixed_radio = ctk.CTkRadioButton(
            sizing_frame,
            text="Fixed",
            variable=self.sizing_mode_var,
            value="fixed",
            command=self._toggle_sizing_frames,
        )
        self.fixed_radio.grid(row=1, column=0, padx=(10, 5), pady=5, sticky="w")
        self.dynamic_radio = ctk.CTkRadioButton(
            sizing_frame,
            text="Dynamic",
            variable=self.sizing_mode_var,
            value="dynamic",
            command=self._toggle_sizing_frames,
        )
        self.dynamic_radio.grid(row=1, column=1, padx=(5, 10), pady=5, sticky="w")

        # Fixed Sizing
        self.fixed_sizing_frame = ctk.CTkFrame(sizing_frame)
        self.fixed_sizing_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.fixed_sizing_frame, text="Size (USDT):").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        self.trade_size_entry = ctk.CTkEntry(self.fixed_sizing_frame)
        self.trade_size_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.trade_size_entry.insert(
            0, str(self.config["trading_parameters"].get("trade_size_usdt", 20.0))
        )

        # Dynamic Sizing
        self.dynamic_sizing_frame = ctk.CTkFrame(sizing_frame)
        self.dynamic_sizing_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.dynamic_sizing_frame, text="Balance (%):").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        self.dynamic_pct_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
        self.dynamic_pct_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.dynamic_pct_entry.insert(
            0, str(self.config["trading_parameters"].get("dynamic_size_percentage", 5.0))
        )

        ctk.CTkLabel(self.dynamic_sizing_frame, text="Max Size (USDT):").grid(
            row=1, column=0, padx=10, pady=5, sticky="w"
        )
        self.dynamic_max_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
        self.dynamic_max_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.dynamic_max_entry.insert(
            0, str(self.config["trading_parameters"].get("dynamic_size_max_usdt", 100.0))
        )

        self.dry_run_checkbox = ctk.CTkCheckBox(sizing_frame, text="Dry Run (Simulation Mode)")
        self.dry_run_checkbox.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="w")
        if self.config["trading_parameters"].get("dry_run", True):
            self.dry_run_checkbox.select()

        self._toggle_sizing_frames()

        # --- Symbol Selection Frame ---
        symbol_frame = ctk.CTkFrame(self)
        symbol_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        ctk.CTkLabel(symbol_frame, text="Symbol Selection", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        symbol_scroll_frame = ctk.CTkScrollableFrame(symbol_frame, height=150)
        symbol_scroll_frame.pack(fill="x", expand=True, padx=5, pady=5)
        for symbol in self.config["trading_parameters"]["symbols_to_scan"]:
            checkbox = ctk.CTkCheckBox(symbol_scroll_frame, text=symbol)
            checkbox.pack(anchor="w", padx=10, pady=2)
            checkbox.select()
            self.symbol_checkboxes[symbol] = checkbox

        # --- Tabs (Stats + Wallet) ---
        left_tab_view = ctk.CTkTabview(self)
        left_tab_view.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
        left_tab_view.add("Session Stats")
        left_tab_view.add("Wallet Balances")

        # Stats Tab
        stats_tab = left_tab_view.tab("Session Stats")
        self.stats_frame = ctk.CTkFrame(stats_tab, fg_color="transparent")
        self.stats_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.stats_frame.grid_columnconfigure(1, weight=1)
        self._create_stats_labels()

        # Balances Tab
        balances_tab = left_tab_view.tab("Wallet Balances")
        balances_tab.grid_columnconfigure(0, weight=1)
        balances_tab.grid_rowconfigure(0, weight=1)
        self.balance_frame = ctk.CTkScrollableFrame(balances_tab, label_text="")
        self.balance_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

    # ----------------------------------------------------------------------
    # STATS
    # ----------------------------------------------------------------------
    def _create_stats_labels(self):
        """Creates labels used by update_stats_display."""
        self.status_label = ctk.CTkLabel(
            self.stats_frame,
            text="Status: STOPPED",
            text_color="red",
            font=ctk.CTkFont(weight="bold"),
        )
        self.status_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(5, 10))

        # Actual stats (match engine keys)
        label_style = dict(padx=10, pady=5, sticky="w")
        value_style = dict(padx=10, pady=5, sticky="e")

        ctk.CTkLabel(self.stats_frame, text="Session Profit (USDT):").grid(row=1, column=0, **label_style)
        self.session_profit_label = ctk.CTkLabel(self.stats_frame, text="0.00")
        self.session_profit_label.grid(row=1, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Trades:").grid(row=2, column=0, **label_style)
        self.trade_count_label = ctk.CTkLabel(self.stats_frame, text="0")
        self.trade_count_label.grid(row=2, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Win Rate:").grid(row=3, column=0, **label_style)
        self.win_rate_label = ctk.CTkLabel(self.stats_frame, text="–")
        self.win_rate_label.grid(row=3, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Avg Profit/Trade:").grid(row=4, column=0, **label_style)
        self.avg_profit_label = ctk.CTkLabel(self.stats_frame, text="0.00")
        self.avg_profit_label.grid(row=4, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Failed Trades:").grid(row=5, column=0, **label_style)
        self.failed_trades_label = ctk.CTkLabel(self.stats_frame, text="0")
        self.failed_trades_label.grid(row=5, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Neutralized Trades:").grid(row=6, column=0, **label_style)
        self.neutral_trades_label = ctk.CTkLabel(self.stats_frame, text="0")
        self.neutral_trades_label.grid(row=6, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Critical Failures:", text_color="gray").grid(
            row=7, column=0, **label_style
        )
        self.critical_failures_label = ctk.CTkLabel(
            self.stats_frame, text="0", text_color="red"
        )
        self.critical_failures_label.grid(row=7, column=1, **value_style)

        ctk.CTkLabel(self.stats_frame, text="Runtime:").grid(row=8, column=0, **label_style)
        self.runtime_label = ctk.CTkLabel(self.stats_frame, text="00:00:00")
        self.runtime_label.grid(row=8, column=1, **value_style)

    # ----------------------------------------------------------------------
    # CONTROL & UPDATE METHODS
    # ----------------------------------------------------------------------
    def _toggle_sizing_frames(self):
        """Shows/hides sizing mode sections."""
        mode = self.sizing_mode_var.get()
        if mode == "fixed":
            self.fixed_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
            self.dynamic_sizing_frame.grid_remove()
        else:
            self.fixed_sizing_frame.grid_remove()
            self.dynamic_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    def get_start_parameters(self) -> Dict[str, Any]:
        """Collects all parameters from user inputs before bot start."""
        sizing_mode = self.sizing_mode_var.get()
        params = {"sizing_mode": sizing_mode}

        if sizing_mode == "fixed":
            trade_size = float(self.trade_size_entry.get())
            if trade_size <= 0:
                raise ValueError("Fixed trade size must be positive.")
            params["trade_size_usdt"] = trade_size
        else:
            pct = float(self.dynamic_pct_entry.get())
            max_size = float(self.dynamic_max_entry.get())
            if not (0 < pct <= 100):
                raise ValueError("Percentage must be between 0 and 100.")
            if max_size <= 0:
                raise ValueError("Max size must be positive.")
            params["dynamic_size_percentage"] = pct
            params["dynamic_size_max_usdt"] = max_size

        params["dry_run"] = self.dry_run_checkbox.get() == 1
        selected_symbols = [s for s, c in self.symbol_checkboxes.items() if c.get() == 1]
        if not selected_symbols:
            raise ValueError("Please select at least one symbol to trade.")
        params["selected_symbols"] = selected_symbols
        return params

    def set_controls_state(self, is_enabled: bool):
        """Enable or disable all input controls."""
        state = "normal" if is_enabled else "disabled"
        self.start_button.configure(state="normal" if is_enabled else "disabled")
        self.stop_button.configure(state="disabled" if is_enabled else "normal")
        for radio in [self.fixed_radio, self.dynamic_radio]:
            radio.configure(state=state)
        self.trade_size_entry.configure(state=state)
        self.dynamic_pct_entry.configure(state=state)
        self.dynamic_max_entry.configure(state=state)
        self.dry_run_checkbox.configure(state=state)
        for checkbox in self.symbol_checkboxes.values():
            checkbox.configure(state=state)

        if is_enabled:
            self.set_status("STOPPED", "red")

    def set_status(self, text: str, color: str):
        """Set the engine status label color and text."""
        self.status_label.configure(text=f"Status: {text}", text_color=color)
        self.status_label.configure(font=ctk.CTkFont(weight="bold" if text == "RUNNING" else "normal"))

    def update_stats_display(
        self,
        session_profit: float = 0.0,
        trade_count: int = 0,
        win_rate: float | None = None,
        avg_profit: float = 0.0,
        failed_trades: int = 0,
        neutralized_trades: int = 0,
        critical_failures: int = 0,
    ):
        """Updates the statistics labels on the panel."""
        try:
            self.session_profit_label.configure(text=f"{session_profit:.2f}")
            self.trade_count_label.configure(text=str(trade_count))
            self.win_rate_label.configure(
                text=f"{win_rate:.1f} %" if win_rate is not None else "–"
            )
            self.avg_profit_label.configure(text=f"{avg_profit:.2f}")
            self.failed_trades_label.configure(text=str(failed_trades))
            self.neutral_trades_label.configure(text=str(neutralized_trades))
            self.critical_failures_label.configure(text=str(critical_failures))
        except Exception as e:
            print(f"[WARN] Stats update failed: {e}")

    def update_balance_display(self, balance_data: Dict[str, Any]):
        """Refresh wallet balances in grid format."""
        for widget in self.balance_frame.winfo_children():
            widget.destroy()

        all_assets = set()
        exchange_names = sorted(balance_data.keys())
        for ex_name in exchange_names:
            all_assets.update(balance_data[ex_name].keys())
        sorted_assets = sorted(list(all_assets))

        num_cols = len(exchange_names) + 1
        for i in range(num_cols):
            self.balance_frame.grid_columnconfigure(i, weight=1)

        ctk.CTkLabel(self.balance_frame, text="").grid(row=0, column=0)
        for col_idx, ex_name in enumerate(exchange_names, 1):
            header = ctk.CTkLabel(
                self.balance_frame,
                text=ex_name.capitalize(),
                font=ctk.CTkFont(weight="bold"),
            )
            header.grid(row=0, column=col_idx, padx=5, pady=2, sticky="ew")

        for row_idx, asset in enumerate(sorted_assets, 1):
            asset_label = ctk.CTkLabel(
                self.balance_frame,
                text=asset,
                font=ctk.CTkFont(weight="bold"),
                anchor="w",
            )
            asset_label.grid(row=row_idx, column=0, padx=5, pady=2, sticky="w")
            for col_idx, ex_name in enumerate(exchange_names, 1):
                balance = balance_data.get(ex_name, {}).get(asset, 0.0)
                val = balance if isinstance(balance, (int, float)) else 0.0
                ctk.CTkLabel(
                    self.balance_frame,
                    text=f"{val:.4f}",
                    font=ctk.CTkFont(size=11),
                    anchor="e",
                ).grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="ew")

    def update_runtime_clock(self, uptime_seconds: int):
        """Updates runtime timer display."""
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.runtime_label.configure(text=f"{hours:02}:{minutes:02}:{seconds:02}")
