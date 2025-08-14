import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import subprocess, threading, time, queue, csv, os, math
from collections import deque, defaultdict
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

class MultiPingGUI:
    def __init__(self, root):
        root.title("Multi-Ping Grapher (Latency • Loss • Jitter)")
        root.geometry("1200x820")
        self.stop_event = threading.Event()
        self.q = queue.Queue()
        self.last_ts = 0.0
        self.max_points = 900
        self.lat_series = {}
        self.loss_series = {}
        self.jitter_series = {}
        self.prev_rtt = {}
        self.jitter_ewma = defaultdict(float)
        self.sent_counts = defaultdict(int)
        self.recv_counts = defaultdict(int)
        self.colors = {}
        self.csv_enabled = tk.BooleanVar(value=False)
        self.csv_path = tk.StringVar(value="")
        self.ipver = tk.StringVar(value="IPv4")
        self.interval = tk.DoubleVar(value=1.0)
        self.timeout = tk.IntVar(value=1000)
        self.size = tk.IntVar(value=32)
        self.window_loss = tk.IntVar(value=100)
        self.window_jitter = tk.IntVar(value=50)
        self.targets_text = tk.StringVar(value="8.8.8.8\n1.1.1.1")
        self.status = tk.StringVar(value="Stopped")
        self.dirty = False
        self._build_ui(root)
        root.after(300, self._drain_queue)

    def _build_ui(self, root):
        top = ttk.Frame(root, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Targets (one per line)").grid(row=0, column=0, sticky="w")
        tgt = tk.Text(top, height=6, width=44)
        tgt.insert("1.0", self.targets_text.get())
        tgt.grid(row=1, column=0, rowspan=5, sticky="nsew", padx=(0,8))
        self.targets_widget = tgt

        form = ttk.Frame(top)
        form.grid(row=0, column=1, rowspan=5, sticky="nsew")
        ttk.Label(form, text="Interval (s)").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.interval, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="Timeout (ms)").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.timeout, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Size (bytes)").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.size, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(form, text="Loss Window (probes)").grid(row=3, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.window_loss, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(form, text="Jitter Window (probes)").grid(row=4, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.window_jitter, width=8).grid(row=4, column=1, sticky="w")
        ttk.Label(form, text="IP Version").grid(row=5, column=0, sticky="w")
        ttk.Combobox(form, state="readonly", values=["IPv4","IPv6"], textvariable=self.ipver, width=8).grid(row=5, column=1, sticky="w")

        ctrls = ttk.Frame(top)
        ctrls.grid(row=0, column=2, rowspan=6, sticky="nsew", padx=(8,0))
        self.start_btn = ttk.Button(ctrls, text="Start", command=self.start)
        self.stop_btn = ttk.Button(ctrls, text="Stop", command=self.stop, state="disabled")
        self.clear_btn = ttk.Button(ctrls, text="Clear Graphs", command=self.clear_graphs)
        self.save_btn = ttk.Button(ctrls, text="Choose CSV...", command=self.choose_csv)
        ttk.Checkbutton(ctrls, text="Log to CSV", variable=self.csv_enabled).grid(row=0, column=0, sticky="w")
        self.save_btn.grid(row=1, column=0, sticky="we", pady=2)
        self.start_btn.grid(row=2, column=0, sticky="we", pady=2)
        self.stop_btn.grid(row=3, column=0, sticky="we", pady=2)
        self.clear_btn.grid(row=4, column=0, sticky="we", pady=2)
        ttk.Label(ctrls, textvariable=self.status).grid(row=5, column=0, sticky="w", pady=(8,0))

        main = ttk.Frame(root, padding=(8,0,8,8))
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.fig = plt.Figure(figsize=(10,6.6), dpi=100, constrained_layout=True)
        self.ax_latency = self.fig.add_subplot(3,1,1, label="ax_latency")
        self.ax_loss = self.fig.add_subplot(3,1,2, label="ax_loss", sharex=self.ax_latency)
        self.ax_jitter = self.fig.add_subplot(3,1,3, label="ax_jitter", sharex=self.ax_latency)
        self.ax_latency.set_ylabel("Latency (ms)")
        self.ax_latency.set_title("Latency")
        self.ax_loss.set_ylabel("Loss (%)")
        self.ax_loss.set_title("Packet Loss (windowed)")
        self.ax_jitter.set_ylabel("Jitter (ms)")
        self.ax_jitter.set_title("Jitter (EWMA of RTT delta)")
        self.ax_jitter.set_xlabel("Time (s)")
        self.canvas = FigureCanvasTkAgg(self.fig, master=main)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(root, padding=(8,0,8,8))
        bottom.pack(side=tk.BOTTOM, fill=tk.BOTH)
        self.stats_lbl = ttk.Label(bottom, text="Stats: —")
        self.stats_lbl.pack(anchor="w", pady=(0,4))
        ttk.Label(bottom, text="Log").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(bottom, height=8)
        self.log.pack(fill=tk.BOTH, expand=True)

    def choose_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], initialfile=f"ping_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        if path:
            self.csv_path.set(path)

    def clear_graphs(self):
        self.lat_series.clear(); self.loss_series.clear(); self.jitter_series.clear()
        self.prev_rtt.clear(); self.jitter_ewma.clear()
        self.sent_counts.clear(); self.recv_counts.clear()
        self.colors.clear()
        for ax in (self.ax_latency, self.ax_loss, self.ax_jitter):
            ax.cla()
        self.ax_latency.set_ylabel("Latency (ms)"); self.ax_latency.set_title("Latency")
        self.ax_loss.set_ylabel("Loss (%)"); self.ax_loss.set_title("Packet Loss (windowed)")
        self.ax_jitter.set_ylabel("Jitter (ms)"); self.ax_jitter.set_title("Jitter (EWMA of RTT delta)"); self.ax_jitter.set_xlabel("Time (s)")
        self.canvas.draw_idle()

    def start(self):
        tlist = [l.strip() for l in self.targets_widget.get("1.0", tk.END).splitlines() if l.strip()]
        if not tlist:
            self._log("Add at least one target.\n"); return
        try:
            iv = max(0.1, float(self.interval.get()))
            to = max(1, int(self.timeout.get()))
            sz = max(1, int(self.size.get()))
            _ = max(1, int(self.window_loss.get()))
            _ = max(1, int(self.window_jitter.get()))
        except:
            self._log("Invalid numeric value.\n"); return
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status.set("Running")
        for t in tlist:
            self.lat_series.setdefault(t, deque(maxlen=self.max_points))
            self.loss_series.setdefault(t, deque(maxlen=self.max_points))
            self.jitter_series.setdefault(t, deque(maxlen=self.max_points))
        threading.Thread(target=self._scheduler, args=(tlist, iv, to, sz), daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status.set("Stopped")

    def _scheduler(self, targets, interval, timeout_ms, size):
        next_run = time.time()
        while not self.stop_event.is_set():
            now = time.time()
            if now >= next_run:
                for t in targets:
                    threading.Thread(target=self._probe_once, args=(t, timeout_ms, size), daemon=True).start()
                next_run = now + interval
            if self.stop_event.wait(0.05):
                break

    def _probe_once(self, target, timeout_ms, size):
        self.sent_counts[target] += 1
        cmd = ["ping", target, "-n", "1", "-w", str(timeout_ms), "-l", str(size)]
        cmd.append("-6" if self.ipver.get() == "IPv6" else "-4")
        ts = time.time()
        try:
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = CREATE_NO_WINDOW
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                startupinfo=startupinfo, creationflags=creationflags
            )
            out = proc.stdout or proc.stderr
            rtt = self._parse_latency_ms(out)
            if rtt is not None:
                self.recv_counts[target] += 1
            self.q.put(("sample", target, ts, rtt, out.strip()))
        except Exception as e:
            self.q.put(("sample", target, ts, None, f"Error: {e}"))

    def _parse_latency_ms(self, ping_output):
        s = ping_output.lower()
        if "reply from" in s or "bytes from" in s or "respuesta desde" in s or "antwort von" in s:
            i = s.find("time=")
            if i >= 0:
                j = s.find("ms", i)
                if j > i:
                    val = s[i+5:j]
                    val = "".join(ch for ch in val if (ch.isdigit() or ch=="." or ch=="-"))
                    try: return float(val)
                    except: return None
        if "minimum" in s and "average" in s and "maximum" in s:
            for tok in s.split():
                if tok.endswith("ms"):
                    num = tok[:-2]
                    try:
                        f = float(num)
                        if f > 0: return f
                    except: pass
        return None

    def _drain_queue(self):
        updated = False
        try:
            while True:
                item = self.q.get_nowait()
                if not item: break
                kind = item[0]
                if kind == "sample":
                    _, target, ts, rtt, text = item
                    self._handle_sample(target, ts, rtt, text)
                    updated = True
        except queue.Empty:
            pass
        if updated:
            self.dirty = True
        self._redraw()
        self.canvas.get_tk_widget().after(300, self._drain_queue)

    def _handle_sample(self, target, ts, rtt, text):
        self.lat_series.setdefault(target, deque(maxlen=self.max_points))
        self.loss_series.setdefault(target, deque(maxlen=self.max_points))
        self.jitter_series.setdefault(target, deque(maxlen=self.max_points))
        if rtt is None:
            self.lat_series[target].append((ts, math.nan))
        else:
            self.lat_series[target].append((ts, rtt))
            prev = self.prev_rtt.get(target)
            if prev is not None:
                d = abs(rtt - prev)
                j = self.jitter_ewma[target] + (d - self.jitter_ewma[target]) / 16.0
                self.jitter_ewma[target] = j
                self.jitter_series[target].append((ts, j))
            else:
                self.jitter_series[target].append((ts, 0.0))
            self.prev_rtt[target] = rtt

        loss = self._compute_window_loss(target, max(1, int(self.window_loss.get())))
        self.loss_series[target].append((ts, loss))
        if self.csv_enabled.get() and self.csv_path.get():
            self._csv_write(target, ts, rtt, self.sent_counts[target], self.recv_counts[target], loss, self.jitter_ewma[target])
        tstamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        if rtt is None:
            self._log(f"[{tstamp}] {target} timeout\n")
        else:
            self._log(f"[{tstamp}] {target} {rtt:.2f} ms, jitter {self.jitter_ewma[target]:.2f} ms\n")

    def _compute_window_loss(self, target, window):
        lat = self.lat_series[target]
        if not lat: return 0.0
        n = min(window, len(lat))
        if n <= 0: return 0.0
        recent = list(lat)[-n:]
        misses = sum(1 for _, r in recent if (r is None or (isinstance(r, float) and (math.isnan(r)))))
        return 100.0 * misses / n

    def _csv_write(self, target, ts, rtt, sent, recv, loss, jitter):
        newfile = not os.path.exists(self.csv_path.get())
        try:
            with open(self.csv_path.get(), "a", newline="") as f:
                w = csv.writer(f)
                if newfile:
                    w.writerow(["timestamp_iso","epoch","target","rtt_ms","sent","recv","window_loss_pct","jitter_ms"])
                w.writerow([datetime.fromtimestamp(ts).isoformat(), f"{ts:.3f}", target, "" if rtt is None else f"{rtt:.3f}", sent, recv, f"{loss:.2f}", f"{jitter:.3f}"])
        except:
            pass

    def _redraw(self):
        t0 = time.time()
        if not self.dirty or (t0 - self.last_ts) < 0.5:
            return
        self.last_ts = t0
        self.dirty = False
        for ax in (self.ax_latency, self.ax_loss, self.ax_jitter):
            ax.cla()
        self.ax_latency.set_ylabel("Latency (ms)"); self.ax_latency.set_title("Latency")
        self.ax_loss.set_ylabel("Loss (%)"); self.ax_loss.set_title("Packet Loss (windowed)")
        self.ax_jitter.set_ylabel("Jitter (ms)"); self.ax_jitter.set_title("Jitter (EWMA of RTT delta)"); self.ax_jitter.set_xlabel("Time (s)")
        start = None
        for target in sorted(self.lat_series.keys()):
            self.colors.setdefault(target, None)
            lat = self.lat_series[target]
            if not lat: continue
            xs = [p[0] for p in lat]
            ys = [p[1] if (p[1] is not None and not (isinstance(p[1], float) and math.isnan(p[1]))) else float("nan") for p in lat]
            if start is None and xs: start = xs[0]
            xrel = [x - (start or xs[0]) for x in xs]
            line_lat, = self.ax_latency.plot(xrel, ys, label=target)
            if self.colors[target] is None:
                self.colors[target] = line_lat.get_color()
            loss = self.loss_series.get(target, [])
            if loss:
                xs2 = [p[0] for p in loss]
                xrel2 = [x - (start or xs2[0]) for x in xs2]
                ys2 = [p[1] for p in loss]
                self.ax_loss.plot(xrel2, ys2, label=f"{target} loss", color=self.colors[target])
            jit = self.jitter_series.get(target, [])
            if jit:
                xs3 = [p[0] for p in jit]
                xrel3 = [x - (start or xs3[0]) for x in xs3]
                ys3 = [p[1] for p in jit]
                self.ax_jitter.plot(xrel3, ys3, label=f"{target} jitter", color=self.colors[target])
        self.ax_latency.legend(loc="upper right", ncols=2 if len(self.lat_series) > 1 else 1, fontsize="small")
        self.ax_loss.legend(loc="upper right", ncols=2 if len(self.lat_series) > 1 else 1, fontsize="small")
        self.ax_jitter.legend(loc="upper right", ncols=2 if len(self.lat_series) > 1 else 1, fontsize="small")
        self.canvas.draw_idle()

    def _log(self, s):
        self.log.insert(tk.END, s)
        self.log.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    MultiPingGUI(root)
    root.mainloop()
