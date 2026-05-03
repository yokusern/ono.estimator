"use client";

export function RSIGauge({ value }: { value: number }) {
  const rsi = value || 0;
  const isOverbought = rsi > 70;
  const isOversold = rsi < 30;
  const color = isOverbought ? "bg-rose-500" : isOversold ? "bg-sky-500" : "bg-sky-500";
  const textColor = isOverbought ? "text-rose-500" : isOversold ? "text-sky-500" : "text-slate-900";

  return (
    <div className="bg-white rounded-[40px] p-10 border border-slate-100/50 shadow-sm">
      <div className="flex items-center justify-between mb-6">
        <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Momentum Index</span>
        <span className={`text-2xl font-black ${textColor}`}>{rsi.toFixed(1)}</span>
      </div>
      <div className="h-4 w-full bg-slate-100 rounded-full overflow-hidden p-1">
        <div
          className={`h-full ${color} rounded-full shadow-[0_0_15px_rgba(14,165,233,0.4)] transition-all duration-700`}
          style={{ width: `${rsi}%` }}
        />
      </div>
      <div className="flex justify-between mt-2">
        <span className="text-[8px] font-black text-sky-400 uppercase tracking-widest">Oversold 30</span>
        <span className="text-[8px] font-black text-rose-400 uppercase tracking-widest">Overbought 70</span>
      </div>
    </div>
  );
}

export function TrendAlignment() {
  return (
    <div className="bg-sky-500 rounded-[40px] p-10 flex flex-col justify-center text-center shadow-xl shadow-sky-100">
      <span className="text-[10px] font-black uppercase tracking-[0.3em] text-sky-100 mb-2">Trend Alignment</span>
      <p className="text-2xl font-black text-white">CONFLUENCE ACTIVE</p>
    </div>
  );
}
