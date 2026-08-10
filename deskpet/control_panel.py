"""M3 普通标题栏控制面板；Tk 与 Pygame 共用主线程并通过队列传递命令。"""

from __future__ import annotations

import queue
import os
import sys
from pathlib import Path
from typing import Any


class ControlPanelBridge:
    def __init__(self) -> None:
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self.updates: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=3)
        self.root: Any | None = None

    def open(self, snapshot: dict[str, Any]) -> None:
        if self.root is None:
            self._run()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.push_snapshot(snapshot)
        self.pump()

    @property
    def is_created(self) -> bool:
        return self.root is not None

    def push_snapshot(self, snapshot: dict[str, Any]) -> None:
        try:
            self.updates.put_nowait(snapshot)
        except queue.Full:
            try:
                self.updates.get_nowait()
            except queue.Empty:
                pass
            self.updates.put_nowait(snapshot)

    def poll_commands(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        while True:
            try:
                result.append(self.commands.get_nowait())
            except queue.Empty:
                return result

    def close(self) -> None:
        if self.root is None:
            return
        try:
            self.root.destroy()
        except Exception:
            pass
        self.root = None

    def pump(self) -> None:
        if self.root is None:
            return
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            self.root = None

    def _run(self) -> None:
        # PyInstaller's standard Tk hook can overwrite the path set by a
        # custom runtime hook.  Correct it immediately before importing
        # tkinter so one-file builds always use their private script library.
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            runtime_root = Path(bundle_root) / "tcl_runtime"
            tcl_library = runtime_root / "tcl8.6"
            tk_library = runtime_root / "tk8.6"
            if (tcl_library / "init.tcl").is_file():
                os.environ["TCL_LIBRARY"] = str(tcl_library)
            if (tk_library / "tk.tcl").is_file():
                os.environ["TK_LIBRARY"] = str(tk_library)

        import tkinter as tk
        from tkinter import filedialog, ttk

        root = tk.Tk()
        self.root = root
        root.title("线条小狗桌宠 · 控制面板")
        root.geometry("760x650")
        root.minsize(720, 600)
        root.configure(bg="#f6f1ef")
        root.withdraw()

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f6f1ef")
        style.configure("TLabel", background="#f6f1ef", foreground="#493e42", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"), foreground="#5e4850")
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9), foreground="#87747b")
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(9, 5))
        style.configure("Accent.TButton", background="#ffd9df", foreground="#5d444c")
        style.configure("TCheckbutton", background="#f6f1ef", font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background="#f6f1ef", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=(14, 8))
        style.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=26)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="线条小狗桌宠", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="照顾、计时、便签和系统设置", style="Sub.TLabel").pack(anchor="w", pady=(0, 10))
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        home = ttk.Frame(notebook, padding=14)
        timing = ttk.Frame(notebook, padding=14)
        notes = ttk.Frame(notebook, padding=14)
        appearance = ttk.Frame(notebook, padding=14)
        system = ttk.Frame(notebook, padding=14)
        ai = ttk.Frame(notebook, padding=14)
        notebook.add(home, text="首页")
        notebook.add(timing, text="计时")
        notebook.add(notes, text="便签")
        notebook.add(appearance, text="外观与行为")
        notebook.add(system, text="系统与工具")
        notebook.add(ai, text="AI（可选）")

        def send(command: str, **values: Any) -> None:
            self.commands.put({"command": command, **values})

        # 首页
        home_status = tk.StringVar(value="正在读取角色状态……")
        home_timer = tk.StringVar(value="当前没有运行中的计时")
        ttk.Label(home, textvariable=home_status, font=("Microsoft YaHei UI", 11), justify="left").pack(anchor="w", pady=(4, 12))
        ttk.Label(home, textvariable=home_timer, style="Sub.TLabel").pack(anchor="w", pady=(0, 16))
        care_frame = ttk.LabelFrame(home, text="照顾", padding=12)
        care_frame.pack(fill="x")
        care_actions = (
            ("feed_meal", "营养餐"),
            ("feed_icecream", "冰淇淋"),
            ("exercise_warmup", "热身弹跳"),
            ("exercise_cheer", "啦啦操"),
            ("exercise_run", "跑步"),
            ("pet", "摸摸"),
            ("bathe", "洗澡"),
            ("sleep", "睡觉/叫醒"),
            ("treat", "治疗"),
        )
        for index, (action, label) in enumerate(care_actions):
            ttk.Button(care_frame, text=label, command=lambda value=action: send("care", action=value)).grid(
                row=index // 4, column=index % 4, padx=5, pady=5, sticky="ew"
            )
        for column in range(4):
            care_frame.columnconfigure(column, weight=1)

        # 计时
        countdown = ttk.LabelFrame(timing, text="倒计时", padding=10)
        countdown.pack(fill="x", pady=(0, 8))
        countdown_title = tk.StringVar(value="休息一下")
        countdown_minutes = tk.StringVar(value="10")
        ttk.Entry(countdown, textvariable=countdown_title, width=24).grid(row=0, column=0, padx=4)
        ttk.Entry(countdown, textvariable=countdown_minutes, width=7).grid(row=0, column=1, padx=4)
        ttk.Label(countdown, text="分钟").grid(row=0, column=2)
        ttk.Button(countdown, text="开始", style="Accent.TButton", command=lambda: send("start_countdown", title=countdown_title.get(), minutes=countdown_minutes.get())).grid(row=0, column=3, padx=6)

        alarm = ttk.LabelFrame(timing, text="闹钟", padding=10)
        alarm.pack(fill="x", pady=8)
        alarm_title = tk.StringVar(value="提醒")
        alarm_time = tk.StringVar(value="09:00")
        alarm_weekdays = tk.StringVar(value="")
        ttk.Entry(alarm, textvariable=alarm_title, width=20).grid(row=0, column=0, padx=4)
        ttk.Entry(alarm, textvariable=alarm_time, width=8).grid(row=0, column=1, padx=4)
        ttk.Entry(alarm, textvariable=alarm_weekdays, width=16).grid(row=0, column=2, padx=4)
        ttk.Button(alarm, text="添加闹钟", command=lambda: send("start_alarm", title=alarm_title.get(), time=alarm_time.get(), weekdays=alarm_weekdays.get())).grid(row=0, column=3, padx=5)
        ttk.Label(alarm, text="重复星期可填：1,2,3,4,5；留空表示一次", style="Sub.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))

        pomodoro = ttk.LabelFrame(timing, text="番茄钟", padding=10)
        pomodoro.pack(fill="x", pady=8)
        pomo_work, pomo_short, pomo_long = tk.StringVar(value="25"), tk.StringVar(value="5"), tk.StringVar(value="15")
        for index, (label, variable) in enumerate((("专注", pomo_work), ("短休", pomo_short), ("长休", pomo_long))):
            ttk.Label(pomodoro, text=label).grid(row=0, column=index * 2, padx=(4, 1))
            ttk.Entry(pomodoro, textvariable=variable, width=5).grid(row=0, column=index * 2 + 1, padx=(1, 5))
        ttk.Button(pomodoro, text="开始四轮", style="Accent.TButton", command=lambda: send("start_pomodoro", work=pomo_work.get(), short=pomo_short.get(), long=pomo_long.get())).grid(row=0, column=6, padx=5)
        ttk.Button(pomodoro, text="停止", command=lambda: send("stop_pomodoro")).grid(row=0, column=7, padx=5)

        timer_tree = ttk.Treeview(timing, columns=("title", "end"), show="headings", height=6)
        timer_tree.heading("title", text="运行中的计时")
        timer_tree.heading("end", text="结束时间")
        timer_tree.column("title", width=390)
        timer_tree.column("end", width=160, anchor="center")
        timer_tree.pack(fill="both", expand=True, pady=(8, 4))
        ttk.Button(timing, text="取消选中计时", command=lambda: send("cancel_timer", timer_id=(timer_tree.selection()[0] if timer_tree.selection() else ""))).pack(anchor="e")

        # 便签
        note_top = ttk.Frame(notes)
        note_top.pack(fill="x")
        note_search = tk.StringVar()
        ttk.Entry(note_top, textvariable=note_search, width=28).pack(side="left", padx=(0, 5))
        ttk.Button(note_top, text="搜索", command=lambda: send("search_notes", search=note_search.get())).pack(side="left")
        show_deleted = tk.BooleanVar(value=False)
        ttk.Checkbutton(note_top, text="最近删除", variable=show_deleted, command=lambda: send("show_deleted_notes", enabled=show_deleted.get())).pack(side="right")

        note_tree = ttk.Treeview(notes, columns=("done", "title", "priority", "due"), show="headings", height=8)
        for key, label, width in (("done", "状态", 60), ("title", "标题", 290), ("priority", "优先级", 75), ("due", "到期", 150)):
            note_tree.heading(key, text=label)
            note_tree.column(key, width=width, anchor="center" if key != "title" else "w")
        note_tree.pack(fill="both", expand=True, pady=8)

        editor = ttk.LabelFrame(notes, text="新建便签 / 待办", padding=8)
        editor.pack(fill="x")
        note_title, note_due = tk.StringVar(), tk.StringVar()
        note_priority = tk.StringVar(value="普通")
        note_content = tk.Text(editor, height=3, width=46, font=("Microsoft YaHei UI", 9), relief="solid", borderwidth=1)
        ttk.Entry(editor, textvariable=note_title, width=25).grid(row=0, column=0, padx=3, sticky="ew")
        ttk.Entry(editor, textvariable=note_due, width=18).grid(row=0, column=1, padx=3)
        ttk.Combobox(editor, textvariable=note_priority, values=("低", "普通", "高"), width=7, state="readonly").grid(row=0, column=2, padx=3)
        note_content.grid(row=1, column=0, columnspan=3, padx=3, pady=5, sticky="ew")
        ttk.Label(editor, text="到期时间示例：2026-08-08 18:30；可留空", style="Sub.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Button(editor, text="添加", style="Accent.TButton", command=lambda: send("add_note", title=note_title.get(), content=note_content.get("1.0", "end").strip(), due=note_due.get(), priority=note_priority.get())).grid(row=2, column=2, sticky="e")

        note_buttons = ttk.Frame(notes)
        note_buttons.pack(fill="x", pady=(7, 0))
        def selected_note() -> str:
            return note_tree.selection()[0] if note_tree.selection() else ""
        ttk.Button(note_buttons, text="完成/恢复", command=lambda: send("toggle_note", note_id=selected_note())).pack(side="left", padx=3)
        ttk.Button(note_buttons, text="延期一天", command=lambda: send("postpone_note", note_id=selected_note())).pack(side="left", padx=3)
        ttk.Button(note_buttons, text="删除/恢复", command=lambda: send("delete_or_restore_note", note_id=selected_note(), deleted=show_deleted.get())).pack(side="left", padx=3)
        ttk.Button(note_buttons, text="导出文本", command=lambda: send("export_notes", destination=filedialog.asksaveasfilename(title="导出便签", defaultextension=".txt", filetypes=(("文本文件", "*.txt"),)))).pack(side="right", padx=3)

        # AI（可选）：不开启或未填写接口时不会发出任何网络请求。
        ai_enabled = tk.BooleanVar(value=False)
        ai_base_url = tk.StringVar()
        ai_model = tk.StringVar()
        ai_api_key = tk.StringVar()
        ai_config = ttk.LabelFrame(ai, text="兼容 OpenAI 的接口配置", padding=12)
        ai_config.pack(fill="x", pady=(4, 10))
        ttk.Checkbutton(ai_config, text="启用 AI 功能", variable=ai_enabled).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(ai_config, text="接口地址").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(ai_config, textvariable=ai_base_url, width=48).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(ai_config, text="模型名").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_config, textvariable=ai_model, width=48).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(ai_config, text="API 密钥").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_config, textvariable=ai_api_key, show="*", width=48).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(ai_config, text="密钥只保留在本次运行内存中，不写入设置文件。未启用时桌宠完全离线运行。", style="Sub.TLabel", wraplength=500).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ai_config.columnconfigure(1, weight=1)
        ai_question = tk.StringVar()
        ai_history = tk.Text(ai, height=10, wrap="word", state="disabled")
        ai_history.pack(fill="both", expand=True, pady=(4, 8))
        ai_send = ttk.Frame(ai)
        ai_send.pack(fill="x")
        ttk.Entry(ai_send, textvariable=ai_question).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(ai_send, text="发送", command=lambda: (send("ai_chat", message=ai_question.get()), ai_question.set(""))).pack(side="right")
        ttk.Button(ai_send, text="清除聊天记录", command=lambda: send("clear_ai_data")).pack(side="right", padx=(0, 6))

        # 外观与行为
        scale_value = tk.DoubleVar(value=1.0)
        speed_value = tk.DoubleVar(value=1.0)
        bubble_speed = tk.IntVar(value=18)
        gravity = tk.BooleanVar(value=True)
        collision = tk.BooleanVar(value=True)
        edge_snap = tk.BooleanVar(value=True)
        reminders_enabled = tk.BooleanVar(value=True)
        alarm_sound = tk.BooleanVar(value=True)
        interaction_sound = tk.BooleanVar(value=False)
        reminder_sedentary = tk.BooleanVar(value=True)
        reminder_water = tk.BooleanVar(value=True)
        reminder_eyes = tk.BooleanVar(value=True)
        sedentary_minutes, water_minutes, eye_minutes = tk.StringVar(value="60"), tk.StringVar(value="70"), tk.StringVar(value="45")
        growth_tick_minutes = tk.StringVar(value="10")
        natural_decay_multiplier = tk.StringVar(value="2.0")
        passive_energy_decay_per_hour = tk.StringVar(value="0.2")
        exercise_energy_multiplier = tk.StringVar(value="2.0")

        visual = ttk.LabelFrame(appearance, text="显示", padding=12)
        visual.pack(fill="x", pady=(0, 10))
        ttk.Label(visual, text="角色大小").grid(row=0, column=0, sticky="w")
        ttk.Scale(visual, from_=0.5, to=2.0, variable=scale_value, length=320).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(visual, text="动画速度").grid(row=1, column=0, sticky="w")
        ttk.Scale(visual, from_=0.5, to=1.5, variable=speed_value, length=320).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(visual, text="气泡打字速度").grid(row=2, column=0, sticky="w")
        ttk.Scale(visual, from_=10, to=30, variable=bubble_speed, length=320).grid(row=2, column=1, sticky="ew", padx=8)
        visual.columnconfigure(1, weight=1)

        behavior = ttk.LabelFrame(appearance, text="行为与提醒", padding=12)
        behavior.pack(fill="x")
        for index, (label, variable) in enumerate((("重力", gravity), ("窗口表面碰撞", collision), ("屏幕边缘吸附", edge_snap), ("闹钟声音", alarm_sound), ("互动声音", interaction_sound))):
            ttk.Checkbutton(behavior, text=label, variable=variable).grid(row=0, column=index, padx=7, sticky="w")
        ttk.Checkbutton(behavior, text="久坐提醒", variable=reminder_sedentary).grid(row=1, column=0, padx=7, pady=7, sticky="w")
        ttk.Entry(behavior, textvariable=sedentary_minutes, width=6).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(behavior, text="喝水提醒", variable=reminder_water).grid(row=2, column=0, padx=7, pady=7, sticky="w")
        ttk.Entry(behavior, textvariable=water_minutes, width=6).grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(behavior, text="护眼提醒", variable=reminder_eyes).grid(row=3, column=0, padx=7, pady=7, sticky="w")
        ttk.Entry(behavior, textvariable=eye_minutes, width=6).grid(row=3, column=1, sticky="w")
        ttk.Label(behavior, text="分钟", style="Sub.TLabel").grid(row=1, column=2, rowspan=3, sticky="nw", pady=9)

        growth_behavior = ttk.LabelFrame(appearance, text="养成参数", padding=12)
        growth_behavior.pack(fill="x", pady=(10, 0))
        ttk.Label(growth_behavior, text="状态结算周期").grid(row=0, column=0, sticky="w")
        ttk.Entry(growth_behavior, textvariable=growth_tick_minutes, width=7).grid(row=0, column=1, padx=(5, 3))
        ttk.Label(growth_behavior, text="分钟（1～60）", style="Sub.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(growth_behavior, text="自然消耗倍率").grid(row=0, column=3, padx=(22, 0), sticky="w")
        ttk.Entry(growth_behavior, textvariable=natural_decay_multiplier, width=7).grid(row=0, column=4, padx=5)
        ttk.Label(growth_behavior, text="倍（0～5）", style="Sub.TLabel").grid(row=0, column=5, sticky="w")
        ttk.Label(growth_behavior, text="体力自然消耗").grid(row=1, column=0, pady=(8, 0), sticky="w")
        ttk.Entry(growth_behavior, textvariable=passive_energy_decay_per_hour, width=7).grid(row=1, column=1, padx=(5, 3), pady=(8, 0))
        ttk.Label(growth_behavior, text="点/小时（0～2）", style="Sub.TLabel").grid(row=1, column=2, pady=(8, 0), sticky="w")
        ttk.Label(growth_behavior, text="运动体力倍率").grid(row=1, column=3, padx=(22, 0), pady=(8, 0), sticky="w")
        ttk.Entry(growth_behavior, textvariable=exercise_energy_multiplier, width=7).grid(row=1, column=4, padx=5, pady=(8, 0))
        ttk.Label(growth_behavior, text="倍（0～4）", style="Sub.TLabel").grid(row=1, column=5, pady=(8, 0), sticky="w")

        # 系统与工具
        system_text = tk.StringVar(value="CPU --  内存 --  电量 --  网络 --  温度：系统未提供")
        ttk.Label(system, textvariable=system_text, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(3, 12))
        builtin_frame = ttk.LabelFrame(system, text="快捷工具", padding=12)
        builtin_frame.pack(fill="x")
        for index, (tool_id, label) in enumerate((("calculator", "计算器"), ("notepad", "记事本"), ("screenshot", "截图工具"), ("explorer", "资源管理器"))):
            ttk.Button(builtin_frame, text=label, command=lambda value=tool_id: send("launch_tool", tool=value)).grid(row=0, column=index, padx=6, pady=3, sticky="ew")
            builtin_frame.columnconfigure(index, weight=1)
        custom_name = tk.StringVar(value="我的工具")
        custom_target = tk.StringVar()
        custom = ttk.LabelFrame(system, text="自定义程序或网页", padding=12)
        custom.pack(fill="x", pady=10)
        ttk.Entry(custom, textvariable=custom_name, width=14).pack(side="left", padx=(0, 5))
        ttk.Entry(custom, textvariable=custom_target).pack(side="left", fill="x", expand=True, padx=(0, 7))
        ttk.Button(custom, text="打开", command=lambda: send("launch_custom", target=custom_target.get())).pack(side="right")
        ttk.Button(custom, text="保存", command=lambda: send("save_custom_tool", name=custom_name.get(), target=custom_target.get())).pack(side="right", padx=(0, 5))
        custom_list = ttk.Combobox(custom, values=(), width=15, state="readonly")
        custom_list.pack(side="right", padx=(0, 5))
        custom_list.bind(
            "<<ComboboxSelected>>",
            lambda _event: (
                custom_name.set(custom_list.get().split("｜", 1)[0]),
                custom_target.set(custom_list.get().split("｜", 1)[1] if "｜" in custom_list.get() else ""),
            ),
        )

        topmost = tk.BooleanVar(value=True)
        click_through = tk.BooleanVar(value=False)
        autostart = tk.BooleanVar(value=False)
        system_options = ttk.LabelFrame(system, text="窗口与启动", padding=12)
        weather_enabled = tk.BooleanVar(value=False)
        weather_city = tk.StringVar()
        fullscreen_policy = tk.StringVar(value="quiet")
        environment_options = ttk.LabelFrame(system, text="环境与全屏", padding=12)
        environment_options.pack(fill="x", pady=(10, 0))
        data_options = ttk.LabelFrame(system, text="数据管理", padding=12)
        data_options.pack(fill="x", pady=(10, 0))
        ttk.Button(data_options, text="备份全部数据", command=lambda: send("backup_data", destination=filedialog.asksaveasfilename(defaultextension=".zip", filetypes=(("桌宠备份", "*.zip"),)))).pack(side="left", padx=4)
        ttk.Button(data_options, text="恢复备份", command=lambda: send("restore_data", source=filedialog.askopenfilename(filetypes=(("桌宠备份", "*.zip"),)))).pack(side="left", padx=4)
        weather_text = tk.StringVar(value="天气未启用")

        def apply_weather_from_panel() -> None:
            send(
                "apply_weather",
                enabled=weather_enabled.get(),
                city=weather_city.get(),
            )

        ttk.Checkbutton(
            environment_options,
            text="启用天气",
            variable=weather_enabled,
            command=apply_weather_from_panel,
        ).grid(row=0, column=0, sticky="w")
        weather_city_entry = ttk.Entry(
            environment_options,
            textvariable=weather_city,
            width=16,
        )
        weather_city_entry.grid(row=0, column=1, padx=6)
        weather_city_entry.bind(
            "<Return>",
            lambda _event: (apply_weather_from_panel(), "break")[1],
        )
        ttk.Button(
            environment_options,
            text="刷新天气",
            command=apply_weather_from_panel,
        ).grid(row=0, column=2, padx=4)
        ttk.Label(environment_options, textvariable=weather_text, style="Sub.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Label(environment_options, text="全屏时").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(environment_options, textvariable=fullscreen_policy, values=("hide", "quiet", "ignore"), state="readonly", width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(environment_options, text="hide=隐藏，quiet=安静，ignore=忽略", style="Sub.TLabel").grid(row=1, column=2, sticky="w", pady=(8, 0))
        system_options.pack(fill="x")
        ttk.Checkbutton(system_options, text="强力置顶", variable=topmost).pack(side="left", padx=6)
        ttk.Checkbutton(system_options, text="鼠标穿透", variable=click_through).pack(side="left", padx=6)
        ttk.Checkbutton(system_options, text="开机自启", variable=autostart).pack(side="left", padx=6)

        apply_status = tk.StringVar(value="")
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(footer, textvariable=apply_status, style="Sub.TLabel").pack(side="left")
        ttk.Button(
            footer,
            text="应用设置",
            style="Accent.TButton",
            command=lambda: send(
                "apply_settings",
                values={
                    "scale": scale_value.get(),
                    "animation_speed": speed_value.get(),
                    "bubble_speed": bubble_speed.get(),
                    "gravity": gravity.get(),
                    "window_collision": collision.get(),
                    "edge_snap": edge_snap.get(),
                    "alarm_sound": alarm_sound.get(),
                    "interaction_sound": interaction_sound.get(),
                    "reminder_sedentary": reminder_sedentary.get(),
                    "reminder_water": reminder_water.get(),
                    "reminder_eyes": reminder_eyes.get(),
                    "reminder_sedentary_minutes": sedentary_minutes.get(),
                    "reminder_water_minutes": water_minutes.get(),
                    "reminder_eyes_minutes": eye_minutes.get(),
                    "growth_tick_minutes": growth_tick_minutes.get(),
                    "natural_decay_multiplier": natural_decay_multiplier.get(),
                    "passive_energy_decay_per_hour": passive_energy_decay_per_hour.get(),
                    "exercise_energy_multiplier": exercise_energy_multiplier.get(),
                    "topmost": topmost.get(),
                    "click_through": click_through.get(),
                    "autostart": autostart.get(),
                    "ai_enabled": ai_enabled.get(),
                    "ai_base_url": ai_base_url.get(),
                    "ai_model": ai_model.get(),
                    "ai_api_key": ai_api_key.get(),
                    "weather_enabled": weather_enabled.get(),
                    "weather_city": weather_city.get(),
                    "fullscreen_policy": fullscreen_policy.get(),
                },
            ),
        ).pack(side="right")

        note_cache: dict[str, dict[str, Any]] = {}

        def format_percent(value: Any) -> str:
            return "--" if value is None else f"{float(value):.0f}%"

        def apply_snapshot(snapshot: dict[str, Any]) -> None:
            nonlocal note_cache
            growth = snapshot.get("growth")
            if isinstance(growth, dict):
                home_status.set(
                    f"Lv.{growth.get('level', 1)}  {growth.get('mode', '清醒')}    "
                    f"饱腹 {growth.get('fullness', 0):.0f}  心情 {growth.get('mood', 0):.0f}  "
                    f"体力 {growth.get('energy', 0):.0f}\n"
                    f"清洁 {growth.get('cleanliness', 0):.0f}  健康 {growth.get('health', 0):.0f}  "
                    f"好感 {growth.get('affection', 0):.0f}  经验 {growth.get('xp', 0)}"
                )
            if "timer_summary" in snapshot:
                home_timer.set(str(snapshot["timer_summary"]))
            settings = snapshot.get("settings")
            if isinstance(settings, dict):
                scale_value.set(float(settings.get("scale", 1.0)))
                speed_value.set(float(settings.get("animation_speed", 1.0)))
                bubble_speed.set(int(settings.get("bubble_speed", 18)))
                gravity.set(bool(settings.get("gravity", True)))
                collision.set(bool(settings.get("window_collision", True)))
                edge_snap.set(bool(settings.get("edge_snap", True)))
                alarm_sound.set(bool(settings.get("alarm_sound", True)))
                interaction_sound.set(bool(settings.get("interaction_sound", False)))
                reminder_sedentary.set(bool(settings.get("reminder_sedentary", True)))
                reminder_water.set(bool(settings.get("reminder_water", True)))
                reminder_eyes.set(bool(settings.get("reminder_eyes", True)))
                sedentary_minutes.set(str(settings.get("reminder_sedentary_minutes", 60)))
                water_minutes.set(str(settings.get("reminder_water_minutes", 70)))
                eye_minutes.set(str(settings.get("reminder_eyes_minutes", 45)))
                growth_tick_minutes.set(str(settings.get("growth_tick_minutes", 10)))
                natural_decay_multiplier.set(str(settings.get("natural_decay_multiplier", 2.0)))
                passive_energy_decay_per_hour.set(str(settings.get("passive_energy_decay_per_hour", 0.2)))
                exercise_energy_multiplier.set(str(settings.get("exercise_energy_multiplier", 2.0)))
                topmost.set(bool(settings.get("topmost", True)))
                click_through.set(bool(settings.get("click_through", False)))
                autostart.set(bool(settings.get("autostart", False)))
                ai_enabled.set(bool(settings.get("ai_enabled", False)))
                ai_base_url.set(str(settings.get("ai_base_url", "")))
                ai_model.set(str(settings.get("ai_model", "")))
                weather_enabled.set(bool(settings.get("weather_enabled", False)))
                if root.focus_get() is not weather_city_entry:
                    weather_city.set(str(settings.get("weather_city", "")))
                fullscreen_policy.set(str(settings.get("fullscreen_policy", "quiet")))
                custom_values = [
                    f"{item.get('name', '')}｜{item.get('target', '')}"
                    for item in settings.get("custom_tools", [])
                    if isinstance(item, dict)
                ]
                custom_list.configure(values=custom_values)
            monitor = snapshot.get("system")
            if isinstance(monitor, dict):
                battery_text = format_percent(monitor.get("battery_percent"))
                if monitor.get("charging") is True:
                    battery_text += " 充电中"
                download = monitor.get("download_kbps")
                upload = monitor.get("upload_kbps")
                network_text = "--" if download is None else f"↓{float(download):.0f} ↑{float(upload or 0):.0f} KB/s"
                system_text.set(
                    f"CPU {format_percent(monitor.get('cpu_percent'))}   内存 {format_percent(monitor.get('memory_percent'))}   "
                    f"电量 {battery_text}   网络 {network_text}   温度 {monitor.get('temperature', '系统未提供')}"
                )
            if "weather" in snapshot:
                weather_text.set(str(snapshot["weather"]))
            if "ai_history" in snapshot:
                ai_history.configure(state="normal")
                ai_history.delete("1.0", "end")
                ai_history.insert("end", str(snapshot["ai_history"]))
                ai_history.configure(state="disabled")
            if "timers" in snapshot:
                timer_tree.delete(*timer_tree.get_children())
                for timer in snapshot["timers"]:
                    import datetime as _dt
                    end_text = _dt.datetime.fromtimestamp(float(timer["ends_at"])).strftime("%m-%d %H:%M")
                    timer_tree.insert("", "end", iid=str(timer["id"]), values=(timer["title"], end_text))
            if "notes" in snapshot:
                note_tree.delete(*note_tree.get_children())
                note_cache = {str(note["id"]): note for note in snapshot["notes"]}
                for note in snapshot["notes"]:
                    import datetime as _dt
                    due = ""
                    if note.get("due_at"):
                        due = _dt.datetime.fromtimestamp(float(note["due_at"])).strftime("%m-%d %H:%M")
                    priority = ("低", "普通", "高")[max(0, min(2, int(note.get("priority", 1))))]
                    done = "完成" if note.get("completed") else "待办"
                    if note.get("deleted_at"):
                        done = "已删除"
                    note_tree.insert("", "end", iid=str(note["id"]), values=(done, note["title"], priority, due))
            if "message" in snapshot:
                apply_status.set(str(snapshot["message"]))

        def drain_updates() -> None:
            latest: dict[str, Any] | None = None
            while True:
                try:
                    latest = self.updates.get_nowait()
                except queue.Empty:
                    break
            if latest:
                if latest.get("shutdown"):
                    root.destroy()
                    self.root = None
                    return
                apply_snapshot(latest)
            root.after(250, drain_updates)

        root.protocol("WM_DELETE_WINDOW", root.withdraw)
        root.after(100, drain_updates)
