"""Dependency-free visual components for the address workspace."""
import tkinter as tk
from tkinter import ttk
import os
import webbrowser

from amap_lookup import text, selected_candidates
from ai_filter import DEFAULT_MODEL

BG = "#F3F5F8"
INK = "#192B3A"
MUTED = "#718096"
NAVY = "#152B3A"
ACCENT = "#087F73"
FONT = "Microsoft YaHei UI"


def label(parent, value, size=10, color=INK, bold=False, bg="white", **kwargs):
    return tk.Label(parent, text=value, font=(FONT, size, "bold" if bold else "normal"),
                    bg=bg, fg=color, anchor="w", **kwargs)


def card(parent, **kwargs):
    return tk.Frame(parent, bg="white", highlightbackground="#E2E7EE",
                    highlightthickness=1, **kwargs)


def configure_styles(root):
    root.configure(bg=BG)
    root.option_add("*Font", (FONT, 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TButton", font=(FONT, 10), padding=(12, 8), background="white",
                    foreground=INK, bordercolor="#DBE3EA", lightcolor="white", darkcolor="white")
    style.map("TButton", background=[("active", "#EDF4F5")],
              foreground=[("disabled", "#A5AFBA")])
    style.configure("Primary.TButton", background=ACCENT, foreground="white",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, font=(FONT, 10, "bold"))
    style.map("Primary.TButton", background=[("disabled", "#ADC8C4"), ("active", "#066A60")],
              foreground=[("disabled", "#F4F8F7"), ("!disabled", "white")])
    style.configure("Side.TCheckbutton", background=NAVY, foreground="#D7E3EC",
                    font=(FONT, 9), padding=0)
    style.map("Side.TCheckbutton", background=[("active", NAVY)],
              indicatorbackground=[("selected", "#41C4AE"), ("!selected", "#284355")])
    style.configure("Side.TEntry", fieldbackground="#223E50", foreground="white",
                    insertcolor="white", bordercolor="#3B5668", padding=8)
    style.configure("Side.TCombobox", fieldbackground="#223E50", foreground="white", padding=6)
    style.configure("Treeview", background="white", fieldbackground="white", foreground=INK,
                    rowheight=38, font=(FONT, 10), borderwidth=0)
    style.configure("Treeview.Heading", font=(FONT, 9, "bold"), background="#EDF2F6",
                    foreground="#506476", borderwidth=0, padding=(8, 10), relief="flat")
    style.map("Treeview", background=[("selected", "#DCEFEA")],
              foreground=[("selected", "#075F56")])
    style.map("Treeview.Heading", background=[("active", "#E3EBF1")])
    style.configure("Horizontal.TProgressbar", troughcolor="#E7EEF2", background=ACCENT,
                    borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT, thickness=4)
    style.configure("TScrollbar", background="#D8E1E8", troughcolor="#F6F8FA",
                    borderwidth=0, arrowsize=12)


def build_ui(app, config, ai_config):
    root = app.root
    root.title("地点工作台 · 高德 × DeepSeek")
    root.geometry("1320x860")
    root.minsize(1100, 760)
    configure_styles(root)
    app.key = tk.StringVar(value=os.environ.get("AMAP_KEY") or text(config.get("key")))
    app.remember = tk.BooleanVar(value=bool(config.get("key")))
    app.city = tk.StringVar(value=text(config.get("city")) if "city" in config else "")
    app.ai_enabled = tk.BooleanVar(value=bool(ai_config.get("enabled", False)))
    app.ai_key = tk.StringVar(value=os.environ.get("DEEPSEEK_API_KEY") or text(ai_config.get("key")))
    app.ai_remember = tk.BooleanVar(value=bool(ai_config.get("key")))
    app.ai_model = tk.StringVar(value=text(ai_config.get("model")) or DEFAULT_MODEL)
    app.status = tk.StringVar(value="准备就绪。填写服务 Key，粘贴地点名称后开始查询。")

    side = tk.Frame(root, bg=NAVY, width=300)
    side.pack(side="left", fill="y")
    side.pack_propagate(False)
    branding = tk.Frame(side, bg=NAVY)
    branding.pack(fill="x", padx=24, pady=(28, 24))
    icon = tk.Canvas(branding, width=42, height=44, bg=NAVY, highlightthickness=0)
    icon.pack(side="left", padx=(0, 12))
    icon.create_oval(6, 2, 36, 32, fill="#42C7B0", outline="")
    icon.create_polygon(8, 24, 21, 42, 34, 24, fill="#42C7B0", outline="")
    icon.create_oval(16, 12, 26, 22, fill=NAVY, outline="")
    title = tk.Frame(branding, bg=NAVY)
    title.pack(side="left")
    label(title, "地点工作台", 18, "white", True, NAVY).pack(anchor="w")
    label(title, "ADDRESS WORKSPACE", 8, "#83A6B8", bg=NAVY).pack(anchor="w", pady=(3, 0))
    label(side, "连接服务", 10, "#83A6B8", True, NAVY).pack(anchor="w", padx=24, pady=(0, 14))

    def section_title(value, subtitle):
        label(side, value, 12, "#FFFFFF", True, NAVY).pack(anchor="w", padx=24)
        label(side, subtitle, 9, "#94ADBC", bg=NAVY).pack(anchor="w", padx=24, pady=(4, 12))

    section_title("01  /  高德地图", "搜索原始地点与详细地址")
    label(side, "Web 服务 Key", 9, "#CCDCE6", bg=NAVY).pack(anchor="w", padx=24, pady=(0, 6))
    ttk.Entry(side, textvariable=app.key, show="•", style="Side.TEntry").pack(fill="x", padx=24)
    ttk.Checkbutton(side, text="在本机记住 Key", variable=app.remember,
                    style="Side.TCheckbutton").pack(anchor="w", padx=24, pady=(10, 12))
    label(side, "限定城市", 9, "#CCDCE6", bg=NAVY).pack(anchor="w", padx=24, pady=(0, 6))
    ttk.Entry(side, textvariable=app.city, style="Side.TEntry").pack(fill="x", padx=24)
    label(side, "留空搜索全国，填写城市可减少重名", 9, "#94ADBC", bg=NAVY).pack(anchor="w", padx=24, pady=(8, 0))
    link = label(side, "申请高德 Key ↗", 9, "#57D9C2", bg=NAVY, cursor="hand2")
    link.pack(anchor="w", padx=24, pady=(12, 20))
    link.bind("<Button-1>", lambda _: webbrowser.open("https://lbs.amap.com/api/webservice/create-project-and-key"))
    tk.Frame(side, height=1, bg="#304B5B").pack(fill="x", padx=24, pady=(0, 20))

    section_title("02  /  DeepSeek", "从高德候选中辅助筛选，可选启用")
    ttk.Checkbutton(side, text="启用 AI 辅助筛选", variable=app.ai_enabled,
                    style="Side.TCheckbutton").pack(anchor="w", padx=24, pady=(0, 12))
    label(side, "DeepSeek API Key", 9, "#CCDCE6", bg=NAVY).pack(anchor="w", padx=24, pady=(0, 6))
    ttk.Entry(side, textvariable=app.ai_key, show="•", style="Side.TEntry").pack(fill="x", padx=24)
    ttk.Checkbutton(side, text="在本机记住 AI Key", variable=app.ai_remember,
                    style="Side.TCheckbutton").pack(anchor="w", padx=24, pady=(10, 12))
    label(side, "模型名称", 9, "#CCDCE6", bg=NAVY).pack(anchor="w", padx=24, pady=(0, 6))
    ttk.Entry(side, textvariable=app.ai_model, style="Side.TEntry").pack(fill="x", padx=24)
    label(side, "≥90% 且无歧义才自动勾选；分数为 AI\n估计。启用后，地点与候选将发送至\nDeepSeek，并按其 API 用量计费。", 9,
          "#94ADBC", bg=NAVY, justify="left").pack(anchor="w", padx=24, pady=(12, 0))
    label(side, "本机记住的 Key 为明文配置。\n分享项目时请勿包含配置或查询结果。", 9,
          "#94ADBC", bg=NAVY, justify="left").pack(side="bottom", anchor="w", padx=24, pady=24)

    main = tk.Frame(root, bg=BG)
    main.pack(side="left", fill="both", expand=True, padx=26, pady=24)
    header = tk.Frame(main, bg=BG)
    header.pack(fill="x", pady=(0, 20))
    label(header, "把地点名称，变成清晰的地址。", 23, INK, True, BG).pack(anchor="w")
    label(header, "批量搜索  /  AI 辅助核对  /  由你确认最终结果", 10, MUTED, bg=BG).pack(anchor="w", pady=(7, 0))

    stats = tk.Frame(main, bg=BG)
    stats.pack(fill="x", pady=(0, 16))
    app.summary_vars = []
    for i, (title_text, caption, color) in enumerate((
            ("已查询名称", "本次已返回的查询", INK),
            ("已勾选地址", "可复制或导出", ACCENT),
            ("待处理名称", "未选中或请求失败", "#B56A1F"))):
        box = card(stats)
        box.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
        stats.columnconfigure(i, weight=1, uniform="stats")
        label(box, title_text, 9, MUTED).pack(anchor="w", padx=16, pady=(11, 0))
        count = tk.StringVar(value="0")
        app.summary_vars.append(count)
        tk.Label(box, textvariable=count, bg="white", fg=color, font=(FONT, 24, "bold"), anchor="w").pack(anchor="w", padx=16)
        label(box, caption, 8, MUTED).pack(anchor="w", padx=16, pady=(0, 10))

    input_box = card(main)
    input_box.pack(fill="x", pady=(0, 16))
    input_heading = tk.Frame(input_box, bg="white")
    input_heading.pack(fill="x", padx=18, pady=(14, 10))
    label(input_heading, "地点名称", 12, INK, True).pack(side="left")
    app.input_count = tk.StringVar(value="0 / 500")
    tk.Label(input_heading, textvariable=app.input_count, font=(FONT, 9), bg="white", fg=MUTED).pack(side="right")
    label(input_heading, "一行一个，可直接粘贴列表", 9, MUTED).pack(side="left", padx=14)
    input_wrap = tk.Frame(input_box, bg="#E2E7EE", padx=1, pady=1)
    input_wrap.pack(fill="x", padx=18)
    app.names = tk.Text(input_wrap, height=4, font=(FONT, 11), wrap="word", relief="flat",
                        bg="#F8FAFC", fg=INK, insertbackground=ACCENT, padx=12, pady=10,
                        selectbackground="#DCEFEA", undo=True)
    app.names.pack(fill="x")
    app.names.bind("<<Modified>>", lambda _: update_input_count(app))
    actions = tk.Frame(input_box, bg="white")
    actions.pack(fill="x", padx=18, pady=14)
    app.search_button = ttk.Button(actions, text="开始查询 →", command=app.start, style="Primary.TButton")
    app.search_button.pack(side="left")
    app.retry_button = ttk.Button(actions, text="重试失败项", command=lambda: app.start(retry_failed=True))
    app.retry_button.pack(side="left", padx=8)
    app.stop_button = ttk.Button(actions, text="停止", command=app.stop.set, state="disabled")
    app.stop_button.pack(side="left")
    label(actions, "每批最多 500 个地点", 9, MUTED).pack(side="right")

    result_box = card(main)
    result_box.pack(fill="both", expand=True)
    toolbar = tk.Frame(result_box, bg="white")
    toolbar.pack(fill="x", padx=18, pady=(14, 12))
    label(toolbar, "查询结果", 12, INK, True).pack(side="left")
    ttk.Button(toolbar, text="导出 CSV", command=app.export).pack(side="right")
    ttk.Button(toolbar, text="复制勾选地址", command=app.copy_addresses).pack(side="right", padx=8)
    ttk.Button(toolbar, text="清空此项勾选", command=app.clear_selected).pack(side="right")
    table = tk.Frame(result_box, bg="white")
    table.pack(fill="both", expand=True, padx=1)
    app.tree = ttk.Treeview(table, columns=("pick", "address", "confidence", "status", "reason"), selectmode="browse")
    for col, title_text, width in (("#0", "名称 / 候选地点", 215), ("pick", "勾选", 56),
                                   ("address", "详细地址", 245), ("confidence", "AI 匹配度", 100),
                                   ("status", "状态", 155), ("reason", "筛选依据 / 待核对原因", 270)):
        app.tree.heading(col, text=title_text, anchor="w" if col != "pick" else "center")
        app.tree.column(col, width=width, minwidth=width, stretch=col in ("address", "reason"))
    app.tree.column("pick", anchor="center")
    app.tree.column("confidence", anchor="center")
    app.tree.tag_configure("query", background="#F0F4F7", foreground=INK, font=(FONT, 10, "bold"))
    app.tree.tag_configure("selected", foreground="#087466", background="#F0FAF6")
    app.tree.tag_configure("review", foreground="#9D601D", background="#FFFAF1")
    app.tree.tag_configure("odd", background="#F8FAFC")
    ybar = ttk.Scrollbar(table, orient="vertical", command=app.tree.yview)
    xbar = ttk.Scrollbar(table, orient="horizontal", command=app.tree.xview)
    app.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    app.tree.grid(row=0, column=0, sticky="nsew")
    ybar.grid(row=0, column=1, sticky="ns")
    xbar.grid(row=1, column=0, sticky="ew")
    table.columnconfigure(0, weight=1)
    table.rowconfigure(0, weight=1)
    app.tree.bind("<Double-1>", app.select_candidate)
    app.tree.bind("<Button-1>", app.click_checkbox)
    app.tree.bind("<space>", app.select_candidate)
    app.empty_state = tk.Frame(table, bg="white")
    app.empty_state.place(relx=.5, rely=.43, anchor="center")
    label(app.empty_state, "◎", 30, "#49A99C").pack(anchor="center")
    label(app.empty_state, "下一个准确地址，从这里开始", 13, "#506476", True).pack(anchor="center", pady=(5, 7))
    label(app.empty_state, "填写左侧 Key，输入地点名称，点击「开始查询」", 9, MUTED).pack(anchor="center")
    label(result_box, "展开候选后点击方框或双击勾选；每个名称可保留多个地址。", 9, MUTED).pack(anchor="w", padx=18, pady=(10, 12))

    app.progress = ttk.Progressbar(main, mode="determinate", maximum=1)
    app.progress.pack(fill="x", pady=(16, 8))
    status_label = tk.Label(main, textvariable=app.status, bg=BG, fg="#506476", font=(FONT, 9),
                           anchor="w", justify="left", wraplength=930)
    status_label.pack(fill="x")
    main.bind("<Configure>", lambda e: status_label.configure(wraplength=max(100, e.width - 8)))


def update_input_count(app):
    count = len({n.strip() for n in app.names.get("1.0", "end").splitlines() if n.strip()})
    app.input_count.set(f"{count} / 500")
    app.names.edit_modified(False)


def update_summary(app):
    app.summary_vars[0].set(str(len(app.results)))
    app.summary_vars[1].set(str(sum(len(selected_candidates(r)) for r in app.results)))
    app.summary_vars[2].set(str(sum(not selected_candidates(r) for r in app.results)))
    if app.results:
        app.empty_state.place_forget()
    else:
        app.empty_state.place(relx=.5, rely=.43, anchor="center")
