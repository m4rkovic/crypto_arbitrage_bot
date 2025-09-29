# analysis_tab.py

import customtkinter as ctk
import pandas as pd
from typing import Any, Dict, Optional

# --- ADDED: Matplotlib imports ---
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
plt.style.use('dark_background') # Set a theme that matches our GUI

from performance_analyzer import PerformanceAnalyzer

class AnalysisTab(ctk.CTkFrame):
    """
    The "Performance Analysis" tab.
    Handles loading trade data and displaying all KPIs, portfolio performance,
    charts, and the detailed trade log.
    """
    def __init__(self, master, app_instance):
        super().__init__(master, fg_color="transparent")
        self.app = app_instance # Reference to the main App instance
        self.kpi_labels: Dict[str, ctk.CTkLabel] = {}
        self.portfolio_labels: Dict[str, ctk.CTkLabel] = {}
        self.analysis_canvas_widgets: Dict[str, Any] = {}
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        self.create_widgets()
        
        self.pack(expand=True, fill="both")

    def create_widgets(self):
        """Builds all widgets for the analysis tab."""
        # --- Top Control Frame ---
        control_frame = ctk.CTkFrame(self)
        control_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        refresh_button = ctk.CTkButton(control_frame, text="Load/Refresh Trade Data", command=self._on_refresh_analysis_data)
        refresh_button.pack(side="left", padx=10, pady=5)
        self.analysis_status_label = ctk.CTkLabel(control_frame, text="Waiting for session data...", text_color="gray")
        self.analysis_status_label.pack(side="left", padx=10, pady=5)

        # --- Left Panel (KPIs & Portfolio) ---
        left_panel = ctk.CTkScrollableFrame(self)
        left_panel.grid(row=1, column=0, sticky="ns", padx=10, pady=10)
        left_panel.grid_columnconfigure(0, weight=1) # Allow frames inside to fill

        self._create_kpi_frame(left_panel)
        self._create_portfolio_frame(left_panel)
        
        # --- Right Panel (Charts & Trade Log) ---
        right_panel_content_frame = ctk.CTkFrame(self)
        right_panel_content_frame.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        right_panel_content_frame.grid_rowconfigure(0, weight=1) # Tab view will expand
        right_panel_content_frame.grid_rowconfigure(1, weight=1) # Pie chart will expand
        right_panel_content_frame.grid_columnconfigure(0, weight=1)

        # Frame for the Pie Chart
        pie_chart_frame = ctk.CTkFrame(right_panel_content_frame)
        pie_chart_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 10))
        self._create_pie_chart_widget(pie_chart_frame)
        
        # Tab View for other charts and logs
        chart_tab_view = ctk.CTkTabview(right_panel_content_frame)
        chart_tab_view.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        chart_tab_view.add("P/L Curve")
        chart_tab_view.add("Profit By Symbol")
        chart_tab_view.add("Trade Log")
        
        self.chart_frames = {
            "P/L Curve": chart_tab_view.tab("P/L Curve"),
            "Profit By Symbol": chart_tab_view.tab("Profit By Symbol"),
        }
        self.trade_log_frame = ctk.CTkScrollableFrame(chart_tab_view.tab("Trade Log"))
        self.trade_log_frame.pack(fill="both", expand=True)

    def _create_pie_chart_widget(self, parent):
        """Creates the Matplotlib widget for the portfolio pie chart."""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # --- Matplotlib Pie Chart Setup ---
        self.portfolio_fig, self.portfolio_ax = plt.subplots(figsize=(5, 4), dpi=100)
        self.portfolio_fig.patch.set_facecolor('#2b2b2b') # Match frame background
        self.portfolio_ax.set_facecolor('#2b2b2b')

        self.portfolio_canvas = FigureCanvasTkAgg(self.portfolio_fig, master=parent)
        self.portfolio_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.portfolio_ax.set_title("Portfolio Allocation (USD Value)", color="white")
        self.portfolio_ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
        self.portfolio_canvas.draw()
        
    def _create_kpi_frame(self, parent):
        kpi_frame = ctk.CTkFrame(parent)
        kpi_frame.pack(fill="x", expand=True, padx=5, pady=5)
        # ... (rest of kpi_frame code is unchanged)
        ctk.CTkLabel(kpi_frame, text="Trade Performance KPIs", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        kpi_list = ["Total Trades", "Successful Trades", "Win Rate (%)", "Net P/L ($)", "Profit Factor", "Max Drawdown ($)", "Sharpe Ratio"]
        for kpi_name in kpi_list:
            frame = ctk.CTkFrame(kpi_frame, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(frame, text=f"{kpi_name}:", anchor="w").pack(side="left")
            value_label = ctk.CTkLabel(frame, text="N/A", anchor="e")
            value_label.pack(side="right")
            self.kpi_labels[kpi_name] = value_label

    def _create_portfolio_frame(self, parent):
        portfolio_frame = ctk.CTkFrame(parent)
        portfolio_frame.pack(fill="x", expand=True, padx=5, pady=15)
        # ... (rest of portfolio_frame code is unchanged)
        ctk.CTkLabel(portfolio_frame, text="Portfolio Performance", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        portfolio_list = {"Starting Value ($)": "N/A", "Current Value ($)": "N/A", "Portfolio P/L ($)": "N/A", "Portfolio Growth (%)": "N/A"}
        for name, default_val in portfolio_list.items():
            frame = ctk.CTkFrame(portfolio_frame, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(frame, text=f"{name}:", anchor="w").pack(side="left")
            value_label = ctk.CTkLabel(frame, text=default_val, anchor="e")
            value_label.pack(side="right")
            self.portfolio_labels[name] = value_label
        
        self.portfolio_asset_breakdown_frame = ctk.CTkFrame(portfolio_frame)
        self.portfolio_asset_breakdown_frame.pack(fill="x", expand=True, padx=10, pady=10)
        ctk.CTkLabel(self.portfolio_asset_breakdown_frame, text="Asset Breakdown:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        
    def _on_refresh_analysis_data(self):
        # ... (this method is unchanged)
        self.analysis_status_label.configure(text="Loading and analyzing trade data...")
        analyzer = PerformanceAnalyzer()
        if not analyzer.load_data():
            self.analysis_status_label.configure(text="Could not load trades.csv. Run bot to generate data.", text_color="orange")
            return
        kpis = analyzer.calculate_kpis()
        for name, label in self.kpi_labels.items():
            value = kpis.get(name, "N/A")
            label.configure(text=str(value))
            if name == "Net P/L ($)":
                try:
                    profit_val = float(str(value).replace("$","").replace(",",""))
                    label.configure(text_color="green" if profit_val >= 0 else "red")
                except (ValueError, TypeError):
                    label.configure(text_color="gray")
        self._embed_chart(analyzer.generate_equity_curve(), "P/L Curve")
        self._embed_chart(analyzer.generate_profit_by_symbol_chart(), "Profit By Symbol")
        self._populate_trade_log_table(analyzer.trades_df)
        self.analysis_status_label.configure(text="Analysis complete.", text_color="green")

    def _embed_chart(self, fig: Figure, chart_name: str):
        # ... (this method is unchanged)
        if chart_name in self.analysis_canvas_widgets and self.analysis_canvas_widgets[chart_name]:
            self.analysis_canvas_widgets[chart_name].get_tk_widget().destroy()
        parent_frame = self.chart_frames.get(chart_name)
        if parent_frame:
            canvas = FigureCanvasTkAgg(fig, master=parent_frame)
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(side="top", fill="both", expand=True, padx=5, pady=5)
            canvas.draw()
            self.analysis_canvas_widgets[chart_name] = canvas
    
    def _populate_trade_log_table(self, df: pd.DataFrame):
        # ... (this method is unchanged)
        for widget in self.trade_log_frame.winfo_children():
            widget.destroy()
        headers = ['Timestamp', 'Symbol', 'Buy Ex', 'Sell Ex', 'Net Profit ($)']
        self.trade_log_frame.grid_columnconfigure((0,1,2,3,4), weight=1)
        for i, header in enumerate(headers):
            ctk.CTkLabel(self.trade_log_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5, pady=2)
        df_display = df[df['status'] == 'SUCCESS'].reset_index()
        for index, row in df_display.iterrows():
            row_num = index + 1
            ctk.CTkLabel(self.trade_log_frame, text=row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')).grid(row=row_num, column=0, padx=5, pady=2, sticky="w")
            ctk.CTkLabel(self.trade_log_frame, text=row['symbol']).grid(row=row_num, column=1, padx=5, pady=2)
            ctk.CTkLabel(self.trade_log_frame, text=row['buy_exchange']).grid(row=row_num, column=2, padx=5, pady=2)
            ctk.CTkLabel(self.trade_log_frame, text=row['sell_exchange']).grid(row=row_num, column=3, padx=5, pady=2)
            profit_label = ctk.CTkLabel(self.trade_log_frame, text=f"{row['net_profit_usd']:.4f}")
            profit_label.grid(row=row_num, column=4, padx=5, pady=2, sticky="e")
            profit_label.configure(text_color="green" if row['net_profit_usd'] > 0 else "red")
    
    def update_portfolio_display(self, current_data: Dict, initial_snapshot: Optional[Dict]):
        """Updates all widgets in the 'Portfolio Performance' section AND the pie chart."""
        if not initial_snapshot: return

        start_val = initial_snapshot.get("total_usd_value", 0.0)
        current_val = current_data.get("total_usd_value", 0.0)
        pnl = current_val - start_val
        growth = (pnl / start_val * 100) if start_val > 0 else 0.0
        
        # --- Update text labels (existing functionality) ---
        self.portfolio_labels["Starting Value ($)"].configure(text=f"${start_val:,.2f}")
        self.portfolio_labels["Current Value ($)"].configure(text=f"${current_val:,.2f}")
        self.portfolio_labels["Portfolio P/L ($)"].configure(text=f"${pnl:,.2f}", text_color="green" if pnl >= 0 else "red")
        self.portfolio_labels["Portfolio Growth (%)"].configure(text=f"{growth:.2f}%", text_color="green" if growth >= 0 else "red")
        
        # --- Update Pie Chart (NEW functionality) ---
        self.update_pie_chart(current_data)
        
        # --- Update Asset Breakdown text (existing functionality) ---
        for widget in self.portfolio_asset_breakdown_frame.winfo_children():
            if not isinstance(widget, ctk.CTkLabel) or "Asset Breakdown" not in widget.cget("text"):
                widget.destroy()

        all_assets = sorted(list(set(initial_snapshot.get("assets", {}).keys()) | set(current_data.get("assets", {}).keys())))
        for asset in all_assets:
            start_asset = initial_snapshot.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
            current_asset = current_data.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
            
            asset_frame = ctk.CTkFrame(self.portfolio_asset_breakdown_frame)
            asset_frame.pack(fill="x", pady=2)
            ctk.CTkLabel(asset_frame, text=asset, font=ctk.CTkFont(weight="bold"), width=60).pack(side="left", padx=5)
            ctk.CTkLabel(asset_frame, text=f"Start: ${start_asset['value_usd']:,.2f} ({start_asset['balance']:.4f})").pack(side="left", padx=10)
            ctk.CTkLabel(asset_frame, text=f"Now: ${current_asset['value_usd']:,.2f} ({current_asset['balance']:.4f})").pack(side="left", padx=10)
            
    def update_pie_chart(self, portfolio_data: Dict):
        """Clears and redraws the portfolio allocation pie chart."""
        assets = portfolio_data.get('assets', {})
        total_value_usd = portfolio_data.get('total_usd_value', 0)
        
        labels = []
        sizes = []
        
        # Filter out assets with zero or negligible value to keep the chart clean
        for asset, details in assets.items():
            if details['usd_value'] > 0.005 * total_value_usd: # Only show assets > 0.5% of portfolio
                labels.append(f"{asset}\n(${details['usd_value']:.2f})")
                sizes.append(details['usd_value'])

        # --- Update the plot ---
        self.portfolio_ax.clear() # Clear the previous plot
        if not sizes:
            self.portfolio_ax.text(0.5, 0.5, 'Waiting for portfolio data...', ha='center', va='center', color='white')
        else:
            wedges, texts, autotexts = self.portfolio_ax.pie(
                sizes, 
                autopct='%1.1f%%', 
                startangle=140,
                pctdistance=0.85
            )
            plt.setp(autotexts, size=8, weight="bold", color="white")
            self.portfolio_ax.legend(wedges, labels, title="Assets", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize='small', title_fontsize='small')

        self.portfolio_ax.set_title(f"Total Portfolio Value: ${total_value_usd:.2f}", color="white")
        self.portfolio_canvas.draw()