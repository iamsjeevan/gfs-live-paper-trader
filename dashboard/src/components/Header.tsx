import React from 'react';
import { TrendingUp, ShieldCheck, Flame, Cpu, RefreshCw } from 'lucide-react';

interface HeaderProps {
  market: 'INDIA' | 'US';
  setMarket: (m: 'INDIA' | 'US') => void;
  regime: string;
  leverage: number;
}

export const Header: React.FC<HeaderProps> = ({ market, setMarket, regime, leverage }) => {
  return (
    <header className="bg-slate-900/80 backdrop-blur-md border-b border-slate-800 sticky top-0 z-50 px-4 lg:px-8 py-4">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <Cpu className="w-6 h-6 text-slate-950 font-bold" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white tracking-tight flex items-center gap-2">
              QTDL-Momentum <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Vercel Forward Tester 2026</span>
            </h1>
            <p className="text-xs text-slate-400">Quality-Turnaround Dynamic Leverage Momentum Engine</p>
          </div>
        </div>

        {/* Dynamic Regime Badge */}
        <div className="flex items-center gap-3 bg-slate-800/80 border border-slate-700/60 rounded-xl px-4 py-2 text-xs">
          <div className="flex items-center gap-2">
            <Flame className="w-4 h-4 text-amber-400 animate-pulse" />
            <span className="text-slate-300 font-medium">Market Regime:</span>
            <span className="text-emerald-400 font-bold uppercase tracking-wider">{regime}</span>
          </div>
          <div className="h-4 w-[1px] bg-slate-700" />
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-cyan-400" />
            <span className="text-slate-300 font-medium">Active Leverage:</span>
            <span className="text-cyan-400 font-extrabold">{leverage}x</span>
          </div>
        </div>

        {/* Market Switcher */}
        <div className="flex items-center bg-slate-950 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setMarket('INDIA')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              market === 'INDIA'
                ? 'bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            🇮🇳 India NSE
          </button>
          <button
            onClick={() => setMarket('US')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              market === 'US'
                ? 'bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            🇺🇸 US Market
          </button>
        </div>
      </div>
    </header>
  );
};
