import React from 'react';
import { Calendar, CheckCircle, ShieldAlert, Sparkles, Milestone } from 'lucide-react';

export const ForwardTestingTracker: React.FC = () => {
  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Milestone className="w-5 h-5 text-cyan-400" />
          <h2 className="text-white font-bold text-base">1-Year Live Forward Testing Setup & Milestones</h2>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 font-bold">
          Target: Aug 2026 – Aug 2027
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Phase 1 */}
        <div className="bg-slate-950 p-5 rounded-xl border border-slate-800 relative">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-bold text-emerald-400">PHASE 1: MONTHS 1-3</span>
            <CheckCircle className="w-4 h-4 text-emerald-400" />
          </div>
          <h3 className="text-white font-bold text-sm mb-1">Emergency Fund & Small Capital Test</h3>
          <p className="text-xs text-slate-400 leading-relaxed mb-3">
            Keep 6 months emergency capital in <strong>Arbitrage Mutual Funds (7.2% P.A.)</strong>. Execute QTDL strategy on smaller capital size (₹1 Lakh) to get mentally comfortable with daily price swings.
          </p>
          <div className="text-[11px] text-emerald-300 bg-emerald-500/10 px-2.5 py-1 rounded-md border border-emerald-500/20 font-medium">
            Goal: Verify order execution & monthly rebalance discipline
          </div>
        </div>

        {/* Phase 2 */}
        <div className="bg-slate-950 p-5 rounded-xl border border-slate-800 relative">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-bold text-cyan-400">PHASE 2: MONTHS 4-8</span>
            <Sparkles className="w-4 h-4 text-cyan-400" />
          </div>
          <h3 className="text-white font-bold text-sm mb-1">Scale Up & 3-Tier Dynamic Leverage</h3>
          <p className="text-xs text-slate-400 leading-relaxed mb-3">
            Enable <strong>Zerodha MTF / LiquidCASE collateral pledge</strong>. Activate 3-Tier Dynamic Leverage (1.5x Bull / 1.25x Dip / 1.0x Bear) on Nifty 500 signals.
          </p>
          <div className="text-[11px] text-cyan-300 bg-cyan-500/10 px-2.5 py-1 rounded-md border border-cyan-500/20 font-medium">
            Goal: Compound returns while keeping emergency cash untouched
          </div>
        </div>

        {/* Phase 3 */}
        <div className="bg-slate-950 p-5 rounded-xl border border-slate-800 relative">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-bold text-purple-400">PHASE 3: MONTHS 9-12</span>
            <Calendar className="w-4 h-4 text-purple-400" />
          </div>
          <h3 className="text-white font-bold text-sm mb-1">Full 1-Year Forward Audit</h3>
          <p className="text-xs text-slate-400 leading-relaxed mb-3">
            Review 12-month forward performance against backtest CAGR (36.1% to 47.3%). Audit brokerage costs, tax drag, and winner retention rate.
          </p>
          <div className="text-[11px] text-purple-300 bg-purple-500/10 px-2.5 py-1 rounded-md border border-purple-500/20 font-medium">
            Goal: Full institutional review & long-term capital scale
          </div>
        </div>
      </div>
    </div>
  );
};
